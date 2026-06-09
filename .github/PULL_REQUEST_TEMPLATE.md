<!--
Thanks for opening a PR! A few notes:

- Keep one logical change per PR. Smaller PRs land faster.
- If you're fixing a bug, link the issue it closes.
- If your change is user-visible, add a CHANGELOG entry under [Unreleased].
- See CONTRIBUTING.md for the branch + commit conventions.
-->

## Summary

<!-- One paragraph: what does this PR change, and why? -->

## Test plan

<!--
How did you verify the change? Examples:
- [x] make test         (unit + regression suite)
- [x] ruff check . && ruff format --check .
- [x] Manual: spun up a lab, ran 5 iterations, confirmed the X field landed
- [x] Frontend: opened /admin in browser, hard-refreshed, checked Y panel
-->

- [ ] `make test` passes locally
- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] If the change touches REST routes: `python scripts/export_openapi.py > docs/openapi.json` regenerated

## Migration notes

<!--
If this PR introduces a new alembic migration, an env var, a breaking
config change, or a one-way data migration — describe it here so the
release notes pick it up. Otherwise: "None."
-->

None.

## Related issue

Closes #
