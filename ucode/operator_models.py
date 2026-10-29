"""Bounded operator models, independent of Tk and benchmark timing contracts."""
from dataclasses import dataclass
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import uuid

from .stream_data import SourceInfo, positive_count


def ungroup(value):
    return re.sub(r'[\s\u00a0\u202f]', '', str(value))


def parse_number(value, *, integer=False):
    raw=ungroup(value).replace(',','.')
    try:
        if integer:
            if not re.fullmatch(r'[+-]?\d+',raw): raise ValueError()
            return int(raw)
        number=float(raw)
        if not math.isfinite(number): raise ValueError()
        return number
    except (TypeError,ValueError,OverflowError) as exc:
        raise ValueError('Введите целое число' if integer else 'Введите число') from exc


def grouped_number(value):
    raw=ungroup(value)
    match=re.fullmatch(r'([+-]?)(\d*)([.,]\d*)?',raw)
    if not match: return str(value)
    return match[1]+re.sub(r'\B(?=(\d{3})+(?!\d))',' ',match[2])+(match[3] or '')


@dataclass(frozen=True)
class SequenceSpec:
    start:str
    count:int
    step:int=1

    def __post_init__(self):
        raw=ungroup(self.start)
        if not re.fullmatch(r'[0-9]{1,12}',raw): raise ValueError('Начальный номер: от 1 до 12 цифр')
        positive_count(self.count);positive_count(self.step)
        object.__setattr__(self,'start',raw.zfill(12))
        if int(raw)+(self.count-1)*self.step>999999999999:
            raise ValueError('Последний номер выходит за пределы 12 цифр')

    @property
    def first(self): return self.start
    @property
    def last(self): return self.value(self.count)
    def value(self,row):
        if not 1<=row<=self.count: raise IndexError(row)
        return f'{int(self.start)+(row-1)*self.step:012d}'

    def save(self,path,*,cancel=None,progress=None):
        path=Path(path)
        parent=path.parent.resolve()
        if not parent.is_dir(): raise ValueError('Папка TXT не существует')
        required=self.count*13+16*1024**2
        if shutil.disk_usage(parent).free<required: raise ValueError('Недостаточно места для TXT')
        with path.open('x',encoding='utf-8',newline='\n') as stream:
            for index in range(self.count):
                if index%1024==0:
                    if cancel is not None and cancel.is_set(): raise InterruptedError('Создание TXT остановлено; частичный файл сохранён')
                    if progress: progress(index,self.count)
                    if shutil.disk_usage(parent).free<16*1024**2: raise ValueError('Заканчивается место для TXT')
                stream.write(f'{int(self.start)+index*self.step:012d}\n')
        if progress: progress(self.count,self.count)
        return path


