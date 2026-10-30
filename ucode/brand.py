"""User-supplied uBrand artwork; no SVG renderer needed at runtime."""
import base64
from pathlib import Path

ASSETS = Path(__file__).with_name('assets')
SVG_SHA256 = '0050d768e2c21ec8311c97b45e5fcc3efc80da6fd2ec3d11e01fd10e6eba11d1'


def image_uri():
    return 'data:image/png;base64,' + base64.b64encode((ASSETS/'ubrand.png').read_bytes()).decode('ascii')


def install(app, parent):
    from PIL import Image, ImageTk
    from tkinter import ttk
    size = max(18, min(64, round(24*float(app.root.tk.call('tk','scaling'))/(96/72))))
    with Image.open(ASSETS/'ubrand.png') as source:
        app.brand_image = ImageTk.PhotoImage(source.resize((size,size),Image.Resampling.LANCZOS), master=app.root)
        app.brand_icon = ImageTk.PhotoImage(source, master=app.root)
    app.root.iconphoto(True, app.brand_icon)
    app.brand_button = ttk.Button(parent, image=app.brand_image, text='uBrand', compound='left',
                                  command=lambda:app.show_help('about'), style='Brand.TButton')
    app.brand_button.pack(side='left', padx=(0,10))

