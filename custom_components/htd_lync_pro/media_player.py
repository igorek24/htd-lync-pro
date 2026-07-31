"""Media player entities: one per zone plus the built-in MP3 player."""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    RepeatMode,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HtdLyncConfigEntry
from .const import DOMAIN
from .entity import HtdLyncControllerEntity, HtdLyncZoneEntity
from .protocol import VOLUME_MIN_DB

ZONE_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
)

MP3_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.REPEAT_SET
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtdLyncConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client = entry.runtime_data
    entities: list[MediaPlayerEntity] = [
        HtdLyncZonePlayer(client, entry.entry_id, zone)
        for zone in range(1, client.zone_count + 1)
    ]
    entities.append(HtdLyncMp3Player(client, entry.entry_id))
    async_add_entities(entities)


class HtdLyncZonePlayer(HtdLyncZoneEntity, MediaPlayerEntity):
    _attr_name = None  # entity takes the device (zone) name
    _attr_supported_features = ZONE_FEATURES
    _attr_device_class = "speaker"
    _attr_icon = "mdi:speaker"

    def __init__(self, client, entry_id: str, zone: int) -> None:
        super().__init__(client, entry_id, zone)
        self._attr_unique_id = f"{entry_id}_zone{zone}_player"

    @property
    def state(self) -> MediaPlayerState:
        return MediaPlayerState.ON if self._state.power else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float:
        return self._state.volume_keypad / 60

    @property
    def volume_step(self) -> float:
        return 1 / 60

    @property
    def is_volume_muted(self) -> bool:
        return self._state.mute

    @property
    def source(self) -> str:
        return self._client.source_name(self._zone, self._state.source)

    @property
    def source_list(self) -> list[str]:
        return self._client.source_list(self._zone)

    @property
    def extra_state_attributes(self) -> dict:
        state = self._state
        return {
            "zone": self._zone,
            "volume_db": state.volume_db,
            "volume_keypad": state.volume_keypad,
            "bass": state.bass,
            "treble": state.treble,
            "balance": state.balance,
            "do_not_disturb": state.dnd,
            "party_mode": state.party,
            "source_number": state.source,
            "raw_status": [hex(b) for b in state.raw],
        }

    async def async_turn_on(self) -> None:
        await self._client.async_power(self._zone, True)

    async def async_turn_off(self) -> None:
        await self._client.async_power(self._zone, False)

    async def async_set_volume_level(self, volume: float) -> None:
        await self._client.async_set_volume_db(
            self._zone, VOLUME_MIN_DB + round(volume * 60)
        )

    async def async_volume_up(self) -> None:
        await self._client.async_volume_step(self._zone, 1)

    async def async_volume_down(self) -> None:
        await self._client.async_volume_step(self._zone, -1)

    async def async_mute_volume(self, mute: bool) -> None:
        await self._client.async_mute(self._zone, mute)

    async def async_select_source(self, source: str) -> None:
        sources = self.source_list
        if source in sources:
            await self._client.async_set_source(self._zone, sources.index(source) + 1)


class HtdLyncMp3Player(HtdLyncControllerEntity, MediaPlayerEntity):
    _attr_translation_key = "mp3_player"
    _attr_name = "MP3 player"
    _attr_supported_features = MP3_FEATURES
    _attr_icon = "mdi:music-box"

    def __init__(self, client, entry_id: str) -> None:
        super().__init__(client, entry_id)
        self._attr_unique_id = f"{entry_id}_mp3"

    @property
    def state(self) -> MediaPlayerState:
        return (
            MediaPlayerState.PLAYING
            if self._client.mp3.playing
            else MediaPlayerState.IDLE
        )

    @property
    def media_title(self) -> str | None:
        return self._client.mp3.file_name

    @property
    def media_artist(self) -> str | None:
        return self._client.mp3.artist

    @property
    def repeat(self) -> RepeatMode:
        return RepeatMode.ALL if self._client.mp3.repeat else RepeatMode.OFF

    async def async_media_play(self) -> None:
        await self._client.async_mp3_play_pause()

    async def async_media_pause(self) -> None:
        await self._client.async_mp3_play_pause()

    async def async_media_stop(self) -> None:
        await self._client.async_mp3_stop()

    async def async_media_next_track(self) -> None:
        await self._client.async_mp3_forward()

    async def async_media_previous_track(self) -> None:
        await self._client.async_mp3_back()

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        await self._client.async_mp3_repeat(repeat != RepeatMode.OFF)
