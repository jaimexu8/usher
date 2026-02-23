import os
from dataclasses import dataclass


@dataclass
class Config:
    discord_token: str
    coc_api_token: str
    command_prefix: str
    log_level: str
    sqlite_path: str
    poll_interval: int  # seconds


def load_config() -> Config:
    discord_token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not discord_token:
        raise ValueError("DISCORD_TOKEN environment variable is required")

    coc_api_token = os.environ.get("COC_API_TOKEN", "").strip()
    if not coc_api_token:
        raise ValueError("COC_API_TOKEN environment variable is required")

    poll_interval = int(os.environ.get("POLL_INTERVAL", "120"))

    return Config(
        discord_token=discord_token,
        coc_api_token=coc_api_token,
        command_prefix=os.environ.get("COMMAND_PREFIX", "!"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        sqlite_path=os.environ.get("SQLITE_PATH", "/app/data/bot.db"),
        poll_interval=poll_interval,
    )
