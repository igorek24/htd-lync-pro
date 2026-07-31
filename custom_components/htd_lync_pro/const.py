"""Constants for the HTD Lync integration."""

DOMAIN = "htd_lync_pro"
MANUFACTURER = "Home Theater Direct"

DEFAULT_PORT = 10006
DEFAULT_NAME = "HTD Lync"

CONF_CONNECTION_TYPE = "connection_type"
CONF_SERIAL_PATH = "serial_path"
CONF_TONE_ENCODING = "tone_encoding"
CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = 0  # seconds; 0 = push only (poll manually via button/service)
CONF_DOORBELL_RESTORE = "doorbell_restore"
DEFAULT_DOORBELL_RESTORE = True
CONF_MAX_ON_VOLUME = "max_power_on_volume"     # keypad 0-60; 0 = disabled
CONF_QUIET_CAP = "quiet_hours_volume"          # keypad 0-60; 0 = disabled
CONF_QUIET_START = "quiet_hours_start"         # "HH:MM"
CONF_QUIET_END = "quiet_hours_end"             # "HH:MM"
CONF_ANNOUNCE_PLAYER = "announce_media_player"  # e.g. media_player.rpi_vlc
CONF_ANNOUNCE_TTS = "announce_tts_entity"       # e.g. tts.piper

CONNECTION_TCP = "tcp"
CONNECTION_SERIAL = "serial"

SERVICE_SET_ZONES = "set_zones"
SERVICE_PARTY_MODE = "party_mode"
SERVICE_ALL_ON = "all_on"
SERVICE_ALL_OFF = "all_off"
SERVICE_RECALL_PRESET = "recall_preset"
SERVICE_SAVE_PRESET = "save_preset"
SERVICE_SET_ZONE_NAME = "set_zone_name"
SERVICE_SET_SOURCE_NAME = "set_source_name"
SERVICE_REFRESH = "refresh"
SERVICE_SNAPSHOT = "snapshot"
SERVICE_RESTORE = "restore"
SERVICE_FOLLOW_ME = "follow_me"
SERVICE_ANNOUNCE = "announce"

ATTR_TO_ZONE = "to_zone"
ATTR_FROM_ZONE = "from_zone"
ATTR_TURN_OFF_SOURCE = "turn_off_source"
ATTR_COPY_VOLUME = "copy_volume"
ATTR_MESSAGE = "message"
ATTR_MEDIA_URL = "media_url"
ATTR_MEDIA_PLAYER = "media_player"
ATTR_TTS_ENTITY = "tts_entity"
ATTR_ANNOUNCE_VOLUME = "volume_level"
ATTR_RESTORE_VOLUME = "restore_volume"

ATTR_ZONES = "zones"
ATTR_SOURCE = "source"
ATTR_VOLUME = "volume"
ATTR_OFFSETS = "offsets"
ATTR_OTHERS_OFF = "others_off"
ATTR_PRESET = "preset"
ATTR_ZONE = "zone"
ATTR_NAME = "name"
