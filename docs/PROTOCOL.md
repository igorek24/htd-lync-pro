# HTD Lync 6/12 Serial Protocol — as actually implemented

This documents the wire protocol used by `htd_lync_pro`, including several
behaviors that appear in **no HTD documentation**. Sources, in order of
authority:

1. Live captures from a real **Lync 12, firmware v3** (via GW-SL1, TCP :10006)
2. The official **HTD Lync Android app v1.30.04** (a Cordova app — all
   logic is plain JavaScript in `assets/www/js/commands.js`)
3. HTD *Lync Hex Codes* (V.09.25.14)
4. HTD *Lync Serial Commands — Version 1.1* (⚠ wrong in places, see below)

Serial settings: **38400 8N1**. The GW-SL1 gateway bridges TCP :10006 to the
same byte stream.

## Frame format

```
PC → Lync:  0x02 <reserved> <zone> <command> <data...> <checksum>
Lync → PC:  0x02 0x00 <zone> <command> <data...> <checksum>
checksum = sum of all preceding bytes, mod 256
```

`reserved` is 0x00 except doorbell enable/disable (0x01, see below).
Exception: the **Query ID reply is bare ASCII** (`Lync12` / `Lync6`) with no
framing and no checksum.

## Commands (PC → Lync)

| Command | Frame | Notes |
|---|---|---|
| Query ID | `02 00 00 08 00` | Reply: ASCII `Lync12`/`Lync6` |
| Query firmware | `02 00 00 0F 00` | Reply cmd `0x33` on v3 |
| Query all zone status | `02 00 00 05 00` | Reply: keypad-exist + 14B status per zone |
| Query everything | `02 00 01 0C 00` | Big echo: statuses + zone names + source names + MP3 state |
| Query zone name | `02 00 <z> 0D 00` | |
| Query source name | `02 00 <z> 0E <src-1>` | |
| Power zone on/off | `02 00 <z> 04 57/58` | zone 0 + `55/56` = all on/off |
| Mute on/off | `02 00 <z> 04 1E/1F` | |
| DND on/off | `02 00 <z> 04 59/5A` | |
| **Doorbell enable/disable** | `02 01 <z> 04 A1/A0` | ⚠ reserved byte **0x01** for both (per official app) |
| Source select | `02 00 <z> 04 <code>` | codes below; **also powers the zone on** |
| Party mode source | `02 00 <z> 04 <code>` | app sends per-zone, **not** broadcast |
| Volume set | `02 00 <z> 15 <dB>` | **signed** byte: −60…0 → `0xC4…0x00` |
| Balance set | `02 00 <z> 16 <val>` | signed, −18…+18 (v3) |
| Treble set | `02 00 <z> 17 <val>` | signed, −10…+10 (v3) |
| Bass set | `02 00 <z> 18 <val>` | signed, −10…+10 (v3) |
| Zone name set | `02 00 <z> 06 00 <10B name> 00` | ASCII, NUL padded |
| Source name set | `02 00 <z> 07 <src> <10B name> 00` | each zone has its own source names |
| Recall/Save preset | `02 00 00 0A/0B <1-4>` | hardware "files" |
| MP3 FF/PP/FB/Stop | `02 00 00 04 0A/0B/0C/0D` | |
| MP3 repeat | `02 00 00 01 FF/00` | |

### Source select codes

| Source | Code | Party-mode code |
|---|---|---|
| 1–12 | `0x10`–`0x1B` | `0x36`–`0x41` |
| 13–18 (Lync 12) | `0x63`–`0x68` | `0x69`–`0x6E` |
| MP3 player / Intercom | `0x7E` | — |

`0x7E` selects the **last source**: the built-in MP3 player on Lync 6
(source 13), and on Lync 12 v3 the 19th source, which the app names
**Intercom**.

## Responses (Lync → PC)

| Cmd | Length | Meaning |
|---|---|---|
| `0x05` | 14 | Zone status (below) |
| `0x06` | 14 | Audio & keypad exist bitmaps |
| `0x09` | 6 | MP3 play end |
| `0x0C`/`0x0E` | 18 | Source name (name at [4..13], source index at [15], 0-based) |
| `0x0D` | 18 | Zone name (name at [4..13]) |
| `0x11`/`0x12` | var | MP3 file/artist name (ASCII, NUL-terminated, + checksum) |
| `0x13` / `0x14` | 6 / var | MP3 on / off |
| `0x1B` | 14 | Error (data: 1=volume, 2=balance, 3=treble, 4=bass range) |
| **`0x1F`** | 14 | **Doorbell chime state — undocumented, see below** |
| `0x33` | 14 | Firmware v3 marker |

### Zone status frame (`0x05`, 14 bytes)

```
02 00 <zone> 05 <D1> <D2> <D3> <D4> <input> <vol> <treble> <bass> <balance> <cksum>
```

- **D1**: bit0 power, bit1 mute, bit2 dnd. Bit7 is often set on v3
  (`0x80/0x81` observed) — mask it off.
- **D2**: bit5 party mode (bit7 all-on, bit6 all-off per v1.1 doc)
- **D4**: observed `0x13` (=19) on v3 — appears to be the party/intercom
  input slot
- **input**: 0-based (`0x00` = source 1, `0x12` = source 19/Intercom)
- **vol/treble/bass/balance**: signed bytes (vol −60…0)

## 🔔 Doorbell (undocumented — discovered 2026-07-31)

Pressing a doorbell wired to the unit produces a message that exists in no
HTD document and is ignored by the official app:

```
02 00 00 1F 02 00 00 00 00 00 00 00 00 23   ← chime started, data = input bitmask (0x2 = DB2)
02 00 00 1F 00 00 00 00 00 00 00 00 00 21   ← chime ended
```

During the chime the unit **powers zones on and switches them to the
Intercom source (19)** — except zones with DND on or doorbell disabled —
and **does not revert them** when the chime ends. It pushes the zone
status changes gradually over the chime duration.

`htd_lync_pro` uses `0x1F` for its doorbell binary sensor / event and
snapshots + restores the zone states around the chime.

## ⚠ Where HTD's v1.1 PDF is wrong (firmware v3)

- **Volume set**: PDF says `0x80`-offset (`0x80`=0dB…`0x43`=−61dB).
  Reality (hex-codes doc + app + hardware): **signed** bytes
  (`0x00`=0dB…`0xC4`=−60dB).
- **Balance/treble/bass set**: PDF says `0x80`-offset. Reality (app +
  hardware, no range errors): **signed** bytes.
- **Party mode**: PDF implies broadcast to zone 0. The app sends the
  party-source code to each zone individually.
- **Doorbell enable**: not in the PDF at all; requires reserved byte `0x01`.
- **Zone status input byte**: PDF table is 1-based; the wire is 0-based.
