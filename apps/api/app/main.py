import hashlib
import hmac
import json
import logging
import re
import secrets
import time
import uuid
from typing import Literal
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit

from boto3.dynamodb.types import TypeSerializer
from boto3.dynamodb.conditions import Attr
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import settings
from .db import dynamodb_client, get_item, query_partition, scan_items, table_resource
from .gamepack import get_mission, load_pack, public_missions
from .security import create_token, require_admin, require_participant
from .providers import FlociProvider, AwsSandboxProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cloudops-arena")
app = FastAPI(title=settings.app_name, version="0.1.1", description="Reusable, Game Pack-driven technology GameDay platform")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Hub-Signature-256", "X-GitHub-Event", "X-GitHub-Delivery"],
)


class JoinRequest(BaseModel):
    event_code: str = Field(min_length=4, max_length=64)
    display_name: str = Field(min_length=2, max_length=60)
    invite_code: str | None = Field(default=None, min_length=6, max_length=80)
    # Backward compatibility with the first MVP form.
    team_code: str | None = Field(default=None, min_length=4, max_length=80)


class CreateTeamRequest(BaseModel):
    event_code: str = Field(min_length=4, max_length=64)
    display_name: str = Field(min_length=2, max_length=60)
    team_name: str = Field(min_length=2, max_length=60)


class AdminLogin(BaseModel):
    username: str
    password: str


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=120)


class EventStatusRequest(BaseModel):
    status: str


class ActivateMissionRequest(BaseModel):
    mission_id: str


class EventCreateRequest(BaseModel):
    title: str = Field(min_length=4, max_length=100)
    game_pack: str = Field(default="aws-event-driven", min_length=3, max_length=80)
    participation_mode: Literal["individual", "team"] = "team"
    team_size: int = Field(default=5, ge=2, le=6)
    max_participants: int = Field(default=100, ge=1, le=500)


class GitHubRepoRequest(BaseModel):
    repo_name: str = Field(min_length=3, max_length=120)
    repo_url: str = Field(min_length=10, max_length=250)


class ParticipantGitHubRepoRequest(BaseModel):
    repo_url: str = Field(min_length=19, max_length=250)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def event_by_code(event_code: str) -> dict | None:
    # Dedicated lookup item avoids scanning every participant/team on the hot join path.
    lookup = get_item(f"EVENTCODE#{event_code.strip().upper()}", "EVENT")
    if lookup:
        return get_item(f"EVENT#{lookup['event_id']}", "META")
    # Backward-compatible fallback for older seeded demo data.
    events = scan_items(Attr("type").eq("event"))
    for event in events:
        if hmac.compare_digest(str(event.get("event_code", "")).upper(), event_code.strip().upper()):
            return event
    return None


def hash_invite_code(invite_code: str) -> str:
    return hashlib.sha256(invite_code.strip().upper().encode("utf-8")).hexdigest()


def team_by_code(event_id: str, team_code: str) -> dict | None:
    candidate = hash_invite_code(team_code)
    for team in query_partition(f"EVENT#{event_id}"):
        if team.get("type") != "team":
            continue
        stored_hash = str(team.get("invite_code_hash", ""))
        # Read legacy demo codes while older local databases are being migrated.
        legacy_code = str(team.get("join_code", "")).upper()
        if (stored_hash and hmac.compare_digest(stored_hash, candidate)) or (legacy_code and hmac.compare_digest(legacy_code, team_code.strip().upper())):
            return team
    return None


def participant_session(event: dict, team: dict, participant: dict, *, is_team_leader: bool = False) -> dict:
    token = create_token({
        "sub": participant["participant_id"], "role": "participant",
        "event_id": event["event_id"], "team_id": team["team_id"],
        "name": participant["display_name"],
    })
    return {
        "access_token": token,
        "token_type": "bearer",
        "participant": {
            "id": participant["participant_id"], "name": participant["display_name"],
            "team_id": team["team_id"], "team_name": team["name"],
            "is_team_leader": is_team_leader,
            "participation_mode": event.get("participation_mode", "team"),
        },
    }


def participant_item(event_id: str, participant_id: str, display_name: str, team_id: str, created_at: str) -> dict:
    return {
        "PK": f"EVENT#{event_id}", "SK": f"USER#{participant_id}",
        "type": "participant", "participant_id": participant_id,
        "display_name": display_name, "team_id": team_id,
        "event_id": event_id, "created_at": created_at,
    }


def transaction_condition_failed(exc: Exception, operation_index: int) -> bool:
    reasons = getattr(exc, "response", {}).get("CancellationReasons", [])
    return (
        len(reasons) > operation_index
        and reasons[operation_index].get("Code") == "ConditionalCheckFailed"
    )


