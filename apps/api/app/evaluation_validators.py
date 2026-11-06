"""Reviewed executor contracts. A different mission cannot reuse another grade."""
VALIDATORS={
    'aws-event-driven-deploy-v1':('mission-02','terraform_deployment_passed'),
    'aws-event-driven-plan-v1':('mission-02','terraform_plan_passed'),
    'aws-event-driven-runtime-v1':('mission-03','runtime_flow_passed'),
    'aws-event-driven-resilience-v1':('mission-04','resilience_flow_passed'),
}


def accepts(mission_id,validator,result_code=None):
    expected=VALIDATORS.get(validator)
    return bool(expected and expected[0]==mission_id and (result_code is None or expected[1]==result_code))
