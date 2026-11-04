"""Create a fresh, ready-to-use demo event without pre-created teams.

Team-mode participants create their team in the portal; individual-mode participants
are assigned a private leaderboard entry automatically.
"""
import os
import time
import boto3
from datetime import datetime, timezone
from botocore.exceptions import ClientError

ENDPOINT = os.getenv("DYNAMODB_ENDPOINT_URL", "http://floci:4566")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
TABLE = os.getenv("DYNAMODB_TABLE_NAME", "CloudOpsArena")
EVENT_ID = os.getenv("DEMO_EVENT_ID", "aws-event-driven-02")
EVENT_CODE = os.getenv("DEMO_EVENT_CODE", "CLOUDOPS-TEAM")
MODE = os.getenv("DEMO_PARTICIPATION_MODE", "team").strip().lower()
TEAM_SIZE = int(os.getenv("DEMO_TEAM_SIZE", "5"))
MAX_PARTICIPANTS = int(os.getenv("DEMO_MAX_PARTICIPANTS", "100"))

if MODE not in {"team", "individual"}:
    raise ValueError("DEMO_PARTICIPATION_MODE must be 'team' or 'individual'")
if MODE == "team" and not 2 <= TEAM_SIZE <= 6:
    raise ValueError("DEMO_TEAM_SIZE must be between 2 and 6")

client = boto3.client(
    "dynamodb", endpoint_url=ENDPOINT, region_name=REGION,
    aws_access_key_id="test", aws_secret_access_key="test",
)
for attempt in range(30):
    try:
        client.describe_table(TableName=TABLE)
        break
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException" or attempt == 29:
            raise
        time.sleep(2)

table = boto3.resource(
    "dynamodb", endpoint_url=ENDPOINT, region_name=REGION,
    aws_access_key_id="test", aws_secret_access_key="test",
).Table(TABLE)

existing = table.get_item(Key={"PK": f"EVENT#{EVENT_ID}", "SK": "META"}).get("Item")
if existing:
    print(f"Demo event {EVENT_ID} already exists; preserving registrations and scores.")
    raise SystemExit(0)

now = datetime.now(timezone.utc).isoformat()
first_mission = "mission-01"
event = {
    "PK": f"EVENT#{EVENT_ID}", "SK": "META", "type": "event",
    "event_id": EVENT_ID, "event_code": EVENT_CODE,
    "title": "Todo empieza con un evento", "game_pack": "aws-event-driven",
    "status": "open", "active_mission_id": first_mission,
    "participation_mode": MODE,
    "team_size": TEAM_SIZE if MODE == "team" else 1,
    "max_participants": MAX_PARTICIPANTS,
    "max_teams": MAX_PARTICIPANTS if MODE == "individual" else max(1, (MAX_PARTICIPANTS + TEAM_SIZE - 1) // TEAM_SIZE),
    "participant_count": 0, "team_count": 0, "created_at": now,
}
table.put_item(Item=event, ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)")
table.put_item(Item={
    "PK": f"EVENTCODE#{EVENT_CODE}", "SK": "EVENT", "type": "event-code-lookup",
    "event_id": EVENT_ID, "created_at": now,
}, ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)")

print("Demo event seeded successfully.")
print(f"Event ID: {EVENT_ID}")
print(f"Event code: {EVENT_CODE}")
print(f"Participation mode: {MODE}")
print(f"Capacity: {MAX_PARTICIPANTS} participants")
if MODE == "team":
    print(f"Team size: {TEAM_SIZE}. Participants create teams and share their invitation code.")
else:
    print("Individual registration: each participant receives an individual leaderboard entry.")
