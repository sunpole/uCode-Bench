# Внутренние контракты

## Графические отчёты

`graphical_report.chart_model` читает сохранённые сырые повторы без изменения входныхdict/JSON. Сравнения разделены по команде/виду, тиражу, QA, CPU-замерам, source/profile/геометрии и границам времени. Нужны все ожидаемые непрогревочные повторы с требуемыми статусами, безошибочные и с конечным положительным временем; иначе строка остаётся с причиной, без столбца. Научные прямойPDF/объединение и время метода безQA не смешиваются сlauncher_wall лаборатории. CPU берётся только из сохранённых наблюдений, никакого вывода100% по числу процессов. Средние фаз суммируются, service_sum конвейера не складываются.

`embed_graphs` не нормализуетRUNNING-отчёты, браузер строитSVG при открытии финальногоHTML. Измерения trial.seconds не меняются. `write_graphical_copy` читает не больше64МиБ и пишет уникальныйHTML, оригинал не изменяет/не читаетPDF/не запускаетQA. АрхивныеJSON разворачиваются вdata. Встраиваемые данные экранированы отHTML/script injection, выводtextContent. Внешнихскриптов/сети/новыхзависимостей нет. CLI `ucode graphs --input ...` только просмотр. Живой временнойряд этим контрактом не заявляется; подробности GRAPHICAL_REPORTS.md.

## Единые тесты / команды / текстовый архив

`HubNotebook.select` принимает прежние дочерние страницы, выбирает главный hub и вложенную страницу; getter возвращает выбранный leaf. Консоль языка1 преобразует test lab/pipeline/search/scientific в существующие validated configs; `command_text` сериализует каждый пользовательский параметр. CLI/GUI используют один парсер. Весь скрипт валидируется до первого запуска; --plan не генерируетPDF. Очередь последовательная, до32 команд; ошибки/отмена/изменение исходников между командами останавливают остаток. Никакого выполнения shell/Python/произвольных программ.

`archived_test` откладывает вложенные архивы до выхода из внешнего измеряемого теста, затем передаёт финальный100% callback. Архивирование не меняет измеренные секунды илиQA. Успех/ошибка архива — отдельный archive-status.json. ContextVar archive_scope задаётся внутри рабочего потокаGUI; без scope API пишет _test_archive возле результатов. Внутренние lab workers обычной генерации не архивируются как отдельные тесты. Одна text-запись на завершённый тип серии/очередь; все повторы внутри неё сохраняются.

Архив schema1: append-only runs/uuid/report.json, report.html, ОТЧЁТ.txt + локальный catalog.sqlite/index.html. ОграничениеJSON64МиБ, snapshot hash вычисляется по тем же прочитаннымbytes, что разбираются; импорт не меняет оригиналы и не повторяетQA. Уникальный source_key+BEGIN IMMEDIATE защищают от дубликатов/конкурирующих записей. Все HTML-поля escaped; пути/коды/секретные поля очищаются. PDF/входныеTXT/матрицы не включаются. Archive environment отделён от исходногоruntime. Облако/общий сервер в этом пакете отсутствуют по уточнению пользователя. См.TEST_HUB.md/TEST_COMMANDS.md.

## Изолированные тесты конвейера CPU

`PipelineConfig` / `build_pipeline_cases`: явные counts × allocations × schedules × batches × telemetry_modes × repeats, без скрытых прогонов. Allocations физические/логические QR+PDF, PDF=0 полный цикл. CPU-топология, ограничения affinity и пересечение физических ядер валидируются; недоступное SKIPPED с причиной. Equal — фиксированные диапазоны обоих этапов через divmod; queue — следующая свободному. Размер IPC-порции ограничен1–1000 в обоих случаях.

`lab_worker strategy=pipeline` использует собственный `pipeline.prepared_pages` в изолированном процессе, frozen code, RAM/job guards и cooperative cancel. По одному подтверждённому CPU на worker, барьер готовности; только родитель trial может сужать свою маску до PDF-набора. Один окончательный сборщик разделяет набор PDF/общий пул и не получает дополнительного ядра. Нет лимита количества страниц простой константой, есть ограниченные пакеты и дисковый индекс.

`stream_pdf.write_pdf(prepared=...)` принимает `(1-based page index,payload,compressed stream)` вне порядка, проверяет диапазон/уникальность/число страниц и сортирует Kids дисковым индексом. Новый признак inherited_geometry совместим со старыми индексами; DiskReader заново проверяет PDF bytes, геометрию родителя и порядок. Обычный вызов без prepared сохраняет прежний профиль.

