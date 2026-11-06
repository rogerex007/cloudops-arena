import hashlib
from types import SimpleNamespace

from app import main
from app.main import CreateTeamRequest, JoinRequest
from fastapi import HTTPException


class FakeDynamoClient:
    class exceptions:
        class TransactionCanceledException(Exception):
            def __init__(self, response=None):
                self.response = response or {}

    def __init__(self):
        self.transactions = []
        self.transaction_error = None
        self.transaction_errors = []
        self.transaction_attempts = 0

    def transact_write_items(self, **kwargs):
        self.transaction_attempts += 1
        if self.transaction_errors:
            raise self.transaction_errors.pop(0)
        if self.transaction_error:
            raise self.transaction_error
        self.transactions.append(kwargs["TransactItems"])


class FakeTable:
    def __init__(self):
        self.meta = SimpleNamespace(client=FakeDynamoClient())
        self.items = {}

    def get_item(self, *, Key, ConsistentRead):
        assert ConsistentRead is True
        key = (Key["PK"], Key["SK"])
        return {"Item": self.items[key]} if key in self.items else {}


def team_event(mode="team"):
    return {
        "event_id": "event-1",
        "event_code": "ARENA-1234",
        "title": "Test Event",
        "status": "open",
        "active_mission_id": "mission-02",
        "participation_mode": mode,
        "team_size": 5 if mode == "team" else 1,
        "max_participants": 100,
        "max_teams": 50 if mode == "team" else 100,
    }


def test_public_event_lookup_exposes_registration_mode(monkeypatch):
    monkeypatch.setattr(main, "event_by_code", lambda _code: team_event("team"))
    result = main.public_event_by_code("arena-1234")
    assert result["participation_mode"] == "team"
    assert result["team_size"] == 5


