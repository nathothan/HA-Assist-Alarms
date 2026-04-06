"""Constants for the ha_alarms integration."""
# All domain-level constants, attribute names, service names, default values,
# storage keys, and coordinator signal names live here. Nothing else imports
# from this module's peers, so it is safe to import everywhere without cycles.

DOMAIN = "ha_alarms"

# Storage
STORAGE_KEY = f"{DOMAIN}.storage"
STORAGE_VERSION = 1

# Service names
SERVICE_SET_ALARM = "set_alarm"
SERVICE_CANCEL_ALARM = "cancel_alarm"
SERVICE_SET_REMINDER = "set_reminder"
SERVICE_CANCEL_REMINDER = "cancel_reminder"
SERVICE_SNOOZE = "snooze"
SERVICE_STOP_ALL = "stop_all"

# Item type discriminator
ITEM_TYPE_ALARM = "alarm"
ITEM_TYPE_REMINDER = "reminder"

# Attribute / field names
ATTR_SATELLITE = "satellite"       # assist_satellite.* entity ID
ATTR_TIME = "time"                 # time string as spoken / parsed
ATTR_DATE = "date"                 # date string as spoken / parsed
ATTR_LABEL = "label"               # name spoken aloud at ring time
ATTR_REPEAT = "repeat"             # once | daily | weekdays | weekends
ATTR_SNOOZE_MINUTES = "snooze_minutes"
ATTR_SOUND = "sound"               # media path or full HTTP URL
ATTR_VOLUME_START = "volume_start" # initial volume when alarm fires (0.0–1.0)
ATTR_VOLUME_END = "volume_end"     # maximum volume to ramp to (0.0–1.0)
ATTR_VOLUME_RAMP = "volume_ramp"   # True = ramp gradually; False = hold at volume_start

# Repeat values
REPEAT_ONCE = "once"
REPEAT_DAILY = "daily"
REPEAT_WEEKDAYS = "weekdays"
REPEAT_WEEKENDS = "weekends"

# Defaults
DEFAULT_SNOOZE_MINUTES = 5
DEFAULT_ALARM_SOUND = "/local/alarms/ship_chime.mp3"
DEFAULT_VOLUME_START = 0.2
DEFAULT_VOLUME_END = 1.0
DEFAULT_VOLUME_RAMP = True

# Per-device audio configuration.
# Maps assist_satellite entity ID → dict with sound, volume_start, volume_end,
# and volume_ramp settings.  coordinator.schedule_item() reads this dict and
# stores the resolved values in each item so the announcer has them at fire time.
#
# sound        — HA www path (/local/alarms/...) or full HTTP URL.
#                Files live in /config/www/alarms/ on the HA instance
#                (Samba: \\homeassistant.local\config\www\alarms\).
#                Served at http://homeassistant.local:8123/local/alarms/... without
#                auth tokens — required for ESPHome ffmpeg_proxy to fetch them.
#                NOTE: /config/media/ requires HA auth tokens; ESPHome cannot
#                supply these, so sound files must live in /config/www/ instead.
# volume_start — volume set immediately when the alarm fires (0.0–1.0).
# volume_end   — maximum volume the ramp stops at (0.0–1.0).
# volume_ramp  — True = step +20% every 30 s from volume_start to volume_end;
#                False = hold at volume_start for the entire ring.
#
# To add a new satellite: add an entry here, then restart HA.
# Falls back to DEFAULT_* values for any key not specified.
DEVICE_CONFIG: dict[str, dict] = {
    "assist_satellite.formatbce_respeaker_lite_assist_satellite": {
        "name": "Office",
        "sound": "/local/alarms/ship_chime.mp3",
        "volume_start": 0.2,
        "volume_end": 1.0,
        "volume_ramp": True,
    },
    "assist_satellite.home_assistant_voice_09787e_assist_satellite": {
        "name": "Kitchen",
        "sound": "/local/alarms/ship_chime.mp3",
        "volume_start": 0.5,
        "volume_end": 1.0,
        "volume_ramp": True,
    },
    "assist_satellite.theater_voice_assist_satellite": {
        "name": "Theater",
        "sound": "/local/alarms/ship_chime.mp3",
        "volume_start": 1.0,
        "volume_end": 1.0,
        "volume_ramp": False,
    },
    "assist_satellite.waveshare_audio_3_assist_satellite": {
        "name": "Living Room",
        "sound": "/local/alarms/ship_chime.mp3",
        "volume_start": 0.2,
        "volume_end": 1.0,
        "volume_ramp": True,
    },
    "assist_satellite.bedroom_voice_assist_satellite": {
        "name": "Bedroom",
        "sound": "http://homeassistant.local:8123/local/alarms/ship_chime.mp3",
        "volume_start": 0.1,
        "volume_end": 0.6,
        "volume_ramp": True,
    },
    "assist_satellite.elodie_voice_assist_satellite": {
        "name": "Elodie",
        "sound": "http://homeassistant.local:8123/local/alarms/ship_chime.mp3",
        "volume_start": 0.1,
        "volume_end": 0.6,
        "volume_ramp": True,
    },
}

# Dispatcher signal — fired by the coordinator when the item list changes
SIGNAL_ITEMS_UPDATED = f"{DOMAIN}_items_updated"
