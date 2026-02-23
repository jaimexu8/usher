import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

log = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id TEXT PRIMARY KEY,
    clan_tag TEXT,
    war_channel_id TEXT,
    results_channel_id TEXT,
    capital_channel_id TEXT,
    reminder_thresholds TEXT DEFAULT '[720, 180, 60]',
    timezone TEXT DEFAULT 'UTC',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    discord_user_id TEXT NOT NULL,
    player_tag TEXT NOT NULL,
    nickname TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(guild_id, player_tag)
);

CREATE TABLE IF NOT EXISTS wars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    war_id TEXT NOT NULL,
    state TEXT NOT NULL,
    end_time TEXT,
    summary_posted INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(guild_id, war_id)
);

CREATE TABLE IF NOT EXISTS reminders_sent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    war_id TEXT NOT NULL,
    player_tag TEXT NOT NULL,
    threshold_minutes INTEGER NOT NULL,
    sent_at TEXT DEFAULT (datetime('now')),
    UNIQUE(guild_id, war_id, player_tag, threshold_minutes)
);

CREATE TABLE IF NOT EXISTS capital_seasons_posted (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    season_end_time TEXT NOT NULL,
    UNIQUE(guild_id, season_end_time)
);
"""


@dataclass
class GuildConfig:
    guild_id: str
    clan_tag: Optional[str] = None
    war_channel_id: Optional[str] = None
    results_channel_id: Optional[str] = None
    capital_channel_id: Optional[str] = None
    reminder_thresholds: list = field(default_factory=lambda: [720, 180, 60])
    timezone: str = "UTC"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def effective_results_channel(self) -> Optional[str]:
        return self.results_channel_id or self.war_channel_id

    def effective_capital_channel(self) -> Optional[str]:
        return self.capital_channel_id or self.results_channel_id or self.war_channel_id


@dataclass
class UserLink:
    id: int
    guild_id: str
    discord_user_id: str
    player_tag: str
    nickname: Optional[str]
    created_at: str


@dataclass
class War:
    id: int
    guild_id: str
    war_id: str
    state: str
    end_time: Optional[str]
    summary_posted: bool
    created_at: str
    updated_at: str


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()
        log.info("Database initialized at %s", self.path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    # -------------------------------------------------------------------------
    # Guild config
    # -------------------------------------------------------------------------

    async def get_guild_config(self, guild_id: str) -> Optional[GuildConfig]:
        async with self._conn.execute(
            "SELECT * FROM guild_config WHERE guild_id = ?", (str(guild_id),)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return self._row_to_guild_config(row)

    async def get_all_guild_configs(self) -> list:
        async with self._conn.execute("SELECT * FROM guild_config") as cur:
            rows = await cur.fetchall()
        return [self._row_to_guild_config(r) for r in rows]

    async def upsert_guild_config(self, guild_id: str, **kwargs) -> GuildConfig:
        now = datetime.now(timezone.utc).isoformat()
        existing = await self.get_guild_config(guild_id)

        if existing is None:
            await self._conn.execute(
                "INSERT INTO guild_config (guild_id, updated_at) VALUES (?, ?)",
                (str(guild_id), now),
            )
            await self._conn.commit()
            existing = await self.get_guild_config(guild_id)

        updates = {}
        for k, v in kwargs.items():
            if k == "reminder_thresholds" and isinstance(v, list):
                updates[k] = json.dumps(v)
            else:
                updates[k] = v
        updates["updated_at"] = now

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [str(guild_id)]
            await self._conn.execute(
                f"UPDATE guild_config SET {set_clause} WHERE guild_id = ?", values
            )
            await self._conn.commit()

        return await self.get_guild_config(guild_id)

    def _row_to_guild_config(self, row) -> GuildConfig:
        thresholds_raw = row["reminder_thresholds"] or "[720, 180, 60]"
        try:
            thresholds = json.loads(thresholds_raw)
        except (json.JSONDecodeError, TypeError):
            thresholds = [720, 180, 60]
        return GuildConfig(
            guild_id=row["guild_id"],
            clan_tag=row["clan_tag"],
            war_channel_id=row["war_channel_id"],
            results_channel_id=row["results_channel_id"],
            capital_channel_id=row["capital_channel_id"],
            reminder_thresholds=thresholds,
            timezone=row["timezone"] or "UTC",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # -------------------------------------------------------------------------
    # User links
    # -------------------------------------------------------------------------

    async def get_user_links(self, guild_id: str, discord_user_id: str) -> list:
        async with self._conn.execute(
            "SELECT * FROM user_links WHERE guild_id = ? AND discord_user_id = ? ORDER BY created_at",
            (str(guild_id), str(discord_user_id)),
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_user_link(r) for r in rows]

    async def get_link_by_player_tag(self, guild_id: str, player_tag: str) -> Optional[UserLink]:
        async with self._conn.execute(
            "SELECT * FROM user_links WHERE guild_id = ? AND player_tag = ?",
            (str(guild_id), player_tag.upper()),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return self._row_to_user_link(row)

    async def add_user_link(
        self,
        guild_id: str,
        discord_user_id: str,
        player_tag: str,
        nickname: Optional[str] = None,
    ) -> bool:
        """Returns True if inserted, False if updated (overwrote an existing link)."""
        player_tag = player_tag.upper()
        existing = await self.get_link_by_player_tag(guild_id, player_tag)
        if existing and existing.discord_user_id == str(discord_user_id):
            # Update nickname only
            await self._conn.execute(
                "UPDATE user_links SET nickname = ? WHERE guild_id = ? AND player_tag = ?",
                (nickname, str(guild_id), player_tag),
            )
            await self._conn.commit()
            return False

        await self._conn.execute(
            """INSERT INTO user_links (guild_id, discord_user_id, player_tag, nickname)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(guild_id, player_tag)
               DO UPDATE SET discord_user_id = excluded.discord_user_id, nickname = excluded.nickname""",
            (str(guild_id), str(discord_user_id), player_tag, nickname),
        )
        await self._conn.commit()
        return existing is None  # True = new insert, False = overwrote

    async def remove_user_link(
        self, guild_id: str, discord_user_id: str, player_tag: str
    ) -> bool:
        player_tag = player_tag.upper()
        cur = await self._conn.execute(
            "DELETE FROM user_links WHERE guild_id = ? AND discord_user_id = ? AND player_tag = ?",
            (str(guild_id), str(discord_user_id), player_tag),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def remove_all_user_links(self, guild_id: str, discord_user_id: str) -> int:
        cur = await self._conn.execute(
            "DELETE FROM user_links WHERE guild_id = ? AND discord_user_id = ?",
            (str(guild_id), str(discord_user_id)),
        )
        await self._conn.commit()
        return cur.rowcount

    def _row_to_user_link(self, row) -> UserLink:
        return UserLink(
            id=row["id"],
            guild_id=row["guild_id"],
            discord_user_id=row["discord_user_id"],
            player_tag=row["player_tag"],
            nickname=row["nickname"],
            created_at=row["created_at"],
        )

    # -------------------------------------------------------------------------
    # Wars
    # -------------------------------------------------------------------------

    async def get_war(self, guild_id: str, war_id: str) -> Optional[War]:
        async with self._conn.execute(
            "SELECT * FROM wars WHERE guild_id = ? AND war_id = ?",
            (str(guild_id), war_id),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return self._row_to_war(row)

    async def upsert_war(
        self, guild_id: str, war_id: str, state: str, end_time: Optional[str]
    ) -> War:
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            """INSERT INTO wars (guild_id, war_id, state, end_time, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, war_id)
               DO UPDATE SET state = excluded.state, end_time = excluded.end_time,
                             updated_at = excluded.updated_at""",
            (str(guild_id), war_id, state, end_time, now),
        )
        await self._conn.commit()
        return await self.get_war(guild_id, war_id)

    async def mark_war_summary_posted(self, guild_id: str, war_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE wars SET summary_posted = 1, updated_at = ? WHERE guild_id = ? AND war_id = ?",
            (now, str(guild_id), war_id),
        )
        await self._conn.commit()

    def _row_to_war(self, row) -> War:
        return War(
            id=row["id"],
            guild_id=row["guild_id"],
            war_id=row["war_id"],
            state=row["state"],
            end_time=row["end_time"],
            summary_posted=bool(row["summary_posted"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # -------------------------------------------------------------------------
    # Reminders
    # -------------------------------------------------------------------------

    async def get_reminded_player_tags(
        self, guild_id: str, war_id: str, threshold_minutes: int
    ) -> set:
        async with self._conn.execute(
            "SELECT player_tag FROM reminders_sent WHERE guild_id = ? AND war_id = ? AND threshold_minutes = ?",
            (str(guild_id), war_id, threshold_minutes),
        ) as cur:
            rows = await cur.fetchall()
        return {r["player_tag"] for r in rows}

    async def add_reminders_sent(
        self,
        guild_id: str,
        war_id: str,
        player_tags: list,
        threshold_minutes: int,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.executemany(
            """INSERT OR IGNORE INTO reminders_sent
               (guild_id, war_id, player_tag, threshold_minutes, sent_at)
               VALUES (?, ?, ?, ?, ?)""",
            [(str(guild_id), war_id, tag.upper(), threshold_minutes, now) for tag in player_tags],
        )
        await self._conn.commit()

    # -------------------------------------------------------------------------
    # Capital seasons
    # -------------------------------------------------------------------------

    async def is_capital_season_posted(self, guild_id: str, season_end_time: str) -> bool:
        async with self._conn.execute(
            "SELECT 1 FROM capital_seasons_posted WHERE guild_id = ? AND season_end_time = ?",
            (str(guild_id), season_end_time),
        ) as cur:
            row = await cur.fetchone()
        return row is not None

    async def mark_capital_season_posted(self, guild_id: str, season_end_time: str) -> None:
        await self._conn.execute(
            "INSERT OR IGNORE INTO capital_seasons_posted (guild_id, season_end_time) VALUES (?, ?)",
            (str(guild_id), season_end_time),
        )
        await self._conn.commit()
