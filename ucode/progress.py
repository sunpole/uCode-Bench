"""Real completed-work counters. Only successful finalization may show 100%."""
import time


class ProgressTracker:
    def __init__(self, total_units, callback=None):
        self.total_units = max(1, total_units)
        self.callback = callback or (lambda event: None)
        self.started = time.perf_counter()
        self.stage_started = self.started
        self.stage = None
        self.last_emit = 0.0
        self.percent = 0.0

    def step(self, stage, done, total, base, *, force=False, unit="кодов"):
        now = time.perf_counter()
        if stage != self.stage:
            self.stage, self.stage_started = stage, now
            force = True
        if force or done == total or now - self.last_emit >= 0.05:
            self.last_emit = now
            self.percent = max(self.percent, min(99.9, 100 * (base + done) / self.total_units))
            elapsed = max(0.001, now - self.stage_started)
            self.callback({"stage": stage, "done": done, "total": total, "percent": self.percent,
                           "elapsed": now - self.started, "speed": done / elapsed, "unit": unit})

    def finish(self, count):
        self.percent = 100.0
        elapsed = time.perf_counter() - self.started
        self.callback({"stage": "Готово", "done": count, "total": count, "percent": 100.0,
                       "elapsed": elapsed, "speed": count / max(elapsed, 0.001)})
