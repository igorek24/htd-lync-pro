"""Protocol tests, checked against HTD's published "Lync Hex Codes" doc
and the frames sent by the proven Hubitat driver."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "lync_protocol",
    Path(__file__).resolve().parents[1] / "custom_components" / "htd_lync_pro" / "protocol.py",
)
p = importlib.util.module_from_spec(_spec)
import sys

sys.modules[_spec.name] = p
_spec.loader.exec_module(p)


def test_power_commands_match_official_hex_codes():
    # Power Zone 1 On : \x02\x00\x01\x04\x57\x5E
    assert p.cmd_power(1, True) == bytes([0x02, 0x00, 0x01, 0x04, 0x57, 0x5E])
    # Power Zone 12 Off : \x02\x00\x0C\x04\x58\x6A
    assert p.cmd_power(12, False) == bytes([0x02, 0x00, 0x0C, 0x04, 0x58, 0x6A])
    # Power ALL On : \x02\x00\x00\x04\x55\x5B
    assert p.cmd_all_power(True) == bytes([0x02, 0x00, 0x00, 0x04, 0x55, 0x5B])


def test_mute_dnd_match_official_hex_codes():
    # Mute Zone 7 On : \x02\x00\x07\x04\x1E\x2B
    assert p.cmd_mute(7, True) == bytes([0x02, 0x00, 0x07, 0x04, 0x1E, 0x2B])
    # DND Zone 12 Off : \x02\x00\x0C\x04\x5A\x6C
    assert p.cmd_dnd(12, False) == bytes([0x02, 0x00, 0x0C, 0x04, 0x5A, 0x6C])


def test_source_select_match_official_hex_codes():
    # Zone 3 Input 5 : \x02\x00\x03\x04\x14\x1D
    assert p.cmd_source(3, 5) == bytes([0x02, 0x00, 0x03, 0x04, 0x14, 0x1D])
    # Zone 10 Input 18 : \x02\x00\x0A\x04\x68\x78
    assert p.cmd_source(10, 18) == bytes([0x02, 0x00, 0x0A, 0x04, 0x68, 0x78])


def test_party_mode_match_official_app():
    # The app sends party source per zone: 02 00 zone 04 partySource
    # Party Mode Source 5 to zone 5: \x02\x00\x05\x04\x3A\x45
    assert p.cmd_party_mode(5, 5) == bytes([0x02, 0x00, 0x05, 0x04, 0x3A, 0x45])
    # source 13 -> 0x69
    assert p.cmd_party_mode(1, 13)[4] == 0x69


def test_volume_uses_signed_v3_encoding():
    # Official: "Zone 1 - Volume Level 0" (=-60dB) \x02\x01\x01\x15\xC4\xDD
    # data byte for -60 dB must be 0xC4; we send reserved=0x00 like the
    # proven Hubitat driver, so only compare the data byte.
    assert p.cmd_volume(1, -60)[4] == 0xC4
    assert p.cmd_volume(1, -10)[4] == 0xF6
    assert p.cmd_volume(1, 0)[4] == 0x00
    # clamping
    assert p.cmd_volume(1, -99)[4] == 0xC4
    assert p.cmd_volume(1, 5)[4] == 0x00


def test_mp3_commands_match_official_hex_codes():
    # MP3 Play Function - PP \x02\x00\x00\x04\x0B\x11
    assert p.cmd_mp3(p.DATA_MP3_PLAY_PAUSE) == bytes([0x02, 0x00, 0x00, 0x04, 0x0B, 0x11])
    # MP3 Repeat Loop - OFF \x02\x00\x00\x01\x00\x03
    assert p.cmd_mp3_repeat(False) == bytes([0x02, 0x00, 0x00, 0x01, 0x00, 0x03])


def test_queries_match_hubitat_driver():
    # getId: [2,0,0,8,0,0x0A]
    assert p.cmd_query_id() == bytes([0x02, 0x00, 0x00, 0x08, 0x00, 0x0A])
    # Query All Zones Status \x02\x00\x00\x05\x00\x07
    assert p.cmd_query_all_status() == bytes([0x02, 0x00, 0x00, 0x05, 0x00, 0x07])
    # queryAll: [2,0,1,0x0C,0] + checksum 0x0F
    assert p.cmd_query_everything() == bytes([0x02, 0x00, 0x01, 0x0C, 0x00, 0x0F])
    # getFirmware: [2,0,0,0x0F,0,0x11]
    assert p.cmd_query_firmware() == bytes([0x02, 0x00, 0x00, 0x0F, 0x00, 0x11])


def test_doorbell_matches_official_app():
    # app: ["02","01",zone,"04","A1"] on, ["02","01",zone,"04","A0"] off
    on = p.cmd_doorbell(2, True)
    assert list(on[:5]) == [0x02, 0x01, 0x02, 0x04, 0xA1]
    off = p.cmd_doorbell(2, False)
    assert list(off[:5]) == [0x02, 0x01, 0x02, 0x04, 0xA0]


def test_mp3_source_is_0x7e():
    # app: source 19 (Lync12 v3) and Lync6 source 13 -> 0x7E
    assert p.cmd_source(3, 19)[4] == 0x7E


def _zone_status_frame(zone, d1=0x01, source0=2, vol=0xF6, treble=0x00,
                       bass=0xFB, balance=0x02, d2=0):
    body = bytes([0x02, 0x00, zone, 0x05, d1, d2, 0, 0, source0, vol,
                  treble, bass, balance])
    return body + bytes([p.checksum(body)])


def test_parse_zone_status():
    parser = p.LyncProtocolParser()
    msgs = parser.feed(_zone_status_frame(4))
    assert len(msgs) == 1
    m = msgs[0]
    assert isinstance(m, p.ZoneStatusMsg)
    assert m.zone == 4
    assert m.power is True and m.mute is False and m.dnd is False
    assert m.source == 3          # 0-based on the wire
    assert m.volume_db == -10
    assert m.bass == -5
    assert m.balance == 2


def test_parse_status_flag_combinations():
    parser = p.LyncProtocolParser()
    # power+mute+dnd = bits 0,1,2 -> 0x07 (driver saw 0x87 too: high bit noise)
    m = parser.feed(_zone_status_frame(1, d1=0x07))[0]
    assert m.power and m.mute and m.dnd
    m = parser.feed(_zone_status_frame(1, d1=0x00))[0]
    assert not m.power and not m.mute


def test_parse_concatenated_all_zone_status():
    parser = p.LyncProtocolParser()
    blob = b"".join(_zone_status_frame(z) for z in range(1, 13))
    msgs = parser.feed(blob)
    assert [m.zone for m in msgs] == list(range(1, 13))


def test_parse_split_across_reads():
    parser = p.LyncProtocolParser()
    frame = _zone_status_frame(9)
    assert parser.feed(frame[:5]) == []
    msgs = parser.feed(frame[5:])
    assert len(msgs) == 1 and msgs[0].zone == 9


def test_parse_id_and_firmware():
    parser = p.LyncProtocolParser()
    msgs = parser.feed(b"Lync12")
    assert msgs and isinstance(msgs[0], p.IdMsg) and msgs[0].model == "Lync12"
    body = bytes([0x02, 0x00, 0x00, 0x33] + [0] * 9)
    frame = body + bytes([p.checksum(body)])
    msgs = parser.feed(frame)
    assert msgs and isinstance(msgs[0], p.FirmwareMsg)


def test_parse_zone_name():
    parser = p.LyncProtocolParser()
    name = b"Kitchen\x00\x00\x00"
    body = bytes([0x02, 0x00, 0x05, 0x0D]) + name + bytes([0, 5, 0])
    frame = body + bytes([p.checksum(body)])
    msgs = parser.feed(frame)
    assert msgs and isinstance(msgs[0], p.ZoneNameMsg)
    assert msgs[0].zone == 5 and msgs[0].name == "Kitchen"


def test_parse_source_name():
    parser = p.LyncProtocolParser()
    name = b"Sonos\x00\x00\x00\x00\x00"
    body = bytes([0x02, 0x00, 0x01, 0x0E]) + name + bytes([0, 2, 0])
    frame = body + bytes([p.checksum(body)])
    msgs = parser.feed(frame)
    assert msgs and isinstance(msgs[0], p.SourceNameMsg)
    assert msgs[0].source == 3 and msgs[0].name == "Sonos"


def test_parser_resyncs_after_garbage():
    parser = p.LyncProtocolParser()
    good = _zone_status_frame(2)
    msgs = parser.feed(b"\xff\x03\x99" + good)
    assert len(msgs) == 1 and msgs[0].zone == 2


def test_parser_rejects_bad_checksum_then_recovers():
    parser = p.LyncProtocolParser()
    bad = bytearray(_zone_status_frame(2))
    bad[-1] ^= 0xFF
    msgs = parser.feed(bytes(bad) + _zone_status_frame(3))
    assert [m.zone for m in msgs] == [3]


def test_mp3_file_name_variable_length():
    parser = p.LyncProtocolParser()
    body = bytes([0x02, 0x00, 0x00, 0x11]) + b"track01.mp3" + b"\x00"
    frame = body + bytes([p.checksum(body)])
    msgs = parser.feed(frame)
    assert msgs and msgs[0].event == "file_name" and msgs[0].text == "track01.mp3"


def test_name_set_commands():
    frame = p.cmd_set_zone_name(1, "Zone1")
    # 0x02 0x00 zone 0x06 0x00 + 10 name bytes + 0x00 + checksum = 17
    assert len(frame) == 17
    assert frame[4] == 0x00 and frame[5:10] == b"Zone1"
    frame = p.cmd_set_source_name(1, 1, "DVD")
    assert frame[4] == 0x01 and frame[5:8] == b"DVD"


def test_tone_encodings():
    assert p.cmd_bass(1, -5, p.ToneEncoding.SIGNED)[4] == 0xFB
    assert p.cmd_bass(1, -5, p.ToneEncoding.OFFSET)[4] == 0x7B
    assert p.cmd_balance(1, 18, p.ToneEncoding.OFFSET)[4] == 0x92
    assert p.cmd_treble(1, 10, p.ToneEncoding.SIGNED)[4] == 0x0A




def test_doorbell_ring_signature():
    parser = p.LyncProtocolParser()
    # frame observed during doorbell chime: D1 = 0x64 (bits 5/6 set)
    m = parser.feed(_zone_status_frame(1, d1=0x64))[0]
    assert m.doorbell_signature is True
    # normal frames must not trigger it
    for d1 in (0x00, 0x01, 0x03, 0x07, 0x81, 0x87):
        m = parser.feed(_zone_status_frame(1, d1=d1))[0]
        assert m.doorbell_signature is False, hex(d1)




def test_doorbell_message_0x1f():
    parser = p.LyncProtocolParser()
    # captured from real Lync 12 v3 hardware
    ring = bytes.fromhex("02 00 00 1f 02 00 00 00 00 00 00 00 00 23".replace(" ", ""))
    stop = bytes.fromhex("02 00 00 1f 00 00 00 00 00 00 00 00 00 21".replace(" ", ""))
    msgs = parser.feed(ring)
    assert len(msgs) == 1 and isinstance(msgs[0], p.DoorbellMsg)
    assert msgs[0].active is True and msgs[0].input == 2
    msgs = parser.feed(stop)
    assert msgs[0].active is False and msgs[0].input == 0


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as err:
                failures += 1
                print(f"FAIL {name}: {err}")
    raise SystemExit(1 if failures else 0)
