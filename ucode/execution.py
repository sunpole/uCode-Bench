"""Ordered, bounded encoding backends. Workers never touch Tk or final PDF.

Spawn + one pipe per owned process avoids the Windows 61-worker executor cap.
Only one batch is in flight per worker; cancellation reaps this pool only.
"""
from dataclasses import dataclass
import math
import multiprocessing as mp
import os
import time

from .engines import get_engine
from .hardware import inspect_cpu, memory_info


@dataclass(frozen=True)
class ExecutionOptions:
    backend: str = "serial"
    workers: int = 1
    batch_size: int = 32
    cpus: tuple = ()
    cpu_unit: str = "physical"
    ram_mode: str = "auto"

    def __post_init__(self):
        if self.backend not in ("serial", "process", "thread"):
            raise ValueError("Доступны serial, process и thread")
        for value in (self.workers, self.batch_size):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("Процессы и партия должны быть положительными целыми числами")
        if self.batch_size > 1000:
            raise ValueError("Размер партии: от 1 до 1000")
        if self.cpus and (self.backend!="process" or self.cpu_unit not in ("physical","logical")):
            raise ValueError("Выбор ядер требует отдельных процессов")
        if self.ram_mode not in ("auto","max","50%","80%"):
            raise ValueError("Неверный бюджет ОЗУ")


