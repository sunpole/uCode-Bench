# Внутренние контракты

Актуальные изменения интерфейса и API v0.2 описаны в последнем разделе; ранние разделы сохранены как история методики.

Проект называется uCode; приложенное ТЗ uBarcodeBench задаёт первый эксперимент.

- `config.Experiment`: count=200 (2 для smoke, 1000 только после допуска), start=200000000000, repeats=3, module_mm=0.5, quiet_modules=4, threshold_seconds=120.
- `config.QRFrame`: payload: str, matrix: tuple[tuple[bool]], version=1, error='M'. Обычный QR 21x21 для 12 цифр.
- `data.generate_numbers(config) -> list[str]`, `write_numbers(numbers, path)`.
- `qr.encode_numbers(numbers) -> list[QRFrame]`: доступный ReportLab QR encoder; уровень M, numeric, version 1. Segno отсутствует; установка не выполняется.
- `pdf.write_pdf(frames, path, config)`: векторные прямоугольники, CMYK (0,0,0,1), сторона (21+8)*0.5=14.5 мм.
- `mergers.available_adapters() -> list[Adapter]`: name, `probe() -> dict` с available/reason/version, `merge(inputs: list[Path], output: Path)`; ошибки через исключения. Адаптеры не устанавливают зависимости.
- `quality.check_pdf(path, frames, config, *, render_samples=True) -> dict`: status PASS/FAIL, errors list[str], pages_checked int, decoded_samples list[dict], прочие диагностические поля. Проверять все страницы структурно и по матрицам; контрольные изображения из PDF декодировать независимо.
- `benchmark.run_experiment(output_root: Path, config: Experiment, progress=None, cancel=None, allowed_methods=None) -> Path`: создаёт новый каталог запуска, возвращает его; `progress(message: str)`; `cancel` threading.Event или None; allowed_methods ограничивает этап 1000.
- `report.write_reports(result: dict, directory: Path) -> None`: report.json, report.csv, report.html. Верхние поля schema_version, status, config, environment, stages, methods, run_directory, notes. Каждая строка methods: name, category (merge/direct), status (PASS/INVALID/ERROR/SKIPPED), reason, trials (список словарей), median_seconds, spread_seconds, eligible_for_1000, output_bytes. trial: seconds, cpu_seconds, peak_rss_bytes, output_bytes, qa, path. stages: qr_encoding, single_files, direct_pdf (списки замеров), overall_seconds. Прямая генерация включает QR-кодирование+PDF; QR-кодирование дополнительно замеряется отдельно.
- `gui.main()` открывает локальный tkinter GUI с четырьмя кнопками и отменой. Импорт benchmark отложенный. GUI работает в worker thread, сообщения через queue.
- `python -m ucode doctor|create|benchmark|gui`; benchmark `--count 2|200|1000`, `--qualifying-report` обязателен для 1000; `--output` задаёт корень уникальных запусков.

QA вне времени метода. Три запуска без разогрева. Объединение читает один и тот же набор готовых PDF последнего отдельного этапа. CPU — процессные секунды. Для каждого замера создаётся свежий worker; импорт engine modules до начала таймера. RAM — сохранённый ОС пик Working Set/RSS за жизнь worker, включая импорт/загрузку входов, но без QA. Внешний Win32 процесс учитывается по сохранённому handle (GetProcessTimes/GetProcessMemoryInfo), сумма индивидуальных RAM пиков помечается верхней оценкой. На другой ОС внешние метрики могут быть null с пояснением.

## Расширение по запросу 2026-10-27

Пользователь явно разрешил проектную установку, оба масштаба 200/1000 и публичную копию. Исходный запрет установки без запроса соблюдается: разрешение относится к этой задаче и этому проекту. Автоматический переход suite к 1000 разрешён текущим запросом **только для методов с QA PASS и медианой <120 с на 200**; gate и повторная проверка сохранённого отчёта сохраняются. В обычном GUI отдельная кнопка остаётся.

### Установка и обнаружение

