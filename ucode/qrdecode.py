"""Independent, deliberately narrow QR decoder for the stage-1 QA contract.

Supports pristine, normally oriented QR Version 1 / M / 12 numeric digits.
Checks both format copies, fixed patterns, all Reed-Solomon syndromes and
canonical numeric padding. It detects errors and never silently corrects them.
There is no import of the encoder and no metadata-based payload shortcut.
This is an experiment verifier, not a general camera/scanner decoder.
"""

from collections.abc import Sequence


class DecodeError(ValueError):
    """The symbol does not satisfy the supported QR contract."""


def _format_word(data: int) -> int:
    remainder = data << 10
    while remainder.bit_length() >= 11:
        remainder ^= 0x537 << (remainder.bit_length() - 11)
    return ((data << 10) | remainder) ^ 0x5412


def _mul(a: int, b: int) -> int:
    value = 0
    while b:
        if b & 1:
            value ^= a
        b >>= 1
        a <<= 1
        if a & 0x100:
            a ^= 0x11D
    return value


def _reserved() -> set[tuple[int, int]]:
    result = {(r, c) for r in range(9) for c in range(9)}
    result |= {(r, c) for r in range(9) for c in range(13, 21)}
    result |= {(r, c) for r in range(13, 21) for c in range(9)}
    result |= {(6, i) for i in range(21)} | {(i, 6) for i in range(21)}
    return result


def _mask(mask: int, r: int, c: int) -> bool:
    return (
        (r + c) % 2 == 0,
        r % 2 == 0,
        c % 3 == 0,
        (r + c) % 3 == 0,
        (r // 2 + c // 3) % 2 == 0,
        (r * c) % 2 + (r * c) % 3 == 0,
        ((r * c) % 2 + (r * c) % 3) % 2 == 0,
        ((r * c) % 3 + (r + c) % 2) % 2 == 0,
    )[mask]


def _fixed_patterns(matrix):
    for top, left in ((0, 0), (0, 14), (14, 0)):
        for r in range(7):
            for c in range(7):
                expected = r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4)
                if matrix[top + r][left + c] != expected:
                    raise DecodeError("Finder pattern mismatch")
        for r in range(max(0, top - 1), min(21, top + 8)):
            for c in range(max(0, left - 1), min(21, left + 8)):
                if (r < top or r >= top + 7 or c < left or c >= left + 7) and matrix[r][c]:
                    raise DecodeError("Finder separator is not white")
    for pos in range(8, 13):
        if matrix[6][pos] != (pos % 2 == 0) or matrix[pos][6] != (pos % 2 == 0):
            raise DecodeError("Timing pattern mismatch")
    if not matrix[13][8]:
        raise DecodeError("Fixed dark module is missing")


def decode_numeric_v1_m(matrix: Sequence[Sequence[bool]]) -> str:
    """Decode and validate a 21x21 symbol independently of its encoder."""
    if len(matrix) != 21 or any(len(row) != 21 for row in matrix):
        raise DecodeError("Only standard QR Version 1 (21x21) is supported")
    matrix = tuple(tuple(bool(cell) for cell in row) for row in matrix)
    _fixed_patterns(matrix)
    word_a = word_b = 0
    for bit in range(15):
        row = bit if bit < 6 else bit + 1 if bit < 8 else 6 + bit
        col = 20 - bit if bit < 8 else 7 if bit == 8 else 14 - bit
        word_a |= int(matrix[row][8]) << bit
        word_b |= int(matrix[8][col]) << bit
    matches = [mask for mask in range(8) if word_a == word_b == _format_word(mask)]
    if len(matches) != 1:
        raise DecodeError("Format BCH/copies mismatch or error correction level is not M")
    mask = matches[0]
    reserved = _reserved()
    bits = []
    upward = True
    right = 20
    while right > 0:
        if right == 6:
            right = 5
        rows = range(20, -1, -1) if upward else range(21)
        for row in rows:
            for col in (right, right - 1):
                if (row, col) not in reserved:
                    bits.append(int(matrix[row][col] ^ _mask(mask, row, col)))
        upward = not upward
        right -= 2
    if len(bits) != 208:
        raise DecodeError("Unexpected data-module count")
    words = [sum(bits[i + j] << (7 - j) for j in range(8)) for i in range(0, 208, 8)]
    alpha = 1
    for _ in range(10):
        syndrome = 0
        for word in words:
            syndrome = _mul(syndrome, alpha) ^ word
        if syndrome:
            raise DecodeError("Reed-Solomon parity mismatch")
        alpha = _mul(alpha, 2)
    offset = 0

    def read(length):
        nonlocal offset
        value = 0
        for bit in bits[offset:offset + length]:
            value = (value << 1) | bit
        offset += length
        return value

    if read(4) != 1 or read(10) != 12:
        raise DecodeError("Expected one numeric segment with twelve digits")
    groups = [read(10) for _ in range(4)]
    if any(value > 999 for value in groups):
        raise DecodeError("Invalid numeric group")
    payload = "".join(f"{value:03d}" for value in groups)
    if any(bits[offset:64]):
        raise DecodeError("Invalid numeric terminator or alignment padding")
    if words[8:16] != [0xEC, 0x11] * 4:
        raise DecodeError("Invalid QR pad codewords")
    return payload
