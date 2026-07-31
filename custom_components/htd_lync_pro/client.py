"""Async client for HTD Lync 6/12 over TCP (GW-SL1 gateway) or RS-232 serial."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from . import protocol as p
from .protocol import (
    LyncProtocolParser,
    Mp3State,
    ToneEncoding,
    ZoneState,
)

_LOGGER = logging.getLogger(__name__)

SERIAL_BAUD = 38400
COMMAND_SPACING = 0.05  # seconds between writes; the unit chokes on bursts
RECONNECT_DELAY_MIN = 2
RECONNECT_DELAY_MAX = 60

MODEL_INFO = {
    "Lync6": {"zones": 6, "sources": 13},   # 12 inputs + built-in MP3 player
    "Lync12": {"zones": 12, "sources": 19},  # 18 inputs + built-in MP3 player
}


class HtdLyncClient:
    """Maintains a persistent connection and mirrors the unit's state."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        serial_path: str | None = None,
        tone_encoding: ToneEncoding = ToneEncoding.SIGNED,
    ) -> None:
        if not host and not serial_path:
            raise ValueError("either host/port or serial_path is required")
        self._host = host
        self._port = port
        self._serial_path = serial_path
        self.tone_encoding = tone_encoding

        self._parser = LyncProtocolParser()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._run_task: asyncio.Task | None = None
        self._write_lock = asyncio.Lock()
        self._closing = False
        self._connected = asyncio.Event()
        self._id_received = asyncio.Event()

        self.model: str | None = None
        self.firmware: str | None = None
        self.zones: dict[int, ZoneState] = {}
        self.mp3 = Mp3State()
        self.detected_zones: list[int] = []
        self.doorbell_ringing = False
        self.doorbell_input = 0
        self.restore_after_doorbell = True
        self._doorbell_clear_task: asyncio.Task | None = None
        self._doorbell_snapshot: dict[int, tuple[bool, int, int]] | None = None
        self._doorbell_restore_task: asyncio.Task | None = None
        self.saved_snapshot: dict[int, tuple[bool, int, int]] | None = None

        self._subscribers: list[Callable[[int | None], None]] = []

    # -- properties ---------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def ready(self) -> bool:
        return self.connected and self.model is not None

    @property
    def zone_count(self) -> int:
        return MODEL_INFO.get(self.model, {}).get("zones", 12)

    @property
    def source_count(self) -> int:
        return MODEL_INFO.get(self.model, {}).get("sources", 18)

    @property
    def connection_description(self) -> str:
        if self._serial_path:
            return self._serial_path
        return f"{self._host}:{self._port}"

    def zone(self, zone: int) -> ZoneState:
        if zone not in self.zones:
            self.zones[zone] = ZoneState(zone=zone)
        return self.zones[zone]

    def source_name(self, zone: int, source: int) -> str:
        state = self.zones.get(zone)
        if state and source in state.source_names:
            return state.source_names[source]
        # fall back to any zone that knows this source's name
        for other in self.zones.values():
            if source in other.source_names:
                return other.source_names[source]
        if source == 19:
            return "Intercom"  # firmware v3 zone-to-zone source (official app name)
        if self.model == "Lync6" and source == 13:
            return "MP3 Player"
        return f"Source {source}"

    def source_list(self, zone: int) -> list[str]:
        return [self.source_name(zone, s) for s in range(1, self.source_count + 1)]

    # -- subscriptions ------------------------------------------------------

    def subscribe(self, callback: Callable[[int | None], None]) -> Callable[[], None]:
        """Register a callback fired on state change (zone number or None=global)."""
        self._subscribers.append(callback)

        def _unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return _unsubscribe

    def _notify(self, zone: int | None) -> None:
        for callback in list(self._subscribers):
            try:
                callback(zone)
            except Exception:  # noqa: BLE001 - never let one subscriber kill the loop
                _LOGGER.exception("Subscriber callback failed")

    # -- connection lifecycle -----------------------------------------------

    async def async_connect(self) -> None:
        """Open the connection and start the reader loop."""
        self._closing = False
        if self._run_task is None or self._run_task.done():
            self._run_task = asyncio.get_running_loop().create_task(self._run())
        await asyncio.wait_for(self._connected.wait(), timeout=10)

    async def async_wait_ready(self, timeout: float = 10) -> None:
        await asyncio.wait_for(self._id_received.wait(), timeout=timeout)

    async def async_disconnect(self) -> None:
        self._closing = True
        if self._doorbell_clear_task:
            self._doorbell_clear_task.cancel()
            self._doorbell_clear_task = None
        if self._doorbell_restore_task:
            self._doorbell_restore_task.cancel()
            self._doorbell_restore_task = None
        if self._run_task:
            self._run_task.cancel()
            self._run_task = None
        await self._close_transport()

    async def _close_transport(self) -> None:
        self._connected.clear()
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (OSError, asyncio.TimeoutError):
                pass
        self._reader = None
        self._writer = None

    async def _open(self) -> None:
        if self._serial_path:
            # Lazy import: only needed for direct RS-232 connections.
            from serial_asyncio_fast import open_serial_connection

            self._reader, self._writer = await open_serial_connection(
                url=self._serial_path,
                baudrate=SERIAL_BAUD,
            )
        else:
            self._reader, self._writer = await asyncio.open_connection(
                self._host, self._port
            )

    async def _run(self) -> None:
        delay = RECONNECT_DELAY_MIN
        while not self._closing:
            try:
                await self._open()
                self._connected.set()
                self._notify(None)
                delay = RECONNECT_DELAY_MIN
                _LOGGER.info("Connected to Lync at %s", self.connection_description)
                await self._refresh_after_connect()
                await self._read_loop()
            except asyncio.CancelledError:
                raise
            except (OSError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "Lync connection to %s failed (%s), retrying in %ss",
                    self.connection_description, err, delay,
                )
            finally:
                await self._close_transport()
                self._notify(None)
            if self._closing:
                return
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_DELAY_MAX)

    async def _read_loop(self) -> None:
        assert self._reader is not None
        while True:
            data = await self._reader.read(1024)
            if not data:
                raise ConnectionResetError("connection closed by remote end")
            _LOGGER.debug("RX %s", data.hex(" "))
            for msg in self._parser.feed(data):
                self._handle_message(msg)

    async def _refresh_after_connect(self) -> None:
        await self.async_query_id()
        await self.async_query_firmware()
        await self.async_query_everything()

    # -- message handling ---------------------------------------------------

    def _handle_message(self, msg: p.LyncMessage) -> None:
        if isinstance(msg, p.IdMsg):
            self.model = msg.model
            self._id_received.set()
            self._notify(None)
        elif isinstance(msg, p.FirmwareMsg):
            self.firmware = msg.version
            self._notify(None)
        elif isinstance(msg, p.ZoneStatusMsg):
            if msg.doorbell_signature:
                _LOGGER.info(
                    "Doorbell signature in zone %d status (D1-D4: %s) - "
                    "please report this frame if it did NOT coincide with a "
                    "doorbell ring", msg.zone, [hex(b) for b in msg.raw],
                )
                self._set_doorbell_ringing()
            state = self.zone(msg.zone)
            state.power = msg.power
            state.mute = msg.mute
            state.dnd = msg.dnd
            state.party = msg.party
            state.source = msg.source
            state.volume_db = msg.volume_db
            state.treble = msg.treble
            state.bass = msg.bass
            state.balance = msg.balance
            state.raw = msg.raw
            self._notify(msg.zone)
        elif isinstance(msg, p.ZoneNameMsg):
            if msg.name:
                self.zone(msg.zone).name = msg.name
                self._notify(msg.zone)
        elif isinstance(msg, p.SourceNameMsg):
            if msg.name and 1 <= msg.zone <= 12:
                self.zone(msg.zone).source_names[msg.source] = msg.name
                self._notify(msg.zone)
        elif isinstance(msg, p.KeypadExistMsg):
            self.detected_zones = msg.zones
            self._notify(None)
        elif isinstance(msg, p.Mp3Msg):
            if msg.event == "on":
                self.mp3.playing = True
            elif msg.event in ("off", "play_end"):
                self.mp3.playing = False
            elif msg.event == "file_name":
                self.mp3.file_name = msg.text
            elif msg.event == "artist":
                self.mp3.artist = msg.text
            self._notify(None)
        elif isinstance(msg, p.DoorbellMsg):
            _LOGGER.info(
                "Doorbell %s (input %#x)",
                "ringing" if msg.active else "stopped",
                msg.input,
            )
            if msg.active:
                self.doorbell_input = msg.input
                self._set_doorbell_ringing()
            else:
                self._clear_doorbell_ringing()
        elif isinstance(msg, p.ErrorMsg):
            _LOGGER.error("Lync reported: %s", msg.text)

    def _set_doorbell_ringing(self) -> None:
        """Mark the doorbell as ringing.

        The unit sends an explicit stop message (0x1F data 0x00) when the
        chime ends; the timer is only a fallback in case it gets lost.
        """
        # A pending restore is void: the chime is (re)altering zones again,
        # but the snapshot from the first ring stays authoritative.
        if self._doorbell_restore_task and not self._doorbell_restore_task.done():
            self._doorbell_restore_task.cancel()
        if self._doorbell_snapshot is None:
            self._doorbell_snapshot = {
                zone: (state.power, state.source, state.volume_db)
                for zone, state in self.zones.items()
            }
        self.doorbell_ringing = True
        self._notify(None)
        if self._doorbell_clear_task and not self._doorbell_clear_task.done():
            self._doorbell_clear_task.cancel()

        async def _fallback_clear() -> None:
            await asyncio.sleep(60)
            self._clear_doorbell_ringing()

        self._doorbell_clear_task = asyncio.get_running_loop().create_task(
            _fallback_clear()
        )

    def _clear_doorbell_ringing(self) -> None:
        if self._doorbell_clear_task and not self._doorbell_clear_task.done():
            self._doorbell_clear_task.cancel()
        if self.doorbell_ringing:
            self.doorbell_ringing = False
            self._notify(None)
        snapshot, self._doorbell_snapshot = self._doorbell_snapshot, None
        if snapshot and self.restore_after_doorbell:
            self._doorbell_restore_task = asyncio.get_running_loop().create_task(
                self._restore_after_doorbell(snapshot)
            )

    async def _restore_after_doorbell(
        self, snapshot: dict[int, tuple[bool, int, int]]
    ) -> None:
        """Put zones back how they were before the chime.

        The unit powers zones on and routes them to the Intercom source for
        the chime, and does not revert them afterwards.
        """
        await asyncio.sleep(2)  # let the unit finish its own state pushes
        restored = await self.async_restore_states(snapshot)
        if restored:
            _LOGGER.info(
                "Restored %d zone(s) to their pre-doorbell state", restored
            )

    # -- generic snapshot / restore ------------------------------------------

    def take_snapshot(self) -> dict[int, tuple[bool, int, int]]:
        """Capture power/source/volume of every zone."""
        self.saved_snapshot = {
            zone: (state.power, state.source, state.volume_db)
            for zone, state in self.zones.items()
        }
        return self.saved_snapshot

    async def async_restore_states(
        self, snapshot: dict[int, tuple[bool, int, int]] | None = None
    ) -> int:
        """Restore a snapshot; only zones that differ get commands."""
        snapshot = snapshot or self.saved_snapshot
        if not snapshot:
            return 0
        await self.async_query_all_status()
        await asyncio.sleep(1)
        restored = 0
        for zone, (power, source, volume_db) in snapshot.items():
            current = self.zones.get(zone)
            if current is None:
                continue
            if not power:
                if current.power:
                    await self.async_power(zone, False)
                    restored += 1
                continue
            if current.source != source:
                await self.async_set_source(zone, source)  # also powers on
                restored += 1
            elif not current.power:
                await self.async_power(zone, True)
                restored += 1
            if current.volume_db != volume_db:
                await self._send(p.cmd_volume(zone, volume_db))
        if restored:
            await self.async_query_all_status()
        return restored

    async def async_follow_me(
        self,
        to_zone: int,
        from_zone: int | None = None,
        turn_off_source: bool = True,
        copy_volume: bool = True,
        exclude_zones: list[int] | None = None,
        volume_offset: int = 0,
    ) -> bool:
        """Move what's playing in one zone to another.

        exclude_zones are never followed from and never targeted; if the
        destination is excluded, nothing happens. volume_offset adjusts the
        destination volume in dB relative to the source zone.
        """
        exclude = set(exclude_zones or [])
        if to_zone in exclude:
            _LOGGER.debug("follow_me: zone %d is excluded, skipping", to_zone)
            return False
        if from_zone is None:
            candidates = [
                zone for zone, state in self.zones.items()
                if state.power and zone != to_zone and zone not in exclude
            ]
            if not candidates:
                return False  # nothing is playing anywhere (or all excluded)
            from_zone = candidates[0]
            if len(candidates) > 1:
                _LOGGER.warning(
                    "follow_me: several zones are on (%s); following zone %d. "
                    "Pass from_zone to disambiguate.", candidates, from_zone,
                )
        src_state = self.zones.get(from_zone)
        if (
            src_state is None or not src_state.power
            or from_zone == to_zone or from_zone in exclude
        ):
            return False
        dest = self.zones.get(to_zone)
        if dest and dest.power and dest.source == src_state.source:
            # destination already playing the same thing; just handle the tail
            if turn_off_source:
                await self.async_power(from_zone, False)
            return True
        await self.async_set_source(to_zone, src_state.source)  # powers on
        if copy_volume:
            volume_db = max(
                p.VOLUME_MIN_DB,
                min(p.VOLUME_MAX_DB, src_state.volume_db + volume_offset),
            )
            await self._send(p.cmd_volume(to_zone, volume_db))
        if turn_off_source:
            await self.async_power(from_zone, False)
        await self.async_query_all_status()
        return True

    # -- sending ------------------------------------------------------------

    async def _send(self, frame: bytes) -> None:
        async with self._write_lock:
            if not self._writer:
                raise ConnectionError("not connected to Lync")
            _LOGGER.debug("TX %s", frame.hex(" "))
            self._writer.write(frame)
            await self._writer.drain()
            await asyncio.sleep(COMMAND_SPACING)

    # -- queries ------------------------------------------------------------

    async def async_query_id(self) -> None:
        await self._send(p.cmd_query_id())

    async def async_query_firmware(self) -> None:
        await self._send(p.cmd_query_firmware())

    async def async_query_all_status(self) -> None:
        await self._send(p.cmd_query_all_status())

    async def async_query_everything(self) -> None:
        """Request all zone statuses, zone names, source names and MP3 state."""
        await self._send(p.cmd_query_everything())

    async def async_refresh_zone(self, zone: int) -> None:
        """Force a status echo by re-selecting the current source (app trick)."""
        state = self.zones.get(zone)
        if state is None or not state.power:
            return
        source = state.source if 1 <= state.source <= self.source_count else 1
        await self._send(p.cmd_source(zone, source))

    # -- zone controls ------------------------------------------------------

    async def async_power(self, zone: int, on: bool) -> None:
        await self._send(p.cmd_power(zone, on))

    async def async_all_power(self, on: bool) -> None:
        await self._send(p.cmd_all_power(on))
        await self.async_query_all_status()

    async def async_mute(self, zone: int, on: bool) -> None:
        await self._send(p.cmd_mute(zone, on))

    async def async_dnd(self, zone: int, on: bool) -> None:
        await self._send(p.cmd_dnd(zone, on))
        await self.async_refresh_zone(zone)

    async def async_doorbell(self, zone: int, on: bool) -> None:
        await self._send(p.cmd_doorbell(zone, on))

    async def async_set_source(self, zone: int, source: int) -> None:
        if source == self.source_count:
            # last source is always the built-in MP3 player (0x7E)
            await self._send(p.build_frame(zone, p.CMD_COMMON, [p.SOURCE_MP3]))
        else:
            await self._send(p.cmd_source(zone, source))

    async def async_party_mode(self, source: int) -> None:
        # the official app links zones one at a time rather than broadcasting
        for zone in range(1, self.zone_count + 1):
            await self._send(p.cmd_party_mode(zone, source))
        await self.async_query_all_status()

    async def async_set_volume_db(self, zone: int, volume_db: int) -> None:
        await self._send(p.cmd_volume(zone, volume_db))
        await self.async_refresh_zone(zone)

    async def async_volume_step(self, zone: int, delta: int) -> None:
        state = self.zone(zone)
        await self.async_set_volume_db(zone, state.volume_db + delta)

    async def async_set_bass(self, zone: int, value: int) -> None:
        await self._send(p.cmd_bass(zone, value, self.tone_encoding))
        await self.async_refresh_zone(zone)

    async def async_set_treble(self, zone: int, value: int) -> None:
        await self._send(p.cmd_treble(zone, value, self.tone_encoding))
        await self.async_refresh_zone(zone)

    async def async_set_balance(self, zone: int, value: int) -> None:
        await self._send(p.cmd_balance(zone, value, self.tone_encoding))
        await self.async_refresh_zone(zone)

    async def async_set_zone_name(self, zone: int, name: str) -> None:
        await self._send(p.cmd_set_zone_name(zone, name))
        await self._send(p.cmd_query_zone_name(zone))

    async def async_set_source_name(self, zone: int, source: int, name: str) -> None:
        await self._send(p.cmd_set_source_name(zone, source, name))
        await self._send(p.cmd_query_source_name(zone, source))

    # -- presets / MP3 ------------------------------------------------------

    async def async_recall_preset(self, number: int) -> None:
        await self._send(p.cmd_recall_file(number))
        await self.async_query_all_status()

    async def async_save_preset(self, number: int) -> None:
        await self._send(p.cmd_save_file(number))

    async def async_mp3_play_pause(self) -> None:
        await self._send(p.cmd_mp3(p.DATA_MP3_PLAY_PAUSE))

    async def async_mp3_stop(self) -> None:
        await self._send(p.cmd_mp3(p.DATA_MP3_STOP))

    async def async_mp3_forward(self) -> None:
        await self._send(p.cmd_mp3(p.DATA_MP3_FF))

    async def async_mp3_back(self) -> None:
        await self._send(p.cmd_mp3(p.DATA_MP3_FB))

    async def async_mp3_repeat(self, on: bool) -> None:
        await self._send(p.cmd_mp3_repeat(on))
        self.mp3.repeat = on
        self._notify(None)

    # -- composite: the "party preset" --------------------------------------

    async def async_set_zones_scene(
        self,
        zones: list[int],
        source: int | None,
        volume: int | None,
        offsets: dict[int, int] | None = None,
        others_off: bool = False,
    ) -> None:
        """Turn on a set of zones, put them on one source, set volume w/ offsets.

        volume is keypad scale 0-60; offsets are per-zone dB adjustments.
        """
        offsets = offsets or {}
        if others_off:
            for other in range(1, self.zone_count + 1):
                if other not in zones:
                    await self.async_power(other, False)
        for zone in zones:
            await self.async_power(zone, True)
            if source is not None:
                await self.async_set_source(zone, source)
            if volume is not None:
                db = p.VOLUME_MIN_DB + max(
                    0, min(60, volume + offsets.get(zone, 0))
                )
                await self._send(p.cmd_volume(zone, db))
        await self.async_query_all_status()
