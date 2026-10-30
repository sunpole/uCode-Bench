"""Small streaming PDF 1.4 writer: CMYK rectangle paths, shared document data.

No fonts, images, transforms or Forms. The existing independent QA parser can
validate the exact same supported operators, without relaxed checks.
"""
import math
from pathlib import Path
import zlib


def _number(value, precision=5):
    return f"{value:.{precision}f}".rstrip("0").rstrip(".") or "0"


def _rectangles(matrix):
    active={}; result=[]
    for y,row in enumerate(reversed(matrix)):
        runs=[]; x=0
        while x<21:
            if not row[x]: x+=1; continue
            start=x
            while x<21 and row[x]: x+=1
            runs.append((start,x-start))
        current={}
        for run in runs:
            old=active.get(run)
            current[run]=(old[0],old[1],old[2],old[3]+1) if old else (run[0],y,run[1],1)
        result.extend(rect for run,rect in active.items() if run not in current)
        active=current
    result.extend(active.values())
    return result


def write_pdf(frames,path,config,*,on_progress=None,cancel=None):
    if not 1<=len(frames)<=10000:
        raise ValueError("Compact PDF supports 1..10000 pages")
    unit=float(config.module_mm)*72/25.4
    quiet=config.quiet_modules
    if not math.isfinite(unit) or unit<=0 or not isinstance(quiet,int) or quiet<4:
        raise ValueError("Invalid QR print geometry")
    ink=tuple(getattr(config,"ink",(0,0,0,100)))
    if len(ink)!=4 or any(not math.isfinite(v) or not 0<=v<=100 for v in ink):
        raise ValueError("Invalid CMYK")
    cells=21+2*quiet
    grid=[_number(index*unit) for index in range(cells+1)]
    side=grid[-1]
    offsets=[0]*7; pages=[]; matrices={}; identities={}
    def stopped():
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Запись компактного PDF остановлена; частичный файл сохранён")
    stopped()
    with Path(path).open("xb") as stream:
        stream.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        def allocate():
            offsets.append(0); return len(offsets)-1
        def obj(ident,body):
            offsets[ident]=stream.tell()
            stream.write(f"{ident} 0 obj\n".encode()+body+b"\nendobj\n")
        def content(ident,data,compress=False):
            if compress: data=zlib.compress(data)
            flags=b" /Filter /FlateDecode" if compress else b""
            obj(ident,b"<< /Length "+str(len(data)).encode()+flags+b" >>\nstream\n"+data+b"\nendstream")
        obj(3,b"<< >>")
        from .print_background import background_operators
        content(4,(background_operators(config,side)+" ".join(_number(value/100,9) for value in ink)+" k\nn\n").encode())
        content(5,b"f\n")
        obj(6,f"<< /Creator (uCode CompactPDF/1) /Title (uCode QR {len(frames)}) >>".encode())
        for index,frame in enumerate(frames,1):
            stopped()
            cached=identities.get(id(frame))
            if cached is not None:
                reference=cached[1]
            else:
                if frame.version!=1 or frame.error not in ("L","M","Q","H") or len(frame.matrix)!=21 or any(len(row)!=21 for row in frame.matrix):
                    raise ValueError("Only ordinary QR V1 L/M/Q/H frames are supported")
                matrix=frame.matrix if isinstance(frame.matrix,tuple) and all(isinstance(row,tuple) for row in frame.matrix) else tuple(tuple(bool(cell) for cell in row) for row in frame.matrix)
                reference=matrices.get(matrix)
                if reference is None:
                    lines=[f"{grid[x+quiet]} {grid[y+quiet]} {grid[width]} {grid[height]} re\n"
                           for x,y,width,height in _rectangles(matrix)]
                    reference=allocate(); content(reference,"".join(lines).encode(),True)
                    matrices[matrix]=reference
                identities[id(frame)]=(frame,reference)
            page=allocate(); pages.append(page)
            obj(page,f"<< /Type /Page /Parent 2 0 R /Contents [4 0 R {reference} 0 R 5 0 R] >>".encode())
            if on_progress: on_progress(index,len(frames))
        kids=" ".join(f"{page} 0 R" for page in pages)
        obj(2,f"<< /Type /Pages /Count {len(pages)} /Kids [{kids}] /MediaBox [0 0 {side} {side}] /Resources 3 0 R >>".encode())
        obj(1,b"<< /Type /Catalog /Pages 2 0 R >>")
        stopped()
        xref=stream.tell()
        stream.write(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
        for offset in offsets[1:]:
            if not offset or offset>=10000000000: raise ValueError("Invalid classic PDF xref offset")
            stream.write(f"{offset:010d} 00000 n \n".encode())
        stream.write(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
