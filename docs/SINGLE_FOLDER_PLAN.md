> **СТАТУС 30.10.2026:** миграция пользователя в единственную `016_uCode` **уже выполнена и подтверждена** (два worktree сохранены на отдельном диске и удалены штатным Git). Нижеследующий текст описывает исходный план/ранний аудит, а не текущий список папок. Читать [CODEX_RESUME_2026-10-30.md](CODEX_RESUME_2026-10-30.md) прежде, чем предлагать изменения файловой структуры.

# Единая локальная папка uCode — план безопасного перехода

Статус: **PLAN / НЕ ВЫПОЛНЕН НА ПК**. Инициатор: пользователь 30.10.2026. Составлено ChatGPT для работы без Codex и будущей передачи Codex.

## Решение пользователя

Вместо трёх исторических рабочих папок использовать впоследствии **одну внешнюю папку** `016_uCode` с единственным ярлыком запуска. Стабильные исторические релизы держать на GitHub в Releases и immutable git tags, а на ПК — активную и одну проверенную предыдущую установленную версию для аварийного отката.

Известные каталоги пользователя: `016_uCode_PDF_test` (исходная рабочая папка, возможны локальные незакоммиченные изменения), `016_uCode` (содержимое пока не осмотрено), `016_uCode_GitHub_preview` (дополнительный Git worktree для сохранения Codex WIP). Не предполагать, что папки содержат одинаковые файлы, и не выбирать источник истины до аудита.

Предлагаемая будущая структура:
- `016_uCode/Проект/`: одна обычная Git-копия исходников с origin `sunpole/uCode-Bench`; **отдельно от установленного EXE**.
- `016_uCode/Данные/`: TXT, PDF, результаты, настройки и отчёты, которые никогда не удаляются обновлением.
- `016_uCode/.local/versions/vX.Y.Z/`: распакованные immutable portable build(s), активный релиз и одна сохранённая прошлая проверенная версия.
- `016_uCode/.local/updater/`: самостоятельный native `uCode.Updater.exe` и временная загрузка/backup, если выбран такой контракт установщика.
- `016_uCode/Запустить uCode.lnk`: постоянный ярлык/launcher, указывающий на проверенную активную версию.

**Эта структура концептуальна, не обещание уже созданных каталогов.** Хранение пользовательских данных должно соответствовать `ucode/distribution.py::user_root()` (`LOCALAPPDATA/uBrand/uCode` в текущей frozen Windows сборке); необходимо отдельно определить миграцию и совместимость путей прежде чем перенести данные под корень проекта. Не переносить автоматически настройки из системы без явной проверки и согласия.

## Этап A: только диагностика (разрешён сейчас)

1. На Windows через Git Bash Here проверить наличие трёх папок, `git status -sb`, `git rev-parse --show-toplevel`, `git remote -v`, `git worktree list`, краткий список верхнего уровня и размеры. Результат без содержимого частных TXT/PDF, токенов и секретов. `016_uCode` может оказаться без Git или с вложенной копией `Проект`.
2. Выявить у исходной папки незакоммиченные/staged/untracked файлы, ignored results, скрытые настройки, резервные копии и отдельные локальные артефакты; проверить, нет ли источников, отсутствующих в GitHub Releases.
3. Зафиксировать, какая папка является основным репозиторием и какую физически можно удалить только после проверки.

На этапе A не выполнять `rm`, `git clean`, `git reset --hard`, `git worktree prune/remove`, `git switch`, `git checkout`, `git pull` на грязном дереве, `git stash`, overwrite, Move-Item, robocopy /MIR.

## Этап B: сохранение (после подтверждённого аудита)

1. Создать проверяемую копию уникальных исходников/результатов в новой нейтральной backup-папке или пользовательском архиве; независимые SHA-256 для критических файлов.
2. Сохранить как минимум текущие фактические локальные данные/настройки/историю Code WIP; не публиковать private TXT, PDF и пользовательские пути в публичный GitHub.
3. Привязать одну нормальную Git-копию и проверить `git status`, origin, ветку, правильный HEAD, чистоту и целостность.
4. Git-linked worktree переносить/освобождать через `git worktree` и только после подтверждения отсутствия единственных незакоммиченных файлов; **не удалять физическую папку отдельно**.

## Этап C: единый запуск и реальный updater (только после QA)

- Фиксированный `uCode` launcher; самостоятельный native updater не должен знать, какой UI используется (сейчас WebView2, позже возможен WPF/WinUI).
- Release определяется стабильным GitHub tag, никогда не commit `main` или PR preview; preview-кандидаты выбираются отдельно и явно.
- Update flow после явного согласия: скачать в staging, проверить источник, размер и SHA-256 + при необходимости подписанный manifest, распаковать с защитой от traversal, тестировать бинарник, закрыть активное приложение, переключить активный каталог атомарно, сохранить предыдущий и rollback.
- Отдельно изучить NTFS permissions, Defender/SmartScreen, WebView2, совместимость Windows, отсутствие прав администратора и блокировки работающих файлов.
- Пока `uCode.Updater.exe --install` не реализован/протестирован, этот этап **не выполнен**. Стабильная `v0.3.4` и пользовательские результаты остаются нетронутыми.