def test_individual_registration_creates_private_leaderboard_entry(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(main, "event_by_code", lambda _code: team_event("individual"))
    monkeypatch.setattr(main, "table_resource", lambda: table)
    monkeypatch.setattr(main, "dynamodb_client", lambda: table.meta.client)

    result = main.participant_join(JoinRequest(
        event_code="ARENA-1234", display_name="Ana Student"
    ))

    assert result["participant"]["name"] == "Ana Student"
    assert result["participant"]["participation_mode"] == "individual"
    assert len(table.meta.client.transactions) == 1
    operations = table.meta.client.transactions[0]
    assert len(operations) == 3  # event counter + private team + participant
    team_item = operations[1]["Put"]["Item"]
    assert team_item["max_members"]["N"] == "1"


def test_individual_registration_reports_full_event_when_capacity_condition_fails(monkeypatch):
    table = FakeTable()
    table.meta.client.transaction_error = table.meta.client.exceptions.TransactionCanceledException({
        "CancellationReasons": [{"Code": "ConditionalCheckFailed"}]
    })
    monkeypatch.setattr(main, "event_by_code", lambda _code: team_event("individual"))
    monkeypatch.setattr(main, "table_resource", lambda: table)
    monkeypatch.setattr(main, "dynamodb_client", lambda: table.meta.client)

    try:
        main.participant_join(JoinRequest(event_code="ARENA-1234", display_name="Ana Student"))
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "capacidad máxima" in exc.detail
    else:
        raise AssertionError("A full event should reject additional participants")


def test_individual_registration_detects_capacity_without_cancellation_reasons(monkeypatch):
    table = FakeTable()
    table.items[("EVENT#event-1", "META")] = {"participant_count": 100}
    table.meta.client.transaction_error = table.meta.client.exceptions.TransactionCanceledException()
    monkeypatch.setattr(main, "event_by_code", lambda _code: team_event("individual"))
    monkeypatch.setattr(main, "table_resource", lambda: table)
    monkeypatch.setattr(main, "dynamodb_client", lambda: table.meta.client)

    try:
        main.participant_join(JoinRequest(event_code="ARENA-1234", display_name="Ana Student"))
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "capacidad máxima" in exc.detail
    else:
        raise AssertionError("A full event should reject additional participants")


def test_individual_registration_retries_transient_transaction_conflict(monkeypatch):
    table = FakeTable()
    table.meta.client.transaction_errors.append(
        table.meta.client.exceptions.TransactionCanceledException({
            "CancellationReasons": [
                {"Code": "None"},
                {"Code": "TransactionConflict"},
                {"Code": "None"},
            ]
        })
    )
    monkeypatch.setattr(main, "event_by_code", lambda _code: team_event("individual"))
    monkeypatch.setattr(main, "table_resource", lambda: table)
    monkeypatch.setattr(main, "dynamodb_client", lambda: table.meta.client)
    monkeypatch.setattr(main.time, "sleep", lambda _delay: None)

    result = main.participant_join(JoinRequest(event_code="ARENA-1234", display_name="Ana Student"))

    assert result["participant"]["name"] == "Ana Student"
    assert table.meta.client.transaction_attempts == 2
    assert len(table.meta.client.transactions) == 1


def test_individual_registration_does_not_misreport_other_transaction_failures(monkeypatch):
    table = FakeTable()
    table.meta.client.transaction_error = table.meta.client.exceptions.TransactionCanceledException({
        "Error": {"Code": "TransactionCanceledException"},
        "ResponseMetadata": {"RequestId": "request-123"},
        "CancellationReasons": [
            {"Code": "None"},
            {"Code": "ValidationError", "Message": "Invalid update expression"},
            {"Code": "ConditionalCheckFailed"},
        ]
    })
    monkeypatch.setattr(main, "event_by_code", lambda _code: team_event("individual"))
    monkeypatch.setattr(main, "table_resource", lambda: table)
    monkeypatch.setattr(main, "dynamodb_client", lambda: table.meta.client)

    try:
        main.participant_join(JoinRequest(event_code="ARENA-1234", display_name="Ana Student"))
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "capacidad máxima" not in exc.detail
        assert "base de datos rechazó los datos" in exc.detail
        assert "Operación 2: Invalid update expression" in exc.detail
        assert "request-123" in exc.detail
    else:
        raise AssertionError("A cancelled registration transaction should fail")


def test_team_creator_gets_one_time_invitation(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(main, "event_by_code", lambda _code: team_event("team"))
    monkeypatch.setattr(main, "table_resource", lambda: table)
    monkeypatch.setattr(main, "dynamodb_client", lambda: table.meta.client)

    result = main.participant_create_team(CreateTeamRequest(
        event_code="ARENA-1234", display_name="Ana Student", team_name="Lambda Force"
    ))

    assert result["participant"]["is_team_leader"] is True
    assert result["participant"]["team_name"] == "Lambda Force"
    assert result["invite_code"].startswith("ARENA-")
    assert result["invite_url"].startswith("/?event=ARENA-1234&invite=")
    stored_team = table.meta.client.transactions[0][1]["Put"]["Item"]
    assert stored_team["invite_code_hash"]["S"] == hashlib.sha256(result["invite_code"].upper().encode()).hexdigest()
    assert "join_code" not in stored_team  # plaintext invitation is not persisted


def test_teammate_joins_using_hashed_invitation(monkeypatch):
    table = FakeTable()
    event = team_event("team")
    invite = "ARENA-THISISATESTCODE"
    team = {
        "type": "team", "team_id": "team-xyz", "name": "Lambda Force", "max_members": 5,
        "member_count": 1,
        "invite_code_hash": hashlib.sha256(invite.encode()).hexdigest(),
    }
    monkeypatch.setattr(main, "event_by_code", lambda _code: event)
    monkeypatch.setattr(main, "query_partition", lambda _pk: [team])
    monkeypatch.setattr(main, "table_resource", lambda: table)
    monkeypatch.setattr(main, "dynamodb_client", lambda: table.meta.client)

    result = main.participant_join(JoinRequest(
        event_code="ARENA-1234", display_name="Luis Student", invite_code=invite.lower()
    ))

    assert result["participant"]["team_id"] == "team-xyz"
    operations = table.meta.client.transactions[0]
    assert len(operations) == 3  # event capacity + team capacity + participant


def test_team_event_requires_invitation_to_join_existing_team(monkeypatch):
    monkeypatch.setattr(main, "event_by_code", lambda _code: team_event("team"))
    try:
        main.participant_join(JoinRequest(event_code="ARENA-1234", display_name="Ana"))
    except HTTPException as exc:
        assert exc.status_code == 422
        assert "invitación" in exc.detail
    else:
        raise AssertionError("Joining a team without an invitation should fail")


def test_individual_event_rejects_team_creation(monkeypatch):
    monkeypatch.setattr(main, "event_by_code", lambda _code: team_event("individual"))
    try:
        main.participant_create_team(CreateTeamRequest(
            event_code="ARENA-1234", display_name="Ana", team_name="Lambda Force"
        ))
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("An individual event must not allow team creation")


def test_participant_connects_github_repository_for_one_point(monkeypatch):
    table = FakeTable()
    team_id = "team-xyz"
    table.items[(f"EVENT#{team_event()['event_id']}", f"TEAM#{team_id}")] = {
        "PK": "EVENT#event-1", "SK": f"TEAM#{team_id}", "type": "team",
        "team_id": team_id, "repo_name": "", "repo_url": "", "score": 3,
    }
    monkeypatch.setattr(main, "get_item", lambda _pk, _sk: team_event())
    monkeypatch.setattr(main, "table_resource", lambda: table)
    monkeypatch.setattr(main, "dynamodb_client", lambda: table.meta.client)
    monkeypatch.setattr(main, "query_partition", lambda _pk: [])

    result = main.participant_register_github_repo(
        main.ParticipantGitHubRepoRequest(repo_url="https://github.com/cloudops/team-xyz.git"),
        {"event_id": "event-1", "team_id": team_id},
    )

    assert result == {
        "repo_name": "cloudops/team-xyz", "repo_url": "https://github.com/cloudops/team-xyz",
        "awarded": True, "points": 1,
    }
    operations = table.meta.client.transactions[0]
    assert len(operations) == 4
    update = operations[0]["Update"]
    assert update["ExpressionAttributeValues"][":point"]["N"] == "1"
    assert update["ExpressionAttributeValues"][":repo"]["S"] == "cloudops/team-xyz"
    submission = operations[1]["Put"]["Item"]
    assert submission["mission_id"]["S"] == "mission-02-repo"
    assert submission["points"]["N"] == "1"
    repo_claim = operations[2]["Put"]["Item"]
    assert repo_claim["SK"]["S"] == "REPO#cloudops/team-xyz"
    assert repo_claim["team_id"]["S"] == team_id


def test_participant_repository_link_is_idempotent(monkeypatch):
    table = FakeTable()
    team_id = "team-xyz"
    team_key = (f"EVENT#event-1", f"TEAM#{team_id}")
    submission_key = (f"EVENT#event-1", f"SUB#{team_id}#mission-02-repo")
    table.items[team_key] = {
        "PK": team_key[0], "SK": team_key[1], "type": "team", "team_id": team_id,
        "repo_name": "cloudops/team-xyz", "repo_url": "https://github.com/cloudops/team-xyz",
    }
    table.items[submission_key] = {"type": "submission", "points": 1}
    monkeypatch.setattr(main, "get_item", lambda _pk, _sk: team_event())
    monkeypatch.setattr(main, "table_resource", lambda: table)
    monkeypatch.setattr(main, "query_partition", lambda _pk: [])

    result = main.participant_register_github_repo(
        main.ParticipantGitHubRepoRequest(repo_url="https://github.com/cloudops/team-xyz"),
        {"event_id": "event-1", "team_id": team_id},
    )

    assert result["awarded"] is False
    assert result["points"] == 0
    assert table.meta.client.transactions == []


def test_participant_cannot_replace_linked_github_repository(monkeypatch):
    table = FakeTable()
    team_id = "team-xyz"
    team_key = (f"EVENT#event-1", f"TEAM#{team_id}")
    table.items[team_key] = {
        "PK": team_key[0], "SK": team_key[1], "type": "team", "team_id": team_id,
        "repo_name": "cloudops/old-repo", "repo_url": "https://github.com/cloudops/old-repo",
    }
    monkeypatch.setattr(main, "get_item", lambda _pk, _sk: team_event())
    monkeypatch.setattr(main, "table_resource", lambda: table)
    monkeypatch.setattr(main, "query_partition", lambda _pk: [])

    try:
        main.participant_register_github_repo(
            main.ParticipantGitHubRepoRequest(repo_url="https://github.com/cloudops/new-repo"),
            {"event_id": "event-1", "team_id": team_id},
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "ya tiene otro repositorio" in exc.detail
    else:
        raise AssertionError("Participants must not replace the linked repository")


def test_participant_cannot_link_repository_already_claimed_by_another_team(monkeypatch):
    table = FakeTable()
    team_id = "team-xyz"
    table.items[(f"EVENT#event-1", f"TEAM#{team_id}")] = {
        "PK": "EVENT#event-1", "SK": f"TEAM#{team_id}", "type": "team",
        "team_id": team_id, "repo_name": "", "repo_url": "",
    }
    monkeypatch.setattr(main, "get_item", lambda _pk, _sk: team_event())
    monkeypatch.setattr(main, "table_resource", lambda: table)
    monkeypatch.setattr(main, "query_partition", lambda _pk: [{
        "type": "team", "team_id": "another-team", "repo_name": "cloudops/team-xyz",
    }])

    try:
        main.participant_register_github_repo(
            main.ParticipantGitHubRepoRequest(repo_url="https://github.com/cloudops/team-xyz"),
            {"event_id": "event-1", "team_id": team_id},
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "vinculado a otro equipo" in exc.detail
    else:
        raise AssertionError("A GitHub repository must not be shared by multiple teams")


def test_participant_repository_link_rejects_non_github_urls():
    try:
        main.participant_register_github_repo(
            main.ParticipantGitHubRepoRequest(repo_url="https://example.com/cloudops/team"),
            {"event_id": "event-1", "team_id": "team-xyz"},
        )
    except HTTPException as exc:
        assert exc.status_code == 422
        assert "github.com" in exc.detail
    else:
        raise AssertionError("Only GitHub HTTPS repository URLs should be accepted")


def test_terraform_workflow_awards_only_remaining_mission_points(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(main, "dynamodb_client", lambda: table.meta.client)

    awarded = main.award_mission(
        "event-1",
        "team-xyz",
        {"id": "mission-02", "points": 15, "workflow_points": 14},
        "github-actions",
    )

    assert awarded is True
    score_update = table.meta.client.transactions[0][1]["Update"]
    assert score_update["ExpressionAttributeValues"][":points"]["N"] == "14"
