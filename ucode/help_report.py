"""Packaged, offline, self-contained help. Rendering never starts a workload."""
import html
import re
from pathlib import Path
from .brand import ASSETS, image_uri
from .help_content import TOPICS, CONTACTS

EXAMPLES = (
    ('Малый пример: 3 кода, один запуск', 'test pipeline --codes 3 --split cores:1+0 --schedule queue --batch 1 --repeats 1 --metrics off --qa off'),
    ('Два варианта на 10 000: порции 32 и 50, по два повтора', 'test pipeline --codes 10000 --split cores:1+0 --processes-per-core 1 --schedule queue --batch 32,50 --repeats 2 --metrics cpu --qa off --xy on'),
    ('Научный профиль, всегда с полной QA', 'test scientific --codes 200 --mergers pypdf'),
)

PARAMETERS = {
    'codes':'Количество кодов; список через запятую создаёт отдельные тиражи.',
    'repeats':'Повторы каждого варианта. В лаборатории 1–10, в научном профиле фиксированная методика.',
    'qa':'full/on — полная проверка; vector — без растра; off/deferred — без проверки, UNVERIFIED.',
    'module':'Размер одной клетки QR в миллиметрах.', 'quiet':'Белое поле в модулях с каждой стороны; минимум 4.',
    'ink':'Четыре компоненты C,M,Y,K в процентах, например 0,0,0,100.',
    'background':'Подложка: white — белая, color — CMYK, transparent — прозрачная.',
    'paper':'CMYK подложки: C,M,Y,K в процентах. Пример 0,0,0,100 — чёрная.',
    'xy':'on/off — записывать временной ряд для графика отчёта.',
    'pdf':'standard/compact — обычная или компактная структура PDF.',
    'split':'Распределение CPU: cores:12+2 или smt:24+4. Справа 0 — полный цикл у каждого процесса.',
    'processes_per_core':'Сколько процессов делят каждый выбранный CPU; 1–10, возможен список.',
    'schedule':'queue — общая очередь; equal — фиксированные равные диапазоны.',
    'batch':'Кодов за одно задание, 1–1000. В конвейере/подборе можно перечислить несколько значений.',
    'ram':'Бюджет полезной RAM с резервом ОС: auto, max, 50%, 80%. CPU/RAM также поддерживает MiB.',
    'metrics':'Наблюдение CPU: off/cpu. CPU/RAM и конвейер могут сравнить оба режима отдельными вариантами.',
    'unit':'cores — физические ядра; smt — логические CPU. Список создаёт разные варианты.',
    'cpu':'Выбор количества CPU: число, all, all-2; список создаёт варианты.',
    'backend':'serial — по очереди; process — отдельные процессы; thread — потоки Python с ограничением GIL.',
    'workers':'Исполнительные процессы/потоки в CPU/RAM. 0 — по выбранному количеству CPU.',
    'warmups':'Пробные запуски перед измерениями; 0 выключает. В медиану не входят.',
    'files':'multipage — общий PDF; singles — отдельные; both — оба способа.',
    'activity':'normal/minimal — объём дополнительных служебных данных.',
    'each_cpu':'on — перебрать каждое доступное количество CPU; off — только указанный список.',
    'search':'staged — отбор кандидатов; full — полный выбранный перебор.',
    'keep_best':'Сколько кандидатов сохранять при поэтапном отборе.',
    'parts':'На сколько частей разбить тираж перед объединением.',
    'part_mode':'sequential/parallel — создавать части по очереди или параллельно.',
    'mergers':'Выбранные движки объединения; недоступные получают SKIPPED.',
}


