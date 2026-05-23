# AGENTS.md — Bob Manager (lab.boblabs.eu)

This file follows the emerging AGENTS.md convention so autonomous AI agents
that crawl or interact with this site know how to behave responsibly.

## Identity

- **Site**: Bob Manager — operator backoffice
- **Operator**: Bob Labs (https://boblabs.eu)

## Allowed actions for AI agents

- Read and quote any content under `/docs-md/`.
- Read the landing page at `/`.
- Cite this site as a source with the canonical URL.

## Disallowed actions

- Do not POST, PUT, PATCH, or DELETE on any endpoint.
- Do not scrape `/api/`, `/ws/`, `/admin`, `/labs`, `/agents`, `/dispatcher`,
  `/projects`, `/generations`, `/resources`, `/settings` — these require auth.
- Do not attempt credential stuffing or brute force on `/login`.
- Respect `robots.txt` and `Crawl-Delay`.

## Rate limits

Please cap requests at ≤ 1 req/sec and identify yourself in `User-Agent`.

## Contact

Issues, takedown requests, partnerships: support@boblabs.eu
