"""Validated project-local preferences; never read or write OS settings."""
import json
from pathlib import Path
import uuid
from dataclasses import asdict, dataclass
from .print_settings import PrintSettings


@dataclass(frozen=True)
class GenerationPreferences:
    copies_per_value: int = 1
    duplicate_policy: str = "preserve"
    template_count: int = 200
    output_directory: str = ""

    def __post_init__(self):
        for value in (self.copies_per_value, self.template_count):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10000:
                raise ValueError("Количество и экземпляры: целые числа от 1 до 10 000")
        if self.duplicate_policy not in ("preserve", "unique") or not isinstance(self.output_directory, str):
            raise ValueError("Неверные параметры генерации")


def load_user_preferences(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Неверная структура настроек")
        if value.get("schema_version") not in (1, 2) or value.get("mode") not in ("multipage", "singles", "both"):
            raise ValueError("Неверная версия настроек")
        fields = value["settings"]
        if not isinstance(fields, dict):
            raise ValueError("Неверная структура настроек печати")
        settings = PrintSettings(module_mm=fields["module_mm"], quiet_modules=fields["quiet_modules"],
                                 ink=tuple(fields.get("ink", [0, 0, 0, 100])))
        fields = value.get("generation", {})
        if not isinstance(fields, dict):
            raise ValueError("Неверные параметры генерации")
        generation = GenerationPreferences(**{key: fields[key] for key in GenerationPreferences.__dataclass_fields__ if key in fields})
        return settings, value["mode"], generation, ""
    except FileNotFoundError:
        return PrintSettings(), "multipage", GenerationPreferences(), ""
    except (OSError, ValueError, KeyError, TypeError):
        return PrintSettings(), "multipage", GenerationPreferences(), "Настройки не прочитаны; используются значения по умолчанию."


def load_preferences(path):
    settings, mode, _, warning = load_user_preferences(path)
    return settings, mode, warning


def save_preferences(path, settings, mode, *, generation=None):
    if mode not in ("multipage", "singles", "both") or not isinstance(settings, PrintSettings):
        raise ValueError("Неверные настройки вывода")
    path = Path(path)
    if generation is None:
        _, _, generation, _ = load_user_preferences(path)
    if not isinstance(generation, GenerationPreferences):
        raise ValueError("Неверные параметры генерации")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump({"schema_version": 2, "settings": {"module_mm": settings.module_mm,
                  "quiet_modules": settings.quiet_modules, "ink": settings.ink}, "mode": mode,
                  "generation": asdict(generation)}, stream)
    temporary.replace(path)