@dataclass
class SourceIndex(SourceInfo):
    source:Path
    database:Path
    sha256:str
    source_size:int
    source_mtime_ns:int

    @classmethod
    def build(cls,source,cache,*,cancel=None,progress=None):
        from .batch import iter_codes
        source=Path(source).resolve();before=source.stat()
        cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
        database=cache/('source-'+uuid.uuid4().hex+'.sqlite')
        db=sqlite3.connect(database)
        digest=hashlib.sha256();count=0;first=last=''
        try:
            db.execute('PRAGMA cache_size=-4096');db.execute('PRAGMA temp_store=FILE')
            db.execute('CREATE TABLE codes(n INTEGER PRIMARY KEY,value TEXT NOT NULL)')
            for value in iter_codes(source,max_lines=None,max_bytes=None,cancel=cancel):
                count+=1;first=first or value;last=value
                db.execute('INSERT INTO codes VALUES (?,?)',(count,value))
                if count%2048==0:
                    db.commit()
                    if cancel is not None and cancel.is_set(): raise InterruptedError('Загрузка базы остановлена')
                    if shutil.disk_usage(cache).free<256*1024**2: raise ValueError('Недостаточно места для индекса базы')
                    if progress: progress(count,before.st_size)
            db.execute('CREATE INDEX value_lookup ON codes(value)');db.commit()
            unique=db.execute('SELECT COUNT(DISTINCT value) FROM codes').fetchone()[0]
            with source.open('rb') as stream:
                while chunk:=stream.read(1024*1024):
                    if cancel is not None and cancel.is_set(): raise InterruptedError('Загрузка базы остановлена')
                    digest.update(chunk)
            after=source.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                raise ValueError('TXT изменился во время загрузки; откройте его заново')
            return cls(count,unique,first,last,source,database,digest.hexdigest(),after.st_size,after.st_mtime_ns)
        finally: db.close()

    def unchanged(self):
        try:
            stat=self.source.stat()
            return (stat.st_size,stat.st_mtime_ns)==(self.source_size,self.source_mtime_ns)
        except OSError: return False

    def verify_content(self):
        if not self.unchanged(): return False
        digest=hashlib.sha256()
        with self.source.open('rb') as stream:
            while chunk:=stream.read(1024*1024): digest.update(chunk)
        return digest.hexdigest()==self.sha256

    def row(self,number):
        if not isinstance(number,int) or not 1<=number<=self.count: raise IndexError(number)
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute('SELECT value FROM codes WHERE n=?',(number,)).fetchone()[0]

    def rows(self,start,limit=60):
        if not isinstance(start,int) or start<1 or not isinstance(limit,int) or not 1<=limit<=200:
            raise ValueError('Недопустимый диапазон строк')
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute('SELECT n,value FROM codes WHERE n>=? ORDER BY n LIMIT ?',(start,limit)).fetchall()

    def find(self,text,*,cancel=None):
        if not text: return []
        with closing(sqlite3.connect(self.database)) as db:
            if cancel is not None: db.set_progress_handler(lambda:int(cancel.is_set()),1000)
            try: return db.execute('SELECT n,value FROM codes WHERE instr(value,?)>0 ORDER BY n LIMIT 3',(str(text),)).fetchall()
            except sqlite3.OperationalError:
                if cancel is not None and cancel.is_set(): return []
                raise


@dataclass(frozen=True)
class SpaceEstimate:
    pdf_bytes:int
    temporary_bytes:int
    required_bytes:int
    free_bytes:int
    reserve_bytes:int
    @property
    def enough(self): return self.free_bytes>=self.required_bytes


def estimate_space(count,mode,sample_page_bytes,free_bytes,*,temp_bytes=None,
                   reports_bytes=16*1024**2,allocation_unit=4096):
    positive_count(count);positive_count(sample_page_bytes);positive_count(allocation_unit)
    if mode not in ('multipage','singles','both'): raise ValueError('Выберите формат PDF')
    if not isinstance(free_bytes,int) or free_bytes<0: raise ValueError('Свободное место неизвестно')
    if temp_bytes is None: temp_bytes=count*4096
    if temp_bytes<0 or reports_bytes<0: raise ValueError('Некорректная оценка временных файлов')
    round_up=lambda n: ((n+allocation_unit-1)//allocation_unit)*allocation_unit
    pdf=round_up(count*sample_page_bytes) if mode!='singles' else 0
    if mode in ('singles','both'): pdf+=count*round_up(sample_page_bytes)
    reserve=max(2*1024**3,math.ceil(free_bytes*.1))
    return SpaceEstimate(pdf,temp_bytes,4*(pdf+temp_bytes+reports_bytes)+reserve,free_bytes,reserve)


class JobApproval:
    def __init__(self): self.signature=None;self.required=0;self.directory=None
    @staticmethod
    def key(order):
        return hashlib.sha256(json.dumps(order,sort_keys=True,ensure_ascii=False,default=str).encode('utf-8')).hexdigest()
    def approve(self,order,directory,required):
        self.signature=self.key(order);self.directory=str(Path(directory).resolve());self.required=required
    def valid(self,order,directory,free):
        return self.signature==self.key(order) and self.directory==str(Path(directory).resolve()) and free>=self.required
    def invalidate(self): self.signature=None
