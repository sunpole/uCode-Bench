# Журнал uCode

## 2026-10-27 — первый этап

Исходная папка `016_uCode` была пустой, Git-репозитория не было. Пользователь передал ТЗ uBarcodeBench и название проекта uCode. Принято: реализовать первый модульный QR/PDF-бенчмарк под именем uCode, без других кодировок и без автоматического этапа 1000.

Окружение проверено на этом ПК: Xeon E5-2680 v4, 28 logical CPUs, 17 079 623 680 байт RAM, Windows 10. Системный Python 3.13 без нужных пакетов. В уже установленной среде Codex: Python 3.12.14, ReportLab 4.4.9, pypdf 6.10.0, Pillow 12.3.0, Poppler. Segno, qpdf, mutool, PyMuPDF, pikepdf отсутствуют. Ничего не устанавливалось.

Реализованы M01–M09, независимые merger adapters, CLI и tkinter GUI. Время метода измеряется в отдельном свежем процессе; импорт и QA вне времени метода. Проверка каждой страницы сравнивает матрицу и декодирует payload независимо от encoder; raster controls читаются из PNG готового PDF. Параметры фиксированы. Результаты защищены уникальными каталогами и exclusive report writes.

### Свежие проверки

- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\launch.ps1 doctor` — exit 0, core_ready=true, только pypdf доступен из merger adapters.
- `python -m unittest discover -s tests -v` — 38 tests, PASS (до дополнительной проверки GUI).
- `python -m ucode benchmark --count 2 --output output\smoke` — exit 0, COMPLETE; direct и pypdf PASS, недоступные адаптеры SKIPPED. Ни один smoke-результат не допускается к 1000.
- Computer Use: окно `uCode — QR-бенчмарк` найдено; начальный capture `FrameArrived timed out`, повтор после нового выбора/активации `window capture timed out`. Визуальная проверка и физические клики не подтверждены.
- `launch.ps1 create` — exit 0, создан отдельный набор 200 PDF, TXT и inputs.json; все 200 страниц QA PASS, контрольные QR декодированы. Каталог `output/runs/inputs-200-20261027-133555-5a2e7465/`.
- Дополнительные Tk controller tests проверяют вызов кнопок, фоновый worker, ошибку в отчёте, отмену и начальную блокировку 1000. Первый вариант теста ожидал незамокированное модальное окно и был остановлен; затем исправлено ожидание русского сообщения. Отдельный прогон выявил финализацию старых Tk fixtures в worker thread (Tcl_AsyncDelete); teardown теперь уничтожает Tk и собирает циклы в главном потоке. Это исправление тестового lifecycle, не скрытый успешный повтор.
- После исправления teardown: **42 tests, PASS**, exit 0; лог `output/verification/tests-20261027-1337.log`. Финальная проверка после устранения гонки закрытия GUI: **43 tests, PASS**, exit 0; лог `output/verification/tests-20261027-1340.log`. Physical GUI input этим не подтверждается.
- HTML-отчёт визуально открыт в in-app browser через временный localhost server: заголовок, параметры, COMPLETE и таблица pypdf/PASS/0,3260 с отображаются корректно. Временные server/tab и созданный для проверки idle GUI process закрыты.

### Реальный бенчмарк 200

Каталог: `output/runs/run-200-20261027-133137-964192f2/`. Команда: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\launch.ps1 benchmark --count 200`, exit 0. Статус COMPLETE, полный elapsed вместе с QA 24,0848 с.

| Этап/метод | Три времени, с | Медиана, с | max−min, с | QA / допуск |
| --- | --- | --- | --- | --- |
| QR encoding | 0,802091 / 0,794347 / 0,814770 | 0,802091 | 0,020423 | подготовка |
| 200 отдельных PDF (без QR encoding) | 0,524473 / 0,509412 / 0,521849 | 0,521849 | 0,015061 | все 600 файлов PASS |
| Прямая генерация (QR + PDF) | 1,095049 / 1,101440 / 1,094727 | 1,095049 | 0,006713 | PASS / допущен |
| pypdf: объединение готовых | 0,334714 / 0,326001 / 0,325373 | 0,326001 | 0,009342 | PASS / допущен |
| qpdf, MuPDF/mutool, PyMuPDF, pikepdf | не измерено | — | — | SKIPPED, отсутствуют |

