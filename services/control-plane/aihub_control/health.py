"""System health: one list of checks for the «Здоровье системы» page and the failure notifications."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx2 as httpx
from sqlalchemy import func, select

from .config import Settings
from .models import AccountLimit, AccountProfile, BackupSnapshot, Notification, Session, Worker
from .orchestration.notifications import notify_users

ORDER = {"ok": 0, "unknown": 1, "warning": 2, "critical": 3}
CATEGORY = "system.health"
DATABASE_RPO = timedelta(hours=26)


def _check(key: str, title: str, status: str, summary: str, details: list[str] | None = None) -> dict:
    return {"key": key, "title": title, "status": status, "summary": summary, "details": details or []}


def _age(moment: datetime | None, now: datetime) -> str:
    if not moment:
        return "никогда"
    seconds = int((now - moment).total_seconds())
    if seconds < 120:
        return f"{seconds} с назад"
    if seconds < 7200:
        return f"{seconds // 60} мин назад"
    if seconds < 172800:
        return f"{seconds // 3600} ч назад"
    return f"{seconds // 86400} дн назад"


def check_workers(db, now: datetime) -> dict:
    workers = db.scalars(select(Worker).order_by(Worker.id)).all()
    if not workers:
        return _check("workers", "Воркеры", "unknown", "воркеры не зарегистрированы")
    details, offline = [], []
    for worker in workers:
        alive = worker.status == "online" and worker.last_heartbeat_at and (
            now - worker.last_heartbeat_at
        ).total_seconds() <= max(worker.lease_ttl_s, 60) * 2
        if not alive:
            offline.append(worker.id)
        details.append(f"{worker.id}: {'в сети' if alive else 'не в сети'}, сигнал {_age(worker.last_heartbeat_at, now)}")
    if not offline:
        return _check("workers", "Воркеры", "ok", f"все в сети ({len(workers)})", details)
    status = "critical" if len(offline) == len(workers) else "warning"
    return _check("workers", "Воркеры", status, f"не в сети: {', '.join(offline)}", details)


def check_tailscale(settings: Settings) -> dict:
    socket = settings.tailscale_socket.strip()
    if not socket:
        return _check("tailscale", "Tailscale", "unknown", "не настроено (AIHUB_TAILSCALE_SOCKET)")
    if not os.path.exists(socket):
        # Not shared with the hub (yet): no data rather than a false alarm.
        return _check("tailscale", "Tailscale", "unknown", "сокет tailscaled не подключён к хабу", [socket])
    try:
        transport = httpx.HTTPTransport(uds=socket)
        with httpx.Client(transport=transport, timeout=5) as client:
            data = client.get("http://local-tailscaled.sock/localapi/v0/status").json()
    except (httpx.HTTPError, OSError, ValueError) as exc:
        return _check("tailscale", "Tailscale", "critical", "демон не отвечает", [type(exc).__name__])
    me = data.get("Self") or {}
    state = data.get("BackendState")
    health = [str(item) for item in data.get("Health") or []]
    details = [f"состояние: {state}", f"узел: {me.get('HostName')} {', '.join(me.get('TailscaleIPs') or [])}",
               f"relay: {me.get('Relay') or '—'}", *health]
    if state != "Running":
        return _check("tailscale", "Tailscale", "critical", f"не подключён ({state})", details)
    if not me.get("Online"):
        return _check("tailscale", "Tailscale", "warning", "нет связи с координацией Tailscale", details)
    return _check("tailscale", "Tailscale", "warning" if health else "ok", "в сети" if not health else "в сети, есть предупреждения", details)


def check_limits(db, now: datetime) -> dict:
    rows = db.execute(
        select(AccountLimit, AccountProfile.name).join(AccountProfile, AccountProfile.id == AccountLimit.account_id)
    ).all()
    if not rows:
        return _check("limits", "Лимиты аккаунтов", "unknown", "данных о лимитах нет")
    details, hot = [], []
    for row, name in rows:
        window = "5 ч" if row.kind == "five_hour" else "неделя"
        resets = (
            datetime.fromtimestamp(row.resets_at, timezone.utc).astimezone().strftime("%d.%m %H:%M")
            if row.resets_at else "—"
        )
        details.append(f"{name} · {window}: {round(row.used_percent)}% (сброс {resets})")
        if row.used_percent >= 90:
            hot.append(f"{name} {window} {round(row.used_percent)}%")
    if not hot:
        return _check("limits", "Лимиты аккаунтов", "ok", "запас есть у всех аккаунтов", details)
    return _check("limits", "Лимиты аккаунтов", "warning", "почти исчерпаны: " + ", ".join(hot), details)


def check_knowledge(settings: Settings) -> dict:
    base = settings.knowledge_url.rstrip("/")
    try:
        health = httpx.get(f"{base}/health", timeout=5)
        index = httpx.get(f"{base}/index/status", timeout=5).json() if health.is_success else {}
    except (httpx.HTTPError, ValueError) as exc:
        return _check("knowledge", "Индекс знаний", "critical", "сервис знаний недоступен", [type(exc).__name__])
    if not health.is_success:
        return _check("knowledge", "Индекс знаний", "critical", f"сервис знаний: {health.status_code}")
    state = health.json()
    details = [
        f"документов: {index.get('documents', '?')}, фрагментов: {index.get('chunks', '?')}",
        f"модель: {index.get('model', '?')}, база: {index.get('vault', '?')}, векторы: {state.get('qdrant')}",
    ]
    problems = []
    if state.get("qdrant") != "ok":
        problems.append("векторный поиск недоступен")
    if index.get("vault") not in (None, "ok"):
        problems.append("база заметок недоступна")
    if index.get("errors"):
        problems.append(f"ошибок индексации: {index['errors']}")
        if index.get("last_error"):
            details.append(f"последняя: {index['last_error']}")
    if index.get("last_backend_error"):
        details.append(f"эмбеддинги: {index['last_backend_error']}")
    if not problems:
        return _check("knowledge", "Индекс знаний", "ok", "работает", details)
    return _check("knowledge", "Индекс знаний", "warning", "; ".join(problems), details)


def check_backups(db, now: datetime) -> dict:
    rows = db.scalars(select(BackupSnapshot).order_by(BackupSnapshot.started_at.desc())).all()
    if not rows:
        return _check("backups", "Бэкапы", "warning", "бэкапов ещё не было")
    details, problems = [], []
    for kind in sorted({row.kind for row in rows}):
        latest_ok = next((row for row in rows if row.kind == kind and row.ok), None)
        latest = next(row for row in rows if row.kind == kind)
        finished = latest_ok.finished_at if latest_ok else None
        details.append(f"{kind}: успешный {_age(finished, now)}" + ("" if latest.ok else ", последний с ошибкой"))
        if not latest_ok or (kind == "database" and finished and now - finished > DATABASE_RPO):
            problems.append(f"{kind}: нет свежего успешного")
        elif not latest.ok:
            problems.append(f"{kind}: последний с ошибкой")
    if not problems:
        return _check("backups", "Бэкапы", "ok", "свежие", details)
    critical = any(item.startswith("database") for item in problems)
    return _check("backups", "Бэкапы", "critical" if critical else "warning", "; ".join(problems), details)


def check_errors(db, now: datetime) -> dict:
    since = now - timedelta(hours=24)
    failed = db.scalars(
        select(Session).where(Session.status == "failed", Session.updated_at >= since).order_by(Session.updated_at.desc())
    ).all()
    critical = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.severity == "critical", Notification.created_at >= since, Notification.category != CATEGORY,
        )
    ) or 0
    details = [f"{_age(item.updated_at, now)} · {item.title or item.engine} ({item.project_id})" for item in failed[:8]]
    if not failed and not critical:
        return _check("errors", "Ошибки за сутки", "ok", "упавших сессий нет")
    summary = f"упавших сессий: {len(failed)}" + (f", критичных уведомлений: {critical}" if critical else "")
    return _check("errors", "Ошибки за сутки", "warning", summary, details)


def collect(db) -> dict:
    settings = Settings()
    now = datetime.now(timezone.utc)
    checks = [
        check_workers(db, now),
        check_tailscale(settings),
        check_limits(db, now),
        check_knowledge(settings),
        check_backups(db, now),
        check_errors(db, now),
    ]
    overall = max((item["status"] for item in checks), key=lambda value: ORDER[value])
    return {"status": overall, "checked_at": now, "checks": checks}


# The «errors» check is itself about notifications; everything else notifies on a change of state.
NOTIFIED = {"workers", "tailscale", "limits", "knowledge", "backups"}


def notify_changes(db, report: dict) -> int:
    """«Сбой: X» when a check turns warning/critical, «Восстановлено: X» when it is ok again.
    The previous state is the latest health notification for that check, so restarts do not repeat it."""
    sent = 0
    for item in report["checks"]:
        if item["key"] not in NOTIFIED or item["status"] == "unknown":
            continue
        latest = db.scalar(
            select(Notification.title).where(
                Notification.category == CATEGORY, Notification.body.like(f"[{item['key']}]%"),
            ).order_by(Notification.created_at.desc()).limit(1)
        )
        failing_before = bool(latest and latest.startswith("Сбой"))
        failing_now = item["status"] in ("warning", "critical")
        if failing_now and not failing_before:
            notify_users(db, CATEGORY, f"Сбой: {item['title']}", f"[{item['key']}] {item['summary']}",
                         severity="critical" if item["status"] == "critical" else "warning")
            sent += 1
        elif failing_before and not failing_now:
            notify_users(db, CATEGORY, f"Восстановлено: {item['title']}", f"[{item['key']}] {item['summary']}")
            sent += 1
    db.commit()
    return sent
