"""Base entities for HTD Lync."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .client import HtdLyncClient
from .const import DOMAIN, MANUFACTURER


class HtdLyncBaseEntity(Entity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, client: HtdLyncClient, entry_id: str) -> None:
        self._client = client
        self._entry_id = entry_id
        self._unsubscribe = None

    async def async_added_to_hass(self) -> None:
        self._unsubscribe = self._client.subscribe(self._on_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    def _relevant(self, zone: int | None) -> bool:
        return True

    def _on_update(self, zone: int | None) -> None:
        if self._relevant(zone):
            self.schedule_update_ha_state()

    @property
    def available(self) -> bool:
        return self._client.connected


class HtdLyncControllerEntity(HtdLyncBaseEntity):
    """Entity that belongs to the controller device (not a zone)."""

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=f"HTD {self._client.model or 'Lync'}",
            manufacturer=MANUFACTURER,
            model=self._client.model or "Lync",
            sw_version=self._client.firmware,
        )


class HtdLyncZoneEntity(HtdLyncBaseEntity):
    """Entity that belongs to one audio zone (its own HA device)."""

    def __init__(self, client: HtdLyncClient, entry_id: str, zone: int) -> None:
        super().__init__(client, entry_id)
        self._zone = zone

    @property
    def _state(self):
        return self._client.zone(self._zone)

    def _relevant(self, zone: int | None) -> bool:
        return zone is None or zone == self._zone

    @property
    def device_info(self) -> DeviceInfo:
        zone_name = self._state.name or f"Zone {self._zone}"
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}-zone{self._zone}")},
            via_device=(DOMAIN, self._entry_id),
            name=zone_name,
            manufacturer=MANUFACTURER,
            model=f"{self._client.model or 'Lync'} zone {self._zone}",
        )