## Codex / ChatGPT — актуальные задачи

- Ветка разработки и PR: `codex/v035-native-updater-tab` / PR #29 поверх PR #28. Docs/UPDATER_V035_HANDOFF.md сохраняет текущую реализацию GUI и native updater.
- Сначала запросить/проанализировать **реальный диагностический вывод Git Bash**. Не угадывать фактический локальный status по GitHub.
- После этого предложить пользователю точный миграционный сценарий с обратимыми шагами и отдельным подтверждением удаления старых папок.
- Массовые QR переменной числовой длины пользователь отклонил. Не добавлять их в план.

## Отдельно от переноса папок

Все выпущенные релизы можно хранить на https://github.com/sunpole/uCode-Bench/releases. GitHub Releases не заменяет резервные копии **невыложенных в репозиторий** исходников, PDF, TXT, пользовательских настроек и результатов.

## Результаты первого локального аудита, подтверждены пользователем 30.10.2026

- Основной Git worktree `016_uCode`: ветка `feature/txt-batch-print-pdf-20261027`, **чисто**, отстаёт от upstream на 8 коммитов; `output/` примерно **124 МиБ**, `results/` примерно 731 КиБ, `.local-state/` 290 КиБ, `tools/` 395 МиБ, `.venv/` 306 МиБ.
- Дополнительный Git worktree `016_uCode_GitHub_preview`: ветка `codex/portable-wip-20261030`, **чисто**, отстаёт от upstream на 6 коммитов; `results/` примерно 914 КиБ.
- Первоначальный Git worktree `016_uCode_PDF_test`: ветка `codex/v035-distribution`, **НЕЧИСТО**: пять modified `ucode/benchmark.py`, `ucode/operation_host.py`, `ucode/operator_desktop.py`, `ucode/operator_service.py`, `ucode/resource_lab.py`; три untracked `scripts/frozen_entry.py`, `ucode/distribution.py`, `ucode/system_check.py`. `output/` около **20 ГиБ**, `results/` около 913 КиБ, `.local-state/` 1.3 МиБ, `tools/` 396 МиБ, `.venv/` 333 МиБ.
- Пользователь подтвердил `git worktree list`: все три каталога — рабочие деревья **одного** Git репозитория, а не три независимых клона. `016_uCode/Проект` отсутствует; будущая структура — план, не реализована.
- Установленный frozen uCode хранит примерно 70 МиБ пользовательских данных в профиле Windows `LOCALAPPDATA/uBrand/uCode` (точный путь не раскрывать в публичном репозитории).
- **Критический вывод:** ни `016_uCode_PDF_test`, ни её `output/` нельзя удалять/чистить до проверки сохранности 20 ГиБ, настроек и восьми исходных изменений. Ранее в GitHub сохранили восемь файлов Codex в коммите `f70f748`, но локальную побайтовую идентичность этим файлам в первом аудите ещё НЕ доказали. Проверить `git hash-object --path` / blob SHA для восьми путей. При несовпадении создать отдельную резервную копию/пачт, без перезаписи GitHub.
- **Следующий read-only этап:** сравнить рабочие восемь файлов с git blob `f70f748`, оценить дерево содержимого `output/` в крупных разделах, доступное место под независимую резервную копию 20 ГиБ. Проверить источники `results/` и `.local-state/`, не включать приватные значения/имена в публичные отчёты. Ни `git worktree remove`, ни `rm -rf`, ни `git clean`, ни `git reset --hard` пока НЕ выполнять.


### Report-only PDF policy, owner decision 2026-10-30

- User confirmed `f70f748` matches **all 8/8** local Codex source files. Main `016_uCode` remains the future single workspace but C: is 99% occupied (only 5.7 GiB available); `016_uCode_PDF_test/output/jobs` contains about 20 GiB generated output. Never delete working files automatically or change the local PC via GitHub actions.
- Explicit requirement: benchmark/lab output should be **small test reports, QA evidence, timing and configuration**, not permanently accumulated PDF; generated PDF must still be physically written and verified before safely discarding it *outside* measured intervals. User-initiated production PDF for printing must be retained.
- Read **docs/REPORT_ONLY_TESTS.md** and draft **PR #30** (`codex/v035-report-only-benchmarks` → `codex/v035-native-updater-tab`) before any further changes. GUI LabConfig/PipelineConfig/SearchConfig now perform per-trial report-only cleanup; historical scientific gate and console path need a separate safe migration and must never claim PASS without comparable QA evidence. `.gitignore` excludes output/ already; no PDF upload to GitHub.
- No `git reset --hard`/`git clean`/worktree deletion; separate confirmation is required before deleting previous 20 GiB. Existing `results`, `.local-state`, TXT, user settings remain intact.
