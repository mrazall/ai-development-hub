# Adding an engine

An engine is an agent CLI the worker can drive. Built in: `claude_code` (Claude Code, stream-JSON),
`codex` (Codex CLI, `exec --json`), and `mock*` engines for tests and demos. (`opencode` is detected on
workers but has no adapter yet — a good first engine to add.)

## The adapter contract

`packages/agent-adapters/aihub_agents/adapters.py`:

```python
class EngineAdapter:
    async def start(self) -> AsyncIterator[AgentEvent]: ...   # run, yield normalised events
    async def send(self, text: str) -> None: ...              # follow-up input (interactive engines)
    async def interrupt(self) -> None: ...                    # stop
```

Events (`AgentEvent(kind, payload, source)`) the panel understands:

| kind | payload |
|---|---|
| `session.status` | `status`: running / completed / failed; optional `engine_session_ref` (for resume), `context_tokens` |
| `message` | `role`, `text`; `partial: true` while streaming; `raw_type` from the CLI; `usage`, `cost_usd` on the final one |
| `tool.call` / `tool.result` | `name`, `command` / `exit_code`, `output` |
| `diff` | `changes: [{path, kind}]` |
| `output` | `text`, `stream` |

Most CLIs print JSON lines: subclass `_JsonLinesAdapter`, build the command line, and map each record in a
`normalize_*` function (see `normalize_codex_event`). Keep secrets out of events: payloads are redacted, but
don't rely on it.

## Wiring it in

1. Construct your adapter in `Worker.run_assignment` for its engine name.
2. Report it in `Worker.capabilities()` so the panel offers it for that worker.
3. Add the name to `--enable-engines` on workers that should run it.
4. Tests: a normalisation unit test with recorded output, and — if it changes user-visible behaviour — a
   scenario in `services/control-plane/tests/test_scenarios_integration.py` using a mock.
