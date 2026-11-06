"""Cross-container VM ceiling. The kernel releases locks if a service dies."""
import fcntl
from pathlib import Path


def take(directory, maximum=2):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    for index in range(maximum):
        handle = (root/f'vm-{index}.lock').open('a+')
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except BlockingIOError:
            handle.close()
    return None


def available(directory, maximum=2):
    held = []
    try:
        for _ in range(maximum):
            handle = take(directory, maximum)
            if handle is None: break
            held.append(handle)
        return len(held)
    finally:
        for handle in held: handle.close()