`pipeline_wall`/production — создание PDF; launcher_wall включает запуск/импорты/TXT/выбранную QA/завершение. QR/PDF service_sum — перекрывающиеся суммы задач, не wall-фазы; assembler_active — участки записи страниц без ожиданий и хвоста xref. Рейтинг только полных корректных повторов одинакового режима CPU-замеров. Full без raster/при QA FAIL не побеждает; deferred — NOT_RUN/UNVERIFIED/0. Подробности: CPU_PIPELINE.md, WORK_LOG.md.

## Явные ядра генерации и диагностические CPU-замеры

ExecutionOptions.cpus включает process-only pinning: по одному подтверждённому CPU на дочерний QR-процесс. GUI affinity не меняется. Физические наборы требуют разных core IDs, selected CPUs проверяются по текущему разрешённому набору. Effective pool ограничен числом порций, подтверждение — PID+маска результата. Старая serial/28 мигрирует как1, ручное изменение backend/workers сбрасывает простой выбор. Cache16MiB auto / до512MiB max — полезный SQLite-кэш по safe budget; не принудительная allocation и не production quota.

В обычной генерации CPUTrace не создаётся. В тестах telemetry_modes=(cpu)|(off)|(off,cpu); только явный compare удваивает варианты. CPUTrace использует CPU-часы собственного дерева, интервалы0,5с, среднее взвешено временем. Атрибуция конкретному CPU только после подтверждённой single-CPU affinity; parent/unpinned остаётся в aggregate. Min/max интервала не выдаются за мгновенные пики, отсутствующие данные пусты. RAM guard работает в обоих A/B режимах. Сравнения CPU/PDF не смешивают режимы диагностики незаметно.

Lab/search запускают worker из собственной сохранённой .runtime, с отдельным asset_root для проектных зависимостей. Hash проверяется по этой копии; нарушение целостности останавливает серию сразу. Venv/native dependencies не замораживаются. Незавершённый подбор предупреждает перед рейтингом. Подробности и приёмка: [GENERATION_CORES.md](GENERATION_CORES.md).

## Подбор ПК — 28.10.2026

`SearchConfig/run_search` создаёт отдельный pc-performance-search. Прежний scientific не меняется. Свежие изолированные повторы, общие affinity/RAM/cancel guards, fingerprint всех модулей и исходников helpers. Рейтинг по медиане launcher_wall полного согласованного набора повторов; QA FAIL/ошибки/неполные исключены. Deferred=UNVERIFIED/QA0, vector=LIMITED. Staged переносит лидеров и крайние CPU каждого backend/unit; full проверяет всю direct-матрицу. Split проверяет лучший измеренный direct-профиль размера/unit с максимальным выбранным CPU-набором, выбранными частями/режимами/мержерами. Покрытие явно отражено, глобальный оптимум не заявляется.

Split: собственные spawn-процессы, непересекающиеся CPU-подмножества, последовательные диапазоны кодов, один итоговый PDF, QA только финального результата. Без callback честное ожидание merger. Только явный поиск снимает timeout120s; scientific сохраняет120s. parts_creation — wall time, QR/write суммы перекрываются. Временный QR-кэш можно удалить после закрытия, коды/PDF/индексы/manifest остаются. Общий pypdf reader mergedPDF пока может хранить O(N) метаданные под бюджетом процесса. 11 адаптеров —9 семейств, другие QR-кодировщики не объявляются подключёнными. [Методика](PC_PERFORMANCE_SEARCH.md).

## Потоковые тиражи — актуализация28.10.2026

Фиксированный пользовательский максимум10000 снят в production/template/custom lab/preferences/history. Исторические scientific counts/gates остаются прежними. Ниже ограничения старых list API относятся к in-memory пути, а не к пользовательскому тиражу. `batch.STREAM_THRESHOLD=10000` — граница автоматического выбора, не максимальное количество. `stream_data.inspect_codes` возвращает небольшой list или SourceInfo с count/unique/first/last; уникальность индексируется SQLite с ограниченным cache. CountPlan вычисляет итог без массива выбранных/повторённых строк. В GUI большие count планы не требуют всех данных в RAM.

