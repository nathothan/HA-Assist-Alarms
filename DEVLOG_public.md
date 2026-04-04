# HA Alarms — Project History

A development history of the HA Alarms integration, written for the public GitHub release. See `DEVLOG.md` in the private repository for the full session-by-session log.

---

## Motivation

This project started as an Alexa replacement. A home with several ESPHome voice satellites (ReSpeaker Lite devices running formatBCE firmware) needed per-room alarms and voice reminders — the kind of thing Alexa handles trivially but that Home Assistant had no clean solution for.

Two existing integrations were evaluated: [HA-Alarms-and-Reminders](https://github.com/omaramin-2000/HA-Alarms-and-Reminders) and HA Alarm Clock. Both installed without errors but voice commands did nothing. A code review identified the root causes and concluded a clean rewrite was the right path.

---

## What Was Wrong With the Reference Integration

A review of the reference codebase found nine structural problems:

1. **No relative-time support** — "in 30 minutes" and "in an hour" silently fail
2. **Closed `{time}` enumeration** — only exact `7AM`-style strings match; almost nothing in real speech does
3. **Two parallel parsers, one unused** — the full `datetime_parser.py` is never called from the intent path
4. **UUID satellite fallback** — five of six intent handlers fall back to `context.id` (a UUID) when `satellite_id` is absent; the UUID gets rejected and the alarm fires to nowhere
5. **Backwards bare-hour heuristic** — assumes hour < 7 → PM; "set alarm for 6" schedules 18:00
6. **`pydub` hard dependency** — imported at the top level; if not installed the entire integration fails to load
7. **Duplicate setup paths** — both `async_setup` (YAML) and `async_setup_entry` (config entry) run on install; services are double-registered
8. **Missed alarms silently dropped** — any item whose scheduled time is in the past is skipped on load with no log message
9. **Double-space in sentence pattern** — `"{task} [(on|in)] [{date}]  at {time}"` has two spaces before `at`

---

## Architecture Decisions

**Config-entry only.** No `async_setup` YAML path. One setup path, no double-registration.

**Wildcard sentence slots.** `{time}`, `{date}`, `{label}`, and `{minutes}` are all wildcards in the sentence YAML. The raw spoken string is passed to `datetime_parser.py` for interpretation. This supports relative time, day names, AM/PM, 24-hour, and word numbers without enumerating every possible form.

**Single parser.** `datetime_parser.py` is the only time/date parser in the codebase. Intent handlers and service handlers both import and call it directly.

**Satellite routing via entity registry.** Each intent handler reads `intent_obj.device_id` and resolves it to an `assist_satellite.*` entity ID via the HA entity registry at call time. Nothing is hardcoded. The same code works for every satellite without configuration.

**Media player resolution via entity registry.** The announcer walks the entity registry at ring time to find the `media_player.*` entity on the same HA device as the satellite. Prefers non-Music-Assistant players to avoid interfering with music playback state.

**No pydub.** Zero extra Python dependencies. Audio is played via `media_player.play_media` with an HTTP URL or `media-source://` URI. Duration detection is not needed because the ring loop restarts playback whenever the media player goes idle.

**Explicit error logging.** Past-due alarms on restart log a warning. Missing satellite logs a warning. Ambiguous bare-hour (e.g. "9") raises `ParseAmbiguousError` so the intent handler can ask "Did you mean 9 AM or 9 PM?" rather than guessing.

**Gradual volume ramp.** Alarm starts at 20% volume and steps up 20% every 30 seconds, capped at 100%. Prior volume is captured and restored when the alarm is stopped or snoozed.

---

## Development History

### Phase 1 — Research and architecture
- Evaluated two existing integrations; identified root causes of failure
- Designed clean architecture addressing all nine problems found
- Created stub files for all modules with full docstrings before writing any implementation

### Phase 2 — Core implementation
- Implemented all modules from scratch: `const.py`, `datetime_parser.py`, `coordinator.py`, `announcer.py`, `intent_handler.py`, `config_flow.py`, `__init__.py`
- `datetime_parser.py` passed 26/26 standalone tests before HA integration
- Sentence YAML uses wildcards throughout; all slots passed raw to the parser

### Phase 3 — First working deployment
- Fixed `manifest.json` invalid fields causing config flow rejection
- Fixed missing `services.yaml` causing startup errors
- Fixed service schema key names (`time` vs `time_str`)
- Fixed satellite extraction: switched from non-existent `context.satellite_id` to `intent_obj.device_id` + entity registry lookup
- Replaced periodic TTS ring loop with continuous `media_player.play_media` loop
- Added sensor platform for dashboard visibility

### Phase 4 — Voice command coverage
- Added date-first phrasing: "set alarm for Saturday at 10am"
- Fixed relative reminders: "remind me in 30 minutes to…"
- Added repeating alarms (daily/weekdays/weekends) with fixed `slots:` injection
- Added word number support: "in two hours", "in an hour", "in ninety minutes"
- Added cancel-by-voice with three-tier resolution: label → time expression → date
- Added list alarms/reminders intents
- Added cancel-all intents

### Phase 5 — Multi-satellite testing
- Confirmed working on four satellites simultaneously: two ReSpeaker Lites, one HA Voice PE, one Waveshare audio board
- All satellites resolve their own media player automatically — no configuration needed
- Added `_MIN_RESTART_INTERVAL` to prevent log spam on devices that report idle after each short clip

### Phase 6 — Polish and release prep
- Gradual volume ramp (20% → 100% over 150 seconds)
- Per-device alarm sounds via `DEVICE_SOUNDS` dict in `const.py`
- Deploy script (`deploy.sh`) for one-command Samba deployment
- Pipeline requirement documented: Intent recognition must be set to "Home Assistant"

---

## Current Feature Set

- Set alarms and reminders by voice — absolute time, relative time, named weekday, date-first phrasing
- Repeating alarms — daily, weekdays, weekends; auto-reschedule after firing
- Gradual volume ramp — 20% → 100% over 150 seconds
- Snooze by voice (while ringing or explicitly); default 5 minutes
- Cancel by label, time expression, or day name
- Cancel all alarms or reminders at once
- List scheduled alarms/reminders by voice
- Per-device alarm sounds configurable per satellite
- Persistent storage — survives HA restarts; missed one-shot alarms cleaned up on load
- Dashboard sensors with item counts and full attribute lists
- No YAML configuration — UI-only setup

---

## Known Limitations

- Per-device sound files require editing `const.py` — no UI yet
- Cancel by label uses substring matching — "cancel Mom reminder" matches "call Mom"
- Browser Assist UI commands have no satellite context; satellite-filtered queries return all-satellite results
- Bedroom satellites (planned additions) not yet confirmed working

---

## Hardware Tested and Confirmed Working

| Device | Satellites tested |
|---|---|
| ReSpeaker Lite with formatBCE firmware | 2× (Office, Theater) |
| Home Assistant Voice PE | 1× (Kitchen) |
| Waveshare ESP32-S3 audio board | 1× (Living Room) |

All four satellites confirmed working simultaneously in a multi-device ring test.
