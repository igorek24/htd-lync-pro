"""HTD Lync 6/12 whole-house audio integration."""

from __future__ import annotations

import asyncio
import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
)
from homeassistant.helpers.event import async_track_time_interval

from .client import HtdLyncClient
from .const import (
    ATTR_ANNOUNCE_VOLUME,
    ATTR_COPY_VOLUME,
    ATTR_FROM_ZONE,
    ATTR_MEDIA_PLAYER,
    ATTR_MEDIA_URL,
    ATTR_MESSAGE,
    ATTR_NAME,
    ATTR_OFFSETS,
    ATTR_OTHERS_OFF,
    ATTR_PRESET,
    ATTR_RESTORE_VOLUME,
    ATTR_SOURCE,
    ATTR_TO_ZONE,
    ATTR_TTS_ENTITY,
    ATTR_TURN_OFF_SOURCE,
    ATTR_VOLUME,
    ATTR_ZONE,
    ATTR_ZONES,
    CONF_ANNOUNCE_PLAYER,
    CONF_ANNOUNCE_TTS,
    CONF_DOORBELL_RESTORE,
    CONF_MAX_ON_VOLUME,
    CONF_POLL_INTERVAL,
    CONF_QUIET_CAP,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SERIAL_PATH,
    CONF_TONE_ENCODING,
    DEFAULT_DOORBELL_RESTORE,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    SERVICE_ANNOUNCE,
    SERVICE_FOLLOW_ME,
    SERVICE_REFRESH,
    SERVICE_RESTORE,
    SERVICE_SNAPSHOT,
    SERVICE_ALL_OFF,
    SERVICE_ALL_ON,
    SERVICE_PARTY_MODE,
    SERVICE_RECALL_PRESET,
    SERVICE_SAVE_PRESET,
    SERVICE_SET_SOURCE_NAME,
    SERVICE_SET_ZONE_NAME,
    SERVICE_SET_ZONES,
)
from .protocol import ToneEncoding

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
]

type HtdLyncConfigEntry = ConfigEntry[HtdLyncClient]


