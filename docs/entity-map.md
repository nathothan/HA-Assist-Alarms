# HA Alarms — Entity Map

Confirmed entity IDs for all voice satellite devices.

---

## Office ReSpeaker (formatBCE firmware)

| Role | Entity ID | Notes |
|---|---|---|
| Assist satellite | `assist_satellite.formatbce_respeaker_lite_assist_satellite` | |
| Media player (raw ESPHome) | `media_player.office_respeaker_media_player` | **Ring loop uses this** |
| Media player (Music Assistant) | `media_player.office_respeaker` | Skipped — Music Assistant wrapper |

---

## Kitchen Voice (HA Voice PE)

| Role | Entity ID | Notes |
|---|---|---|
| Assist satellite | `assist_satellite.home_assistant_voice_09787e_assist_satellite` | |
| Media player (raw) | `media_player.home_assistant_voice_09787e_media_player` | **Ring loop uses this** ✅ confirmed 2026-03-27 |
| Media player (alt/renamed) | `media_player.kitchen_voice_media_player` | May be same device, different name |

---

## Theater ReSpeaker

| Role | Entity ID | Notes |
|---|---|---|
| Assist satellite | `assist_satellite.theater_voice_assist_satellite` | |
| Media player (raw ESPHome) | `media_player.theater_voice_media_player` | **Ring loop uses this** ✅ confirmed 2026-03-27 |
| Media player (alt) | `media_player.theater_voice_media_player_2` | Possibly Music Assistant duplicate — skip |

---

## Living Room Voice

| Role | Entity ID | Notes |
|---|---|---|
| Assist satellite | `assist_satellite.waveshare_audio_3_assist_satellite` | |
| Media player (raw ESPHome) | `media_player.waveshare_audio_3` | **Ring loop uses this** ✅ confirmed 2026-03-27 |
| Media player (renamed/MA) | `media_player.living_room_voice` | Skipped — Music Assistant or renamed |

---

---

## Per-Device Audio Configuration

Audio settings for each satellite are configured in `DEVICE_CONFIG` in
`custom_components/ha_alarms/const.py`. Each entry controls:

| Key | Type | Description |
|---|---|---|
| `sound` | str | Path to the alarm audio file on the HA instance (e.g. `/media/alarms/bedroom_alarm.mp3`) |
| `volume_start` | float | Initial volume when alarm fires (0.0–1.0) |
| `volume_end` | float | Maximum volume reached at end of ramp (0.0–1.0) |
| `volume_ramp` | bool | `True` = gradually increase volume; `False` = start at `volume_start` and hold |

When adding a new satellite, add an entry to `DEVICE_CONFIG` using the confirmed
`assist_satellite.*` entity ID as the key. Recommended bedroom defaults:
`volume_start: 0.15`, `volume_end: 0.75`, `volume_ramp: True`. Common areas can go higher.

The prior media player volume is captured before the alarm fires and restored after
dismissal or snooze — so music playing quietly at bedtime will resume at the same
volume after the alarm is stopped.

Sound files should be placed in `/config/www/alarms/` on the HA instance,
accessible via Samba at `\\homeassistant.local\config\www\alarms\`.
Paths use the format `/local/alarms/filename.mp3`, which the announcer converts to
`http://homeassistant.local:8123/local/alarms/filename.mp3` at ring time.
This plain HTTP URL is served directly by HA without an auth token, which is
required for ESPHome ffmpeg_proxy to reliably fetch the file.

> **Why not `/config/media/alarms/`?** The `media-source://` URIs generated for
> that path include auth-signed tokens that some ESPHome devices fail to fetch
> (HTTP 404 from ffmpeg_proxy). The `/local/` (www/) approach avoids this entirely.

To change the sound file without editing code, use the **Configure** button on the
HA Alarms integration card in **Settings → Devices & Services**. Volume settings
(`volume_start`, `volume_end`, `volume_ramp`) always come from `DEVICE_CONFIG`.

---

## Bedroom Voice (ReSpeaker Lite)

| Role | Entity ID | Notes |
|---|---|---|
| Assist satellite | `assist_satellite.bedroom_voice_assist_satellite` | Confirmed 2026-04-06 |
| Media player (raw ESPHome) | `media_player.bedroom_voice_media_player` | **Ring loop uses this** ✅ confirmed 2026-04-06 |
| Media player (Music Assistant) | `media_player.bedroom_voice` | Skipped — Music Assistant wrapper |

---

## Elodie Voice (ReSpeaker Lite)

| Role | Entity ID | Notes |
|---|---|---|
| Assist satellite | `assist_satellite.elodie_voice_assist_satellite` | Confirmed 2026-04-06 |
| Media player (raw ESPHome) | `media_player.elodie_voice_media_player` | **Ring loop uses this** ✅ confirmed 2026-04-06 |
| Media player (Music Assistant) | `media_player.elodie_voice` | Skipped — Music Assistant wrapper |

---

## New Satellite Onboarding Checklist

1. Flash formatBCE firmware via ESPHome Builder
2. Add to HA via ESPHome device discovery
3. Confirm `assist_satellite.*` entity ID in **Developer Tools → States** (search `assist_satellite`)
4. Add an entry to `DEVICE_CONFIG` in `const.py` with the entity ID, preferred sound file, and volume settings
5. Add entity ID to `docs/entity-map.md`
6. Run `./deploy.sh` and restart HA
7. Test: say **"set an alarm for 2 minutes from now"** on the new device
8. Confirm alarm rings on the correct satellite (not another room)
9. Say **"stop"** to dismiss; confirm volume restores to pre-alarm level

---

## How the Announcer Resolves Media Players

`announcer.py` resolves the media_player entity automatically at ring time via
the HA entity registry — no entity IDs are hardcoded in the code. The lookup:

1. Gets the `device_id` of the `assist_satellite` entity from the registry.
2. Collects all `media_player.*` entities on that same device.
3. **Prefers non-Music-Assistant platforms** (`entry.platform != "music_assistant"`).
4. Falls back to any media_player if all happen to be Music Assistant.

This means when you add a new satellite, no code changes are needed — as long as
the satellite's `assist_satellite` and raw `media_player` entities share the same
HA device, the announcer will find and use the right player automatically.
