"""Operator-only acceptance test; no HTTP listener and no scoring side effects."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import socket
import subprocess
import time

IMAGE = Path('/opt/arena/image')
WORK = Path('/work')


class VM:
    def __init__(self, name, deployment=None):
        self.deployment=deployment
        self.root = WORK/name
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.disk = self.root/'lab.qcow2'
        self.iso = self.root/'operator.iso'
        self.process = None
        self.stream = None
        self.sock = None

    def boot(self):
        if not self.disk.exists():
            subprocess.run(['qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', str(IMAGE/'base.qcow2'), str(self.disk)], check=True, capture_output=True)
        source = self.root/'operator'
        source.mkdir(exist_ok=True)
        import shutil
        shutil.copyfile('/opt/arena/guest.py', source/'guest.py')
        if self.deployment:
            import base64
            request={key:value for key,value in self.deployment.items() if key!='files'}
            (source/'request.json').write_text(json.dumps(request))
            for name,content in self.deployment['files'].items():
                target=source/'source'/name
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(base64.b64decode(content,validate=True))
        subprocess.run(['genisoimage', '-quiet', '-R', '-o', str(self.iso), str(source)], check=True)
        rpc = self.root/'rpc.sock'
        rpc.unlink(missing_ok=True)
        log = (self.root/'console.log').open('ab')
        self.process = subprocess.Popen([
            'qemu-system-x86_64', '-enable-kvm', '-machine', 'q35', '-cpu', 'host',
            '-smp', '2', '-m', '3072', '-display', 'none', '-no-reboot', '-net', 'none',
            '-kernel', str(IMAGE/'kernel'), '-initrd', str(IMAGE/'initrd'),
            '-append', 'root=/dev/vda rw console=ttyS0 quiet',
            '-drive', 'file='+str(self.disk)+',if=virtio,format=qcow2',
            '-drive', 'file='+str(self.iso)+',media=cdrom,readonly=on,format=raw',
            '-device', 'virtio-serial', '-chardev', 'socket,id=rpc,path='+str(rpc)+',server=on,wait=off',
            '-device', 'virtserialport,chardev=rpc,name=arena.rpc', '-serial', 'stdio',
        ], stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        log.close()
        for _ in range(100):
            if rpc.exists(): break
            if self.process.poll() is not None: raise RuntimeError('QEMU failed to start')
            time.sleep(.1)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(420)
        self.sock.connect(str(rpc))
        self.stream = self.sock.makefile('rwb')
        result = self.read()
        if not result.get('ready'): raise RuntimeError(str(result))

    def read(self):
        raw = self.stream.readline(128*1024)
        if not raw.endswith(b'\n'): raise RuntimeError('Invalid or oversized guest response')
        return json.loads(raw)

    def call(self, command, **fields):
        self.stream.write(json.dumps({'command': command, **fields}).encode()+b'\n')
        self.stream.flush()
        result = self.read()
        if not result.get('ok'): raise RuntimeError(result.get('error', 'Guest error'))
        return result['result']

    def stop(self):
        if self.process and self.process.poll() is None:
            try:
                self.stream.write(b'{"command":"shutdown"}\n')
                self.stream.flush()
                self.process.wait(timeout=60)
            except Exception:
                self.process.kill()
                self.process.wait(timeout=10)
                raise RuntimeError('Lab did not stop cleanly; persistence proof invalid')
        if self.stream: self.stream.close()
        if self.sock: self.sock.close()

    def force_cleanup(self):
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)
        if self.stream: self.stream.close()
        if self.sock: self.sock.close()


def check(name):
    started = time.monotonic()
    vm = VM(name)
    order_id = name+'-order'
    try:
        vm.boot()
        print(name+': booted', flush=True)
        deployed = vm.call('deploy')
        print(name+': applied', flush=True)
        assert len(deployed['tables']) == 2 and len(deployed['functions']) == 3
        before = vm.call('order', order_id=order_id)
        print(name+': managed Lambda flow passed', flush=True)
        vm.stop()
        vm.boot()
        print(name+': resumed', flush=True)
        after = vm.call('inventory')
        assert before['tables'] == after['tables']
        assert any(row['orderId']['S'] == order_id for row in after['orders'])
        assert len(after['processed']) == 2
        assert all(row['orderId']['S'] == order_id for row in after['orders']), 'Cross-lab data found'
        vm.call('order', order_id=name+'-after-resume')
        vm.stop()
        return {'lab': name, 'deployed': True, 'managed_lambda_flow': True, 'persistent_resume': True,
                'elapsed_seconds': round(time.monotonic()-started, 1)}
    finally:
        vm.force_cleanup()


def main():
    # Separate pilot container has a hard 8 GiB cap. Preserve host headroom too.
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
    if available < 13*1024**3:
        raise RuntimeError('Pilot requires 13 GiB available host memory (6 GiB guests + host reserve)')
    if list(WORK.glob('pilot-*/lab.qcow2')):
        raise RuntimeError('Use a fresh pilot volume; existing lab disks are preserved')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(check, ['pilot-a', 'pilot-b']))
    report = {'status': 'passed', 'labs': results, 'public_ports': [], 'host_docker_socket': False}
    peak = Path('/sys/fs/cgroup/memory.peak')
    if peak.exists(): report['container_memory_peak_bytes'] = int(peak.read_text())
    (WORK/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
