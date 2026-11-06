"""Trusted policy for the first Terraform plan validator. No apply is permitted."""
import json
import re

VALIDATOR = "aws-event-driven-plan-v1"
PREFIX = "game-packs/aws-event-driven/"
FILES = [PREFIX + "terraform/" + name for name in ("main.tf", "variables.tf", "versions.tf", "outputs.tf")]
FILES += [PREFIX + f"functions/{service}/handler.py" for service in ("orders", "payments", "inventory")]
RUNTIME_VALIDATOR = "aws-event-driven-runtime-v1"
RUNTIME_FILES = [PREFIX + f"functions/{service}/handler.py" for service in ("orders", "payments", "inventory")]
RESILIENCE_VALIDATOR = "aws-event-driven-resilience-v1"
VALIDATORS = {VALIDATOR: FILES, RUNTIME_VALIDATOR: RUNTIME_FILES, RESILIENCE_VALIDATOR: RUNTIME_FILES}
ALLOWED_RESOURCES = {
    "aws_dynamodb_table": 2, "aws_sqs_queue": 4, "aws_cloudwatch_event_bus": 1,
    "aws_cloudwatch_event_rule": 1, "aws_cloudwatch_event_target": 2,
    "aws_sqs_queue_policy": 2, "aws_iam_role": 3, "aws_iam_role_policy": 3,
    "aws_lambda_function": 3, "aws_lambda_event_source_mapping": 2,
    "aws_apigatewayv2_api": 1, "aws_apigatewayv2_integration": 1,
    "aws_apigatewayv2_route": 1, "aws_apigatewayv2_stage": 1, "aws_lambda_permission": 1,
}
EXPECTED_REFERENCES = {
    'aws_lambda_function.orders': {'aws_iam_role.orders','aws_dynamodb_table.orders','aws_cloudwatch_event_bus.orders','data.archive_file.orders'},
    'aws_lambda_function.payments': {'aws_iam_role.payments','aws_dynamodb_table.idempotency','data.archive_file.payments'},
    'aws_lambda_function.inventory': {'aws_iam_role.inventory','aws_dynamodb_table.idempotency','data.archive_file.inventory'},
    'aws_lambda_event_source_mapping.payments': {'aws_sqs_queue.payments','aws_lambda_function.payments'},
    'aws_lambda_event_source_mapping.inventory': {'aws_sqs_queue.inventory','aws_lambda_function.inventory'},
    'aws_cloudwatch_event_target.payments': {'aws_cloudwatch_event_rule.order_created','aws_sqs_queue.payments'},
    'aws_cloudwatch_event_target.inventory': {'aws_cloudwatch_event_rule.order_created','aws_sqs_queue.inventory'},
    'aws_sqs_queue.payments': {'aws_sqs_queue.payments_dlq'},
    'aws_sqs_queue.inventory': {'aws_sqs_queue.inventory_dlq'},
    'aws_apigatewayv2_integration.orders': {'aws_lambda_function.orders','aws_apigatewayv2_api.orders'},
    'aws_apigatewayv2_route.create_order': {'aws_apigatewayv2_integration.orders'},
}
ALLOWED_ACTIONS = {'logs:CreateLogGroup','logs:CreateLogStream','logs:PutLogEvents','dynamodb:PutItem',
                   'events:PutEvents','sqs:ReceiveMessage','sqs:DeleteMessage','sqs:GetQueueAttributes','sqs:ChangeMessageVisibility'}


