import importlib.util
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[3]/'apps/runner'
spec=importlib.util.spec_from_file_location('policy',ROOT/'policy.py')
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
sys.modules.setdefault('policy',policy)
spec=importlib.util.spec_from_file_location('runtime_judge',ROOT/'runtime.py')
judge=importlib.util.module_from_spec(spec);spec.loader.exec_module(judge)

PAYLOAD={'orderId':'random-order','customerId':'random-customer','total':'123.45'}
ITEM={'orderId':{'S':'random-order'},'customerId':{'S':'random-customer'},'total':{'N':'123.45'},
    'status':{'S':'CREATED'},'createdAt':{'S':'2026-11-04'}}


def test_success_response_without_persistence_cannot_pass():
    response={'statusCode':201,'body':{'orderId':PAYLOAD['orderId'],'status':'CREATED'}}
    judge.check_order(response,ITEM,PAYLOAD)
    with pytest.raises(ValueError):judge.check_order(response,{},PAYLOAD)
    with pytest.raises(ValueError):judge.check_order(response,{**ITEM,'total':{'N':'1'}},PAYLOAD)


def test_event_must_preserve_order_and_both_routing_fields():
    event={'source':'com.cloudopsarena.orders','detail-type':'OrderCreated','detail':PAYLOAD}
    judge.check_envelope(event,PAYLOAD)
    with pytest.raises(ValueError):judge.check_envelope({**event,'detail-type':'Different'},PAYLOAD)
    with pytest.raises(ValueError):judge.check_envelope({**event,'detail':{**PAYLOAD,'orderId':'other'}},PAYLOAD)


def test_consumer_noop_or_wrong_service_cannot_pass():
    item={'eventId':{'S':PAYLOAD['orderId']},'service':{'S':'payments'},'orderId':{'S':PAYLOAD['orderId']}}
    judge.check_consumer({'batchItemFailures':[]},item,'payments',PAYLOAD['orderId'])
    for response,stored,service in [({'batchItemFailures':[]},{},'payments'),({'batchItemFailures':[]},item,'inventory'),({},item,'payments')]:
        with pytest.raises(ValueError):judge.check_consumer(response,stored,service,PAYLOAD['orderId'])


def test_validator_file_sets_are_distinct():
    assert len(policy.VALIDATORS[policy.RUNTIME_VALIDATOR])==3
    assert len(policy.VALIDATORS[policy.VALIDATOR])==7


def test_malformed_numbers_fail_as_validation_errors():
    with pytest.raises(ValueError):judge.check_envelope({'source':'com.cloudopsarena.orders','detail-type':'OrderCreated','detail':{**PAYLOAD,'total':'not-a-number'}},PAYLOAD)
