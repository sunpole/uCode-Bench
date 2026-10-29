import copy
import json
from pathlib import Path
import tempfile
import unittest

from ucode.graphical_report import chart_model, graphical_section, write_graphical_copy


def fixture():
    def trial(seconds, **extra):
        return {"status": "UNVERIFIED", "seconds": {"launcher_wall": seconds, "production": seconds - 1,
                "code_encoding": seconds - 2, "write_multipage": 1, "quality_checks": 0},
                "pdf_bytes": 2048, "memory": {"peak_tree_rss_bytes": 1048576}, **extra}
    return {"kind": "resource-lab", "status": "UNVERIFIED", "source_digest": "code-a",
            "config": {"repeats": 3, "qa_mode": "deferred", "output_mode": "multipage"},
            "cases": [{"id": "C1", "count": 100, "cpu_unit": "physical", "cpu_choice": "2", "backend": "process",
                       "status": "UNVERIFIED", "telemetry_mode": "off",
                       "trials": [trial(4), trial(2), trial(3), trial(999, warmup=True)]}]}


class GraphicalReportsTests(unittest.TestCase):
    def test_exact_raw_statistics_exclude_warmup_and_do_not_modify_source(self):
        data=fixture(); before=copy.deepcopy(data); model=chart_model(data)
        row=model["groups"][0]["rows"][0]
        self.assertEqual(row["wall"], {"median": 3, "min": 2, "max": 4})
        self.assertAlmostEqual(row["speed"]["median"], 100/3)
        self.assertEqual(row["ram"]["median"], 1)
        self.assertEqual(row["pdf"]["median"], 2/1024)
        self.assertEqual(len(row["trials"]), 3)
        self.assertEqual(sum(row["phases"].values()), 3)
        self.assertEqual(data, before)

    def test_failed_partial_nonfinite_and_error_trials_have_no_comparison_bars(self):
        for change in (lambda d: d["cases"][0]["trials"].pop(0),
                       lambda d: d["cases"][0]["trials"][0].update(status="INVALID"),
                       lambda d: d["cases"][0]["trials"][0].update(errors=["broken"]),
                       lambda d: d["cases"][0]["trials"][0]["seconds"].update(launcher_wall=float("nan"))):
            data=fixture(); change(data)
            row=chart_model(data)["groups"][0]["rows"][0]
            self.assertFalse(row["eligible"])
            self.assertIsNone(row["wall"])
            self.assertTrue(row["reason"])

    def test_group_count_quality_diagnostics_and_commands_separately(self):
        a=fixture(); b=fixture(); b["cases"][0]["telemetry_mode"]="cpu"
        c=fixture(); c["config"]["qa_mode"]="vector"
        data={"kind":"test-command-queue", "runs":[{"result": d} for d in (a,b,c)]}
        self.assertEqual(len(chart_model(data)["groups"]),3)

    def test_pipeline_overlap_not_stacked_as_wall_phases_and_cpu_not_invented(self):
        d=fixture(); d["kind"]="cpu-pipeline-lab"; c=d["cases"][0]; c["allocation"]="physical:12:2"
        for t in c["trials"]:
            t["seconds"].update(qr_service_sum=99,pdf_service_sum=88)
        row=chart_model(d)["groups"][0]["rows"][0]
        self.assertNotIn(99,row["phases"].values())
        self.assertIsNone(row["cpu"])

    def test_scientific_direct_and_merge_remain_separate(self):
        methods=[{"name": n,"category":category,"status":"PASS", "trials":[{"seconds":v,"qa":{"status":"PASS"}} for v in (2,4,3)]}
                 for n,category in (("Direct PDF","direct"),("pypdf","merge"))]
        model=chart_model({"config":{"count":200,"repeats":3},"methods":methods})
        self.assertEqual(len(model["groups"]),2)
        self.assertEqual(model["groups"][0]["rows"][0]["wall"]["median"],3)

    def test_cpu_weighting_and_missing_diagnostics_are_explicit(self):
        data=fixture(); data['cases'][0]['telemetry_mode']='cpu'
        trials=data['cases'][0]['trials']
        for t,mean,duration in zip(trials[:2],(20,80),(1,3)):
            t['memory']['cpu_telemetry']={'phases':{'QR':{'selected_cpu_load_pct':
                {'min':10,'mean':mean,'max':90,'sampled_seconds':duration}}}}
        value=chart_model(data)['groups'][0]['rows'][0]['cpu']['QR']
        self.assertEqual(value['mean'],65)
        self.assertEqual(value['sampled_seconds'],4)
        self.assertEqual(value['observed_repeats'],2)

    def test_running_reports_skip_chart_build_and_row_limit_is_visible(self):
        from ucode.graphical_report import embed_graphs
        from unittest.mock import patch
        with patch('ucode.graphical_report.graphical_section',side_effect=AssertionError('not in timed work')):
            self.assertEqual(embed_graphs('<h1>Run</h1>',{'status':'RUNNING'}),'<h1>Run</h1>')
        data=fixture(); data['cases']*=3
        with patch('ucode.graphical_report.MAX_ROWS',2):
            model=chart_model(data)
        self.assertEqual(model['omitted'],1)
        self.assertEqual(len(model['groups'][0]['rows']),2)

    def test_archive_button_creates_new_graphs_and_opens_html_without_changing_last_result(self):
        import gc
        import tkinter as tk
        from unittest.mock import patch
        from ucode.batch_gui import BatchWindow
        from ucode.test_archive import store_test
        with tempfile.TemporaryDirectory() as temp:
            root_path=Path(temp); source=root_path/'source'; source.mkdir()
            (source/'lab.json').write_text(json.dumps(fixture()),encoding='utf-8')
            try: root=tk.Tk()
            except tk.TclError as exc: self.skipTest(str(exc))
            root.withdraw(); app=BatchWindow(root,root_path/'out')
            try:
                store_test(source,app.archive_root); app.archive_view.refresh()
                app.archive_view.table.selection_set('0')
                last=(app.last_output,app.last_pdf,app.last_report)
                with patch.object(app,'open_path') as opened:
                    app.archive_view.open_graphs(); app.worker.join(15); app.poll()
                    self.assertFalse(app.busy)
                    path=opened.call_args.args[0]
                    self.assertEqual(path.suffix,'.html'); self.assertTrue(path.is_file())
                self.assertEqual((app.last_output,app.last_pdf,app.last_report),last)
            finally:
                if app.worker: app.worker.join(15)
                root.destroy(); del app,root; gc.collect()

    def test_offline_escaping_and_new_copy_leave_history_bytes_unchanged(self):
        data=fixture(); data["cases"][0]["id"]='</script><img src=x onerror=alert(1)>'
        section=graphical_section(data)
        self.assertNotIn('</script><img',section)
        self.assertNotIn('https://',section)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/"report.json"; source.write_text(json.dumps({"archive_schema":1,"data":data}),encoding="utf-8")
            before=source.read_bytes(); output=write_graphical_copy(source,root/"views")
            self.assertEqual(source.read_bytes(),before)
            self.assertTrue(output.is_file()); self.assertIn('Графики',output.read_text(encoding="utf-8"))
            self.assertNotEqual(output,write_graphical_copy(source,root/"views"))


if __name__ == '__main__': unittest.main()
