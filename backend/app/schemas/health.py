from typing import Literal

from pydantic import BaseModel


class ReadinessOut(BaseModel):
    """PR24B (`docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md` §15A):
    the fail-closed production readiness contract. `status` mirrors the
    HTTP status code (`ready` <-> 200, `not_ready` <-> 503) so a body-aware
    caller and a status-code-only caller always agree. `database` is the
    sole readiness-blocking dependency; `redis` is reported for visibility
    only and never affects `status` (see `redis` field docstring below)."""

    status: Literal["ready", "not_ready"]
    database: Literal["ok", "error"]
    # Never blocks readiness: app.core.redis's own cache/refresh-token
    # helpers are already fail-open on a Redis outage, so a readiness
    # contract that hard-fails on Redis would contradict the application's
    # own established behavior (§15A.5). "degraded" only ever means
    # "Redis is unreachable right now" -- it carries no other severity.
    redis: Literal["ok", "degraded"]
