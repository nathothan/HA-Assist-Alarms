# HA Alarms & Reminders — Dev Log

## Known Hardware Issues

> **ReSpeaker LED stuck in slow-pulse white** — Occasionally the ReSpeaker LED gets stuck in slow-pulse white after voice interactions, despite the assist_satellite entity showing idle in HA. Power cycle clears it. Suspected formatBCE firmware LED script state issue, not related to ha_alarms.

## Pipeline Requirements

> **Intent recognition must be set to "Home Assistant"** — ha_alarms relies on HA's sentence matching engine to route voice commands to the correct intent handler. In Settings → Voice Assistants → Pipelines → (your pipeline) → Edit, the "Intent recognition" step must be set to "Home Assistant". If it is set to "None", all commands bypass sentence matching and go directly to the LLM conversation agent, which cannot call custom intents — resulting in responses like "I'm afraid setting alarms isn't working." This affects any custom sentence-based integration, not just ha_alarms. Pipelines configured for local Whisper/Piper/Wyoming often default to None for this step.

---

## Session 10 — 2026-04-03

### Added Bedroom 2 satellite

Added `assist_satellite.bedroom2_voice_assist_satellite` to `DEVICE_CONFIG` in
`const.py` with `name: "Bedroom 2"`. Volume settings match Bedroom
(`volume_start: 0.15`, `volume_end: 0.75`, `volume_ramp: True`). Sound path
`/local/alarms/ship_chime.mp3` → `http://homeassistant.local:8123/local/alarms/ship_chime.mp3`
via the standard `/local/` resolution path established in Session 9d.

The `satellite_name` attribute exposed by sensor.py will now show "Bedroom 2"
in the Lovelace dashboard card automatically.

---

## Session 9d — 2026-04-03

### Sound file location: /config/www/alarms/ is mandatory for ESPHome

**Root cause confirmed:** HA's `/media/` URL path requires an auth token.
`http://homeassistant.local:8123/media/alarms/ship_chime.mp3` returns 401/404
for unauthenticated requests. ESPHome devices fetch audio via ffmpeg_proxy —
an unauthenticated HTTP client — so they can never retrieve files served from
`/config/media/`.

