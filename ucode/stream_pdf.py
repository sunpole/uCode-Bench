"""Incremental PDF objects and disk xref/page indexes; bounded independent QA reader."""
import io
from pathlib import Path
import sqlite3
import zlib

from .compact_pdf import _number,_rectangles


def write_pdf(frames,path,settings,index_path,*,cancel=None,on_progress=None,guard=lambda:None,prepared=None):
    count=len(frames); db=sqlite3.connect(str(index_path))
    db.execute("PRAGMA cache_size=-2048")
    db.executescript("CREATE TABLE objects(id INTEGER PRIMARY KEY,off INTEGER,size INTEGER); CREATE TABLE pages(n INTEGER PRIMARY KEY,ref INTEGER); CREATE TABLE meta(key TEXT PRIMARY KEY,value INTEGER); CREATE TABLE contents(value TEXT PRIMARY KEY,ref INTEGER)")
    unit=settings.module_mm*72/25.4; side=_number((21+2*settings.quiet_modules)*unit)
    def check():
        if cancel is not None and cancel.is_set(): raise InterruptedError("Запись PDF остановлена")
        guard()
    try:
        with Path(path).open("xb") as out:
            out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
            def obj(ident,body):
                offset=out.tell(); raw=f"{ident} 0 obj\n".encode()+body+b"\nendobj\n"
                out.write(raw); db.execute("INSERT INTO objects VALUES (?,?,?)",(ident,offset,len(raw)))
            obj(1,b"<< /Type /Catalog /Pages 2 0 R >>")
            obj(3,b"<< /Creator (uCode DiskPDF/1) >>")
            next_id=4
            saved=0
            source=((n,frame.payload,frame,None) for n,frame in enumerate(frames,1)) if prepared is None else ((n,payload,None,data) for n,payload,data in prepared)
            for number,payload,frame,data in source:
                check()
                if not 1<=number<=count: raise ValueError("Номер страницы вне тиража")
                if frame is not None and (frame.version!=1 or frame.error!="M" or frame.size!=21 or any(len(row)!=21 for row in frame.matrix)):
                    raise ValueError("Только QR V1-M")
                cached=db.execute("SELECT ref FROM contents WHERE value=?",(payload,)).fetchone() if settings.pdf_profile=="compact" else None
                content=cached[0] if cached else next_id
                if not cached:
                    if data is None:
                        lines=[" ".join(_number(v/100,9) for v in settings.ink)+" k\nn\n"]
                        rects=_rectangles(frame.matrix) if settings.pdf_profile=="compact" else ((x,y,1,1) for y,row in enumerate(reversed(frame.matrix)) for x,dark in enumerate(row) if dark)
                        for x,y,w,h in rects:
                            lines.append(f"{_number((x+settings.quiet_modules)*unit)} {_number((y+settings.quiet_modules)*unit)} {_number(w*unit)} {_number(h*unit)} re\n")
                        data=zlib.compress(("".join(lines)+"f\n").encode())
                    obj(content,f"<< /Length {len(data)} /Filter /FlateDecode >>\nstream\n".encode()+data+b"\nendstream")
                    db.execute("INSERT OR IGNORE INTO contents VALUES (?,?)",(payload,content))
                    next_id+=1
                page=next_id; next_id+=1
                geometry=f" /MediaBox [0 0 {side} {side}] /Resources << >>" if prepared is None else ""
                obj(page,f"<< /Type /Page /Parent 2 0 R{geometry} /Contents {content} 0 R >>".encode())
                db.execute("INSERT INTO pages VALUES (?,?)",(number,page))
                saved+=1
                if saved%256==0: db.commit()
                if on_progress: on_progress(saved,count)
            if saved!=count: raise ValueError("Количество записанных страниц не совпало с планом")
            offset=out.tell()
            prefix=f"2 0 obj\n<< /Type /Pages /Count {count} /Kids [".encode(); out.write(prefix)
            for ref, in db.execute("SELECT ref FROM pages ORDER BY n"):
                check(); out.write(f"{ref} 0 R ".encode())
            ending=f"] /MediaBox [0 0 {side} {side}] /Resources << >> >>\nendobj\n".encode() if prepared is not None else b"] >>\nendobj\n"
            out.write(ending); db.execute("INSERT INTO objects VALUES (2,?,?)",(offset,out.tell()-offset))
            check(); xref=out.tell(); size=next_id
            out.write(f"xref\n0 {size}\n0000000000 65535 f \n".encode())
            for ident,offset in db.execute("SELECT id,off FROM objects ORDER BY id"):
                check()
                if offset>=10**10: raise ValueError("Файл превысил формат classic PDF xref (10 ГБ), частичный файл сохранён")
                out.write(f"{offset:010d} 00000 n \n".encode())
            out.write(f"trailer\n<< /Size {size} /Root 1 0 R /Info 3 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
            db.executemany("INSERT INTO meta VALUES (?,?)",(("count",count),("xref",xref),("size",size)))
            db.execute("INSERT INTO meta VALUES ('inherited_geometry',?)",(int(prepared is not None),))
            db.commit()
    finally: db.close()


class DiskReader:
    """Parse final PDF bytes with pypdf, resolving one indexed object at a time.

    The final xref, root Kids order/count and trailer are independently reread;
    the saved index alone cannot turn a damaged PDF into PASS.
    """
    strict=True
    is_encrypted=False
    bounded_pages=True
    def __init__(self,path,index_path,*,cancel=None,guard=lambda:None):
        self.path=Path(path); self.index_path=index_path; self.cancel=cancel; self.guard=guard
        self.db=sqlite3.connect(f"{Path(index_path).resolve().as_uri()}?mode=ro",uri=True)
        self.db.execute("PRAGMA cache_size=-2048")
        self.meta=dict(self.db.execute("SELECT key,value FROM meta"))
        self.pages=self
        try: self.validate()
        except BaseException: self.close(); raise
    def close(self): self.db.close()
    def check(self):
        if self.cancel is not None and self.cancel.is_set(): raise InterruptedError("Проверка PDF остановлена")
        self.guard()
    def validate(self):
        with self.path.open("rb") as stream:
            if stream.read(9)!=b"%PDF-1.4\n": raise ValueError("PDF header повреждён")
            stream.seek(self.meta["xref"])
            if stream.readline()!=b"xref\n" or stream.readline()!=f"0 {self.meta['size']}\n".encode() or stream.readline()!=b"0000000000 65535 f \n":
                raise ValueError("PDF xref повреждён")
            for ident,offset in self.db.execute("SELECT id,off FROM objects ORDER BY id"):
                self.check()
                if stream.readline()!=f"{offset:010d} 00000 n \n".encode(): raise ValueError("PDF xref не совпадает с объектами")
            expected=f"trailer\n<< /Size {self.meta['size']} /Root 1 0 R /Info 3 0 R >>\nstartxref\n{self.meta['xref']}\n%%EOF\n".encode()
            if stream.read(len(expected)+1)!=expected: raise ValueError("PDF trailer повреждён")
            offset=self.db.execute("SELECT off FROM objects WHERE id=2").fetchone()[0]; stream.seek(offset)
            prefix=f"2 0 obj\n<< /Type /Pages /Count {len(self)} /Kids [".encode()
            if stream.read(len(prefix))!=prefix: raise ValueError("PDF page tree повреждён")
            for ref, in self.db.execute("SELECT ref FROM pages ORDER BY n"):
                self.check(); expected=f"{ref} 0 R ".encode()
                if stream.read(len(expected))!=expected: raise ValueError("PDF page order повреждён")
            if self.meta.get("inherited_geometry"):
                # Parent geometry is parsed independently below, not trusted from the index.
                tail=stream.readline()
                if not tail.startswith(b"] /MediaBox [") or not tail.endswith(b" /Resources << >> >>\n") or stream.readline()!=b"endobj\n":
                    raise ValueError("PDF parent geometry повреждена")
                from pypdf.generic import read_object
                self.inherited=read_object(io.BytesIO(b"<< "+tail[2:]),self)
                ending=b""
            else: ending=b"] >>\nendobj\n"
            if stream.read(len(ending))!=ending: raise ValueError("PDF page tree завершён неверно")
        catalog=self.get_object_id(1)
        if str(catalog.get("/Type"))!="/Catalog" or catalog.raw_get("/Pages").idnum!=2: raise ValueError("Неверный PDF catalog")
    def __len__(self): return self.meta["count"]
    def __iter__(self):
        for index in range(len(self)): yield self[index]
    def __getitem__(self,index):
        from pypdf._page import PageObject
        from pypdf.generic import IndirectObject
        self.check()
        ref=self.db.execute("SELECT ref FROM pages WHERE n=?",(index+1,)).fetchone()[0]
        indirect=IndirectObject(ref,0,self)
        raw=self.get_object(indirect)
        if str(raw.get("/Type"))!="/Page" or raw.raw_get("/Parent").idnum!=2: raise ValueError("Неверная ссылка страницы PDF")
        page=PageObject(self,indirect); page.update(raw)
        if self.meta.get("inherited_geometry"):
            from pypdf.generic import NameObject
            for name in ("/MediaBox","/Resources"):
                if name not in page: page[NameObject(name)]=self.inherited[name]
        return page
    def get_object(self,ref): return self.get_object_id(ref.idnum)
    def get_object_id(self,ident):
        from pypdf.generic import read_object
        self.check()
        offset,size=self.db.execute("SELECT off,size FROM objects WHERE id=?",(ident,)).fetchone()
        if size>128*1024: raise ValueError("Неожиданно большой объект PDF")
        with self.path.open("rb") as stream:
            stream.seek(offset); raw=stream.read(size)
        prefix=f"{ident} 0 obj\n".encode()
        if not raw.startswith(prefix) or not raw.endswith(b"\nendobj\n"): raise ValueError("PDF object повреждён")
        return read_object(io.BytesIO(raw[len(prefix):]),self)
