"""Local, static QR payloads. No uploads, redirects or network requests."""
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote,urlencode,urlsplit,urlunsplit
import uuid

from .stream_data import SourceInfo

KINDS={
 'text':('Текст',[('text','Текст','textarea')]),
 'url':('Ссылка',[('url','Адрес https://…','url')]),
 'email':('E-mail',[('email','Адрес получателя','email'),('subject','Тема','text'),('message','Сообщение','textarea')]),
 'phone':('Телефон',[('phone','Номер с кодом страны','tel')]),
 'sms':('SMS',[('phone','Номер с кодом страны','tel'),('message','Сообщение','textarea')]),
 'contact':('Контакт',[('given','Имя','text'),('family','Фамилия','text'),('phone','Телефон','tel'),('email','E-mail','email'),('company','Организация','text'),('title','Должность','text'),('url','Сайт','url'),('address','Адрес','text'),('note','Примечание','textarea')]),
 'wifi':('Wi-Fi',[('ssid','Название сети (SSID)','text'),('security','Защита','security'),('password','Пароль','password'),('hidden','Скрытая сеть','checkbox')]),
 'whatsapp':('WhatsApp',[('phone','Номер с кодом страны','tel'),('message','Сообщение','textarea')]),
 'pdf':('PDF по ссылке',[('url','Публичная ссылка на PDF','url')]),
 'images':('Изображения по ссылке',[('url','Публичная ссылка на изображение или галерею','url')]),
 'video':('Видео по ссылке',[('url','Публичная ссылка на видео','url')]),
 'app':('Приложение по ссылке',[('url','Ссылка на страницу приложения','url')]),
 'social':('Соцсеть по ссылке',[('url','Ссылка на профиль или готовую страницу ссылок','url')]),
 'event':('Событие',[('title','Название','text'),('start','Начало — местное время','datetime-local'),('end','Окончание — местное время','datetime-local'),('location','Место','text'),('description','Описание','textarea')]),
 'geo':('Координаты',[('latitude','Широта','text'),('longitude','Долгота','text')]),
}

def single(value):
    value=str(value).strip()
    if any(c in value for c in '\r\n\x00'):raise ValueError('Однострочное поле содержит перевод строки')
    return value

def phone(value):
    value=re.sub(r'[ ()-]','',single(value))
    if not re.fullmatch(r'\+?[0-9]{7,15}',value):raise ValueError('Телефон: 7–15 цифр, возможен + в начале')
    return value

def email(value):
    value=single(value)
    if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',value):raise ValueError('Проверьте адрес e-mail')
    return value

def url(value):
    value=single(value);parsed=urlsplit(value)
    if parsed.scheme.lower() not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Нужна готовая http:// или https:// ссылка без логина и пароля')
    if any(c.isspace() for c in value):raise ValueError('В ссылке не должно быть пробелов')
    if re.search(r'%(?![0-9a-fA-F]{2})',value):raise ValueError('Некорректное %-кодирование ссылки')
    host=parsed.hostname.encode('idna').decode('ascii')
    if ':' in host:host='['+host+']'
    if parsed.port:host+=':'+str(parsed.port)
    return urlunsplit((parsed.scheme.lower(),host,quote(parsed.path,safe='/%:@!$&\'()*+,;=-._~'),quote(parsed.query,safe='/%?:@!$&\'()*+,;=-._~'),quote(parsed.fragment,safe='/%?:@!$&\'()*+,;=-._~')))

def escaped(value):return str(value).replace('\\','\\\\').replace('\r\n','\n').replace('\r','\n').replace('\n','\\n').replace(';','\\;').replace(',','\\,')

def folded(lines):
    result=[]
    for line in lines:
        part=''
        for char in line:
            if len((part+char).encode('utf-8'))>75:result.append(part);part=' '
            part+=char
        result.append(part)
    return '\r\n'.join(result)+'\r\n'

