import json
import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands

from ..coc_client import normalize_tag, CoCApiError
from ..database import GuildConfig

log = logging.getLogger(__name__)

HANDLER_ROLE_NAME = "usher handler"


def is_usher_manager():
    """Allow server admins (manage_guild) OR members with the 'Usher Handler' role."""
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.guild_permissions.manage_guild:
            return True
        if any(r.name.lower() == HANDLER_ROLE_NAME for r in ctx.author.roles):
            return True
        raise commands.MissingPermissions(["manage_guild"])
    return commands.check(predicate)


def parse_duration_minutes(s: str) -> int:
    """Parse '12h', '30m', or plain integer string into minutes."""
    s = s.strip().lower()
    if s.endswith("h"):
        return int(s[:-1]) * 60
    elif s.endswith("m"):
        return int(s[:-1])
    else:
        return int(s)


class AdminCog(commands.Cog, name="Admin"):
    """Server admin commands for configuring the bot."""

    def __init__(self, bot):
        self.bot = bot

    async def _require_config(self, ctx) -> Optional[GuildConfig]:
        cfg = await self.bot.db.get_guild_config(ctx.guild.id)
        if cfg is None or not cfg.clan_tag:
            await ctx.send(
                f"No clan configured yet. Use `{self.bot.config.command_prefix}setclan #CLANTAG` first."
            )
            return None
        return cfg

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @commands.command(name="setclan")
    @is_usher_manager()
    async def setclan(self, ctx, clan_tag: str):
        """Set the clan tag to monitor (admin only)."""
        clan_tag = normalize_tag(clan_tag)
        await ctx.send(f"Validating clan tag `{clan_tag}` with CoC API...")
        try:
            war_data = await self.bot.coc.get_current_war(clan_tag)
        except CoCApiError as e:
            if e.status == 0:
                await ctx.send(f"Network error reaching CoC API: {e}")
                return
            # 403 means private war log — the clan exists but log is private; that's OK
            war_data = None

        # If we get here without error, clan exists (or war log is private)
        await self.bot.db.upsert_guild_config(ctx.guild.id, clan_tag=clan_tag)
        await ctx.send(f"Clan set to `{clan_tag}`.")

    @commands.command(name="setwarchannel")
    @is_usher_manager()
    async def setwarchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel for war attack reminders (admin only)."""
        await self.bot.db.upsert_guild_config(ctx.guild.id, war_channel_id=str(channel.id))
        await ctx.send(f"War reminder channel set to {channel.mention}.")

    @commands.command(name="setresultschannel")
    @is_usher_manager()
    async def setresultschannel(self, ctx, channel: discord.TextChannel):
        """Set the channel for war result summaries (admin only)."""
        await self.bot.db.upsert_guild_config(ctx.guild.id, results_channel_id=str(channel.id))
        await ctx.send(f"War results channel set to {channel.mention}.")

    @commands.command(name="setcapitalchannel")
    @is_usher_manager()
    async def setcapitalchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel for clan capital raid summaries (admin only)."""
        await self.bot.db.upsert_guild_config(ctx.guild.id, capital_channel_id=str(channel.id))
        await ctx.send(f"Capital raid channel set to {channel.mention}.")

    @commands.command(name="setreminders")
    @is_usher_manager()
    async def setreminders(self, ctx, *thresholds: str):
        """Set reminder thresholds (e.g. !setreminders 12h 3h 1h) (admin only)."""
        if not thresholds:
            await ctx.send("Provide at least one threshold, e.g. `12h 3h 1h`.")
            return
        try:
            parsed = sorted([parse_duration_minutes(t) for t in thresholds], reverse=True)
        except ValueError:
            await ctx.send("Invalid threshold format. Use e.g. `12h`, `3h`, `90m`, or plain minutes like `720`.")
            return
        await self.bot.db.upsert_guild_config(ctx.guild.id, reminder_thresholds=parsed)
        human = ", ".join(
            (f"{m // 60}h" if m % 60 == 0 else f"{m}m") for m in parsed
        )
        await ctx.send(f"Reminder thresholds set to: {human}.")

    @commands.command(name="status")
    @is_usher_manager()
    async def status(self, ctx):
        """Show bot config and current war state (admin only)."""
        cfg = await self.bot.db.get_guild_config(ctx.guild.id)
        if cfg is None:
            await ctx.send("Bot not yet configured for this server.")
            return

        lines = ["**Bot Status**", ""]
        lines.append(f"**Clan:** `{cfg.clan_tag or 'not set'}`")

        war_ch = self.bot.get_channel(int(cfg.war_channel_id)) if cfg.war_channel_id else None
        res_ch = self.bot.get_channel(int(cfg.results_channel_id)) if cfg.results_channel_id else None
        cap_ch = self.bot.get_channel(int(cfg.capital_channel_id)) if cfg.capital_channel_id else None

        lines.append(f"**War channel:** {war_ch.mention if war_ch else '`not set`'}")
        lines.append(f"**Results channel:** {res_ch.mention if res_ch else '`not set (falls back to war channel)`'}")
        lines.append(f"**Capital channel:** {cap_ch.mention if cap_ch else '`not set (falls back to results/war channel)`'}")

        thresholds_human = ", ".join(
            (f"{m // 60}h" if m % 60 == 0 else f"{m}m") for m in cfg.reminder_thresholds
        )
        lines.append(f"**Reminder thresholds:** {thresholds_human}")
        lines.append(f"**Poll interval:** {self.bot.config.poll_interval}s")

        if cfg.clan_tag:
            try:
                war_data = await self.bot.coc.get_current_war(cfg.clan_tag)
                if war_data:
                    state = war_data.get("state", "unknown")
                    end_time_str = war_data.get("endTime")
                    if end_time_str and state == "inWar":
                        from ..coc_client import parse_coc_time
                        end_dt = parse_coc_time(end_time_str)
                        now = datetime.now(timezone.utc)
                        remaining = end_dt - now
                        total_secs = int(remaining.total_seconds())
                        if total_secs > 0:
                            h, rem = divmod(total_secs, 3600)
                            m, s = divmod(rem, 60)
                            lines.append(f"**Current war:** {state} — **{h}h {m}m** remaining")
                        else:
                            lines.append(f"**Current war:** {state} (ended)")
                    else:
                        lines.append(f"**Current war:** {state}")
                else:
                    lines.append("**Current war:** not in war")
            except Exception as e:
                lines.append(f"**Current war:** error fetching ({e})")

        await ctx.send("\n".join(lines))

    @commands.command(name="testreminder")
    @is_usher_manager()
    async def testreminder(self, ctx):
        """Preview what a reminder message would look like (no pings sent) (admin only)."""
        cfg = await self._require_config(ctx)
        if cfg is None:
            return

        try:
            war_data = await self.bot.coc.get_current_war(cfg.clan_tag)
        except Exception as e:
            await ctx.send(f"Error fetching war data: {e}")
            return

        if not war_data or war_data.get("state") not in ("inWar", "preparation"):
            await ctx.send("No active or preparation war found.")
            return

        state = war_data.get("state")
        attacks_per_member = war_data.get("attacksPerMember", 2)
        clan_members = war_data.get("clan", {}).get("members", [])

        from ..coc_client import remaining_attacks
        players_with_attacks = [
            m for m in clan_members if remaining_attacks(m, attacks_per_member) > 0
        ]

        if not players_with_attacks:
            await ctx.send("All clan members have used their attacks (or no war data).")
            return

        lines = ["**[TEST — no pings] War reminder preview**", ""]
        lines.append("The following players still have attacks remaining:")
        lines.append("")
        for member in players_with_attacks:
            tag = member["tag"].upper()
            name = member.get("name", tag)
            rem = remaining_attacks(member, attacks_per_member)
            link = await self.bot.db.get_link_by_player_tag(ctx.guild.id, tag)
            if link:
                lines.append(f"<@{link.discord_user_id}> ({name} `{tag}`) — {rem} attack(s) left [**TEST, not sent**]")
            else:
                lines.append(f"{name} `{tag}` — {rem} attack(s) left")

        await ctx.send("\n".join(lines))
