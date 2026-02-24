import logging
from typing import Optional

import discord
from discord.ext import commands

from ..coc_client import normalize_tag, CoCApiError, is_valid_tag_format

log = logging.getLogger(__name__)

HANDLER_ROLE_NAME = "usher handler"


def _is_usher_manager(member: discord.Member) -> bool:
    """True if member can manage other users' links (admin or Usher Handler role)."""
    if member.guild_permissions.manage_guild:
        return True
    return any(r.name.lower() == HANDLER_ROLE_NAME for r in member.roles)


def _looks_like_user_ref(s: str) -> bool:
    """True if s looks like a Discord mention or user ID (so we don't treat it as a CoC tag)."""
    s = s.strip()
    if s.startswith("<@") and s.endswith(">"):
        return True
    return s.isdigit() and len(s) >= 17


def _extract_user_id(s: str) -> Optional[int]:
    """If s is a mention or Discord user ID, return the integer ID; else None."""
    s = s.strip()
    if s.startswith("<@") and s.endswith(">"):
        try:
            return int(s.replace("<@", "").replace("!", "").replace(">", ""))
        except ValueError:
            return None
    if s.isdigit() and len(s) >= 17:
        return int(s)
    return None


async def _parse_user_ref(guild: discord.Guild, s: str) -> Optional[discord.Member]:
    """If s is a mention or user ID, return the Member (from cache or API)."""
    uid = _extract_user_id(s)
    if uid is None:
        return None
    member = guild.get_member(uid)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(uid)
    except (discord.NotFound, discord.HTTPException):
        return None


async def _resolve_target(
    ctx: commands.Context, args: list[str]
) -> tuple[Optional[discord.Member], int, Optional[str]]:
    """
    If args[0] is a user ref (mention or uid), resolve to Member and require caller is usher manager.
    Return (target_member, num_args_consumed, error_message).
    If error_message is set, target is None and consumed is 0.
    """
    if not args:
        return (ctx.author, 0, None)
    first = args[0]
    member = await _parse_user_ref(ctx.guild, first)
    # If it looked like a user ref but we couldn't resolve, don't treat it as a CoC tag
    if _looks_like_user_ref(first) and member is None:
        return (
            None,
            0,
            "User not found. Make sure they're in this server or use a valid @mention / user ID.",
        )
    if member is None:
        return (ctx.author, 0, None)
    # First arg is a user ref; only admins / usher handlers can use it
    if not _is_usher_manager(ctx.author):
        return (None, 0, "Only server admins or Usher Handlers can manage another user's links.")
    return (member, 1, None)


