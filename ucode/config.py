"""Shared, fixed first-stage experiment contract."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Experiment:
    count: int = 200
    start: int = 200000000000
    repeats: int = 3
    module_mm: float = 0.5
    quiet_modules: int = 4
    threshold_seconds: float = 120.0

    def __post_init__(self):
        if self.count not in (2, 200, 1000, 10000):
            raise ValueError("Supported counts: 2 (smoke), 200, 1000, 10000; resources and qualification are required")
        if self.repeats != 3:
            raise ValueError("Three repeats are required")
        if self.start < 0 or len(str(self.start + self.count - 1)) != 12 or len(str(self.start)) != 12:
            raise ValueError("Expected twelve-digit nonnegative numbers")
        if self.module_mm != 0.5 or self.quiet_modules != 4 or self.threshold_seconds != 120:
            raise ValueError("Stage 1 geometry and threshold are fixed")

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class QRFrame:
    payload: str
    matrix: tuple[tuple[bool, ...], ...]
    version: int = 1
    error: str = "M"

    @property
    def size(self):
        return len(self.matrix)

    def to_dict(self):
        return {"payload": self.payload, "matrix": self.matrix, "version": self.version, "error": self.error}

    @classmethod
    def from_dict(cls, data):
        return cls(str(data["payload"]), tuple(tuple(bool(c) for c in row) for row in data["matrix"]), data["version"], data["error"])
