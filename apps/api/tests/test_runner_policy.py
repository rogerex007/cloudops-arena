import importlib.util
from pathlib import Path
import pytest

PATH=Path(__file__).resolve().parents[3]/'apps/runner/policy.py'
spec=importlib.util.spec_from_file_location('runner_policy',PATH)
policy=importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def test_expected_plan_has_only_allowed_creations():
    changes=[]
    for kind,count in policy.ALLOWED_RESOURCES.items():
        changes.extend({'type':kind,'provider_name':'registry.terraform.io/hashicorp/aws','mode':'managed','change':{'actions':['create']}} for _ in range(count))
    configuration={'root_module':{'resources':[{'address':address,'expressions':{'references':list(targets)}} for address,targets in policy.EXPECTED_REFERENCES.items()]}}
    evidence=policy.inspect_plan({'resource_changes':changes,'configuration':configuration})
    assert evidence['total_resources']==sum(policy.ALLOWED_RESOURCES.values())
    assert evidence['applied'] is False
    assert evidence['routing_checked'] is True
    changes[0]['change']['actions']=['delete']
    with pytest.raises(ValueError): policy.inspect_plan({'resource_changes':changes})


@pytest.mark.parametrize('document',[
    {'module':[{'other':{'source':'https://untrusted'}}]},
    {'terraform':[{'backend':[{'s3':{}}]}]},
    {'terraform':[{'required_providers':[{'aws':{'source':'other/aws'}}]}]},
    {'data':[{'external':{'command':{}}}]},
    {'resource':[{'aws_instance':{'vm':{}}}]},
    {'resource':[{'aws_sqs_queue':{'queue':{'provisioner':[]}}}]},
])
def test_rejects_unreviewed_execution_surfaces(document):
    with pytest.raises(ValueError): policy.inspect_hcl([document])


def test_missing_resources_cannot_pass():
    with pytest.raises(ValueError): policy.inspect_plan({'resource_changes':[]})


def test_real_starter_hcl_passes_the_trusted_policy():
    import hcl2
    root=PATH.parents[2]/'game-packs/aws-event-driven/terraform'
    policy.inspect_hcl([hcl2.loads(path.read_text()) for path in root.glob('*.tf')])


def test_admin_iam_action_cannot_pass():
    with pytest.raises(ValueError):
        policy.inspect_iam('${jsonencode({"Statement": [{"Effect":"Allow","Action":["iam:*"],"Resource":"*"}]})}')
