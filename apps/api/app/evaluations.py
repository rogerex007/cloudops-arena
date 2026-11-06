"""Persist requests; execution belongs to a separate trusted worker."""
import hashlib
import json
import time
from datetime import datetime, timezone

from boto3.dynamodb.types import TypeSerializer
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .config import settings
from .db import dynamodb_client, table_resource
from .gamepack import get_mission, load_pack
from .security import require_participant
from .mission_clock import require_time,deadline_condition

router = APIRouter()
QUEUE_KEY={"PK":"CONTROL#EVALUATIONS","SK":"QUEUE"}
PUBLIC_FIELDS = (
    "evaluation_id", "mission_id", "repo_name", "commit_sha", "status",
    "created_at", "participant_id", "game_pack", "pack_version",
    "message", "result_code", "missing_files", "updated_at", "finished_at", "attempt",
    "evidence", "points_awarded", "validator_version",
    "queued_at", "queue_position", "queue_total", "progress", "source", "actions_run_id", "actions_url",
    "operation",
)


class EvaluationRequest(BaseModel):
    commit_sha: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    retry: bool = False


def queued_order(item):
    return (item.get('queued_at',item.get('updated_at',item.get('created_at',''))),item.get('PK',''),item.get('SK',''))


def queue_summary(rows):
    pending=sorted((row for row in rows if row.get('type')=='evaluation' and row.get('status')=='pending'),key=queued_order)
    return {'waiting':len(pending),'running':sum(row.get('type')=='evaluation' and row.get('status') in {'preparing','running'} for row in rows),
        'execution_limit':settings.evaluation_concurrency,'admission_limit':settings.evaluation_queue_limit,
        'positions':{row['evaluation_id']:index+1 for index,row in enumerate(pending)}}


def public_evaluation(item: dict, queue: dict | None = None) -> dict:
    result={key: item[key] for key in PUBLIC_FIELDS if key in item}
    if queue and item.get('status')=='pending':
        result.update(queue_position=queue['positions'].get(item['evaluation_id']),queue_total=queue['waiting'])
    return result


@router.post("/api/v1/participant/missions/{mission_id}/evaluations")
def request_evaluation(mission_id: str, body: EvaluationRequest, principal: dict = Depends(require_participant)):
    raise HTTPException(410, "Las entregas se solicitan únicamente desde GitHub Actions con el workflow de la misión.")


