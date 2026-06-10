"""Shared helper utilities."""

from __future__ import annotations

import asyncio
import json
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable, TypeVar

from zoneinfo import ZoneInfo


T = TypeVar("T")


class ExternalServiceError(RuntimeError):
    """Raised when an external dependency fails."""


class ServiceUnavailableError(ExternalServiceError):
    """Raised when an external service is unavailable or unconfigured."""


def utc_now() -> datetime:
    """Return timezone-aware UTC now."""

    return datetime.now(UTC)


def wat_now() -> datetime:
    """Return timezone-aware West Africa Time."""

    return datetime.now(ZoneInfo("Africa/Lagos"))


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a float into the provided range."""

    return max(minimum, min(value, maximum))


def safe_json_loads(raw_text: str) -> dict[str, Any]:
    """Parse the first JSON object found in a model response."""

    raw_text = raw_text.strip()
    if raw_text.startswith("{") and raw_text.endswith("}"):
        return json.loads(raw_text)

    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in response")
    return json.loads(match.group(0))


async def with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    """Run an async operation with exponential backoff."""

    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except retry_exceptions as error:
            last_error = error
            if attempt == attempts:
                break
            await asyncio.sleep(base_delay * math.pow(2, attempt - 1))
    assert last_error is not None
    raise last_error


def minutes_from_now(minutes: int) -> datetime:
    """Return a UTC timestamp advanced by the supplied minutes."""

    return utc_now() + timedelta(minutes=minutes)


def iso_now() -> str:
    """Return the current UTC time as ISO 8601 text."""

    return utc_now().isoformat()
