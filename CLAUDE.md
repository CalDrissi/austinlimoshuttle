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

## Coordinator
The **coordinator orchestrates only** — it dispatches work to the owning lane and relays results.
It does NOT make code edits, run builds, run docker, deploy, SSH, or debug-by-doing itself; all
hands-on work goes to the owning agent (or `@deploy` for ops, `@repo-manager` for releases).

## Graph-first (graphify MCP, read-only)
Before grepping or guessing, use the `graphify` MCP tools to locate and understand code:
`query_graph`, `get_node`, `get_neighbors`, `shortest_path`, `god_nodes`, `get_community`.
The graph is **read-only** and is rebuilt after every merge — never assume you can write to it.

This applies to the **coordinator** too, not only domain agents. Before grep/guess for "where does
X live / how does Y connect", query the graph. Check freshness first: `graph_stats` "Built at
commit" must match `origin/main`; if it's behind, the graph is missing recent code — repo-manager
rebuilds it (`graphify update .` + restart `docker-compose.graphify.yml`) before it is trusted.

## Branches & worktrees (Orca-managed)
- Each task runs in its **own git worktree + branch** (`agent/<domain>/<short-task>`), created
  from `origin/main`.
- Rebase `main` into your branch before you start a task and before you hand off.
- **Merge foundations sooner.** Prefer merging a verified foundation/independent branch to `main`
  promptly rather than stacking many branches off each other. Deep branch stacks make integration
  slow and conflict-prone — keep `main` the common base.

## Deploy workflow (owner decision 2026-11-25: NO merge gate)
The merge gate is **retired**. There are no blocking verifiers between a branch and `main`;
author diligence (run the tests you touched, `/code-review` your own diff) plus **periodic E2E
verification rounds** are the quality net — the coordinator schedules full app-exercising passes
and defects found there become immediate fix tasks.

Both app processes run **on the VPS host under pm2** (user `limoweb`); only **MariaDB stays in
Docker** (`limo-prod-db`, published to the host loopback on `127.0.0.1:3307` via
`docker-compose.db-hostport.yml` — always pass both `-f` files or the port mapping is lost).
Deploys are fast lanes, one script each, run as root on the VPS:
- **Frontend** — `scripts/deploy-frontend.sh`: pull → `npm ci` + `next build` as limoweb →
  pm2 reload `limo-frontend`. Build-before-restart: a failed build leaves the old app serving.
- **Backend** — `scripts/deploy-backend.sh`: pull → pip (only if requirements changed) →
  `manage.py check` → `migrate` → `collectstatic` → graceful gunicorn reload
  (`pm2 sendSignal SIGHUP limo-backend`) → smoke curl `/api/vehicles/` (non-200 exits 1).
  Any failure **before** the reload leaves the running app untouched.

Rollback: the last containerized backend (`limo-prod-backend` container + image) is kept stopped
on the VPS — `docker start limo-prod-backend` restores it on :8001 (stop the pm2 `limo-backend`
app first; both bind 127.0.0.1:8001).

Backend tests still exist (`docker compose exec backend pytest` in the dev stack, or
`ops/fast-test.sh`) — run them when you touch backend logic; they are no longer a merge
precondition. After a merge, **repo-manager rebuilds the graph** (`graphify --update` +
`docker compose -f docker-compose.graphify.yml restart`).

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
