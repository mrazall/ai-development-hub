# Architecture

The **hub** (control plane + web panel) keeps projects, sessions and the event log. **Workers** run on the
machines where agent CLIs are installed and logged in; they poll the hub, run sessions and stream events back.

- Memory: this vault, indexed for hybrid search (full text + vectors).
- Orchestration: an orchestrator session splits a task, starts executors on branches, then merges.

See also [[Decisions/0001 Use a worker per machine]].
