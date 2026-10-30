"""Current workflow wording; historical Tk help remains available for legacy UI."""
from .help_content import TOPICS as LEGACY_TOPICS

RENAMES={'«Генерация»':'«Просмотр»','«PDF и цвет»':'«Оформление»','«CPU / RAM»':'«Настройка»',
         'вкладка «История»':'«Тесты → История»','во вкладке «История»':'в «Тесты → История»'}
TOPICS=[]
for original in LEGACY_TOPICS:
    topic=dict(original)
    paragraphs=[]
    for paragraph in topic['paragraphs']:
        for old,new in RENAMES.items():paragraph=paragraph.replace(old,new)
        paragraphs.append(paragraph)
    topic['paragraphs']=tuple(paragraphs);TOPICS.append(topic)
TOPICS[0]={**TOPICS[0],'short':'Тип → База → Путь → Оформление → Настройка → Просмотр → Создать PDF.',
           'paragraphs':('В «База» откройте TXT UTF-8 с 12 цифрами на строке или создайте последовательность: начало, количество строк и шаг. Первый/второй/последний номер видны до сохранения.',
                         'Выберите папку во вкладке «Путь» и проверьте место. В «Оформление» задайте геометрию и краски, в «Настройка» — CPU, RAM, формат и QA. Изменение заказа требует новой проверки папки.',
                         'В «Просмотр» выберите строку, проверьте QR и нажмите «Создать PDF». Кнопка появляется только здесь. Тесты имеют собственные подразделы и параметры печати. СТОП требует подтверждения через 3 секунды; частичные файлы сохраняются.')}
TOPICS=tuple(TOPICS)
