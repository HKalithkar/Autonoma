SHELL := /bin/sh

PYTHON ?= python3
COMPOSE ?= docker compose -f infra/docker-compose.yml
TRACE_COMPOSE ?= docker compose -f infra/docker-compose.langfuse.yml
TRACE_OTEL_COMPOSE ?= docker compose -f infra/docker-compose.yml -f infra/docker-compose.otel-langfuse.yml

format:
	$(COMPOSE) run --rm --build devtools python -m ruff format .
	$(COMPOSE) run --rm --build web npm run format

lint:
	$(COMPOSE) run --rm --build devtools python -m ruff check .
	$(COMPOSE) run --rm --build devtools python -m mypy apps
	$(COMPOSE) run --rm --build web npm run lint

policy-test:
	docker run --rm $(if $(DOCKER_PLATFORM),--platform $(DOCKER_PLATFORM),) -v "$(PWD)/apps/policy:/policy" openpolicyagent/opa:0.65.0 test /policy

test:
	$(COMPOSE) run --rm --build \
		-e VAULT_INTEGRATION_TESTS \
		-e VAULT_ADDR \
		-e VAULT_TOKEN \
		-e VAULT_KV_MOUNT \
		devtools python -m pytest
	$(COMPOSE) run --rm --build web npm run test

coverage:
	$(COMPOSE) run --rm --build devtools python -m pytest --cov=apps --cov=libs --cov-report=term-missing

e2e:
	$(COMPOSE) run --rm e2e

test-vault: engines-up
	docker compose -f infra/docker-compose.engines.yml run --rm vault-init
	docker compose -f infra/docker-compose.engines.yml run --rm \
		-e VAULT_INTEGRATION_TESTS=1 \
		-e VAULT_ADDR=http://vault:8200 \
		-e VAULT_TOKEN=autonoma-dev-token \
		-e VAULT_KV_MOUNT=kv \
		devtools python tools/wait_for_vault_seed.py
	docker compose -f infra/docker-compose.engines.yml run --rm \
		-e VAULT_INTEGRATION_TESTS=1 \
		-e VAULT_ADDR=http://vault:8200 \
		-e VAULT_TOKEN=autonoma-dev-token \
		-e VAULT_KV_MOUNT=kv \
		devtools python -m pytest \
		apps/plugin_gateway/tests/test_plugin_gateway_invoke.py::test_invoke_vault_secret_resolve_integration
	$(MAKE) engines-down

db-migrate:
	$(COMPOSE) run --rm --build devtools alembic -c apps/api/alembic.ini upgrade head

dev:
	$(COMPOSE) up --build

up:
	$(COMPOSE) up -d --build

all-up:
	docker compose -f infra/docker-compose.yml -f infra/docker-compose.engines.yml --profile airflow --profile jenkins --profile n8n up -d --build

all-down:
	docker compose -f infra/docker-compose.yml -f infra/docker-compose.engines.yml --profile airflow --profile jenkins --profile n8n down

trace-up:
	$(TRACE_COMPOSE) up -d --build
	$(TRACE_OTEL_COMPOSE) up -d --build otel-collector

down:
	$(COMPOSE) down

cleanup:
	$(COMPOSE) down --remove-orphans --volumes --rmi local
	@if [ "$(ALL_ORPHANS)" = "1" ]; then \
		echo "Pruning orphan containers, images, volumes, and networks..."; \
		docker container prune -f; \
		docker image prune -af; \
		docker volume prune -af; \
		docker network prune -f; \
	fi

cleanup-all:
	$(COMPOSE) down --remove-orphans --volumes --rmi all
	$(TRACE_COMPOSE) down --remove-orphans --volumes --rmi all
	docker compose -f infra/docker-compose.engines.yml down --remove-orphans --volumes --rmi all
	docker container prune -f
	docker image prune -af
	docker volume prune -af
	docker network prune -f

trace-down:
	$(TRACE_COMPOSE) down
	$(COMPOSE) up -d --build otel-collector

smoke:
	./scripts/smoke.sh

engines-airflow-up:
	docker compose -f infra/docker-compose.engines.yml --profile airflow up -d --build

engines-jenkins-up:
	docker compose -f infra/docker-compose.engines.yml --profile jenkins up -d --build

engines-n8n-up:
	docker compose -f infra/docker-compose.engines.yml --profile n8n up -d --build

engines-up:
	docker compose -f infra/docker-compose.engines.yml --profile airflow --profile jenkins up -d --build

engines-down:
	docker compose -f infra/docker-compose.engines.yml --profile airflow --profile jenkins down
DOCKER_PLATFORM ?=
