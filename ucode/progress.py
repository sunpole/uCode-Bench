"""Real completed-work counters. Only successful finalization may show 100%."""
import time
from collections import deque
import math


class ProgressTracker:
    def __init__(self, total_units, callback=None, *, clock=None, speed_window=3.0, min_interval=.05,emit_every=1):
        if not math.isfinite(speed_window) or speed_window <= 0:
            raise ValueError("Окно измерения скорости должно быть положительным")
        self.total_units = max(1, total_units)
        self.callback = callback or (lambda event: None)
        self.clock = clock or time.perf_counter
        self.speed_window = speed_window
        self.started = self.clock()
        self.stage_started = self.started
        self.stage = None
        self.stage_key = None
        self.samples = deque(maxlen=256)
        self.last_emit = 0.0
        self.min_interval=min_interval
        self.emit_every=emit_every
        self.percent = 0.0

    def step(self, stage, done, total, base, *, force=False, unit="кодов"):
        if not force and (stage,base)==self.stage_key and done!=total and done%self.emit_every:
            return
        now = self.clock()
        if (stage, base) != self.stage_key:
            self.stage, self.stage_started = stage, now
            self.stage_initial_done = done
            self.stage_key = (stage, base)
            self.samples.clear()
            self.samples.append((now, done))
            force = True
        if force or done == total or now - self.last_emit >= self.min_interval:
            self.last_emit = now
            self.percent = max(self.percent, min(99.9, 100 * (base + done) / self.total_units))
            elapsed = max(0.001, now - self.stage_started)
            self.samples.append((now, done))
            # Retain one observation on/before the window edge. With sparse
            # callbacks the observed interval may exceed the requested window;
            # publish that interval instead of inventing intermediate counts.
            while len(self.samples) > 2 and self.samples[1][0] <= now - self.speed_window:
                self.samples.popleft()
            observed = max(0.001, now - self.samples[0][0])
            current_speed = max(0, done - self.samples[0][1]) / observed
            self.callback({"stage": stage, "done": done, "total": total, "percent": self.percent,
                           "elapsed": now - self.started, "speed": current_speed, "unit": unit,
                           "average_speed": max(0, done - self.stage_initial_done) / elapsed,
                           "speed_window_seconds": observed})

    def finish(self, count,stage="Готово"):
        self.percent = 100.0
        elapsed = self.clock() - self.started
        self.callback({"stage": stage, "done": count, "total": count, "percent": 100.0,
                       "elapsed": elapsed, "speed": count / max(elapsed, 0.001),
                       "average_speed": count / max(elapsed, 0.001), "unit": "кодов",
                       "speed_window_seconds": elapsed})
