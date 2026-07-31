"""Per-zone source selection as an inline dropdown."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HtdLyncConfigEntry
from .entity import HtdLyncZoneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtdLyncConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client = entry.runtime_data
    async_add_entities(
        HtdLyncSourceSelect(client, entry.entry_id, zone)
        for zone in range(1, client.zone_count + 1)
    )


class HtdLyncSourceSelect(HtdLyncZoneEntity, SelectEntity):
    """Source dropdown for a zone.

    Note: per the Lync protocol, selecting a source also powers the zone on.
    """

    _attr_name = "Source"
    _attr_icon = "mdi:import"

    def __init__(self, client, entry_id: str, zone: int) -> None:
        super().__init__(client, entry_id, zone)
        self._attr_unique_id = f"{entry_id}_zone{zone}_source"

    @property
    def options(self) -> list[str]:
        return self._client.source_list(self._zone)

    @property
    def current_option(self) -> str | None:
        return self._client.source_name(self._zone, self._state.source)

    async def async_select_option(self, option: str) -> None:
        sources = self.options
        if option in sources:
            await self._client.async_set_source(self._zone, sources.index(option) + 1)
