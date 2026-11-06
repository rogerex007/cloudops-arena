"""Internal KVM executor. Accepts files, never commands or host paths."""
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
import uuid

from policy import FILES, VALIDATOR, VALIDATORS
from progress import curated
from capacity import Capacity

POOL=Capacity(int(os.getenv('RUNNER_CONCURRENCY','2')))
MAX_BYTES=3*1024*1024


def execute(files,on_progress=None,validator=VALIDATOR):
    notify=on_progress or (lambda event:None)
    if validator not in VALIDATORS or set(files)!=set(VALIDATORS[validator]):
        raise ValueError('Unexpected source files')
    with tempfile.TemporaryDirectory(prefix='job-',dir='/work') as temporary:
        directory=Path(temporary)
        source=directory/'iso/source'
        hashes={}
        total=0
        for name, encoded in files.items():
            data=base64.b64decode(encoded,validate=True)
            total+=len(data)
            if len(data)>256*1024 or total>2*1024*1024:
                raise ValueError('Source too large')
            path=source/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(data)
            hashes[name]=hashlib.sha256(data).hexdigest()
        digest=hashlib.sha256(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        run_id=uuid.uuid4().hex
        (directory/'iso/request.json').write_text(json.dumps({'run_id':run_id,'source_digest':digest,'validator':validator}))
        subprocess.run(['genisoimage','-quiet','-J','-R','-o',str(directory/'input.iso'),str(directory/'iso')],check=True,timeout=15,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(['qemu-img','create','-f','qcow2','-F','qcow2','-b','/opt/arena/image/base.qcow2',str(directory/'disk.qcow2')],check=True,timeout=15,stdout=subprocess.DEVNULL)
        command=['qemu-system-x86_64','-machine','q35,accel=kvm','-cpu','host','-smp','2','-m','1536',
            '-kernel','/opt/arena/image/kernel','-initrd','/opt/arena/image/initrd',
            '-append','root=/dev/vda rw console=ttyS0 quiet panic=1','-display','none','-monitor','none','-net','none','-no-reboot',
            '-drive',f'file={directory}/disk.qcow2,if=virtio,format=qcow2',
            '-drive',f'file={directory}/input.iso,media=cdrom,readonly=on',
            '-serial',f'file:{directory}/console.log','-device','virtio-serial',
            '-chardev',f'file,id=result,path={directory}/result.json',
            '-device','virtserialport,chardev=result,name=arena.result',
            '-chardev',f'file,id=progress,path={directory}/progress.jsonl',
            '-device','virtserialport,chardev=progress,name=arena.progress']
        error_log=open(directory/'qemu.log','wb')
        # Bound any single overlay/console file even if a guest misbehaves.
        command=['prlimit','--fsize=536870912:536870912','--',*command]
        process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=error_log,start_new_session=True)
        try:
            notify(curated('vm','running'))
            started=time.monotonic();offset=0;pending=b'';booted=False
            def drain():
                nonlocal offset,pending,booted
                path=directory/'progress.jsonl'
                if not path.exists():return
                if path.stat().st_size>16000:raise RuntimeError('Oversized guest progress')
                with path.open('rb') as source:
                    source.seek(offset);chunk=source.read(16001);offset=source.tell()
                pending+=chunk
                while b'\n' in pending:
                    line,pending=pending.split(b'\n',1)
                    event=json.loads(line)
                    if not booted:
                        notify(curated('vm','passed'));booted=True
                    notify(curated(event.get('stage'),event.get('status')))
            while process.poll() is None:
                drain()
                if time.monotonic()-started>270:raise subprocess.TimeoutExpired(command,270)
                time.sleep(0.2)
            drain()
            path=directory/'result.json'
            if not path.exists() or not path.stat().st_size or path.stat().st_size>16000:
                error_log.flush()
                details=(directory/'qemu.log').read_text(errors='replace')[-2000:]
                console=(directory/'console.log').read_text(errors='replace')[-2500:] if (directory/'console.log').exists() else ''
                raise RuntimeError('No trusted VM result: '+details+' '+console)
            result=json.loads(path.read_text())
            if result.get('run_id')!=run_id or result.get('source_digest')!=digest or result.get('validator')!=validator or result.get('status') not in {'passed','failed','blocked'}:
                raise RuntimeError('Invalid VM result')
            if result.get('status')=='passed' and result.get('evidence',{}).get('network_interfaces')!=['lo']:
                raise RuntimeError('VM network isolation evidence missing')
            return result
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGKILL)
                process.wait()
            error_log.close()
            # TemporaryDirectory removes the ISO, overlay and evidence files only
            # after QEMU has exited. No persistent participant VM is retained.


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_args):
        pass

    def send(self,status,payload):
        data=json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        status=POOL.status()
        self.send(200 if self.path=='/health' else 404,{'ready':Path('/dev/kvm').exists() and status['available']>0,'validator':VALIDATOR,**status})

    def do_POST(self):
        self.connection.settimeout(15)
        secret=Path(os.environ['RUNNER_TOKEN_FILE']).read_text().strip()
        if not secret or not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+secret):
            self.send(401,{'error':'Authentication required'}); return
        if self.path!='/evaluate':
            self.send(404,{'error':'Not found'}); return
        if not POOL.acquire():
            self.send(409,{'error':'Runner busy'}); return
        streaming=False
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<=0 or length>MAX_BYTES:
                raise ValueError('Invalid request size')
            request=json.loads(self.rfile.read(length))
            if request.get('validator') not in VALIDATORS:
                raise ValueError('Unknown validator')
            streaming=self.headers.get('Accept')=='application/x-ndjson'
            if streaming:
                self.send_response(200);self.send_header('Content-Type','application/x-ndjson');self.end_headers()
            def frame(value):
                self.wfile.write(json.dumps(value).encode()+b'\n');self.wfile.flush()
            callback=(lambda event:frame({'type':'progress','event':event})) if streaming else None
            result=execute(request['files'],callback,request['validator'])
            if streaming:
                frame({'type':'progress','event':curated('cleanup','passed')})
                frame({'type':'result','result':result})
            else:self.send(200,result)
        except (ValueError,KeyError):
            if streaming:frame({'type':'error','error':'Invalid evaluation input'})
            else:self.send(422,{'error':'Invalid evaluation input'})
        except Exception:
            logging.exception('Isolated VM evaluation failed')
            if streaming:frame({'type':'error','error':'Isolated execution unavailable'})
            else:self.send(503,{'error':'Isolated execution unavailable'})
        finally:
            POOL.release()


if __name__=='__main__':
    ThreadingHTTPServer(('0.0.0.0',9000),Handler).serve_forever()
