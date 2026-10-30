"""One user-initiated native file dialog, isolated from HTTP worker threads."""
import json
import sys
import tkinter as tk
from tkinter import filedialog


def main():
    kind=sys.argv[1];initial=sys.argv[2] if len(sys.argv)>2 else ''
    root=tk.Tk();root.withdraw();root.attributes('-topmost',True)
    options={'parent':root,'initialdir':initial or None}
    try:
        if kind=='folder':value=filedialog.askdirectory(title='Папка uCode',**options)
        elif kind=='save':value=filedialog.asksaveasfilename(title='Сохранить TXT',defaultextension='.txt',filetypes=[('TXT UTF-8','*.txt')],**options)
        elif kind=='json':value=filedialog.askopenfilename(title='Отчёт uCode',filetypes=[('JSON','*.json')],**options)
        else:value=filedialog.askopenfilename(title='Открыть базу кодов',filetypes=[('TXT UTF-8','*.txt'),('Все файлы','*.*')],**options)
        print(json.dumps(value,ensure_ascii=False),flush=True)
    finally:root.destroy()


if __name__=='__main__':main()
