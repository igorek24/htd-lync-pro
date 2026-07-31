#!/usr/bin/env python3
"""Minimal HTD Lync 12 (firmware v3) emulator for integration testing.

Listens on TCP :10006 like a GW-SL1 gateway and simulates 12 zones with
names, source names, and the built-in MP3 player.

Usage: python3 tools/lync_emulator.py [port]
"""

import asyncio
import functools
import builtins

print = functools.partial(builtins.print, flush=True)
import sys

ZONE_NAMES = [
    "Pool", "Sunroom", "Kitchen", "Bathroom", "LivingRoom", "Master",
    "Garage", "Office", "Patio", "Gym", "Theater", "Guest",
]
SOURCE_NAMES = [
    "Sonos", "TV", "MP3", "Radio", "Aux1", "Aux2",
    "Source 7", "Source 8", "Source 9", "Source 10", "Source 11", "Source 12",
    "Source 13", "Source 14", "Source 15", "Source 16", "Source 17", "Source 18",
]

SOURCE_SELECT = {
    **{0x10 + i: i + 1 for i in range(12)},
    **{0x63 + i: i + 13 for i in range(6)},
    0x7E: 19,  # built-in MP3 player
}
PARTY_SELECT = {
    **{0x36 + i: i + 1 for i in range(12)},
    **{0x69 + i: i + 13 for i in range(6)},
}


def cksum(b: bytes) -> bytes:
    return bytes([sum(b) & 0xFF])


class Zone:
    def __init__(self, num: int):
        self.num = num
        self.power = False
        self.mute = False
        self.dnd = False
        self.source = 1
        self.volume = -40  # dB
        self.treble = 0
        self.bass = 0
        self.balance = 0

    def status_frame(self) -> bytes:
        d1 = (self.power * 0x01) | (self.mute * 0x02) | (self.dnd * 0x04)
        body = bytes([
            0x02, 0x00, self.num, 0x05, d1, 0, 0, 0,
            self.source - 1,
            self.volume & 0xFF, self.treble & 0xFF,
            self.bass & 0xFF, self.balance & 0xFF,
        ])
        return body + cksum(body)


