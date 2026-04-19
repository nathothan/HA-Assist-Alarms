# HA Alarms

Voice-triggered alarms and reminders for Home Assistant, designed for homes with ESPHome voice satellites. Set, snooze, and cancel alarms entirely by voice — no app, no phone, no screen required.

HA Alarms integrates with the HA Assist pipeline so that each satellite handles its own alarms independently. An alarm set on the bedroom satellite rings on the bedroom satellite; an alarm set in the kitchen rings in the kitchen. The integration stores all items persistently, announces them via TTS, plays a continuous alarm sound through the device's media player, and ramps volume gradually so you actually wake up.

---

## Features

- **Set alarms and reminders by voice** — absolute times, relative times, named weekdays, and AM/PM all work naturally
- **Repeating alarms** — daily, weekdays, or weekends; auto-reschedule after firing
- **Gradual volume ramp** — starts at 20% and increases by 20% every 30 seconds, capped at 100%
- **Snooze** — by voice while the alarm is ringing, or by explicit command; default 5 minutes
- **Cancel by label or time** — "cancel my 9 AM alarm", "cancel my Tuesday alarm", "cancel my call Mom reminder"
- **Cancel all** — stop every scheduled alarm or reminder at once
- **List alarms/reminders** — ask what's set and get a spoken summary
- **Multi-satellite** — each device manages its own items independently; no cross-talk
- **Persistent storage** — survives HA restarts; missed one-shot alarms are cleaned up automatically; repeating alarms advance to the next occurrence
- **Dashboard sensors** — two sensor entities expose item counts and details for use in Lovelace cards
- **No YAML configuration** — set up entirely through the HA UI

---

## Supported Hardware

Any ESPHome-based voice satellite that creates an `assist_satellite.*` entity in Home Assistant will work. Tested devices:

