# Исследование PDF-движков для uCode

Дата: **2026-10-27**, Europe/Minsk. Проверены первичные страницы проектов, GitHub Releases, официальная документация и PyPI/NuGet. Это каталог кандидатов и источников установки; наличие ссылки не означает, что движок уже установлен или прошёл uCode QA. Реальные версии и результаты фиксируются отдельными `doctor`, installation manifest и benchmark reports.

## Практический набор

Для Windows x64 разумный расширенный набор — 10 способов объединения: qpdf CLI, MuPDF/mutool CLI, PyMuPDF, pikepdf, pypdf, pdfrw, pypdfium2/PDFium, pdfcpu, pdf-lib/Node и Apache PDFBox/Java. Ghostscript/pdfwrite — ещё один полезный кандидат, который **пересоздаёт** документ; его результат проходит тот же QA и не должен называться структурно lossless без проверки. PDFsharp/.NET добавляет ещё одну независимую реализацию, если на ПК есть совместимый SDK/runtime.

Число адаптеров не равно числу независимых ядер: **pikepdf использует qpdf**, а **PyMuPDF и mutool используют MuPDF**. В отчёте полезно сохранять поля family и invocation (Python API / CLI / Node / JVM), чтобы сравнение не превращалось в подсчёт обёрток одного ядра.

| Кандидат | Проверенная актуальная версия | Семейство / установка | Лицензия из первичного источника |
| --- | --- | --- | --- |
| qpdf | 12.4.2 | C++ qpdf, официальный portable ZIP | Apache-2.0 |
| mutool | MuPDF 1.28.5 | C MuPDF, официальный Windows ZIP | AGPL-3.0-or-later / коммерческая Artifex |
| PyMuPDF | 2.0, выпущен 19.10.2026 | Python wheel, MuPDF 1.28.5 | AGPL-3.0 / коммерческая Artifex |
| pikepdf | 10.17.0 | Python wheel, qpdf | MPL-2.0; зависимости имеют свои лицензии |
| pypdf | 6.21.2 | Pure Python wheel | BSD-3-Clause |
| pdfrw | 0.4, 2017 год | Pure Python wheel; старый отдельный parser/writer | MIT |
| pypdfium2 | 5.14.0 | Python wheel с PDFium | Apache-2.0 / BSD-3-Clause, PDFium и зависимости отдельно |
| pdfcpu | 0.16.3 | Go, официальный portable Windows ZIP | Apache-2.0 |
| pdf-lib | 1.17.1 | Pure JavaScript, npm | MIT |
| Apache PDFBox | 3.0.8 | официальный standalone JAR, Java 8+ | Apache-2.0 |
| Ghostscript | 10.08.0 | официальный Windows NSIS EXE; извлечение portable возможно при наличии подходящего extractor | AGPL / коммерческая Artifex |
| PDFsharp | 6.5.0; предыдущая 6.2.4 | NuGet, .NET | 6.5.0 — AGPL-3.0-only; 6.2.4 — MIT |

Версия pdfcpu 0.16.2 встречается в более старом поисковом кэше. Тег 0.16.3 от 19.10.2026 и его asset проверены отдельно; именно он выбран для новой установки. Аналогично PyMuPDF 2.0 уже опубликован: старое ограничение `<2` удерживает установку на ветке 1.x. Для актуальных PyMuPDF и pikepdf требуется Python >=3.11; имеющийся Python 3.12 подходит.

