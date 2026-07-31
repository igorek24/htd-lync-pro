"""Diagnostics support for HTD Lync Pro."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import HtdLyncConfigEntry

TO_REDACT = {CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HtdLyncConfigEntry
) -> dict[str, Any]:
    client = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "controller": {
            "model": client.model,
            "firmware": client.firmware,
            "connected": client.connected,
            "zone_count": client.zone_count,
            "source_count": client.source_count,
            "detected_zones": client.detected_zones,
            "doorbell_ringing": client.doorbell_ringing,
            "doorbell_input": client.doorbell_input,
            "mp3": asdict(client.mp3),
        },
        "zones": {zone: asdict(state) for zone, state in client.zones.items()},
    }