class Emulator:
    def __init__(self):
        self.zones = {n: Zone(n) for n in range(1, 13)}
        self.mp3_playing = False
        self.writers = set()

    def broadcast(self, data: bytes):
        for w in list(self.writers):
            try:
                w.write(data)
            except Exception:
                self.writers.discard(w)

    def doorbell_ring_frame(self, active: bool = True) -> bytes:
        """Doorbell chime message 0x1F, as captured from a real Lync 12 v3."""
        body = bytes([0x02, 0x00, 0x00, 0x1F, 0x02 if active else 0x00]
                     + [0] * 8)
        return body + cksum(body)

    def zone_name_frame(self, zone: int) -> bytes:
        name = ZONE_NAMES[zone - 1].encode()[:10].ljust(10, b"\x00")
        body = bytes([0x02, 0x00, zone, 0x0D]) + name + bytes([0, zone, 0])
        return body + cksum(body)

    def source_name_frame(self, zone: int, source: int) -> bytes:
        name = SOURCE_NAMES[source - 1].encode()[:10].ljust(10, b"\x00")
        body = bytes([0x02, 0x00, zone, 0x0E]) + name + bytes([0, source - 1, 0])
        return body + cksum(body)

    def handle(self, frame: bytes) -> bytes:
        out = bytearray()
        zone_addr, cmd = frame[2], frame[3]
        data = frame[4] if len(frame) > 4 else 0

        if cmd == 0x08:  # query ID
            out += b"Lync12"
        elif cmd == 0x0F:  # firmware
            body = bytes([0x02, 0x00, 0x00, 0x33] + [0] * 9)
            out += body + cksum(body)
        elif cmd == 0x05:  # all zone status
            for z in self.zones.values():
                out += z.status_frame()
        elif cmd == 0x0C:  # query everything
            for z in self.zones.values():
                out += z.status_frame()
            for n in self.zones:
                out += self.zone_name_frame(n)
            for s in range(1, 19):
                out += self.source_name_frame(1, s)
        elif cmd == 0x0D:
            out += self.zone_name_frame(zone_addr)
        elif cmd == 0x0E:
            out += self.source_name_frame(zone_addr, data + 1)
        elif cmd == 0x15:  # volume
            z = self.zones.get(zone_addr)
            if z:
                z.volume = data - 256 if data > 127 else data
                out += z.status_frame()
        elif cmd in (0x16, 0x17, 0x18):  # balance/treble/bass
            z = self.zones.get(zone_addr)
            if z:
                val = data - 256 if data > 127 else data
                if cmd == 0x16:
                    z.balance = val
                elif cmd == 0x17:
                    z.treble = val
                else:
                    z.bass = val
                out += z.status_frame()
        elif cmd == 0x04:
            out += self.common(zone_addr, data)
        return bytes(out)

    def common(self, zone_addr: int, data: int) -> bytes:
        out = bytearray()
        if data in (0x55, 0x56):  # all on/off
            for z in self.zones.values():
                z.power = data == 0x55
                out += z.status_frame()
        elif data in (0x57, 0x58):
            z = self.zones.get(zone_addr)
            if z:
                z.power = data == 0x57
                out += z.status_frame()
        elif data in (0x1E, 0x1F):
            z = self.zones.get(zone_addr)
            if z:
                z.mute = data == 0x1E
                out += z.status_frame()
        elif data in (0x59, 0x5A):
            z = self.zones.get(zone_addr)
            if z:
                z.dnd = data == 0x59
                out += z.status_frame()
        elif data in SOURCE_SELECT:
            z = self.zones.get(zone_addr)
            if z:
                z.source = SOURCE_SELECT[data]
                z.power = True
                out += z.status_frame()
        elif data in PARTY_SELECT:
            targets = (
                [self.zones[zone_addr]] if zone_addr in self.zones
                else list(self.zones.values())
            )
            for z in targets:
                z.source = PARTY_SELECT[data]
                z.power = True
                out += z.status_frame()
        elif data == 0xA2:  # emulator-only: simulate a doorbell ring
            # like the real unit: chime powers zones on, routes to source 19,
            # and does NOT revert afterwards
            self.broadcast(self.doorbell_ring_frame(True))
            for z in self.zones.values():
                z.power = True
                z.source = 19
                self.broadcast(z.status_frame())
            asyncio.get_event_loop().call_later(
                3, lambda: self.broadcast(self.doorbell_ring_frame(False))
            )
        elif data == 0x0B:  # MP3 play/pause
            self.mp3_playing = not self.mp3_playing
            code = 0x13 if self.mp3_playing else 0x14
            body = bytes([0x02, 0x00, 0x00, code, 0x00])
            out += body + cksum(body)
            if self.mp3_playing:
                body = bytes([0x02, 0x00, 0x00, 0x11]) + b"demo_track.mp3\x00"
                out += body + cksum(body)
        return bytes(out)


async def client_loop(emu: Emulator, reader, writer):
    peer = writer.get_extra_info("peername")
    print(f"connected: {peer}")
    emu.writers.add(writer)
    buf = bytearray()
    try:
        while True:
            chunk = await reader.read(256)
            if not chunk:
                break
            buf.extend(chunk)
            while len(buf) >= 6 and buf[0] == 0x02:
                # inbound command frames are 6 bytes (except name-set: 17)
                length = 17 if buf[3] in (0x06, 0x07) else 6
                if len(buf) < length:
                    break
                frame = bytes(buf[:length])
                del buf[:length]
                reply = emu.handle(frame)
                print(f"RX {frame.hex(' ')} -> {len(reply)}B")
                if reply:
                    writer.write(reply)
                    await writer.drain()
            if buf and buf[0] != 0x02:
                buf.pop(0)
    finally:
        print(f"disconnected: {peer}")
        emu.writers.discard(writer)
        writer.close()


async def main(port: int):
    emu = Emulator()
    server = await asyncio.start_server(
        lambda r, w: client_loop(emu, r, w), "0.0.0.0", port
    )
    print(f"Lync12 emulator listening on :{port}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10006))
