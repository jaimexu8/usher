import logging
import re
from datetime import datetime, timezone
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

BASE_URL = "https://api.clashofclans.com/v1"

# CoC clan and player tags use this character set (no 1/I, 0/O ambiguity); length 5-9 after #
COC_TAG_PATTERN = re.compile(r"^#[0289PYLQGRJCUV]{5,9}$", re.IGNORECASE)


def normalize_tag(tag: str) -> str:
    tag = tag.strip().upper()
    if not tag.startswith("#"):
        tag = "#" + tag
    return tag


def is_valid_tag_format(tag: str) -> bool:
    """Return True if tag looks like a valid CoC tag (clan or player). Format only, no API check."""
    normalized = normalize_tag(tag)
    return bool(COC_TAG_PATTERN.match(normalized))


def is_valid_clan_tag_format(tag: str) -> bool:
    """Alias for is_valid_tag_format (clan and player tags share the same format)."""
    return is_valid_tag_format(tag)


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

    async def _get_status_and_json(self, path: str) -> tuple[int, Optional[dict]]:
        """Return (status_code, json_body). Used when we need to distinguish 404 from 200."""
        url = f"{BASE_URL}{path}"
        try:
            async with self._session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return (200, data)
                return (resp.status, None)
        except aiohttp.ClientError as e:
            raise CoCApiError(0, str(e)) from e

    async def get_clan(self, clan_tag: str) -> Optional[dict]:
        """Fetch clan by tag. Returns clan dict if found, None if 404/403."""
        status, data = await self._get_status_and_json(f"/clans/{encode_tag(clan_tag)}")
        if status == 404:
            return None
        if status == 403:
            log.debug("CoC API 403 for clan %s", clan_tag)
            return None
        return data

    async def get_current_war(self, clan_tag: str) -> Optional[dict]:
        return await self._get(f"/clans/{encode_tag(clan_tag)}/currentwar")

    async def get_player(self, player_tag: str) -> Optional[dict]:
        return await self._get(f"/players/{encode_tag(player_tag)}")

    async def get_capital_raid_seasons(self, clan_tag: str) -> Optional[dict]:
        return await self._get(f"/clans/{encode_tag(clan_tag)}/capitalraidseasons")
