# Contributing to Bob Labs

Thanks for considering a contribution. Bob Labs is a multi-service stack
(FastAPI control-plane, React UI, Go agent, sandbox runners, GPU services),
so the contribution path varies a bit by area. The basics below cover 90 %
of cases.

## Quick start (local dev)

You'll need Docker + Docker Compose v2.20+, and ~20 GB free for image
builds and the data volumes.

```bash
git clone <fork-url> bob-manager
cd bob-manager
cp .env.example .env                 # edit the secrets / model knobs you need
docker compose up -d --build         # bob-api, bob-ui, bob-db, qdrant, agent…
```

bob-ui lands on http://localhost:3000 (default operator login —
`admin` / value of `ADMIN_PASSWORD` in `.env`). The API's Swagger doc lives
at http://localhost:8888/docs.

For development with hot-reload:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

## Reporting bugs

Open a GitHub issue with:

- What you tried, what happened, what you expected.
- The commit SHA or release tag you're running.
- Relevant log excerpts (please redact secrets — `.env`, JWTs, agent
  tokens, RAG content).
- For UI bugs, a screenshot helps.

For **security-relevant** issues, use [SECURITY.md](SECURITY.md) instead.

## Submitting a PR

1. **Fork + branch**: `git checkout -b <kind>/<short-description>` where
   `<kind>` is `feat`, `fix`, `docs`, `refactor`, `test`, or `chore`.
2. **Keep it focused**: one logical change per PR. If you have a bundle,
   split it.
3. **Run the local checks** before opening the PR:
   - `python scripts/test-all-tools.py` — the 40-tool smoke gate. Should
     end with `0 STACKTRACE` (a "GRACEFUL" exit for tools that need
     external credentials is fine).
   - `docker compose up -d --build` — at minimum confirm `bob-api`,
     `bob-db`, `bob-qdrant`, and `bob-ui` come up healthy.
   - For UI changes, click through the flow you touched (Labs → run a
     trivial lab, Outreach → check the queue renders, etc.).
4. **Commit messages** — the project follows a loose Conventional-Commit
   convention. Examples from the log:
   - `feat : add solo_agent loop type`
   - `fix : outreach datetime YAML + publish-public.sh bugs`
   - `docs : phase 0 audit fixes + new CONSUMER_APPS contract`
   The prefix matters more than the precise punctuation.
5. **Open the PR**: describe the motivation (the *why*), summarise the
   changes (the *what*), and call out anything you're unsure about
   (sub-question for reviewers).

## Style — current state, not aspirations

The repo doesn't ship with an enforced formatter or linter today. PR
reviews are the source of truth for style. A few conventions that have
emerged:

- **Python** — type hints on public function signatures, `__future__
  annotations`, async-first for anything I/O-bound. Don't add new top-
  level dependencies without a one-line justification in the PR.
- **JavaScript (React)** — function components, hooks, no class
  components. Keep components small; extract when state/effect logic
  starts spilling.
- **SQL** — migrations go through `control-plane/app/migrations/init.sql`
  (consolidated schema, no per-migration files for now).
- **Built-in tools** — new tool files at
  `control-plane/app/services/tools/tool_<name>.py`, auto-discovered.
  Mirror an existing tool (`tool_defi_data.py` is a good reference for
  the dispatcher + cache pattern). Always return
  `{"success": bool, "output": str}`. See [TOOLS_AND_SANDBOX.md](docs/TOOLS_AND_SANDBOX.md).

## Tests

There is no per-module unit-test suite yet — coverage comes from the
end-to-end smoke gate (`scripts/test-all-tools.py`) and manual UI
verification. If your change touches a critical path (auth, dispatcher,
sandbox isolation), consider adding a targeted script under `scripts/`
that exercises it.

## Docs

When you change behaviour, please update the matching doc under `docs/`:

- `TOOLS_AND_SANDBOX.md` for tool surface changes.
- `CONSUMER_APPS.md` for the `/internal/apps/*` HMAC channel.
- `LABS.md` / `AGENTS_AND_ORCHESTRATION.md` for the lab runner.
- `CONFIGURATION.md` if you add a new env var.

Keep the docs short and concrete — examples > prose.

## Questions

Open a GitHub Discussion (or an issue tagged `question` if Discussions
aren't enabled yet). We're happy to help you find the right place for a
change before you start writing code.
