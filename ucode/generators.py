"""Capability contract: each implemented symbology owns validation/render/QA."""
from dataclasses import dataclass
from typing import Protocol


class Generator(Protocol):
    key: str
    name: str
    available: bool
    input_description: str

    def validate(self, value: str) -> bool: ...
    def default_settings(self): ...
    def encode(self, values, **kwargs): ...
    def write_pdf(self, frames, path, settings, **kwargs): ...
    def verify(self, path, frames, settings, **kwargs): ...


@dataclass(frozen=True)
class QRGenerator:
    key: str = "qr"
    name: str = "QR Code"
    available: bool = True
    input_description: str = "12 цифр в строке"

    def validate(self, value):
        return len(value) == 12 and value.isascii() and value.isdigit()

    def default_settings(self):
        from .print_settings import PrintSettings
        return PrintSettings()

    def encode(self, values, **kwargs):
        from .qr import encode_numbers
        return encode_numbers(values, **kwargs)

    def write_pdf(self, frames, path, settings, **kwargs):
        from .pdf import write_pdf
        return write_pdf(frames, path, settings, **kwargs)

    def verify(self, path, frames, settings, **kwargs):
        from .quality import check_pdf
        return check_pdf(path, frames, settings, **kwargs)


@dataclass(frozen=True)
class PlannedGenerator:
    key: str
    name: str
    available: bool = False
    input_description: str = "В разработке"

    def _unavailable(self, *args, **kwargs):
        raise ValueError(f"{self.name}: в разработке")

    validate = default_settings = encode = write_pdf = verify = _unavailable


def generators() -> tuple[Generator, ...]:
    return (QRGenerator(), PlannedGenerator("ean13", "EAN-13"),
            PlannedGenerator("code128", "Code 128"), PlannedGenerator("datamatrix", "Data Matrix"))


def get_generator(key) -> Generator:
    item = next((g for g in generators() if g.key == key), None)
    if item is None or not item.available:
        raise ValueError("Этот генератор в разработке")
    return item
