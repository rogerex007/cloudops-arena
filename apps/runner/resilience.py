"""Root-owned resilience judge and append-only simulated business-operation sink."""
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import uuid


class Operations:
    def __init__(self):
        self.records=[]
        self.lock=threading.Lock()
        self.expected=None
        self.active_service=None
        self.violations=0
        ledger=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.connection.settimeout(2)
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if self.path!='/operations' or not 0<length<=2048:raise ValueError()
                    body=json.loads(self.rfile.read(length))
                    if not isinstance(body,dict) or set(body)!={'service','orderId'}:raise ValueError()
                    if body['service'] not in ('payments','inventory') or not isinstance(body['orderId'],str) or not 1<=len(body['orderId'])<=128:raise ValueError()
                    with ledger.lock:
                        if body['service']!=ledger.active_service:
                            ledger.violations+=1;raise ValueError()
                        if len(ledger.records)>=128:raise ValueError()
                        ledger.records.append((body['service'],body['orderId']))
                except (ValueError,TypeError,KeyError,TimeoutError):
                    self.send_response(400);self.end_headers();return
                data=b'{"recorded":true}'
                self.send_response(201);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.daemon_threads=False
        self.url=f'http://127.0.0.1:{self.server.server_port}/operations'

    def __enter__(self):
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        return self

    def __exit__(self,exc_type,exc,tb):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)
        if exc_type is None and self.expected is not None:self.require(self.expected)

    def activate(self,service):
        with self.lock:self.active_service=service

    def snapshot(self):
        with self.lock:return Counter(self.records)

    def require(self,expected):
        self.expected=Counter(expected)
        if self.violations or self.snapshot()!=Counter(expected):
            raise ValueError('Las operaciones simuladas deben registrarse una sola vez por servicio y orden mediante OPERATIONS_URL; una fila o un log no bastan.')


def failed_ids(response,records):
    """Model ReportBatchItemFailures. None represents a handler exception."""
    ids={record['messageId'] for record in records}
    if response is None:return ids
    try:
        failures=response['batchItemFailures']
        if not isinstance(failures,list):raise ValueError()
        values=[entry['itemIdentifier'] for entry in failures]
        if any(not isinstance(value,str) for value in values) or len(values)!=len(set(values)) or not set(values)<=ids:raise ValueError()
        return set(values)
    except (KeyError,TypeError,ValueError):
        raise ValueError('batchItemFailures debe contener solo los messageId fallidos del lote actual, sin duplicados.')


def sqs_event(messages):
    return {'Records':[{'messageId':message['MessageId'],'receiptHandle':message.get('ReceiptHandle',''),
        'body':message['Body'],'eventSource':'aws:sqs','awsRegion':'us-east-1',
        'attributes':message.get('Attributes',{})} for message in messages]}


def receive(sqs,url,count=1,timeout=12):
    messages=[];deadline=time.monotonic()+timeout
    while len(messages)<count and time.monotonic()<deadline:
        messages.extend(sqs.receive_message(QueueUrl=url,MaxNumberOfMessages=min(10,count-len(messages)),
            WaitTimeSeconds=1,AttributeNames=['ApproximateReceiveCount']).get('Messages',[]))
    if len(messages)!=count:raise ValueError('No llegaron los mensajes esperados a SQS dentro del tiempo del laboratorio.')
    return messages


