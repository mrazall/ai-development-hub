"""Settings the admin can change in the panel. The deployment env (Settings) is the default; a value saved
in the panel overrides it until reset. Bootstrap and security settings (database, secrets, CSP frame-src,
the Tailscale socket, the vault id prefix) stay env-only on purpose."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import select

from .config import Settings
from .models import SystemSetting

# key → description; `env` is the Settings attribute that gives the default.
REGISTRY: dict[str, dict[str, Any]] = {
    "public_url": {
        "env": "public_url", "kind": "url", "group": "Подключение",
        "label": "Адрес хаба для воркеров и агентов",
        "help": "По нему воркеры и MCP агентов обращаются к хабу. Неверный адрес оборвёт связь агентов с хабом.",
    },
    "worker_shell_hint": {
        "env": "worker_shell_hint", "kind": "text", "group": "Подключение",
        "label": "Как открыть терминал воркера",
        "help": "Команда в инструкциях по входу в CLI (например «wsl -d Ubuntu-24.04 -u dev»). Пусто — без команды.",
    },
    "chat_system_prompt": {
        "env": "chat_system_prompt", "kind": "textarea", "group": "Чаты",
        "label": "Системный промпт чатов",
        "help": "Добавляется к каждому личному чату. Пусто — встроенный нейтральный промпт.",
    },
    "chat_engine": {
        "env": "chat_engine", "kind": "choice", "group": "Чаты",
        "choices": ["claude_code", "mock_echo_prompt"],
        "label": "Движок чатов",
        "help": "claude_code — настоящий Claude; mock_echo_prompt — повторяет вопрос (демо и тесты, без подписки).",
    },
    "vault_worker_id": {
        "env": "vault_worker_id", "kind": "text", "group": "База знаний",
        "label": "Воркер для «Внести в базу»",
        "help": "ID воркера, на котором лежит копия базы Obsidian (git). Пусто — внесение черновиков выключено.",
    },
    "vault_workdir": {
        "env": "vault_workdir", "kind": "text", "group": "База знаний",
        "label": "Папка базы на этом воркере",
        "help": "Абсолютный путь к git-копии базы, где Sonnet вносит черновики.",
    },
    "vault_model": {
        "env": "vault_model", "kind": "text", "group": "База знаний",
        "label": "Модель для внесения черновиков",
        "help": "Например claude-sonnet-5-5.",
    },
    "obsidian_vault": {
        "env": "obsidian_vault", "kind": "text", "group": "База знаний",
        "label": "Имя хранилища Obsidian",
        "help": "Для кнопки «Открыть в Obsidian» — как хранилище называется в Obsidian на ваших устройствах. Пусто — кнопки нет.",
    },
    "health_interval_s": {
        "env": "health_interval_s", "kind": "int", "group": "Здоровье",
        "label": "Интервал проверок здоровья, секунд",
        "help": "Как часто проверять систему и слать уведомления о сбоях. 0 — выключено.",
    },
}


def _default(key: str) -> Any:
    return getattr(Settings(), REGISTRY[key]["env"])


def get_setting(db, key: str) -> Any:
    row = db.get(SystemSetting, key) if db is not None else None
    return row.value if row is not None else _default(key)


def validate(key: str, value: Any) -> Any:
    spec = REGISTRY.get(key)
    if not spec:
        raise HTTPException(404, "unknown setting")
    kind = spec["kind"]
    if kind == "int":
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, "нужно целое число") from exc
        if value < 0 or value > 86400:
            raise HTTPException(422, "от 0 до 86400")
        return value
    value = "" if value is None else str(value).strip()
    if len(value) > 20000:
        raise HTTPException(422, "слишком длинное значение")
    if kind == "url":
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(422, "нужен адрес вида https://hub.example.com")
        return value.rstrip("/")
    if kind == "choice" and value not in spec["choices"]:
        raise HTTPException(422, "значение не из списка")
    return value


def describe(db) -> list[dict]:
    rows = {row.key: row for row in db.scalars(select(SystemSetting))}
    return [
        {
            "key": key,
            **{name: spec[name] for name in ("kind", "group", "label", "help") if name in spec},
            "choices": spec.get("choices"),
            "value": rows[key].value if key in rows else _default(key),
            "default": _default(key),
            "source": "panel" if key in rows else "env",
            "updated_by": rows[key].updated_by if key in rows else None,
            "updated_at": rows[key].updated_at if key in rows else None,
        }
        for key, spec in REGISTRY.items()
    ]


def save(db, key: str, value: Any, username: str) -> None:
    value = validate(key, value)
    row = db.get(SystemSetting, key) or SystemSetting(key=key)
    row.value, row.updated_by, row.updated_at = value, username, datetime.now(timezone.utc)
    db.add(row)
    db.commit()


def reset(db, key: str) -> None:
    if key not in REGISTRY:
        raise HTTPException(404, "unknown setting")
    row = db.get(SystemSetting, key)
    if row is not None:
        db.delete(row)
        db.commit()
