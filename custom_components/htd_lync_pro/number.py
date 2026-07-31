"""Number entities: bass / treble / balance / keypad volume per zone."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HtdLyncConfigEntry
from .client import HtdLyncClient
from .entity import HtdLyncZoneEntity
from .protocol import BALANCE_RANGE, TONE_RANGE, ZoneState


@dataclass(frozen=True, kw_only=True)
class HtdNumberDescription(NumberEntityDescription):
    get_value: Callable[[ZoneState], int]
    set_value: Callable[[HtdLyncClient, int, int], Awaitable[None]]


DESCRIPTIONS: tuple[HtdNumberDescription, ...] = (
    HtdNumberDescription(
        key="bass",
        name="Bass",
        icon="mdi:speaker",
        native_min_value=-TONE_RANGE,
        native_max_value=TONE_RANGE,
        native_step=1,
        get_value=lambda s: s.bass,
        set_value=lambda c, z, v: c.async_set_bass(z, v),
    ),
    HtdNumberDescription(
        key="treble",
        name="Treble",
        icon="mdi:music-clef-treble",
        native_min_value=-TONE_RANGE,
        native_max_value=TONE_RANGE,
        native_step=1,
        get_value=lambda s: s.treble,
        set_value=lambda c, z, v: c.async_set_treble(z, v),
    ),
    HtdNumberDescription(
        key="balance",
        name="Balance",
        icon="mdi:pan-horizontal",
        native_min_value=-BALANCE_RANGE,
        native_max_value=BALANCE_RANGE,
        native_step=1,
        get_value=lambda s: s.balance,
        set_value=lambda c, z, v: c.async_set_balance(z, v),
    ),
    HtdNumberDescription(
        key="volume_keypad",
        name="Volume (keypad 0-60)",
        icon="mdi:volume-medium",
        native_min_value=0,
        native_max_value=60,
        native_step=1,
        get_value=lambda s: s.volume_keypad,
        set_value=lambda c, z, v: c.async_set_volume_db(z, v - 60),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtdLyncConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client = entry.runtime_data
    async_add_entities(
        HtdLyncZoneNumber(client, entry.entry_id, zone, description)
        for zone in range(1, client.zone_count + 1)
        for description in DESCRIPTIONS
    )


class HtdLyncZoneNumber(HtdLyncZoneEntity, NumberEntity):
    entity_description: HtdNumberDescription

    def __init__(self, client, entry_id, zone, description) -> None:
        super().__init__(client, entry_id, zone)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_zone{zone}_{description.key}"

    @property
    def native_value(self) -> int:
        return self.entity_description.get_value(self._state)

    async def async_set_native_value(self, value: float) -> None:
        await self.entity_description.set_value(self._client, self._zone, int(value))
