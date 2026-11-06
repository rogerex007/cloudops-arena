"""Root-owned mission-03 judge; participant handlers only run in child UIDs."""
import base64
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid

import boto3
from botocore.config import Config

from policy import PREFIX


def invoke(working,service,event,env,limits,*,allow_failure=False,operations=None):
    path=working/PREFIX/f'functions/{service}/handler.py'
    output=Path('/work/invoke-output.json')
    diagnostic=Path('/work/invoke-error.log')
    process=None
    if operations:operations.activate(service)
    try:
        with output.open('wb') as stdout,diagnostic.open('wb') as stderr:
            process=subprocess.Popen(['/opt/judge/bin/python','-I','/opt/arena/invoke.py'],
                stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,env=env,cwd='/work/home',
                preexec_fn=limits,start_new_session=True)
            process.communicate(json.dumps({'path':str(path),'event':event}).encode(),timeout=20)
        if allow_failure and process.returncode and process.returncode>0:
            return None
        if process.returncode or output.stat().st_size>1024*1024:
            raise ValueError(f'{service}: el handler falló. Revisa handler(event, context), las variables de entorno y sus llamadas a boto3.')
        try:return json.loads(output.read_text())
        except (ValueError,UnicodeError):raise ValueError(f'{service}: el handler debe devolver un objeto JSON válido.')
    except subprocess.TimeoutExpired:
        raise ValueError(f'{service}: el handler superó el tiempo permitido.')
    finally:
        if process:
            # Kill descendants even when the original handler process exited.
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait()
        if operations:operations.activate(None)


def check_order(response,item,payload):
    if not isinstance(response,dict) or response.get('statusCode')!=201:
        raise ValueError('Orders debe devolver statusCode 201.')
    try:
        body=json.loads(response['body']) if isinstance(response['body'],str) else response['body']
        valid=(body['orderId']==payload['orderId'] and body['status']=='CREATED'
            and item['orderId']['S']==payload['orderId'] and item['customerId']['S']==payload['customerId']
            and Decimal(item['total']['N'])==Decimal(str(payload['total'])) and item['status']['S']=='CREATED'
            and bool(item['createdAt']['S']))
    except (KeyError,TypeError,ValueError,InvalidOperation):valid=False
    if not valid:raise ValueError('Orders debe conservar orderId, customerId y total, y guardar status CREATED y createdAt en DynamoDB.')


def check_envelope(envelope,payload):
    try:
        detail=envelope['detail']
        valid=(envelope['source']=='com.cloudopsarena.orders' and envelope['detail-type']=='OrderCreated'
            and detail['orderId']==payload['orderId'] and detail['customerId']==payload['customerId']
            and Decimal(str(detail['total']))==Decimal(str(payload['total'])))
    except (KeyError,TypeError,ValueError,InvalidOperation):valid=False
    if not valid:raise ValueError('OrderCreated debe conservar orderId, customerId y total en ambas colas.')


def check_consumer(response,item,service,order_id):
    if not isinstance(response,dict) or response.get('batchItemFailures')!=[]:
        raise ValueError(f'{service}: devuelve batchItemFailures vacío al procesar mensajes válidos.')
    if not item or item.get('eventId',{}).get('S')!=order_id or item.get('service',{}).get('S')!=service or item.get('orderId',{}).get('S')!=order_id:
        raise ValueError(f'{service}: registra el procesamiento con eventId=orderId, service={service} y orderId en IDEMPOTENCY_TABLE.')


