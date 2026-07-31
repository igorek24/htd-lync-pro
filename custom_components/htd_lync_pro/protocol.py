"""HTD Lync 6/12 serial protocol.

Frame format (PC -> Lync):
    0x02 + reserved(0x00) + zone + command + data... + checksum
    checksum = sum of all preceding bytes, modulo 256

Sources for this implementation, in order of authority:
  1. The proven Hubitat driver (works against Lync 12 firmware v3)
  2. HTD "Lync Hex Codes" (V.09.25.14)
  3. HTD "Lync Serial Commands - Version 1.1"

Volume uses signed dB bytes (-60..0 -> 0xC4..0x00) per (1) and (2).
The v1.1 doc describes an 0x80-offset encoding for balance/treble/bass
set commands; firmware v3 is believed to use signed bytes like volume,
so both encodings are supported (see ToneEncoding).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

HEADER = 0x02

# Command bytes (PC -> Lync)
CMD_MP3_REPEAT = 0x01
CMD_COMMON = 0x04
CMD_QUERY_ALL_STATUS = 0x05
CMD_SET_ZONE_NAME = 0x06
CMD_SET_SOURCE_NAME = 0x07
CMD_QUERY_ID = 0x08
CMD_RECALL_FILE = 0x0A
CMD_SAVE_FILE = 0x0B
CMD_QUERY_ZONE_ALL = 0x0C  # per-zone "query all" -> big echo of everything
CMD_QUERY_ZONE_NAME = 0x0D
CMD_QUERY_SOURCE_NAME = 0x0E
CMD_QUERY_FIRMWARE = 0x0F
CMD_SET_VOLUME = 0x15
CMD_SET_BALANCE = 0x16
CMD_SET_TREBLE = 0x17
CMD_SET_BASS = 0x18
CMD_SET_ECHO_MODE = 0x19
CMD_AUDIO_DEFAULT = 0x1E

# Common command (0x04) data bytes
DATA_ALL_ON = 0x55
DATA_ALL_OFF = 0x56
DATA_POWER_ON = 0x57
DATA_POWER_OFF = 0x58
DATA_MUTE_ON = 0x1E
DATA_MUTE_OFF = 0x1F
DATA_DND_ON = 0x59
DATA_DND_OFF = 0x5A
DATA_DOORBELL_ON = 0xA1  # v3, sent with reserved byte 0x01 (per Hubitat driver)
DATA_DOORBELL_OFF = 0xA0
DATA_MP3_FF = 0x0A
DATA_MP3_PLAY_PAUSE = 0x0B
DATA_MP3_FB = 0x0C
DATA_MP3_STOP = 0x0D

# Source select data bytes: sources 1-12, 13-18 (Lync 12 only), and the
# built-in MP3 player (0x7E) as the last source (19 on Lync 12 v3, 13 on
# Lync 6) -- confirmed from the official Android app.
SOURCE_MP3 = 0x7E
SOURCE_SELECT = [
    0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B,
    0x63, 0x64, 0x65, 0x66, 0x67, 0x68, SOURCE_MP3,
]
# Party-mode source select: the official app sends one of these to each
# zone in turn (not a broadcast) to link the whole house to one source.
PARTY_SELECT = [
    0x36, 0x37, 0x38, 0x39, 0x3A, 0x3B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40, 0x41,
    0x69, 0x6A, 0x6B, 0x6C, 0x6D, 0x6E,
]

# Response command bytes (Lync -> PC)
RSP_ZONE_STATUS = 0x05
RSP_KEYPAD_EXIST = 0x06
RSP_MP3_PLAY_END = 0x09
RSP_SOURCE_NAME = 0x0C
RSP_ZONE_NAME = 0x0D
RSP_SOURCE_NAME_ALT = 0x0E  # observed on v3 (per Hubitat driver)
RSP_MP3_FILE_NAME = 0x11
RSP_MP3_ARTIST = 0x12
RSP_MP3_ON = 0x13
RSP_MP3_OFF = 0x14
RSP_ERROR = 0x1B
RSP_DOORBELL = 0x1F  # undocumented; captured from a real Lync 12 v3 ring
RSP_FIRMWARE = 0x33

# Fixed frame lengths, keyed by the response command byte.
_FIXED_LEN = {
    RSP_ZONE_STATUS: 14,
    RSP_KEYPAD_EXIST: 14,
    RSP_MP3_PLAY_END: 6,
    RSP_SOURCE_NAME: 18,
    RSP_ZONE_NAME: 18,
    RSP_SOURCE_NAME_ALT: 18,
    RSP_MP3_ON: 6,
    RSP_ERROR: 14,
    RSP_DOORBELL: 14,
    RSP_FIRMWARE: 14,
}

VOLUME_MIN_DB = -60
VOLUME_MAX_DB = 0
TONE_RANGE = 10       # bass/treble: -10..+10
BALANCE_RANGE = 18    # balance: -18 (left) .. +18 (right)

ERROR_TEXT = {
    1: "volume setting range error",
    2: "balance setting range error",
    3: "treble setting range error",
    4: "bass setting range error",
}


class ToneEncoding(str, Enum):
    """Byte encoding used by bass/treble/balance set commands."""

    SIGNED = "signed"     # -5 -> 0xFB (matches v3 volume + status reports)
    OFFSET = "offset"     # -5 -> 0x7B (0x80-based, per v1.1 protocol doc)


@dataclass
class ZoneState:
    zone: int
    power: bool = False
    mute: bool = False
    dnd: bool = False
    party: bool = False
    source: int = 1               # 1-based
    volume_db: int = VOLUME_MIN_DB  # -60..0
    treble: int = 0
    bass: int = 0
    balance: int = 0
    name: str | None = None
    source_names: dict[int, str] = field(default_factory=dict)
    raw: tuple[int, int, int, int] = (0, 0, 0, 0)

    @property
    def volume_keypad(self) -> int:
        """Volume as shown on HTD keypads/app: 0..60."""
        return self.volume_db - VOLUME_MIN_DB


@dataclass
class Mp3State:
    playing: bool = False
    repeat: bool = False
    file_name: str | None = None
    artist: str | None = None


# ---------------------------------------------------------------------------
# Frame building
# ---------------------------------------------------------------------------

def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def build_frame(zone: int, command: int, data: bytes | list[int], reserved: int = 0x00) -> bytes:
    body = bytes([HEADER, reserved, zone, command]) + bytes(data)
    return body + bytes([checksum(body)])


def _signed_byte(value: int) -> int:
    return value & 0xFF


def _decode_signed(byte: int) -> int:
    return byte - 256 if byte > 127 else byte


def cmd_power(zone: int, on: bool) -> bytes:
    return build_frame(zone, CMD_COMMON, [DATA_POWER_ON if on else DATA_POWER_OFF])


def cmd_all_power(on: bool) -> bytes:
    return build_frame(0, CMD_COMMON, [DATA_ALL_ON if on else DATA_ALL_OFF])


def cmd_mute(zone: int, on: bool) -> bytes:
    return build_frame(zone, CMD_COMMON, [DATA_MUTE_ON if on else DATA_MUTE_OFF])


def cmd_dnd(zone: int, on: bool) -> bytes:
    return build_frame(zone, CMD_COMMON, [DATA_DND_ON if on else DATA_DND_OFF])


def cmd_doorbell(zone: int, on: bool) -> bytes:
    # The official app sends both on and off with reserved byte 0x01.
    data = DATA_DOORBELL_ON if on else DATA_DOORBELL_OFF
    return build_frame(zone, CMD_COMMON, [data], reserved=0x01)


def cmd_source(zone: int, source: int) -> bytes:
    """Select input source (1-18). Also powers the zone on."""
    if not 1 <= source <= len(SOURCE_SELECT):
        raise ValueError(f"source must be 1-{len(SOURCE_SELECT)}, got {source}")
    return build_frame(zone, CMD_COMMON, [SOURCE_SELECT[source - 1]])


def cmd_party_mode(zone: int, source: int) -> bytes:
    """Link one zone to the given party source (send to each zone in turn)."""
    if not 1 <= source <= len(PARTY_SELECT):
        raise ValueError(f"source must be 1-{len(PARTY_SELECT)}, got {source}")
    return build_frame(zone, CMD_COMMON, [PARTY_SELECT[source - 1]])


def cmd_volume(zone: int, volume_db: int) -> bytes:
    """Set volume in dB, -60 (silent) .. 0 (max)."""
    volume_db = max(VOLUME_MIN_DB, min(VOLUME_MAX_DB, volume_db))
    return build_frame(zone, CMD_SET_VOLUME, [_signed_byte(volume_db)])


def _tone_byte(value: int, encoding: ToneEncoding) -> int:
    if encoding is ToneEncoding.OFFSET:
        return 0x80 + value
    return _signed_byte(value)


def cmd_bass(zone: int, value: int, encoding: ToneEncoding = ToneEncoding.SIGNED) -> bytes:
    value = max(-TONE_RANGE, min(TONE_RANGE, value))
    return build_frame(zone, CMD_SET_BASS, [_tone_byte(value, encoding)])


def cmd_treble(zone: int, value: int, encoding: ToneEncoding = ToneEncoding.SIGNED) -> bytes:
    value = max(-TONE_RANGE, min(TONE_RANGE, value))
    return build_frame(zone, CMD_SET_TREBLE, [_tone_byte(value, encoding)])


def cmd_balance(zone: int, value: int, encoding: ToneEncoding = ToneEncoding.SIGNED) -> bytes:
    value = max(-BALANCE_RANGE, min(BALANCE_RANGE, value))
    return build_frame(zone, CMD_SET_BALANCE, [_tone_byte(value, encoding)])


def cmd_mp3(action: int) -> bytes:
    return build_frame(0, CMD_COMMON, [action])


def cmd_mp3_repeat(on: bool) -> bytes:
    return build_frame(0, CMD_MP3_REPEAT, [0xFF if on else 0x00])


def cmd_recall_file(number: int) -> bytes:
    if not 1 <= number <= 4:
        raise ValueError("preset number must be 1-4")
    return build_frame(0, CMD_RECALL_FILE, [number])


def cmd_save_file(number: int) -> bytes:
    if not 1 <= number <= 4:
        raise ValueError("preset number must be 1-4")
    return build_frame(0, CMD_SAVE_FILE, [number])


def cmd_query_id() -> bytes:
    return build_frame(0, CMD_QUERY_ID, [0x00])


def cmd_query_firmware() -> bytes:
    return build_frame(0, CMD_QUERY_FIRMWARE, [0x00])


def cmd_query_all_status() -> bytes:
    return build_frame(0, CMD_QUERY_ALL_STATUS, [0x00])


def cmd_query_everything(zone: int = 1) -> bytes:
    """Echoes all zone statuses, all zone names, all source names, MP3 state."""
    return build_frame(zone, CMD_QUERY_ZONE_ALL, [0x00])


def cmd_query_zone_name(zone: int) -> bytes:
    return build_frame(zone, CMD_QUERY_ZONE_NAME, [0x00])


def cmd_query_source_name(zone: int, source: int) -> bytes:
    return build_frame(zone, CMD_QUERY_SOURCE_NAME, [source - 1])


def _name_payload(name: str) -> bytes:
    encoded = name.encode("ascii", errors="replace")[:10]
    return encoded.ljust(10, b"\x00")


def cmd_set_zone_name(zone: int, name: str) -> bytes:
    return build_frame(zone, CMD_SET_ZONE_NAME, b"\x00" + _name_payload(name) + b"\x00")


def cmd_set_source_name(zone: int, source: int, name: str) -> bytes:
    return build_frame(zone, CMD_SET_SOURCE_NAME, bytes([source]) + _name_payload(name) + b"\x00")


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

@dataclass
class ZoneStatusMsg:
    zone: int
    power: bool
    mute: bool
    dnd: bool
    party: bool
    source: int
    volume_db: int
    treble: int
    bass: int
    balance: int
    # raw state bytes D1-D4, kept for diagnosing undocumented flags
    raw: tuple[int, int, int, int] = (0, 0, 0, 0)

    @property
    def doorbell_signature(self) -> bool:
        """Undocumented bits observed during a doorbell chime.

        Normal D1 frames only use bits 0-2 (power/mute/dnd) and sometimes
        bit 7. The Hubitat driver observed D1 = 0x64 while the doorbell
        chime played, so bits 5/6 in D1 are treated as the ring marker.
        Experimental until confirmed with a capture from real hardware.
        """
        return bool(self.raw[0] & 0x60)


@dataclass
class ZoneNameMsg:
    zone: int
    name: str


@dataclass
class SourceNameMsg:
    zone: int
    source: int
    name: str


@dataclass
class KeypadExistMsg:
    zones: list[int]


@dataclass
class IdMsg:
    model: str  # "Lync6" or "Lync12"


@dataclass
class FirmwareMsg:
    version: str  # "v3"


@dataclass
class ErrorMsg:
    code: int
    text: str


@dataclass
class DoorbellMsg:
    """Doorbell chime state change (undocumented message 0x1F).

    Captured from a real Lync 12 v3: `02 00 00 1F 02 ... 23` when the
    chime starts (data = doorbell input bitmask), `02 00 00 1F 00 ... 21`
    when it ends.
    """

    active: bool
    input: int  # raw data byte; 0 when the chime ends


@dataclass
class Mp3Msg:
    event: str  # on | off | play_end | file_name | artist
    text: str | None = None


LyncMessage = (
    ZoneStatusMsg | ZoneNameMsg | SourceNameMsg | KeypadExistMsg
    | IdMsg | FirmwareMsg | ErrorMsg | Mp3Msg | DoorbellMsg
)


def _ascii(data: bytes) -> str:
    return data.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


class LyncProtocolParser:
    """Incremental parser: feed raw bytes, get complete messages back.

    Handles the fact that the unit streams many frames back-to-back (the
    "query everything" reply is thousands of bytes of concatenated frames)
    and that the ID reply is bare ASCII with no framing at all.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[LyncMessage]:
        self._buf.extend(data)
        messages: list[LyncMessage] = []
        while True:
            msg, consumed = self._next_message()
            if consumed == 0:
                break
            del self._buf[:consumed]
            if msg is not None:
                messages.append(msg)
        return messages

    def _next_message(self) -> tuple[LyncMessage | None, int]:
        buf = self._buf
        if not buf:
            return None, 0

        # Bare ASCII ID reply ("Lync6" / "Lync12"), possibly NUL padded.
        if buf[0] == 0x4C:  # 'L'
            text = bytes(buf)
            if text.startswith(b"Lync"):
                if b"Lync12" in text[:8]:
                    return IdMsg("Lync12"), 6
                if b"Lync6" in text[:8]:
                    return IdMsg("Lync6"), 5
                if len(buf) < 8:
                    return None, 0  # wait for more bytes
            return None, 1  # not an ID message, skip

        if buf[0] != HEADER:
            return None, 1  # resync: drop garbage byte

        if len(buf) < 5:
            return None, 0

        cmd = buf[3]

        if cmd in (RSP_MP3_FILE_NAME, RSP_MP3_ARTIST, RSP_MP3_OFF):
            # Variable length: ASCII, NUL terminated, then checksum byte.
            end = buf.find(b"\x00", 4)
            if end == -1:
                return None, 0 if len(buf) < 80 else 1
            frame_len = end + 2  # include NUL + checksum
            if len(buf) < frame_len:
                return None, 0
            frame = bytes(buf[:frame_len])
            text = _ascii(frame[4:end])
            if cmd == RSP_MP3_FILE_NAME:
                return Mp3Msg("file_name", text), frame_len
            if cmd == RSP_MP3_ARTIST:
                return Mp3Msg("artist", text), frame_len
            return Mp3Msg("off"), frame_len

        length = _FIXED_LEN.get(cmd)
        if length is None:
            return None, 1  # unknown command, resync

        if len(buf) < length:
            return None, 0

        frame = bytes(buf[:length])
        if checksum(frame[:-1]) != frame[-1]:
            return None, 1  # bad checksum, resync one byte at a time

        return self._decode(frame, cmd), length

    def _decode(self, frame: bytes, cmd: int) -> LyncMessage | None:
        if cmd == RSP_ZONE_STATUS:
            zone = frame[2]
            if zone == 0:
                return None
            d1 = frame[4]
            return ZoneStatusMsg(
                zone=zone,
                power=bool(d1 & 0x01),
                mute=bool(d1 & 0x02),
                dnd=bool(d1 & 0x04),
                party=bool(frame[5] & 0x20),
                source=frame[8] + 1,
                volume_db=_decode_signed(frame[9]),
                treble=_decode_signed(frame[10]),
                bass=_decode_signed(frame[11]),
                balance=_decode_signed(frame[12]),
                raw=(frame[4], frame[5], frame[6], frame[7]),
            )

        if cmd == RSP_KEYPAD_EXIST:
            zones = []
            for bit in range(8):
                if frame[5] & (1 << bit):
                    zones.append(bit + 1)
            for bit in range(4):
                if frame[7] & (1 << bit):
                    zones.append(bit + 9)
            return KeypadExistMsg(zones=zones)

        if cmd == RSP_ZONE_NAME:
            zone = frame[2] or frame[15]
            if not zone:
                return None
            return ZoneNameMsg(zone=zone, name=_ascii(frame[4:14]))

        if cmd in (RSP_SOURCE_NAME, RSP_SOURCE_NAME_ALT):
            return SourceNameMsg(
                zone=frame[2],
                source=frame[15] + 1,
                name=_ascii(frame[4:14]),
            )

        if cmd == RSP_FIRMWARE:
            return FirmwareMsg("v3")

        if cmd == RSP_ERROR:
            code = frame[4]
            return ErrorMsg(code=code, text=ERROR_TEXT.get(code, f"error {code}"))

        if cmd == RSP_DOORBELL:
            return DoorbellMsg(active=frame[4] != 0, input=frame[4])

        if cmd == RSP_MP3_PLAY_END:
            return Mp3Msg("play_end")

        if cmd == RSP_MP3_ON:
            return Mp3Msg("on")

        return None
