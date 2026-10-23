# M&M Austin Limousine — agent fleet protocol

This repo is worked by a **standing fleet of always-on domain agents** orchestrated by Orca.
Every agent reads this file on startup. Follow it exactly.

## Your identity
You are **one domain agent**. Your lane (the paths you own + what you may touch) is defined in
[`docs/agents/domains.md`](docs/agents/domains.md). On startup, find your entry by your handle
(e.g. `@pricing-engine`) and work **only inside your paths**.

- A change that needs another lane → **do not edit it**. Message that lane's owner (or the
  coordinator) and record the interface in `CONTRACTS.md`.
- When unsure what you own or where code lives → **query the graph first** (see below).

## Graph-first (graphify MCP, read-only)
Before grepping or guessing, use the `graphify` MCP tools to locate and understand code:
`query_graph`, `get_node`, `get_neighbors`, `shortest_path`, `god_nodes`, `get_community`.
The graph is **read-only** and is rebuilt after every merge — never assume you can write to it.

## Branches & worktrees (Orca-managed)
- Each task runs in its **own git worktree + branch** (`agent/<domain>/<short-task>`), created
  from `origin/main`. Never commit directly to `main`.
- Rebase `main` into your branch before you start a task and before you hand off.

## The merge gate (autonomous on green)
A branch merges to `main` **only** when BOTH verifiers pass:
1. **code-verifier** — `backend` tests + `frontend` typecheck/build + `/code-review` clean.
2. **business-verifier** — the affected flow actually works (runs the app, exercises it).

On both-green, **repo-manager** merges, then **rebuilds the graph** (`graphify --update` +
`docker compose -f docker-compose.graphify.yml restart`) and **re-runs the suite on `main`**;
if `main` goes red it **auto-reverts** the merge and reopens the task. No human step unless a
verifier escalates.

## Shared memory
- **`BLACKBOARD.md`** — live, in-flight coordination (who's doing what, findings, blockers).
  Append-only per agent; keep entries short and dated.
- **`CONTRACTS.md`** — durable cross-agent interface decisions (e.g. "`quote()` now returns X").
  Update it the moment your change affects another lane's inputs/outputs.
- Orca inbox/tasks/gates carry the rest of coordination.

## Idle behaviour
When you have no task, **park on your inbox** (`orca orchestration check --wait`). Stay alive;
act when messaged by the coordinator, another agent, or the user.

## Standing rules
- **Audit before editing**: analyse + propose; make no edits until the task is confirmed.
- Never touch secrets. `.env`, `backend/.env`, `frontend/.env.local`, `.secrets/` are gitignored —
  never commit or print them. Scan every diff for secrets before pushing.
- Document build/behaviour changes in `docs/app-architecture.html` (map + endpoint ref + §13
  changelog) in the same task.

## Dev environment (local Docker)
- App stack: `docker compose up` (db :3307, Django :8000, Next :3000).
- Graph MCP: `docker compose -f docker-compose.graphify.yml up -d`.
- Backend tests: `docker compose exec backend pytest`. Frontend: `cd frontend && npm run build`.