def _evaluate_runtime(working,env,limits,emit,ledger=None):
    config=Config(connect_timeout=2,read_timeout=5,retries={'max_attempts':1})
    def client(service):
        return boto3.client(service,region_name='us-east-1',endpoint_url='http://127.0.0.1:4566',
            aws_access_key_id='test',aws_secret_access_key='test',config=config)
    db=client('dynamodb');events=client('events');sqs=client('sqs')
    prefix='arena-'+uuid.uuid4().hex[:16]
    orders=prefix+'-orders';processed=prefix+'-processed';bus=prefix+'-bus'
    emit('fixtures','running')
    db.create_table(TableName=orders,KeySchema=[{'AttributeName':'orderId','KeyType':'HASH'}],
        AttributeDefinitions=[{'AttributeName':'orderId','AttributeType':'S'}],BillingMode='PAY_PER_REQUEST')
    db.create_table(TableName=processed,KeySchema=[{'AttributeName':'eventId','KeyType':'HASH'},{'AttributeName':'service','KeyType':'RANGE'}],
        AttributeDefinitions=[{'AttributeName':'eventId','AttributeType':'S'},{'AttributeName':'service','AttributeType':'S'}],BillingMode='PAY_PER_REQUEST')
    events.create_event_bus(Name=bus)
    rule=events.put_rule(Name='created',EventBusName=bus,EventPattern=json.dumps({'source':['com.cloudopsarena.orders'],'detail-type':['OrderCreated']}))
    queues={};targets=[];dlq=None
    if ledger:
        dlq=sqs.create_queue(QueueName=prefix+'-payments-dlq')['QueueUrl']
        dlq_arn=sqs.get_queue_attributes(QueueUrl=dlq,AttributeNames=['QueueArn'])['Attributes']['QueueArn']
    for service in ('payments','inventory'):
        attributes={'VisibilityTimeout':'1'} if ledger else {}
        if ledger and service=='payments':
            attributes['RedrivePolicy']=json.dumps({'deadLetterTargetArn':dlq_arn,'maxReceiveCount':2})
        url=sqs.create_queue(QueueName=prefix+'-'+service,Attributes=attributes)['QueueUrl']
        arn=sqs.get_queue_attributes(QueueUrl=url,AttributeNames=['QueueArn'])['Attributes']['QueueArn']
        sqs.set_queue_attributes(QueueUrl=url,Attributes={'Policy':json.dumps({'Version':'2012-10-17','Statement':[{
            'Effect':'Allow','Principal':{'Service':'events.amazonaws.com'},'Action':'sqs:SendMessage','Resource':arn,
            'Condition':{'ArnEquals':{'aws:SourceArn':rule['RuleArn']}}}]})})
        queues[service]=url;targets.append({'Id':service,'Arn':arn})
    setup=events.put_targets(Rule='created',EventBusName=bus,Targets=targets)
    if setup.get('FailedEntryCount',0):raise RuntimeError('Floci target setup failed')
    emit('fixtures','passed')
    learner_env={**env,'AWS_ENDPOINT_URL':'http://127.0.0.1:4566','AWS_REGION':'us-east-1',
        'ORDERS_TABLE':orders,'EVENT_BUS_NAME':bus,'IDEMPOTENCY_TABLE':processed,'FAIL_PAYMENTS':'false'}
    if ledger:learner_env['OPERATIONS_URL']=ledger.url
    cases=[]
    emit('orders','running')
    for encoded in (False,True):
        payload={'orderId':uuid.uuid4().hex,'customerId':'customer-'+uuid.uuid4().hex[:8],'total':str(Decimal(int(uuid.uuid4().hex[:4],16))/100+1)}
        body=json.dumps(payload)
        event={'body':base64.b64encode(body.encode()).decode() if encoded else body,'isBase64Encoded':encoded,'requestContext':{'http':{'method':'POST','path':'/orders'}}}
        response=invoke(working,'orders',event,learner_env,limits,operations=ledger)
        item=db.get_item(TableName=orders,Key={'orderId':{'S':payload['orderId']}},ConsistentRead=True).get('Item',{})
        check_order(response,item,payload);cases.append(payload)
    emit('orders','passed')
    emit('routing','running')
    batches={}
    for service,url in queues.items():
        messages=[];deadline=time.monotonic()+12
        while len(messages)<len(cases) and time.monotonic()<deadline:
            messages.extend(sqs.receive_message(QueueUrl=url,MaxNumberOfMessages=10,WaitTimeSeconds=1).get('Messages',[]))
        if len(messages)!=len(cases):raise ValueError(f'EventBridge debe entregar las dos órdenes a la cola de {service}.')
        remaining={case['orderId']:case for case in cases}
        for message in messages:
            try:envelope=json.loads(message['Body']);order_id=envelope['detail']['orderId']
            except (KeyError,TypeError,ValueError):raise ValueError('La cola debe recibir un evento OrderCreated válido.')
            if order_id not in remaining:raise ValueError('Las dos órdenes deben publicarse una vez y conservar su identificador.')
            check_envelope(envelope,remaining.pop(order_id))
        batches[service]=messages
    emit('routing','passed');emit('consumers','running')
    for service,messages in batches.items():
        event={'Records':[{'messageId':message['MessageId'],'receiptHandle':message['ReceiptHandle'],
            'body':message['Body'],'eventSource':'aws:sqs','awsRegion':'us-east-1'} for message in messages]}
        response=invoke(working,service,event,learner_env,limits,operations=ledger)
        for case in cases:
            item=db.get_item(TableName=processed,Key={'eventId':{'S':case['orderId']},'service':{'S':service}},ConsistentRead=True).get('Item',{})
            check_consumer(response,item,service,case['orderId'])
        for message in messages:sqs.delete_message(QueueUrl=queues[service],ReceiptHandle=message['ReceiptHandle'])
    emit('consumers','passed')
    if ledger:
        from resilience import exercise
        return exercise(working,learner_env,limits,emit,ledger,{'db':db,'sqs':sqs,'orders':orders,'processed':processed,'queues':queues,'dlq':dlq},cases,batches)
    return {'orders_checked':2,'consumers_checked':['payments','inventory'],'eventbridge_sqs_checked':True,
        'handler_invocation':'unprivileged-subprocess','lambda_service_invoked':False,'terraform_applied':False}


def evaluate_runtime(working,env,limits,emit,*,resilience=False):
    if resilience:
        from resilience import Operations
        with Operations() as ledger:return _evaluate_runtime(working,env,limits,emit,ledger)
    return _evaluate_runtime(working,env,limits,emit)
