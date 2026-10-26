---
type: decision
status: accepted
---
# 0001: Use a worker per machine

Agents run where their tools and logins live, so each machine runs one worker that talks to the hub over HTTPS.
The hub never needs credentials of the agent accounts. Context: [[Architecture]].
