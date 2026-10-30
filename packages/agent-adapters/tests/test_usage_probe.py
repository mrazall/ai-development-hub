from datetime import datetime
from zoneinfo import ZoneInfo

from aihub_agents.usage_probe import parse_claude_usage, parse_codex_status, parse_reset

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 29, 15, 30, tzinfo=MSK)

# Screens as the CLIs rendered them (Claude Code 2.1.312 `/usage`, Codex 0.161.0 `/status`).
CLAUDE_USAGE = """
   Settings  Status   Config   Usage   Stats
   Session
   Total cost:            $0.0000
   Usage:                 0 input, 0 output, 0 cache read, 0 cache write
   Current session
   ██████████████████████████████████████             76% used
   Resets 5:49pm (Europe/Moscow)
   Current week (all models)
   ████████████████▌                                  33% used
   Resets Nov 4, 7:59pm (Europe/Moscow)
   Usage credits
"""

CODEX_STATUS = """
  Account:             Plus
  5h limit:            [████████████████████] 100% left (resets 8:57 PM)
  Weekly limit:        [██████████████████░░] 90% left (resets 12:31 PM on 4 Nov)
"""


def at(*args):
    return int(datetime(*args, tzinfo=MSK).timestamp())


def test_claude_usage_screen():
    assert parse_claude_usage(CLAUDE_USAGE, NOW) == [
        {"kind": "five_hour", "used_percent": 76.0, "resets_at": at(2026, 10, 29, 17, 49)},
        {"kind": "seven_day", "used_percent": 33.0, "resets_at": at(2026, 11, 4, 19, 59)},
    ]


def test_codex_status_screen():
    assert parse_codex_status(CODEX_STATUS, NOW) == [
        {"kind": "five_hour", "used_percent": 0.0, "resets_at": at(2026, 10, 29, 20, 57)},
        {"kind": "seven_day", "used_percent": 10.0, "resets_at": at(2026, 11, 4, 12, 31)},
    ]


def test_reset_times():
    assert parse_reset("7pm", NOW) == at(2026, 10, 29, 19, 0)
    assert parse_reset("9:15am", NOW) == at(2026, 10, 30, 9, 15)  # already passed today → tomorrow
    late_december = datetime(2026, 12, 30, 12, 0, tzinfo=MSK)
    assert parse_reset("Jan 2, 1:00pm", late_december) == at(2027, 1, 2, 13, 0)
    assert parse_reset("soon", NOW) is None
    # Codex in a 24-hour locale
    assert parse_reset("21:52", NOW) == at(2026, 10, 29, 21, 52)
    assert parse_reset("12:31 on 4 Nov", NOW) == at(2026, 11, 4, 12, 31)


def test_a_screen_without_limits_gives_nothing():
    assert parse_claude_usage("Welcome to Claude Code", NOW) == []
    assert parse_codex_status("› Ask Codex to do anything", NOW) == []


def test_limits_refresh_does_not_hold_the_worker_loop(monkeypatch):
    import asyncio

    from aihub_agents.worker import Worker

    worker = Worker("http://hub", "w", "token")
    started, release = asyncio.Event(), asyncio.Event()
    order = []

    async def slow_refresh(client, request):
        order.append(request["id"])
        started.set()
        await release.wait()

    async def next_request(*args, **kwargs):
        class Answer:
            is_success = True

            def __init__(self, body):
                self.body = body

            def json(self):
                return self.body

        return Answer(requests.pop(0))

    requests = [{"id": "r1", "kind": "limits_refresh"}, {"id": "r2", "kind": "limits_refresh"}]
    monkeypatch.setattr(worker, "_refresh_limits", slow_refresh)
    monkeypatch.setattr(worker, "_request", next_request)

    async def scenario():
        await asyncio.wait_for(worker.service_workspace_request(None), 1)  # returns at once
        await asyncio.wait_for(worker.service_workspace_request(None), 1)
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.sleep(0.05)
        assert order == ["r1"]  # the second waits for the first: one CLI at a time
        release.set()
        await asyncio.gather(*worker._background)
        assert order == ["r1", "r2"]

    asyncio.run(scenario())
