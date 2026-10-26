from aihub_control.tickets import consume, issue, owner_for


def test_stream_ticket_is_single_use_and_bound_to_user():
    ticket, ttl = issue("user-a")
    assert ttl == 60
    assert owner_for(ticket) == "user-a"
    assert not consume(ticket, "user-b")
    # A wrong owner must not consume a valid ticket.
    assert consume(ticket, "user-a")
    assert not consume(ticket, "user-a")


def test_stream_ticket_owner_is_not_available_after_expiry(monkeypatch):
    ticket, _ = issue("user-a")
    from aihub_control import tickets
    from datetime import datetime, timedelta, timezone

    digest = tickets.hashlib.sha256(ticket.encode()).hexdigest()
    tickets._tickets[digest] = ("user-a", datetime.now(timezone.utc) - timedelta(seconds=1))
    assert owner_for(ticket) is None
