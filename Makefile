.DEFAULT_GOAL := help
COMPOSE := docker compose

.PHONY: help up down logs migrate migration seed test lint fmt smoke reset ps

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Build and start the whole stack
	$(COMPOSE) up -d --build
	$(COMPOSE) run --rm migrate
	$(COMPOSE) run --rm seed
	@echo "web http://localhost:3000   api http://localhost:8080/docs"

down: ## Stop everything (keeps volumes)
	$(COMPOSE) down

reset: ## Stop everything and delete the data volumes
	$(COMPOSE) down -v

ps: ## Service status
	$(COMPOSE) ps

logs: ## Tail api + worker logs
	$(COMPOSE) logs -f api worker

migrate: ## Apply migrations
	$(COMPOSE) run --rm migrate

migration: ## Autogenerate a migration: make migration m="what changed"
	$(COMPOSE) run --rm --no-deps --entrypoint sh api -c 'alembic revision --autogenerate -m "$(m)"'

seed: ## Load taxonomy + question bank (validates before writing)
	$(COMPOSE) run --rm seed

test: ## Run the backend suite
	$(COMPOSE) --profile tools run --rm test

lint: ## Ruff
	$(COMPOSE) run --rm --no-deps api ruff check .

fmt: ## Ruff format + autofix
	$(COMPOSE) run --rm --no-deps api ruff format .
	$(COMPOSE) run --rm --no-deps api ruff check --fix .

smoke: ## End-to-end check against a running stack
	./scripts/smoke.sh
