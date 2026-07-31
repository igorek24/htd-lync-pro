"""Doorbell ring detection (experimental).

The Lync protocol has no documented doorbell-ring message, but the unit
pushes zone status frames with otherwise-unused bits set in the state byte
while a chime plays. When that signature is seen, this sensor turns on for
a few seconds and a `htd_lync_pro_doorbell` event fires on the HA bus.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HtdLyncConfigEntry
from .const import DOMAIN
from .entity import HtdLyncControllerEntity

EVENT_DOORBELL = f"{DOMAIN}_doorbell"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtdLyncConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([HtdLyncDoorbellRingSensor(hass, entry)])


class HtdLyncDoorbellRingSensor(HtdLyncControllerEntity, BinarySensorEntity):
    _attr_name = "Doorbell ringing"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = "mdi:bell-ring"

    def __init__(self, hass: HomeAssistant, entry: HtdLyncConfigEntry) -> None:
        super().__init__(entry.runtime_data, entry.entry_id)
        self._hass = hass
        self._attr_unique_id = f"{entry.entry_id}_doorbell_ringing"
        self._was_ringing = False

    @property
    def is_on(self) -> bool:
        return self._client.doorbell_ringing

    @property
    def extra_state_attributes(self) -> dict:
        return {"doorbell_input": self._client.doorbell_input}

    def _on_update(self, zone: int | None) -> None:
        ringing = self._client.doorbell_ringing
        if ringing and not self._was_ringing:
            self._hass.bus.fire(
                EVENT_DOORBELL,
                {
                    "entry_id": self._entry_id,
                    "doorbell_input": self._client.doorbell_input,
                },
            )
        self._was_ringing = ringing
        super()._on_update(zone)
