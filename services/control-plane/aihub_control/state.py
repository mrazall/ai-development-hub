from .models import SessionStatus

TRANSITIONS = {
    SessionStatus.queued: {SessionStatus.starting, SessionStatus.offline, SessionStatus.failed},
    SessionStatus.starting: {SessionStatus.running, SessionStatus.offline, SessionStatus.failed},
    SessionStatus.running: {
        SessionStatus.waiting_approval,
        SessionStatus.blocked,
        SessionStatus.completed,
        SessionStatus.failed,
        SessionStatus.offline,
    },
    SessionStatus.waiting_approval: {
        SessionStatus.running,
        SessionStatus.blocked,
        SessionStatus.failed,
        SessionStatus.offline,
    },
    SessionStatus.blocked: {SessionStatus.running, SessionStatus.failed, SessionStatus.offline},
    # An agent may finish while a late heartbeat has it marked offline.
    SessionStatus.offline: {SessionStatus.starting, SessionStatus.running, SessionStatus.completed, SessionStatus.failed},
    SessionStatus.failed: set(),
    SessionStatus.completed: set(),
}


def validate_transition(old: str, new: str):
    if old == new:
        return
    if SessionStatus(new) not in TRANSITIONS.get(SessionStatus(old), set()):
        raise ValueError(f"invalid session transition: {old} -> {new}")