`run_batch` направляет SourceInfo или большой итог в `stream_batch.run_stream_batch`; реализовано для QR/ReportLab encoder, без скрытой замены стороннего адаптера. DiskPlan хранит строки/уникальные значения/матрицы в SQLite. `encode_values(result_store=FrameStore)` сохраняет bounded партии, повторно использует один spawn/thread пул на весь запуск и не собирает result dict/list размераN. Serial имеет тот же bounded путь. `execution_plan(buffered=True)` оценивает активные партии вместо всех матриц. Матрицы сохраняются транзакциями до256 принятых значений, без fsync на каждую строку; финальный commit обязателен.

`stream_pdf` пишет реальные PDF-объекты последовательно, page/xref/content indexes на диске с фиксированным SQLite cache. Compact объединяет прямоугольники и повторно использует Contents одинаковых кодов через дисковый индекс. Большой standard/compact использует uCode DiskPDF/1, не ReportLab Canvas; print.pdf_writer сообщает это. Независимый pypdf-based DiskReader перечитывает actual xref/trailer/root Kids order/count и по одному объекту, затем прежний `_page_matrix`/QR decoder проверяют каждую страницу. Raster first/middle/last сохранён. У stream QA нет Counter/cache размераN, список ошибок ограничен20. Индексы сохраняются как часть результата, нужны для повторной проверки. `audit_stream_job` заново кодирует codes.txt на диске, исходные PDF/manifest неизменны.

No-QA=UNVERIFIED/NOT_RUN/0с, vector=LIMITED, полная QA с renderer=COMPLETE, QA FAIL=INVALID. Ошибки и отмена не получают100%. Preflight проверяет место/оценку RAM, runtime guard — резерв RAM/256MiB свободного диска. Остановка только своих задач, частичные файлы сохранены. Автоматический часовой timeout custom lab снят; явный timeout `_run_trial` сохраняется для проверок. Количество повторов/размер партий/матрицы остаются защищены своими параметрами. Нет заявления о бесконечном файле: classic PDF xref поддерживает offsets<10^10 байт; при исчерпании формата/ресурсов честная ошибка, а не переполнение. Начальная GUI-проверка TXT и создание шаблона пока синхронны. Детали/тесты/обновление: STREAMING_PAGES.md.

CPU UI: Тесты содержит явные переключатели физических ядер/SMT, канонические UNITS не изменены. `show_core_tests` включает physical, сохраняет допустимые CPU choices, удаляет несовместимые, пустой набор заменяет1, не запускает нагрузку. Неизвестная топология не подменяется logical. Обычная генерация сохраняет распределение ОС; production workers не называются physical cores. Дополнительные параметры скрываемые, legacy значения сохранены. ChoiceMenu принимает aliases для старых русских названий после изменения подписей. Границы/проверки: PLAIN_CPU_CONTROLS.md.

## Button settings (28.10.2026)

`ui_choices.ChoiceMenu` связывает кнопку/русские подписи с прежним StringVar, поддерживает single/multiple и legacy label aliases. Canonical CSV/keys остаются внутренним форматом read_form/preferences; GUI не содержит editable enum/CSV полей. Single menu имеет отдельный Tcl StringVar: trace модели не удаляет menu callback до его вызова. Unknown selected values видны и снимаются, неподдерживаемые CPU не получают рабочего допуска.

`NumberSet` добавляет numeric selections через кнопку, custom RAM GiB преобразует в MiB. after_sync гарантирует актуальность видимого количества до refresh/разрешения запуска. В основном custom_config используется видимое одиночное число; сохранение считает его выбранным количеством, другие advanced axes сохраняются. В expanded режиме CSV набор задаётся меню/Добавить, без потери совместимости read_form. Worker/geometry/QA/ресурсные guards не изменены; основной test-control/2–30rows контракт прежний. BUTTON_SETTINGS.md содержит свежие проверки/ограничения/откат.

## Custom test controls (28.10.2026)

`test_controls.custom_config(app)` — одно quantity>=1, selected CPU modes, repeats1–10; один process/backend, auto RAM, multipage с текущими print_settings/profile, normal activity, warmups0. Не использует скрытые advanced lists, одинаковые/недоступные CPU отклоняются до запуска. Numeric CPU сортируются, all-2/all следуют за ними; повторы каждого case последовательны. `read_form/start_lab` остаются для явной расширенной матрицы. LabConfig/scientific defaults3 не изменены, GUI без saved prefs defaults1.

