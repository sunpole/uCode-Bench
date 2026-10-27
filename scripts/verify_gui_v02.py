"""Run the actual Tk event loop/worker on 1000 codes, recording UI state.

This is an application integration check, not native mouse/screenshot proof.
"""
import json
from pathlib import Path
import sys
import time
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ucode.batch import make_template
from ucode.batch_gui import BatchWindow

base = ROOT / "output/v02-gui"
source = make_template(base / "templates", 1000)
root = tk.Tk()
root.withdraw()
app = BatchWindow(root, base)
app.input_var.set(str(source))
assert app.inspect_input() is not None
root.deiconify()
samples = []
started = time.perf_counter()
failure = []


def observe():
    samples.append({"elapsed": time.perf_counter() - started, "status": app.status_var.get(),
                    "percent": float(app.progress["value"]), "clock": app.elapsed_var.get(),
                    "speed": app.speed_var.get(), "busy": app.busy})
    if time.perf_counter() - started > 120:
        failure.append("GUI operation exceeded 120 seconds")
        app.request_cancel()
    if not app.busy and app.last_output and (app.worker is None or not app.worker.is_alive()):
        try:
            report = json.loads((app.last_output / "manifest.json").read_text(encoding="utf-8"))
            assert report["status"] == "COMPLETE", report
            assert report["count"] == 1000
            assert app.last_pdf and app.last_pdf.is_file()
            assert app.last_report and app.last_report.is_file()
            assert samples[-1]["percent"] == 100
            assert any(0 < row["percent"] < 100 for row in samples)
            assert all(a["percent"] <= b["percent"] for a, b in zip(samples, samples[1:]))
            text = " ".join(row["status"] for row in samples)
            assert "Кодирование" in text and "Создание" in text and "Проверка" in text
            width, height = root.winfo_width(), root.winfo_height()
            rectangles = []
            def visit(widget):
                for child in widget.winfo_children():
                    if child.winfo_ismapped():
                        x, y = child.winfo_rootx() - root.winfo_rootx(), child.winfo_rooty() - root.winfo_rooty()
                        w, h = child.winfo_width(), child.winfo_height()
                        rectangles.append({"class": child.winfo_class(), "x": x, "y": y, "w": w, "h": h})
                        assert x >= 0 and y >= 0 and x + w <= width + 2 and y + h <= height + 2, rectangles[-1]
                        visit(child)
            visit(root)
            evidence = {"status": "PASS", "pdf": str(app.last_pdf.relative_to(ROOT)),
                        "window": [width, height], "samples": samples, "widget_rectangles": rectangles,
                        "scope": "actual Tk mainloop, primary button invoke, worker, state updates and bounds; native capture unavailable"}
            (app.last_output / "gui-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
            print("PASS GUI event loop / 1000 real PDF:", app.last_output, flush=True)
        except Exception as exc:
            failure.append(str(exc))
        root.after(300, root.destroy)
    elif failure and (app.worker is None or not app.worker.is_alive()):
        root.destroy()
    else:
        root.after(150, observe)


root.after(250, app.generate.invoke)
root.after(400, observe)
root.mainloop()
if failure:
    raise SystemExit("GUI verification failed: " + "; ".join(failure))