def exercise(working,env,limits,emit,ledger,fixture,cases,batches):
    from runtime import invoke,check_consumer,check_envelope,check_order
    db,sqs=fixture['db'],fixture['sqs']
    queues,dlq=fixture['queues'],fixture['dlq']
    processed=fixture['processed']
    def item(service,order_id):
        return db.get_item(TableName=processed,Key={'eventId':{'S':order_id},'service':{'S':service}},ConsistentRead=True).get('Item',{})
    def consume(service,messages,environment=env,allow_failure=False):
        event=sqs_event(messages)
        response=invoke(working,service,event,environment,limits,allow_failure=allow_failure,operations=ledger)
        return response,failed_ids(response,event['Records'])
    def acknowledge(url,messages):
        for message in messages:sqs.delete_message(QueueUrl=url,ReceiptHandle=message['ReceiptHandle'])
    expected={(service,case['orderId']):1 for service in queues for case in cases}
    emit('duplicates','running');ledger.require(expected)
    # Same business order, new transport IDs and two deliveries in one batch.
    duplicate=cases[0]
    for service,url in queues.items():
        original=next(message for message in batches[service] if json.loads(message['Body'])['detail']['orderId']==duplicate['orderId'])
        for _ in range(2):
            envelope=json.loads(original['Body']);envelope['id']=str(uuid.uuid4())
            sqs.send_message(QueueUrl=url,MessageBody=json.dumps(envelope))
        messages=receive(sqs,url,count=2)
        response,failures=consume(service,messages)
        if failures:raise ValueError('Los duplicados ya procesados deben reconocerse como éxito, sin repetir la operación.')
        check_consumer(response,item(service,duplicate['orderId']),service,duplicate['orderId'])
        ledger.require(expected);acknowledge(url,messages)
    emit('duplicates','passed')

    emit('partial_batch','running')
    good_id=uuid.uuid4().hex;good_message=str(uuid.uuid4());bad_message=str(uuid.uuid4())
    envelope=json.loads(batches['payments'][0]['Body']);envelope['detail']['orderId']=good_id;envelope['id']=str(uuid.uuid4())
    records=[{'messageId':good_message,'body':json.dumps(envelope)},
        {'messageId':bad_message,'body':'{"detail":{}}'}]
    response=invoke(working,'payments',{'Records':records},env,limits,allow_failure=True,operations=ledger)
    if failed_ids(response,records)!={bad_message}:raise ValueError('El lote mixto debe reportar solo el mensaje inválido en batchItemFailures.')
    check_consumer({'batchItemFailures':[]},item('payments',good_id),'payments',good_id)
    expected['payments',good_id]=1;ledger.require(expected)
    emit('partial_batch','passed')

    emit('failure','running')
    payload={'orderId':uuid.uuid4().hex,'customerId':'incident-'+uuid.uuid4().hex[:8],'total':'47.25'}
    order_id=payload['orderId']
    response=invoke(working,'orders',{'body':json.dumps(payload),'isBase64Encoded':False},env,limits,operations=ledger)
    order=db.get_item(TableName=fixture['orders'],Key={'orderId':{'S':order_id}},ConsistentRead=True).get('Item',{})
    check_order(response,order,payload)
    inventory=receive(sqs,queues['inventory'])
    check_envelope(json.loads(inventory[0]['Body']),payload)
    response,failures=consume('inventory',inventory)
    if failures:raise ValueError('Inventory debe continuar aunque Payments esté fallando.')
    check_consumer(response,item('inventory',order_id),'inventory',order_id)
    expected['inventory',order_id]=1;ledger.require(expected);acknowledge(queues['inventory'],inventory)
    emit('failure','passed');emit('retries','running')
    failure_env={**env,'FAIL_PAYMENTS':'true'}
    counts=[];dead=None;deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        messages=sqs.receive_message(QueueUrl=queues['payments'],MaxNumberOfMessages=1,WaitTimeSeconds=1,
            AttributeNames=['ApproximateReceiveCount']).get('Messages',[])
        if messages:
            message=messages[0];check_envelope(json.loads(message['Body']),payload)
            count=int(message.get('Attributes',{}).get('ApproximateReceiveCount','0'))
            if count<=0 or (counts and count<=counts[-1]):raise RuntimeError('SQS receive count evidence unavailable')
            counts.append(count)
            _response,failures=consume('payments',messages,failure_env,allow_failure=True)
            if failures!={message['MessageId']}:raise ValueError('Con FAIL_PAYMENTS=true debes fallar o reportar el mensaje, sin confirmarlo como procesado.')
            if item('payments',order_id):raise ValueError('El fallo controlado debe ocurrir antes de registrar el pago o su idempotencia.')
            ledger.require(expected)
            # Do not delete or forward the message: native SQS policy must redrive it.
        dead_messages=sqs.receive_message(QueueUrl=dlq,MaxNumberOfMessages=1,WaitTimeSeconds=1).get('Messages',[])
        if dead_messages:dead=dead_messages[0];break
        time.sleep(0.1)
    if len(counts)<2:raise RuntimeError('SQS did not produce repeated receives under the reviewed policy')
    emit('retries','passed');emit('dlq','running')
    if not dead:raise RuntimeError('Native Floci SQS redrive did not produce DLQ evidence')
    check_envelope(json.loads(dead['Body']),payload)
    if item('payments',order_id):raise ValueError('La orden fallida no debe figurar como pagada al llegar a la DLQ.')
    ledger.require(expected);emit('dlq','passed');emit('recovery','running')
    # Controlled re-delivery of the actual DLQ body, with the incident disabled.
    sqs.send_message(QueueUrl=queues['payments'],MessageBody=dead['Body'])
    messages=receive(sqs,queues['payments'])
    response,failures=consume('payments',messages)
    if failures:raise ValueError('Al desactivar FAIL_PAYMENTS el pago debe recuperarse.')
    check_consumer(response,item('payments',order_id),'payments',order_id)
    expected['payments',order_id]=1;ledger.require(expected)
    acknowledge(queues['payments'],messages);acknowledge(dlq,[dead])
    sqs.send_message(QueueUrl=queues['payments'],MessageBody=dead['Body'])
    duplicate_messages=receive(sqs,queues['payments'])
    _response,failures=consume('payments',duplicate_messages)
    if failures:raise ValueError('Repetir el mensaje recuperado debe ser un éxito sin repetir el pago.')
    ledger.require(expected);acknowledge(queues['payments'],duplicate_messages)
    emit('recovery','passed')
    return {'duplicate_deliveries_checked':True,'operation_counts_checked':True,'partial_batch_checked':True,
        'inventory_during_payment_failure':True,'payment_receive_counts':counts,'native_sqs_dlq_checked':True,
        'recovery_checked':True,'business_operation_sink':'root-owned-append-only',
        'handler_invocation':'unprivileged-subprocess','lambda_service_invoked':False,'terraform_applied':False}
