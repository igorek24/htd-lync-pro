"""Switch entities: per-zone DND and doorbell mute, whole-house power."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import HtdLyncConfigEntry
from .entity import HtdLyncZoneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtdLyncConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client = entry.runtime_data
    entities: list[SwitchEntity] = []
    for zone in range(1, client.zone_count + 1):
        entities.append(HtdLyncDndSwitch(client, entry.entry_id, zone))
        entities.append(HtdLyncDoorbellSwitch(client, entry.entry_id, zone))
    async_add_entities(entities)


class HtdLyncDndSwitch(HtdLyncZoneEntity, SwitchEntity):
    """Do Not Disturb: zone ignores party mode / doorbell announcements."""

    _attr_name = "Do not disturb"
    _attr_icon = "mdi:bell-off-outline"

    def __init__(self, client, entry_id: str, zone: int) -> None:
        super().__init__(client, entry_id, zone)
        self._attr_unique_id = f"{entry_id}_zone{zone}_dnd"

    @property
    def is_on(self) -> bool:
        return self._state.dnd

    async def async_turn_on(self, **kwargs) -> None:
        await self._client.async_dnd(self._zone, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._client.async_dnd(self._zone, False)


class HtdLyncDoorbellSwitch(HtdLyncZoneEntity, SwitchEntity, RestoreEntity):
    """Doorbell chime enable for the zone (firmware v3).

    The unit does not report doorbell state, so this switch is optimistic
    and restores its last state across restarts.
    """

    _attr_name = "Doorbell"
    _attr_icon = "mdi:doorbell"
    _attr_assumed_state = True

    def __init__(self, client, entry_id: str, zone: int) -> None:
        super().__init__(client, entry_id, zone)
        self._attr_unique_id = f"{entry_id}_zone{zone}_doorbell"
        self._is_on = True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._is_on = last.state == "on"

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        await self._client.async_doorbell(self._zone, True)
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self._client.async_doorbell(self._zone, False)
        self._is_on = False
        self.async_write_ha_state()