Direct PDF: 233 480 байт, peak Working Set 34 729 984 байт максимум по повторам. pypdf: 269 064 байт, peak Working Set 38 121 472 байт максимум. Каждый из шести итоговых PDF проверен на всех 200 страницах, 18 контрольных PNG декодированы из готовых результатов; ещё 9 PNG из трёх наборов одностраничных PDF. Два контрольных PNG (первый direct, последний pypdf) визуально проверены: модули чёткие, поля чистые. HTML, CSV, JSON сохранены. `load_qualifying_methods(report.json)` заново подтвердил Direct PDF и pypdf, сверив TXT, QA и SHA-256. **1000 не запускались.**

### Выявленные и исправленные случаи

- Импорты Python merger engines перенесены до начала timed scope.
- Входной TXT читается обратно, сверяется с последовательностью и payloads; сохраняется SHA-256.
- Допуск проверяет ровно три повтора, raster controls, стандартный count=200, source QA и неизменённые файлы.
- Пустой список source QA не считается PASS.
- Ненулевые даже малые PDF transforms и page transparency Group отклоняются.
- GUI/CLI читают статус отчёта; ошибка или отмена не выдаётся за успех.
- После бенчмарка устранена гонка закрытия GUI: событие done могло приходить раньше выхода worker. Окно теперь дожидается фактического завершения потока; main сохраняет Application до конца mainloop. Добавлен регрессионный тест. Измеряемые QR/PDF/merge-модули после бенчмарка не менялись. `source-manifest.json` фиксирует хеши исходников до этой GUI-правки.

### Ограничения и следующий шаг

- Движки SKIPPED не проверены реальным объединением; тесты их argv/ошибок не заменяют runtime.
- QA decoder — чистый V1/M/numeric12; не общий сканер и без исправления ошибок. Физическая печать и PDF/X не проверялись.
- mutool на 1000 длинных путях может упереться в Windows argv и завершится явной ERROR; qpdf использует response arguments.
- GUI нуждается в визуальной проверке, если захват экрана недоступен.
- Этап 1000 — только отдельным действием пользователя с квалифицирующим отчётом.
- Git commit/push не выполнялись, репозиторий не инициализирован.

## 2026-10-27 — расширенное сравнение и публичная копия: подготовка

Новый прямой запрос пользователя: установить максимально практичный набор движков, найти дополнительные проекты на GitHub, сравнить на 200 и 1000 файлах, сохранить результаты/отчёты локально и сделать публичный GitHub-репозиторий. Этот запрос разрешает установку и последовательный suite 200 → 1000 без повторного вопроса. Условие QA PASS + median <120 с на 200 для допуска метода к 1000 сохраняется.

Предыдущий раздел журнала — историческая запись первого ограниченного запуска. Его 24,0848 с полного elapsed, pypdf 0,326001 с и direct 1,095049 с не считаются результатами нового набора движков. **Новых измеренных результатов на момент этой записи нет.**

### Принятый объём

- Устанавливать только в корне проекта: Python `.venv/`, native `tools/`, Node `node_modules/`; не менять глобальные пакеты, системный PATH или registry.
- План: 11 merger adapters — существующие qpdf/mutool/PyMuPDF/pikepdf/pypdf и дополнительные pdfrw, pypdfium2/PDFium, pdfcpu, pdf-lib/Node, Apache PDFBox/Java, PDFsharp/.NET. Прямая генерация измеряется отдельно.
- Источники/версии/хеши исследованы в `docs/ENGINE_RESEARCH.md`. Проверка сайта/PyPI не считается выполненной установкой.
- pikepdf/qpdf и PyMuPDF/mutool имеют общие kernel families; количество адаптеров не выдаётся за количество независимых ядер.
- Для PDFsharp выбран .NET 8 helper с пакетом 6.2.4 (MIT). Latest 6.5.0 найден с AGPL; смена лицензии не скрывается за словом «latest».
- Ghostscript остаётся дополнительным исследованным кандидатом. Официальный installer пишет registry даже при заданном `/D`; без проверенной portable-распаковки его нельзя устанавливать как якобы изолированный ZIP. Фактическое включение/пропуск должен появиться в installation manifest.

### Новые точки входа и сохранение

