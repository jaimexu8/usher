import logging
from datetime import datetime, timezone

from discord.ext import commands

from ..coc_client import parse_coc_time, remaining_attacks, CoCApiError

log = logging.getLogger(__name__)


class WarCog(commands.Cog, name="War"):
    """Commands for viewing current war information."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="war")
    async def war(self, ctx):
        """Show the current war status: time left and who still has attacks."""
        cfg = await self.bot.db.get_guild_config(ctx.guild.id)
        if cfg is None or not cfg.clan_tag:
            await ctx.send(
                f"No clan configured. Ask an admin to run `{self.bot.config.command_prefix}setclan #CLANTAG`."
            )
            return

        try:
            war_data = await self.bot.coc.get_current_war(cfg.clan_tag)
        except CoCApiError as e:
            await ctx.send(f"Error fetching war data from CoC API: {e}")
            return

        if not war_data:
            await ctx.send("Could not retrieve war data (war log may be private).")
            return

        state = war_data.get("state")

        if state == "notInWar":
            await ctx.send("The clan is not currently in a war.")
            return

        clan = war_data.get("clan", {})
        opponent = war_data.get("opponent", {})
        clan_name = clan.get("name", cfg.clan_tag)
        opp_name = opponent.get("name", "Opponent")
        attacks_per_member = war_data.get("attacksPerMember", 2)
        team_size = war_data.get("teamSize", "?")

        if state == "preparation":
            start_str = war_data.get("startTime", "")
            if start_str:
                start_dt = parse_coc_time(start_str)
                now = datetime.now(timezone.utc)
                remaining = start_dt - now
                total_secs = int(remaining.total_seconds())
                if total_secs > 0:
                    h, rem = divmod(total_secs, 3600)
                    m, _ = divmod(rem, 60)
                    time_str = f"War starts in **{h}h {m}m**"
                else:
                    time_str = "War is starting soon"
            else:
                time_str = "War is in preparation"
            await ctx.send(
                f"**{clan_name}** vs **{opp_name}** ({team_size}v{team_size})\n{time_str}"
            )
            return

        if state not in ("inWar", "warEnded"):
            await ctx.send(f"War state: `{state}`")
            return

        end_str = war_data.get("endTime", "")
        time_str = ""
        if end_str:
            end_dt = parse_coc_time(end_str)
            now = datetime.now(timezone.utc)
            remaining = end_dt - now
            total_secs = int(remaining.total_seconds())
            if state == "inWar" and total_secs > 0:
                h, rem = divmod(total_secs, 3600)
                m, _ = divmod(rem, 60)
                time_str = f"**{h}h {m}m remaining**"
            elif state == "warEnded" or total_secs <= 0:
                time_str = "**War has ended**"

        # Clan scores
        clan_stars = clan.get("stars", 0)
        opp_stars = opponent.get("stars", 0)
        clan_dest = clan.get("destructionPercentage", 0.0)
        opp_dest = opponent.get("destructionPercentage", 0.0)

        lines = [
            f"**{clan_name}** vs **{opp_name}** ({team_size}v{team_size})",
            f"{time_str}",
            "",
            f"**{clan_name}:** ⭐ {clan_stars} | 💥 {clan_dest:.1f}%",
            f"**{opp_name}:** ⭐ {opp_stars} | 💥 {opp_dest:.1f}%",
        ]

        # Players with remaining attacks
        clan_members = clan.get("members", [])
        players_remaining = [
            m for m in clan_members if remaining_attacks(m, attacks_per_member) > 0
        ]

        if state == "inWar":
            lines.append("")
            if players_remaining:
                lines.append(f"**Players with attacks remaining ({len(players_remaining)}):**")
                for member in players_remaining:
                    tag = member["tag"].upper()
                    name = member.get("name", tag)
                    rem = remaining_attacks(member, attacks_per_member)
                    lines.append(f"• {name} `{tag}` — {rem} attack(s)")
            else:
                lines.append("All players have used their attacks!")

        await ctx.send("\n".join(lines))