def execution_plan(options, count, cpu, available_ram,*,buffered=False):
    if options.cpus:
        from .affinity import cpu_keys
        if len(cpu_keys(options.cpus))!=len(set(cpu_keys(options.cpus))) or not set(cpu_keys(options.cpus)).issubset(set(cpu_keys(cpu.get("available_cpus") or []))):
            raise ValueError("Выбранные ядра больше не доступны")
        if options.workers>len(options.cpus): raise ValueError("Процессов больше выбранных CPU")
        if options.cpu_unit=="physical" and len({(c["group"],c["core"]) for c in options.cpus})!=len(options.cpus):
            raise ValueError("Выбраны SMT-потоки одного ядра вместо разных физических ядер")
    if options.workers > cpu["available_logical"] and options.backend != "serial":
        raise ValueError(f"Процессов больше, чем доступных CPU: {cpu['available_logical']}")
    effective = min(options.workers, math.ceil(count / options.batch_size)) if options.backend != "serial" else 1
    if options.backend != "serial" and available_ram is None:
        raise ValueError("Свободная RAM неизвестна; процессы недоступны до проверки ресурсов")
    # A conservative preflight estimate, not a measured peak or a RAM quota.
    reserve = max(512 * 1024**2, (available_ram or 0) // 10)
    per_worker = 128 * 1024**2 if options.backend == "process" else 8 * 1024**2 if options.backend == "thread" else 0
    buffered_count=min(count,max(1,effective)*options.batch_size) if buffered else count
    cache_mib=useful_cache_mib(options,available_ram) if buffered else 0
    required = 256 * 1024**2 + buffered_count * 40000 + effective * per_worker+cache_mib*1024**2
    if available_ram is not None and available_ram < required + reserve:
        raise ValueError(f"Недостаточно свободной RAM для {effective} процессов и резерва ОС; уменьшите процессы")
    from .resource_monitor import ram_budget
    budget=ram_budget(options.ram_mode,available_ram) if available_ram is not None else None
    if budget and required>budget["budget_bytes"]: raise ValueError("План превышает безопасный бюджет ОЗУ; уменьшите число ядер или порцию")
    return {"backend": options.backend, "requested_workers": options.workers, "effective_workers": effective,
            "cpu_selection":{"unit":options.cpu_unit,"cpus":list(options.cpus),"worker_pinning":bool(options.cpus)},
            "ram_budget":budget,"detailed_metrics":"NOT_RUN — available in tests only",
            "sqlite_cache_mib":cache_mib,
            "batch_size": options.batch_size, "required_ram_estimate_bytes": required,
            "os_reserve_bytes": reserve, "ram_limit_enforced": False,
            "ram_check": "estimated" if available_ram is not None else "unknown",
            "scope": "Только кодирование QR; запись PDF и QA последовательны",
            "affinity": "OS scheduler within inherited affinity; backend does not widen CPU access", "start_method": "spawn" if options.backend == "process" else None}


def useful_cache_mib(options,available_ram):
    from .resource_monitor import ram_budget
    if available_ram is None: return 4
    budget=ram_budget(options.ram_mode,available_ram)["budget_bytes"]
    return max(4,min(512,budget//(32*1024**2))) if options.ram_mode=="max" else 16


def _worker(connection, stop, engine_key, engine_spec,encoding_only=False,cpus=()):
    try:
        if cpus:
            from .affinity import apply_affinity
            apply_affinity(list(cpus))
        engine = get_engine(engine_key, **engine_spec)
        (getattr(engine,"prepare_encoding",engine.prepare) if encoding_only else engine.prepare)()
        cpus = inspect_cpu().get("available_cpus")
        while not stop.is_set():
            job = connection.recv()
            if job is None: break
            index, values = job
            frames = engine.encode(values, cancel=stop)
            connection.send(("ok", index, frames, os.getpid(), cpus))
    except (EOFError, BrokenPipeError):
        pass
    except BaseException as exc:
        try: connection.send(("error", type(exc).__name__ + ": " + str(exc)))
        except (OSError, EOFError): pass
    finally:
        connection.close()


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Кодирование остановлено; созданные файлы сохранены")


def encode_values(values, *, engine_key="reportlab", options=None, plan=None, cancel=None,
                  on_progress=None, metadata=None, selected_engine=None, generator="qr",
                  mode="multipage", colorspace="DeviceCMYK",encoding_only=False,result_store=None):
    options = options or ExecutionOptions()
    engine_spec = {"generator": generator, "mode": mode, "colorspace": colorspace}
    engine = selected_engine or get_engine(engine_key, **engine_spec)
    if options.backend not in engine.info().execution_modes:
        raise ValueError("Движок не поддерживает выбранный способ выполнения")
    _cancelled(cancel)
    plan = plan or execution_plan(options, len(values), inspect_cpu(), memory_info()["available_bytes"])
    info = metadata if metadata is not None else {}
    info.update(plan, worker_pids=[], completed_values=0, max_in_flight_values=0)
    info["worker_affinity"] = {}
    info["encoder_only_preparation"]=encoding_only
    if options.backend == "serial":
        (getattr(engine,"prepare_encoding",engine.prepare) if encoding_only else engine.prepare)()
        if result_store is not None:
            for index,start in enumerate(range(0,len(values),options.batch_size)):
                _cancelled(cancel)
                batch=values[start:start+options.batch_size]
                frames=engine.encode(batch,cancel=cancel)
                if [frame.payload for frame in frames]!=batch: raise ValueError("Encoder изменил порядок кодов")
                result_store[index]=frames; info["completed_values"]=start+len(frames)
                info["max_in_flight_values"]=max(info["max_in_flight_values"],len(frames))
                if on_progress: on_progress(info["completed_values"],len(values))
            return result_store.finish(),info
        def observe(done, total):
            info["completed_values"] = done
            if on_progress: on_progress(done, total)
        frames = engine.encode(values, cancel=cancel, on_progress=observe)
        return frames, info
    if options.backend == "thread":
        return _thread_encode(values, engine, options, info, cancel, on_progress,encoding_only,result_store), info
    context = mp.get_context("spawn"); stop = context.Event()
    pool = []; result = result_store if result_store is not None else {}; sent = 0; completed = 0; chunks = math.ceil(len(values) / options.batch_size)
    try:
        for index in range(plan["effective_workers"]):
            _cancelled(cancel)
            parent, child = context.Pipe()
            assigned=(options.cpus[index],) if options.cpus else ()
            process = context.Process(target=_worker, args=(child, stop, engine_key, engine_spec,encoding_only,assigned), name="ucode-encoder")
            try: process.start()
            except BaseException:
                parent.close(); child.close(); raise
            child.close(); pool.append((process, parent))
        active = {}
        def assign(connection):
            nonlocal sent
            if sent < chunks:
                start = sent * options.batch_size
                batch = values[start:start+options.batch_size]
                try:
                    connection.send((sent, batch))
                except OSError as exc:
                    raise RuntimeError("Рабочий процесс завершился без результата; задача не доставлена") from exc
                active[connection] = (sent, batch)
                sent += 1
                info["max_in_flight_values"] = max(info["max_in_flight_values"], sum(len(b) for _, b in active.values()))
        for _, connection in pool: assign(connection)
        while active:
            _cancelled(cancel)
            changed = False
            for process, connection in pool:
                if connection not in active: continue
                try:
                    ready = connection.poll()
                except OSError as exc:
                    raise RuntimeError("Рабочий процесс завершился без результата; канал закрыт") from exc
                if ready:
                    try: message = connection.recv()
                    except (EOFError, OSError) as exc: raise RuntimeError("Рабочий процесс завершился без результата") from exc
                    if message[0] != "ok": raise RuntimeError("Ошибка рабочего процесса: " + message[1])
                    _, index, frames, pid, cpus = message
                    expected_index, batch = active.pop(connection)
                    if index != expected_index or [frame.payload for frame in frames] != list(batch):
                        raise ValueError("Рабочий процесс изменил порядок или количество кодов")
                    result[index] = frames; completed += len(frames)
                    info["completed_values"] = completed
                    if pid not in info["worker_pids"]: info["worker_pids"].append(pid)
                    info["worker_affinity"][str(pid)] = cpus
                    if on_progress: on_progress(completed, len(values))
                    _cancelled(cancel); assign(connection); changed = True
                elif process.exitcode is not None:
                    raise RuntimeError(f"Рабочий процесс завершился, exitcode={process.exitcode}")
            if not changed: time.sleep(.01)
        return (result_store.finish() if result_store is not None else [frame for i in range(chunks) for frame in result[i]]), info
    finally:
        stop.set()
        for process, connection in pool:
            try: connection.send(None)
            except (OSError, EOFError): pass
        deadline = time.monotonic() + .5
        for process, _ in pool: process.join(max(0, deadline-time.monotonic()))
        for process, _ in pool:
            if process.is_alive(): process.terminate()
        for process, connection in pool:
            process.join(2)
            if process.is_alive(): process.kill(); process.join(2)
            connection.close()
            process.close()


def _thread_encode(values, engine, options, info, cancel, on_progress,encoding_only=False,result_store=None):
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    import threading
    stop = threading.Event()
    (getattr(engine,"prepare_encoding",engine.prepare) if encoding_only else engine.prepare)()
    chunks = math.ceil(len(values) / options.batch_size)
    executor = ThreadPoolExecutor(max_workers=info["effective_workers"], thread_name_prefix="ucode-encoder")
    pending = {}; results = result_store if result_store is not None else {}; sent = completed = 0
    def submit():
        nonlocal sent
        if sent < chunks:
            batch = values[sent*options.batch_size:(sent+1)*options.batch_size]
            future = executor.submit(engine.encode, batch, cancel=stop)
            pending[future] = (sent, batch); sent += 1
            info["max_in_flight_values"] = max(info["max_in_flight_values"], sum(len(b) for _, b in pending.values()))
    try:
        for _ in range(info["effective_workers"]): submit()
        while pending:
            _cancelled(cancel)
            done, _ = wait(pending, timeout=.05, return_when=FIRST_COMPLETED)
            for future in done:
                index, batch = pending.pop(future); frames = future.result()
                if [frame.payload for frame in frames] != list(batch):
                    raise ValueError("Поток изменил порядок/количество кодов")
                results[index] = frames; completed += len(frames)
                info["completed_values"] = completed
                if on_progress: on_progress(completed, len(values))
                _cancelled(cancel); submit()
        return result_store.finish() if result_store is not None else [frame for index in range(chunks) for frame in results[index]]
    finally:
        stop.set()
        for future in pending: future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
