"""Bounded VM admission; no participant-controlled limits or host paths."""
from pathlib import Path
import shutil
import threading
import os

GIB=1024**3


def available_memory():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):return int(line.split()[1])*1024
    return 0


def cgroup_headroom():
    try:
        maximum=Path('/sys/fs/cgroup/memory.max').read_text().strip()
        if maximum=='max':return None
        return max(0,int(maximum)-int(Path('/sys/fs/cgroup/memory.current').read_text()))
    except (OSError,ValueError):return None


class Capacity:
    def __init__(self,maximum=2,*,memory=available_memory,disk=None,cgroup=cgroup_headroom,reserve=6*GIB,budget=2*GIB):
        if not 1<=maximum<=4:raise ValueError('Runner concurrency must be between 1 and 4')
        self.maximum=maximum;self.memory=memory;self.disk=disk or (lambda:shutil.disk_usage('/work').free)
        self.cgroup=cgroup;self.reserve=reserve;self.budget=budget;self.active=0;self.lock=threading.Lock()
        self.shared_directory=os.getenv('VM_SLOTS_DIR','')
        self.shared_handles=[]

    def _status(self):
        # Count active reservations as well as resident memory: conservative while
        # QEMU is still starting and has not touched its full guest RAM yet.
        credits=max(0,min(self.maximum-self.active,(self.memory()-self.reserve)//self.budget-self.active))
        headroom=self.cgroup()
        if headroom is not None:credits=max(0,min(credits,headroom//self.budget-self.active))
        reason=None
        if self.disk()<2*GIB:credits=0;reason='disk'
        elif credits==0 and self.active<self.maximum:reason='memory'
        if self.shared_directory:
            from shared_slots import available
            credits=min(credits,available(self.shared_directory))
        return {'capacity':self.maximum,'running':self.active,'available':int(credits),'paused_reason':reason}

    def status(self):
        with self.lock:return self._status()

    def acquire(self):
        with self.lock:
            if not self._status()['available']:return False
            if self.shared_directory:
                from shared_slots import take
                handle=take(self.shared_directory)
                if handle is None:return False
                self.shared_handles.append(handle)
            self.active+=1;return True

    def release(self):
        with self.lock:
            if self.active<=0:raise RuntimeError('Unbalanced VM release')
            self.active-=1
            if self.shared_handles:self.shared_handles.pop().close()