def build_payload(kind,fields):
    if kind not in KINDS:raise ValueError('Неизвестный вид содержимого QR')
    if not isinstance(fields,dict):raise ValueError('Нужны поля содержимого')
    v=lambda key: str(fields.get(key,''))
    if kind=='text':payload=v('text')
    elif kind in ('url','pdf','images','video','app','social'):payload=url(v('url'))
    elif kind=='phone':payload='tel:'+phone(v('phone'))
    elif kind=='sms':payload='SMSTO:'+phone(v('phone'))+':'+v('message')
    elif kind=='email':
        payload='mailto:'+quote(email(v('email')),safe='@.+')
        query={k:val for k,val in [('subject',v('subject')),('body',v('message'))] if val}
        if query:payload+='?'+urlencode(query,quote_via=quote)
    elif kind=='whatsapp':
        number=phone(v('phone')).lstrip('+');payload='https://wa.me/'+number
        if v('message'):payload+='?'+urlencode({'text':v('message')},quote_via=quote)
    elif kind=='wifi':
        ssid=v('ssid');security=v('security') or 'WPA'
        if not ssid or len(ssid.encode('utf-8'))>32:raise ValueError('SSID Wi-Fi: от 1 до 32 байт UTF-8')
        if any(c in ssid+v('password') for c in '\r\n\x00'):raise ValueError('SSID и пароль Wi-Fi не должны содержать переводы строк или NUL')
        if security not in ('WPA','WEP','nopass'):raise ValueError('Wi-Fi: WPA/WPA2, WEP или без пароля')
        if security!='nopass' and not v('password'):raise ValueError('Укажите пароль Wi-Fi')
        def w(text):
            for char in ('\\',';',',',':','"'):text=text.replace(char,'\\'+char)
            return text
        payload=f'WIFI:T:{security};S:{w(ssid)};P:{w(v("password")) if security!="nopass" else ""};H:{"true" if fields.get("hidden") is True else "false"};;'
    elif kind=='contact':
        given=single(v('given'));family=single(v('family'))
        if not given and not family:raise ValueError('Укажите имя или фамилию контакта')
        lines=['BEGIN:VCARD','VERSION:3.0','N:'+escaped(family)+';'+escaped(given)+';;;','FN:'+escaped((given+' '+family).strip())]
        for key,tag,validate in [('phone','TEL',phone),('email','EMAIL',email),('company','ORG',single),('title','TITLE',single),('url','URL',url),('note','NOTE',str)]:
            if v(key):lines.append(tag+':'+(validate(v(key)) if tag=='URL' else escaped(validate(v(key)))))
        if v('address'):lines.append('ADR:;;'+escaped(single(v('address')))+';;;;')
        payload=folded(lines+['END:VCARD'])
    elif kind=='event':
        title=single(v('title'))
        if not title:raise ValueError('Укажите название события')
        try:start=datetime.fromisoformat(v('start'));end=datetime.fromisoformat(v('end'))
        except ValueError:raise ValueError('Укажите начало и окончание события')
        if start.tzinfo or end.tzinfo or end<=start:raise ValueError('Окончание должно быть после начала; время — местное без часового пояса')
        uid=hashlib.sha256(json.dumps(fields,sort_keys=True,ensure_ascii=False).encode()).hexdigest()+'@ucode.local'
        payload=folded(['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//uCode//Local QR//RU','BEGIN:VEVENT','UID:'+uid,
                       'DTSTAMP:'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'DTSTART:'+start.strftime('%Y%m%dT%H%M%S'),
                       'DTEND:'+end.strftime('%Y%m%dT%H%M%S'),'SUMMARY:'+escaped(title),'LOCATION:'+escaped(v('location')),
                       'DESCRIPTION:'+escaped(v('description')),'END:VEVENT','END:VCALENDAR'])
    else:
        try:latitude=float(v('latitude'));longitude=float(v('longitude'))
        except ValueError:raise ValueError('Координаты должны быть числами с точкой')
        if not -90<=latitude<=90 or not -180<=longitude<=180:raise ValueError('Координаты вне допустимого диапазона')
        payload=f'geo:{latitude:g},{longitude:g}'
    if not payload or '\x00' in payload:raise ValueError('Содержимое пустое или содержит NUL')
    limit=7089 if payload.isascii() and payload.isdigit() else 4296 if all(c in '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:' for c in payload) else 2953
    if len(payload.encode('utf-8'))>limit:raise ValueError('Слишком много данных для одного QR; сократите содержимое')
    return payload

@dataclass
class PayloadSource(SourceInfo):
    source:Path
    database:Path
    sha256:str
    source_size:int
    source_mtime_ns:int
    content_kind:str
    @classmethod
    def create(cls,root,kind,payload):
        root=Path(root);root.mkdir(parents=True,exist_ok=True);path=root/(uuid.uuid4().hex+'.json')
        path.write_text(json.dumps({'kind':kind,'payload':payload},ensure_ascii=False),encoding='utf-8');stat=path.stat()
        return cls(1,1,payload,payload,path,path,hashlib.sha256(path.read_bytes()).hexdigest(),stat.st_size,stat.st_mtime_ns,kind)
    def unchanged(self):
        try:return self.source.stat().st_size==self.source_size and self.source.stat().st_mtime_ns==self.source_mtime_ns
        except OSError:return False
    def verify_content(self):return self.unchanged() and hashlib.sha256(self.source.read_bytes()).hexdigest()==self.sha256
    def row(self,number):
        if number!=1:raise IndexError(number)
        return self.first
    def rows(self,start,limit=60):return [(1,self.first)] if start==1 else []
    def find(self,text,**kwargs):return [(1,self.first)] if text in self.first else []
