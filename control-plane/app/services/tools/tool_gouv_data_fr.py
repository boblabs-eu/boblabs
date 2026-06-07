"""French government open-data tool: data.gouv.fr public APIs.

Read-only wrapper around three public, no-auth APIs published by the data.gouv.fr
team:

- **Main API** — catalog (datasets, organizations, resources)
- **Metrics API** — usage statistics per dataset/org/site
- **Tabular API** — row-level queries on hosted CSV resources

Direct REST. No MCP indirection — the official MCP server at
https://mcp.data.gouv.fr/mcp is itself a wrapper around these same endpoints,
so we skip the extra hop.

Pair this tool with the optional skill file at ``templates/skills/datagouv.md``
when an agent needs nuanced workflow guidance: include the skill as a
``context_file`` on the lab blueprint and the agent will be able to
``file_read`` it from ``datagouv_skill.md``.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

_MAIN_BASE = "https://www.data.gouv.fr/api"
_METRICS_BASE = "https://metric-api.data.gouv.fr/api"
_TABULAR_BASE = "https://tabular-api.data.gouv.fr/api"
# Recherche d'entreprises — the canonical company-name search API for France
# (Annuaire des Entreprises). Public, no auth, listed on data.gouv.fr as a
# dataservice. This is what an agent should call to map "rezomes" → SIREN +
# NAF + headcount + address + dirigeants, not the raw SIRENE Tabular (which
# is impractical for name-based lookup on millions of rows).
_ENTREPRISES_BASE = "https://recherche-entreprises.api.gouv.fr"
_UA = "bob-api/gouv_data_fr (+https://boblabs.eu)"
_TIMEOUT = 15.0

# Cache TTLs (seconds). Catalog moves slowly, metrics move faster, tabular is
# user-driven so no cache.
_CATALOG_TTL = 600
_METRICS_TTL = 60

_cache: dict[str, dict] = {}


def _get_cached(key: str, ttl: int) -> dict | None:
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < ttl:
        return entry["data"]
    return None


def _set_cached(key: str, data) -> None:
    _cache[key] = {"data": data, "ts": time.time()}


TOOLS = {
    "gouv_data_fr": {
        "description": (
            "Query data.gouv.fr (French national open-data portal) public APIs. "
            "Read-only catalog search, dataset metadata, organizations, usage "
            "metrics, and tabular row queries on hosted CSV resources. "
            "Pair with the datagouv skill file at datagouv_skill.md "
            "(when the lab blueprint includes it) for API quirks and recipes."
        ),
        "parameters": {
            "action": {
                "type": "string",
                "description": (
                    "One of: search_entreprises (find French companies by name/filters — USE THIS "
                    "for company prospecting, not query_tabular), get_entreprise (by SIREN), "
                    "search_datasets, get_dataset, search_organizations, get_organization, "
                    "get_dataset_metrics, query_tabular, get_resource"
                ),
                "required": True,
            },
            "params": {
                "type": "object",
                "description": (
                    "Action-specific parameters. Common shapes: "
                    "search_entreprises {query, page=1, per_page=10, activite_principale (NAF code "
                    "e.g. '62.01Z'), code_postal, departement (e.g. '75' or '75,92,93'), "
                    "tranche_effectif_salarie (INSEE code e.g. '12' for 20-49), "
                    "categorie_juridique, etat_administratif='A'}; "
                    "get_entreprise {siren}; "
                    "search_datasets {query, page=1, page_size=20, sort, organization, format}; "
                    "get_dataset {id}; "
                    "search_organizations {query, page=1, page_size=20}; "
                    "get_organization {id}; "
                    "get_dataset_metrics {dataset_id, period_start, period_end}; "
                    "query_tabular {resource_id, columns, filters, page=1, page_size=50}; "
                    "get_resource {resource_id}. "
                    "Tip: when in doubt about `sort`, omit it — the API has a fixed "
                    "whitelist of valid fields and rejects guesses with HTTP 400. "
                    "On any 400 the error message tells you which field is wrong."
                ),
                "required": True,
            },
        },
    },
}


# ── Dispatcher ───────────────────────────────────────────────────────────────


async def gouv_data_fr(executor: "ToolExecutor", args: dict) -> dict:
    action = (args.get("action") or "").strip().lower()
    if not action:
        return {"success": False, "output": "gouv_data_fr: 'action' is required"}

    params = args.get("params") or {}
    if not isinstance(params, dict):
        return {"success": False, "output": "gouv_data_fr: 'params' must be an object"}

    handlers = {
        "search_entreprises": _search_entreprises,
        "get_entreprise": _get_entreprise,
        "search_datasets": _search_datasets,
        "get_dataset": _get_dataset,
        "search_organizations": _search_organizations,
        "get_organization": _get_organization,
        "get_dataset_metrics": _get_dataset_metrics,
        "query_tabular": _query_tabular,
        "get_resource": _get_resource,
    }
    handler = handlers.get(action)
    if handler is None:
        return {
            "success": False,
            "output": f"gouv_data_fr: unknown action '{action}'. Known: {sorted(handlers)}",
        }

    try:
        return await handler(params)
    except httpx.TimeoutException:
        return {"success": False, "output": f"gouv_data_fr: '{action}' timed out after {_TIMEOUT}s"}
    except httpx.HTTPError as e:
        return {"success": False, "output": f"gouv_data_fr: HTTP error in '{action}': {e}"}
    except Exception as e:  # noqa: BLE001
        logger.exception("gouv_data_fr action %s crashed", action)
        return {"success": False, "output": f"gouv_data_fr: '{action}' failed: {e}"}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA, "Accept": "application/json"})


async def _get_json(client: httpx.AsyncClient, url: str, params: dict | None = None) -> tuple[int, dict | list | str]:
    resp = await client.get(url, params=params)
    if resp.headers.get("content-type", "").startswith("application/json"):
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, resp.text
    return resp.status_code, resp.text


def _err(status: int, body) -> dict:
    if isinstance(body, dict):
        # data.gouv.fr returns {"message": "...", "errors": {"field": "explanation"}}.
        # Surface BOTH so the agent can see which parameter is wrong.
        msg = body.get("message") or body.get("detail") or ""
        errs = body.get("errors")
        if isinstance(errs, dict) and errs:
            field_msgs = "; ".join(f"{k}: {v}" for k, v in errs.items())
            msg = f"{msg} ({field_msgs})" if msg else field_msgs
        if not msg:
            msg = body
    else:
        msg = body
    return {"success": False, "output": f"HTTP {status}: {msg}"}


# ── Action handlers — Main API ──────────────────────────────────────────────


async def _search_datasets(params: dict) -> dict:
    query = str(params.get("query") or "").strip()
    page = int(params.get("page") or 1)
    page_size = min(int(params.get("page_size") or 20), 100)
    sort = params.get("sort")
    organization = params.get("organization")
    fmt = params.get("format")

    qp = {"page": page, "page_size": page_size}
    if query:
        qp["q"] = query
    if sort:
        qp["sort"] = sort
    if organization:
        qp["organization"] = organization
    if fmt:
        qp["format"] = fmt

    cache_key = f"search_datasets:{sorted(qp.items())}"
    cached = _get_cached(cache_key, _CATALOG_TTL)
    if cached is not None:
        return {"success": True, "output": cached}

    async with _client() as client:
        status, body = await _get_json(client, f"{_MAIN_BASE}/2/datasets/search/", qp)
    if status != 200 or not isinstance(body, dict):
        return _err(status, body)

    output = {
        "total": body.get("total"),
        "page": body.get("page"),
        "page_size": body.get("page_size"),
        "next_page": body.get("next_page"),
        "data": [
            {
                "id": d.get("id"),
                "slug": d.get("slug"),
                "title": d.get("title"),
                "organization": (d.get("organization") or {}).get("name") if isinstance(d.get("organization"), dict) else d.get("organization"),
                "page": d.get("page"),
                "resources_count": len(d.get("resources") or []),
                "frequency": d.get("frequency"),
                "last_update": d.get("last_update"),
            }
            for d in (body.get("data") or [])
        ],
    }
    _set_cached(cache_key, output)
    return {"success": True, "output": output}


async def _get_dataset(params: dict) -> dict:
    dataset_id = str(params.get("id") or "").strip()
    if not dataset_id:
        return {"success": False, "output": "get_dataset: 'id' (slug or UUID) is required"}

    cache_key = f"get_dataset:{dataset_id}"
    cached = _get_cached(cache_key, _CATALOG_TTL)
    if cached is not None:
        return {"success": True, "output": cached}

    async with _client() as client:
        status, body = await _get_json(client, f"{_MAIN_BASE}/2/datasets/{dataset_id}/")
    if status != 200 or not isinstance(body, dict):
        return _err(status, body)

    output = {
        "id": body.get("id"),
        "slug": body.get("slug"),
        "title": body.get("title"),
        "description": body.get("description"),
        "organization": body.get("organization"),
        "frequency": body.get("frequency"),
        "license": body.get("license"),
        "tags": body.get("tags"),
        "created_at": body.get("created_at"),
        "last_modified": body.get("last_modified"),
        "page": body.get("page"),
        "resources": [
            {
                "id": r.get("id"),
                "title": r.get("title"),
                "format": r.get("format"),
                "url": r.get("url"),
                "filesize": r.get("filesize"),
                "mime": r.get("mime"),
                "last_modified": r.get("last_modified"),
            }
            for r in (body.get("resources") or [])
        ],
    }
    _set_cached(cache_key, output)
    return {"success": True, "output": output}


async def _search_organizations(params: dict) -> dict:
    query = str(params.get("query") or "").strip()
    page = int(params.get("page") or 1)
    page_size = min(int(params.get("page_size") or 20), 100)

    qp = {"page": page, "page_size": page_size}
    if query:
        qp["q"] = query

    cache_key = f"search_orgs:{sorted(qp.items())}"
    cached = _get_cached(cache_key, _CATALOG_TTL)
    if cached is not None:
        return {"success": True, "output": cached}

    async with _client() as client:
        status, body = await _get_json(client, f"{_MAIN_BASE}/1/organizations/", qp)
    if status != 200 or not isinstance(body, dict):
        return _err(status, body)

    output = {
        "total": body.get("total"),
        "page": body.get("page"),
        "page_size": body.get("page_size"),
        "next_page": body.get("next_page"),
        "data": [
            {
                "id": o.get("id"),
                "slug": o.get("slug"),
                "name": o.get("name"),
                "acronym": o.get("acronym"),
                "page": o.get("page"),
                "metrics": o.get("metrics"),
            }
            for o in (body.get("data") or [])
        ],
    }
    _set_cached(cache_key, output)
    return {"success": True, "output": output}


async def _get_organization(params: dict) -> dict:
    org_id = str(params.get("id") or "").strip()
    if not org_id:
        return {"success": False, "output": "get_organization: 'id' (slug or UUID) is required"}

    cache_key = f"get_org:{org_id}"
    cached = _get_cached(cache_key, _CATALOG_TTL)
    if cached is not None:
        return {"success": True, "output": cached}

    async with _client() as client:
        status, body = await _get_json(client, f"{_MAIN_BASE}/1/organizations/{org_id}/")
    if status != 200 or not isinstance(body, dict):
        return _err(status, body)

    output = {
        "id": body.get("id"),
        "slug": body.get("slug"),
        "name": body.get("name"),
        "acronym": body.get("acronym"),
        "description": body.get("description"),
        "url": body.get("url"),
        "page": body.get("page"),
        "metrics": body.get("metrics"),
        "created_at": body.get("created_at"),
        "last_modified": body.get("last_modified"),
    }
    _set_cached(cache_key, output)
    return {"success": True, "output": output}


async def _get_resource(params: dict) -> dict:
    resource_id = str(params.get("resource_id") or "").strip()
    if not resource_id:
        return {"success": False, "output": "get_resource: 'resource_id' (UUID) is required"}

    cache_key = f"get_resource:{resource_id}"
    cached = _get_cached(cache_key, _CATALOG_TTL)
    if cached is not None:
        return {"success": True, "output": cached}

    async with _client() as client:
        status, body = await _get_json(client, f"{_MAIN_BASE}/2/datasets/resources/{resource_id}/")
    if status != 200 or not isinstance(body, dict):
        return _err(status, body)

    _set_cached(cache_key, body)
    return {"success": True, "output": body}


# ── Action handlers — Metrics API ───────────────────────────────────────────


async def _get_dataset_metrics(params: dict) -> dict:
    dataset_id = str(params.get("dataset_id") or "").strip()
    if not dataset_id:
        return {"success": False, "output": "get_dataset_metrics: 'dataset_id' is required"}

    qp: dict[str, str | int] = {"dataset_id__exact": dataset_id, "page_size": min(int(params.get("page_size") or 50), 200)}
    if params.get("period_start"):
        qp["metric_month__gte"] = str(params["period_start"])
    if params.get("period_end"):
        qp["metric_month__lte"] = str(params["period_end"])

    cache_key = f"metrics:{sorted(qp.items())}"
    cached = _get_cached(cache_key, _METRICS_TTL)
    if cached is not None:
        return {"success": True, "output": cached}

    async with _client() as client:
        status, body = await _get_json(client, f"{_METRICS_BASE}/datasets/data/", qp)
    if status != 200 or not isinstance(body, dict):
        return _err(status, body)

    _set_cached(cache_key, body)
    return {"success": True, "output": body}


# ── Action handlers — Tabular API ───────────────────────────────────────────


async def _query_tabular(params: dict) -> dict:
    resource_id = str(params.get("resource_id") or "").strip()
    if not resource_id:
        return {"success": False, "output": "query_tabular: 'resource_id' (CSV resource UUID) is required"}

    page = int(params.get("page") or 1)
    page_size = min(int(params.get("page_size") or 50), 500)
    qp: dict = {"page": page, "page_size": page_size}

    columns = params.get("columns")
    if isinstance(columns, list) and columns:
        qp["columns"] = ",".join(str(c) for c in columns)

    # Filters: dict of {column: value} or {column: {"op": "exact", "value": ...}}
    filters = params.get("filters") or {}
    if isinstance(filters, dict):
        for col, spec in filters.items():
            if isinstance(spec, dict):
                op = spec.get("op", "exact")
                val = spec.get("value")
                if val is None:
                    continue
                qp[f"{col}__{op}"] = val
            else:
                qp[f"{col}__exact"] = spec

    sort = params.get("sort")
    if sort:
        qp["sort"] = sort

    async with _client() as client:
        status, body = await _get_json(client, f"{_TABULAR_BASE}/resources/{resource_id}/data/", qp)
    if status != 200:
        return _err(status, body)
    return {"success": True, "output": body}


# ── Action handlers — Recherche d'entreprises (Annuaire) ───────────────────


def _normalize_company_record(item: dict) -> dict:
    """Trim the rich recherche-entreprises payload to the fields agents actually
    need for prospecting. Keeps SIREN, name, NAF code, headcount band, address,
    and the list of directors so the Copywriter can address them by name.
    """
    siege = item.get("siege") or {}
    dirigeants = []
    for d in (item.get("dirigeants") or []):
        if not isinstance(d, dict):
            continue
        dirigeants.append({
            "nom": d.get("nom") or d.get("nom_complet"),
            "prenoms": d.get("prenoms") or d.get("prenom"),
            "qualite": d.get("qualite"),
            "type_dirigeant": d.get("type_dirigeant"),
        })
    return {
        "siren": item.get("siren"),
        "nom_complet": item.get("nom_complet"),
        "nom_raison_sociale": item.get("nom_raison_sociale"),
        "sigle": item.get("sigle"),
        "activite_principale": item.get("activite_principale"),  # NAF/APE code
        "section_activite_principale": item.get("section_activite_principale"),
        "tranche_effectif_salarie": item.get("tranche_effectif_salarie"),
        "annee_tranche_effectif_salarie": item.get("annee_tranche_effectif_salarie"),
        "categorie_juridique": item.get("nature_juridique") or item.get("categorie_juridique"),
        "etat_administratif": item.get("etat_administratif"),
        "date_creation": item.get("date_creation"),
        "siege": {
            "siret": siege.get("siret"),
            "code_postal": siege.get("code_postal"),
            "commune": siege.get("libelle_commune") or siege.get("commune"),
            "departement": siege.get("departement"),
            "region": siege.get("region"),
            "adresse": siege.get("adresse") or siege.get("geo_adresse"),
            "activite_principale": siege.get("activite_principale"),
            "tranche_effectif_salarie": siege.get("tranche_effectif_salarie"),
        },
        "dirigeants": dirigeants,
        "public_page": f"https://annuaire-entreprises.data.gouv.fr/entreprise/{item.get('siren')}" if item.get("siren") else None,
    }


async def _search_entreprises(params: dict) -> dict:
    """Search French companies by name and/or filters.

    Wraps https://recherche-entreprises.api.gouv.fr/search. Free, no auth, no
    pagination tricks — pass `q` and any combination of:
      - activite_principale: NAF/APE code (e.g. '62.01Z')
      - code_postal: postal code
      - departement: department code (or comma-list)
      - tranche_effectif_salarie: INSEE headcount band code (e.g. '12' for 20-49)
      - categorie_juridique: legal-form code
      - etat_administratif: 'A' (active, default) or 'C' (cessée)
    """
    query = str(params.get("query") or params.get("q") or "").strip()
    page = int(params.get("page") or 1)
    per_page = min(int(params.get("per_page") or params.get("page_size") or 10), 25)

    qp: dict = {"page": page, "per_page": per_page}
    if query:
        qp["q"] = query
    for k in (
        "activite_principale",
        "code_postal",
        "departement",
        "tranche_effectif_salarie",
        "categorie_juridique",
        "etat_administratif",
        "code_commune",
        "nature_juridique",
        "section_activite_principale",
    ):
        v = params.get(k)
        if v is None or v == "":
            continue
        # API accepts comma-separated lists for multi-value filters
        if isinstance(v, list):
            qp[k] = ",".join(str(x) for x in v)
        else:
            qp[k] = str(v)

    # Default to active companies if the caller didn't say otherwise.
    qp.setdefault("etat_administratif", "A")

    cache_key = f"search_entreprises:{sorted(qp.items())}"
    cached = _get_cached(cache_key, _CATALOG_TTL)
    if cached is not None:
        return {"success": True, "output": cached}

    async with _client() as client:
        status, body = await _get_json(client, f"{_ENTREPRISES_BASE}/search", qp)
    if status != 200 or not isinstance(body, dict):
        return _err(status, body)

    output = {
        "total_results": body.get("total_results"),
        "page": body.get("page") or page,
        "per_page": body.get("per_page") or per_page,
        "total_pages": body.get("total_pages"),
        "results": [_normalize_company_record(r) for r in (body.get("results") or [])],
    }
    _set_cached(cache_key, output)
    return {"success": True, "output": output}


async def _get_entreprise(params: dict) -> dict:
    """Fetch a single French company by SIREN (9 digits) via the Annuaire search."""
    siren = str(params.get("siren") or params.get("id") or "").strip().replace(" ", "")
    if not siren or not siren.isdigit() or len(siren) != 9:
        return {"success": False, "output": "get_entreprise: 'siren' must be a 9-digit string"}

    cache_key = f"get_entreprise:{siren}"
    cached = _get_cached(cache_key, _CATALOG_TTL)
    if cached is not None:
        return {"success": True, "output": cached}

    qp = {"q": siren, "per_page": 1, "etat_administratif": "A,C"}
    async with _client() as client:
        status, body = await _get_json(client, f"{_ENTREPRISES_BASE}/search", qp)
    if status != 200 or not isinstance(body, dict):
        return _err(status, body)
    results = body.get("results") or []
    if not results:
        return {"success": False, "output": f"get_entreprise: SIREN {siren} not found"}
    output = _normalize_company_record(results[0])
    _set_cached(cache_key, output)
    return {"success": True, "output": output}


HANDLERS = {
    "gouv_data_fr": gouv_data_fr,
}
