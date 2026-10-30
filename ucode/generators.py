"""Capability contract: each implemented symbology owns validation/render/QA."""
from dataclasses import dataclass
from typing import Protocol


class Generator(Protocol):
    key: str
    name: str
    available: bool
    input_description: str
    progress_name: str

    def validate(self, value: str) -> bool: ...
    def default_settings(self): ...
    def validate_settings(self, settings): ...
    def describe_settings(self, settings) -> dict: ...
    def encode(self, values, **kwargs): ...
    def write_pdf(self, frames, path, settings, **kwargs): ...
    def verify(self, path, frames, settings, **kwargs): ...


@dataclass(frozen=True)
class QRGenerator:
    key: str = "qr"
    name: str = "QR Code"
    available: bool = True
    progress_name: str = "QR"
    legacy_timing_key: str = "qr_encoding"
    input_description: str = "QR V1 L/M/Q/H: ровно 12 ASCII-цифр, без пробелов"

    def validate(self, value):
        return len(value) == 12 and value.isascii() and value.isdigit()

    def default_settings(self):
        from .print_settings import PrintSettings
        return PrintSettings()

    def validate_settings(self, settings):
        from .print_settings import PrintSettings
        if not isinstance(settings, PrintSettings):
            raise ValueError("Ожидаются безопасные настройки PrintSettings для QR")

    def describe_settings(self, settings):
        self.validate_settings(settings)
        return {"symbology": self.name, "version": 1, "ecc": settings.error_correction, "numeric_digits": 12,
                "description": "векторный QR V1-"+settings.error_correction,
                **settings.to_dict(), "colorspace": "DeviceCMYK", "vector": True,
                "pdf_x_certified": False}

    def encode(self, values, **kwargs):
        from .engines import get_engine
        return get_engine().encode(values, **kwargs)

    def write_pdf(self, frames, path, settings, **kwargs):
        from .engines import get_engine
        return get_engine().write_pdf(frames, path, settings, **kwargs)

    def verify(self, path, frames, settings, **kwargs):
        from .quality import check_pdf
        return check_pdf(path, frames, settings, **kwargs)


@dataclass(frozen=True)
class PlannedGenerator:
    key: str
    name: str
    available: bool = False
    input_description: str = "В разработке"
    progress_name: str = "В разработке"

    def _unavailable(self, *args, **kwargs):
        raise ValueError(f"{self.name}: в разработке")

    validate = default_settings = validate_settings = describe_settings = encode = write_pdf = verify = _unavailable


_GENERATORS: dict[str, Generator] = {
    "qr": QRGenerator(), "ean13": PlannedGenerator("ean13", "EAN-13"),
    "code128": PlannedGenerator("code128", "Code 128"),
    "datamatrix": PlannedGenerator("datamatrix", "Data Matrix"),
}


def generators() -> tuple[Generator, ...]:
    return tuple(_GENERATORS.values())


def get_generator(key) -> Generator:
    item = next((g for g in generators() if g.key == key), None)
    if item is None or not item.available:
        raise ValueError("Этот генератор в разработке")
    return item
