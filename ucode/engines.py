"""Generation engines; symbology validation/QA live in generators, not here.

This registry is separate from PDF mergers. Adding an engine does not require
editing the production pipeline. No discovery path installs or downloads code.
"""
from dataclasses import asdict, dataclass
from importlib import metadata
from typing import Protocol


@dataclass(frozen=True)
class EngineInfo:
    key: str
    name: str
    version: str | None
    available: bool
    reason: str = ""
    symbologies: tuple[str, ...] = ("qr",)
    colorspaces: tuple[str, ...] = ("DeviceCMYK",)
    output_modes: tuple[str, ...] = ("singles", "multipage", "both")
    pdf_methods: tuple[str, ...] = ("direct", "single-files")
    execution_modes: tuple[str, ...] = ("serial",)
    vector: bool = True
    streaming: bool = False

    def to_dict(self):
        return asdict(self)


class GenerationEngine(Protocol):
    def info(self) -> EngineInfo: ...
    def prepare(self): ...
    def encode(self, values, **kwargs): ...
    def write_pdf(self, frames, path, settings, **kwargs): ...
    def write_singles(self, frames, directory, settings, **kwargs): ...


class ReportLabEngine:
    def info(self):
        try:
            version = metadata.version("reportlab")
        except metadata.PackageNotFoundError:
            return EngineInfo("reportlab", "ReportLab QR + PDF", None, False,
                              "ReportLab не установлен; автоматической установки нет")
        return EngineInfo("reportlab", "ReportLab QR + PDF", version, True)

    def prepare(self):
        # Worker invokes this before the method timer, preserving the old
        # scientific profile's import boundary. It is not a benchmark warmup.
        from .qr import encode_numbers
        from .pdf import write_pdf, write_single_files
        self._encode = encode_numbers
        self._write = write_pdf
        self._singles = write_single_files

    def encode(self, values, **kwargs):
        if not hasattr(self, "_encode"):
            self.prepare()
        return self._encode(values, **kwargs)

    def write_pdf(self, frames, path, settings, **kwargs):
        if not hasattr(self, "_write"):
            self.prepare()
        return self._write(frames, path, settings, **kwargs)

    def write_singles(self, frames, directory, settings, **kwargs):
        if not hasattr(self, "_singles"):
            self.prepare()
        return self._singles(frames, directory, settings, **kwargs)


_ENGINES: dict[str, GenerationEngine] = {"reportlab": ReportLabEngine()}


def available_engines():
    return tuple(engine.info() for engine in _ENGINES.values())


def get_engine(key="reportlab", *, generator="qr", mode="multipage", colorspace="DeviceCMYK"):
    engine = _ENGINES.get(key)
    if engine is None:
        raise ValueError(f"Неизвестный движок генерации: {key}")
    info = engine.info()
    if not info.available:
        raise ValueError(f"Недоступен движок {info.name}: {info.reason}")
    if generator not in info.symbologies:
        raise ValueError(f"Движок {info.name} не поддерживает тип кода {generator}")
    if mode not in info.output_modes:
        raise ValueError(f"Движок {info.name} не поддерживает формат результата {mode}")
    if colorspace not in info.colorspaces or not info.vector:
        raise ValueError(f"Движок {info.name} не поддерживает требуемый векторный {colorspace}")
    return engine
