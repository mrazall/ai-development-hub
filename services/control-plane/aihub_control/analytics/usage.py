"""Shared usage normalization and pricing."""
from __future__ import annotations

USAGE_EVENTS = ("result", "turn.completed")
TOKEN_KINDS = ("input", "cache_read", "cache_write", "output")


def parse_prices(value: str | None) -> dict[str, tuple[float, float, float]]:
    """`model=input,cached,output` per line, USD per million tokens (cache writes are priced as input)."""
    prices: dict[str, tuple[float, float, float]] = {}
    for line in (value or "").splitlines():
        name, sep, numbers = line.partition("=")
        parts = [part.strip() for part in numbers.split(",")]
        if not sep or not name.strip() or len(parts) != 3:
            continue
        try:
            prices[name.strip()] = (float(parts[0]), float(parts[1]), float(parts[2]))
        except ValueError:
            continue
    return prices


def normalize(engine: str, usage: dict) -> dict[str, int]:
    def number(key: str) -> int:
        try:
            return max(int(usage.get(key) or 0), 0)
        except (TypeError, ValueError):
            return 0

    if engine == "codex":  # input_tokens already includes the cached part
        cached = number("cached_input_tokens")
        return {"input": max(number("input_tokens") - cached, 0), "cache_read": cached,
                "cache_write": number("cache_write_input_tokens"), "output": number("output_tokens")}
    return {"input": number("input_tokens"), "cache_read": number("cache_read_input_tokens"),
            "cache_write": number("cache_creation_input_tokens"), "output": number("output_tokens")}


def price_of(tokens: dict[str, int], price: tuple[float, float, float]) -> float:
    fresh, cached, output = price
    return ((tokens["input"] + tokens["cache_write"]) * fresh + tokens["cache_read"] * cached
            + tokens["output"] * output) / 1_000_000


