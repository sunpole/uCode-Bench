"""M01: reproducible numeric input, preserved as UTF-8 TXT."""
from pathlib import Path
from .config import Experiment


def generate_numbers(config: Experiment) -> list[str]:
    return [str(config.start + i) for i in range(config.count)]


def write_numbers(numbers: list[str], path: Path) -> None:
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(numbers) + "\n")