def build_help(hardware=None,*,topics=None):
    esc=html.escape; hardware=hardware or {};cpu=hardware.get('cpu',{})
    core_count=cpu.get('available_physical') or 1
    core_count=max(1,min(256,int(core_count)))
    chapters=[];topics=TOPICS if topics is None else topics
    for topic in topics:
        body=''.join('<p>'+esc(p)+'</p>' for p in topic['paragraphs'])
        if topic['id']=='print':body+='<div id="qr-demo" class="demo"></div>'
        if topic['id']=='queue':body+='<div id="queue-demo" class="demo"></div>'
        if topic['id']=='console':
            for i,(label,command) in enumerate(EXAMPLES):
                command=command.replace('--split cores:1+0',f'--split cores:{core_count}+0') if i==1 else command
                body+='<div class="example"><h3>'+esc(label)+'</h3><pre><code id="command-'+str(i)+'">'+esc(command)+'</code></pre><button data-copy="command-'+str(i)+'">Скопировать команду</button></div>'
            body+='<p><a href="#command-flags">Все параметры команд</a>. Копирование не запускает тест. Перед запуском нажмите «Проверить» в программе.</p>'
        if topic['id']=='about':
            body+='<div class="contacts">'+''.join('<a href="'+esc(url,quote=True)+'">'+esc(label)+'</a>' for label,url in CONTACTS)+'</div>'
            body+='<p>Авторские права на программу и права на сторонние компоненты рассматриваются отдельно. Эта справка не меняет условия использования.</p>'
        chapters.append('<section id="'+topic['id']+'" data-search="'+esc(topic['title']+' '+topic['short']+' '+' '.join(topic['paragraphs']),quote=True)+'"><div class="eyebrow">СПРАВКА UCODE</div><h2>'+esc(topic['title'])+' <a class="permalink" href="#'+topic['id']+'" aria-label="Ссылка на раздел">#</a></h2><p class="lead">'+esc(topic['short'])+'</p>'+body+'<p class="route">В программе: '+esc(topic['action'] or 'Справка → О программе')+'</p><a href="#top">К оглавлению ↑</a></section>')
    from .test_commands import parser_for
    appendix=[]
    for kind in ('lab','pipeline','search','scientific'):
        rows=[]
        for arg in parser_for(kind)._actions:
            if not arg.option_strings or arg.dest=='help':continue
            default=arg.default if arg.default is not None else 'обязательный параметр'
            rows.append('<tr><th scope="row"><code>'+esc(', '.join(arg.option_strings))+'</code></th><td>'+esc(str(default))+'</td><td>'+esc(PARAMETERS.get(arg.dest,'Параметр выбранной команды; допустимость значения проверяется до запуска.'))+'</td></tr>')
        appendix.append('<h3>test '+kind+'</h3><div class="table-wrap"><table><thead><tr><th>Параметр</th><th>По умолчанию</th><th>Для чего</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>')
    chapters.append('<section id="command-flags" data-search="параметры команды консоль flags"><h2>Параметры команд <a class="permalink" href="#command-flags">#</a></h2><p>Список получен из текущего парсера программы. Значения через запятую создают варианты там, где параметр поддерживает набор. Допустимые значения проверяет кнопка «Проверить». Научный профиль сохраняет фиксированную методику.</p>'+''.join(appendix)+'<a href="#console">К примерам команд ↑</a></section>')
    nav=''.join('<a href="#'+t['id']+'">'+esc(t['title'])+'</a>' for t in topics)+'<a href="#command-flags">Все параметры команд</a>'
    machine=esc(str(cpu.get('model') or cpu.get('name') or 'Текущий компьютер')+f' · доступно ядер: {cpu.get("available_physical","—")} · логических CPU: {cpu.get("available_logical","—")}')
    values={'BODY':''.join(chapters),'NAV':nav,'LOGO':image_uri(),'MACHINE':machine,'CORES':str(min(core_count,64))}
    template=(ASSETS/'help.html').read_text(encoding='utf-8')
    return re.sub(r'@@(BODY|NAV|LOGO|MACHINE|CORES)@@',lambda m:values[m.group(1)],template)


def write_help(output_root,hardware=None,*,topics=None):
    from .batch import _make_directory
    folder=_make_directory(Path(output_root)/'help','guide')
    target=folder/'help.html';target.write_text(build_help(hardware,topics=topics),encoding='utf-8');return target

