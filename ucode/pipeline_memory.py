"""Measured startup reservations for oversubscribed test pools, never a RAM fill."""
import math
import os

MIB=1024**2


def ready_memory():
    from .resource_monitor import tree_stats
    own=next((p for p in tree_stats(os.getpid()) if p['identity'][0]==os.getpid()),None)
    if not own or not own.get('rss'): return None
    return {'rss_bytes':own['rss'],'private_bytes':own.get('private'),
            'baseline_bytes':max(own['rss'],own.get('private') or 0),
            'scope':'One real pool process after imports/encoder preparation, before any QR work'}


def memory_plan(count,workers,batch,baseline=None,*,minimum=False):
    if type(count) is not int or count<1 or type(workers) is not int or not 1<=workers<=256 or type(batch) is not int or not 1<=batch<=1000:
        raise ValueError('Неверный план памяти/числа процессов')
    if baseline is not None and (type(baseline) not in (int,float) or not math.isfinite(baseline) or baseline<=0):
        raise ValueError('Неверное наблюдение памяти процесса')
    per=48*MIB if minimum else max(48*MIB,math.ceil(1.5*baseline)) if baseline is not None else 128*MIB
    bounded=min(count,2*workers*batch)
    return {'per_process_bytes':per,'bounded_values':bounded,'required_bytes':256*MIB+workers*per+bounded*40000,
            'baseline_bytes':baseline,'phase':'minimum_before_probe' if minimum else 'measured_startup' if baseline is not None else 'conservative_fallback',
            'model':'256MiB parent + max(48MiB, 1.5x measured startup) per process + bounded IPC; minimum48MiB before probe, fallback128MiB',
            'scope':'Estimate, not measured peak or quota; existing OS reserve, tree monitor and Windows Job remain active'}
