COMPOSE := docker compose -f compose.yaml -f compose.dev.yaml

.PHONY: help dev dev-init dev-build dev-down dev-clean dev-logs \
        shell-backend shell-frontend psql redis-cli mail \
        migrate makemigration test lint

help:
	@echo "ICS - available targets:"
	@echo ""
	@echo "  make dev           - start the dev stack with hot reload"
	@echo "  make dev-init      - first run: build images and apply migrations"
	@echo "  make dev-build     - rebuild the dev images"
	@echo "  make dev-down      - stop the containers"
	@echo "  make dev-clean     - stop and delete volumes (DELETES DATA)"
	@echo "  make dev-logs      - backend and frontend logs"
	@echo ""
	@echo "  make shell-backend - bash in the backend container"
	@echo "  make shell-frontend - sh in the frontend container"
	@echo "  make psql          - psql into Postgres"
	@echo "  make redis-cli     - redis-cli"
	@echo "  make mail          - open MailPit (dev mailbox)"
	@echo ""
	@echo "  make migrate       - alembic upgrade head"
	@echo "  make makemigration MSG='description'  - autogenerate a migration"
	@echo "  make seed-admin EMAIL=a@example.com PASS='long-passphrase'  - create an admin"
	@echo "  make outbox        - show sent e-mails (dev outbox)"
	@echo "  make test          - pytest"
	@echo "  make lint          - ruff and tsc"

dev:
	$(COMPOSE) up

dev-init: dev-build
	$(COMPOSE) up -d postgres redis
	@echo "Waiting for Postgres..."
	@until $(COMPOSE) exec -T postgres pg_isready -U ics > /dev/null 2>&1; do sleep 1; done
	$(COMPOSE) run --rm backend alembic upgrade head
	@echo "Init done. Run 'make dev'."

dev-build:
	$(COMPOSE) build

dev-down:
	$(COMPOSE) down

dev-clean:
	$(COMPOSE) down -v

dev-logs:
	$(COMPOSE) logs -f backend frontend

shell-backend:
	$(COMPOSE) exec backend bash

shell-frontend:
	$(COMPOSE) exec frontend sh

psql:
	$(COMPOSE) exec postgres psql -U ics -d ics

redis-cli:
	$(COMPOSE) exec redis redis-cli

mail:
	@echo "MailPit: http://localhost:8025"
	@command -v open >/dev/null 2>&1 && open http://localhost:8025 \
	  || command -v xdg-open >/dev/null 2>&1 && xdg-open http://localhost:8025 \
	  || echo "(could not open a browser, open the URL by hand)"

migrate:
	$(COMPOSE) run --rm backend alembic upgrade head

seed-admin:
	@if [ -z "$(EMAIL)" ] || [ -z "$(PASS)" ]; then echo "Usage: make seed-admin EMAIL=a@example.com PASS='long-passphrase'"; exit 1; fi
	$(COMPOSE) run --rm backend python -m app.cli seed-admin --email "$(EMAIL)" --password "$(PASS)"

outbox:
	$(COMPOSE) run --rm backend python -m app.cli outbox-tail

makemigration:
	@if [ -z "$(MSG)" ]; then echo "Usage: make makemigration MSG='description'"; exit 1; fi
	$(COMPOSE) run --rm backend alembic revision --autogenerate -m "$(MSG)"

test:
	$(COMPOSE) run --rm backend pytest

lint:
	$(COMPOSE) run --rm backend ruff check app
	$(COMPOSE) run --rm frontend npm run typecheck