- `scripts/install_engines.py`: подготовка локального окружения; manifest `tools/engines.json` с native paths, версиями и данными происхождения.
- `scripts/full_comparison.py`: orchestrator установки, tests/doctor, новых 200/1000 запусков, сравнения, экспорта и разрешённой публикации через `gh`.
- Уникальные suite-каталоги: `output/comparisons/`; полные локальные архивы: `output/exports/`. Исходные/итоговые PDF, PNG QA и сырые метрики остаются на ПК; старые прогоны не удаляются.
- GitHub: новая публичная копия `sunpole/uCode-Bench`, поскольку `sunpole/uCode` уже занят старым EAN-13 проектом. Старый репозиторий не изменять. В Git публикуются исходники и очищенные summaries; полный подготовленный ZIP — release asset. Credentials и machine paths очищаются в отдельной публичной копии, локальные оригиналы сохраняются.

### Статус и доказательства

На момент документирования **pending**: завершение установки, fresh doctor всех адаптеров, tests после интеграции, реальные замеры новых 200/1000, полный локальный ZIP, создание/проверка public repository и release. До фактического readback не записывать ожидаемые скорости, число успешно установленных движков или URL ещё не созданного release как подтверждённые результаты.

Следующий исполнитель должен прочитать этот раздел, `docs/CONTRACTS.md`, исследование движков и состояние installation/suite manifests, затем продолжить с первого ещё не подтверждённого этапа. Не переустанавливать и не перезапускать успешные шаги вслепую; сохранять исходную ошибку и точную причину SKIPPED/ERROR/INVALID.

### Preflight перед расширенной установкой

- Подтверждены GitHub connector и GitHub CLI: `sunpole`, id 13759759. `sunpole/uCode` — публичный старый EAN-13 проект; `sunpole/uCode-Bench` на момент проверки отсутствует.
- Проверены PyPI metadata HTTP 200 для всех закреплённых версий: ReportLab 4.4.9, pypdf 6.21.2, Pillow 12.3.0, PyMuPDF 2.0, pikepdf 10.17.0, pypdfium2 5.14.0. Native pins и SHA-256 сверены по official GitHub release assets; PDFBox 3.0.8 SHA-512 сверён по официальному sidecar.
- После интеграции **74 tests, PASS, 3 SKIPPED** в исходной bundled-среде; лог `output/verification/tests-expanded-preinstall-20261027.log`. После установки тесты будут выполнены заново в `.venv` с реальными дополнительными engines.
- Win32 child counters проверены реальным коротким Python-процессом: child_cpu_seconds=0,046875 и child_peak_rss_bytes=11 427 840. Внешний startup включён в замер; Python library imports предварительно загружаются.
- Независимое чтение setup/publication scripts выявило и исправило bare import, Windows npm quoting, риск dotnet first-run registry/certificate/PATH changes, публикацию PARTIAL под COMPLETE-заголовком и неполный source manifest. Установщик не запускает сторонние install scripts, npm использует --ignore-scripts, native ZIP проверяются хешами и на path traversal.
- Pipeline разрешает публичный Release только после завершения обоих размеров, проверки тестов, allowlist staging и проверки отсутствия credentials. Уже существующий remote сохраняется отказом; force push/reset/clean не используются. В конце проверяются PUBLIC, commit SHA и имя/размер release asset.
- Попытка долговременного запуска через Codex Process Jobs завершилась до старта payload: `Unsupported platform: win32. Use macOS or Linux.` Задача CPJ не создана; pipeline запущен обычным foreground-процессом под контролем родительского агента. Не искать CPJ id для этой попытки.
- Первый pip install зависал до начала загрузки. Диагностика: PyPI имеет 4 IPv6 и 4 IPv4 адреса; TCP IPv6 — timeout 2 с, IPv4 — connect 0,047 с. Pipeline остановлен на установке первого пакета; зависший процесс pip только этого проекта завершён по проверенным executable/argv. Добавлен `pip_ipv4.py` для одного процесса pip; Node получает dns-result-order=ipv4first, .NET — process-local disableIPv6. Системные DNS, маршруты, IPv6 и registry не менялись. Native downloads используют curl с hard timeout и проверкой хеша.

### Доставка расширенного сравнения

Установка всех 11 адаптеров завершилась. 74 теста в `.venv` прошли без пропусков. Оба масштаба завершены; 10 merger methods и direct прошли QA на 200 и на 1000. PDFsharp по умолчанию INVALID на 200: MediaBox [0,0,41.102,41.102] вместо [0,0,41.10236,41.10236] и добавлена transparency Group с /CS /DeviceRGB; 1000 для него SKIPPED по неизменённому QA gate. Допуски не ослаблялись. Подробности находятся в локальном `PDFSHARP_QA.md` внутри suite/архива.

