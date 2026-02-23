import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

BASE_URL = "https://api.clashofclans.com/v1"


def normalize_tag(tag: str) -> str:
    tag = tag.strip().upper()
    if not tag.startswith("#"):
        tag = "#" + tag
    return tag


def encode_tag(tag: str) -> str:
    return normalize_tag(tag).replace("#", "%23")


def parse_coc_time(time_str: str) -> datetime:
    """Parse CoC API timestamp (e.g. '20250101T120000.000Z') into UTC datetime."""
    return datetime.strptime(time_str, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)


def remaining_attacks(member: dict, attacks_per_member: int) -> int:
    used = len(member.get("attacks", []))
    return max(0, attacks_per_member - used)


def make_war_id(clan_tag: str, war_data: dict) -> str:
    """Derive a stable unique ID for a war from CoC data."""
    prep = war_data.get("preparationStartTime", "UNKNOWN")
    return f"{normalize_tag(clan_tag)}_{prep}"


class CoCApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"CoC API error {status}: {message}")


class CoCClient:
    def __init__(self, session: aiohttp.ClientSession):
        self._session = session

    async def _get(self, path: str) -> Optional[dict]:
        url = f"{BASE_URL}{path}"
        try:
            async with self._session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 403:
                    log.debug("CoC API 403 for %s (private/restricted)", path)
                    return None
                elif resp.status == 404:
                    return None
                else:
                    text = await resp.text()
                    raise CoCApiError(resp.status, text[:200])
        except aiohttp.ClientError as e:
            raise CoCApiError(0, str(e)) from e

    async def get_current_war(self, clan_tag: str) -> Optional[dict]:
        return await self._get(f"/clans/{encode_tag(clan_tag)}/currentwar")

    async def get_player(self, player_tag: str) -> Optional[dict]:
        return await self._get(f"/players/{encode_tag(player_tag)}")

    async def get_capital_raid_seasons(self, clan_tag: str) -> Optional[dict]:
        return await self._get(f"/clans/{encode_tag(clan_tag)}/capitalraidseasons")