def counter_reached(table, event_id: str, counter: str, limit: int, sort_key: str = "META") -> bool:
    response = table.get_item(
        Key={"PK": f"EVENT#{event_id}", "SK": sort_key},
        ConsistentRead=True,
    )
    return int(response.get("Item", {}).get(counter, 0)) >= limit


def log_registration_cancellation(exc: Exception, event_id: str) -> None:
    response = getattr(exc, "response", {})
    error = response.get("Error", {})
    error_code = error.get("Code", "unknown")
    error_message = error.get("Message", "")
    reasons = [
        {
            "code": reason.get("Code", "unknown"),
            "message": reason.get("Message", ""),
        }
        for reason in response.get("CancellationReasons", [])
    ]
    request_id = response.get("ResponseMetadata", {}).get("RequestId", "unknown")
    logger.warning(
        "Registration transaction canceled for event %s: request_id=%s error=%s message=%s reasons=%s",
        event_id,
        request_id,
        error_code,
        error_message,
        reasons,
    )


def registration_cancellation_message(exc: Exception) -> str:
    response = getattr(exc, "response", {})
    error_code = response.get("Error", {}).get("Code", "unknown")
    reasons = [
        (index, reason)
        for index, reason in enumerate(response.get("CancellationReasons", []), start=1)
        if reason.get("Code") not in (None, "None")
    ]
    request_id = response.get("ResponseMetadata", {}).get("RequestId")

    explanations = {
        "TransactionConflict": "hay otro registro modificando el evento al mismo tiempo",
        "ProvisionedThroughputExceeded": "se alcanzó temporalmente el límite de solicitudes de la base de datos",
        "ThrottlingError": "la base de datos está recibiendo demasiadas solicitudes",
        "ValidationError": "la base de datos rechazó los datos del registro",
        "ItemCollectionSizeLimitExceeded": "se alcanzó el límite de almacenamiento del evento",
    }
    explanation = next(
        (explanations[reason.get("Code")] for _, reason in reasons if reason.get("Code") in explanations),
        None,
    )
    reason_detail = next(
        (
            f"Operación {index}: {reason['Message']}"
            for index, reason in reasons
            if reason.get("Code") == "ValidationError" and reason.get("Message")
        ),
        None,
    )
    if explanation:
        message = f"No se pudo completar el registro porque {explanation}. Inténtalo de nuevo."
    elif reasons:
        message = (
            "No se pudo completar el registro "
            f"(operación {reasons[0][0]}, motivo técnico: {reasons[0][1].get('Code', 'unknown')})."
        )
    else:
        message = f"No se pudo completar el registro (servicio: {error_code}; motivo no informado)."
    if reason_detail:
        message += f" Detalle: {reason_detail}."
    if request_id:
        message += f" Referencia: {request_id}."
    return message


def transact_registration(client, operations: list[dict]) -> None:
    transaction = client.transact_write_items
    for attempt in range(3):
        try:
            transaction(TransactItems=operations)
            return
        except client.exceptions.TransactionCanceledException as exc:
            reason_codes = {
                reason.get("Code")
                for reason in getattr(exc, "response", {}).get("CancellationReasons", [])
            }
            if not reason_codes.intersection({
                "TransactionConflict",
                "ProvisionedThroughputExceeded",
                "ThrottlingError",
            }) or attempt == 2:
                raise
            time.sleep(0.05 * (2 ** attempt))


def award_mission(event_id: str, team_id: str, mission: dict, source: str, run_id: str | None = None) -> bool:
    client = dynamodb_client()
    points = int(mission.get("workflow_points", mission.get("points", 0)))
    submission_id = f"{team_id}#{mission['id']}"
    item = {
        "PK": f"EVENT#{event_id}",
        "SK": f"SUB#{submission_id}",
        "type": "submission",
        "team_id": team_id,
        "mission_id": mission["id"],
        "status": "passed",
        "points": points,
        "source": source,
        "run_id": run_id or "",
        "created_at": now_iso(),
    }
    try:
        client.transact_write_items(TransactItems=[
            {
                "Put": {
                    "TableName": settings.dynamodb_table_name,
                    "Item": {k: TypeSerializer().serialize(v) for k, v in item.items()},
                    "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
                }
            },
            {
                "Update": {
                    "TableName": settings.dynamodb_table_name,
                    "Key": {"PK": {"S": f"EVENT#{event_id}"}, "SK": {"S": f"TEAM#{team_id}"}},
                    "UpdateExpression": "SET score = if_not_exists(score, :zero) + :points, updated_at = :now",
                    "ExpressionAttributeValues": {":zero": {"N": "0"}, ":points": {"N": str(points)}, ":now": {"S": now_iso()}},
                    "ConditionExpression": "attribute_exists(PK)",
                }
            },
        ])
        return True
    except client.exceptions.TransactionCanceledException:
        return False


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name, "environment": settings.environment}


