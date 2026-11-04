# Participant registration

CloudOps Arena supports two registration modes, configured per event.

## Individual

1. Participant enters their name and event code in the portal.
2. The portal looks up the event and confirms it is configured for individual registration.
3. The API creates a private leaderboard entry and participant record in one DynamoDB transaction.
4. The participant enters the Game Pack.

Each individual is represented internally by a one-member leaderboard group so the same scoring and mission model can be reused.

## Teams

1. Participant enters their name and event code.
2. The portal looks up the event and confirms it is configured for teams.
3. The participant chooses **Create team** or **I have an invitation**.
4. A team creator submits a team name. The API atomically checks event capacity, creates the team, registers the creator as its first member, and returns a random invitation code/link once.
5. The team creator shares the invitation link with colleagues.
6. Colleagues open the link, enter their names, and complete registration using the invitation code.
7. The API atomically checks event and team capacity before adding each teammate.

New invitation codes are stored as SHA-256 hashes. The raw code is returned only in the creation response and is not stored in DynamoDB. The legacy `team_code` request field and plaintext join-code lookup remain temporarily for compatibility with the first local demo seed; remove them after old demo data is discarded.

## LAN access for an auditorium

The web container publishes port `5173` on the host's network interfaces. Participants open `http://<host-lan-ip>:5173`. The browser sends `/api/...` requests to the same origin and Nginx proxies them to the API container. Never build the frontend with `VITE_API_BASE_URL=http://localhost:8000` for a multi-laptop event: `localhost` in a participant's browser means their own laptop.

Only port `5173` should be accessible from the participant network. The API's host port `8000` and Floci's port `4566` remain bound to loopback in the local compose setup.