Полный ZIP `output/exports/suite-200-1000-20261027-141751-154b079e-all-files.zip`: 34 621 964 байта. Первый push из автоматического pipeline вернул exit128; stderr дочернего процесса не сохранился, точная причина не установлена. Новое явное выполнение той же команды git push с тем же gh credential helper завершилось exit0. В setup/pipeline добавлена явная передача stdout/stderr для диагностики будущих запусков. Замеры после этого не перезапускались.

Создан новый публичный `https://github.com/sunpole/uCode-Bench`, исходный commit отправлен в main. Старый `sunpole/uCode` не изменялся. Публикация Release и окончательная сверка следуют отдельным шагом; первичный `.local-state/.../final-status.json` сохраняет исходную ошибку pipeline, не подменяется успешным статусом.

### Завершение и readback публикации

Release опубликован и проверен: https://github.com/sunpole/uCode-Bench/releases/tag/results-200-1000-20261027-141751-154b079e . Тег создан на d943aa2c803c2d451019c42177d1d8fb35738a65; последующие изменения — документация доставки. Проверены GitHub visibility=PUBLIC и совпадение локального/remote main commit на момент readback.

SHA-256 локального ZIP и digest GitHub asset совпали: `6940a2257333ee5fad250cf44603f53f2a05931687e84d4c89fefc8890c03c0e`. Размер с обеих сторон 34 621 964 байта. ZIP CRC testzip PASS: 4085 записей, **3669 PDF**, **216 PNG** контрольного QA. Все локальные исходные данные и сырые отчёты сохранены; публичный ZIP содержит очищенную переносимую копию. 200 и 1000 имеют COMPLETE, по 11 успешных методов с direct включительно, по три QA PASS на каждый успешный метод. Этапы вместе с подготовкой/QA: 84,0498 с и 298,0472 с; suite elapsed 382,41 с.

HTML comparison визуально открыт в in-app browser: обе размерности, PASS/INVALID/SKIPPED, раздельная генерация, реальные ссылки на PDF и CPU/RAM отображаются. Последний QR из 1000 mutool визуально проверен. Временные tab/server закрыты. После правки передачи subprocess diagnostics выполнены 5 pipeline tests — PASS; базовые 74 теста уже прошли после установки без пропусков, измеряемый код с тех пор не менялся.

Итоговый минимум median среди успешных merger adapters: mutool **0,182746 с / 0,814974 с** на 200/1000. Direct **1,119775 с / 5,516372 с** отдельно. Все численные значения — из сохранённого comparison.json; прежнее приблизительное обновление 0,811 с для mutool/1000 уточняется точным замером 0,814974 с.

## Expanded comparison 2026-10-27

Local report: `output/comparisons/suite-200-1000-20261027-141751-154b079e/comparison.html`.
Local complete archive: `output/exports/suite-200-1000-20261027-141751-154b079e-all-files.zip`.

| Method | 200 median, s | QA | 1000 median, s | QA |
| --- | ---: | --- | ---: | --- |
| Direct PDF | 1.119775 | PASS | 5.516372 | PASS |
| Apache PDFBox | 1.238533 | PASS | 2.177539 | PASS |
| MuPDF (mutool) | 0.182746 | PASS | 0.814974 | PASS |
| PDFium (pypdfium2) | 0.246055 | PASS | 1.200908 | PASS |
| PDFsharp (.NET) | 0.435315 | INVALID | not measured | SKIPPED |
| PyMuPDF | 0.317630 | PASS | 1.666582 | PASS |
| pdf-lib (Node.js) | 1.020927 | PASS | 3.189848 | PASS |
| pdfcpu | 0.270196 | PASS | 1.247994 | PASS |
| pdfrw | 0.260319 | PASS | 1.338410 | PASS |
| pikepdf | 0.212120 | PASS | 1.090862 | PASS |
| pypdf | 0.312335 | PASS | 1.622643 | PASS |
| qpdf | 0.503207 | PASS | 2.222499 | PASS |

These are measured values from preserved local reports. Missing or failed methods are not extrapolated.
CPU/RAM/file sizes and all repeats are in the JSON/CSV. Full suite status: COMPLETE.