@app.get("/api/v1/public/event")
def public_event():
    events = scan_items(Attr("type").eq("event"))
    if not events:
        raise HTTPException(404, "No event has been seeded. Run scripts/seed_demo.py.")
    event = sorted(events, key=lambda x: x.get("created_at", ""), reverse=True)[0]
    return {k: event.get(k) for k in ("event_id", "title", "status", "game_pack", "active_mission_id", "starts_at", "participation_mode", "team_size", "max_participants")}


@app.get("/api/v1/public/events/{event_code}")
def public_event_by_code(event_code: str):
    event = event_by_code(event_code)
    if not event:
        raise HTTPException(404, "No encontramos un evento con ese código. Verifica que esté escrito correctamente.")
    if event.get("status") != "open":
        raise HTTPException(403, "Este evento no está aceptando registros en este momento.")
    return {
        "event_id": event["event_id"],
        "event_code": event.get("event_code"),
        "title": event.get("title"),
        "status": event.get("status"),
        "participation_mode": event.get("participation_mode", "team"),
        "team_size": int(event.get("team_size", 5)),
        "max_participants": int(event.get("max_participants", 500)),
        "game_pack": event.get("game_pack"),
    }


@app.post("/api/v1/auth/join")
def participant_join(body: JoinRequest):
    event = event_by_code(body.event_code.strip().upper())
    if not event:
        raise HTTPException(404, "No encontramos el evento. Revisa el código e inténtalo de nuevo.")
    if event.get("status") != "open":
        raise HTTPException(403, "Este evento no está aceptando participantes en este momento.")

    display_name = body.display_name.strip()
    mode = event.get("participation_mode", "team")
    event_id = event["event_id"]
    participant_id = str(uuid.uuid4())
    created = now_iso()
    table = table_resource()
    client = dynamodb_client()

    if mode == "individual":
        team_id = f"individual-{participant_id[:12]}"
        team = {
            "PK": f"EVENT#{event_id}", "SK": f"TEAM#{team_id}", "type": "team",
            "event_id": event_id, "team_id": team_id, "name": display_name,
            "max_members": 1, "member_count": 1, "score": 0,
            "repo_name": "", "repo_url": "", "created_at": created,
        }
        participant = participant_item(event_id, participant_id, display_name, team_id, created)
        try:
            transact_registration(client, [
                {"Update": {
                    "TableName": settings.dynamodb_table_name,
                    "Key": {"PK": {"S": f"EVENT#{event_id}"}, "SK": {"S": "META"}},
                    "UpdateExpression": "SET participant_count = if_not_exists(participant_count, :zero) + :one, team_count = if_not_exists(team_count, :zero) + :one",
                    "ConditionExpression": "attribute_not_exists(participant_count) OR participant_count < :max_participants",
                    "ExpressionAttributeValues": {":zero": {"N": "0"}, ":one": {"N": "1"}, ":max_participants": {"N": str(int(event.get("max_participants", 500))) }},
                }},
                {"Put": {"TableName": settings.dynamodb_table_name, "Item": {k: TypeSerializer().serialize(v) for k, v in team.items()}, "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)"}},
                {"Put": {"TableName": settings.dynamodb_table_name, "Item": {k: TypeSerializer().serialize(v) for k, v in participant.items()}, "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)"}},
            ])
        except client.exceptions.TransactionCanceledException as exc:
            if transaction_condition_failed(exc, 0) or counter_reached(
                table, event_id, "participant_count", int(event.get("max_participants", 500))
            ):
                raise HTTPException(409, "El evento alcanzó su capacidad máxima. Consulta con el instructor.")
            log_registration_cancellation(exc, event_id)
            raise HTTPException(409, registration_cancellation_message(exc))
        return participant_session(event, team, participant)

    invite_code = (body.invite_code or body.team_code or "").strip()
    if not invite_code:
        raise HTTPException(422, "Necesitas el código de invitación de tu equipo. Pídeselo a quien lo creó.")
    team = team_by_code(event_id, invite_code)
    if not team:
        raise HTTPException(404, "El código de invitación no es válido para este evento.")
    participant = participant_item(event_id, participant_id, display_name, team["team_id"], created)
    try:
        transact_registration(client, [
            {"Update": {
                "TableName": settings.dynamodb_table_name,
                "Key": {"PK": {"S": f"EVENT#{event_id}"}, "SK": {"S": "META"}},
                "UpdateExpression": "SET participant_count = if_not_exists(participant_count, :zero) + :one",
                "ConditionExpression": "attribute_not_exists(participant_count) OR participant_count < :max_participants",
                "ExpressionAttributeValues": {":zero": {"N": "0"}, ":one": {"N": "1"}, ":max_participants": {"N": str(int(event.get("max_participants", 500))) }},
            }},
            {"Update": {
                "TableName": settings.dynamodb_table_name,
                "Key": {"PK": {"S": f"EVENT#{event_id}"}, "SK": {"S": f"TEAM#{team['team_id']}"}},
                "UpdateExpression": "SET member_count = if_not_exists(member_count, :zero) + :one",
                "ConditionExpression": "(attribute_not_exists(member_count) OR member_count < :max_members)",
                "ExpressionAttributeValues": {":zero": {"N": "0"}, ":one": {"N": "1"}, ":max_members": {"N": str(int(team.get("max_members", event.get("team_size", 5)))) }},
            }},
            {"Put": {"TableName": settings.dynamodb_table_name, "Item": {k: TypeSerializer().serialize(v) for k, v in participant.items()}, "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)"}},
        ])
    except client.exceptions.TransactionCanceledException as exc:
        if transaction_condition_failed(exc, 0) or counter_reached(
            table, event_id, "participant_count", int(event.get("max_participants", 500))
        ):
            raise HTTPException(409, "El evento alcanzó su capacidad máxima. Consulta con el instructor.")
        if transaction_condition_failed(exc, 1) or counter_reached(
            table,
            event_id,
            "member_count",
            int(team.get("max_members", event.get("team_size", 5))),
            f"TEAM#{team['team_id']}",
        ):
            raise HTTPException(409, "El equipo está completo. Consulta con quien lo creó.")
        log_registration_cancellation(exc, event_id)
        raise HTTPException(409, registration_cancellation_message(exc))
    return participant_session(event, team, participant)