`trial_results.trial_rows(data)` возвращает все непрогревочные planned slots и записанные warmup rows с флагом; неисполненные имеют NOT_RUN/SKIPPED и None timings. `write_trial_results` вызывается один раз в finally run_lab до конечной comparison, вне измерения PDF; сохраняет all-results.html/csv и rawlink. Новые exports не перезаписывают существующие файлы. Рекомендации используют history.case_result QA gates, одинаковые case-параметры и median_with_qa; при близости5% меньше CPU без заявления о статистической значимости.

Primary button в lab означает запуск custom/явной advanced матрицы, на других вкладках — прежнюю генерацию. Simple completion открывает all-results, advanced — comparison; оба сохраняют прежние lab.json/trials. Progress events дополнены run_index/runs_total/repeat_index/cpu_count/cpu_unit; старые поля/таймеры сохранены. CUSTOM_TESTS.md содержит свежие проверки/пределы и два пользовательских примера только как конфигурации, не измеренные большие результаты.

## Resource-lab history (28.10.2026)

`history.scan_history(root)` — ограниченный read-only индекс одного lab-root или папки lab.json; `read_run` валидирует kind/schema/структуру и восстанавливает summary из непрогревочных trials. Только COMPLETE + сохранённая полная QA PASS + ожидаемые count/mode/число повторов дают успешные медианы; время конечное, total>=production. История не доказывает неизменность PDF после QA и не ранжирует разные запуски/ПК. Ошибочные файлы видны отдельно, размер/количество записей ограничены; HISTORY_P07.md задаёт пределы.

`artifact_path` запрещает absolute/drive/.. и resolve-выход из исходного run, `pdf_for_case` читает относительные ссылки непрогревочных trial, не выполняя QA/генерацию. `HistoryView` использует существующий worker и события history/history_error, не заменяет last_* производственного результата. Поиск/фильтр/страницы работают в Tk, видимых строк3/4 по DPI, без scrollbar. Старые scientific/benchmark не подменяются resource-lab; общий сравнительный импорт остаётся TODO.

## Test interface (28.10.2026)

`lab_ui.refresh_cpu_buttons` получает текущие hardware/UNITS и тот же `select_cpus`, что runner. Кнопки — варианты серии, не сумма; all/all-2 раскрываются по unit. Недоступные кнопки остаются disabled после busy/idle, предпочтения не урезаются скрытно. Новый GUI default physical/1, если топология известна, старые saved prefs сохранены. `show_lab` обновляет hardware из ОС; fallback не выдумывает физические ядра/CPU IDs. Preview считает repeats+warmups, статистика по-прежнему исключает warmup.

`open_reports.open_html_report(path)` для Windows читает executable HTTPS/HTTP association через AssocQueryStringW и запускает с отдельным file URI аргументом без shell. Нет изменения registry/ассоциаций и fallback к .html editor. Ошибки показывает контроллер, TXT/PDF/папки остаются в обычных приложениях. Оба GUI используют helper. На других ОС — webbrowser.open_new_tab. Физическое окно браузера/визуальная приёмка пользовательские; TEST_INTERFACE.md содержит свежие проверки и ограничения.

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

## Видимый набор P02 и ранний P10

- `generation_plan.build_plan(values, copies_per_value=1, duplicate_policy="preserve", types=("qr",))`: source_rows/unique/copies/per_type/total отдельно от repeats. Сохраняются порядок и ведущие нули. План ограничен 10000 входных строк/итоговых кодов, потребляет максимум 10001 элемент перед отказом. `unique` сохраняет первые появления.
- `batch.iter_codes`: ленивый валидатор строк UTF-8/BOM, default max_lines=10000/max_bytes=2 MiB; max None для отдельного потокового сканирования. Один read не больше 4097 bytes, отмена между строками. `load_codes` — совместимая list-обёртка, не безлимитный режим генерации.
- `run_batch(..., copies_per_value=1, duplicate_policy="preserve")` сохраняет прежние вызовы. Encoder получает уникальные значения, immutable frames используются для повторов. Порядок выходных payload проверяется, каждый PDF QA выполняется как прежде. Старый научный worker/profile этим кэшированием не менялся.
- Исходный snapshot — source-codes.txt, фактические страницы — codes.txt. generation содержит плановые encoding_values_planned и подтверждённые encoded_values/pdf_pages_written. Count — логический тираж; обе формы PDF не удваивают число кодов, все физические страницы учтены отдельно.
- `GenerationPreferences` и `load_user_preferences` расширяют schema v2. `load_preferences` возвращает прежнюю тройку; `save_preferences` без generation сохраняет уже записанные новые параметры. Поля записываются атомарной заменой только проектной .local-state.
- `ui_theme` задаёт только тёмную тему Tk; `ui_layout` строит компактные вкладки. BatchWindow сохраняет бизнес-логику/worker queue. Системные file/folder dialogs допустимы; печать/цвет/merger/help встроены в главный экран. Будущие disk-temp параметры не показываются как работающие.
- Автоматический smoke теперь включает 2/7/2/6 страниц и copies/dedup. Визуальную приёмку выполняет пользователь; большие сценарии не запускаются автоматически.
# CPU snapshot и encoding execution (P04 / первый P05)