- Точка установки: `scripts/install_engines.py`; изолированные `.venv/`, `tools/`, `node_modules/` внутри корня uCode.
- Native tools manifest: `tools/engines.json`. Он должен сохранять выбранные пути/версии, источники и хеши; обнаружение native adapters использует локальные инструменты без системной регистрации.
- `scripts/launch.ps1` остаётся launcher, установка не должна выполняться при обычном открытии GUI/doctor.
- Скачивание только из проверенных официальных источников/реестров; SHA-256/SHA-512 или package integrity проверяется и сохраняется. Глобальные пакеты, PATH и registry не меняются.
- В плане 11 merger adapters: qpdf, mutool, PyMuPDF, pikepdf, pypdf, pdfrw, pypdfium2, pdfcpu, pdf-lib, PDFBox, PDFsharp. Прямая генерация — отдельная категория.
- PDFsharp helper использует .NET 8 и pin `PDFsharp 6.2.4` (MIT); найденный latest 6.5.0 имеет другую лицензию (AGPL) и в этот pin не подменяется.
- Семейства qpdf/pikepdf и MuPDF/PyMuPDF общие. Реестр/отчёт должны позволять отличить adapter от kernel family и способа вызова; одинаковое ядро не считается двумя независимыми реализациями.
- Native/Node/JVM/.NET argv не должен включать 1000 длинных абсолютных путей: использовать manifest, argument file либо cwd + короткие относительные имена с проверкой Windows limit. Входной порядок неизменен.

### Общий pipeline и артефакты

- Точка полного запуска: `scripts/full_comparison.py`: установка → tests/doctor → suite 200 → gate → 1000 допущенных методов → сравнение → локальный экспорт → разрешённая публичная копия через `gh`.
- Все результаты suite находятся в новом уникальном каталоге под `output/comparisons/`, а полный локальный архив — под `output/exports/`. Старые `output/runs/` и старые отчёты сохраняются.
- Каждый масштаб сохраняет свои TXT, исходные и итоговые PDF, QA PNG, запросы/метрики worker и HTML/CSV/JSON. Сводное сравнение связывает масштабы и показывает median/spread/CPU/RAM/bytes/QA по каждому adapter.
- QA и установка не включаются в время метода. CLI/Node/JVM startup, если он включён, должен явно отличаться от Python import, исключённого до timed API call. Полный elapsed pipeline хранится отдельно.
- Любая ошибка QA остаётся INVALID. Недоступность — SKIPPED, ошибка вызова — ERROR. Не присваивать PASS по существованию выходного файла и не вычислять время 1000 из времени 200.
- Подготовленный pipeline не означает завершённый benchmark. До получения файлов и readback статусы новых установок/замеров/публикации должны быть pending/unverified.

### Публичная копия

Назначение: новый `sunpole/uCode-Bench`; старый `sunpole/uCode` с EAN-13 не менять. Исходники и очищенная сравнительная сводка входят в Git; полный подготовленный ZIP — release asset. `.venv`, tools binaries, node_modules, secrets, credentials и локальные machine paths не должны случайно попасть в публичные данные. Локальные оригинальные отчёты сохраняются; публичный экспорт готовится отдельной копией с очищенной метаинформацией. Успех публикации подтверждается фактической public visibility, remote/revision и доступностью release assets; их предполагаемое наличие не является доказательством.

## Актуализация v0.2 — единый UI и научный размер 10000

