"""Validated project-local preferences; never read or write OS settings."""
import json
from pathlib import Path
import uuid
from .print_settings import PrintSettings


def load_preferences(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Неверная структура настроек")
        if value.get("schema_version") != 1 or value.get("mode") not in ("multipage", "singles", "both"):
            raise ValueError("Неверная версия настроек")
        fields = value["settings"]
        if not isinstance(fields, dict):
            raise ValueError("Неверная структура настроек печати")
        settings = PrintSettings(module_mm=fields["module_mm"], quiet_modules=fields["quiet_modules"],
                                 ink=tuple(fields.get("ink", [0, 0, 0, 100])))
        return settings, value["mode"], ""
    except FileNotFoundError:
        return PrintSettings(), "multipage", ""
    except (OSError, ValueError, KeyError, TypeError):
        return PrintSettings(), "multipage", "Настройки не прочитаны; используются значения по умолчанию."


def save_preferences(path, settings, mode):
    if mode not in ("multipage", "singles", "both") or not isinstance(settings, PrintSettings):
        raise ValueError("Неверные настройки вывода")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump({"schema_version": 1, "settings": {"module_mm": settings.module_mm,
                  "quiet_modules": settings.quiet_modules, "ink": settings.ink}, "mode": mode}, stream)
    temporary.replace(path)