class LinkingCog(commands.Cog, name="Linking"):
    """Commands for linking Discord accounts to CoC player tags."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="link")
    async def link(self, ctx, *args: str):
        """Link a Discord account to a CoC player tag. Admins can link for others.

        Examples:
          !link #ABC123
          !link #ABC123 Main
          !link @username #ABC123
          !link 123456789012345678 #ABC123
        """
        if not args:
            await ctx.send(
                f"Usage: `{ctx.prefix}link #TAG [nickname]` or "
                f"`{ctx.prefix}link @user #TAG [nickname]` (admin only)."
            )
            return

        target, consumed, err = await _resolve_target(ctx, list(args))
        if err:
            await ctx.send(err)
            return
        args = args[consumed:]

        if not args:
            await ctx.send("Please provide a player tag (e.g. `#ABC123`).")
            return

        player_tag = normalize_tag(args[0])
        nickname = args[1] if len(args) > 1 else None

        if not is_valid_tag_format(player_tag):
            await ctx.send(
                f"Invalid player tag format. CoC tags are 5–9 characters after # "
                f"(e.g. `#2PP`, `#ABC123`). Use only the allowed letters/numbers."
            )
            return

        # Verify player exists via CoC API
        try:
            player_data = await self.bot.coc.get_player(player_tag)
            if player_data is None:
                await ctx.send(f"Player tag `{player_tag}` not found in CoC. Double-check the tag and try again.")
                return
            player_name = player_data.get("name", player_tag)
        except CoCApiError as e:
            log.warning("Could not validate player %s: %s", player_tag, e)
            player_name = player_tag
            await ctx.send("Note: couldn't verify tag with CoC API right now, but I'll link it anyway.")

        is_new = await self.bot.db.add_user_link(
            ctx.guild.id,
            target.id,
            player_tag,
            nickname,
        )

        display = f"`{player_name}` (`{player_tag}`)"
        nick_str = f" (nickname: **{nickname}**)" if nickname else ""
        who_str = f" for **{target.display_name}**" if target.id != ctx.author.id else ""
        if is_new:
            await ctx.send(f"Linked {display}{nick_str} to {target.mention}'s account." if who_str else f"Linked {display}{nick_str} to your Discord account.")
        else:
            await ctx.send(f"Updated link for {display}{nick_str}{who_str}.")

    @commands.command(name="unlink")
    async def unlink(self, ctx, *args: str):
        """Unlink a CoC player tag from a Discord account. Admins can unlink for others.

        Examples: !unlink #ABC123   !unlink @username #ABC123   !unlink 123456789012345678 #ABC123
        """
        if not args:
            await ctx.send(f"Usage: `{ctx.prefix}unlink #TAG` or `{ctx.prefix}unlink @user #TAG` (admin only).")
            return

        target, consumed, err = await _resolve_target(ctx, list(args))
        if err:
            await ctx.send(err)
            return
        args = args[consumed:]

        if not args:
            await ctx.send("Please provide the player tag to unlink (e.g. `#ABC123`).")
            return

        player_tag = normalize_tag(args[0])

        if not is_valid_tag_format(player_tag):
            await ctx.send(f"Invalid player tag format. CoC tags are 5–9 characters after # (e.g. `#2PP`).")
            return

        removed = await self.bot.db.remove_user_link(ctx.guild.id, target.id, player_tag)
        who_str = f" for **{target.display_name}**" if target.id != ctx.author.id else ""
        if removed:
            await ctx.send(f"Unlinked `{player_tag}` from {target.mention}'s account." if who_str else f"Unlinked `{player_tag}` from your account.")
        else:
            await ctx.send(f"No link found for `{player_tag}` on {target.mention}'s account." if who_str else f"No link found for `{player_tag}` on your account.")

    @commands.command(name="unlinkall")
    async def unlinkall(self, ctx, *args: str):
        """Remove all CoC tags linked to a Discord account. Admins can run for others.

        Examples: !unlinkall   !unlinkall @username   !unlinkall 123456789012345678
        """
        target, consumed, err = await _resolve_target(ctx, list(args))
        if err:
            await ctx.send(err)
            return

        count = await self.bot.db.remove_all_user_links(ctx.guild.id, target.id)
        who_str = f" for **{target.display_name}**" if target.id != ctx.author.id else ""
        if count > 0:
            await ctx.send(f"Removed {count} linked account(s){who_str}.")
        else:
            await ctx.send(f"No linked accounts to remove{who_str}." if who_str else "You have no linked accounts to remove.")

    @commands.command(name="links")
    async def links(self, ctx, *args: str):
        """List linked CoC accounts for yourself or another user (admin only for others).

        Examples: !links   !links @username   !links 123456789012345678
        """
        target, consumed, err = await _resolve_target(ctx, list(args))
        if err:
            await ctx.send(err)
            return

        linked = await self.bot.db.get_user_links(ctx.guild.id, target.id)
        who_str = f"**{target.display_name}'s**" if target.id != ctx.author.id else "Your"
        if not linked:
            await ctx.send(
                f"{who_str} linked accounts: none. Use `{self.bot.config.command_prefix}link #PLAYERTAG` to add one."
            )
            return

        lines = [f"{who_str} linked accounts ({len(linked)}):"]
        for lnk in linked:
            nick_str = f" — *{lnk.nickname}*" if lnk.nickname else ""
            lines.append(f"• `{lnk.player_tag}`{nick_str}")
        await ctx.send("\n".join(lines))
