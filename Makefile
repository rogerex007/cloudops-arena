COMPOSE = docker compose -f infra/local/compose.yaml

.PHONY: up down reset logs api-logs web-logs local-lab plan destroy fmt test

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

reset:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f --tail=100

api-logs:
	$(COMPOSE) logs -f api

web-logs:
	$(COMPOSE) logs -f web

plan:
	./scripts/run-floci-lab.sh

local-lab:
	APPLY=true ./scripts/run-floci-lab.sh

destroy:
	./scripts/destroy-floci-lab.sh

fmt:
	terraform -chdir=game-packs/aws-event-driven/terraform fmt -recursive
	terraform -chdir=infra/aws-control-plane fmt -recursive

test:
	./scripts/check-project.sh
