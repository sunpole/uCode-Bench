import copy
import gc
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from ucode.help_content import TOPICS,CONTEXT
from ucode.help_report import build_help,EXAMPLES
from ucode.result_presentation import test_outcome


def limited_queue():
    cases=[{'status':'UNVERIFIED','count':10000,'trials':[{'status':'UNVERIFIED','errors':[]} for _ in range(2)]} for _ in range(3)]
    cases.append({'status':'INVALID','count':10000,'trials':[{'status':'RESOURCE_LIMIT','errors':['Безопасного бюджета ОЗУ недостаточно']} ]})
    return {'kind':'test-command-queue','status':'ERROR','commands':['test pipeline'],
            'runs':[{'result':{'status':'PARTIAL','config':{'repeats':2},'cases':cases}}],
            'errors':['Команда завершилась со статусом PARTIAL; следующие команды не запущены'],'elapsed_seconds':61}


class Markup(HTMLParser):
    def __init__(self,text):super().__init__();self.ids=[];self.links=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if values.get('id'):self.ids.append(values['id'])
        if tag=='a':self.links.append(values.get('href',''))


class HelpContracts(unittest.TestCase):
    def test_offline_help_links_all_parser_flags_real_logo_and_safe_hardware_text(self):
        from ucode.test_commands import parser_for,parse_command
        from ucode.brand import ASSETS,SVG_SHA256
        self.assertEqual(hashlib.sha256((ASSETS/'ubrand.svg').read_bytes()).hexdigest(),SVG_SHA256)
        doc=build_help({'cpu':{'name':'<img src=x onerror=alert(1)>','available_physical':14,'available_logical':28}})
        self.assertNotIn('<img src=x',doc);self.assertIn('&lt;img',doc)
        markup=Markup(doc);self.assertEqual(len(markup.ids),len(set(markup.ids)))
        for href in markup.links:
            if href.startswith('#'):self.assertIn(href[1:],markup.ids)
            else:self.assertTrue(href.startswith(('https://','tel:')))
        for t in TOPICS:self.assertIn(t['id'],markup.ids)
        for kind in ('lab','pipeline','search','scientific'):
            for arg in parser_for(kind)._actions:
                for name in arg.option_strings:
                    if name!='--help':self.assertIn(name,doc)
        for _,example in EXAMPLES:parse_command(example)
        self.assertIn('data:image/png;base64,',doc)
        self.assertNotIn('@@',doc)
        self.assertNotIn('<script src=',doc)

    def test_resource_limit_is_explained_without_altering_or_hiding_real_failures(self):
        data=limited_queue();before=copy.deepcopy(data);view=test_outcome(data)
        self.assertEqual(data,before);self.assertEqual((view['complete'],view['planned']),(6,8))
        self.assertTrue(view['resource_only']);self.assertIn('ОЗУ',view['title'])
        self.assertEqual(view['status'],'ERROR');self.assertEqual(view['tone'],'warning')
        data['runs'][0]['result']['cases'][0]['trials'][0]={'status':'INVALID','errors':['QA failed']}
        self.assertFalse(test_outcome(data)['resource_only'])
        data=limited_queue();data['errors'].append('Unexpected exception')
        self.assertFalse(test_outcome(data)['resource_only'])
        data=limited_queue();data['runs'][0]['result']['cases'].append({'status':'INVALID','trials':[]})
        self.assertFalse(test_outcome(data)['resource_only'])

    def test_text_report_has_human_summary_collapsed_json_and_no_fake_success(self):
        from ucode.test_archive import write_text_report
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'report.html';data=limited_queue();before=copy.deepcopy(data);write_text_report(p,data,'Очередь')
            doc=p.read_text(encoding='utf-8');self.assertIn('Готовых повторов: 6 / 8',doc)
            self.assertIn('НЕ ВСЕ ТЕСТЫ ВЫПОЛНЕНЫ',doc);self.assertIn('<details>',doc)
            self.assertIn('RESOURCE_LIMIT',doc);self.assertEqual(data,before)

    def test_browser_anchor_uses_default_browser_without_html_editor(self):
        import sys
        from ucode.open_reports import open_html_report
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'help.html';p.write_text('help',encoding='utf-8')
            with patch('ucode.open_reports._windows_browser_executable',return_value=Path('browser.exe')),patch('ucode.open_reports.subprocess.Popen') as win,patch('ucode.open_reports.webbrowser.open_new_tab',return_value=True) as other:
                open_html_report(p,anchor='queue')
                url=win.call_args.args[0][1] if sys.platform=='win32' else other.call_args.args[0]
                self.assertEqual(url,p.as_uri()+'#queue')
            with self.assertRaises(ValueError):open_html_report(p,anchor='../../bad')


