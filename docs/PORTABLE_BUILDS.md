# uCode: переносимые приложения — этап 1 (30.10.2026)

Статус: **три preview-пакета собраны в GitHub Actions и прошли CLI + небольшой реальный QR/PDF smoke**. Полноценные GUI, чистая установка, подпись и автообновление пока не подтверждены.

## Что добавлено

- `.github/workflows/portable-preview.yml`: отдельная GitHub Actions сборка (Windows x64 / Ubuntu Linux x64 / macOS ARM64). Автоматически реагирует на изменение workflow или трёх входных файлов Codex, а также допускает ручной запуск после попадания на default branch.
- Предварительная проверка наличия `scripts/frozen_entry.py`, `ucode/distribution.py`, `ucode/system_check.py`. Их **реальное содержимое сейчас существует только по сообщению UI Codex; на удалённой ветке при создании инструкции файлов не было**. Если их нет — упаковка SKIPPED и это видно в GitHub CI; ни пустого EXE, ни ложного релиза.
- После появления файлов проверяется Python-синтаксис и совпадение версии `pyproject.toml` с `ucode/__init__.py`.
- Если preflight PASS, `PyInstaller --onedir` собирает папку исполняемой программы для каждой ОС на собственном GitHub runner. Проверка `--help` выполняется через реально собранный бинарник с тайм-аутом 50 секунд; затем создаются временные ZIP/TAR.GZ и `SHA256SUMS.txt`.
- Артефакты CI сохраняются **на 14 дней**, это НЕ GitHub Release, НЕ стабильный выпуск, НЕ установщик и НЕ автоматическое обновление пользователя.

## Пакеты по ОС

| ОС | Предварительный артефакт CI | Что ещё проверить |
| --- | --- | --- |
| Windows x64 | `uCode-{version}-windows-x64.zip`, папка с `uCode.exe` | Microsoft WebView2 Runtime, desktop smoke, окна, запуск без установленного Python, PDF/QR и процессы |
| Linux x64 | `uCode-{version}-linux-x64.tar.gz`, папка с `uCode` | GTK/WebKit либо выбранный backend, desktop launcher, зависимости дистрибутива, сборка и реальные PDF |
| macOS ARM64 | `uCode-{version}-macos-arm64.zip` с `uCode.app` | запуск Finder, подпись/notarization/Gatekeeper, пользовательские файлы, настоящий PDF, ресурсы, subprocess |

**Особенно важно:** Python внутри сборки есть, но нативный WebView2, GTK/WebKit и системные библиотеки могут требоваться отдельно. `--help` проверяет только запуск CLI, не работу интерфейса или PDF. Приложение для Intel Mac пока не собрано.

## Условия для признания рабочей версии стабильной

1. Сохранить локальные WIP-файлы Codex **до обновления рабочей папки**, не использовать `git reset --hard`, `git clean` и не перезаписывать их.
2. Выполнить Windows и Linux существующего CI (`.github/workflows/txt-batch.yml`) и устранить реальные ошибки; Windows watchdog увеличен с 120 до 300 секунд, поскольку за 120 секунд тесты не успевали завершиться.
3. Сверить исходники и теги. Подготовить проверенный исходный снимок 0.3.4 отдельно от упаковочных изменений. Тег/релиз `v0.3.4` можно создать после доказанного PASS версии 0.3.4; **не путать последний опубликованный `v0.3.0`**.
4. После фиксации frozen-изменений добиться PASS всех трёх platform-preview и хотя бы небольших реальных PDF/QR в каждой ОС. Для Windows отдельно выполнить полную проверку WebView2 без Python на чистой машине; Linux/macOS тесты GUI — отдельно.
5. Проектирование автообновления: только проверенный подписанный/хешированный пакет GitHub Release, явное согласие пользователя, резервная рабочая версия, атомарная замена при закрытой программе, сохранение `output/`, `.local-state/`, настроек и пользовательских результатов, откат. Код самообновления в данном этапе **не реализован**.
6. Только после всех проверок, документированного завершения и согласованного порядка — PR к `main`, без force-push и без подмены существующих тегов.

## Примечания о воспроизводимости

