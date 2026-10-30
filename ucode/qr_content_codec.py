"""General static-content QR encoder and independent pristine-symbol verifier.

The verifier imports no encoder. It verifies format/version BCH, layout,
unmasks/interleaves blocks and checks RS syndromes and decoded content.
It does not correct damage or claim camera interoperability.
"""
import json
from pathlib import Path
import re
from .config import QRFrame
from .qrdecode import _format_word,_mask,_mul,DecodeError

TABLES=json.loads((Path(__file__).with_name('assets')/'qr-standard-tables.json').read_text())
LEVELS={'L':1,'M':0,'Q':3,'H':2}
ALPHABET='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:'

def encode_content(payload,level='M'):
    from reportlab.graphics.barcode.qrencoder import QRCode,QR,QRNumber,QRAlphaNum,QR8bitByte,QRRSBlock
    if level not in LEVELS:raise ValueError('Коррекция QR: L/M/Q/H')
    class UTF8ECI(QR):
        mode=7;lengthbits=(0,0,0)
        @property
        def bitlength(self):return 8
        def write(self,buffer,version):buffer.put(7,4);buffer.put(26,8)
    if re.fullmatch('[0-9]+',payload):segments=[QRNumber(payload)]
    elif payload and all(c in ALPHABET for c in payload):segments=[QRAlphaNum(payload)]
    else:segments=([] if payload.isascii() else [UTF8ECI('')])+[QR8bitByte(payload.encode('utf-8'))]
    for version in range(1,41):
        bits=sum(4+s.getLengthBits(version)+s.bitlength for s in segments)
        capacity=8*sum(b.dataCount for b in QRRSBlock.getRSBlocks(version,LEVELS[level]))
        if bits<=capacity:break
    else:raise ValueError('Данные не помещаются в QR на уровне '+level+'. Сократите данные или уменьшите коррекцию.')
    qr=QRCode(version=version,errorCorrectLevel=LEVELS[level])
    for segment in segments:qr.addData(segment)
    qr.make()
    return QRFrame(payload,tuple(tuple(bool(c) for c in row) for row in qr.modules),version,level)

def version_word(version):
    remainder=version<<12
    while remainder.bit_length()>=13:remainder^=0x1f25<<(remainder.bit_length()-13)
    return (version<<12)|remainder

