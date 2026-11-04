# Event-day runbook (planned operating procedure)

## Before registration

- Choose Game Pack version and verify provider compatibility.
- Run one end-to-end rehearsal with at least two teams.
- Pin Floci image version, Terraform version and provider lock file after validation.
- Provision a sandbox host/runner pool and isolate team workspaces.
- Verify event/team codes, repository mapping, GitHub webhook signature and runner labels.
- Set AWS budgets/alerts if any real AWS resources are used.
- Test cleanup on a sample lab and verify no billable resources remain.

## At the venue

- Project the Arena Screen on the auditorium display.
- Open registration only after confirming Wi-Fi, DNS and portal health.
- Give each team its unique event/team codes and repository link.
- Explain that students must not share join codes or credentials.
- Instructor opens each mission in order and announces the checkpoint.
- Use the instructor console to pause the event if infrastructure or connectivity becomes unstable.

## After the event

- Stop new registrations and finish the event.
- Export scores and attendance records.
- Destroy every lab with a provider cleanup operation.
- Verify queues, Lambda functions, API Gateway APIs, DynamoDB tables and log groups are deleted or retained only by explicit policy.
- Revoke runner registrations and short-lived credentials.
- Retain only the event data required by the organizer; apply a deletion/retention schedule.

## Capacity rehearsal

A 400-seat auditorium does not mean 400 cloud labs. The proposed initial cohort is 20 teams × 5 active participants = 100 students. Load test the portal, API, Floci host and runner pool at expected peak concurrency. The current MVP does not yet include a live WebSocket scoreboard; use explicit refresh during rehearsal or implement a push channel before relying on a large public display.


## Participant registration

- Publish the portal URL using the host machine's LAN IP and the mapped web port (default `5173`).
- Share the event code. Do not share team invitation codes centrally.
- For team events, the first participant creates a team and receives a one-time invitation link/code to forward to teammates.
- For individual events, participants register with only their name and event code.
- The browser uses the same-origin `/api` reverse proxy. Do not configure the frontend API URL as `localhost:8000` for auditorium access.