- `python -m ucode gui|batch` открывает `batch_gui.BatchWindow`: один операторский экран, очередь событий из рабочего потока, Tk вызывается только главным потоком. Старый `gui.py` сохранён для совместимости импортов. Главные launcher-файлы открывают одинаковый новый экран.
- `batch.load_codes`: UTF-8/BOM, ровно 12 ASCII-цифр в строке, сохраняются порядок/нули/дубликаты; максимум 10000 строк и 2 МиБ. `run_batch(input_txt, output_root, mode, settings, progress, cancel, events)` создаёт уникальный каталог. Производственные результаты не участвуют в научном рейтинге.
- `PrintSettings`: модуль 0.25–2 мм, поле 4–20 модулей, `ink=(C,M,Y,K)` по 0–100%, полностью белый цвет запрещён. CMYK записывается и независимо проверяется; только `(0,0,0,100)` означает K100. Scientific `Experiment` сохраняет фиксированные параметры K100.
- `app_settings` читает/атомарно сохраняет только `.local-state/user-settings.json`. Повреждённый файл даёт предупреждение и безопасные значения по умолчанию; до явного сохранения исходный файл остаётся нетронутым.
- `Generator` описывает validate/default_settings/encode/write_pdf/verify и входной формат. `QRGenerator` делегирует существующей реализации. EAN-13/Code128/DataMatrix недоступны и явно отклоняют вызовы.
- `events(event)` принимает stage/done/total/percent/elapsed/speed и необязательный unit. `ProgressTracker.step` считает реальные выполненные элементы и ограничивает общий процент 99.9. `finish` вызывается после QA PASS и сохранения отчёта. Отмена/ошибка/LIMITED не получают 100%. В прямом научном PDF кодирование и запись считаются отдельными действиями.
- QR encoder, PDF writer и QA поддерживают `on_progress(done,total)` и `cancel`. Worker публикует фактические счётчики в проектные progress-файлы. Для стороннего merger без callback процент объединения изменяется после возврата движка; секундомер работает, отмена ожидает текущий вызов. Это ограничение API движка, промежуточные проценты не придумываются.
- `scientific.run_scientific(output_root, size, methods, cancel, events, progress)` сохраняет отдельные scientific.json/ОТЧЁТ.txt. size=200/1000/10000/"all"; большой размер выполняет необходимые предыдущие этапы. Три повтора сохраняются; 200→1000 требует QA PASS, хеши и медиану <120 с; 1000→10000 требует три QA PASS и неизменённые артефакты. `load_qualifying_methods(report, target_count=1000)` сохраняет прежний вызов и добавляет target_count=10000.
- `resources.check_resources` ограничивает 1–10000, проверяет доступность диска, свободное место и доступную RAM перед работой. Это консервативная оценка, не гарантия будущих ресурсов. Лимит до миллионов не повышается.
- Префикс имён отдельных PDF имеет `max(4, len(str(count)))` цифр: лексикографический порядок сохраняется и на 10000. Старые результаты не переименовываются.

Доказательства и ограничения: [V02_VERIFICATION.md](V02_VERIFICATION.md). Полная матрица всех движков на 10000 не считается измеренной по одному производственному PDF или orchestration unit test.

## Комплексная модернизация, P01

- Актуальное ТЗ: MODERNIZATION_SPEC.md; зависимости и критерии 11 патчей: MODERNIZATION_PATCHES.md. Новая инструкция: только малые автоматические нагрузки, ручная/визуальная проверка у пользователя.
- `engines.GenerationEngine`: info/prepare/encode/write_pdf/write_singles. `EngineInfo` отдельно описывает версию, доступность, типы кодов, цветовые модели, PDF/output/execution режимы, vector/streaming. Новый реестр не смешивается с merger adapters.
- Модуль типа кода предоставляет validate/default_settings/validate_settings/describe_settings/verify; QA выполняется независимо от выбранного encoder/PDF writer. QRGenerator.encode/write_pdf сохранены как совместимые методы через текущий движок.
- `batch.run_batch(..., generator="qr", engine="reportlab")` сохраняет прежние вызовы. Неподдерживаемые возможности отклоняются до создания outputs. Порядок/количество frames.payload сравниваются с TXT. `code_encoding` — каноническая метрика, QR сохраняет старый alias `qr_encoding`. Новые поля manifest: generator, engine, pipeline_contract.
- Worker исторического профиля использует этот же текущий движок; фиксированный стандарт и импорты до таймера сохранены. Новая настраиваемая лаборатория пока TODO, не подменяет старый профиль.
- Progress event: speed — наблюдаемая скорость по короткому окну; average_speed — средняя наблюдаемого этапа; speed_window_seconds — фактический интервал наблюдения. До первой пары наблюдений скорость 0. Память счётчика ограничена; новая пара stage/base сбрасывает окно. Percent остаётся монотонным; finish после сохранения отчёта/QA.
- Автопроверка настоящих PDF: scripts/verify_smoke.py, только 2/7 значений. Большие verify_v02.py и научные сценарии не вызываются автоматически из CI.
