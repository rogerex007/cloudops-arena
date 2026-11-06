from collections import Counter
import importlib.util
import json
from pathlib import Path
import urllib.request
import urllib.error

import pytest

PATH=Path(__file__).resolve().parents[3]/'apps/runner/resilience.py'
spec=importlib.util.spec_from_file_location('resilience_judge',PATH)
judge=importlib.util.module_from_spec(spec);spec.loader.exec_module(judge)


def test_operations_are_append_only_and_duplicate_calls_fail_grade():
    with judge.Operations() as ledger:
        ledger.activate('payments')
        def post():
            request=urllib.request.Request(ledger.url,data=json.dumps({'service':'payments','orderId':'test-order'}).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=3) as response:assert response.status==201
        post();ledger.require({('payments','test-order'):1})
        with pytest.raises(urllib.error.HTTPError):urllib.request.urlopen(ledger.url,timeout=3)
        assert ledger.snapshot()==Counter({('payments','test-order'):1})
        post()
        with pytest.raises(ValueError):ledger.require({('payments','test-order'):1})
        ledger.require({('payments','test-order'):2})


@pytest.mark.parametrize('response',[
    {}, {'batchItemFailures':'wrong'}, {'batchItemFailures':[{'itemIdentifier':'other'}]},
    {'batchItemFailures':[{'itemIdentifier':'a'},{'itemIdentifier':'a'}]},
    {'batchItemFailures':[{'itemIdentifier':None}]},True,
])
def test_invalid_partial_failure_evidence_rejected(response):
    with pytest.raises(ValueError):judge.failed_ids(response,[{'messageId':'a'}])


def test_exception_fails_entire_batch_and_partial_failure_only_one():
    records=[{'messageId':'good'},{'messageId':'bad'}]
    assert judge.failed_ids(None,records)=={'good','bad'}
    assert judge.failed_ids({'batchItemFailures':[{'itemIdentifier':'bad'}]},records)=={'bad'}
    assert judge.failed_ids({'batchItemFailures':[]},records)==set()


def test_final_close_rechecks_operations_after_last_snapshot():
    with pytest.raises(ValueError):
        with judge.Operations() as ledger:
            ledger.activate('payments')
            ledger.require({})
            request=urllib.request.Request(ledger.url,data=json.dumps({'service':'payments','orderId':'late'}).encode())
            with urllib.request.urlopen(request,timeout=3) as response:assert response.status==201


def test_handler_cannot_attribute_its_operation_to_another_service():
    with pytest.raises(ValueError):
        with judge.Operations() as ledger:
            ledger.activate('inventory')
            request=urllib.request.Request(ledger.url,data=json.dumps({'service':'payments','orderId':'forged'}).encode())
            with pytest.raises(urllib.error.HTTPError):urllib.request.urlopen(request,timeout=3)
            assert ledger.snapshot()==Counter()
            ledger.require({})
