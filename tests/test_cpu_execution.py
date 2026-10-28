"""Small hardware models and actual spawned workers; never a load test."""
import json
import multiprocessing
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


def crash_worker(connection, stop, engine_key, engine_spec):
    import os
    os._exit(7)


class HardwareTests(unittest.TestCase):
    def test_topology_counts_available_cores_without_summing_smt(self):
        from ucode.hardware import cpu_model, worker_presets
        cpus = [{"id": i, "group": i // 64, "logical": i % 64,
                 "core": (i % 64) // 2} for i in range(144)]
        model = cpu_model(cpus, allowed_ids={0, 1, 64, 65, 66, 67})
        self.assertEqual(model["logical_processors"], 144)
        self.assertEqual(model["physical_cores"], 72)
        self.assertEqual(model["available_logical"], 6)
        self.assertEqual(model["available_physical"], 3)
        self.assertEqual(worker_presets(1), (1,))
        self.assertIn(144, worker_presets(144))
        single = cpu_model([{"id": 0, "group": 0, "core": 0, "logical": 0}])
        self.assertEqual(single["available_physical"], 1)
        self.assertFalse(single["smt"])

    def test_missing_topology_does_not_invent_physical_cores(self):
        from ucode.hardware import cpu_model
        model = cpu_model([], fallback_count=36)
        self.assertIsNone(model["physical_cores"])
        self.assertEqual(model["available_logical"], 36)
        self.assertTrue(model["reason"])
        with self.assertRaises(ValueError):
            cpu_model([{"id": 1, "group": 0, "core": 0, "logical": 0}], allowed_ids=set())

    def test_snapshot_is_sanitized_and_probe_preserves_existing_file(self):
        from ucode.hardware import inspect_hardware, probe_directory
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "keep.txt"; original.write_bytes(b"keep")
            snap = inspect_hardware(root)
            self.assertGreaterEqual(snap["cpu"]["available_logical"], 1)
            self.assertGreater(snap["disk"]["free_bytes"], 0)
            self.assertNotIn(str(root), json.dumps(snap))
            self.assertTrue(probe_directory(root)["writable"])
            self.assertEqual(list(root.iterdir()), [original])
            self.assertEqual(original.read_bytes(), b"keep")


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        from ucode.hardware import inspect_cpu
        if self._testMethodName != "test_limits_validate_cpu_memory_and_batch_independently" and inspect_cpu()["available_logical"] < 2:
            self.skipTest("Два доступных CPU нужны для проверки двух процессов")

    def test_crashed_process_is_detected_and_reaped(self):
        from ucode.execution import ExecutionOptions, encode_values
        before = {p.pid for p in multiprocessing.active_children()}
        with patch("ucode.execution._worker", crash_worker), self.assertRaisesRegex(RuntimeError, "без результата|exitcode"):
            encode_values(["200000000001", "200000000002"], options=ExecutionOptions("process", 2, 1))
        self.assertEqual({p.pid for p in multiprocessing.active_children()} - before, set())

    def test_limits_validate_cpu_memory_and_batch_independently(self):
        from ucode.execution import ExecutionOptions, execution_plan
        cpu = {"available_logical": 144}
        plan = execution_plan(ExecutionOptions("process", 128, 1), 3, cpu, 64 * 1024**3)
        self.assertEqual(plan["requested_workers"], 128)
        self.assertEqual(plan["effective_workers"], 3)
        for options in (("unknown", 2, 1), ("serial", True, 1), ("process", 0, 1), ("process", 2, 0)):
            with self.assertRaises(ValueError): ExecutionOptions(*options)
        with self.assertRaises(ValueError):
            execution_plan(ExecutionOptions("process", 145, 1), 3, cpu, None)
        with self.assertRaisesRegex(ValueError, "RAM"):
            execution_plan(ExecutionOptions("process", 2, 1), 3, cpu, 64 * 1024**2)
        with self.assertRaisesRegex(ValueError, "RAM"):
            execution_plan(ExecutionOptions("process", 2, 1), 3, cpu, None)

    def test_real_spawn_preserves_order_and_matches_serial_matrices(self):
        from ucode.execution import ExecutionOptions, encode_values
        values = [f"{200000000000 + i:012d}" for i in range(6)]
        serial, serial_info = encode_values(values, options=ExecutionOptions())
        parallel, info = encode_values(values, options=ExecutionOptions("process", 2, 1))
        self.assertEqual(parallel, serial)
        self.assertEqual(serial_info["backend"], "serial")
        self.assertEqual(len(info["worker_pids"]), 2)
        self.assertEqual(info["completed_values"], 6)
        self.assertLessEqual(info["max_in_flight_values"], 2)

    def test_child_error_and_cancellation_leave_no_owned_workers(self):
        from ucode.execution import ExecutionOptions, encode_values
        before = {p.pid for p in multiprocessing.active_children()}
        with self.assertRaisesRegex(RuntimeError, "ASCII|twelve"):
            encode_values(["BAD", "200000000001"], options=ExecutionOptions("process", 2, 1))
        stop = threading.Event()
        def progress(done, total):
            if done: stop.set()
        with self.assertRaises(InterruptedError):
            encode_values([f"{200000000000+i:012d}" for i in range(7)],
                          options=ExecutionOptions("process", 2, 1), cancel=stop, on_progress=progress)
        self.assertEqual({p.pid for p in multiprocessing.active_children()} - before, set())

    def test_real_process_pdf_copies_and_report(self):
        from ucode.batch import run_batch
        from ucode.execution import ExecutionOptions
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / "codes.txt"
            source.write_text("000000000001\n200000000002\n000000000001\n", encoding="utf-8")
            folder = run_batch(source, root / "out", mode="both", copies_per_value=3,
                               duplicate_policy="unique", execution=ExecutionOptions("process", 2, 1))
            data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn(data["status"], ("COMPLETE", "LIMITED"))
            self.assertEqual(data["execution"]["completed_values"], 2)
            self.assertEqual(data["execution"]["effective_workers"], 2)
            self.assertEqual(data["files"]["multipage"]["pages"], 6)
            self.assertEqual(data["qa"]["multipage"]["status"], "PASS")
            self.assertIn("hardware", data)
            self.assertIn("ПРОЦЕССОР", (folder / "ОТЧЁТ.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
