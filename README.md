# anh-decision-bot

Discord bot for the decision ledger. Ephemeral list views + dynamic action UI for Aaron's suppressions and decisions.

## Components

- **Bot** (`bot.py`) — Discord.py, psycopg2-binary. Primary write path for decisions.
- **API** (`api/`) — FastAPI + asyncpg. Read-only layer for agents.

## Deploy

Via Komodo on `anh-docker01`:

```bash
komodo deploy decision-bot    # bot
komodo deploy decision-api     # FastAPI read layer
```

Both share `DECISION_PG_*` variables from 1Password vault `anh`.

## Bot Commands

| Command | Description |
|---------|-------------|
| `/decisions` | Open decisions (ephemeral embed) |
| `/blockers` | Open blockers (ephemeral embed) |
| `/cabs` | Open CABs (ephemeral embed) |

Each list row has a **Details** button → action buttons (Expected/Fixed/Accepted Risk/Escalate) + batch multi-select.

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_BOT_TOKEN` | — | Bot token from Discord Developer Portal |
| `PG_HOST` | `10.87.1.14` | Postgres host (backupbox LXC 100) |
| `PG_PORT` | `5432` | Postgres port |
| `PG_DB` | `anh_decisions` | Database name |
| `PG_USER` | `postgres` | DB user |
| `PG_PASS` | — | DB password (1Password) |

## Architecture

- Bot writes to `decisions` + `audit_log` in a single transaction (psycopg2)
- API reads via asyncpg pool with read-only PG role (Phase 3)
- Both connect to Postgres on backupbox (`10.87.1.14:5432`)
- Agents query API for suppression decisions (Phase 4)