class HelpWindowTests(unittest.TestCase):
    def setUp(self):
        from ucode.batch_gui import BatchWindow
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        try:self.root=tk.Tk()
        except tk.TclError as exc:self.skipTest(str(exc))
        self.root.withdraw();self.app=BatchWindow(self.root,Path(self.temp.name)/'out')
    def tearDown(self):
        if hasattr(self,'app'):self.root.destroy();self.app=self.root=None;gc.collect()

    def test_context_navigation_does_not_start_or_change_settings_and_disables_launch(self):
        before=(self.app.print_settings,self.app.read_generation_options())
        self.app.input_valid=self.app.plan_valid=True
        with patch.object(self.app,'launch') as launch:
            for page,topic in CONTEXT.items():
                self.app.notebook.select(self.app.pages[page]);self.app.help_view.context()
                self.assertEqual(self.app.help_view.topic,topic)
                self.app.update_buttons();self.assertTrue(self.app.generate.instate(['disabled']))
                self.app.help_view.jump()
                self.assertEqual(self.app.notebook.select(),str(self.app.pages[next(t['page'] for t in TOPICS if t['id']==topic)]))
            launch.assert_not_called()
        self.assertEqual((self.app.print_settings,self.app.read_generation_options()),before)
        self.assertTrue(self.root.bind('<F1>'));self.assertTrue(self.app.brand_image.width()>0)

    def test_all_help_topics_parts_fit_at_100_125_150_percent(self):
        from ucode.batch_gui import BatchWindow
        for scale in (96/72,120/72,144/72):
            window=tk.Tk();window.withdraw();window.tk.call('tk','scaling',scale)
            app=BatchWindow(window,Path(self.temp.name)/str(scale)/'out')
            try:
                app.show_help()
                for topic in TOPICS:
                    app.help_view.show(topic['id'])
                    for part in range(3):
                        app.help_view.part.set(part);app.help_view.render();window.update_idletasks()
                        self.assertLessEqual(window.winfo_reqwidth(),1326,(scale,topic['id']))
                        self.assertLessEqual(window.winfo_reqheight(),668,(scale,topic['id']))
                        self.assertEqual(app.help_text.get('1.0','end-1c'),topic['paragraphs'][part])
                app.present_test(limited_queue());window.update_idletasks()
                self.assertLessEqual(window.winfo_reqheight(),668,(scale,'RAM outcome'))
                self.assertLessEqual(window.winfo_reqwidth(),1326,(scale,'RAM outcome'))
            finally:window.destroy();del app,window;gc.collect()

    def test_console_resource_completion_replaces_running_text_keeps_progress_and_files(self):
        p=Path(self.temp.name)/'series';p.mkdir();source=p/'commands.json';source.write_text(json.dumps(limited_queue(),ensure_ascii=False),encoding='utf-8');before=source.read_bytes()
        self.app.progress['value']=75;self.app.status_var.set('Запуск процессов конвейера');self.app.speed_var.set('Этап: 0')
        self.app.complete(p)
        self.assertIn('ОЗУ',self.app.result_var.get());self.assertIn('6 / 8',self.app.result_details.get())
        self.assertIn('Серия завершена',self.app.status_var.get());self.assertNotIn('Этап: 0',self.app.speed_var.get())
        self.assertEqual(float(self.app.progress['value']),75);self.assertEqual(source.read_bytes(),before)
        self.assertEqual(self.app.last_report,p/'commands.html')

    def test_tooltip_timer_is_cancelled_and_help_opens_correct_anchor(self):
        from ucode.ui_hints import Hint
        h=Hint(self.app.help_button,'Объяснение');h.schedule();self.assertIsNotNone(h.timer);h.hide();self.assertIsNone(h.timer)
        with patch.object(self.app,'open_path') as opened:
            self.app.help_view.show('queue');self.app.help_view.browser()
            args,kwargs=opened.call_args;self.assertEqual(kwargs['anchor'],'queue');self.assertTrue(args[0].is_file())
        h.schedule();self.app.help_button.destroy();self.assertIsNone(h.timer)


if __name__=='__main__':unittest.main()
