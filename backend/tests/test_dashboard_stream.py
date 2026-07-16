import inspect

import pytest

from app.api.v1 import dashboard as dashboard_module


def test_stream_endpoint_has_no_long_lived_db_dependency():
    sig = inspect.signature(dashboard_module.stream)
    assert "db" not in sig.parameters


@pytest.mark.asyncio
async def test_stream_opens_and_closes_a_fresh_session_each_iteration(monkeypatch):
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
        # The session passed in must be the one just opened for this
        # iteration, and it must not have been closed yet by the caller.
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
    # The session used for the first iteration must already be closed
    # before the next iteration's data is produced — no session may stay
    # open for the lifetime of the stream.
    assert closed == [1]
    assert '"iteration": 1' in first_chunk

    second_chunk = await body_iterator.__anext__()
    assert closed == [1, 2]
    assert '"iteration": 2' in second_chunk

    assert opened == [1, 2]

    await body_iterator.aclose()