Первичные страницы версий и лицензий: [qpdf release](https://github.com/qpdf/qpdf/releases/tag/v12.4.2), [qpdf LICENSE](https://github.com/qpdf/qpdf/blob/v12.4.2/LICENSE.txt), [MuPDF downloads](https://github.com/ArtifexSoftware/mupdf-downloads/releases/tag/1.28.5), [PyMuPDF release](https://github.com/pymupdf/PyMuPDF/releases/tag/2.0), [PyMuPDF PyPI](https://pypi.org/project/PyMuPDF/), [pikepdf PyPI](https://pypi.org/project/pikepdf/), [pypdf PyPI](https://pypi.org/project/pypdf/), [pdfrw PyPI](https://pypi.org/project/pdfrw/), [pypdfium2 PyPI](https://pypi.org/project/pypdfium2/), [pdfcpu release](https://github.com/pdfcpu/pdfcpu/releases/tag/v0.16.3), [pdfcpu LICENSE](https://github.com/pdfcpu/pdfcpu/blob/v0.16.3/LICENSE.txt), [pdf-lib release](https://github.com/Hopding/pdf-lib/releases/tag/v1.17.1), [pdf-lib LICENSE](https://github.com/Hopding/pdf-lib/blob/v1.17.1/LICENSE.md), [PDFBox downloads](https://pdfbox.apache.org/download.html), [Ghostscript release](https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/tag/gs10080), [PDFsharp 6.5.0](https://www.nuget.org/packages/PDFsharp/6.5.0), [PDFsharp 6.2.4](https://www.nuget.org/packages/PDFsharp/6.2.4).

## Точные официальные загрузки Windows

SHA-256 ниже опубликованы рядом с assets на официальных GitHub release pages; скачанный файл нужно сверять до запуска. Это хеши архивов/инсталлятора, а не извлечённых EXE.

| Архив / пакет | Официальный URL | SHA-256 |
| --- | --- | --- |
| qpdf MSVC x64 12.4.2, около 26.9 MB | [qpdf-12.4.2-msvc64.zip](https://github.com/qpdf/qpdf/releases/download/v12.4.2/qpdf-12.4.2-msvc64.zip) | `db87077e683630c1217e0e8f9a20a9749d952ab676e881c3689187763a5de25d` |
| MuPDF 1.28.5, около 89.9 MB | [mupdf-1.28.5-windows.zip](https://github.com/ArtifexSoftware/mupdf-downloads/releases/download/1.28.5/mupdf-1.28.5-windows.zip) | `13476a53e84f5527983158acb6442c7853b3cdc022f3b24880780dcfba1fcc99` |
| pdfcpu 0.16.3 x64, 7 071 702 bytes | [pdfcpu_0.16.3_Windows_x86_64.zip](https://github.com/pdfcpu/pdfcpu/releases/download/v0.16.3/pdfcpu_0.16.3_Windows_x86_64.zip) | `282cb436b6904895fe17cf13e10e8397fcf3ba222084986ac1382340761d3d55` |
| Ghostscript 10.08.0 x64, около 62.1 MB | [gs10080w64.exe](https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10080/gs10080w64.exe) | `52a91b8bf09298788d7a57b9206127026c23eacd75405f0a131e26dc381dce50` |
| pdfrw wheel 0.4 | [PyPI files](https://pypi.org/project/pdfrw/0.4/#files), файл `pdfrw-0.4-py2.py3-none-any.whl` | `758289edaa3b672e9a1a67504be73c18ec668d4e5b9d5ac9cbc0dc753d8d196b` |
| pypdfium2 5.14.0 Windows x64 | [PyPI files](https://pypi.org/project/pypdfium2/5.14.0/#files), файл `pypdfium2-5.14.0-py3-none-win_amd64.whl` | `149fd5c6397b8df8bf7911a93506eff0be874f877afe7ac936cf5d37d21a6a06` |

Официальные полные списки assets: [qpdf](https://github.com/qpdf/qpdf/releases/expanded_assets/v12.4.2), [MuPDF](https://github.com/ArtifexSoftware/mupdf-downloads/releases/expanded_assets/1.28.5), [pdfcpu](https://github.com/pdfcpu/pdfcpu/releases/expanded_assets/v0.16.3), [Ghostscript](https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/expanded_assets/gs10080).

PDFBox: [standalone JAR 3.0.8](https://downloads.apache.org/pdfbox/3.0.8/pdfbox-app-3.0.8.jar), [официальный SHA-512](https://downloads.apache.org/pdfbox/3.0.8/pdfbox-app-3.0.8.jar.sha512), [PGP signature](https://downloads.apache.org/pdfbox/3.0.8/pdfbox-app-3.0.8.jar.asc). Полная строка SHA-512 здесь не переписывается: installer должен читать sidecar, сохранить его и проверить скачанный JAR.

Для Python использовать wheels из PyPI с зафиксированными версиями в локальном venv. Для pdf-lib — npm-пакет `pdf-lib@1.17.1` и локальный package-lock с integrity. Исходники проекта и manifests подходят для публичной копии; сторонние бинарные архивы и полные зависимости не нужно случайно добавлять в Git вместе с рабочей папкой.

### Установка Ghostscript и изоляция

[Официальная инструкция Windows](https://ghostscript.readthedocs.io/en/gs10.08.0/Install.html) подтверждает, что EXE — NSIS installer. `/D` меняет каталог, но обычная установка также создаёт `GS_LIB`/`GS_DLL` в registry. Поэтому `/S /D=<папка-проекта>` нельзя описывать как гарантированно переносимую установку без системных изменений.

Если имеется full 7-Zip с поддержкой NSIS, можно попытаться извлечь уже проверенный официальный EXE в `tools/ghostscript/`, сохранив `bin`, DLL, `lib`, `Resource` и нужные файлы; конкретная структура и запуск должны быть проверены. Наличие extractor и такая portable-раскладка в рамках этого исследования **не проверялись**. При отсутствии подходящего extractor нужно честно записать причину пропуска либо отдельно согласовать обычную установку, а не выдавать silent installer за простую распаковку ZIP.

## Интерфейсы объединения и 1000 путей

| Движок | Официальный интерфейс | Практическая передача 1000 входов |
| --- | --- | --- |
| qpdf | `qpdf --empty --pages file1 1-z file2 1-z -- out.pdf` | документированный `@-` со строками аргументов через stdin |
| mutool | `mutool merge -o out.pdf input1.pdf input2.pdf ...` | установить cwd в singles; передать короткие имена в исходном порядке и абсолютный output; явно проверять итоговую Windows command line |
| PyMuPDF | `out.insert_pdf(source)` для каждого открытого документа, `out.save(output)` | list manifest в worker, пути не попадают в argv |
| pikepdf | `out.pages.extend(source.pages)`, `out.save(output)` | list manifest в worker |
| pypdf | `writer.append(input, import_outline=False)`, `writer.write(output)` | list manifest в worker |
| pdfrw | `writer.addpages(PdfReader(input).pages)`, `writer.write(output)` | list manifest в worker |
| pypdfium2 | `PdfDocument.new()`, `out.import_pages(source)`, `out.save(output)` | list manifest в worker; все PDFium вызовы последовательно в одном процессе |
| pdfcpu | `pdfcpu merge out.pdf input1.pdf input2.pdf ...` | cwd singles и имена без длинных абсолютных префиксов; отключить bookmarks; не включать сортировку |
| pdf-lib | `PDFDocument.load`, `out.copyPages`, `out.addPage`, `out.save` | передать Node helper путь к JSON manifest, не 1000 имён в argv |
| PDFBox 3 | `java -jar pdfbox-app-3.0.8.jar merge -o=out.pdf -i=input1.pdf -i=input2.pdf ...` | Java 9+ `@argfile` либо cwd singles и короткие имена; при Java 8 source helper читает manifest |
| Ghostscript | `gswin64c -dBATCH -dNOPAUSE -sDEVICE=pdfwrite -sOutputFile=out.pdf ...` | Ghostscript argument file `@file`; сохранить установленные параметры цвета и весь command manifest |
| PDFsharp | `PdfReader.Open(input, PdfDocumentOpenMode.Import)`, `out.AddPage(page)`, `out.Save(output)` | небольшой C# helper читает JSON/строчный manifest |

Источники интерфейсов: [qpdf CLI](https://qpdf.readthedocs.io/en/stable/cli.html), [mutool merge](https://mupdf.readthedocs.io/en/1.28.4/tools/mutool-merge.html), [PyMuPDF document API](https://pymupdf.readthedocs.io/en/latest/document.html), [pikepdf examples](https://pypi.org/project/pikepdf/), [pdfrw README](https://github.com/pmaupin/pdfrw), [pypdfium2 API](https://pypdfium2.readthedocs.io/en/stable/python_api.html), [pdfcpu merge](https://pdfcpu.io/core/merge/), [pdf-lib examples](https://pdf-lib.js.org/), [PDFBox CLI](https://pdfbox.apache.org/3.0/commandline.html), [Ghostscript usage](https://ghostscript.readthedocs.io/en/gs10.08.0/Use.html), [PDFsharp samples](https://github.com/empira/PDFsharp.Samples).

В uCode имя вида `0001_200000000000.pdf` занимает 21 символ; 1000 таких имён с пробелами — около 22 000 символов. Это оценка длины argv для конкретной схемы имён, **не измерение производительности**. При длинных абсолютных путях превышение Windows command-line limit неизбежно, поэтому один и тот же внешний adapter должен проверять итоговый argv и использовать manifest/relative paths. Не менять порядок файлов и не сортировать их движком повторно.

PDFium по [официальному предупреждению](https://pypdfium2.readthedocs.io/en/stable/python_api.html#incompatibility-with-threading) не потокобезопасен; свежий отдельный worker и последовательные вызовы соответствуют текущей архитектуре uCode.

## QA и интерпретация результатов

Скорость не выводится из рекламных описаний или языка реализации. Каждый установленный кандидат должен пройти реальные три повтора на одинаковом наборе файлов. При исключённом из таймера Python import и включённом CLI/JVM/Node startup это необходимо явно показывать в `invocation`/описании метрики; пользователь сравнивает конкретные способы запуска, а не чистую скорость одинакового ABI.

Ghostscript `pdfwrite` создаёт новые объекты документа; [Artifex прямо описывает](https://ghostscript.readthedocs.io/en/gs10.08.0/VectorDevices.html) это как пересоздание PDF. `LeaveColorUnchanged` управляет цветовой политикой, но не заменяет проверку K100. Текущий узкий uCode parser может отклонить допустимое, но иначе записанное векторное содержимое: такой результат должен остаться INVALID с точным объяснением неподдерживаемых операторов. Расширять parser следует отдельным проверенным изменением, сохраняя запрет RGB/растра, точную геометрию, quiet zone и декодирование.

Наличие PASS на маленьком smoke не подтверждает PASS на 200/1000. Результаты 200 и 1000, исходные/итоговые PDF, QA PNG, версии и CPU/RAM должны остаться в отдельных уникальных локальных каталогах. Следующий этап допускается по действующим правилам uCode и явному запросу пользователя; не скрывать SKIPPED/ERROR/INVALID ради увеличения числа «успешных движков».

## Дальнейшие кандидаты

PDFtk, OpenPDF и iText могут увеличить набор, но требуют дополнительных конкретных runtime/пакетов. Они не исследованы здесь до уровня проверенного Windows artefact и точного pin. Известные wrappers pdfunite-подобных интерфейсов, PDF Arranger, OCRmyPDF или npm `pdf-merger-js` не следует автоматически считать новыми ядрами: они могут использовать уже включённый движок. Коммерческие SDK с trial watermark, облачные API и GUI-only сценарии не дают сопоставимого автономного локального результата этого этапа.