**Final settled configuration:**
- Sound files live in `/config/www/alarms/` (Samba: `config\www\alarms\`).
- Paths in `const.py` use `/local/alarms/` prefix.
- `_resolve_sound_url` converts `/local/...` → `http://homeassistant.local:8123/local/...`,
  a no-auth static file URL that ESPHome ffmpeg_proxy can fetch reliably.
- `/media/...` paths (from stored items or options flow overrides) are rewritten
  to `/local/alarms/<filename>` so they continue to work without a storage wipe.

Do not move sound files to `/config/media/alarms/` — they will silently fail
to play on all ESPHome-based satellites.

---

## Session 9c — 2026-04-03

### Sound file location: settled on /config/media/alarms/

After several iterations (www → media → back to media), the final configuration:

- Sound files live in `/config/media/alarms/` (Samba: `config\media\alarms\`).
- Paths in `const.py` use the `/media/alarms/` prefix.
- `_resolve_sound_url` in `announcer.py` converts any `/media/...` or `/local/...`
  path to `http://homeassistant.local:8123<path>` — a plain HTTP URL the ESPHome
  ffmpeg_proxy can fetch directly.
- `/config/www/alarms/` was deleted; nothing outside ha_alarms referenced it.
- `DEFAULT_ALARM_SOUND` and all five `DEVICE_CONFIG` sound entries updated to
  `/media/alarms/ship_chime.mp3`.

The `/local/` prefix is retained as a backward-compatible alias in
`_resolve_sound_url` so that any stored alarm items written during the
short-lived www phase resolve without a storage wipe.

---

## Session 9b — 2026-04-02

### What we accomplished

Root-caused and fixed the bedroom satellite sound failure; eliminated the
hardcoded `device_names` dict from the Lovelace card.

### Bugs found and fixed

#### Sound failure root cause: `media-source://` auth token 404 from ffmpeg_proxy

**Symptom:** HA log showed repeated:
```
ERROR homeassistant.components.esphome.ffmpeg_proxy
HTTP error 404 Not Found
Error opening input file http://homeassistant.local:8123/media/local/alarms/ship_chime.mp3?authSig=...
```
Every 3 seconds (matching `_MIN_RESTART_INTERVAL`). The media_player was found,
`play_media` was called, and the ESPHome ffmpeg_proxy was activated — but the
auth-signed URL HA generated for the `media-source://` URI returned 404 when
the ESPHome device tried to fetch it. The file exists on disk; the issue was
in HA's media-source signed URL handling for this specific ESPHome device.

**Fix:** Moved all sound files from `/config/media/alarms/` to `/config/www/alarms/`
and changed all sound paths from `/media/alarms/...` to `/local/alarms/...`.
The `/local/` prefix is served by HA as a plain HTTP URL
(`http://homeassistant.local:8123/local/alarms/...`) without auth tokens —
the same approach the original integration used before the media-source refactor.
Updated `_resolve_sound_url` to convert `/local/` paths to direct HTTP URLs.
Updated `DEFAULT_ALARM_SOUND` and all `DEVICE_CONFIG` entries accordingly.

The `media-source://` path in `_resolve_sound_url` is retained for
backward-compatibility with options flow overrides or service call payloads
that may still use `/media/` paths, but all built-in defaults now use `/local/`.

#### "Unknown" satellite label in Lovelace card

**Root cause:** The user's Lovelace card had a hardcoded `device_names` dict that
did not include the bedroom satellite entity ID. Any new satellite would also
show "Unknown" until the dict was manually updated in the card YAML.

**Fix:** Added `satellite_name` to sensor item attributes. sensor.py now looks up
`DEVICE_CONFIG.get(satellite_id, {}).get("name")` and includes the result in
every item dict. Adding a new satellite to `DEVICE_CONFIG` (with a `name` field)
now automatically propagates to the dashboard card — no card YAML edits needed.

Updated README Lovelace template to use `a.satellite_name | default('Unknown')`
instead of a local `device_names` dict. The user's existing card can be updated
by replacing the `device_names` block with `{{ a.satellite_name | default('Unknown') }}`.

---

## Session 9 — 2026-04-02

### What we accomplished

Added bedroom satellite to the integration and fixed a silent TTS-only
fallback that masked missing media_player entities with no log output.

### Bugs found and fixed

#### Issue 1: Bedroom satellite shows as "Unknown" device

**Root cause:** `assist_satellite.bedroom_voice_assist_satellite` was absent
from `DEVICE_CONFIG` in `const.py`. Satellites not in `DEVICE_CONFIG` have no
named entry in the integration's device list — volume settings fall back to
defaults and the satellite is unrecognised in any device label lookups.

**Fix:** Added bedroom satellite to `DEVICE_CONFIG` with bedroom-appropriate
volume settings: `volume_start: 0.15`, `volume_end: 0.75`, `volume_ramp: True`.
Added a `name` field to all `DEVICE_CONFIG` entries ("Office", "Kitchen",
"Theater", "Living Room", "Bedroom") for use in future label lookups.

#### Issue 2: Alarm fires but plays no sound

**Root cause:** When `_get_media_player_id()` returns `None` (no `media_player.*`
entity found on the same HA device as the satellite), `use_media = False` and the
ring loop runs in TTS-only mode. The fallback was logged at `DEBUG` level — it
never appeared in the normal HA log, so there was no indication that sound was
being skipped.

**Fix:** Upgraded the "no media_player found" log from `DEBUG` to `WARNING` with
an actionable message pointing to Settings → Devices & Services. The warning only
fires when a sound URL is present (i.e. sound was expected but couldn't play).

**Likely underlying cause for the bedroom device:** the satellite's
`assist_satellite.*` and `media_player.*` entities may not yet share the same HA
device_id. This is a HA device registry issue, not a code issue. To confirm:
set a test alarm, check the HA log for the new WARNING message. If it appears,
check Settings → Devices & Services and ensure both entities are on the same
device. If they are already linked, the media_player entity may not have been
fully registered at the time the alarm fired; a HA restart after device discovery
typically resolves this.

### Also changed

- `entity-map.md` — bedroom satellite section updated with confirmed entity ID,
  media_player TBD note, and troubleshooting guidance for the TTS-only fallback.

### Known gaps carried forward

1. **Bedroom media_player entity** — unconfirmed; needs a test alarm to verify
   `ha_alarms: using media_player` appears in the HA log.
2. **Volume settings have no UI** — `volume_start`, `volume_end`, `volume_ramp`
   require editing `const.py`.
3. **Second and Third Bedroom satellites** — hardware not yet installed.

---

## Session 8 — 2026-04-01

### What we accomplished

Per-device alarm sound configuration moved to the HA UI via an options flow,
then extended to full per-device volume control via a new `DEVICE_CONFIG` dict
in `const.py`.

### Changes made

#### Options flow for alarm sounds

Added `OptionsFlowHandler` to `config_flow.py`. A "Configure" button now
appears on the integration card in **Settings → Devices & Services**. It shows
one text field per discovered `assist_satellite.*` entity, pre-populated with
the current saved value, the `DEVICE_CONFIG` default, or `DEFAULT_ALARM_SOUND`.
Sound set through the UI overrides `DEVICE_CONFIG` for that satellite.

#### Per-device volume control — `DEVICE_CONFIG` in const.py

`DEVICE_SOUNDS` dict replaced by `DEVICE_CONFIG`, which adds three volume fields
per satellite:

- `volume_start` — volume set immediately when the alarm fires
- `volume_end` — maximum volume the ramp stops at
- `volume_ramp` — `True` = step +20% every 30 s; `False` = hold at `volume_start`

coordinator.schedule_item() reads `DEVICE_CONFIG` and stores all four audio
fields in the item dict so the announcer has them at fire time.

#### Volume ramp refactored in announcer.py

Hardcoded `_VOLUME_START = 0.20` and cap at 1.0 replaced with item-level
`ATTR_VOLUME_START`, `ATTR_VOLUME_END`, `ATTR_VOLUME_RAMP` lookups (with
`DEFAULT_*` fallbacks). When `volume_ramp` is `False` the ramp loop skips the
step logic entirely and holds at `volume_start` for the whole ring.

Prior volume capture and restore on stop/snooze was already in place; it now
correctly handles the "music playing quietly at bedtime" case — the alarm rings
at the configured level, and when dismissed volume returns to whatever it was
before the alarm.

### Current DEVICE_CONFIG state

Theater satellite: `volume_ramp: False`, `volume_start: 1.0` — rings at full
volume immediately, no ramp. All others: ramp from 0.2 → 1.0 (or 0.5 → 1.0
for Kitchen Voice PE). Sound files all still pointing to `ship_chime.mp3`
pending custom file selection.

### Known gaps carried forward

1. **Volume settings have no UI** — `volume_start`, `volume_end`, `volume_ramp`
   require editing `const.py`. Sound override is available via the options flow.
2. **Bedroom satellites not yet installed** — `DEVICE_CONFIG` entries TBD.
3. **Cancel all from browser UI** — no satellite filter without device context.

---

## Session 7 — 2026-03-27

### What we accomplished

Fixed a second coordinator deployment gap (cancel_by_time/cancel_by_date),
completed three-tier cancel resolution, fixed the repeating alarm article
pattern, confirmed repeating alarms work end-to-end, and prepared the project
for public release on GitHub.

### Bugs found and fixed

#### cancel_by_time / cancel_by_date not deployed (Session 5 regression)
- `cancel_by_time` and `cancel_by_date` were added to coordinator.py at the
  end of Session 5 but the file was not confirmed deployed.
- Symptom: "cancel 9 am alarm" returned "No alarm matching '9 am' found."
  even after the coordinator.py copy — the copy was the *old* file.
- Fix: redeployed coordinator.py with both new methods.

#### "cancel tuesday alarm" fell through all tiers
- Label substring match failed (label is "Alarm"), time-expression parse
  failed (bare day name "tuesday" has no time component), no third tier →
  "No alarm matching 'tuesday' found."
- Fix: third tier in `_handle_cancel` now calls `coordinator.cancel_by_date()`
  after label and time-expression matches fail.  `parse_date()` was added as
  a public function in `datetime_parser.py` for this purpose.

#### Repeating alarm article not optional
- "set daily alarm for 7pm" returned `null` intent — pattern was
  `"set a daily alarm for {time}"` (literal "a"), STT often drops the article.
- Fix: changed to `"set [a] daily alarm for {time}"` for all three repeat
  types (daily, weekdays, weekends). Same fix applied to weekday/weekend forms.

### Confirmed working this session

- Cancel by label, time expression, and bare date all confirmed ✅
- "cancel tuesday alarm" → cancels next alarm on Tuesday ✅
- "cancel sunday 3 pm alarm" → cancels alarm at Sunday 15:00 ✅
- Repeating alarms end-to-end: set → fire → auto-reschedule ✅
- "set daily alarm for 7pm" (without "a") matches correctly ✅
- All four satellites continuing to work ✅

### Carried-forward items resolved this session

- **`_raise_volume` dead code** — already removed in commit `0619de5` (Session
  6 close). No action needed.
- **HAVPE minimum restart interval** — already implemented in commit `0619de5`
  (`_MIN_RESTART_INTERVAL = 3.0`). Log noise reduced. No action needed.
- **Repeating alarm end-to-end** — confirmed working. Closed.

### Public release prep

- `README.md` — full documentation: install (HACS + manual), voice command
  reference, dashboard Markdown card template, known limitations, services
  table, contributing guide, MIT license notice.
- `LICENSE` — MIT 2026, author Nathothan.
- `hacs.json` — correct fields for HACS custom repository submission.
- `manifest.json` — `"codeowners": ["@Nathothan"]` added.
- No personal details (IP addresses, real names, internal entity IDs) in any
  public-facing file.

### Known gaps carried forward

1. **Alarm sound URL is hardcoded** — `ALARM_SOUND_URL` in `announcer.py` must
   be edited manually. No UI for this yet.
2. **Cancel all from browser UI cancels everything** — no satellite filter when
   invoked without device context. Documented in README known limitations.
3. **Multiple alarms at same time** — "cancel tuesday alarm" picks earliest;
   if two share identical scheduled_at, which is cancelled is undefined.
4. **No HACS official submission yet** — `hacs.json` is ready; repo needs to
   be public on GitHub first.

### Next session plan

1. Push worktree branch to GitHub as a public repo under the Nathothan account.
2. Submit to HACS default repository (optional, requires HACS review).
3. Test a weekday or weekend repeating alarm across the day boundary.
4. Consider a config-flow option for the alarm sound URL to eliminate the
   hardcoded constant.

---

## Session 6 — 2026-03-26

### What we accomplished

Six features implemented or analysed, two documentation files updated.

### Sync verification (Step 0)

All files were in sync between the worktree and Samba at session start. No copies needed on entry.

### Bug fixes

#### `no device_id in intent` log level
- Both `_LOGGER.warning` calls in `_extract_satellite_id` demoted to `_LOGGER.debug`.
- These fire whenever the browser Assist UI is used (no physical satellite). They are expected and not actionable, so WARNING was noisy.

### New features

#### Feature 1 — "What alarms do I have set?" (HaAlarmsListAlarms / HaAlarmsListReminders)

**coordinator.py:** Added `get_scheduled_items(item_type, satellite_id=None)` — returns all scheduled items of a type sorted by `scheduled_at`, optionally filtered by satellite.

**intent_handler.py:** Added `ListAlarmsHandler` and `ListRemindersHandler`. Response uses number words for counts 1–5, digits for 6+. Lists first 3 items and adds "and N more" for the rest. For reminders includes the label: "call Mom at 7:00 AM".

**ha_alarms.yaml:** Added `HaAlarmsListAlarms` and `HaAlarmsListReminders` intents with natural sentence patterns.

**__init__.py:** Added new intent constants to imports and `_ALL_INTENTS`.

#### Feature 2 — "Wake me up in X hours/minutes"

**ha_alarms.yaml:** Added two new sentences to `HaAlarmsSetAlarm`:
- `"wake me up in {time}"` — e.g. "wake me up in 2 hours"
- `"set [an] alarm in {time}"` — e.g. "set an alarm in 30 minutes"

`datetime_parser.py` already handles all relative-time forms. No Python changes needed.

#### Feature 3 — Gradual volume increase

**announcer.py:** Replaced the `_raise_volume` call (which set volume to 2× current) with a gradual ramp:
- Ring starts at 20% volume
- Volume increases by 20 percentage points every 30 seconds
- Capped at 100%
- Prior volume is still captured before the ring starts and restored on stop/snooze

Volume steps use `asyncio.get_event_loop().time()` (monotonic) to measure the interval accurately regardless of how long each poll iteration takes.

#### Feature 4 — Snooze while ringing

Analysis confirmed: **no new handler needed**. The existing `SnoozeAlarmHandler` already handles this case correctly. While the alarm bell plays on the ReSpeaker, the ESPHome microphone stays active (mic and speaker are independent hardware). The user says "snooze", HA routes the intent to `SnoozeAlarmHandler`, which finds the active item on the originating satellite and calls `coordinator.snooze_item()` to stop the ring and reschedule. Added a docstring comment to `SnoozeAlarmHandler` documenting this.

#### Feature 5 — "Cancel all alarms" (HaAlarmsCancelAllAlarms / HaAlarmsCancelAllReminders)

**coordinator.py:** Added `cancel_all_scheduled(item_type, satellite_id=None)` — cancels every scheduled item of the given type (optionally filtered by satellite), returns count cancelled.

**intent_handler.py:** Added `CancelAllAlarmsHandler` and `CancelAllRemindersHandler`. Each handler stops any currently-ringing items first (via `stop_all_active`), then calls `cancel_all_scheduled`. Satellite filter is applied: from a satellite, only that satellite's items are cancelled; from the browser UI (no satellite), all items of that type are cancelled.

**ha_alarms.yaml:** Added `HaAlarmsCancelAllAlarms` and `HaAlarmsCancelAllReminders` intents with patterns covering "cancel/turn off/delete/remove all alarms".

**__init__.py:** Added new intent constants to imports and `_ALL_INTENTS`.

### Intent shadowing check

Added a comment block at the top of `ha_alarms.yaml` documenting:
- `HaAlarmsSetAlarm` intentionally shadows HA's built-in `HassSetAlarm`
- "what time is my alarm" is distinct from `HassGetCurrentTime` patterns ("what time is it")
- "list my alarms" / "cancel all alarms" have no HA builtin equivalents

No conflicts found. The new `HaAlarmsListAlarms` / `HaAlarmsCancelAllAlarms` patterns do not overlap with any known HA built-in intents.

### Documentation

- `docs/entity-map.md` — rewritten with confirmed entity IDs for all four devices, TBD notes for Kitchen/Theater/Living Room media_player IDs, and a note on how the announcer resolves media players and the ring loop preference rule (prefer `_media_player` suffix over Music Assistant player).
- `DEVLOG.md` — added "Known Hardware Issues" section with ReSpeaker LED stuck note before Session 5.

### All features confirmed working

Tested on all four satellites. HA logs from 2026-03-27T04:47:

| Satellite | Resolved media_player | Volume ramp | Stop method |
|---|---|---|---|
| Office ReSpeaker | `office_respeaker_media_player` ✅ | (stopped before 30s) | stopped |
| Kitchen HAVPE | `home_assistant_voice_09787e_media_player` ✅ | 20→40→60→80% ✅ | stopped |
| Theater ReSpeaker | `theater_voice_media_player` ✅ | (stopped before 30s) | voice dismiss ✅ |
| Living Room Waveshare | `waveshare_audio_3` ✅ | 20→40→60% ✅ | stopped |

**Media player selection**: the `platform != "music_assistant"` filter is working correctly on all four devices — every device picked the raw ESPHome/HA player, not the Music Assistant wrapper.

**Gradual volume ramp**: confirmed working on Kitchen (20→40→60→80% visible in logs) and Living Room (20→40→60%). Steps are ~30 seconds apart as designed.

**Voice dismiss**: Theater ended with `responding→idle — treating as user dismiss` — the satellite heard a voice command while ringing and ended cleanly. This confirms the dismiss detection works during active ring.

**Frequent restart loop on HAVPE**: the Kitchen HAVPE fires "media_player stopped — restarting" every 4 seconds. This is normal — HA Voice PE media player goes idle after each short audio clip rather than holding state like the ReSpeaker. The alarm still rings continuously; it is just louder in the logs.

### Known gaps carried forward

1. **`cancel_all_scheduled` from browser UI cancels all satellites** — when invoked without a satellite context (browser Assist UI), all items of that type are cancelled regardless of satellite. Intentional but worth documenting in the UI.
2. **`_raise_volume` helper is now dead code in announcer.py** — superseded by the gradual ramp. Can be removed in a future cleanup.
3. **Repeating alarms end-to-end** still untested — the fire→reschedule cycle has not been observed live.

### Next session plan

1. Remove dead `_raise_volume` helper from announcer.py.
2. Test a repeating alarm end-to-end: set daily at a time 2 minutes away, let it fire, confirm it re-schedules for next day.
3. Consider whether the HAVPE's rapid restart loop warrants a minimum restart interval (e.g. don't restart sooner than 3 seconds after last start) to reduce log noise.

---

## Session 5 — 2026-03-27

### What we accomplished

Completed the cancel-by-voice feature, fixed a missing coordinator deployment,
and built a three-tier cancel resolution chain that handles every natural way
a user would refer to an alarm they want to cancel.

### Bugs found and fixed

#### coordinator.py not deployed (Session 4 regression)
- `cancel_by_label` was added to coordinator.py at the end of Session 4 but
  the file was never copied to the Samba share. Intent handlers crashed with
  `AttributeError: 'AlarmCoordinator' object has no attribute 'cancel_by_label'`.
- Fix: deployed coordinator.py. Going forward, always copy all modified files
  before closing a session.

#### Cancel by time expression failing
- "cancel 9 am alarm" — `{label}` slot captured "9 am", label substring match
  failed (stored label is "Alarm"), returned "No alarm matching '9 am' found."
- Root cause: no fallback to interpret the label slot as a time expression.
- Fix: added `coordinator.cancel_by_time()` — matches `scheduled_at.hour` +
  `scheduled_at.minute` against a parsed datetime. After label match fails,
  `_handle_cancel` now tries to parse the label query as a datetime and calls
  `cancel_by_time`.
- "cancel sunday 3 pm alarm" works because `_DAY_EMBEDDED_RE` already handles
  "sunday 3 pm" → Sunday 15:00, and `cancel_by_time` matches on hour+minute.

#### Cancel by bare day name failing
- "cancel tuesday alarm" — `{label}` captured "tuesday". Time-expression parse
  fails (no time component in a bare day name), fell through to "no alarm found."
- Fix: added `coordinator.cancel_by_date()` — matches `scheduled_at.date()`
  against a target date. Added `parse_date()` as a public function in
  `datetime_parser.py`. Third fallback in `_handle_cancel` tries date-only
  match after both label and time-expression matches fail.

### New features added this session

#### Cancel-by-voice (full implementation)
Two new intents: `HaAlarmsCancelAlarm` and `HaAlarmsCancelReminder`.

Sentence patterns:
- `"(cancel|delete|remove) [my] {label} alarm"`
- `"(cancel|delete|remove) the {label} alarm"`
- Same for reminders.

Three-tier resolution in `_handle_cancel`:
1. **Label substring** — case-insensitive; "cancel my wake up alarm" matches
   label "Wake Up". Useful for named reminders and labeled alarms.
2. **Time expression** — parses the label slot as a datetime via
   `parse_datetime()`; "cancel 9 am alarm" → matches hour=9, minute=0.
   "cancel sunday 3 pm alarm" → Sunday 15:00 via `_DAY_EMBEDDED_RE`. Useful
   for default "Alarm" label.
3. **Date only** — parses the label slot as a date via `parse_date()`; "cancel
   tuesday alarm" → next Tuesday → matches any alarm on that date. Useful
   when user specifies the day but not the time.

If all three fail → "No alarm matching '{query}' found."
If no label at all → falls back to `cancel_next_scheduled` (soonest upcoming).

#### Word number support in datetime_parser
- `_WORD_TO_NUM` dict: "one" through "nineteen" plus "twenty", "thirty",
  "forty", "fifty", "sixty", "ninety", "a"/"an".
- `_RELATIVE_RE` updated to match word numbers: "in two hours", "in an hour",
  "in ninety minutes".
- Bare-hour normalisation: "nine" → "9" → triggers ambiguous-hour prompt
  "Did you mean 9 AM or 9 PM?" instead of ParseError.

### Architecture note: other satellites

**No code changes needed for Kitchen, Theater, Living Room ReSpeakers.**

The integration is fully satellite-agnostic by design:
- `_extract_satellite_id` reads `intent_obj.device_id` at the moment the voice
  command arrives and resolves it to the `assist_satellite.*` entity on that
  specific device via the entity registry. Nothing is hardcoded.
- `announcer.py` resolves the media player from the same device the same way —
  it walks the entity registry for the device that owns the `assist_satellite`
  entity and picks the first `media_player.*` entity there.
- Stored alarms carry the satellite entity ID of the device that set them, so
  they always ring back to the right room.

The only potential friction point for new satellites:
- **`ALARM_SOUND_URL`** is `http://homeassistant.local:8123/local/ship_bell.mp3`.
  mDNS resolves fine from ESPHome devices on a flat network; on VLANs or strict
  DNS setups, swap to the HA IP address instead.
- If a satellite has no `media_player.*` entity on the same device (unlikely
  for identical ReSpeakers but possible for a HA Voice PE), the announcer
  falls back to TTS-only mode automatically — no crash.

### What was tested and confirmed working

- Cancel by label: "cancel my sing a song reminder" ✅
- Cancel by time: "cancel 9 am alarm" ✅
- Cancel by date: "cancel tuesday alarm" ✅
- "cancel sunday 3 pm alarm" (embedded day+time in label slot) ✅
- Word numbers: "in two hours", "in an hour", "in ninety minutes" ✅
- All Session 4 features still working after changes ✅

### Known gaps carried forward

1. **Repeating alarms end-to-end** — daily/weekdays/weekends can be set by
   voice and the repeat type is stored, but a live fire→reschedule cycle has
   not been observed. Needs a test alarm set to fire in 1 minute.
2. **Other satellites untested** — Kitchen, Theater, Living Room ReSpeakers.
   Should work without code changes; worth a quick voice test per device.
3. **`no device_id in intent` warnings** — appear when testing via the browser
   Assist UI (no physical satellite). Not a bug. Could log at DEBUG instead of
   WARNING to reduce noise.
4. **Auto-purge timer** — missed items are deleted on HA startup and via the
   `ha_alarms.purge` service. No periodic cleanup during a long-running
   session. Low priority since startup handles almost all cases.
5. **Multiple alarms same time on same day** — "cancel tuesday alarm" picks
   the earliest. If two alarms are at identical times, which one is cancelled
   is undefined (dict iteration order). Acceptable for now.

### Next session plan

1. Test a repeating alarm end-to-end: set daily at a time 2 minutes away,
   let it fire, confirm it re-schedules for the next day.
2. Test one additional satellite (Kitchen or Theater).
3. Decide whether to change `ALARM_SOUND_URL` to a hardcoded IP to avoid
   mDNS issues across rooms.
4. Consider lowering `no device_id` log from WARNING to DEBUG.

---

## Session 4 — 2026-03-26/27

### What we accomplished

First full end-to-end working session. Went from "config flow could not be
loaded" to a fully functional alarm system: voice in → alarm fires → bell
rings → volume raises → snooze/cancel works → dashboard card updates live.

### Bugs found and fixed

#### Manifest / loading
- `manifest.json` had empty `"documentation"` and `"issue_tracker"` keys
  causing HA to reject the config flow. Removed those, added
  `"homeassistant": "2026.1.0"`.
- Missing `services.yaml` caused `Failed to load services.yaml` on every
  startup. Created full services.yaml covering all six services.

#### Satellite extraction
- `_extract_satellite_id` was reading `intent_obj.context.satellite_id` —
  that attribute does not exist on HA's standard `Context` object.
- Fix: read `intent_obj.device_id`, then walk the entity registry with
  `er.async_entries_for_device()` to find the `assist_satellite.*` entity on
  that device. Correct entity ID is now resolved automatically from whichever
  satellite heard the command.

#### Service schema key names
- Schemas used `"time"` / `"date"` but callers pass `"time_str"` / `"date_str"`.
  Renamed keys in both schemas and `_parse_time_from_call`.

#### Date-first phrasing
- "set an alarm for Saturday at 10am" failed — sentence YAML only had
  `{time} on {date}`, not `{date} at {time}` ordering.
- Added `{date} at {time}` patterns for both SetAlarm and SetReminder.
- Added `_DAY_EMBEDDED_RE` parser fallback for when the day name arrives
  inside the `time` slot as "Saturday at 10am".

#### Relative reminders
- "remind me in 30 minutes to …" failed because the sentence captures
  `time="30 minutes"` (without "in"), but `_RELATIVE_RE` required the
  "in" prefix. Made "in" optional in the regex.

#### Cancel scheduled alarms
- `stop_all_active` only stopped ringing alarms. "Cancel the alarm" when
  nothing was ringing said "No alarm found."
- Fix: `StopAlarm` / `StopReminder` handlers now check for active items
  first; if none, call new `coordinator.cancel_next_scheduled()` to cancel
  the soonest upcoming item. Spoken response confirms label and time.
- `cancel_next_scheduled` intentionally ignores satellite ID — you should be
  able to cancel any alarm from any satellite.

#### Stale satellite entity ID in storage
- Early test alarms were saved with `assist_satellite.office_respeaker`
  (wrong ID). Fixed satellite extraction meant new alarms got the right ID
  but old ones couldn't be cancelled. Cleared storage manually; fixed
  cancel to be satellite-agnostic.

#### Missed items accumulating in storage
- `async_load` marked past-due items "missed" but never deleted them.
  Over time they pile up invisibly.
- Fix: `async_load` now **deletes** one-shot past-due/active items instead
  of marking them missed. Repeating items are **advanced** to the next
  occurrence and rescheduled rather than discarded.
- Added `coordinator.purge_missed()` and `ha_alarms.purge` service for
  manual cleanup of any remaining missed items.

#### Recurring alarms (HA native conflict)
- "Set a daily alarm" was intercepted by HA's built-in alarm intent
  (`HassSetAlarm`) which responded "The alarm system doesn't support
  recurring alarms."
- Fix: added repeat-specific sentence patterns with fixed `repeat` slots
  (`daily`, `weekdays`, `weekends`) so our intent matches first.
  `SetAlarmHandler` now reads the `repeat` slot (defaults to `once`).
  Response confirms repeat: "Daily alarm set for 9:00 AM."

### New features added this session

#### Announcer: continuous media_player alarm sound
- `assist_satellite.announce` used for initial TTS announcement only.
- Media player entity on same device resolved via entity registry.
- `media_player.play_media` plays `ship_bell.mp3` in a loop (restarts
  when idle), giving continuous sound until stopped.
- Volume raised to 2× current level (capped at 1.0) before ringing;
  restored on stop/snooze.
- Falls back to TTS-only mode if `ALARM_SOUND_URL` is empty or no
  media_player found.

#### Sensor platform
- `sensor.ha_alarms` and `sensor.ha_reminders` entities showing item count
  and full item list (label, scheduled_at, status, when, repeat, satellite)
  as attributes.
- Live updates via `SIGNAL_ITEMS_UPDATED` dispatcher.
- Markdown card template provided for dashboard display.

#### Cancel scheduled alarms by voice
- "Cancel the alarm" now works both while ringing (stops it) and before
  it fires (cancels next upcoming). Same for reminders.
- Spoken confirmation includes item label and scheduled time.

### Key decisions

- `DEFAULT_SNOOZE_MINUTES` changed from 10 → 5.
- weather.yaml (all-commented, invalid) deleted — was causing a startup
  WARNING on every boot.
- `cancel_next_scheduled` does NOT filter by satellite — cancel should work
  regardless of which device set the alarm.
- One-shot missed alarms are deleted on startup, not kept as "missed" clutter.

### Known gaps carried forward

1. **Cancel specific alarm by voice** — "cancel my 9 AM alarm" / "cancel
   my morning alarm". Currently "cancel the alarm" always picks the next
   one by time. Needs a new intent with time/label slot.
2. **Bare number word ("set alarm for nine")** — STT may convert "nine"
   to "9" but the bare-hour ambiguous check should fire. Needs investigation;
   may be HA native alarm intercepting before our intent runs.
3. **Cancel by label/time** — no mechanism to cancel a specific alarm
   without knowing its item_id.

### What was tested and confirmed working

- Set alarm by voice (absolute time, relative time, today, tomorrow,
  day-of-week, date-first phrasing)
- Set reminder by voice (including relative: "remind me in 30 minutes")
- Alarm fires on time with ship bell loop
- Volume doubles on ring, restores on stop
- Stop alarm (ringing and pre-scheduled)
- Cancel alarm (pre-scheduled, by voice)
- Snooze (stops bell, re-fires 5 minutes later)
- Restart persistence (alarm survives HA restart, re-fires correctly)
- Multiple alarms at once
- Sensor entities + dashboard markdown card
- Gitea push working

### Next session plan

1. Investigate "set alarm for nine" — check HA logs to see whether our
   intent or HA's native intent handles bare word numbers.
2. Implement "cancel my {time} alarm" / "cancel my {label} alarm" intent.
3. Test repeating alarms end-to-end (set daily, let it fire, confirm it
   re-schedules for next day).
4. Test remaining satellites (Kitchen, Theater, Living Room).
5. Consider adding a `label` slot to snooze so "snooze my 9 AM alarm"
   works when multiple alarms are active.

---

## Session 3 — 2026-03-26

### What we accomplished

Implemented all five Python modules and the sentence YAML from scratch. Every
module is syntax-clean and the datetime_parser passes 26/26 standalone tests
outside of HA.

### Modules implemented

#### `const.py`
All domain-level constants in one place: `DOMAIN`, `STORAGE_KEY`,
`STORAGE_VERSION`, six `SERVICE_*` names, `ITEM_TYPE_*`, `ATTR_*` field names,
`REPEAT_*` values, `DEFAULT_SNOOZE_MINUTES = 10`, and `SIGNAL_ITEMS_UPDATED`
for future UI dispatcher use.

#### `datetime_parser.py`
Single public function `parse_datetime(time_text, date_text=None, now=None)`
returning a tz-aware datetime.  Handles:
- Absolute: "7:30 AM", "7:30 PM", "7:30", "7 AM", "7am", "19:30"
- Special: "noon" (12:00), "midnight" (00:00)
- Relative: "in 30 minutes", "in an hour", "in 2 hours", "in 90 minutes"
- Date: "today", "tomorrow", weekday names → next occurrence, never today
- Bare hour (1–12) with no AM/PM → `ParseAmbiguousError("Did you mean 6 AM or 6 PM?")`
- Unparseable input → `ParseError`

Key decisions:
- HH:MM without AM/PM treated as 24-hour clock ("7:30" → 07:30, "19:30" → 19:30)
- Absolute time already past today rolls to tomorrow automatically
- `now` parameter makes the parser fully testable outside of HA
- Standalone `if __name__ == "__main__"` test block: 26/26 pass

#### `announcer.py`
`Announcer` class with two public methods:
- `ring(satellite_entity_id, item)` — async, intended as a fire-and-forget task.
  Validates the satellite exists and is not unavailable (logs WARNING, returns
  if not).  Speaks the initial announcement, then loops every 30 s with a
  short wake-up prompt.
- `stop(satellite_entity_id)` — synchronous, sets an asyncio.Event to exit
  the ring loop cleanly from the coordinator.

Dismiss detection: after each `assist_satellite.announce` call the satellite
goes `responding → idle` normally.  A `_watching` flag is only enabled during
the 30 s wait between announces, so our own TTS completions don't false-trigger
dismiss.  A 1.5 s settle delay after each announce lets the satellite fully
return to idle before watching starts.

No pydub. No media_player. `assist_satellite.announce` only.

#### `coordinator.py`
`AlarmCoordinator` owns all runtime state.

Item schema: `id`, `type`, `label`, `satellite`, `scheduled_at` (datetime),
`repeat`, `enabled`, `status` ("scheduled" / "active" / "missed").

Key decisions:
- `scheduled_at` is stored as ISO string in JSON, parsed back with
  `datetime.fromisoformat()` on load; naive datetimes get a UTC fallback with
  a WARNING.
- Past-due items on `async_load` → log WARNING, set `status = "missed"`, no
  silent drop.
- Items that were "active" at shutdown → log WARNING "rescheduling is not
  automatic", set "missed".  No auto-reschedule.
- `_next_occurrence` runs only in `_on_ring_done` (not at fire time), so
  `scheduled_at` always holds the last fire time while status is "active".
  This makes the restart-missed-alarm detection reliable.
- Snooze sentinel: `_stop_ring_externally` sets `item["status"] = "scheduled"`
  before cancelling the task. `_on_ring_done` skips lifecycle logic if status
  is not "active", preventing a snoozed one-shot alarm from being deleted.
- `stop_all_active(item_type=None)` accepts an optional type filter; passing
  `None` stops everything (used by `stop_all` service).
- `async_cancel_all()` cleans up all callbacks and tasks on integration unload.

#### `intent_handler.py`
Six handlers. Shared helpers:
- `_extract_satellite_id`: `hasattr` check on `context.satellite_id`; no UUID
  fallback; logs WARNING and returns None if absent or not dotted.
- `_parse_slots`: shared time+date parse logic returning `(datetime, None)` or
  `(None, error_speech)`.  `ParseAmbiguousError` is surfaced verbatim to the
  user ("Did you mean 6 AM or 6 PM?").
- `_format_dt_for_speech`: "7:30 AM", "7:30 AM tomorrow", "7:30 AM on Monday".

UX decision: `SetReminderHandler` validates label *before* parsing time — user
hears "what should I remind you about?" rather than a time-parse error when
they forget the label.

Snooze targeting: finds active items of the right type on the right satellite,
picks the one with the latest `scheduled_at` (most recently fired), calls
`coordinator.snooze_item()`.

#### `config_flow.py`
Zero-input single-step flow. `_async_current_entries()` guard aborts with
`already_configured` if the domain is already set up. Creates entry with
`title="HA Alarms"`, `data={}`.

#### `__init__.py`
`async_setup_entry` only — no `async_setup` YAML path.  Registers six services
with voluptuous schemas (voluptuous is a HA core dependency, zero extra
installs).  Calls `coordinator.async_load()` then `async_setup_intents(hass)`.

`async_unload_entry`: calls `coordinator.async_cancel_all()`, removes all six
services, clears the intent-registered guard key, and calls
`intent.async_remove()` for each intent type (guarded with `hasattr` for HA
versions before 2024.4).

#### `config/custom_sentences/en/ha_alarms.yaml`
All slots (`{time}`, `{date}`, `{label}`, `{minutes}`) are wildcards, not
enumerations.  Patterns cover:
- Set alarm: 6 forms including "wake me up at {time}"
- Set reminder: 6 forms including relative-time "remind me in {time} to {label}"
- Stop alarm: `(stop|cancel|dismiss) [the] alarm`
- Stop reminder: `(stop|cancel) [the] reminder`
- Snooze alarm: 4 forms including "give me {minutes} more minutes"
- Snooze reminder: 2 forms

### Open questions carried forward

- What is the exact attribute name HA uses for `satellite_id` in intent context
  across HA versions? (2024.x vs 2026.x — needs verification in HA logs on
  first real test.)
- Does `assist_satellite.announce` with `blocking=True` actually wait for TTS
  audio to finish, or does it return when the service handler returns?  If the
  latter, the settle delay in announcer.py may need tuning.
- HA's wildcard slot matching with two wildcards in one sentence
  ("remind me in {time} to {label}") needs live testing — the "to" separator
  should be enough but may behave unexpectedly.

### Next session plan

1. Deploy: copy `custom_components/ha_alarms/` and
   `config/custom_sentences/en/ha_alarms.yaml` to the HA config volume.
2. Restart HA, check logs for load errors (missing imports, config-entry
   setup failures).
3. Add the integration via Settings → Devices & Services → Add Integration →
   "HA Alarms".
4. Open Developer Tools → Assist tab, select a pipeline that uses one of the
   ReSpeaker satellites.
5. Test: "set an alarm for 7 AM" — confirm coordinator logs the schedule and
   returns a spoken confirmation.
6. Test: "set an alarm for 6" — confirm the ambiguous-hour response fires.
7. Test via actual voice on the office ReSpeaker.
8. Check that the alarm fires at the scheduled time and the satellite speaks.
9. Test snooze and stop via voice.
10. Investigate `satellite_id` attribute name in HA logs if routing is broken.

---

## Session 2 — 2026-03-25

### What we accomplished

Cloned the reference integration (omaramin-2000/HA-Alarms-and-Reminders) into
`reference/` and did a full code review of `__init__.py`, `coordinator.py`,
`announcer.py`, `intents.py`, `datetime_parser.py`, and the English sentence
files. Concluded that fixing in place is not worth the risk — the codebase has
too many structural problems to patch cleanly. Decided to write a new
integration (`ha_alarms`) from scratch using the reference only as a research
artifact. Created stub files for all modules with docstrings capturing design
intent.

### 9 bugs / problems found in the reference

1. **No relative-time support.** Neither the sentence patterns nor
   `datetime_parser.py` handle "in 30 minutes" or "in an hour". Common voice
   pattern, silently fails.

2. **`{time}` is a closed enumeration, not a wildcard.** The sentence files
   define `{time}` as a list of `{hour}(AM|PM)` combos. HA's sentence engine
   rejects anything not in the list. In practice almost nothing matches.

3. **Two parallel parsers, only one used.** `datetime_parser.py` is a full
   multi-language parser that is never called from the intent path.
   `intents.py` has its own private `_parse_time()` / `_parse_date()` methods.

4. **UUID fallback for satellite_id.** Five of the six intent handlers fall back
   to `intent_obj.context.id` (a UUID) when `context.satellite_id` is absent.
   The dot-check then rejects the UUID, so the item is saved with no satellite —
   silent failure, alarm fires to nowhere.

5. **Ambiguous bare-hour heuristic is backwards.** `datetime_parser.py` assumes
   hour < 7 → PM, hour 7–12 → AM. "Set alarm for 6" schedules 18:00.

6. **`pydub` hard dependency.** `announcer.py` imports `pydub` at the top level
   for audio duration detection. If pydub is not installed the entire integration
   fails to load.

7. **Duplicate setup paths.** Both `async_setup` (YAML) and `async_setup_entry`
   (config entry) create a coordinator and register all services. On a normal
   config-entry install both run, so services are double-registered.

8. **Missed alarms on restart are silently dropped.** `async_load_items` skips
   any item whose scheduled time is in the past with no log message. Users get
   no indication that an alarm was missed.

9. **Double-space in reminder sentence pattern.** `reminders.py` line 9:
   `"{task} [(on|in)] [{date}]  at {time}"` has two spaces before `at`, which
   may prevent matching in strict parsers.

### Design decisions for ha_alarms

- **Config-entry only.** No `async_setup` / YAML path. One setup path, no
  duplicate service registration.
- **No UUID fallback.** If `context.satellite_id` is absent or not a dotted
  entity ID, log a WARNING and store `satellite=None`. Never pass a UUID as a
  satellite entity ID.
- **No pydub.** Audio duration obtained from the HA media URL's HTTP headers
  (`X-Content-Duration` / `Content-Length`), with a 5 s fallback. Zero extra
  Python dependencies.
- **Wildcard `{time}` and `{date}` slots.** The sentence YAML uses wildcards so
  the raw spoken string is passed to `datetime_parser.py`, which handles all
  forms including relative time.
- **Single parser.** `datetime_parser.py` is the only time/date parser. Intent
  handlers import and call it directly — no inline parsing.
- **Explicit error logging.** Past-due alarms on restart log a WARNING with the
  item name and scheduled time. Missing satellite logs a WARNING at
  schedule-time. Ambiguous bare-hour raises `ParseAmbiguousError` so the intent
  handler can reply "did you mean AM or PM?" rather than guessing.
- **`announcer.py` entity-ID contract.** Caller is responsible for supplying a
  valid `assist_satellite.*` entity ID. Announcer does not normalise or look up
  device IDs — that concern stays in the coordinator.

### Stub files created

```
custom_components/ha_alarms/
  __init__.py
  coordinator.py
  announcer.py
  intent_handler.py
  datetime_parser.py
  const.py
  config_flow.py
  manifest.json
  strings.json
config/custom_sentences/en/ha_alarms.yaml
```

### Next session plan

Implement modules in dependency order (leaves first):

1. **`const.py`** — domain, storage key, service names, attribute names,
   defaults, signal names. No dependencies.
2. **`datetime_parser.py`** — full parser including relative time ("in N
   minutes/hours"). Depends only on stdlib + `homeassistant.util.dt`. Write
   unit tests inline or alongside.
3. **`coordinator.py`** — storage, scheduling, all mutations. Depends on
   `const.py`, `datetime_parser.py`, `announcer.py` (injected).
4. **`announcer.py`** — ring loop, state monitoring, HTTP duration detection.
   Depends on `const.py` only.
5. **`intent_handler.py`** — six intent handlers, clean satellite_id extraction.
   Depends on `const.py`, `coordinator.py`.
6. **`config_flow.py`** — single-step UI flow with already_configured guard.
   Depends on `const.py`.
7. **`__init__.py`** — wires everything together. Depends on all of the above.
8. **`ha_alarms.yaml`** — finalise sentence patterns once parser API is settled.

### Open questions carried forward

- Do we need a `switch` or `todo` platform, or is the coordinator + services
  enough for the first working version?
- What's the exact attribute name HA uses for `satellite_id` in the intent
  context across different HA versions (2024.x vs 2026.x)?
- Should missed alarms on restart ring immediately, be rescheduled N minutes
  out, or just be logged and skipped?

---

## Session 1 — 2026-03-24

### What this project is
A voice-triggered alarm and reminder system for Home Assistant, designed to
replace Alexa's alarm/reminder functionality across multiple ESPHome voice
satellites. Must support multiple alarms per device, named reminders spoken
aloud via TTS, relative-time reminders ("in an hour"), and day-specific
reminders ("on Friday"). Alarms must ring on the device that heard the command.

### Hardware
- 2x ReSpeaker Lite running formatBCE firmware (ESPHome 2026.2.4)
- 1x HA Voice PE
- 3 more devices planned for bedrooms once alarms work

### Infrastructure
- HA OS 2026.3.4 as VM on Unraid 7.2.4
- HA Core 2026.3.4, Nabu Casa active (Cloud STT/TTS)
- Gitea self-hosted (local network)
- code-server on Unraid, workspace at /config/ha-alarms
- Samba share bridging HA VM to Unraid

### Key findings from Session 1

#### The native firmware alarm is NOT sufficient
The formatBCE ReSpeaker firmware has a built-in alarm at the ESPHome level:
- One alarm per device only
- Repeats daily — not one-shot
- Set via esphome.office_respeaker_set_alarm_time (parameter: alarm_time_hh_mm)
- Monitored via sensor.office_respeaker_alarm_time (read-only sensor, not writable)
- Enabled via switch.office_respeaker_alarm_on
- Action selected via select.office_respeaker_alarm_action (Play sound / Send event / Sound and event)
This is ruled out as the primary mechanism — can't handle multiple alarms or named reminders.

#### Confirmed working on the satellites
- TTS works independently (tested via Developer Tools)
- Assist works for basic commands (lights etc.)
- Cloud STT/TTS via Nabu Casa on all pipelines

#### Confirmed entity IDs (Office ReSpeaker)
- media_player.office_respeaker (Music Assistant player)
- media_player.office_respeaker_media_player (raw ESPHome media player)
- select.office_respeaker_alarm_action
- sensor.office_respeaker_alarm_time
- switch.office_respeaker_alarm_on
- esphome.office_respeaker_set_alarm_time (action, param: alarm_time_hh_mm)
- esphome.office_respeaker_set_time_zone
- esphome.office_respeaker_start_va
- esphome.office_respeaker_stop_va

#### Why previous integrations failed
1. HA-Alarms-and-Reminders (omaramin-2000) and HA Alarm Clock (nirnachmani)
   both installed without errors but voice commands did nothing.
2. Root causes identified:
   - Custom Assist intent sentences likely not registering correctly
   - TTS being called on wrong entity (media_player vs assist_satellite)
   - Alarm scheduler not surviving HA restarts
   - No per-device routing — hardcoded entity instead of "device that heard the command"

### Chosen approach
Build on HA-Alarms-and-Reminders (omaramin-2000) as the base — 314 commits,
sounder architecture than the fork. Fix the specific failure points rather than
rewriting from scratch. Key fixes needed:
1. Correct Assist intent registration
2. Per-device TTS routing via pipeline context device_id
3. Restart-persistent alarm scheduling
4. Relative time parsing ("in an hour", "on Friday")

### Next session
1. Pull HA-Alarms-and-Reminders source into /config/ha-alarms/reference/
2. Code review: __init__.py, alarm_handler.py, intent handlers
3. Identify exact lines responsible for each of the 4 failure points
4. Decide: fix in place or extract and rewrite clean
5. Update entity-map.md with second ReSpeaker and HAVPE entity IDs

### Open questions
- What are the entity IDs for the second ReSpeaker and the HAVPE?
- Does HA-Alarms-and-Reminders use async_track_point_in_time correctly?
- How does it handle the device_id context from Assist pipeline calls?
- What does "Send event" mode fire on the native firmware alarm — what's the event name?