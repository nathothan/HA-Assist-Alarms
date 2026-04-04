"""TTS + media delivery via assist_satellite and media_player for ha_alarms.

Ring behaviour
--------------
1. Validate the satellite entity; log WARNING and return if absent/unavailable.
2. Look up the media_player entity on the same HA device as the satellite.
3. Speak the initial announcement via assist_satellite.announce (TTS).
4. If a media_player was found, immediately start playing ALARM_SOUND_URL.
5. Poll every _POLL_INTERVAL seconds:
   - If the media player reaches idle/paused (file ended), restart it — this
     gives continuous looping without a looping file.
   - If stop_event is set (coordinator cancel / stop_all), break.
   - If the satellite transitions responding → idle (user button press), break.
6. On exit: call media_player.media_stop and clean up state listeners.

If ALARM_SOUND_URL is empty the announcer falls back to periodic TTS-only
mode (legacy behaviour) using RING_INTERVAL.

No pydub. assist_satellite.announce for TTS. media_player.play_media for sound.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    ATTR_LABEL,
    ATTR_SOUND,
    ATTR_VOLUME_END,
    ATTR_VOLUME_RAMP,
    ATTR_VOLUME_START,
    DEFAULT_ALARM_SOUND,
    DEFAULT_VOLUME_END,
    DEFAULT_VOLUME_RAMP,
    DEFAULT_VOLUME_START,
    ITEM_TYPE_ALARM,
    ITEM_TYPE_REMINDER,
)

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Fallback interval (seconds) between TTS repeats when no media player is
# available (ALARM_SOUND_URL empty or media_player not found).
RING_INTERVAL = 8

# How long to wait after our own TTS announce before watching for user dismiss,
# giving the satellite time to finish speaking and return to idle.
_SETTLE_DELAY = 2.0

# How often (seconds) to poll the media player state and the stop/dismiss events.
_POLL_INTERVAL = 0.5


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def _build_initial_message(item: dict[str, Any]) -> str:
    """Build the first spoken announcement for an alarm or reminder."""
    item_type = item.get("type", ITEM_TYPE_ALARM)
    label = (item.get(ATTR_LABEL) or "").strip()

    if item_type == ITEM_TYPE_REMINDER:
        return f"Reminder: {label}." if label else "Reminder."

    scheduled_at = item.get("scheduled_at")
    if scheduled_at is not None:
        try:
            time_str = scheduled_at.strftime("%-I:%M %p").lstrip("0") or scheduled_at.strftime("%I:%M %p")
        except ValueError:
            time_str = scheduled_at.strftime("%I:%M %p").lstrip("0")
        if label:
            return f"Alarm: {label}. It's {time_str}."
        return f"Alarm. It's {time_str}."

    return f"Alarm: {label}." if label else "Alarm."


# ---------------------------------------------------------------------------
# Announcer
# ---------------------------------------------------------------------------

class Announcer:
    """Drives the ring loop for a single alarm or reminder fire event."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._stop_events: dict[str, asyncio.Event] = {}

    def stop(self, satellite_entity_id: str) -> None:
        """Signal the active ring loop for this satellite to exit."""
        event = self._stop_events.get(satellite_entity_id)
        if event is not None:
            event.set()

    async def ring(self, satellite_entity_id: str, item: dict[str, Any]) -> None:
        """Announce item on satellite_entity_id and loop until dismissed or stopped."""
        hass = self._hass

        # --- Validate satellite entity ------------------------------------
        state = hass.states.get(satellite_entity_id)
        if state is None:
            _LOGGER.warning(
                "ha_alarms: satellite %s not found — cannot ring alarm '%s'",
                satellite_entity_id,
                item.get(ATTR_LABEL, "<unlabelled>"),
            )
            return
        if state.state == "unavailable":
            _LOGGER.warning(
                "ha_alarms: satellite %s is unavailable — cannot ring alarm '%s'",
                satellite_entity_id,
                item.get(ATTR_LABEL, "<unlabelled>"),
            )
            return

        # --- Resolve alarm sound URL for this item -------------------------
        sound_url = _resolve_sound_url(item.get(ATTR_SOUND) or DEFAULT_ALARM_SOUND)

        # --- Resolve media_player entity on same device -------------------
        media_player_id = _get_media_player_id(hass, satellite_entity_id)
        use_media = bool(sound_url and media_player_id)
        if use_media:
            _LOGGER.debug(
                "ha_alarms: using media_player %s for alarm sound", media_player_id
            )
        elif sound_url and not media_player_id:
            _LOGGER.warning(
                "ha_alarms: no media_player entity found for satellite %s — "
                "falling back to TTS-only. Check that the satellite's media_player "
                "entity shares the same HA device in Settings → Devices & Services.",
                satellite_entity_id,
            )
        else:
            _LOGGER.debug(
                "ha_alarms: sound URL empty — TTS-only mode for %s", satellite_entity_id
            )

        # prior_volume is set inside the try block when use_media is True;
        # initialise here so the finally clause can always reference it safely.
        prior_volume: float | None = None

        # --- Shared events ------------------------------------------------
        stop_event = asyncio.Event()
        self._stop_events[satellite_entity_id] = stop_event
        dismiss_event = asyncio.Event()

        saw_responding: bool = False
        _watching: bool = False

        @callback
        def _on_state_change(event: Any) -> None:
            nonlocal saw_responding, _watching
            if not _watching:
                return
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            s = new_state.state
            if s == "responding":
                saw_responding = True
            elif s == "idle" and saw_responding:
                _LOGGER.debug(
                    "ha_alarms: satellite %s responding→idle — treating as user dismiss",
                    satellite_entity_id,
                )
                dismiss_event.set()

        unsub = async_track_state_change_event(
            hass, [satellite_entity_id], _on_state_change
        )

        try:
            # --- Initial TTS announcement ---------------------------------
            initial_msg = _build_initial_message(item)
            _LOGGER.debug("ha_alarms: ringing %s — %r", satellite_entity_id, initial_msg)
            await _announce(hass, satellite_entity_id, initial_msg)

            # Brief settle, then enable dismiss watching.
            await asyncio.sleep(_SETTLE_DELAY)
            saw_responding = False
            _watching = True

            if use_media:
                # --- Capture prior volume so we can restore it on stop -----
                state_now = hass.states.get(media_player_id)
                if state_now is not None:
                    raw = state_now.attributes.get("volume_level")
                    if raw is not None:
                        try:
                            prior_volume = float(raw)
                        except (TypeError, ValueError):
                            pass

                # Resolve per-item volume settings (stored by coordinator).
                volume_start: float = item.get(ATTR_VOLUME_START, DEFAULT_VOLUME_START)
                volume_end: float = item.get(ATTR_VOLUME_END, DEFAULT_VOLUME_END)
                do_ramp: bool = item.get(ATTR_VOLUME_RAMP, DEFAULT_VOLUME_RAMP)

                _VOLUME_STEP = 0.20
                _VOLUME_STEP_INTERVAL = 30.0  # seconds between ramp steps

                ring_volume = volume_start
                await _set_volume(hass, media_player_id, ring_volume)

                # Start the alarm sound immediately, then keep it looping by
                # restarting whenever the media player goes idle.
                await _play_sound(hass, media_player_id, sound_url)

                last_volume_step = asyncio.get_event_loop().time()

                # Minimum interval between successive play_media calls to avoid
                # hammering the media player on devices (e.g. HA Voice PE) that
                # report idle immediately after each short clip.
                _MIN_RESTART_INTERVAL = 3.0  # seconds
                last_play_time = asyncio.get_event_loop().time()

                while not stop_event.is_set() and not dismiss_event.is_set():
                    await asyncio.sleep(_POLL_INTERVAL)

                    now_mono = asyncio.get_event_loop().time()

                    # Volume ramp: step up every 30 s toward volume_end.
                    # Skipped entirely when do_ramp is False.
                    if do_ramp and ring_volume < volume_end and (now_mono - last_volume_step) >= _VOLUME_STEP_INTERVAL:
                        ring_volume = min(ring_volume + _VOLUME_STEP, volume_end)
                        await _set_volume(hass, media_player_id, ring_volume)
                        last_volume_step = now_mono
                        _LOGGER.debug(
                            "ha_alarms: volume stepped to %.0f%% on %s",
                            ring_volume * 100,
                            media_player_id,
                        )

                    mp_state = hass.states.get(media_player_id)
                    if mp_state and mp_state.state in ("idle", "paused", "off"):
                        if (now_mono - last_play_time) >= _MIN_RESTART_INTERVAL:
                            _LOGGER.debug(
                                "ha_alarms: media_player %s stopped — restarting alarm sound",
                                media_player_id,
                            )
                            await _play_sound(hass, media_player_id, sound_url)
                            last_play_time = now_mono

            else:
                # --- TTS-only fallback loop --------------------------------
                while True:
                    elapsed = 0.0
                    while elapsed < RING_INTERVAL:
                        if stop_event.is_set() or dismiss_event.is_set():
                            break
                        await asyncio.sleep(_POLL_INTERVAL)
                        elapsed += _POLL_INTERVAL

                    if stop_event.is_set() or dismiss_event.is_set():
                        break

                    _watching = False
                    await _announce(hass, satellite_entity_id, initial_msg)
                    await asyncio.sleep(_SETTLE_DELAY)
                    saw_responding = False
                    _watching = True

        finally:
            _watching = False
            unsub()
            self._stop_events.pop(satellite_entity_id, None)

            if use_media:
                await _stop_sound(hass, media_player_id)
                if prior_volume is not None:
                    await _set_volume(hass, media_player_id, prior_volume)

            reason = "dismissed" if dismiss_event.is_set() else "stopped"
            _LOGGER.debug(
                "ha_alarms: ring loop for %s ended (%s)", satellite_entity_id, reason
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_sound_url(path: str) -> str:
    """Convert a sound path to a URL usable by media_player.play_media.

    Accepts:
      - Full HTTP/HTTPS URLs — returned as-is.
      - /local/... — files in /config/www/; served by HA at
        http://homeassistant.local:8123/local/... without auth tokens.
        ESPHome ffmpeg_proxy can fetch these directly.
      - /media/... — HA media-source path; requires auth tokens that
        ESPHome devices cannot supply. Rewritten to /local/alarms/<filename>
        so stored items written with /media/ paths still resolve correctly
        (files must be present in /config/www/alarms/).
    """
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if path.startswith("/local/"):
        return f"http://homeassistant.local:8123{path}"
    if path.startswith("/media/"):
        filename = path.rstrip("/").rsplit("/", 1)[-1]
        rewritten = f"/local/alarms/{filename}"
        _LOGGER.debug(
            "ha_alarms: rewrote /media/ sound path %r → %r (auth not available to ESPHome)",
            path, rewritten,
        )
        return f"http://homeassistant.local:8123{rewritten}"
    _LOGGER.warning("ha_alarms: unrecognised sound path format %r — using as-is", path)
    return path


def _get_media_player_id(hass: HomeAssistant, satellite_entity_id: str) -> str | None:
    """Return the best media_player entity on the same device as the satellite.

    When a device has multiple media_player entities (e.g. a raw ESPHome player
    AND a Music Assistant wrapper), prefer the non-Music-Assistant one to avoid
    interfering with Music Assistant playback state.  Falls back to any
    media_player entity if all are from Music Assistant.
    """
    ent_reg = er.async_get(hass)
    sat_entry = ent_reg.async_get(satellite_entity_id)
    if sat_entry is None or sat_entry.device_id is None:
        _LOGGER.debug(
            "ha_alarms: satellite %s has no device_id in registry",
            satellite_entity_id,
        )
        return None

    candidates = [
        entry
        for entry in er.async_entries_for_device(ent_reg, sat_entry.device_id)
        if entry.domain == "media_player"
    ]
    if not candidates:
        _LOGGER.debug(
            "ha_alarms: no media_player entity found for satellite %s",
            satellite_entity_id,
        )
        return None

    # Prefer non-Music-Assistant players (raw ESPHome / HA device players).
    non_ma = [e for e in candidates if e.platform != "music_assistant"]
    pick = (non_ma or candidates)[0]
    _LOGGER.debug(
        "ha_alarms: resolved media_player %s for satellite %s",
        pick.entity_id,
        satellite_entity_id,
    )
    return pick.entity_id


async def _announce(hass: HomeAssistant, satellite_entity_id: str, message: str) -> None:
    """Call assist_satellite.announce and wait for it to return."""
    try:
        await hass.services.async_call(
            "assist_satellite",
            "announce",
            {"entity_id": satellite_entity_id, "message": message},
            blocking=True,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "ha_alarms: assist_satellite.announce failed for %s",
            satellite_entity_id,
            exc_info=True,
        )


async def _play_sound(hass: HomeAssistant, media_player_id: str, url: str) -> None:
    """Start playing the alarm sound on the media player."""
    try:
        await hass.services.async_call(
            "media_player",
            "play_media",
            {
                "entity_id": media_player_id,
                "media_content_id": url,
                "media_content_type": "music",
            },
            blocking=True,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "ha_alarms: media_player.play_media failed for %s",
            media_player_id,
            exc_info=True,
        )


async def _stop_sound(hass: HomeAssistant, media_player_id: str) -> None:
    """Stop playback on the media player."""
    try:
        await hass.services.async_call(
            "media_player",
            "media_stop",
            {"entity_id": media_player_id},
            blocking=True,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "ha_alarms: media_player.media_stop failed for %s",
            media_player_id,
            exc_info=True,
        )


async def _set_volume(hass: HomeAssistant, media_player_id: str, level: float) -> None:
    """Set the media player volume to level (0.0–1.0)."""
    try:
        await hass.services.async_call(
            "media_player",
            "volume_set",
            {"entity_id": media_player_id, "volume_level": round(level, 2)},
            blocking=True,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "ha_alarms: media_player.volume_set failed for %s",
            media_player_id,
            exc_info=True,
        )
