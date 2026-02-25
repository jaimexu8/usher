import logging

import aiohttp
import discord
from discord.ext import commands

from .config import Config
from .database import Database
from .coc_client import CoCClient

log = logging.getLogger(__name__)


class UsherBot(commands.Bot):
    def __init__(self, config: Config, db: Database):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=config.command_prefix,
            intents=intents,
            help_command=commands.DefaultHelpCommand(),
        )
        self.config = config
        self.db = db
        self.coc: CoCClient = None  # initialized in setup_hook
        self._coc_session: aiohttp.ClientSession = None

    async def setup_hook(self) -> None:
        self._coc_session = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self.config.coc_api_token}"}
        )
        self.coc = CoCClient(self._coc_session)

        from .cogs.admin import AdminCog
        from .cogs.linking import LinkingCog
        from .cogs.war import WarCog
        from .tasks.polling import PollingCog

        await self.add_cog(AdminCog(self))
        await self.add_cog(LinkingCog(self))
        await self.add_cog(WarCog(self))
        await self.add_cog(PollingCog(self))

        log.info("All cogs loaded")

    async def close(self) -> None:
        if self._coc_session and not self._coc_session.closed:
            await self._coc_session.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id)
        log.info("Prefix: %s", self.config.command_prefix)
        if self.config.status_message:
            await self.change_presence(
                activity=discord.Game(name=self.config.status_message)
            )

    async def on_command_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing argument: `{error.param.name}`. See `{self.config.command_prefix}help {ctx.command}`.")
        elif isinstance(error, commands.CommandNotFound):
            pass  # Silently ignore unknown commands
        else:
            log.error("Unhandled command error in %s: %s", ctx.command, error, exc_info=error)
            await ctx.send("An unexpected error occurred. Check bot logs for details.")