`hardware.inspect_hardware(destination)` читает сведения без установки пакетов и изменения ОС. CPU logical/physical/available разделены; Windows group/core и Linux package/core не суммируются с SMT. Отсутствующие данные остаются null с source/reason/scope. Полные job/cgroup v1 quotas и thread masks не заявляются известными. Disk bus/media — сведения драйвера/sysfs, не MB/s; нет серийников и пользовательских путей. `probe_directory` — только явная проверка 32 КиБ write/flush/fsync в своей tempfile, не дисковый benchmark.

`ExecutionOptions(backend, workers, batch_size)` разрешает serial/process/thread. `execution_plan` проверяет число доступных CPU, сокращает пул до числа партий, оценивает RAM с резервом до создания output. При неизвестной RAM параллельный режим отклоняется. В обычной генерации это preflight, не runtime memory quota. Предел 10000 итоговых кодов сохраняется; все matrices пока остаются в RAM до записи. Ограниченная affinity/RAM лаборатории описаны ниже; автоматический выбор лучшего production-профиля не включён.

`encode_values` создаёт spawn-процессы только по выбранному process backend. На каждый worker не более одной партии в IPC; номер партии/порядок payload проверяются. Результат возвращается в порядке входного списка уникальных значений. Worker не получает финальный PDF/Tk; writer/QA остаются последовательными. Прогресс кодирования считается по полученным и принятым результатам, не по отправленным задачам. Отмена/EOF/аварийный exit закрывают и reaping-ят только собственный пул; нет успешного статуса при ошибке.

Manifest `execution` различает requested/effective workers, completed_values, worker_pids, max_in_flight_values, batch_size и оценку RAM. Эти поля не подменяют generation/encoded_values, которое подтверждается после приёмки полного encoder-результата. `seconds.code_encoding` включает spawn, импорт worker, IPC и завершение пула; научный worker/timer не изменён. `hardware` — снимок перед запуском, свободная RAM/диск могут измениться. Предпочтения v1/v2 читаются с defaults serial/1/32; старый API сохранения сохраняет новые поля.

## Resource lab (первый P05–P08)

`LabConfig` и `run_lab` создают отдельный kind resource-lab; обычная генерация и исторические scientific gates не подменяются. Counts 1–10000; повторов по умолчанию 3; прогрев исключён. Оси CPU unit/count, serial/process/thread и RAM budgets; геометрия/цвет/формат текущего окна постоянны в серии. Добавлены оси PDF standard/compact и activity normal/minimal, defaults сохраняют прежний standard/normal. Матрица ограничена 4096 конфигурациями, не числом CPU. Preview показывает реальные eligible/skipped/runs и оценку диска; без калибровки время null. Эквивалентные CPU masks внутри одной unit/PDF/activity сравниваются один раз.

Каждый повтор — новый subprocess. Affinity применяется только внутри него, подтверждается ОС и наследуется workers; GUI/чужие процессы не меняются. Physical означает один логический представитель каждого ядра. All-2 не резервирует ресурсы эксклюзивно. Windows multi-group forced affinity получает SKIPPED, Linux задаёт собственным потокам sched_setaffinity. Backend не расширяет унаследованную маску. ThreadPoolExecutor поддержан только для QR encoding, не общего PDF canvas; GIL ограничение остаётся.