async def async_setup_entry(hass: HomeAssistant, entry: HtdLyncConfigEntry) -> bool:
    client = HtdLyncClient(
        host=entry.data.get(CONF_HOST),
        port=entry.data.get(CONF_PORT),
        serial_path=entry.data.get(CONF_SERIAL_PATH),
        tone_encoding=ToneEncoding(
            entry.options.get(CONF_TONE_ENCODING, ToneEncoding.SIGNED.value)
        ),
    )
    client.restore_after_doorbell = entry.options.get(
        CONF_DOORBELL_RESTORE, DEFAULT_DOORBELL_RESTORE
    )

    try:
        await client.async_connect()
        await client.async_wait_ready(timeout=10)
    except (asyncio.TimeoutError, OSError) as err:
        await client.async_disconnect()
        raise ConfigEntryNotReady(
            f"Cannot reach HTD Lync at {client.connection_description}"
        ) from err

    # Zone names arrive asynchronously after connect; wait briefly so the
    # zone devices register with their real names instead of "Zone N".
    for _ in range(20):
        if any(z.name for z in client.zones.values()):
            break
        await asyncio.sleep(0.5)

    entry.runtime_data = client
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Keep device-registry names in sync with the names stored in the unit
    # (covers late name responses and htd_lync_pro.set_zone_name renames).
    device_registry = dr.async_get(hass)

    def _sync_device_name(zone: int | None) -> None:
        if zone is None:
            return
        state = client.zones.get(zone)
        if not state or not state.name:
            return
        device = device_registry.async_get_device(
            identifiers={(DOMAIN, f"{entry.entry_id}-zone{zone}")}
        )
        if device and device.name != state.name and device.name_by_user is None:
            device_registry.async_update_device(device.id, name=state.name)

    entry.async_on_unload(client.subscribe(_sync_device_name))

    # Power-on volume cap / quiet hours: when a zone flips off -> on with a
    # volume above the cap, clamp it.
    max_cap = entry.options.get(CONF_MAX_ON_VOLUME, 0)
    quiet_cap = entry.options.get(CONF_QUIET_CAP, 0)
    quiet_start = entry.options.get(CONF_QUIET_START, "22:00")
    quiet_end = entry.options.get(CONF_QUIET_END, "07:00")
    if max_cap or quiet_cap:
        from homeassistant.util import dt as dt_util

        last_power: dict[int, bool] = {}

        def _active_cap() -> int:
            cap = max_cap
            if quiet_cap:
                now = dt_util.now().strftime("%H:%M")
                in_quiet = (
                    quiet_start <= now or now < quiet_end
                    if quiet_start > quiet_end
                    else quiet_start <= now < quiet_end
                )
                if in_quiet:
                    cap = min(quiet_cap, max_cap) if max_cap else quiet_cap
            return cap

        def _enforce_cap(zone: int | None) -> None:
            if zone is None:
                return
            state = client.zones.get(zone)
            if state is None:
                return
            was_on = last_power.get(zone)
            last_power[zone] = state.power
            if not state.power or was_on is not False:
                return  # only act on an off -> on transition
            cap = _active_cap()
            if cap and state.volume_keypad > cap:
                _LOGGER.info(
                    "Zone %d turned on at volume %d, capping to %d",
                    zone, state.volume_keypad, cap,
                )
                hass.async_create_task(
                    client.async_set_volume_db(zone, cap - 60)
                )

        entry.async_on_unload(client.subscribe(_enforce_cap))

    poll_interval = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    if poll_interval > 0:

        async def _poll(_now) -> None:
            if client.connected:
                await client.async_query_everything()

        entry.async_on_unload(
            async_track_time_interval(hass, _poll, timedelta(seconds=poll_interval))
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HtdLyncConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_disconnect()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: HtdLyncConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _entry_for_call(hass: HomeAssistant, call: ServiceCall) -> HtdLyncConfigEntry:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ValueError("No HTD Lync controller is configured")
    return entries[0]


def _client_for_call(hass: HomeAssistant, call: ServiceCall) -> HtdLyncClient:
    return _entry_for_call(hass, call).runtime_data


def _resolve_source(client: HtdLyncClient, source: str | int) -> int:
    """Accept a source number or a (device-provided) source name."""
    if isinstance(source, int) or str(source).isdigit():
        number = int(source)
        if not 1 <= number <= client.source_count:
            raise ValueError(f"Source number must be 1-{client.source_count}")
        return number
    wanted = str(source).strip().casefold()
    for num in range(1, client.source_count + 1):
        for zone in range(1, client.zone_count + 1):
            if client.source_name(zone, num).strip().casefold() == wanted:
                return num
    raise ValueError(f"Unknown source name: {source}")


SET_ZONES_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ZONES): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(ATTR_SOURCE): vol.Any(vol.Coerce(int), cv.string),
        vol.Optional(ATTR_VOLUME): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
        vol.Optional(ATTR_OFFSETS): {vol.Coerce(int): vol.Coerce(int)},
        vol.Optional(ATTR_OTHERS_OFF, default=False): cv.boolean,
    }
)


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_ZONES):
        return

    async def handle_set_zones(call: ServiceCall) -> None:
        client = _client_for_call(hass, call)
        source = call.data.get(ATTR_SOURCE)
        await client.async_set_zones_scene(
            zones=call.data[ATTR_ZONES],
            source=_resolve_source(client, source) if source is not None else None,
            volume=call.data.get(ATTR_VOLUME),
            offsets=call.data.get(ATTR_OFFSETS),
            others_off=call.data[ATTR_OTHERS_OFF],
        )

    async def handle_party_mode(call: ServiceCall) -> None:
        client = _client_for_call(hass, call)
        await client.async_party_mode(_resolve_source(client, call.data[ATTR_SOURCE]))

    async def handle_all_on(call: ServiceCall) -> None:
        await _client_for_call(hass, call).async_all_power(True)

    async def handle_all_off(call: ServiceCall) -> None:
        await _client_for_call(hass, call).async_all_power(False)

    async def handle_recall_preset(call: ServiceCall) -> None:
        await _client_for_call(hass, call).async_recall_preset(call.data[ATTR_PRESET])

    async def handle_save_preset(call: ServiceCall) -> None:
        await _client_for_call(hass, call).async_save_preset(call.data[ATTR_PRESET])

    async def handle_set_zone_name(call: ServiceCall) -> None:
        client = _client_for_call(hass, call)
        await client.async_set_zone_name(call.data[ATTR_ZONE], call.data[ATTR_NAME])

    async def handle_set_source_name(call: ServiceCall) -> None:
        client = _client_for_call(hass, call)
        source = _resolve_source(client, call.data[ATTR_SOURCE])
        for zone in range(1, client.zone_count + 1):
            await client.async_set_source_name(zone, source, call.data[ATTR_NAME])

    hass.services.async_register(
        DOMAIN, SERVICE_SET_ZONES, handle_set_zones, schema=SET_ZONES_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PARTY_MODE,
        handle_party_mode,
        schema=vol.Schema({vol.Required(ATTR_SOURCE): vol.Any(vol.Coerce(int), cv.string)}),
    )
    async def handle_refresh(call: ServiceCall) -> None:
        await _client_for_call(hass, call).async_query_everything()

    async def handle_snapshot(call: ServiceCall) -> None:
        client = _client_for_call(hass, call)
        client.take_snapshot()
        _LOGGER.info("Zone snapshot taken (%d zones)", len(client.saved_snapshot))

    async def handle_restore(call: ServiceCall) -> None:
        restored = await _client_for_call(hass, call).async_restore_states()
        _LOGGER.info("Snapshot restore adjusted %d zone(s)", restored)

    async def handle_follow_me(call: ServiceCall) -> None:
        client = _client_for_call(hass, call)
        await client.async_follow_me(
            to_zone=call.data[ATTR_TO_ZONE],
            from_zone=call.data.get(ATTR_FROM_ZONE),
            turn_off_source=call.data[ATTR_TURN_OFF_SOURCE],
            copy_volume=call.data[ATTR_COPY_VOLUME],
            exclude_zones=call.data["exclude_zones"],
            volume_offset=call.data["volume_offset"],
        )

    async def handle_announce(call: ServiceCall) -> None:
        entry = _entry_for_call(hass, call)
        player = call.data.get(ATTR_MEDIA_PLAYER) or entry.options.get(
            CONF_ANNOUNCE_PLAYER
        )
        if not player:
            raise ValueError(
                "No announce media player set: pass media_player or set it "
                "in the integration options"
            )
        message = call.data.get(ATTR_MESSAGE)
        media_url = call.data.get(ATTR_MEDIA_URL)
        if not message and not media_url:
            raise ValueError("Provide either message (TTS) or media_url")

        volume = call.data.get(ATTR_ANNOUNCE_VOLUME)
        restore_volume = call.data[ATTR_RESTORE_VOLUME]
        prev_state = hass.states.get(player)
        prev_volume = (
            prev_state.attributes.get("volume_level") if prev_state else None
        )

        if volume is not None:
            await hass.services.async_call(
                "media_player",
                "volume_set",
                {"entity_id": player, "volume_level": volume},
                blocking=True,
            )

        if message:
            tts_entity = call.data.get(ATTR_TTS_ENTITY) or entry.options.get(
                CONF_ANNOUNCE_TTS
            )
            if not tts_entity:
                raise ValueError(
                    "No TTS entity set: pass tts_entity or set it in the "
                    "integration options"
                )
            await hass.services.async_call(
                "tts",
                "speak",
                {
                    "entity_id": tts_entity,
                    "media_player_entity_id": player,
                    "message": message,
                },
                blocking=True,
            )
        else:
            await hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": player,
                    "media_content_id": media_url,
                    "media_content_type": "music",
                },
                blocking=True,
            )

        if restore_volume and volume is not None and prev_volume is not None:

            async def _restore_player_volume() -> None:
                # wait for playback to finish, then put the volume back
                for _ in range(120):
                    await asyncio.sleep(1)
                    state = hass.states.get(player)
                    if state and state.state not in ("playing", "buffering"):
                        break
                await hass.services.async_call(
                    "media_player",
                    "volume_set",
                    {"entity_id": player, "volume_level": prev_volume},
                    blocking=False,
                )

            entry.async_create_background_task(
                hass, _restore_player_volume(), "htd_lync_pro_announce_restore"
            )

    hass.services.async_register(DOMAIN, SERVICE_ALL_ON, handle_all_on)
    hass.services.async_register(DOMAIN, SERVICE_ALL_OFF, handle_all_off)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, handle_refresh)
    hass.services.async_register(DOMAIN, SERVICE_SNAPSHOT, handle_snapshot)
    hass.services.async_register(DOMAIN, SERVICE_RESTORE, handle_restore)
    hass.services.async_register(
        DOMAIN,
        SERVICE_FOLLOW_ME,
        handle_follow_me,
        schema=vol.Schema(
            {
                vol.Required(ATTR_TO_ZONE): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=12)
                ),
                vol.Optional(ATTR_FROM_ZONE): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=12)
                ),
                vol.Optional(ATTR_TURN_OFF_SOURCE, default=True): cv.boolean,
                vol.Optional(ATTR_COPY_VOLUME, default=True): cv.boolean,
                vol.Optional("exclude_zones", default=[]): vol.All(
                    cv.ensure_list, [vol.Coerce(int)]
                ),
                vol.Optional("volume_offset", default=0): vol.All(
                    vol.Coerce(int), vol.Range(min=-30, max=30)
                ),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ANNOUNCE,
        handle_announce,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_MESSAGE): cv.string,
                vol.Optional(ATTR_MEDIA_URL): cv.string,
                vol.Optional(ATTR_MEDIA_PLAYER): cv.entity_id,
                vol.Optional(ATTR_TTS_ENTITY): cv.entity_id,
                vol.Optional(ATTR_ANNOUNCE_VOLUME): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=1)
                ),
                vol.Optional(ATTR_RESTORE_VOLUME, default=True): cv.boolean,
            }
        ),
    )
    preset_schema = vol.Schema(
        {vol.Required(ATTR_PRESET): vol.All(vol.Coerce(int), vol.Range(min=1, max=4))}
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RECALL_PRESET, handle_recall_preset, schema=preset_schema
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SAVE_PRESET, handle_save_preset, schema=preset_schema
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ZONE_NAME,
        handle_set_zone_name,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ZONE): vol.All(vol.Coerce(int), vol.Range(min=1, max=12)),
                vol.Required(ATTR_NAME): vol.All(cv.string, vol.Length(min=1, max=10)),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SOURCE_NAME,
        handle_set_source_name,
        schema=vol.Schema(
            {
                vol.Required(ATTR_SOURCE): vol.Any(vol.Coerce(int), cv.string),
                vol.Required(ATTR_NAME): vol.All(cv.string, vol.Length(min=1, max=10)),
            }
        ),
    )