def decode_content(matrix,level):
    n=len(matrix);version=(n-17)//4
    if not 1<=version<=40 or n!=17+4*version or any(len(r)!=n for r in matrix):raise DecodeError('Invalid QR dimensions')
    if level not in LEVELS:raise DecodeError('Unsupported level')
    reserved=set();fixed={}
    def put(r,c,value=None):
        reserved.add((r,c))
        if value is not None:fixed[r,c]=bool(value)
    for top,left in ((0,0),(0,n-7),(n-7,0)):
        for dr in range(-1,8):
            for dc in range(-1,8):
                r,c=top+dr,left+dc
                if 0<=r<n and 0<=c<n:
                    value=0<=dr<7 and 0<=dc<7 and (dr in (0,6) or dc in (0,6) or 2<=dr<=4 and 2<=dc<=4)
                    put(r,c,value)
    for r in TABLES['align'][version-1]:
        for c in TABLES['align'][version-1]:
            if (r<=8 and (c<=8 or c>=n-8)) or (r>=n-8 and c<=8):continue
            for dr in range(-2,3):
                for dc in range(-2,3):put(r+dr,c+dc,max(abs(dr),abs(dc))!=1)
    for i in range(8,n-8):
        if (6,i) not in reserved:put(6,i,i%2==0)
        if (i,6) not in reserved:put(i,6,i%2==0)
    a=b=0
    for bit in range(15):
        r=bit if bit<6 else bit+1 if bit<8 else n-15+bit
        c=n-bit-1 if bit<8 else 7 if bit==8 else 14-bit
        put(r,8);put(8,c);a|=int(matrix[r][8])<<bit;b|=int(matrix[8][c])<<bit
    matches=[m for m in range(8) if a==b==_format_word((LEVELS[level]<<3)|m)]
    if len(matches)!=1:raise DecodeError('Format BCH/copies/expected level mismatch')
    put(n-8,8,True)
    if version>=7:
        a=b=0
        for i in range(18):
            r,c=i//3,n-11+i%3;put(r,c);put(c,r)
            a|=int(matrix[r][c])<<i;b|=int(matrix[c][r])<<i
        if a!=b or a!=version_word(version):raise DecodeError('Version BCH mismatch')
    if any(bool(matrix[r][c])!=value for (r,c),value in fixed.items()):raise DecodeError('Fixed QR pattern mismatch')
    bits=[];up=True;right=n-1;mask=matches[0]
    while right>0:
        if right==6:right=5
        for row in (range(n-1,-1,-1) if up else range(n)):
            for col in (right,right-1):
                if (row,col) not in reserved:bits.append(int(bool(matrix[row][col])^_mask(mask,row,col)))
        up=not up;right-=2
    spec=TABLES['rs'][(version-1)*4+'LMQH'.index(level)];blocks=[]
    for i in range(0,len(spec),3):
        count,total,data=spec[i:i+3]
        for _ in range(count):blocks.append({'data':data,'parity':total-data,'words':[0]*total})
    total=sum(len(b['words']) for b in blocks)
    if len(bits)<total*8 or any(bits[total*8:]):raise DecodeError('Remainder bits mismatch')
    words=[sum(bits[i+j]<<(7-j) for j in range(8)) for i in range(0,total*8,8)];offset=0
    for i in range(max(b['data'] for b in blocks)):
        for b in blocks:
            if i<b['data']:b['words'][i]=words[offset];offset+=1
    for i in range(max(b['parity'] for b in blocks)):
        for b in blocks:
            if i<b['parity']:b['words'][b['data']+i]=words[offset];offset+=1
    for b in blocks:
        alpha=1
        for _ in range(b['parity']):
            syndrome=0
            for w in b['words']:syndrome=_mul(syndrome,alpha)^w
            if syndrome:raise DecodeError('RS parity mismatch')
            alpha=_mul(alpha,2)
    data=[w for b in blocks for w in b['words'][:b['data']]]
    stream=[(w>>i)&1 for w in data for i in range(7,-1,-1)];cursor=0;result=bytearray();eci=None
    def read(length):
        nonlocal cursor
        if cursor+length>len(stream):raise DecodeError('QR segment overflow')
        value=0
        for bit in stream[cursor:cursor+length]:value=(value<<1)|bit
        cursor+=length;return value
    group=0 if version<10 else 1 if version<27 else 2
    while cursor+4<=len(stream):
        mode=read(4)
        if mode==0:break
        if mode==7:
            eci=read(8)
            if eci!=26:raise DecodeError('Only UTF-8 ECI 26 supported')
            continue
        if mode not in (1,2,4):raise DecodeError('Unsupported QR mode')
        length=read({1:(10,12,14),2:(9,11,13),4:(8,16,16)}[mode][group])
        if mode==4:
            raw=bytes(read(8) for _ in range(length))
            if any(v>127 for v in raw) and eci!=26:raise DecodeError('Non-ASCII without explicit UTF-8 ECI')
            result.extend(raw)
        elif mode==1:
            while length:
                digits=min(3,length);value=read({1:4,2:7,3:10}[digits])
                if value>=10**digits:raise DecodeError('Invalid numeric value')
                result.extend(f'{value:0{digits}d}'.encode());length-=digits
        else:
            while length>=2:
                value=read(11)
                if value>=45*45:raise DecodeError('Invalid alphanumeric value')
                result.extend((ALPHABET[value//45]+ALPHABET[value%45]).encode());length-=2
            if length:
                value=read(6)
                if value>=45:raise DecodeError('Invalid alphanumeric value')
                result.extend(ALPHABET[value].encode())
    while cursor%8:
        if read(1):raise DecodeError('Nonzero alignment padding')
    pads=[]
    while cursor<len(stream):pads.append(read(8))
    if pads!=[0xec if i%2==0 else 0x11 for i in range(len(pads))]:raise DecodeError('Invalid padding codewords')
    try:return result.decode('utf-8')
    except UnicodeDecodeError as exc:raise DecodeError('Invalid UTF-8') from exc
