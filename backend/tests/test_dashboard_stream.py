import asyncio
import inspect

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1 import dashboard as dashboard_module
from app.core.security import create_access_token


def test_stream_endpoint_has_no_direct_db_dependency():
    sig = inspect.signature(dashboard_module.stream)
    assert "db" not in sig.parameters


def test_stream_uses_the_dedicated_short_lived_auth_dependency_not_get_current_user():
    # dashboard.stream must NOT depend on app.api.v1.deps.get_current_user, whose
    # own db: AsyncSession = Depends(get_db) sub-dependency would otherwise sit in
    # the same dependency tree as the StreamingResponse for the connection's
    # full lifetime.
    sig = inspect.signature(dashboard_module.stream)
    user_param = sig.parameters["_user"]
    assert user_param.default.dependency is dashboard_module.get_current_user_for_stream


class _TrackingSession:
    """Wraps a real AsyncSession and records when it is opened/closed."""

    def __init__(self, real_session, opened: list, closed: list):
        self._real_session = real_session
        self._opened = opened
        self._closed = closed

    async def __aenter__(self):
        self._opened.append(self)
        return self._real_session

    async def __aexit__(self, *exc_info):
        await self._real_session.close()
        self._closed.append(self)
        return False


def _tracking_session_local(session_maker, opened: list, closed: list):
    def factory():
        return _TrackingSession(session_maker(), opened, closed)

    return factory


@pytest.mark.asyncio
async def test_stream_authentication_succeeds_and_releases_its_session_before_streaming(
    monkeypatch, db_engine, seeded_users
):
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    opened: list = []
    closed: list = []
    monkeypatch.setattr(dashboard_module, "AsyncSessionLocal", _tracking_session_local(session_maker, opened, closed))

    admin = seeded_users["admin"]
    token = create_access_token(str(admin.id), "admin")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await dashboard_module.get_current_user_for_stream(credentials)

    assert user.id == admin.id
    # Exactly one session was opened to resolve authentication, and it was
    # already closed by the time get_current_user_for_stream returned —
    # nothing survives into the StreamingResponse that follows.
    assert len(opened) == 1
    assert opened == closed


@pytest.mark.asyncio
async def test_stream_authentication_rejects_inactive_user(monkeypatch, db_engine, seeded_users):
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(dashboard_module, "AsyncSessionLocal", session_maker)

    admin = seeded_users["admin"]
    async with session_maker() as session:
        db_user = await session.get(type(admin), admin.id)
        db_user.is_active = False
        await session.commit()

    token = create_access_token(str(admin.id), "admin")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc_info:
        await dashboard_module.get_current_user_for_stream(credentials)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_stream_authentication_rejects_missing_credentials():
    with pytest.raises(HTTPException) as exc_info:
        await dashboard_module.get_current_user_for_stream(None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_stream_authentication_rejects_invalid_token():
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-real-token")
    with pytest.raises(HTTPException) as exc_info:
        await dashboard_module.get_current_user_for_stream(credentials)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_stream_opens_and_closes_a_fresh_session_each_poll_iteration(monkeypatch):
    opened = []
    closed = []

    class FakeSession:
        def __init__(self, idx):
            self.idx = idx

        async def __aenter__(self):
            opened.append(self.idx)
            return self

        async def __aexit__(self, *exc_info):
            closed.append(self.idx)
            return False

    counter = {"n": 0}

    def fake_session_local():
        counter["n"] += 1
        return FakeSession(counter["n"])

    async def fake_get_summary(session):
        assert session.idx not in closed
        return {"iteration": session.idx}

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(dashboard_module, "AsyncSessionLocal", fake_session_local)
    monkeypatch.setattr(dashboard_module.dashboard_service, "get_summary", fake_get_summary)
    monkeypatch.setattr(dashboard_module.asyncio, "sleep", fake_sleep)

    response = await dashboard_module.stream(_user=object())
    body_iterator = response.body_iterator

    first_chunk = await body_iterator.__anext__()
    assert closed == [1]
    assert '"iteration": 1' in first_chunk

    second_chunk = await body_iterator.__anext__()
    assert closed == [1, 2]
    assert '"iteration": 2' in second_chunk

    assert opened == [1, 2]

    await body_iterator.aclose()


@pytest.mark.asyncio
async def test_multiple_concurrent_streams_do_not_starve_the_pool_for_ordinary_requests(monkeypatch):
    """Regression test for the original SSE connection-pool-exhaustion bug.

    Simulates a connection pool with only 2 slots. 5 concurrent "browser
    tabs" each hold a stream open across several poll iterations, and one
    "ordinary" (non-streaming) request runs at the same time. Because each
    stream iteration only holds its session for the brief query window (and
    releases it before sleeping), the pool is never exhausted and every task
    completes well within the timeout. If a regression reintroduced a
    session held for the full stream lifetime, more than 2 of the 5 streams
    would block forever waiting for a pool slot and this test would time out.
    """
    pool_capacity = 2
    semaphore = asyncio.Semaphore(pool_capacity)
    active_count = 0
    max_concurrent = 0
    lock = asyncio.Lock()

    class TrackedSession:
        async def __aenter__(self):
            nonlocal active_count, max_concurrent
            await semaphore.acquire()
            async with lock:
                active_count += 1
                max_concurrent = max(max_concurrent, active_count)
            return self

        async def __aexit__(self, *exc_info):
            nonlocal active_count
            async with lock:
                active_count -= 1
            semaphore.release()
            return False

    # Capture the real asyncio.sleep before patching it out on the dashboard
    # module — dashboard_module.asyncio *is* the asyncio module (not a copy),
    # so patching its "sleep" attribute affects every caller in the process,
    # including these fakes themselves if they called asyncio.sleep directly.
    real_sleep = asyncio.sleep

    monkeypatch.setattr(dashboard_module, "AsyncSessionLocal", TrackedSession)

    async def fake_get_summary(_session):
        await real_sleep(0)
        return {"ok": True}

    async def fake_sleep(_seconds):
        await real_sleep(0)

    monkeypatch.setattr(dashboard_module.dashboard_service, "get_summary", fake_get_summary)
    monkeypatch.setattr(dashboard_module.asyncio, "sleep", fake_sleep)

    async def run_stream_iterations(n: int):
        response = await dashboard_module.stream(_user=object())
        body_iterator = response.body_iterator
        for _ in range(n):
            await body_iterator.__anext__()
        await body_iterator.aclose()

    async def ordinary_request():
        async with TrackedSession():
            await real_sleep(0)
        return "ordinary-request-ok"

    stream_tasks = [asyncio.create_task(run_stream_iterations(3)) for _ in range(5)]
    ordinary_task = asyncio.create_task(ordinary_request())

    results = await asyncio.wait_for(asyncio.gather(*stream_tasks, ordinary_task), timeout=5)

    assert results[-1] == "ordinary-request-ok"
    assert max_concurrent <= pool_capacity