| Device | Notes |
|---|---|
| [ReSpeaker Lite](https://wiki.seeedstudio.com/reSpeaker_lite_introduction/) with [formatBCE firmware](https://github.com/formatBCE/ReSpeaker-Lite-Home-Assistant-integration) | Primary development device |
| [Home Assistant Voice Preview Edition](https://www.home-assistant.io/voice-pe/) (HAVPE) | Fully supported |
| Waveshare ESP32-S3 audio boards | Confirmed working |
| Any ESPHome device with `assist_satellite` + `media_player` entities on the same HA device | Should work automatically |

The integration automatically discovers the correct media player for each satellite via the HA entity registry — no entity IDs need to be configured.

---

## Requirements

- **Home Assistant 2026.1.0** or newer
- At least one ESPHome voice satellite with an `assist_satellite.*` entity
- The **Anthropic Conversation** integration (or another HA-supported LLM) configured as your pipeline's conversation agent — voice commands use intent matching but the satellite pipeline needs a conversation agent for freeform fallback
- An alarm sound file placed in `/config/www/alarms/` on your HA instance
- TTS configured in HA (Nabu Casa Cloud TTS, Piper, or any HA-supported TTS engine)

---

## Installation

### HACS (recommended)

1. Open HACS → **Integrations** → three-dot menu → **Custom repositories**
2. Add this repository URL, category **Integration**
3. Search for "HA Alarms" and install
4. Restart Home Assistant

### Manual

1. Copy the `custom_components/ha_alarms/` directory into your HA `config/custom_components/` directory
2. Copy `config/custom_sentences/en/ha_alarms.yaml` into your HA `config/custom_sentences/en/` directory (create the directory if it doesn't exist)
3. Restart Home Assistant

---

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **HA Alarms** and click it
3. Follow the setup steps — no YAML required

The integration will create two sensor entities (`sensor.ha_alarms` and `sensor.ha_reminders`) that you can use in dashboards.

### Alarm sound

Place your alarm sound files in `/config/www/alarms/` on your HA instance (accessible via Samba at `\\homeassistant.local\config\www\alarms\`). They are served at `/local/alarms/...` — this path works without auth tokens, which is required for ESPHome's ffmpeg_proxy to fetch them. Files placed in `/config/media/` require HA auth tokens that ESPHome devices cannot supply, so that path will not work.

Per-device sounds, names, and volume settings are configured in `custom_components/ha_alarms/const.py` in the `DEVICE_CONFIG` dict — map each `assist_satellite.*` entity ID to settings:

```python
DEVICE_CONFIG: dict[str, dict] = {
    "assist_satellite.my_bedroom_satellite": {
        "name": "Bedroom",
        "sound": "/local/alarms/ship_chime.mp3",
        "volume_start": 0.2,
        "volume_end": 1.0,
        "volume_ramp": True,
    },
    "assist_satellite.my_kitchen_satellite": {
        "name": "Kitchen",
        "sound": "/local/alarms/ship_chime.mp3",
        "volume_start": 0.5,
        "volume_end": 1.0,
        "volume_ramp": True,
    },
}
```

- `name` — friendly name shown in dashboard cards and spoken satellite attribution
- `sound` — `/local/alarms/` path to the sound file (must be in `/config/www/alarms/`)
- `volume_start` / `volume_end` — volume range for the gradual ramp (0.0–1.0)
- `volume_ramp` — `True` steps +20% every 30 s from start to end; `False` holds at `volume_start`

The `DEFAULT_ALARM_SOUND` constant is used for any satellite not in `DEVICE_CONFIG`. After editing `const.py`, restart Home Assistant to pick up the changes.

### Pipeline requirement

Your HA voice pipeline's **Conversation agent** must be set to **Home Assistant** (the built-in one) — not Claude, Gemini, or any other LLM. When an LLM is set as the conversation agent it handles all voice input directly, bypassing HA's sentence matching engine entirely, which means custom intents like those used by this integration will never fire.

To check: **Settings → Voice Assistants → Pipelines → (your pipeline) → Edit** — the Conversation agent must be set to "Home Assistant", not an LLM integration.

---

## Voice Commands

All commands are spoken to any configured HA Assist satellite. Commands are routed to the satellite that heard them — alarms set from the bedroom ring in the bedroom.

### Setting alarms

```
set an alarm for 7 AM
set an alarm for 7:30 tomorrow morning
wake me up at 6:45
wake me up on Saturday at 10 AM
set an alarm in 2 hours
wake me up in 45 minutes

set a daily alarm for 6 AM
set a weekday alarm for 7 AM
set a weekend alarm for 9 AM
wake me up every day at 6:30
```

### Setting reminders

```
remind me to call Mom at 7 PM
remind me to take out the trash at 9 AM on Monday
set a reminder to pick up dry cleaning at 5 PM
remind me in 30 minutes to check the oven
remind me in 2 hours to take my medication
```

### While an alarm is ringing

```
snooze
snooze for 10 minutes
give me 5 more minutes
stop the alarm
dismiss the alarm
```

### Cancelling

```
cancel my 7 AM alarm
cancel my Tuesday alarm
cancel my call Mom reminder
cancel all my alarms
cancel all my reminders
```

### Listing

```
what alarms do I have set?
list my alarms
what time is my alarm?
do I have any alarms set?
what reminders do I have?
```

---

## Dashboard

The integration creates two sensors that work well with a Markdown card:

```yaml
type: markdown
content: >
  {% set alarms = state_attr('sensor.ha_alarms', 'items') | default([]) %}
  {% set reminders = state_attr('sensor.ha_reminders', 'items') | default([]) %}

  ## 🔔 Alarms
  {% if alarms %}
  {% for a in alarms %}
  - **{{ a.label }}** — {{ a.when }} {{ a.status }}{% if a.repeat != 'once' %} · repeats {{ a.repeat }}{% endif %} · 📍 {{ a.satellite_name | default('Unknown') }}
  {% endfor %}
  {% else %}
  *No alarms scheduled.*
  {% endif %}

  ## 📝 Reminders
  {% if reminders %}
  {% for r in reminders %}
  - **{{ r.label }}** — {{ r.when }} {{ r.status }} · 📍 {{ r.satellite_name | default('Unknown') }}
  {% endfor %}
  {% else %}
  *No reminders scheduled.*
  {% endif %}
```

`satellite_name` is resolved from `DEVICE_CONFIG` in `const.py` — adding a new satellite there automatically populates it in the card without editing the card YAML.

---

## Known Limitations

- **Alarm sounds require manual config** — per-device sound files are configured by editing `const.py`. There is no UI for this yet.
- **Pipeline intent recognition must be enabled** — see Configuration above. LLM-only pipelines bypass custom sentences.
- **Cancel by label matches substrings** — "cancel my Mom reminder" will match a reminder labelled "call Mom". Intended behaviour, but be aware if you have similarly named items.
- **Browser Assist UI has no satellite context** — commands issued through the HA Assist UI in the browser have no device_id, so they are not routed to a satellite and some satellite-filtered commands (like "list my alarms") will return results across all satellites.
- **ReSpeaker LED occasionally gets stuck** — after voice interactions the ReSpeaker LED may stay in slow-pulse white despite the satellite showing idle. Power cycling the device clears it. This is a firmware issue unrelated to HA Alarms.

---

## Services

For automation use, the integration exposes the following services:

| Service | Description |
|---|---|
| `ha_alarms.set_alarm` | Schedule an alarm with optional label, repeat, and satellite |
| `ha_alarms.set_reminder` | Schedule a reminder with a spoken label |
| `ha_alarms.cancel_alarm` | Cancel the next scheduled alarm |
| `ha_alarms.cancel_reminder` | Cancel the next scheduled reminder |
| `ha_alarms.snooze` | Snooze the currently ringing alarm |
| `ha_alarms.stop_all` | Stop all currently ringing alarms and reminders |
| `ha_alarms.purge` | Remove any items stuck in "missed" status |

---

## Contributing

Pull requests are welcome. Before opening one:

1. Run through the voice commands in the Usage section manually against a real satellite
2. Check the HA log for any new `ERROR` or `WARNING` lines from `ha_alarms`
3. Update `DEVLOG.md` with a brief note on what changed and why

---

## License

MIT — see [LICENSE](LICENSE).
