"""Private durable FIFO for trusted playground templates, never scoring/code."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hmac
import base64
import hashlib
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import threading
import time
import urllib.request

from pilot import VM
from shared_slots import take
from policy import FILES

WORK = Path(os.getenv('PLAYGROUND_WORK', '/work'))
SLOTS = os.getenv('VM_SLOTS_DIR', '/slots')
LIMIT = 50
STOP = threading.Event()


@contextmanager
def db():
    connection = sqlite3.connect(WORK/'playgrounds.sqlite', timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('BEGIN IMMEDIATE')
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize():
    WORK.mkdir(parents=True, exist_ok=True)
    with db() as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS labs (id TEXT PRIMARY KEY, event TEXT NOT NULL, state TEXT NOT NULL, queued REAL, expires REAL NOT NULL, snapshot TEXT, captured REAL, message TEXT)')
        if 'provenance' not in {row[1] for row in connection.execute('PRAGMA table_info(labs)')}:
            connection.execute('ALTER TABLE labs ADD COLUMN provenance TEXT')
        if 'owner' not in {row[1] for row in connection.execute('PRAGMA table_info(labs)')}:
            connection.execute('ALTER TABLE labs ADD COLUMN owner TEXT')
        connection.execute('CREATE TABLE IF NOT EXISTS owners (id TEXT PRIMARY KEY,event TEXT NOT NULL,team TEXT NOT NULL,active_lab TEXT,candidate TEXT,expires REAL NOT NULL)')
        # QEMU children die with the old container; never pretend they are live.
        connection.execute("UPDATE labs SET state='failed',message='El servicio se reinició. Tus discos se conservaron; solicita actualizar.' WHERE state='preparing'")


def public(row, connection):
    if row is None:
        return {'status': 'unassigned', 'message': 'Prepara tu playground para explorar sus recursos.'}
    position = None
    if row['state'] == 'queued':
        position = connection.execute("SELECT count(*) FROM labs WHERE state='queued' AND (queued < ? OR (queued=? AND id<=?))", (row['queued'], row['queued'], row['id'])).fetchone()[0]
    return {'lab_id': row['id'][:12], 'status': row['state'], 'queue_position': position,
            'captured_at': row['captured'], 'expires_at': row['expires'],
            'snapshot': json.loads(row['snapshot']) if row['snapshot'] else None,
            'message': row['message'] or '', 'execution_limit': 2, 'capacity': LIMIT,
            'deployment':json.loads(row['provenance']) if row['provenance'] else None}


def validate_deployment(body):
    for key in ('event_id','team_id','evaluation_id'):
        if not isinstance(body.get(key),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',body[key]):raise ValueError('Invalid identity')
    if not re.fullmatch(r'[a-f0-9]{40}',str(body.get('commit_sha',''))):raise ValueError('Invalid commit')
    files=body.get('files',{})
    if set(files)!=set(FILES):raise ValueError('Unexpected files')
    hashes={};total=0
    for name,encoded in files.items():
        data=base64.b64decode(encoded,validate=True);total+=len(data)
        if len(data)>256*1024 or total>2*1024*1024:raise ValueError('Source too large')
        hashes[name]=hashlib.sha256(data).hexdigest()
    digest=hashlib.sha256(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if digest!=body.get('source_digest'):raise ValueError('Digest mismatch')
    attempt=body.get('attempt',1)
    if not isinstance(attempt,int) or not 1<=attempt<=5:raise ValueError('Invalid attempt')
    return hashlib.sha256(json.dumps([body['event_id'],body['team_id'],body['evaluation_id'],digest,attempt]).encode()).hexdigest()


def deploy_participant(body):
    lab_id=validate_deployment(body)
    current=owner_status(body['event_id'],body['team_id'])
    if current.get('status')!='open':raise BlockingIOError('Event not open')
    with db() as connection:
        row=connection.execute('SELECT * FROM labs WHERE id=?',(lab_id,)).fetchone()
        if row and row['state']=='parked' and row['provenance'] and row['expires']>time.time():
            result=json.loads(row['provenance'])['result']
            return result
        if row and row['state']=='preparing':raise BlockingIOError('Deployment already running')
        owner=reserve_owner(connection,body,lab_id,(current.get('receipt') or {}).get('lab_key'))
        available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
        if available<10*1024**3 or shutil.disk_usage(WORK).free<20*1024**3:raise BlockingIOError('Host capacity')
        handle=take(SLOTS)
        if handle is None:raise BlockingIOError('VM capacity')
        connection.execute("INSERT INTO labs(id,event,state,expires,message) VALUES(?,?,'preparing',?,'Desplegando entrega verificada.') ON CONFLICT(id) DO UPDATE SET state='preparing'",(lab_id,body['event_id'],time.time()+7200))
        connection.execute('UPDATE labs SET owner=? WHERE id=?',(owner,lab_id))
    deployment={**body,'run_id':uuid.uuid4().hex}
    vm=VM(lab_id,deployment)
    try:
        vm.boot()
        result=vm.call('deploy')
        if result.get('run_id')!=deployment['run_id'] or result.get('source_digest')!=body['source_digest'] or result.get('status')!='passed':
            raise ValueError('Deployment evidence mismatch')
        snapshot=sanitize(result.pop('snapshot'))
        vm.stop()
        # Confirm persistence using the emulator, not the Terraform return code alone.
        vm.boot()
        if sanitize(vm.call('inventory'))!=snapshot:raise ValueError('Persistence verification failed')
        vm.stop()
        result['deployment']={'lab_key':lab_id,'evaluation_id':body['evaluation_id'],
            'commit_sha':body['commit_sha'],'source_digest':body['source_digest']}
        provenance={**result['deployment'],'result':result}
        with db() as connection:
            connection.execute("UPDATE labs SET state='parked',snapshot=?,provenance=?,captured=?,message='Infraestructura desplegada desde tu commit verificado.' WHERE id=?",(json.dumps(snapshot),json.dumps(provenance),time.time(),lab_id))
        return result
    except Exception as exc:
        import logging
        logging.exception('Participant deployment failed')
        vm.force_cleanup()
        with db() as connection:
            connection.execute("UPDATE labs SET state='failed',message='Falló el despliegue; no se concedieron puntos.' WHERE id=?",(lab_id,))
            connection.execute('UPDATE labs SET expires=? WHERE id=?',(time.time()+300,lab_id))
            connection.execute('UPDATE owners SET candidate=NULL WHERE id=? AND candidate=?',(owner,lab_id))
        return {'status':'failed','result_code':'terraform_deployment_failed','validator':'aws-event-driven-deploy-v1',
            'source_digest':body['source_digest'],'run_id':deployment['run_id'],
            'message':'El despliegue no pudo completarse o conservarse. Revisa Terraform y vuelve a entregar. '+str(exc)[:1800]}
    finally:
        try:vm.force_cleanup()
        finally:handle.close()


def get(lab_id):
    with db() as connection:
        return public(connection.execute('SELECT * FROM labs WHERE id=?', (lab_id,)).fetchone(), connection)


def enqueue(lab_id, event):
    now = time.time()
    with db() as connection:
        row = connection.execute('SELECT * FROM labs WHERE id=?', (lab_id,)).fetchone()
        if row and row['event'] != event: raise ValueError('Owner mismatch')
        if row and row['state'] in ('queued', 'preparing', 'expired'):
            return public(row, connection)
        if row and row['expires'] <= now:
            connection.execute("UPDATE labs SET state='expired', message='El playground expiró.' WHERE id=?", (lab_id,))
        elif row:
            connection.execute("UPDATE labs SET state='queued',queued=?,message='Esperando un turno de ejecución.' WHERE id=?", (now, lab_id))
        else:
            if connection.execute("SELECT count(*) FROM labs WHERE state!='expired'").fetchone()[0] >= LIMIT:
                raise OverflowError('Se alcanzó el límite de 50 playgrounds. Contacta al instructor.')
            connection.execute('INSERT INTO labs(id,event,state,queued,expires,message) VALUES(?,?,?,?,?,?)',
                               (lab_id, event, 'queued', now, now+7200, 'Esperando un turno de ejecución.'))
        return public(connection.execute('SELECT * FROM labs WHERE id=?', (lab_id,)).fetchone(), connection)


def expire_event(event):
    with db() as connection:
        connection.execute("UPDATE labs SET expires=0 WHERE event=?", (event,))
        connection.execute('UPDATE owners SET expires=0 WHERE event=?',(event,))


def owner_status(event,team):
    token=Path(os.environ['RUNNER_TOKEN_FILE']).read_text().strip()
    request=urllib.request.Request('http://api:8000/internal/playgrounds/owners/'+event+'/'+team,headers={'Authorization':'Bearer '+token})
    with urllib.request.urlopen(request,timeout=3) as response:return json.load(response)


def reserve_owner(connection,body,lab_id,legacy_active=None):
    owner=hashlib.sha256(json.dumps([body['event_id'],body['team_id']]).encode()).hexdigest()
    row=connection.execute('SELECT * FROM owners WHERE id=?',(owner,)).fetchone()
    if not row and connection.execute('SELECT count(*) FROM owners').fetchone()[0]>=LIMIT:
        raise BlockingIOError('Participant capacity reached')
    if row and row['candidate'] and row['candidate']!=lab_id:
        candidate=connection.execute('SELECT state FROM labs WHERE id=?',(row['candidate'],)).fetchone()
        if candidate and candidate['state']=='preparing':raise BlockingIOError('Owner deployment in progress')
    connection.execute('INSERT INTO owners(id,event,team,active_lab,candidate,expires) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET candidate=excluded.candidate,expires=MAX(owners.expires,?)',
        (owner,body['event_id'],body['team_id'],legacy_active,lab_id,time.time()+7200,time.time()+600))
    if legacy_active:connection.execute('UPDATE labs SET owner=? WHERE id=?',(owner,legacy_active))
    connection.execute("UPDATE labs SET expires=MAX(expires,?) WHERE owner=? AND state='parked' AND expires>?",(time.time()+600,owner,time.time()))
    connection.execute("UPDATE labs SET expires=0 WHERE owner=? AND state='failed'",(owner,))
    return owner


def activate_committed(event,team,lab_id):
    status=owner_status(event,team);receipt=status.get('receipt') or {}
    if status.get('status')=='finished' or receipt.get('lab_key')!=lab_id:return False
    with db() as connection:
        row=connection.execute('SELECT * FROM labs WHERE id=?',(lab_id,)).fetchone()
        if not row or row['state']!='parked' or not row['provenance']:return False
        proof=json.loads(row['provenance'])
        if not all(proof.get(key)==receipt.get(key) for key in ('evaluation_id','source_digest','commit_sha')):return False
        owner=connection.execute('SELECT active_lab,candidate FROM owners WHERE id=?',(row['owner'],)).fetchone()
        if owner and owner['active_lab']==lab_id and owner['candidate'] is None:return True
        connection.execute('UPDATE owners SET active_lab=?,candidate=NULL,expires=? WHERE id=?',(lab_id,time.time()+7200,row['owner']))
        connection.execute('UPDATE labs SET expires=? WHERE id=?',(time.time()+7200,lab_id))
        connection.execute("UPDATE labs SET expires=0 WHERE owner=? AND id!=? AND state!='preparing'",(row['owner'],lab_id))
    expire()
    return True


def expire():
    # Only delete our digest-named lab directories after their VM has stopped.
    with db() as connection:
        owners=connection.execute("SELECT id FROM owners WHERE expires<=? AND NOT EXISTS (SELECT 1 FROM labs WHERE labs.owner=owners.id AND labs.state='preparing')",(time.time(),)).fetchall()
        for owner in owners:
            connection.execute('UPDATE labs SET expires=0 WHERE owner=?',(owner['id'],))
            connection.execute('DELETE FROM owners WHERE id=?',(owner['id'],))
        rows = connection.execute("SELECT id FROM labs WHERE expires<=? AND state!='preparing' AND state!='expired'", (time.time(),)).fetchall()
        for row in rows:
            root = WORK/row['id']
            if root.exists(): shutil.rmtree(root)
            connection.execute("UPDATE labs SET state='expired',snapshot=NULL,captured=NULL,message='Playground finalizado; recursos temporales eliminados.' WHERE id=?", (row['id'],))


def sanitize(snapshot):
    # Curated inventory only; never propagate logs, SDK URLs, code or credentials.
    result = {}
    for key in ('tables', 'functions', 'buses'):
        values = snapshot.get(key, [])
        if not isinstance(values, list) or len(values)>50: raise ValueError('Invalid inventory')
        result[key] = [str(value)[:128] for value in values]
    result['queues'] = [str(value).rstrip('/').split('/')[-1][:128] for value in snapshot.get('queues', [])[:50]]
    result['order_count'] = len(snapshot.get('orders', []))
    result['processed_count'] = len(snapshot.get('processed', []))
    return result


def execute(lab_id, handle):
    vm = VM(lab_id)
    try:
        vm.boot()
        snapshot = sanitize(vm.call('ensure'))
        vm.stop()
        with db() as connection:
            connection.execute("UPDATE labs SET state='parked',snapshot=?,captured=?,message='Recursos conservados en disco. Esta vista es la última captura.' WHERE id=? AND state='preparing'", (json.dumps(snapshot), time.time(), lab_id))
    except Exception:
        # Untrusted guest output stays in private logs and never enters the API.
        import logging
        logging.exception('Playground operation failed for %s', lab_id[:12])
        vm.force_cleanup()
        with db() as connection:
            connection.execute("UPDATE labs SET state='failed',message='No pudimos preparar el playground. Los discos se conservaron. Reintenta o contacta al instructor.' WHERE id=? AND state='preparing'", (lab_id,))
    finally:
        try: vm.force_cleanup()
        finally:
            handle.close()
            expire()


def reconcile_candidates():
    with db() as connection:
        candidates=connection.execute('SELECT event,team,candidate FROM owners WHERE candidate IS NOT NULL').fetchall()
    for candidate in candidates:
        try:activate_committed(candidate['event'],candidate['team'],candidate['candidate'])
        except (OSError,ValueError):pass


def schedule():
    with ThreadPoolExecutor(max_workers=2) as pool:
        active = set()
        while not STOP.wait(1):
            active = {future for future in active if not future.done()}
            expire()
            reconcile_candidates()
            with db() as connection:
                events = [row[0] for row in connection.execute("SELECT DISTINCT event FROM labs WHERE state!='expired'")]
            opened = []
            for event in events:
                try:
                    token = Path(os.environ['RUNNER_TOKEN_FILE']).read_text().strip()
                    request = urllib.request.Request('http://api:8000/internal/playgrounds/events/'+event, headers={'Authorization':'Bearer '+token})
                    with urllib.request.urlopen(request, timeout=3) as response: status = json.load(response)['status']
                    if status == 'finished': expire_event(event)
                    elif status == 'open': opened.append(event)
                except (OSError, ValueError, KeyError): pass  # fail closed
            if len(active)>=2: continue
            available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
            if available < 10*1024**3 or shutil.disk_usage(WORK).free < 20*1024**3: continue
            with db() as connection:
                rows = connection.execute("SELECT id,event FROM labs WHERE state='queued' AND expires>? ORDER BY queued,id", (time.time(),)).fetchall()
                row = next((row for row in rows if row['event'] in opened), None)
                if not row: continue
                handle = take(SLOTS)
                if handle is None: continue
                connection.execute("UPDATE labs SET state='preparing',message='Preparando o reanudando tu infraestructura aislada.' WHERE id=?", (row['id'],))
            active.add(pool.submit(execute, row['id'], handle))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args): pass

    def send(self, status, value):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        token = Path(os.environ['RUNNER_TOKEN_FILE']).read_text().strip()
        return bool(token) and hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+token)

    def do_GET(self):
        if self.path == '/health': return self.send(200, {'ready': Path('/dev/kvm').exists()})
        if not self.authorized(): return self.send(401, {'detail': 'Unauthorized'})
        match = re.fullmatch(r'/labs/([a-f0-9]{64})', self.path)
        if not match: return self.send(404, {})
        self.send(200, get(match[1]))

    def do_POST(self):
        self.connection.settimeout(20)
        if not self.authorized(): return self.send(401, {'detail': 'Unauthorized'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0<length<=(3*1024*1024 if self.path=='/deploy' else 2048): raise ValueError('Invalid body')
            body = json.loads(self.rfile.read(length))
            if self.path=='/deploy':return self.send(200,deploy_participant(body))
            if self.path=='/activate':
                if not all(isinstance(body.get(key),str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}',body[key]) for key in ('event_id','team_id','lab_key')):raise ValueError('Invalid identity')
                return self.send(200,{'activated':activate_committed(body['event_id'],body['team_id'],body['lab_key'])})
            event = body.get('event_id')
            if not isinstance(event,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',event): raise ValueError('Invalid event')
            if self.path == '/expire-event':
                expire_event(event)
                return self.send(200, {})
            match = re.fullmatch(r'/labs/([a-f0-9]{64})', self.path)
            if not match: return self.send(404, {})
            self.send(202, enqueue(match[1], event))
        except OverflowError as exc: self.send(429, {'detail': str(exc)})
        except BlockingIOError: self.send(409,{'detail':'VM capacity unavailable'})
        except OSError: self.send(503,{'detail':'Control plane temporarily unavailable'})
        except (ValueError, TypeError): self.send(422, {'detail': 'Invalid request'})


class Server(ThreadingHTTPServer):
    # A deploy handler owns its VM and slot. Drain it before container shutdown.
    daemon_threads=False


if __name__ == '__main__':
    initialize()
    scheduler = threading.Thread(target=schedule)
    scheduler.start()
    server = Server(('0.0.0.0',9001), Handler)
    def shutdown(_signal, _frame):
        STOP.set()
        threading.Thread(target=server.shutdown).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    server.serve_forever()
    scheduler.join()
    server.server_close()