RAM max = available − max(1 GiB, 10% available); auto/80% = 80% safe, 50% = половина; явный MiB не превышает safe. Память выделяется только под полезные данные. Windows own nested job ограничивает aggregate commit и убирает дочернее дерево при закрытии; Linux sampled RSS/cooperative cancel, не kernel quota. Пиковый наблюдаемый simultaneous tree RSS не равен физически уникальной памяти, shared pages могут дублироваться; интервал/ограничения метрик фиксируются. Малый budget/несовместимый CPU — SKIPPED, исчерпание резерва/бюджета — RESOURCE_LIMIT. Пул/данные не урезаются незаметно; Disk/Hybrid/spill отсутствуют.

Stop передаётся через собственный cancel.flag, затем Event, после 15 s кооперативного ожидания — только собственный job/process group. Таймаут попытки 3600 s — ERROR. Частичные files/trials/reports сохраняются. JSON обновляется атомарно уникальным staging с ограниченным retry Windows reader lock; необязательные progress-обновления могут быть пропущены, конечный отчёт обязателен.

Production timer фиксируется wall clock до QA после выбранных PDF/метаданных/хешей; QA отдельно, total_including_qa отдельно, launcher_wall включает контрольную оболочку. Close/OS-cache, fsync PDF не заявляется. Python/GIL, engine version, source_digest и comparison_profile_hash защищают от несопоставимых параметров; изменившаяся сборка во время серии — ошибка. CSV содержит полный профиль/оборудование, TXT/HTML — понятную сводку.

Ранжируются только полные COMPLETE/QA PASS повторы; INVALID/LIMITED/ERROR/RESOURCE_LIMIT/CANCELLED/SKIPPED не побеждают. Скорость/ускорение основаны на измеренной медиане; serial1 baseline обязателен для speedup. Рекомендация с QA выбирает быстрее всех и меньше CPU/меньший budget в пределах 5% от лучшего; 5% не является тестом статистической значимости. Результаты двух кодов не экстраполируются на большие серии или другие ПК. Визуальные проверки/большие нагрузки — пользовательские.

## PDF optimization

`PrintSettings.pdf_profile=standard|compact`; standard прежний Canvas, compact `ucode.compact_pdf` с общими inherited geometry/resources и Contents для одинаковых матриц. `run_batch(qa_mode=full|vector|deferred, activity=normal|minimal)` по умолчанию прежний full/normal. Deferred никогда не получает COMPLETE: UNVERIFIED, qa.status NOT_RUN, quality_checks=0. Vector или отсутствие renderer — LIMITED. Минимальный режим исключает SHA и source-codes snapshot, но codes.txt/manifest/отчёт, input/resource/cancel guards сохраняет. 100% в явно ограниченном режиме означает завершение выбранной операции, качество отображается отдельно.

`audit.audit_job(job)` заново получает ожидаемые матрицы из codes.txt и независимо проверяет PDF, пишет новый audits/qa-…; исходные manifest/PDF не изменяются. QA-кэш содержит только общие indirect Contents в одном reader; каждая страница всё равно проходит geometry/resources/expected-payload checks. Кэширование уникальных потоков отсутствует. Список операторов/допуски QA сохранены.

LabConfig.qa_mode=full|vector|deferred (default full) передаётся из общего переключателя GUI или CLI --qa в request каждого lab worker, в том числе для прогрева. Принудительная full QA снята по запросу пользователя. Deferred — QA NOT_RUN, quality_checks=0, trial/case/run UNVERIFIED; vector — LIMITED. `qa_policy.limited_trial` разрешает статистику только для полных согласованных записей выбранного режима без ошибок, с реальными положительными временами и ожидаемым числом кодов. История пересчитывает медианы, не запускает QA и не повышает эти статусы до PASS. `median_operation_seconds` — измеренное время выбранной операции; `median_with_qa_seconds` у неполных режимов null. Legacy total_including_qa в исходных временах сохранён для совместимости: включает только фактически выбранные этапы.

Проверенные рекомендации, serial1 QA speedup и парные отношения PDF/activity по-прежнему допускают только PASS всех повторов. Отдельная сводка времени UNVERIFIED/LIMITED явно указывает охват проверки и сравнивает только одинаковые параметры; с проверенным рейтингом не смешивается. CSV дополнен qa_mode/median_operation_s, прежние поля сохранены. PDF bytes — реальные размеры выбранных PDF. Исторические scientific gates остаются с полной QA и явно отклоняют просьбу выключить её, направляя в lab/generate. CLI возвращает 2 для созданного UNVERIFIED/LIMITED результата, не 0 QA PASS. Границы: OPTIONAL_PDF_VERIFICATION.md; исходный слой PDF: PDF_OPTIMIZATION.md.
