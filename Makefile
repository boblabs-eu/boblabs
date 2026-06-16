.PHONY: test test-up test-down test-only test-shell integration help

# Tests run inside the bob-api image so they get the exact same Python +
# system deps as production. Postgres comes up as a sibling container on
# the bob-manager_default network.
TEST_IMAGE   = bob-manager-bob-api:latest
TEST_NETWORK = bob-manager_default
TEST_DB_URL  = postgresql+asyncpg://bobtest:bobtest@bob-test-db:5432/bob_test
PYTEST_ARGS ?=

DOCKER_RUN_TEST = docker run --rm \
	--network $(TEST_NETWORK) \
	-v $(CURDIR)/control-plane:/app \
	-w /app \
	-e DATABASE_URL='$(TEST_DB_URL)' \
	-e JWT_SECRET='test-jwt-secret-do-not-use-in-prod' \
	-e ADMIN_SECRET='test-admin-secret' \
	-e BOB_API_ALLOW_MULTI_WORKER='1' \
	-e BOB_API_LOCK_PATH=/tmp/bob-api.test.lock \
	$(TEST_IMAGE)

help:
	@echo "Targets:"
	@echo "  make test         Bring up test DB, install pytest, run suite, tear down"
	@echo "  make test-up      Just bring up the test DB"
	@echo "  make test-down    Tear down the test DB"
	@echo "  make test-only    Run pytest assuming test DB is already up"
	@echo "  make test-shell   Drop into a shell in the test container"
	@echo "  make integration  Run scripts/ smoke suite against dev stack"

test: test-up test-only test-down

test-up:
	docker compose -f docker-compose.test.yml up -d --wait

test-down:
	docker compose -f docker-compose.test.yml down -v

test-only:
	$(DOCKER_RUN_TEST) sh -c "\
		pip install -q -r requirements-test.txt && \
		( alembic current 2>/dev/null | grep -q . || alembic stamp 0001_baseline ) && \
		alembic upgrade head && \
		python -m pytest -q tests/ $(PYTEST_ARGS)"

test-shell:
	$(DOCKER_RUN_TEST) sh -c "\
		pip install -q -r requirements-test.txt && \
		( alembic current 2>/dev/null | grep -q . || alembic stamp 0001_baseline ) && \
		alembic upgrade head && \
		exec sh"

integration:
	@echo "Integration smoke (requires dev stack on :3000/:4000 + bob-api):"
	docker compose exec -T bob-api python /app/scripts/test-all-tools.py || true
	BOB_API_URL=$${BOB_API_URL:-http://127.0.0.1:8888} python3 scripts/smoke_consumer_app_agent.py
	BOB_API_URL=$${BOB_API_URL:-http://127.0.0.1:8888} python3 scripts/smoke_consumer_app_rag.py