def inspect_iam(expression):
    if not isinstance(expression,str) or not expression.startswith('${jsonencode({') or not expression.endswith(')}'):
        raise ValueError('La política IAM debe usar el objeto jsonencode revisado del laboratorio.')
    raw=expression.removeprefix('${jsonencode(').removesuffix(')}')
    # References may occur in Resource values; they are never evaluated here.
    policy=json.loads(re.sub(r'\$\{[^}]*\}', 'REFERENCE', raw))
    statements=policy.get('Statement',[])
    if not isinstance(statements,list) or not statements:
        raise ValueError('La política IAM no contiene permisos revisables.')
    for statement in statements:
        if set(statement)-{'Sid','Effect','Action','Resource','Condition'} or statement.get('Effect')!='Allow':
            raise ValueError('La política IAM contiene permisos no autorizados.')
        actions=statement.get('Action',[])
        actions=[actions] if isinstance(actions,str) else actions
        if not actions or not set(actions)<=ALLOWED_ACTIONS:
            raise ValueError('La política IAM contiene acciones fuera del laboratorio.')


def inspect_hcl(documents):
    """Reject unreviewed providers, modules, executable data and provisioners."""
    for document in documents:
        if set(document) - {"terraform", "provider", "variable", "locals", "resource", "data", "output", "__is_block__"}:
            raise ValueError("La configuración contiene bloques no autorizados.")
        for block in document.get("terraform", []):
            if set(block) - {"required_version", "required_providers", "__is_block__"}:
                raise ValueError("No se permiten backends, cloud ni módulos externos.")
            for providers in block.get("required_providers", []):
                for name, config in providers.items():
                    if name == "__is_block__":
                        continue
                    if name not in {"aws", "archive"} or config.get("source") != f"hashicorp/{name}":
                        raise ValueError("Solo se permiten los proveedores oficiales AWS y Archive.")
        for providers in document.get("provider", []):
            if set(providers) - {"aws", "archive", "__is_block__"}:
                raise ValueError("Proveedor no autorizado.")
        for group in document.get("resource", []):
            for resource_type, instances in group.items():
                if resource_type == "__is_block__":
                    continue
                if resource_type not in ALLOWED_RESOURCES:
                    raise ValueError(f"Recurso no autorizado: {resource_type}")
                for instance in instances.values():
                    if "provisioner" in instance or "connection" in instance:
                        raise ValueError("No se permiten provisioners ni conexiones remotas.")
                    if resource_type == 'aws_iam_role_policy':
                        inspect_iam(instance.get('policy'))
        for group in document.get("data", []):
            if set(group) - {"archive_file", "__is_block__"}:
                raise ValueError("Solo se permite el origen de datos Archive.")


def inspect_plan(plan):
    counts = {}
    for resource in plan.get("resource_changes", []):
        kind = resource.get("type")
        if resource.get("mode") == "data":
            if kind != "archive_file":
                raise ValueError("Origen de datos no autorizado en el plan.")
            continue
        if kind not in ALLOWED_RESOURCES or resource.get("provider_name") != "registry.terraform.io/hashicorp/aws":
            raise ValueError("El plan contiene recursos o proveedores no autorizados.")
        if resource.get("change", {}).get("actions") != ["create"]:
            raise ValueError("La evaluación solo admite un plan de creación desde cero.")
        counts[kind] = counts.get(kind, 0) + 1
    if counts != ALLOWED_RESOURCES:
        raise ValueError("El plan no contiene los recursos esperados para órdenes, pagos e inventario.")
    def references(value):
        found=[]
        if isinstance(value,dict):
            found.extend(value.get('references',[]))
            for child in value.values(): found.extend(references(child))
        elif isinstance(value,list):
            for child in value: found.extend(references(child))
        return found
    configuration={entry['address']:entry for entry in plan.get('configuration',{}).get('root_module',{}).get('resources',[])}
    for address,expected in EXPECTED_REFERENCES.items():
        found=references(configuration.get(address,{}))
        if not all(any(ref==target or ref.startswith(target+'.') or ref.startswith(target+'[') for ref in found) for target in expected):
            raise ValueError(f'Falta una conexión esperada del flujo en {address}.')
    if not plan.get("applyable", True) or plan.get("errored", False):
        raise ValueError("Terraform no generó un plan aplicable.")
    return {"resource_counts": counts, "total_resources": sum(counts.values()), "routing_checked": True, "applied": False}
