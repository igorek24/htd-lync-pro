"""Buttons: all on / all off / recall hardware presets 1-4 / refresh."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HtdLyncConfigEntry
from .entity import HtdLyncControllerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtdLyncConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client = entry.runtime_data
    entities: list[ButtonEntity] = [
        HtdLyncAllPowerButton(client, entry.entry_id, on=True),
        HtdLyncAllPowerButton(client, entry.entry_id, on=False),
        HtdLyncRefreshButton(client, entry.entry_id),
    ]
    entities.extend(
        HtdLyncPresetButton(client, entry.entry_id, preset) for preset in range(1, 5)
    )
    async_add_entities(entities)


class HtdLyncAllPowerButton(HtdLyncControllerEntity, ButtonEntity):
    def __init__(self, client, entry_id: str, on: bool) -> None:
        super().__init__(client, entry_id)
        self._on = on
        self._attr_name = "All zones on" if on else "All zones off"
        self._attr_icon = "mdi:power" if on else "mdi:power-off"
        self._attr_unique_id = f"{entry_id}_all_{'on' if on else 'off'}"

    async def async_press(self) -> None:
        await self._client.async_all_power(self._on)


class HtdLyncPresetButton(HtdLyncControllerEntity, ButtonEntity):
    """Recall one of the four presets stored in the unit itself."""

    def __init__(self, client, entry_id: str, preset: int) -> None:
        super().__init__(client, entry_id)
        self._preset = preset
        self._attr_name = f"Recall preset {preset}"
        self._attr_icon = "mdi:folder-play-outline"
        self._attr_unique_id = f"{entry_id}_preset{preset}"

    async def async_press(self) -> None:
        await self._client.async_recall_preset(self._preset)


class HtdLyncRefreshButton(HtdLyncControllerEntity, ButtonEntity):
    """Manually poll the unit for a full state refresh."""

    _attr_name = "Refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, client, entry_id: str) -> None:
        super().__init__(client, entry_id)
        self._attr_unique_id = f"{entry_id}_refresh"

    async def async_press(self) -> None:
        await self._client.async_query_everything()