@app.post("/api/v1/auth/create-team")
def participant_create_team(body: CreateTeamRequest):
    event = event_by_code(body.event_code.strip().upper())
    if not event:
        raise HTTPException(404, "No encontramos el evento. Revisa el código e inténtalo de nuevo.")
    if event.get("status") != "open":
        raise HTTPException(403, "Este evento no está aceptando nuevos equipos.")
    if event.get("participation_mode", "team") != "team":
        raise HTTPException(409, "Este evento está configurado para participación individual.")

    team_name = body.team_name.strip()
    display_name = body.display_name.strip()
    event_id = event["event_id"]
    team_id = f"team-{uuid.uuid4().hex[:12]}"
    participant_id = str(uuid.uuid4())
    invite_code = "ARENA-" + secrets.token_urlsafe(9).replace("-", "A").replace("_", "B").upper()
    created = now_iso()
    team = {
        "PK": f"EVENT#{event_id}", "SK": f"TEAM#{team_id}", "type": "team",
        "event_id": event_id, "team_id": team_id, "name": team_name,
        "invite_code_hash": hash_invite_code(invite_code),
        "max_members": int(event.get("team_size", 5)), "member_count": 1, "score": 0,
        "leader_participant_id": participant_id, "repo_name": "", "repo_url": "", "created_at": created,
    }
    participant = participant_item(event_id, participant_id, display_name, team_id, created)
    table = table_resource()
    client = dynamodb_client()
    try:
        transact_registration(client, [
            {"Update": {
                "TableName": settings.dynamodb_table_name,
                "Key": {"PK": {"S": f"EVENT#{event_id}"}, "SK": {"S": "META"}},
                "UpdateExpression": "SET participant_count = if_not_exists(participant_count, :zero) + :one, team_count = if_not_exists(team_count, :zero) + :one",
                "ConditionExpression": "(attribute_not_exists(participant_count) OR participant_count < :max_participants) AND (attribute_not_exists(team_count) OR team_count < :max_teams)",
                "ExpressionAttributeValues": {
                    ":zero": {"N": "0"},
                    ":one": {"N": "1"},
                    ":max_participants": {"N": str(int(event.get("max_participants", 500)))},
                    ":max_teams": {"N": str(int(event.get("max_teams", 100)))},
                },
            }},
            {"Put": {"TableName": settings.dynamodb_table_name, "Item": {k: TypeSerializer().serialize(v) for k, v in team.items()}, "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)"}},
            {"Put": {"TableName": settings.dynamodb_table_name, "Item": {k: TypeSerializer().serialize(v) for k, v in participant.items()}, "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)"}},
        ])
    except client.exceptions.TransactionCanceledException as exc:
        if transaction_condition_failed(exc, 0) or counter_reached(
            table, event_id, "participant_count", int(event.get("max_participants", 500))
        ) or counter_reached(
            table, event_id, "team_count", int(event.get("max_teams", 100))
        ):
            raise HTTPException(409, "El evento alcanzó el máximo de participantes o equipos.")
        log_registration_cancellation(exc, event_id)
        raise HTTPException(409, registration_cancellation_message(exc))
    result = participant_session(event, team, participant, is_team_leader=True)
    result["invite_code"] = invite_code
    result["invite_url"] = f"/?event={event.get('event_code')}&invite={invite_code}"
    return result


