"""M08: strict vector PDF verification and raster control-symbol decoding."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import uuid
from collections import Counter

from pypdf import PdfReader
from pypdf.generic import ContentStream,IndirectObject,ArrayObject

from .config import Experiment, QRFrame
from .qrdecode import DecodeError, decode_numeric_v1_m


PT_PER_MM = 72 / 25.4
PT_TOLERANCE = 0.0003  # ReportLab serializes path coordinates with finite precision.


def _near(actual, expected):
    return abs(float(actual) - expected) <= PT_TOLERANCE


def _content_key(page):
    value=page.raw_get("/Contents") if "/Contents" in page else None
    if isinstance(value,IndirectObject): return ((value.idnum,value.generation),)
    if isinstance(value,ArrayObject) and value and all(isinstance(item,IndirectObject) for item in value):
        return tuple((item.idnum,item.generation) for item in value)
    return None


def _page_matrix(page, reader, frame: QRFrame, config: Experiment, cache=None,shared=None):
    n = frame.size
    unit = config.module_mm * PT_PER_MM
    side = (n + 2 * config.quiet_modules) * unit
    for box_name in ("mediabox", "cropbox", "trimbox", "bleedbox", "artbox"):
        box = getattr(page, box_name)
        if not all(_near(v, expected) for v, expected in zip(box, (0, 0, side, side))):
            raise ValueError(f"{box_name} is not the exact expected square")
    if int(page.get("/Rotate", 0)) % 360 or float(page.get("/UserUnit", 1)) != 1:
        raise ValueError("Page rotation/UserUnit is unsupported")
    if page.get("/Annots"):
        raise ValueError("Annotations are not permitted")
    if page.get("/Group") is not None:
        raise ValueError("Page transparency groups are not permitted")
    resources = page.get("/Resources", {})
    if hasattr(resources, "get_object"):
        resources = resources.get_object()
    for key in ("/XObject", "/ExtGState", "/ColorSpace", "/Pattern", "/Shading"):
        if resources.get(key):
            raise ValueError(f"Unsupported PDF resource {key}")
    key=_content_key(page)
    if cache is not None and key in cache:
        result,decoded=cache[key]
        if result!=frame.matrix: raise ValueError("Vector QR matrix differs from the expected number/order")
        if decoded!=frame.payload: raise ValueError("Decoded payload differs from TXT")
        return result,decoded
    matrix = [[False] * n for _ in range(n)]
    fill = None
    saved = []
    rectangles = []
    in_text = False
    painted = False
    colored_paper=getattr(config,'background_mode','white')=='color'
    paper_painted=False
    contents = page.get_contents()
    if contents is None:
        raise ValueError("Page content is missing")
    for operands, operator in ContentStream(contents, reader).operations:
        if operator == b"k":
            if len(operands) != 4:
                raise ValueError("Invalid CMYK color")
            fill = tuple(float(v) for v in operands)
        elif operator == b"cm":
            # A geometry rounding tolerance is unsafe here: many individually
            # tiny transforms can accumulate to a visible translation or scale.
            if len(operands) != 6 or tuple(float(v) for v in operands) != (1, 0, 0, 1, 0, 0):
                raise ValueError("Nonidentity transformation is not permitted")
        elif operator == b"q":
            saved.append(fill)
        elif operator == b"Q":
            if not saved:
                raise ValueError("Unbalanced PDF graphics state")
            fill = saved.pop()
        elif operator == b"n":
            rectangles = []
        elif operator == b"re":
            if len(operands) != 4:
                raise ValueError("Invalid rectangle")
            rectangles.append(tuple(float(v) for v in operands))
        elif operator in (b"f", b"f*"):
            if colored_paper and not paper_painted and not painted:
                background=tuple(v/100 for v in config.background_ink)
                if fill is None or any(abs(a-b)>0.000001 for a,b in zip(fill,background)):
                    raise ValueError('Page background does not match configured CMYK')
                if in_text or len(rectangles)!=1 or not all(_near(v,e) for v,e in zip(rectangles[0],(0,0,side,side))):
                    raise ValueError('Background must be exactly one full-page rectangle before the QR')
                rectangles=[];paper_painted=True
                continue
            expected_ink = tuple(v / 100 for v in getattr(config, "ink", (0, 0, 0, 100)))
            if fill is None or any(abs(a - b) > 0.000001 for a, b in zip(fill, expected_ink)):
                raise ValueError(f"Painted fill must be the configured DeviceCMYK {expected_ink}")
            if not rectangles:
                raise ValueError("Empty/unsupported painted path")
            if in_text:
                raise ValueError("Graphics inside a text object are unsupported")
            for x, y, width, height in rectangles:
                values = (x, y, x + width, y + height)
                grid = tuple(round(value / unit) for value in values)
                if not all(_near(value, index * unit) for value, index in zip(values, grid)):
                    raise ValueError("Rectangle edges do not align to 0.5 mm module grid")
                x0, y0, x1, y1 = grid
                quiet = config.quiet_modules
                if not (quiet <= x0 < x1 <= quiet + n and quiet <= y0 < y1 <= quiet + n):
                    raise ValueError("Painting enters quiet zone or lies outside the QR matrix")
                for bottom_row in range(y0, y1):
                    row = n - 1 - (bottom_row - quiet)
                    for column in range(x0 - quiet, x1 - quiet):
                        if matrix[row][column]:
                            raise ValueError("Overlapping module rectangles are unsupported")
                        matrix[row][column] = True
            rectangles = []
            painted = True
        elif operator == b"BT":
            if in_text:
                raise ValueError("Nested text objects")
            in_text = True
        elif operator == b"ET":
            if not in_text:
                raise ValueError("Unbalanced text object")
            in_text = False
        elif operator in (b"Tf", b"TL"):
            # ReportLab writes an empty font setup even for graphics-only pages.
            if not in_text:
                raise ValueError("Text setup outside text object")
        else:
            raise ValueError(f"Unsupported PDF operator {operator!r}; only CMYK rectangles are accepted")
    if saved or in_text or rectangles or not painted or (colored_paper and not paper_painted):
        raise ValueError("Incomplete/unbalanced page content")
    result = tuple(tuple(row) for row in matrix)
    if result != frame.matrix:
        raise ValueError("Vector QR matrix differs from the expected number/order")
    decoded = decode_numeric_v1_m(result)
    if decoded != frame.payload:
        raise ValueError(f"Decoded payload {decoded!r} differs from TXT {frame.payload!r}")
    if cache is not None and key is not None and key in shared:
        cache[key]=(result,decoded)
    return result, decoded


def _decode_image(image_path: Path, config: Experiment, size=21):
    from PIL import Image

    with Image.open(image_path) as image:
        image = image.convert("L")
        cells = size + 2 * config.quiet_modules
        if abs(image.width - image.height) > 1 or min(image.size) < cells * 8:
            raise DecodeError("Rendered symbol is too small or not square")
        full_matrix = []
        colored_paper=getattr(config,'background_mode','white')=='color'
        def center(row,col):
            return image.getpixel((round((col+.5)*image.width/cells),round((row+.5)*image.height/cells)))
        paper_level=center(0,0)
        code_level=center(config.quiet_modules,config.quiet_modules)
        if colored_paper and abs(paper_level-code_level)<32:
            raise DecodeError('Rendered foreground/background contrast is insufficient')
        for row in range(cells):
            values = []
            for col in range(cells):
                # Interior of the module avoids renderer antialiasing at boundaries.
                box = (
                    round((col + 0.25) * image.width / cells),
                    round((row + 0.25) * image.height / cells),
                    round((col + 0.75) * image.width / cells),
                    round((row + 0.75) * image.height / cells),
                )
                low, high = image.crop(box).getextrema()
                if colored_paper:
                    # Known finder corner and quiet zone calibrate the actual
                    # renderer colors. Uniformity and the independent decoder
                    # remain mandatory; inversion is explicit, not guessed.
                    if max(abs(low-code_level),abs(high-code_level))<=12:
                        values.append(True)
                    elif max(abs(low-paper_level),abs(high-paper_level))<=12:
                        values.append(False)
                    else: raise DecodeError('Rendered module differs from both configured colors')
                    continue
                dark_limit = 90 if getattr(config, "ink", (0, 0, 0, 100)) == (0, 0, 0, 100) else 230
                if high < dark_limit:
                    values.append(True)
                elif low > 230:
                    values.append(False)
                else:
                    raise DecodeError("Rendered module interior is neither uniform black nor white")
            full_matrix.append(values)
        quiet = config.quiet_modules
        for r in range(cells):
            for c in range(cells):
                if (r < quiet or c < quiet or r >= quiet + size or c >= quiet + size) and full_matrix[r][c]:
                    raise DecodeError("Rendered quiet zone differs from configured substrate")
        matrix = tuple(tuple(row[quiet:quiet + size]) for row in full_matrix[quiet:quiet + size])
        return decode_numeric_v1_m(matrix)


def check_pdf(path: Path, frames: list[QRFrame], config: Experiment, *, render_samples=True,
              on_progress=None, cancel=None,reader_factory=None) -> dict:
    """Check every vector page and independently decode rendered control pages.

    Raster decoding is required for PASS by default. `render_samples=False` is
    intended only for focused tests; the result explicitly records that scope.
    Rendered PNGs are retained beside the PDF as auditable evidence.
    """
    path = Path(path)
    result = {
        "status": "FAIL", "errors": [], "pages_checked": 0,
        "decoded_samples": [], "render_samples": bool(render_samples),
        "decoder": "independent pristine QR V1/M/numeric12 + BCH + RS",
        "geometry_tolerance_points": PT_TOLERANCE,
    }
    scratch=None
    try:
        if not frames:
            raise ValueError("Expected frames are empty")
        reader = reader_factory() if reader_factory else PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDF is unsupported")
        if len(reader.pages) != len(frames):
            raise ValueError(f"Page count {len(reader.pages)} != expected {len(frames)}")
        digest = hashlib.sha256()
        counts={} if getattr(reader,"bounded_pages",False) else Counter(_content_key(page) for page in reader.pages)
        shared={key for key,count in counts.items() if key is not None and count>1}; cache={}
        decoded_streams=0; cached_pages=0
        control_indices = sorted({0, len(frames) // 2, len(frames) - 1})
        work_total = len(frames) + (len(control_indices) if render_samples else 0)
        for index, (page, frame) in enumerate(zip(reader.pages, frames), 1):
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Проверка PDF остановлена")
            try:
                if frame.version != 1 or frame.error != "M" or frame.size != 21:
                    raise ValueError("Expected frame is outside QR V1/M contract")
                cached=_content_key(page) in cache
                _, payload = _page_matrix(page, reader, frame, config,cache,shared)
                cached_pages+=int(cached); decoded_streams+=int(not cached)
                digest.update((payload + "\n").encode("ascii"))
            except Exception as exc:
                if len(result["errors"])<20: result["errors"].append(f"Page {index}: {type(exc).__name__}: {exc}")
            result["pages_checked"] += 1
            if on_progress:
                on_progress(index, work_total)
        result["decoded_payload_sha256"] = digest.hexdigest()
        result["content_decodes"]=decoded_streams
        result["cached_content_pages"]=cached_pages
        result["cache_scope"]="Only identical indirect Contents within this reader; every page geometry/resources/expected matrix/payload checked"
        if render_samples and not result["errors"]:
            renderer = shutil.which("pdftoppm")
            if not renderer:
                raise ValueError("pdftoppm unavailable: rendered control decoding cannot be verified")
            render_dir = path.parent / f"qa_{path.stem}_{uuid.uuid4().hex[:10]}"
            render_dir.mkdir(exist_ok=False)
            work=render_dir
            source="../"+path.name
            if os.name=="nt" and len(str(render_dir.resolve()))>200:
                # Poppler's PNG writer/Windows process cwd can retain MAX_PATH
                # limits. Render the original PDF via an extended input path
                # into a short project-owned scratch, then retain the PNGs
                # beside the original PDF using Python's long-path support.
                from tempfile import TemporaryDirectory
                from .runtime import ROOT
                base=ROOT/"output"; base.mkdir(parents=True,exist_ok=True)
                scratch=TemporaryDirectory(prefix=".qa-",dir=base)
                work=Path(scratch.name).resolve()
                if not work.is_relative_to(base.resolve()): raise ValueError("QA scratch находится вне проекта")
                absolute=str(path.resolve())
                source=("\\\\?\\UNC\\"+absolute[2:]) if absolute.startswith("\\\\") else "\\\\?\\"+absolute
            for sample_index, index in enumerate(control_indices, 1):
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Проверка образцов остановлена")
                prefix = render_dir / f"page_{index + 1:04d}"
                completed = subprocess.run(
                    [renderer, "-f", str(index + 1), "-l", str(index + 1), "-singlefile",
                     "-r", "1016", "-png", source, prefix.name],
                    cwd=work.resolve(),capture_output=True, timeout=30, check=False,
                )
                if work!=render_dir and (work/(prefix.name+".png")).is_file():
                    shutil.copyfile(work/(prefix.name+".png"),prefix.with_suffix(".png"))
                if completed.returncode:
                    detail = completed.stderr.decode("utf-8", errors="replace")[:500]
                    raise ValueError(f"pdftoppm exited {completed.returncode}: {detail}")
                png = prefix.with_suffix(".png")
                payload = _decode_image(png, config)
                if payload != frames[index].payload:
                    raise ValueError(f"Rendered page {index + 1}: decoded payload does not match TXT")
                result["decoded_samples"].append({"page": index + 1, "payload": payload, "png": str(png.resolve())})
                if on_progress:
                    on_progress(len(frames) + sample_index, work_total)
        result["status"] = "PASS" if not result["errors"] else "FAIL"
    except InterruptedError:
        raise
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if scratch is not None: scratch.cleanup()
        if reader_factory and "reader" in locals(): reader.close()
    return result
