"""Owner Governance 2026-11-27 (D29): the dedicated export listener for HN.

HN may leave the export API only on a separate listener (its own port, never
mapped by Tailscale Funnel/serve), only to an allowlisted *socket peer*, and
never when a forwarding/Funnel header is present. This module owns:

* the startup check (``hn_listener_status``) -- fail closed on any
  misconfiguration, with a clear log line;
* ``ExportHnListenerMiddleware`` -- a pure ASGI middleware that recognises the
  listener by ``scope["server"]`` port, refuses forbidden requests, and stamps
  ``scope["state"]["export_hn_ok"]`` for the export route to read;
* ``start_hn_listener`` -- runs the same app on the extra port in-process.

Nothing here trusts a forwarded header: only ``scope["client"]`` (the TCP peer)
and ``scope["server"]`` (the local socket) are consulted.
"""
import asyncio
import ipaddress
import logging
from dataclasses import dataclass

from starlette.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)

# Never trusted, never accepted on the HN listener (lowercase, as ASGI sends).
REFUSED_HEADERS = (b"tailscale-funnel-request", b"x-forwarded-for", b"forwarded")
_started = False
# Keep equal to the Dockerfile's `--port` (test_export_d29 pins it); APP_PORT
# is what the HN-port != app-port startup check compares against.
HN_STATE_KEY = "export_hn_ok"
EXPORT_PATH_PREFIX = "/api/v1/export/"


@dataclass(frozen=True)
class HnListenerStatus:
    enabled: bool
    port: int | None
    reason: str
    peers: tuple = ()


def parse_peers(raw: str) -> tuple:
    nets = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part:
            nets.append(ipaddress.ip_network(part, strict=False))  # ValueError on garbage
    return tuple(nets)


def hn_listener_status(cfg=settings) -> HnListenerStatus:
    """Disabled unless EXPORT_HN_PORT is set and sane. Never raises."""
    port = cfg.EXPORT_HN_PORT
    if not port:
        return HnListenerStatus(False, None, "EXPORT_HN_PORT is not set")
    if not (1 <= port <= 65535):
        return HnListenerStatus(False, None, f"EXPORT_HN_PORT {port} is not a valid port")
    if port == cfg.APP_PORT:
        return HnListenerStatus(
            False, None, f"EXPORT_HN_PORT {port} equals the normal app port (APP_PORT); the HN listener must be separate"
        )
    try:
        peers = parse_peers(cfg.EXPORT_HN_ALLOWED_PEERS)
    except ValueError:
        return HnListenerStatus(False, None, "EXPORT_HN_ALLOWED_PEERS is not a valid comma-separated IP/CIDR list")
    if not peers:
        return HnListenerStatus(False, None, "EXPORT_HN_ALLOWED_PEERS is empty (an HN listener needs an explicit allowlist)")
    return HnListenerStatus(True, port, "ok", peers)


def log_startup_check(cfg=settings) -> HnListenerStatus:
    status = hn_listener_status(cfg)
    if status.enabled:
        logger.info("Export HN listener enabled on port %s (%d allowed peer range(s))", status.port, len(status.peers))
    elif cfg.EXPORT_HN_PORT:
        logger.critical("Export HN listener REFUSED, HN stays disabled: %s", status.reason)
    return status


def peer_allowed(peer_host: str | None, peers: tuple) -> bool:
    if not peer_host:
        return False
    try:
        addr = ipaddress.ip_address(peer_host)
    except ValueError:  # e.g. a unix-socket peer: never allowlisted
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return any(addr.version == n.version and addr in n for n in peers)


class ExportHnListenerMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware) so it sees the raw scope."""

    def __init__(self, app, cfg=settings):
        self.app = app
        self.cfg = cfg

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = hn_listener_status(self.cfg)
        server = scope.get("server")
        server_port = server[1] if server and len(server) > 1 else None
        # The marker is always written here, so a client cannot pre-set it.
        state = scope.setdefault("state", {})
        state[HN_STATE_KEY] = False
        if not (status.enabled and server_port == status.port):
            await self.app(scope, receive, send)
            return
        # --- on the dedicated HN listener ---
        headers = {k.lower() for k, _ in scope.get("headers", [])}
        if any(h in headers for h in REFUSED_HEADERS):
            await self._refuse(scope, receive, send, 403, "Forwarded or Funnel requests are refused on this listener")
            return
        client = scope.get("client")
        if not peer_allowed(client[0] if client else None, status.peers):
            await self._refuse(scope, receive, send, 403, "Peer not allowed")
            return
        if not scope.get("path", "").startswith(EXPORT_PATH_PREFIX):
            await self._refuse(scope, receive, send, 404, "Not found")
            return
        state[HN_STATE_KEY] = True
        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(scope, receive, send, code: int, detail: str):
        await JSONResponse({"detail": detail}, status_code=code)(scope, receive, send)


async def start_hn_listener(app, cfg=settings):
    """Serve ``app`` on the HN port inside this process. Returns (server, task)
    or None when disabled. Access logging is off; nothing HN-related is logged."""
    global _started
    if _started:  # idempotent: one HN listener per process
        return None
    status = log_startup_check(cfg)
    if not status.enabled:
        return None
    import uvicorn

    _started = True
    # lifespan="off": the HN server must not re-run the app lifespan (it would
    # start a second scheduler and recurse into this function).
    config = uvicorn.Config(
        app, host=cfg.EXPORT_HN_HOST, port=status.port, access_log=False, log_config=None, lifespan="off"
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # the main server owns signals
    task = asyncio.create_task(server.serve())
    return server, task
