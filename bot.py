"""
anh-decision-bot — Discord dynamic UI for the decision ledger.
Phase 2a: list views (!decisions, !blockers, !cabs) with ephemeral embeds.
Phase 2b: action buttons (Expected/Fixed/Accepted Risk/Escalate) + multi-select batch.
"""

import os
import sys
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from dotenv import load_dotenv

# psycopg2 installed in venv at /mnt/nas/software/code/anh/.venv
sys.path.insert(0, "/mnt/nas/software/code/anh/.venv/lib/python3.11/site-packages")

import psycopg2
from psycopg2.extras import RealDictCursor

log = logging.getLogger(__name__)

# ── Mock data (Phase 2a — used when Postgres is not yet deployed) ───────────────

MOCK_DECISIONS = [
    {
        "id": 1, "title": "esbuild CVE accepted as low risk",
        "kind": "risk_accepted", "created_at": "2026-06-12T10:00:00Z",
        "body_excerpt": "Upgraded to 0.28.1. Accept risk until next major release.",
        "related_decision_id": None,
    },
    {
        "id": 2, "title": "BLK-017: media-indexers orphan TOML wave — resolved",
        "kind": "fixed", "created_at": "2026-06-11T08:00:00Z",
        "body_excerpt": "Orphaned TOML wave cleaned up via sync_secrets.py fix.",
        "related_decision_id": None,
    },
]

MOCK_BLOCKERS = [
    {
        "id": 1, "title": "AlertManager → ai-ass webhook down since 2026-06-10",
        "severity": "high", "created_at": "2026-06-10T12:00:00Z",
        "body_excerpt": "CAB-A filed. Standalone infra fix in progress (Gilfoyle).",
    },
    {
        "id": 2, "title": "NAS clone drift on ai-ass (pre June-10 hard-rule remediation)",
        "severity": "medium", "created_at": "2026-06-09T09:00:00Z",
        "body_excerpt": "Local clones redirected to NAS. Drift resolved.",
    },
]

MOCK_CABS = [
    {
        "id": 1, "title": "Decision ledger build (4 tables, bot, FastAPI, agent retrain)",
        "phase": "2a", "status": "pending",
        "created_at": "2026-06-13T09:00:00Z",
        "body_excerpt": "10h build across Dinesh + Gilfoyle. See cab-decision-ledger-build.md",
    },
    {
        "id": 2, "title": "AlertManager webhook rebuild (CAB-2026-06-14-A)",
        "phase": "A", "status": "pending",
        "created_at": "2026-06-12T14:00:00Z",
        "body_excerpt": "Webhook endpoint on ai-ass returning 99.7% failure rate.",
    },
]

# ── Database ──────────────────────────────────────────────────────────────────

PG_HOST = os.getenv("PG_HOST", "10.87.1.14")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_DB   = os.getenv("PG_DB",   "anh_decisions")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASS = os.getenv("PG_PASS", "")

AUDIT_LOG_CHANNEL_ID = int(os.getenv("AUDIT_LOG_CHANNEL_ID", "0"))


def get_db():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB,
        user=PG_USER, password=PG_PASS,
        cursor_factory=RealDictCursor,
    )


def fetch_open_decisions(limit=20):
    """Return open decisions (no resolved_at), oldest first. Fall back to mock."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, title, kind, created_at, body_excerpt,
                           related_decision_id
                      FROM decisions
                     WHERE resolved_at IS NULL
                     ORDER BY created_at ASC
                     LIMIT %s
                """, (limit,))
                return cur.fetchall()
    except Exception:
        log.warning("Postgres unavailable — returning mock decisions")
        return MOCK_DECISIONS[:limit]


def fetch_open_blockers(limit=20):
    """Return open blockers. Fall back to mock."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, title, severity, created_at, body_excerpt
                      FROM blockers
                     WHERE resolved_at IS NULL
                     ORDER BY created_at ASC
                     LIMIT %s
                """, (limit,))
                return cur.fetchall()
    except Exception:
        log.warning("Postgres unavailable — returning mock blockers")
        return MOCK_BLOCKERS[:limit]


def fetch_open_cabs(limit=20):
    """Return open CABs. Fall back to mock."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, title, phase, status, created_at, body_excerpt
                      FROM cabs
                     WHERE status NOT IN ('approved', 'rejected', 'withdrawn')
                     ORDER BY created_at ASC
                     LIMIT %s
                """, (limit,))
                return cur.fetchall()
    except Exception:
        log.warning("Postgres unavailable — returning mock CABs")
        return MOCK_CABS[:limit]