- Пакет `uCode.app` создаётся через `PyInstaller --windowed --onedir`. Используемые описания: https://pyinstaller.org/en/latest/usage.html
- Метки GitHub-hosted runners: https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- Кросс-компиляция пакетов одной ОС из другой ОС в обычном PyInstaller не поддерживается.
- Контрольные суммы в CI — SHA-256 *проверочных артефактов*, но не сертификат цифровой подписи. Приложение Windows/macOS пока не подписано.
- Более полный контракт передачи Codex: `docs/AI_HANDOFF.md`.

## Восстановление Codex WIP и первый реальный результат (30.10.2026)

- Пользователь сохранил все восемь файлов прерванной работы Codex на ветке `codex/portable-wip-20261030`, commit `f70f748c530bdad75e5472a8070b10974f0e878b`; исходная рабочая папка не удалялась. Открыт draft PR #27 в `codex/v034-local-qr-content`.
- Первое CI выявило зависание Windows `--help` на 50 секунд из-за модального сообщения об ошибке. После удаления модального окна из CLI GitHub Actions выявил первопричину — `UnicodeEncodeError` из-за cp1252 при выводе русской справки.
- В `scripts/frozen_entry.py` установлена UTF-8 кодировка stdout/stderr, а консольные ошибки теперь не требуют нажатия на MessageBox; упаковочный smoke читает UTF-8.
- Добавлен `ucode/distribution_smoke.py`, он исключительно по опции `--smoke` создаёт две настоящие QR-страницы в одном PDF, проверяет PDF/manifest и применяет векторную QA. Ожидаемая метка QA — `LIMITED`, **не COMPLETE** (не включает Poppler-растровую проверку камеры). Временная папка после теста удаляется.
- **Проверено на GitHub:** [portable preview run 41062288521](https://github.com/sunpole/uCode-Bench/actions/runs/41062288521), commit `1ddc17f5b7b3ae8ff38788b86ec8be7b1cd081b5`: preflight SUCCESS, Windows x64 SUCCESS, Linux x64 SUCCESS, macOS ARM64 SUCCESS, включая `--help` и `--smoke` **в уже упакованных исполняемых файлах**.
- Проверено существование трёх GitHub Actions artifacts: `ucode-portable-preview-windows-x64-0.3.4`, `ucode-portable-preview-linux-x64-0.3.4`, `ucode-portable-preview-macos-arm64-0.3.4`, контрольные суммы в каждом пакете. Это **не GitHub Releases** и не подписанные инсталляторы; временные CI-артефакты сохраняются 14 дней.
- Полная Windows/Linux исходная регрессия для предыдущего коммита `e45a745ca65e4b300a8e484e0904301698394efb`: [run 41061933545](https://github.com/sunpole/uCode-Bench/actions/runs/41061933545) SUCCESS; актуальную регрессию после добавления smoke нужно отслеживать отдельно.
- Требуется пользовательская приёмка GUI на Windows: открыть `uCode.exe`, проверить WebView2, кнопки, реальные пользовательские TXT/QR, PDF в нужных форматах, DPI и закрытие. На чистой Windows не тестировалось. Аналогично Linux Qt/WebKit и macOS GUI/Gatekeeper не прошли физическую пользовательскую приёмку. Самообновление ещё НЕ реализовано.

### Получение Windows preview через установленный GitHub CLI

```powershell
$download = Join-Path $env:USERPROFILE 'Downloads\uCode-034-preview'
New-Item -ItemType Directory -Force -Path $download | Out-Null
gh run download 41062288521 -R sunpole/uCode-Bench -n ucode-portable-preview-windows-x64-0.3.4 -D $download
$archive = Join-Path $download 'uCode-0.3.4-windows-x64.zip'
Get-FileHash -Algorithm SHA256 -LiteralPath $archive
Get-Content -LiteralPath (Join-Path $download 'SHA256SUMS.txt')
Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $download 'app')
& (Join-Path $download 'app\uCode\uCode.exe') --smoke
```

Сверять хеш `Get-FileHash` с `SHA256SUMS.txt` перед запуском. Не разархивировать поверх рабочей копии или существующего дистрибутива. Инструкции по дальнейшему выпуску stable и merge в main — прежние, пока не выполнены.