@app.post("/api/v1/auth/admin/login")
def admin_login(body: AdminLogin):
    if not hmac.compare_digest(body.username, settings.admin_username) or not hmac.compare_digest(body.password, settings.admin_password):
        raise HTTPException(401, "Invalid administrator credentials")
    token = create_token({"sub": "arena-admin", "role": "admin", "name": "Instructor"})
    return {"access_token": token, "token_type": "bearer", "role": "admin"}


@app.get("/api/v1/me")
def me(principal: dict = Depends(require_participant)):
    participant = get_item(f"EVENT#{principal['event_id']}", f"USER#{principal['sub']}")
    if not participant:
        raise HTTPException(404, "Participant not found")
    return {k: participant.get(k) for k in ("participant_id", "display_name", "team_id", "event_id")}


@app.get("/api/v1/participant/dashboard")
def participant_dashboard(principal: dict = Depends(require_participant)):
    event_id = principal["event_id"]
    rows = query_partition(f"EVENT#{event_id}")
    team = next((x for x in rows if x.get("type") == "team" and x.get("team_id") == principal["team_id"]), None)
    event = next((x for x in rows if x.get("type") == "event"), None)
    if not team or not event:
        raise HTTPException(404, "Event or team not found")
    pack = load_pack(event.get("game_pack", "aws-event-driven"))
    completed = {x.get("mission_id") for x in rows if x.get("type") == "submission" and x.get("team_id") == principal["team_id"] and x.get("status") == "passed"}
    repository_link_awarded = any(
        row.get("SK") == f"SUB#{principal['team_id']}#mission-02-repo"
        for row in rows
    )
    missions = []
    for mission in public_missions(pack):
        mission_id = mission["id"]
        is_active = mission_id == event.get("active_mission_id")
        missions.append({**mission, "completed": mission_id in completed, "active": is_active, "locked": not is_active and mission_id not in completed})
    return {
        "event": {"event_id": event_id, "title": event.get("title"), "status": event.get("status"), "active_mission_id": event.get("active_mission_id"), "participation_mode": event.get("participation_mode", "team")},
        "team": {
            "team_id": team["team_id"], "name": team["name"], "score": int(team.get("score", 0)),
            "github_repo_name": team.get("repo_name", ""), "github_repo_url": team.get("repo_url", ""),
            "github_repo_link_awarded": repository_link_awarded,
        },
        "missions": missions,
        "completed_missions": sorted(completed),
    }


@app.post("/api/v1/participant/missions/{mission_id}/answer")
def answer_mission(mission_id: str, body: AnswerRequest, principal: dict = Depends(require_participant)):
    event = get_item(f"EVENT#{principal['event_id']}", "META")
    if not event or event.get("status") != "open":
        raise HTTPException(403, "The event is not active")
    if event.get("active_mission_id") != mission_id:
        raise HTTPException(409, "This mission is not currently active")
    pack = load_pack(event.get("game_pack", "aws-event-driven"))
    mission = get_mission(pack, mission_id)
    if not mission or mission.get("type") != "quiz":
        raise HTTPException(404, "This mission does not accept quiz answers")
    if not hmac.compare_digest(body.answer.strip().lower(), str(mission.get("answer", "")).strip().lower()):
        return {"passed": False, "message": "Not quite. Review the mission material and try again."}
    awarded = award_mission(principal["event_id"], principal["team_id"], mission, "quiz")
    return {"passed": True, "already_completed": not awarded, "points": 0 if not awarded else int(mission.get("points", 0)), "message": "Checkpoint completed."}


@app.get("/api/v1/leaderboard")
def leaderboard(principal: dict = Depends(require_participant)):
    rows = query_partition(f"EVENT#{principal['event_id']}")
    teams = [x for x in rows if x.get("type") == "team"]
    teams.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    return {"leaderboard": [{"rank": i + 1, "team_id": t["team_id"], "name": t["name"], "score": int(t.get("score", 0)), "is_mine": t["team_id"] == principal["team_id"]} for i, t in enumerate(teams)]}


@app.get("/api/v1/admin/lab-providers/health")
def lab_provider_health(_: dict = Depends(require_admin)):
    floci = FlociProvider().health()
    aws = AwsSandboxProvider(region=settings.dynamodb_region).health()
    return {
        "providers": [
            {"provider": floci.provider, "reachable": floci.reachable, "mode": floci.mode, "detail": floci.detail},
            {"provider": aws.provider, "reachable": aws.reachable, "mode": aws.mode, "detail": aws.detail},
        ]
    }


