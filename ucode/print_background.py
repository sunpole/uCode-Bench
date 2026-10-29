"""Optional opaque CMYK paper fill. Transparent mode paints no paper object."""
def background_operators(config,side):
    if getattr(config,'background_mode','white')!='color': return ''
    from .compact_pdf import _number
    color=' '.join(_number(v/100,9) for v in config.background_ink)
    return f'{color} k\n0 0 {side} {side} re\nf\n'
