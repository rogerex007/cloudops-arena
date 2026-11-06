from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path

PATH=Path(__file__).resolve().parents[3]/'apps/runner/capacity.py'
spec=importlib.util.spec_from_file_location('runner_capacity',PATH)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
GIB=module.GIB


def test_fifty_competing_requests_only_acquire_two_slots():
    pool=module.Capacity(2,memory=lambda:32*GIB,disk=lambda:100*GIB,cgroup=lambda:None)
    with ThreadPoolExecutor(max_workers=50) as executor:results=list(executor.map(lambda _:pool.acquire(),range(50)))
    assert sum(results)==2 and pool.status()['running']==2
    pool.release();assert pool.acquire()
    pool.release();pool.release();assert pool.status()['available']==2


def test_low_memory_disk_and_cgroup_stop_new_vms():
    pool=module.Capacity(2,memory=lambda:7*GIB,disk=lambda:100*GIB,cgroup=lambda:None)
    assert pool.acquire() is False and pool.status()['paused_reason']=='memory'
    pool=module.Capacity(2,memory=lambda:32*GIB,disk=lambda:GIB,cgroup=lambda:None)
    assert pool.acquire() is False and pool.status()['paused_reason']=='disk'
    pool=module.Capacity(4,memory=lambda:32*GIB,disk=lambda:100*GIB,cgroup=lambda:4*GIB)
    assert pool.acquire() and pool.acquire() and not pool.acquire()