def write_decision(target_id: int, target_type: str, kind: str, actor: str) -> dict:
    """
    INSERT into decisions + audit_log in one transaction.
    target_type: 'alert' | 'blocker' | 'cab'
    kind: 'expected' | 'fixed' | 'risk_accepted' | 'escalated'
    Returns the new decision row.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO decisions (target_id, target_type, kind, resolved_by, resolved_at)
                VALUES (%s, %s, %s, %s, NOW())
                RETURNING id, target_id, target_type, kind, resolved_by, resolved_at
            """, (target_id, target_type, kind, actor))
            decision = cur.fetchone()

            cur.execute("""
                INSERT INTO audit_log (action, table_name, record_id, actor, details)
                VALUES ('INSERT', 'decisions', %s, %s,
                        ('{"kind":"' || %s || '","target_id":' || %s || ',"target_type":"' || %s || '"}')::jsonb)
                RETURNING id
            """, (decision["id"], actor, kind, str(target_id), target_type))
            audit_row = cur.fetchone()

            conn.commit()
            return decision, audit_row


def revoke_decision(decision_id: int, actor: str) -> bool:
    """Delete a decision + log it. Only for decisions < 1h old."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM decisions
                 WHERE id = %s
                   AND resolved_at > NOW() - interval '1 hour'
                   AND resolved_by = %s
                RETURNING id
            """, (decision_id, actor))
            deleted = cur.fetchone()
            if deleted:
                cur.execute("""
                    INSERT INTO audit_log (action, table_name, record_id, actor, details)
                    VALUES ('DELETE', 'decisions', %s, %s,
                            ('{"revoked":true}')::jsonb)
                """, (decision_id, actor))
                conn.commit()
                return True
            conn.rollback()
            return False


# ── Formatters ─────────────────────────────────────────────────────────────

KIND_EMOJI = {
    "expected":      "🔔 Expected",
    "fixed":        "✅ Fixed",
    "risk_accepted":"⚠️ Accepted Risk",
    "escalated":    "📣 Escalated",
}

KIND_COLOR = {
    "expected":      0xFFA500,
    "fixed":        0x00FF00,
    "risk_accepted": 0xFF4500,
    "escalated":    0xFF0000,
}


def age_string(dt) -> str:
    if dt is None:
        return "unknown"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = delta.total_seconds()
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds/60)}m ago"
    if seconds < 86400:
        return f"{int(seconds/3600)}h ago"
    return f"{int(seconds/86400)}d ago"


def decision_to_embed(row, index) -> discord.Embed:
    kind = row.get("kind", "open")
    color = KIND_COLOR.get(kind, 0x7289DA)
    embed = discord.Embed(
        title=f"{index}. {row['title']}",
        color=color,
    )
    embed.add_field(name="Type", value=kind or "open", inline=True)
    embed.add_field(name="Age", value=age_string(row["created_at"]), inline=True)
    if row.get("body_excerpt"):
        embed.add_field(name="Excerpt", value=row["body_excerpt"][:200], inline=False)
    embed.add_field(name="ID", value=f"`{row['id']}`", inline=True)
    return embed


def blocker_to_embed(row, index) -> discord.Embed:
    embed = discord.Embed(
        title=f"{index}. {row['title']}",
        color=0xFF4500,
    )
    embed.add_field(name="Severity", value=row.get("severity", "?"), inline=True)
    embed.add_field(name="Age", value=age_string(row["created_at"]), inline=True)
    if row.get("body_excerpt"):
        embed.add_field(name="Excerpt", value=row["body_excerpt"][:200], inline=False)
    embed.add_field(name="ID", value=f"`{row['id']}`", inline=True)
    return embed


def cab_to_embed(row, index) -> discord.Embed:
    embed = discord.Embed(
        title=f"{index}. {row['title']}",
        color=0x9B59B6,
    )
    embed.add_field(name="Phase", value=row.get("phase", "?"), inline=True)
    embed.add_field(name="Status", value=row.get("status", "?"), inline=True)
    embed.add_field(name="Age", value=age_string(row["created_at"]), inline=True)
    if row.get("body_excerpt"):
        embed.add_field(name="Excerpt", value=row["body_excerpt"][:200], inline=False)
    embed.add_field(name="ID", value=f"`{row['id']}`", inline=True)
    return embed


# ── Views (Phase 2b) ────────────────────────────────────────────────────────

