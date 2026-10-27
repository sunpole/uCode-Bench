"""Production counts; copies and symbologies never mean benchmark repeats."""
from dataclasses import dataclass
from itertools import islice

MAX_CODES = 10000


@dataclass(frozen=True)
class GenerationPlan:
    input_records: int
    unique_values: int
    selected_values: tuple[str, ...]
    copies_per_value: int
    duplicate_policy: str
    types: tuple[str, ...]

    @property
    def duplicate_records(self):
        return self.input_records - self.unique_values

    @property
    def codes_per_type(self):
        return {kind: len(self.selected_values) * self.copies_per_value for kind in self.types}

    @property
    def total_codes(self):
        return sum(self.codes_per_type.values())

    def iter_values(self):
        for value in self.selected_values:
            for _ in range(self.copies_per_value):
                yield value

    def to_dict(self):
        return {"input_records": self.input_records, "unique_values": self.unique_values,
                "duplicate_records": self.duplicate_records, "selected_records": len(self.selected_values),
                "copies_per_value": self.copies_per_value, "duplicate_policy": self.duplicate_policy,
                "codes_per_type": self.codes_per_type, "total_codes": self.total_codes,
                "basis": "unique_values" if self.duplicate_policy == "unique" else "source_rows"}


def build_plan(values, *, copies_per_value=1, duplicate_policy="preserve", types=("qr",)):
    if isinstance(copies_per_value, bool) or not isinstance(copies_per_value, int) or not 1 <= copies_per_value <= MAX_CODES:
        raise ValueError("Экземпляров: целое число от 1 до 10 000")
    if duplicate_policy not in ("preserve", "unique"):
        raise ValueError("Повторы TXT: сохранить строки или выбрать только уникальные")
    kinds = tuple(types)
    if not kinds or any(not isinstance(kind, str) or not kind for kind in kinds) or len(set(kinds)) != len(kinds):
        raise ValueError("Выберите неповторяющиеся типы кодов")
    source = tuple(islice(values, MAX_CODES + 1))
    if len(source) > MAX_CODES:
        raise ValueError("В текущем плане максимум 10 000 входных строк; большой поток требует другого способа обработки")
    if not source:
        raise ValueError("База пуста")
    unique = tuple(dict.fromkeys(source))
    plan = GenerationPlan(len(source), len(unique), unique if duplicate_policy == "unique" else source,
                          copies_per_value, duplicate_policy, kinds)
    if plan.total_codes > MAX_CODES:
        raise ValueError(f"Итог {plan.total_codes:,} кодов превышает безопасный лимит 10 000".replace(",", " "))
    return plan
