# Changelog

## 0.1.0 — 2026-07-31

Initial release. Verified against a real HTD Lync 12 (firmware v3) over a
GW-SL1 gateway.

- Per-zone media players with real zone/source names from the unit
- Bass / treble / balance / keypad-volume number entities
- DND and doorbell-enable switches per zone
- Inline source `select` entity per zone
- All-zones on/off, hardware preset recall buttons, refresh button
- Built-in MP3 player entity (transport, repeat, file/artist)
- **Doorbell ring detection** via the undocumented `0x1F` message:
  binary sensor + `htd_lync_pro_doorbell` event with `doorbell_input`
- **Automatic post-doorbell restore** of zone power/source/volume
  (optional, default on)
- Party scene service `set_zones` (zones + source + base volume +
  per-zone offsets), `party_mode`, `all_on`/`all_off`,
  `recall_preset`/`save_preset`, `set_zone_name`/`set_source_name`,
  `refresh`
- TCP (GW-SL1) and RS-232 serial connections; config flow with
  reconfigure (change IP without losing entities) and options
  (poll interval, doorbell restore, tone encoding)
- Live device-name sync from the unit
- Protocol test suite and a Lync 12 emulator for development

## 0.2.0 — 2026-07-31

- `snapshot` / `restore` services — save and re-apply all zone states
- `follow_me` service + automation blueprint (`blueprints/follow_me.yaml`):
  presence-based music that moves room to room, with excluded zones,
  volume copy/offset, source-zone turn-off, and time-window options
- `announce` service — TTS or media through a configurable announcement
  player (designed for amp override-RCA setups), with volume set and
  automatic restore
- Power-on volume cap and quiet-hours cap options
- Diagnostics support (Download Diagnostics on the integration entry)
- Ready-made dashboard view in `docs/dashboard.yaml`

## 0.2.1 — 2026-07-31

- Ship brand icons inside the integration (`custom_components/htd_lync_pro/brand/`)
  per the new Home Assistant 2026.3+ mechanism — the integration icon now
  displays without a central brands-repo entry
- Add MIT license, CI validation (HACS + hassfest + protocol tests), wiki