def register_evaluation(mission_id: str, body: EvaluationRequest, principal: dict, provenance: dict | None = None):
    table = table_resource()
    pk = f"EVENT#{principal['event_id']}"

    def read(sk):
        return table.get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True).get("Item")

    event = read("META")
    if not event or event.get("status") != "open":
        raise HTTPException(403, "El evento no está aceptando evaluaciones.")
    if event.get("active_mission_id") != mission_id:
        raise HTTPException(409, "El instructor debe activar esta misión antes de solicitar una evaluación.")
    require_time(event)
    pack_id = event.get("game_pack", "aws-event-driven")
    pack = load_pack(pack_id)
    mission = get_mission(pack, mission_id)
    if not mission or not mission.get("workflow") or mission.get("type") == "quiz":
        raise HTTPException(422, "Esta misión no admite evaluaciones de repositorio.")
    team_id = principal["team_id"]
    participant = read(f"USER#{principal['sub']}")
    team = read(f"TEAM#{team_id}")
    if not participant or participant.get("team_id") != team_id or not team:
        raise HTTPException(403, "Tu registro en este evento ya no está disponible.")
    if not team.get("repo_name"):
        raise HTTPException(409, "Vincula tu repositorio de GitHub antes de solicitar la evaluación.")
    deploying=bool(provenance and provenance.get('operation')=='deploy')
    if read(f"SUB#{team_id}#{mission_id}") and not deploying:
        raise HTTPException(409, "Esta misión ya está completada.")

    commit_sha = body.commit_sha.lower()
    version = str(pack.get("version", ""))
    identity = [team_id, mission_id, pack_id, version, team["repo_name"].casefold(), commit_sha]
    if provenance and provenance.get('operation'):identity.append(provenance['operation'])
    evaluation_id = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:32]
    evaluation_sk = f"EVAL#{evaluation_id}"
    existing = read(evaluation_sk)
    retrying = bool(existing and body.retry and existing.get("status") in {"failed", "blocked"})
    if existing and not retrying:
        return {"evaluation": public_evaluation(existing), "already_requested": True}
    if retrying and int(existing.get("attempt", 1)) >= 5:
        raise HTTPException(429, "Esta entrega alcanzó el límite de cinco intentos. Consulta con el instructor.")

    item = {
        "PK": pk, "SK": evaluation_sk, "type": "evaluation",
        "evaluation_id": evaluation_id, "event_id": principal["event_id"],
        "team_id": team_id, "participant_id": principal["sub"],
        "mission_id": mission_id, "repo_name": team["repo_name"],
        "commit_sha": commit_sha, "game_pack": pack_id, "pack_version": version,
        "workflow": mission["workflow"], "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repository_verified": False,
        "queue_accounted": True,
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "attempt": int(existing.get("attempt", 1)) + 1 if retrying else 1,
        "message": "Entrega registrada. Esperando la revisión automática del repositorio.",
        "source": "portal",
    }
    if provenance:
        item.update(provenance)
    item['progress']=[{'stage':'received','status':'passed','message':'Solicitud recibida','timestamp':item.get('updated_at',item['created_at'])}]
    if retrying:
        item["created_at"] = existing["created_at"]
        item["updated_at"] = datetime.now(timezone.utc).isoformat()
    client = dynamodb_client()

    def condition(sk, expression, values):
        return {"ConditionCheck": {
            "TableName": settings.dynamodb_table_name,
            "Key": {"PK": {"S": pk}, "SK": {"S": sk}},
            "ConditionExpression": expression,
            "ExpressionAttributeValues": {k: TypeSerializer().serialize(v) for k, v in values.items()},
        }}

    def put(value):
        return {"Put": {
            "TableName": settings.dynamodb_table_name,
            "Item": {k: TypeSerializer().serialize(v) for k, v in value.items()},
            "ConditionExpression": "attribute_not_exists(PK)",
        }}

    event_check = condition(
        "META", "#state = :open AND active_mission_id = :mission AND (game_pack = :pack OR attribute_not_exists(game_pack)) AND "+deadline_condition(),
        {":open": "open", ":mission": mission_id, ":pack": pack_id,':clock_now':int(time.time())},
    )
    event_check["ConditionCheck"]["ExpressionAttributeNames"] = {"#state": "status"}
    request_put = put(item)
    if retrying:
        request_put["Put"].update({
            "ConditionExpression": "#state = :previous AND (attribute_not_exists(attempt) OR attempt = :attempt)",
            "ExpressionAttributeNames": {"#state": "status"},
            "ExpressionAttributeValues": {
                ":previous": {"S": existing["status"]},
                ":attempt": {"N": str(existing.get("attempt", 1))},
            },
        })
    try:
        client.transact_write_items(TransactItems=[
            event_check,
            condition(f"TEAM#{team_id}", "repo_name = :repo", {":repo": team["repo_name"]}),
            condition(f"USER#{principal['sub']}", "team_id = :team", {":team": team_id}),
            *([] if deploying else [{"ConditionCheck": {
                "TableName": settings.dynamodb_table_name,
                "Key": {"PK": {"S": pk}, "SK": {"S": f"SUB#{team_id}#{mission_id}"}},
                "ConditionExpression": "attribute_not_exists(PK)",
            }}]),
            request_put,
            put({"PK": pk, "SK": f"EVALLOCK#{team_id}", "type": "evaluation-lock",
                 "evaluation_id": evaluation_id, "team_id": team_id, "created_at": item["created_at"]}),
            {'Update':{'TableName':settings.dynamodb_table_name,
                'Key':{key:{'S':value} for key,value in QUEUE_KEY.items()},
                'UpdateExpression':'SET outstanding = if_not_exists(outstanding, :zero) + :one',
                'ConditionExpression':'attribute_not_exists(outstanding) OR outstanding < :limit',
                'ExpressionAttributeValues':{':zero':{'N':'0'},':one':{'N':'1'},':limit':{'N':str(settings.evaluation_queue_limit)}}}},
        ])
    except client.exceptions.TransactionCanceledException:
        existing = read(evaluation_sk)
        if existing and (not retrying or existing.get("status") in {"pending", "preparing", "running"}):
            return {"evaluation": public_evaluation(existing), "already_requested": True}
        counter=table.get_item(Key=QUEUE_KEY,ConsistentRead=True).get('Item',{})
        if int(counter.get('outstanding',0))>=settings.evaluation_queue_limit:
            raise HTTPException(429,"La cola está completa. Espera a que termine una evaluación y vuelve a ejecutar el workflow.")
        raise HTTPException(409, "Ya tienes una evaluación pendiente o cambió el estado del evento. Actualiza el portal.")
    return {"evaluation": public_evaluation(item), "already_requested": False}
