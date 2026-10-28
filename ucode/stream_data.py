"""Disk-backed source/QR indexes; caches never grow with the page count."""
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import tempfile
import shutil

from .config import QRFrame


def positive_count(value):
    if isinstance(value,bool) or not isinstance(value,int) or value<1:
        raise ValueError("Количество должно быть положительным целым числом")
    return value


@dataclass
class SourceInfo:
    count:int
    unique:int
    first:str
    last:str
    def __len__(self): return self.count
    def __getitem__(self,index):
        if index==0: return self.first
        if index in (-1,self.count-1): return self.last
        raise IndexError(index)


def inspect_codes(path,*,threshold=10000,generator="qr",cancel=None):
    from .batch import iter_codes,_check_cancel
    small=[]; first=last=None; count=0
    with tempfile.TemporaryDirectory(prefix="ucode-scan-") as temp:
        db=sqlite3.connect(str(Path(temp)/"scan.sqlite"))
        try:
            db.execute("PRAGMA cache_size=-2048"); db.execute("CREATE TABLE codes(value TEXT PRIMARY KEY)")
            for value in iter_codes(path,max_lines=None,max_bytes=None,generator=generator,cancel=cancel):
                count+=1; first=first or value; last=value
                if count<=threshold: small.append(value)
                db.execute("INSERT OR IGNORE INTO codes VALUES (?)",(value,))
                if count%1024==0:
                    db.commit(); _check_cancel(cancel)
                    if shutil.disk_usage(temp).free<256*1024**2: raise ValueError("Недостаточно места для индекса TXT")
            unique=db.execute("SELECT COUNT(*) FROM codes").fetchone()[0]
            return small if count<=threshold else SourceInfo(count,unique,first,last)
        except sqlite3.Error as exc: raise ValueError("Не удалось создать индекс TXT: "+str(exc)) from exc
        finally: db.close()


@dataclass
class CountPlan:
    input_records:int
    unique_values:int
    selected_count:int
    copies_per_value:int
    duplicate_policy:str
    types:tuple
    @property
    def selected_values(self): return range(self.selected_count)
    @property
    def duplicate_records(self): return self.input_records-self.unique_values
    @property
    def codes_per_type(self): return {kind:self.selected_count*self.copies_per_value for kind in self.types}
    @property
    def total_codes(self): return sum(self.codes_per_type.values())
    def to_dict(self):
        return dict(input_records=self.input_records,unique_values=self.unique_values,duplicate_records=self.duplicate_records,
                    selected_records=self.selected_count,copies_per_value=self.copies_per_value,
                    duplicate_policy=self.duplicate_policy,codes_per_type=self.codes_per_type,total_codes=self.total_codes,
                    basis="unique_values" if self.duplicate_policy=="unique" else "source_rows")


class DiskPlan:
    def __init__(self,path,source,*,copies=1,policy="preserve",cancel=None,guard=lambda:None,cache_mib=4):
        from .batch import iter_codes
        self.db=sqlite3.connect(str(path)); self.copies=positive_count(copies)
        if not isinstance(cache_mib,int) or not 1<=cache_mib<=1024: raise ValueError("Некорректный размер кэша SQLite")
        self.db.execute(f"PRAGMA cache_size={-cache_mib*1024}")
        self.db.executescript("CREATE TABLE codes(id INTEGER PRIMARY KEY,value TEXT UNIQUE,frame TEXT); CREATE TABLE rows(id INTEGER PRIMARY KEY,value TEXT)")
        n=0; first=last=None
        try:
            for value in iter_codes(source,max_lines=None,max_bytes=None,cancel=cancel):
                n+=1; first=first or value; last=value
                cur=self.db.execute("INSERT OR IGNORE INTO codes(value) VALUES (?)",(value,))
                if policy=="preserve" or cur.rowcount:
                    self.db.execute("INSERT INTO rows(value) VALUES (?)",(value,))
                if n%256==0: self.db.commit(); guard()
            unique=self.db.execute("SELECT COUNT(*) FROM codes").fetchone()[0]
            selected=self.db.execute("SELECT COUNT(*) FROM rows").fetchone()[0]
            self.plan=CountPlan(n,unique,selected,self.copies,policy,("qr",))
            self.first,self.last=first,last
            self.db.commit()
        except BaseException: self.close(); raise
    def close(self): self.db.close()
    def values(self): return UniqueValues(self)
    def frames(self): return DiskFrames(self)


class UniqueValues:
    def __init__(self,plan): self.plan=plan
    def __len__(self): return self.plan.plan.unique_values
    def __iter__(self):
        for row in self.plan.db.execute("SELECT value FROM codes ORDER BY id"): yield row[0]
    def __getitem__(self,index):
        if isinstance(index,slice):
            start,stop,step=index.indices(len(self))
            return [row[0] for row in self.plan.db.execute("SELECT value FROM codes WHERE id>? AND id<=? ORDER BY id",(start,stop))][::step]
        raise TypeError("Use bounded slices")


class FrameStore:
    def __init__(self,plan): self.plan=plan; self.pending=0
    def __setitem__(self,index,frames):
        self.plan.db.executemany("UPDATE codes SET frame=? WHERE value=?",((json.dumps(frame.to_dict()),frame.payload) for frame in frames))
        self.pending+=len(frames)
        if self.pending>=256: self.plan.db.commit(); self.pending=0
    def finish(self):
        self.plan.db.commit()
        return self.plan.frames()


class DiskFrames:
    def __init__(self,plan): self.plan=plan
    def __len__(self): return self.plan.plan.total_codes
    def __iter__(self):
        for value,raw in self.plan.db.execute("SELECT rows.value,codes.frame FROM rows JOIN codes ON codes.value=rows.value ORDER BY rows.id"):
            frame=QRFrame.from_dict(json.loads(raw))
            for _ in range(self.plan.copies): yield frame
    def __getitem__(self,index):
        if index<0: index+=len(self)
        if not 0<=index<len(self): raise IndexError(index)
        raw=self.plan.db.execute("SELECT codes.frame FROM rows JOIN codes ON codes.value=rows.value WHERE rows.id=?",(index//self.plan.copies+1,)).fetchone()[0]
        return QRFrame.from_dict(json.loads(raw))