@app.get("/api/v1/admin/game-packs")
def admin_game_packs(_: dict = Depends(require_admin)):
    root = Path(settings.game_packs_dir)
    packs = []
    for manifest in root.glob("*/manifest.yaml"):
        try:
            pack = load_pack(manifest.parent.name)
            packs.append({"id": pack.get("id"), "title": pack.get("title"), "version": pack.get("version"), "difficulty": pack.get("difficulty"), "missions": len(pack.get("missions", []))})
        except Exception as exc:
            logger.warning("Skipping invalid Game Pack %s: %s", manifest, exc)
    return {"game_packs": packs}


@app.post("/api/v1/admin/events")
def create_event(body: EventCreateRequest, _: dict = Depends(require_admin)):
    try:
        pack = load_pack(body.game_pack)
    except FileNotFoundError:
        raise HTTPException(404, "Game Pack not found")
    event_id = str(uuid.uuid4())
    event_code = "ARENA-" + secrets.token_hex(4).upper()
    first_mission = pack.get("missions", [{}])[0].get("id")
    created = now_iso()
    if body.participation_mode == "team" and body.max_participants < 2:
        raise HTTPException(422, "Un evento por equipos necesita capacidad para al menos dos participantes.")
    max_teams = body.max_participants if body.participation_mode == "individual" else max(1, (body.max_participants + body.team_size - 1) // body.team_size)
    table_resource().put_item(Item={
        "PK": f"EVENT#{event_id}", "SK": "META", "type": "event",
        "event_id": event_id, "event_code": event_code, "title": body.title,
        "game_pack": body.game_pack, "status": "open", "active_mission_id": first_mission,
        "participation_mode": body.participation_mode,
        "team_size": 1 if body.participation_mode == "individual" else body.team_size,
        "max_participants": body.max_participants, "max_teams": max_teams,
        "participant_count": 0, "team_count": 0, "created_at": created,
    }, ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)")
    table_resource().put_item(Item={
        "PK": f"EVENTCODE#{event_code}", "SK": "EVENT", "type": "event-code-lookup",
        "event_id": event_id, "created_at": created,
    }, ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)")
    return {
        "event_id": event_id, "event_code": event_code, "title": body.title,
        "game_pack": body.game_pack, "participation_mode": body.participation_mode,
        "team_size": 1 if body.participation_mode == "individual" else body.team_size,
        "max_participants": body.max_participants,
        "message": "Evento creado. En modalidad de equipos, cada líder creará su equipo y compartirá el código de invitación.",
    }


@app.patch("/api/v1/admin/events/{event_id}/teams/{team_id}/github")
def register_team_repo(event_id: str, team_id: str, body: GitHubRepoRequest, _: dict = Depends(require_admin)):
    table_resource().update_item(
        Key={"PK": f"EVENT#{event_id}", "SK": f"TEAM#{team_id}"},
        UpdateExpression="SET repo_name = :repo, repo_url = :url, updated_at = :now",
        ExpressionAttributeValues={":repo": body.repo_name, ":url": body.repo_url, ":now": now_iso()},
        ConditionExpression="attribute_exists(PK)",
    )
    return {"event_id": event_id, "team_id": team_id, "repo_name": body.repo_name, "repo_url": body.repo_url}


@app.post("/api/v1/participant/github-repository")
def participant_register_github_repo(
    body: ParticipantGitHubRepoRequest,
    principal: dict = Depends(require_participant),
):
    parsed = urlsplit(body.repo_url.strip())
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(422, "Usa la URL HTTPS de un repositorio en github.com, por ejemplo https://github.com/organizacion/equipo.")
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 2 or not re.fullmatch(r"[A-Za-z0-9-]+", parts[0]) or not re.fullmatch(r"[A-Za-z0-9_.-]+", parts[1]):
        raise HTTPException(422, "La URL debe tener el formato https://github.com/organizacion/repositorio.")
    repo = parts[1][:-4] if parts[1].lower().endswith(".git") else parts[1]
    if not repo:
        raise HTTPException(422, "La URL debe tener el formato https://github.com/organizacion/repositorio.")
    repo_name = f"{parts[0]}/{repo}"
    repo_url = f"https://github.com/{repo_name}"
    event_id = principal["event_id"]
    team_id = principal["team_id"]
    event = get_item(f"EVENT#{event_id}", "META")
    if not event:
        raise HTTPException(404, "No encontramos el evento de este equipo.")
    if event.get("status") != "open":
        raise HTTPException(403, "El evento no está aceptando cambios en este momento.")
    if event.get("active_mission_id") != "mission-02":
        raise HTTPException(409, "El instructor debe activar la misión 2 para conectar el repositorio y recibir el punto.")

    table = table_resource()
    team_key = {"PK": f"EVENT#{event_id}", "SK": f"TEAM#{team_id}"}
    stored_team = table.get_item(Key=team_key, ConsistentRead=True).get("Item")
    if not stored_team:
        raise HTTPException(404, "No encontramos el equipo de este registro.")
    current_repo = stored_team.get("repo_name", "")
    if current_repo and current_repo.casefold() != repo_name.casefold():
        raise HTTPException(409, "Este equipo ya tiene otro repositorio vinculado. Consulta con el instructor para cambiarlo.")
    if current_repo:
        repo_name = current_repo
        repo_url = stored_team.get("repo_url") or f"https://github.com/{repo_name}"
    other_team = next(
        (
            row for row in query_partition(f"EVENT#{event_id}")
            if row.get("type") == "team"
            and row.get("team_id") != team_id
            and str(row.get("repo_name", "")).casefold() == repo_name.casefold()
        ),
        None,
    )
    if other_team:
        raise HTTPException(409, "Ese repositorio ya está vinculado a otro equipo.")

    submission_id = f"{team_id}#mission-02-repo"
    submission_key = {"PK": f"EVENT#{event_id}", "SK": f"SUB#{submission_id}"}
    repo_key = {"PK": f"EVENT#{event_id}", "SK": f"REPO#{repo_name.casefold()}"}
    if table.get_item(Key=submission_key, ConsistentRead=True).get("Item"):
        return {"repo_name": repo_name, "repo_url": repo_url, "awarded": False, "points": 0}

    now = now_iso()
    submission = {
        "PK": submission_key["PK"], "SK": submission_key["SK"],
        "type": "submission", "team_id": team_id, "mission_id": "mission-02-repo",
        "status": "passed", "points": 1, "source": "participant-github-link",
        "run_id": "", "created_at": now,
    }
    client = dynamodb_client()
    try:
        client.transact_write_items(TransactItems=[
            {"Update": {
                "TableName": settings.dynamodb_table_name,
                "Key": {"PK": {"S": team_key["PK"]}, "SK": {"S": team_key["SK"]}},
                "UpdateExpression": "SET repo_name = :repo, repo_url = :url, score = if_not_exists(score, :zero) + :point, updated_at = :now",
                "ConditionExpression": "attribute_exists(PK) AND (attribute_not_exists(repo_name) OR repo_name = :empty OR repo_name = :repo)",
                "ExpressionAttributeValues": {
                    ":repo": {"S": repo_name}, ":url": {"S": repo_url},
                    ":empty": {"S": ""}, ":zero": {"N": "0"},
                    ":point": {"N": "1"}, ":now": {"S": now},
                },
            }},
            {"Put": {
                "TableName": settings.dynamodb_table_name,
                "Item": {key: TypeSerializer().serialize(value) for key, value in submission.items()},
                "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
            }},
            {"Put": {
                "TableName": settings.dynamodb_table_name,
                "Item": {key: TypeSerializer().serialize(value) for key, value in {
                    **repo_key, "type": "github-repository-link", "repo_name": repo_name,
                    "team_id": team_id, "created_at": now,
                }.items()},
                "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
            }},
        ])
    except client.exceptions.TransactionCanceledException as exc:
        refreshed_team = table.get_item(Key=team_key, ConsistentRead=True).get("Item", {})
        existing_submission = table.get_item(Key=submission_key, ConsistentRead=True).get("Item")
        existing_repo_link = table.get_item(Key=repo_key, ConsistentRead=True).get("Item")
        if existing_repo_link and existing_repo_link.get("team_id") != team_id:
            raise HTTPException(409, "Ese repositorio ya está vinculado a otro equipo.")
        if existing_submission and refreshed_team.get("repo_name") == repo_name:
            return {"repo_name": repo_name, "repo_url": repo_url, "awarded": False, "points": 0}
        if refreshed_team.get("repo_name") and refreshed_team["repo_name"] != repo_name:
            raise HTTPException(409, "Este equipo ya tiene otro repositorio vinculado. Consulta con el instructor para cambiarlo.")
        log_registration_cancellation(exc, event_id)
        raise HTTPException(409, registration_cancellation_message(exc))
    return {"repo_name": repo_name, "repo_url": repo_url, "awarded": True, "points": 1}


@app.get("/api/v1/admin/dashboard")
def admin_dashboard(_: dict = Depends(require_admin)):
    events = scan_items(Attr("type").eq("event"))
    if not events:
        return {"event": None, "teams": [], "participants": 0, "submissions": 0}
    event = sorted(events, key=lambda x: x.get("created_at", ""), reverse=True)[0]
    rows = query_partition(f"EVENT#{event['event_id']}")
    teams = [x for x in rows if x.get("type") == "team"]
    teams.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    participants = [x for x in rows if x.get("type") == "participant"]
    submissions = [x for x in rows if x.get("type") == "submission"]
    return {
        "event": {k: event.get(k) for k in ("event_id", "title", "status", "active_mission_id", "game_pack", "participation_mode", "team_size", "max_participants")},
        "participants": len(participants),
        "submissions": len(submissions),
        "teams": [{"team_id": t["team_id"], "name": t["name"], "members": sum(1 for p in participants if p.get("team_id") == t["team_id"]), "score": int(t.get("score", 0)), "repo_url": t.get("repo_url", "")} for t in teams],
    }


@app.patch("/api/v1/admin/events/{event_id}/status")
def update_event_status(event_id: str, body: EventStatusRequest, _: dict = Depends(require_admin)):
    if body.status not in {"open", "paused", "finished"}:
        raise HTTPException(422, "Status must be open, paused, or finished")
    table_resource().update_item(
        Key={"PK": f"EVENT#{event_id}", "SK": "META"},
        UpdateExpression="SET #status = :status, updated_at = :now",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": body.status, ":now": now_iso()},
        ConditionExpression="attribute_exists(PK)",
    )
    return {"event_id": event_id, "status": body.status}


@app.post("/api/v1/admin/events/{event_id}/activate-mission")
def activate_mission(event_id: str, body: ActivateMissionRequest, _: dict = Depends(require_admin)):
    event = get_item(f"EVENT#{event_id}", "META")
    if not event:
        raise HTTPException(404, "Event not found")
    pack = load_pack(event.get("game_pack", "aws-event-driven"))
    if not get_mission(pack, body.mission_id):
        raise HTTPException(404, "Mission not found in Game Pack")
    table_resource().update_item(
        Key={"PK": f"EVENT#{event_id}", "SK": "META"},
        UpdateExpression="SET active_mission_id = :mission, updated_at = :now",
        ExpressionAttributeValues={":mission": body.mission_id, ":now": now_iso()},
    )
    return {"event_id": event_id, "active_mission_id": body.mission_id}


@app.post("/api/v1/admin/demo/award")
def demo_award(payload: dict, _: dict = Depends(require_admin)):
    if not settings.demo_mode:
        raise HTTPException(404, "Not found")
    event_id = str(payload.get("event_id", ""))
    team_id = str(payload.get("team_id", ""))
    mission_id = str(payload.get("mission_id", ""))
    event = get_item(f"EVENT#{event_id}", "META")
    if not event:
        raise HTTPException(404, "Event not found")
    mission = get_mission(load_pack(event.get("game_pack", "aws-event-driven")), mission_id)
    if not mission:
        raise HTTPException(404, "Mission not found")
    awarded = award_mission(event_id, team_id, mission, "demo")
    points = int(mission.get("workflow_points", mission.get("points", 0)))
    return {"awarded": awarded, "points": points if awarded else 0}


@app.post("/api/v1/webhooks/github")
async def github_webhook(request: Request, x_hub_signature_256: str | None = Header(default=None), x_github_event: str | None = Header(default=None)):
    if not settings.github_webhook_secret:
        raise HTTPException(503, "GitHub webhook integration is not configured")
    raw = await request.body()
    expected = "sha256=" + hmac.new(settings.github_webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
    if not x_hub_signature_256 or not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(401, "Invalid webhook signature")
    if x_github_event != "workflow_run":
        return {"accepted": True, "ignored": True}
    payload = json.loads(raw)
    run = payload.get("workflow_run", {})
    if payload.get("action") != "completed" or run.get("conclusion") != "success":
        return {"accepted": True, "ignored": True}
    if run.get("head_branch") not in {"main", "master"}:
        return {"accepted": True, "ignored": True, "reason": "workflow must complete on the protected default branch"}
    repo_name = payload.get("repository", {}).get("full_name")
    workflow_path = run.get("path", "")
    events = scan_items(Attr("type").eq("event"))
    matched = None
    for event in events:
        pack = load_pack(event.get("game_pack", "aws-event-driven"))
        workflow_map = pack.get("github_workflows", {})
        mission_id = workflow_map.get(workflow_path)
        if not mission_id:
            continue
        team = next((
            x for x in query_partition(f"EVENT#{event['event_id']}")
            if x.get("type") == "team"
            and str(x.get("repo_name", "")).casefold() == str(repo_name or "").casefold()
        ), None)
        mission = get_mission(pack, mission_id)
        if team and mission:
            matched = (event, team, mission)
            break
    if not matched:
        return {"accepted": True, "awarded": False, "reason": "repository or workflow is not registered"}
    event, team, mission = matched
    awarded = award_mission(event["event_id"], team["team_id"], mission, "github-actions", str(run.get("id", "")))
    return {"accepted": True, "awarded": awarded, "team_id": team["team_id"], "mission_id": mission["id"]}
