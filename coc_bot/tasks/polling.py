import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from ..coc_client import parse_coc_time, remaining_attacks, make_war_id, CoCApiError
from ..database import GuildConfig

log = logging.getLogger(__name__)

# Map CoC API state strings to internal state names
COC_STATE_MAP = {
    "preparation": "PREP",
    "inWar": "IN_WAR",
    "warEnded": "ENDED",
}


class PollingCog(commands.Cog):
    """Background polling loop for war reminders and summaries."""

    def __init__(self, bot):
        self.bot = bot
        self._polling_loop.change_interval(seconds=bot.config.poll_interval)
        self._polling_loop.start()

    def cog_unload(self):
        self._polling_loop.cancel()

    @tasks.loop(seconds=120)
    async def _polling_loop(self):
        try:
            await self._run_poll()
        except Exception as e:
            log.exception("Unhandled error in polling loop: %s", e)

    @_polling_loop.before_loop
    async def _before_loop(self):
        await self.bot.wait_until_ready()
        log.info("Polling loop starting (interval=%ss)", self.bot.config.poll_interval)

    # ------------------------------------------------------------------
    # Main poll entry point
    # ------------------------------------------------------------------

    async def _run_poll(self):
        configs = await self.bot.db.get_all_guild_configs()
        for cfg in configs:
            if not cfg.clan_tag:
                continue
            try:
                await self._process_guild(cfg)
            except Exception as e:
                log.error("Error processing guild %s: %s", cfg.guild_id, e, exc_info=True)

    async def _process_guild(self, cfg: GuildConfig):
        try:
            war_data = await self.bot.coc.get_current_war(cfg.clan_tag)
        except CoCApiError as e:
            log.warning("CoC API error for guild %s clan %s: %s", cfg.guild_id, cfg.clan_tag, e)
            return

        if not war_data:
            return

        state_raw = war_data.get("state", "")
        if state_raw == "notInWar":
            return

        internal_state = COC_STATE_MAP.get(state_raw, state_raw)
        war_id = make_war_id(cfg.clan_tag, war_data)
        end_time_str = war_data.get("endTime")

        await self.bot.db.upsert_war(cfg.guild_id, war_id, internal_state, end_time_str)

        if internal_state == "IN_WAR":
            await self._process_reminders(cfg, war_data, war_id, end_time_str)
        elif internal_state == "ENDED":
            await self._process_war_end(cfg, war_data, war_id)

        # Always check capital raids
        await self._process_capital(cfg)

    # ------------------------------------------------------------------
    # Reminder logic
    # ------------------------------------------------------------------

    async def _process_reminders(
        self, cfg: GuildConfig, war_data: dict, war_id: str, end_time_str: str
    ):
        if not cfg.war_channel_id:
            return
        if not end_time_str:
            return

        end_dt = parse_coc_time(end_time_str)
        now = datetime.now(timezone.utc)
        minutes_until_end = (end_dt - now).total_seconds() / 60

        attacks_per_member = war_data.get("attacksPerMember", 2)
        clan_members = war_data.get("clan", {}).get("members", [])

        for threshold in cfg.reminder_thresholds:
            if minutes_until_end > threshold:
                # Not yet time for this threshold
                continue

            # Check which players at this threshold have already been reminded
            already_reminded = await self.bot.db.get_reminded_player_tags(
                cfg.guild_id, war_id, threshold
            )

            players_needing_reminder = [
                m for m in clan_members
                if remaining_attacks(m, attacks_per_member) > 0
                and m["tag"].upper() not in already_reminded
            ]

            if not players_needing_reminder:
                continue

            await self._send_reminder(cfg, war_id, players_needing_reminder, threshold, attacks_per_member)

    async def _send_reminder(
        self,
        cfg: GuildConfig,
        war_id: str,
        members: list,
        threshold_minutes: int,
        attacks_per_member: int,
    ):
        channel = self.bot.get_channel(int(cfg.war_channel_id))
        if channel is None:
            log.warning("War channel %s not found for guild %s", cfg.war_channel_id, cfg.guild_id)
            return

        if threshold_minutes >= 60 and threshold_minutes % 60 == 0:
            threshold_human = f"{threshold_minutes // 60}h"
        else:
            threshold_human = f"{threshold_minutes}m"

        lines = [f"⏰ **War reminder — {threshold_human} left**", ""]
        lines.append("The following players still have attacks remaining:")
        lines.append("")

        tags_reminded = []
        for member in members:
            tag = member["tag"].upper()
            name = member.get("name", tag)
            rem = remaining_attacks(member, attacks_per_member)
            link = await self.bot.db.get_link_by_player_tag(cfg.guild_id, tag)
            if link:
                display_name = link.nickname or name
                lines.append(f"<@{link.discord_user_id}> ({display_name} `{tag}`) — {rem} attack(s)")
            else:
                lines.append(f"{name} `{tag}` — {rem} attack(s)")
            tags_reminded.append(tag)

        try:
            await channel.send("\n".join(lines))
            log.info(
                "Sent %s-threshold reminder for war %s in guild %s (%d players)",
                threshold_human, war_id, cfg.guild_id, len(tags_reminded),
            )
        except discord.DiscordException as e:
            log.error("Failed to send reminder to channel %s: %s", cfg.war_channel_id, e)
            return

        # Persist reminders as sent
        await self.bot.db.add_reminders_sent(cfg.guild_id, war_id, tags_reminded, threshold_minutes)

    # ------------------------------------------------------------------
    # War end summary
    # ------------------------------------------------------------------

    async def _process_war_end(self, cfg: GuildConfig, war_data: dict, war_id: str):
        war_record = await self.bot.db.get_war(cfg.guild_id, war_id)
        if war_record and war_record.summary_posted:
            return  # Already posted

        results_channel_id = cfg.effective_results_channel()
        if not results_channel_id:
            log.info("No results channel configured for guild %s, skipping war summary", cfg.guild_id)
            await self.bot.db.mark_war_summary_posted(cfg.guild_id, war_id)
            return

        channel = self.bot.get_channel(int(results_channel_id))
        if channel is None:
            log.warning("Results channel %s not found for guild %s", results_channel_id, cfg.guild_id)
            await self.bot.db.mark_war_summary_posted(cfg.guild_id, war_id)
            return

        message = self._build_war_summary(war_data, cfg.clan_tag)
        try:
            await channel.send(message)
            log.info("Posted war summary for war %s in guild %s", war_id, cfg.guild_id)
        except discord.DiscordException as e:
            log.error("Failed to send war summary to channel %s: %s", results_channel_id, e)
            return

        await self.bot.db.mark_war_summary_posted(cfg.guild_id, war_id)

    def _build_war_summary(self, war_data: dict, clan_tag: str) -> str:
        clan = war_data.get("clan", {})
        opponent = war_data.get("opponent", {})
        clan_name = clan.get("name", clan_tag)
        opp_name = opponent.get("name", "Opponent")
        team_size = war_data.get("teamSize", "?")
        attacks_per_member = war_data.get("attacksPerMember", 2)

        clan_stars = clan.get("stars", 0)
        opp_stars = opponent.get("stars", 0)
        clan_dest = clan.get("destructionPercentage", 0.0)
        opp_dest = opponent.get("destructionPercentage", 0.0)

        # Determine result
        if clan_stars > opp_stars:
            result = "**Victory!** 🏆"
        elif clan_stars < opp_stars:
            result = "**Defeat** 😞"
        elif clan_dest > opp_dest:
            result = "**Victory! (tiebreaker — destruction)** 🏆"
        elif clan_dest < opp_dest:
            result = "**Defeat (tiebreaker — destruction)** 😞"
        else:
            result = "**Tie** 🤝"

        lines = [
            f"⚔️ **War Result — {clan_name} vs {opp_name}** ({team_size}v{team_size})",
            "",
            result,
            "",
            f"**{clan_name}:** ⭐ {clan_stars} | 💥 {clan_dest:.1f}%",
            f"**{opp_name}:** ⭐ {opp_stars} | 💥 {opp_dest:.1f}%",
        ]

        # Missed attacks
        clan_members = clan.get("members", [])
        missed = [m for m in clan_members if remaining_attacks(m, attacks_per_member) > 0]
        if missed:
            lines.append("")
            lines.append(f"**Missed attacks ({len(missed)} players):**")
            for member in missed:
                name = member.get("name", member["tag"])
                rem = remaining_attacks(member, attacks_per_member)
                lines.append(f"• {name} `{member['tag']}` — missed {rem} attack(s)")
        else:
            lines.append("")
            lines.append("All attacks were used! 💪")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Capital raid summaries
    # ------------------------------------------------------------------

    async def _process_capital(self, cfg: GuildConfig):
        capital_channel_id = cfg.effective_capital_channel()
        if not capital_channel_id:
            return

        try:
            data = await self.bot.coc.get_capital_raid_seasons(cfg.clan_tag)
        except CoCApiError as e:
            log.warning("Capital API error for guild %s: %s", cfg.guild_id, e)
            return

        if not data:
            return

        items = data.get("items", [])
        if not items:
            return

        # Most recent season is first
        latest = items[0]
        state = latest.get("state", "")
        end_time_str = latest.get("endTime", "")

        if state != "ended" or not end_time_str:
            return

        already_posted = await self.bot.db.is_capital_season_posted(cfg.guild_id, end_time_str)
        if already_posted:
            return

        channel = self.bot.get_channel(int(capital_channel_id))
        if channel is None:
            log.warning("Capital channel %s not found for guild %s", capital_channel_id, cfg.guild_id)
            await self.bot.db.mark_capital_season_posted(cfg.guild_id, end_time_str)
            return

        message = self._build_capital_summary(latest)
        try:
            await channel.send(message)
            log.info("Posted capital summary for guild %s (season end %s)", cfg.guild_id, end_time_str)
        except discord.DiscordException as e:
            log.error("Failed to send capital summary: %s", e)
            return

        await self.bot.db.mark_capital_season_posted(cfg.guild_id, end_time_str)

    def _build_capital_summary(self, season: dict) -> str:
        total_loot = season.get("capitalTotalLoot", 0)
        raids_completed = season.get("raidsCompleted", 0)
        total_attacks = season.get("totalAttacks", 0)
        enemy_districts = season.get("enemyDistrictsDestroyed", 0)
        members = season.get("members", [])

        lines = [
            "🏰 **Clan Capital Raid Weekend Summary**",
            "",
            f"**Total Capital Gold Looted:** {total_loot:,}",
            f"**Raids Completed:** {raids_completed}",
            f"**Total Attacks Used:** {total_attacks}",
            f"**Enemy Districts Destroyed:** {enemy_districts}",
        ]

        if members:
            lines.append("")
            lines.append(f"**Participants ({len(members)}):**")
            # Sort by capital resources looted descending
            sorted_members = sorted(members, key=lambda m: m.get("capitalResourcesLooted", 0), reverse=True)
            for member in sorted_members[:20]:  # Show top 20
                name = member.get("name", member.get("tag", "?"))
                loot = member.get("capitalResourcesLooted", 0)
                attacks = member.get("attacks", 0)
                lines.append(f"• {name} — {loot:,} gold, {attacks} attack(s)")
            if len(members) > 20:
                lines.append(f"… and {len(members) - 20} more")

        return "\n".join(lines)
