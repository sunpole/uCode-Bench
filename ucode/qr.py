"""M02: ordinary QR Version 1, numeric, exactly error correction M."""
from reportlab.graphics.barcode.qrencoder import QRCode, QRErrorCorrectLevel, QRNumber
from .config import QRFrame


def encode_numbers(numbers: list[str]) -> list[QRFrame]:
    frames = []
    for number in numbers:
        if len(number) != 12 or not number.isascii() or not number.isdigit():
            raise ValueError("Stage 1 requires twelve ASCII digits")
        qr = QRCode(version=1, errorCorrectLevel=QRErrorCorrectLevel.M)
        qr.addData(QRNumber(number))
        qr.make()
        frames.append(QRFrame(number, tuple(tuple(bool(cell) for cell in row) for row in qr.modules)))
    return frames
