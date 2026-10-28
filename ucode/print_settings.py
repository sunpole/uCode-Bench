"""User-facing QR print geometry (separate from immutable benchmark settings)."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class PrintSettings:
    """All lengths millimetres, with the full white margin included in the PDF page."""
    module_mm: float = 0.5
    quiet_modules: int = 4
    ink: tuple = (0, 0, 0, 100)

    def __post_init__(self):
        if isinstance(self.module_mm, bool):
            raise ValueError("Размер модуля должен быть числом в миллиметрах")
        if isinstance(self.quiet_modules, bool) or not isinstance(self.quiet_modules, int) or not 4 <= self.quiet_modules <= 20:
            raise ValueError("Белое поле: от 4 до 20 модулей. Меньше 4 не соответствует QR Code.")
        try:
            module = float(self.module_mm)
        except (TypeError, ValueError) as exc:
            raise ValueError("Неверный физический размер модуля QR") from exc
        if not math.isfinite(module) or not 0.25 <= module <= 2.0:
            raise ValueError("Размер одного модуля должен быть от 0,25 до 2,0 мм.")
        object.__setattr__(self, "module_mm", module)
        if not isinstance(self.ink, (tuple, list)) or len(self.ink) != 4 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 100 for v in self.ink
        ) or not any(self.ink):
            raise ValueError("CMYK: четыре числа 0–100%; цвет не может быть полностью белым.")
        object.__setattr__(self, "ink", tuple(float(v) for v in self.ink))

    @property
    def is_k100(self):
        return self.ink == (0, 0, 0, 100)

    @classmethod
    def from_total_side(cls, total_mm: float, quiet_modules: int = 4, ink=(0, 0, 0, 100)):
        if isinstance(quiet_modules, bool) or not isinstance(quiet_modules, int) or not 4 <= quiet_modules <= 20:
            raise ValueError("Белое поле: целое число от 4 до 20 модулей")
        try:
            total = float(total_mm)
        except (TypeError, ValueError) as exc:
            raise ValueError("Общий размер должен быть числом в миллиметрах") from exc
        if not math.isfinite(total) or total <= 0:
            raise ValueError("Общий размер должен быть положительным числом")
        return cls(module_mm=total / (21 + 2 * quiet_modules), quiet_modules=quiet_modules, ink=ink)

    @property
    def side_mm(self) -> float:
        return (21 + 2 * self.quiet_modules) * self.module_mm

    @property
    def dark_matrix_mm(self) -> float:
        return 21 * self.module_mm

    @property
    def white_margin_mm(self) -> float:
        return self.quiet_modules * self.module_mm

    def to_dict(self) -> dict:
        return {
            "module_mm": self.module_mm,
            "quiet_modules": self.quiet_modules,
            "page_mm": [self.side_mm, self.side_mm],
            "dark_matrix_mm": self.dark_matrix_mm,
            "white_margin_mm": self.white_margin_mm,
            "ink": list(self.ink), "k100": self.is_k100,
        }


def format_duration(seconds) -> str:
    """Human-readable duration, preserving fractions for sub-second tasks."""
    if seconds is None:
        return "нет данных"
    seconds = float(seconds)
    if not math.isfinite(seconds) or seconds < 0:
        return "нет данных"
    if seconds < 1:
        return f"{seconds:.3f} сек".replace(".", ",")
    whole = round(seconds)
    hours, remainder = divmod(whole, 3600)
    minutes, sec = divmod(remainder, 60)
    if hours:
        return f"{hours} ч {minutes} мин {sec} сек"
    if minutes:
        return f"{minutes} мин {sec} сек"
    return f"{sec} сек"


def human_report(report: dict) -> str:
    """Plain Russian operational report for the printer/operator."""
    values = report.get("seconds", {})
    cfg = report.get("print", {})
    qa = report.get("qa", {})
    rows = [
        "uCode — ОТЧЁТ О СОЗДАНИИ PDF",
        "=" * 42,
        f"Статус: {report.get('status', 'неизвестно')}",
        f"Количество кодов: {report.get('count', 0):,}".replace(",", " "),
        f"Количество PDF: {report.get('files', {}).get('singles', {}).get('count', 0) + bool(report.get('files', {}).get('multipage'))}",
        f"Объём PDF: {(report.get('files', {}).get('singles', {}).get('bytes', 0) + report.get('files', {}).get('multipage', {}).get('bytes', 0)) / 1024**2:.2f} МиБ",
        f"Входной файл: {report.get('input_filename', '')}",
        f"Движок: {report.get('engine', {}).get('name', 'не записан в этом отчёте')} "
        f"{report.get('engine', {}).get('version') or ''}".rstrip(),
        f"Режим: {report.get('mode', '')}",
        f"Размер PDF: {cfg.get('page_mm', ['?', '?'])[0]:.3f} × {cfg.get('page_mm', ['?', '?'])[1]:.3f} мм" if isinstance(cfg.get("page_mm"), list) else "Размер PDF: нет данных",
        f"Белое поле: {cfg.get('quiet_modules', '?')} модуля(ей)",
        "Цвет CMYK (%): " + " / ".join(str(v) for v in cfg.get("ink", [0, 0, 0, 100])) +
        ("; K100, одна чёрная краска" if cfg.get("k100", True) else "; цветной режим CMYK") +
        "; " + cfg.get("description", "векторный QR V1-M") + "; PDF/X не сертифицирован",
        "",
        "ФАКТИЧЕСКОЕ ВРЕМЯ",
        f"Вся операция с QA: {format_duration(values.get('total_including_qa'))}",
        f"Кодирование {cfg.get('symbology', 'QR')}: {format_duration(values.get('code_encoding', values.get('qr_encoding')))}",
        f"Запись отдельных PDF: {format_duration(values.get('write_singles'))}",
        f"Запись общего PDF: {format_duration(values.get('write_multipage'))}",
        f"Проверка качества: {format_duration(values.get('quality_checks'))}",
    ]
    elapsed = values.get("total_including_qa")
    hardware = report.get("hardware")
    if hardware:
        cpu, ram, disk = (hardware[key] for key in ("cpu", "ram", "disk"))
        def gib(value):
            return f"{value / 1024**3:.2f} ГиБ" if value is not None else "неизвестно"
        execution = report.get("execution", {})
        rows.extend(["", "ПРОЦЕССОР И РЕСУРСЫ",
                     f"CPU: {cpu.get('name') or 'неизвестно'}",
                     f"Физические ядра: {cpu['physical_cores']}; логические CPU: {cpu['logical_processors']}",
                     f"Доступно процессу: {cpu['available_physical']} физических / {cpu['available_logical']} логических",
                     f"Источник CPU: {cpu['source']}; ограничения: {cpu.get('reason') or 'см. scope в manifest'}",
                     f"RAM всего / доступно: {gib(ram['total_bytes'])} / {gib(ram['available_bytes'])}",
                     f"Диск: {disk.get('bus') or 'шина неизвестна'}; {disk.get('media') or 'носитель неизвестен'}; свободно {gib(disk['free_bytes'])}",
                     "Скорость диска этим запуском не измерялась.",
                     f"Режим кодирования: {execution.get('backend')}; работники запрошены / использованы: {execution.get('requested_workers')} / {execution.get('effective_workers')}",
                     f"Партия: {execution.get('batch_size')}; завершено значений: {execution.get('completed_values', 0)}",
                     "Запись PDF и QA последовательны. CPU scope/affinity — в manifest или отчёте лаборатории.",
                     f"Предварительная оценка RAM (не измеренный пик/не квота): {gib(execution.get('required_ram_estimate_bytes'))}; резерв {gib(execution.get('os_reserve_bytes'))}", ""])
    generation = report.get("generation")
    if generation:
        rows.extend(["", "РАСЧЁТ ТИРАЖА",
                     f"Строк в TXT: {generation['input_records']}; уникальных значений: {generation['unique_values']}",
                     "Повторы TXT: " + ("только уникальные" if generation['duplicate_policy'] == "unique" else "сохранены все строки"),
                     f"{generation['selected_records']} × {generation['copies_per_value']} экземпляров = {generation['total_codes']} кодов",
                     f"Подготовлено уникальных матриц: {generation.get('encoded_values', 0)}",
                     f"Страниц во всех записанных PDF: {generation.get('pdf_pages_written', 0)}",
                     "Режим «оба» сохраняет один тираж в двух видах PDF; число кодов не удваивается.", ""])
    if elapsed and elapsed > 0:
        rows.append(f"Средняя скорость всей операции: {report.get('count', 0)/elapsed:.2f} кодов/сек".replace(".", ","))
    rows.extend(["", "ПРОВЕРКА",
                 f"Многостраничный PDF: {qa.get('multipage', {}).get('status', 'не выбран')}",
                 f"Отдельные PDF: {qa.get('singles', {}).get('status', 'не выбраны')}",
                 "COMPLETE = проверены структуры и растровые образцы.",
                 "LIMITED = структурная проверка пройдена, растровая недоступна.",
                 "INVALID/ERROR = есть ошибки; причины перечислены ниже.",
                 "",
                 "Времена измерены на машине, где выполнялась эта задача.",
                 "Скорость зависит от размера, носителя, нагрузки и режима.",
                 ""])
    details = list(report.get("errors", [])) + qa.get("multipage", {}).get("errors", [])[:5]
    for item in qa.get("singles", {}).get("first_failures", [])[:3]:
        details.append(f"Файл {item.get('file')}: {item.get('errors')}")
    if details:
        rows.extend(["ПРИЧИНЫ ОСТАНОВКИ / ОШИБОК", *map(str, details), ""])
    return "\n".join(rows)
