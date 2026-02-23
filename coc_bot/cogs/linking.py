import logging

from discord.ext import commands

from ..coc_client import normalize_tag, CoCApiError

log = logging.getLogger(__name__)


class LinkingCog(commands.Cog, name="Linking"):
    """Commands for linking Discord accounts to CoC player tags."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="link")
    async def link(self, ctx, player_tag: str, nickname: str = None):
        """Link your Discord account to a CoC player tag. Optional nickname for display.

        Example: !link #ABC123
                 !link #ABC123 Main
        """
        player_tag = normalize_tag(player_tag)

        # Optionally verify player exists via CoC API
        try:
            player_data = await self.bot.coc.get_player(player_tag)
            if player_data is None:
                await ctx.send(f"Player tag `{player_tag}` not found in CoC. Double-check the tag and try again.")
                return
            player_name = player_data.get("name", player_tag)
        except CoCApiError as e:
            # If API is down or error, allow linking anyway but warn
            log.warning("Could not validate player %s: %s", player_tag, e)
            player_name = player_tag
            await ctx.send(f"Note: couldn't verify tag with CoC API right now, but I'll link it anyway.")

        is_new = await self.bot.db.add_user_link(
            ctx.guild.id,
            ctx.author.id,
            player_tag,
            nickname,
        )

        display = f"`{player_name}` (`{player_tag}`)"
        nick_str = f" (nickname: **{nickname}**)" if nickname else ""
        if is_new:
            await ctx.send(f"Linked {display}{nick_str} to your Discord account.")
        else:
            await ctx.send(f"Updated link for {display}{nick_str}.")

    @commands.command(name="unlink")
    async def unlink(self, ctx, player_tag: str):
        """Unlink a CoC player tag from your Discord account.

        Example: !unlink #ABC123
        """
        player_tag = normalize_tag(player_tag)
        removed = await self.bot.db.remove_user_link(ctx.guild.id, ctx.author.id, player_tag)
        if removed:
            await ctx.send(f"Unlinked `{player_tag}` from your account.")
        else:
            await ctx.send(f"No link found for `{player_tag}` on your account.")

    @commands.command(name="unlinkall")
    async def unlinkall(self, ctx):
        """Remove all CoC tags linked to your Discord account."""
        count = await self.bot.db.remove_all_user_links(ctx.guild.id, ctx.author.id)
        if count > 0:
            await ctx.send(f"Removed {count} linked account(s).")
        else:
            await ctx.send("You have no linked accounts to remove.")

    @commands.command(name="links")
    async def links(self, ctx):
        """List your currently linked CoC accounts."""
        linked = await self.bot.db.get_user_links(ctx.guild.id, ctx.author.id)
        if not linked:
            await ctx.send(f"You have no linked accounts. Use `{self.bot.config.command_prefix}link #PLAYERTAG` to add one.")
            return

        lines = [f"**Your linked accounts ({len(linked)}):**"]
        for lnk in linked:
            nick_str = f" — *{lnk.nickname}*" if lnk.nickname else ""
            lines.append(f"• `{lnk.player_tag}`{nick_str}")
        await ctx.send("\n".join(lines))