class DecisionListView(discord.ui.View):
    """List view: rows with Details button; multi-select at bottom."""

    def __init__(self, rows, row_type, target_type, *, timeout=300):
        super().__init__(timeout=timeout)
        self.rows = rows
        self.row_type = row_type
        self.target_type = target_type

        # Row buttons — Details per row
        for i, row in enumerate(rows):
            btn = DetailsButton(row, row_type, target_type, index=i)
            self.add_item(btn)

        # Multi-select for batch action
        if len(rows) > 1:
            options = [
                discord.SelectOption(
                    label=f"#{i+1} — {r['title'][:80]}",
                    value=str(r["id"]),
                )
                for i, r in enumerate(rows)
            ]
            select = BatchSelect(options, row_type, target_type)
            self.add_item(select)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class DetailsButton(discord.ui.Button):
    """Tap → ephemeral edit showing full context + action buttons."""

    def __init__(self, row, row_type, target_type, index):
        self.row = row
        self.row_type = row_type
        self.target_type = target_type
        label = f"#{index+1} Details"
        super().__init__(label=label, style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        row = self.row
        actor = interaction.user.display_name

        # Build detail embed
        if self.row_type == "decision":
            embed = decision_to_embed(row, 0)
        elif self.row_type == "blocker":
            embed = blocker_to_embed(row, 0)
        else:
            embed = cab_to_embed(row, 0)

        embed.title = f"Details — {row['title']}"
        if row.get("body_excerpt"):
            embed.description = row["body_excerpt"]

        view = ActionView(row, self.row_type, self.target_type, actor)
        await interaction.response.send_message(
            embed=embed, view=view, ephemeral=True
        )


class BatchSelect(discord.ui.Select):
    """Multi-select → choose rows → then pick action."""

    def __init__(self, options, row_type, target_type):
        self.row_type = row_type
        self.target_type = target_type
        super().__init__(
            placeholder="Select rows for batch action…",
            min_values=1,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        actor = interaction.user.display_name
        selected_ids = [int(v) for v in self.values]

        # Re-fetch to be safe — can't trust message custom data in Discord.py
        if self.row_type == "decision":
            all_rows = fetch_open_decisions(limit=50)
        elif self.row_type == "blocker":
            all_rows = fetch_open_blockers(limit=50)
        else:
            all_rows = fetch_open_cabs(limit=50)
        rows_map = {r["id"]: r for r in all_rows}
        selected_rows = [rows_map[i] for i in selected_ids if i in rows_map]

        view = BatchActionView(selected_rows, self.row_type, self.target_type, actor)
        embed = discord.Embed(
            title=f"Batch: {len(selected_rows)} row(s) selected",
            color=0x7289DA,
        )
        for i, r in enumerate(selected_rows):
            embed.add_field(
                name=f"#{i+1}",
                value=f"**{r['title']}**\nID: `{r['id']}`",
                inline=False,
            )
        await interaction.response.send_message(
            embed=embed, view=view, ephemeral=True
        )


class ActionView(discord.ui.View):
    """Action buttons on a detail view."""

    def __init__(self, row, row_type, target_type, actor):
        super().__init__(timeout=300)
        self.row = row
        self.row_type = row_type
        self.target_type = target_type
        self.actor = actor

        for kind, label in [
            ("expected",     "🔔 Expected"),
            ("fixed",        "✅ Fixed"),
            ("risk_accepted","⚠️ Accepted Risk"),
            ("escalated",    "📣 Escalate"),
        ]:
            self.add_item(ActionButton(kind, label, row, row_type, target_type, actor))

        # Revoke button (only show for recent decisions — check via message age)
        self.add_item(RevokeButton(row, row_type, target_type, actor))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class ActionButton(discord.ui.Button):
    def __init__(self, kind, label, row, row_type, target_type, actor):
        self.kind = kind
        self.row = row
        self.row_type = row_type
        self.target_type = target_type
        self.actor = actor
        style = {
            "expected":      discord.ButtonStyle.secondary,
            "fixed":        discord.ButtonStyle.success,
            "risk_accepted": discord.ButtonStyle.danger,
            "escalated":    discord.ButtonStyle.danger,
        }[kind]
        super().__init__(label=label, style=style)

    async def callback(self, interaction: discord.Interaction):
        row = self.row
        try:
            decision, audit = write_decision(
                target_id=row["id"],
                target_type=self.target_type,
                kind=self.kind,
                actor=self.actor,
            )
            embed = discord.Embed(
                title=f"✅ {KIND_EMOJI[self.kind]}",
                description=f"Decision recorded for **{row['title']}**\n"
                            f"Decision ID: `{decision['id']}`\n"
                            f"Actor: {self.actor}",
                color=KIND_COLOR[self.kind],
            )
            view = None
        except Exception as e:
            log.exception("Failed to write decision")
            embed = discord.Embed(
                title="❌ Write failed",
                description=f"Could not record decision: {e}",
                color=0xFF0000,
            )
            view = None

        await interaction.response.edit_message(embed=embed, view=view)


class RevokeButton(discord.ui.Button):
    def __init__(self, row, row_type, target_type, actor):
        self.row = row
        self.row_type = row_type
        self.target_type = target_type
        self.actor = actor
        super().__init__(
            label="🔄 Revoke",
            style=discord.ButtonStyle.danger,
        )

    async def callback(self, interaction: discord.Interaction):
        row = self.row
        ok = revoke_decision(row["id"], self.actor)
        if ok:
            embed = discord.Embed(
                title="🔄 Revoked",
                description=f"Decision `{row['id']}` has been revoked.",
                color=0x808080,
            )
        else:
            embed = discord.Embed(
                title="❌ Revoke failed",
                description="Only decisions < 1h old by the same actor can be revoked.",
                color=0xFF0000,
            )
        await interaction.response.edit_message(embed=embed, view=None)


class BatchActionView(discord.ui.View):
    """Batch action: one button per kind."""

    def __init__(self, rows, row_type, target_type, actor):
        super().__init__(timeout=300)
        self.rows = rows
        self.row_type = row_type
        self.target_type = target_type
        self.actor = actor

        for kind, label in [
            ("expected",     "🔔 Mark all Expected"),
            ("fixed",        "✅ Mark all Fixed"),
            ("risk_accepted","⚠️ Accept all Risk"),
            ("escalated",    "📣 Escalate all"),
        ]:
            self.add_item(BatchActionButton(kind, label, rows, row_type, target_type, actor))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class BatchActionButton(discord.ui.Button):
    def __init__(self, kind, label, rows, row_type, target_type, actor):
        self.kind = kind
        self.rows = rows
        self.row_type = row_type
        self.target_type = target_type
        self.actor = actor
        style = {
            "expected":      discord.ButtonStyle.secondary,
            "fixed":        discord.ButtonStyle.success,
            "risk_accepted": discord.ButtonStyle.danger,
            "escalated":    discord.ButtonStyle.danger,
        }[kind]
        super().__init__(label=label, style=style, row=1)

    async def callback(self, interaction: discord.Interaction):
        written = []
        errors = []
        for row in self.rows:
            try:
                d, a = write_decision(
                    target_id=row["id"],
                    target_type=self.target_type,
                    kind=self.kind,
                    actor=self.actor,
                )
                written.append(f"✅ `{d['id']}` — {row['title']}")
            except Exception as e:
                errors.append(f"❌ `{row['id']}` — {e}")

        color = KIND_COLOR[self.kind]
        embed = discord.Embed(
            title=f"Batch {KIND_EMOJI[self.kind]} — {len(written)} recorded",
            color=color,
        )
        for line in written:
            embed.add_field(name="\u200b", value=line, inline=False)
        if errors:
            for line in errors:
                embed.add_field(name="\u200b", value=line, inline=False)

        await interaction.response.edit_message(embed=embed, view=None)


# ── Bot ───────────────────────────────────────────────────────────────────────

class DecisionBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()


async def run_bot():
    load_dotenv()
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        log.error("DISCORD_BOT_TOKEN not set")
        sys.exit(1)

    bot = DecisionBot()

    # ── Commands ──────────────────────────────────────────────────────────

    @bot.tree.command(name="decisions", description="Open decisions (ephemeral)")
    async def cmd_decisions(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = fetch_open_decisions(limit=20)
        if not rows:
            embed = discord.Embed(
                title="No open decisions",
                color=0x7289DA,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Open Decisions ({len(rows)})",
            color=0x7289DA,
        )
        view = DecisionListView(rows, "decision", "alert")
        # Store rows on message for BatchSelect re-fetch
        msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        # We can't attach custom data to the message object, so re-fetch in callback
        # BatchSelect re-fetches from DB instead

    @bot.tree.command(name="blockers", description="Open blockers (ephemeral)")
    async def cmd_blockers(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = fetch_open_blockers(limit=20)
        if not rows:
            embed = discord.Embed(title="No open blockers", color=0xFF4500)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Open Blockers ({len(rows)})",
            color=0xFF4500,
        )
        view = DecisionListView(rows, "blocker", "blocker")
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @bot.tree.command(name="cabs", description="Open CABs (ephemeral)")
    async def cmd_cabs(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = fetch_open_cabs(limit=20)
        if not rows:
            embed = discord.Embed(title="No open CABs", color=0x9B59B6)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Open CABs ({len(rows)})",
            color=0x9B59B6,
        )
        view = DecisionListView(rows, "cab", "cab")
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    await bot.start(token, log_handler=None)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(run_bot())
