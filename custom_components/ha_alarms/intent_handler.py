"""Intent handlers for ha_alarms voice commands.

Registers six intents with HA:
  HaAlarmsSetAlarm, HaAlarmsSetReminder
  HaAlarmsStopAlarm, HaAlarmsStopReminder
  HaAlarmsSnoozeAlarm, HaAlarmsSnoozeReminder

satellite_id extraction:
  Reads intent_obj.device_id (the device that triggered the assist pipeline),
  then resolves it to an assist_satellite.* entity ID via the entity registry.
  If device_id is absent or the device has no assist_satellite entity,
  satellite_id is set to None and logged at WARNING.

async_setup_intents(hass) is called once from __init__.async_setup_entry and
guards against double-registration with a flag in hass.data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, intent
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_LABEL,
    ATTR_REPEAT,
    ATTR_SATELLITE,
    DEFAULT_SNOOZE_MINUTES,
    DOMAIN,
    ITEM_TYPE_ALARM,
    ITEM_TYPE_REMINDER,
    REPEAT_ONCE,
)
from .coordinator import AlarmCoordinator
from .datetime_parser import ParseAmbiguousError, ParseError, parse_date, parse_datetime

_LOGGER = logging.getLogger(__name__)

# Guard key stored in hass.data to prevent double-registration.
_INTENTS_REGISTERED_KEY = f"{DOMAIN}_intents_registered"

# Intent type name constants (must match the sentence YAML).
INTENT_SET_ALARM = "HaAlarmsSetAlarm"
INTENT_SET_REMINDER = "HaAlarmsSetReminder"
INTENT_STOP_ALARM = "HaAlarmsStopAlarm"
INTENT_STOP_REMINDER = "HaAlarmsStopReminder"
INTENT_SNOOZE_ALARM = "HaAlarmsSnoozeAlarm"
INTENT_SNOOZE_REMINDER = "HaAlarmsSnoozeReminder"
INTENT_CANCEL_ALARM = "HaAlarmsCancelAlarm"
INTENT_CANCEL_REMINDER = "HaAlarmsCancelReminder"
INTENT_LIST_ALARMS = "HaAlarmsListAlarms"
INTENT_LIST_REMINDERS = "HaAlarmsListReminders"
INTENT_CANCEL_ALL_ALARMS = "HaAlarmsCancelAllAlarms"
INTENT_CANCEL_ALL_REMINDERS = "HaAlarmsCancelAllReminders"


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def async_setup_intents(hass: HomeAssistant) -> None:
    """Register all ha_alarms intent handlers. Safe to call multiple times."""
    if hass.data.get(_INTENTS_REGISTERED_KEY):
        return
    hass.data[_INTENTS_REGISTERED_KEY] = True

    for handler in (
        SetAlarmHandler(),
        SetReminderHandler(),
        StopAlarmHandler(),
        StopReminderHandler(),
        SnoozeAlarmHandler(),
        SnoozeReminderHandler(),
        CancelAlarmHandler(),
        CancelReminderHandler(),
        ListAlarmsHandler(),
        ListRemindersHandler(),
        CancelAllAlarmsHandler(),
        CancelAllRemindersHandler(),
    ):
        intent.async_register(hass, handler)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _extract_satellite_id(intent_obj: intent.Intent) -> str | None:
    """Return the assist_satellite entity ID for the originating device, or None.

    HA passes the satellite's device_id via intent_obj.device_id.  We resolve
    that to an assist_satellite.* entity ID via the entity registry.  Logs a
    WARNING and returns None if device_id is absent or has no assist_satellite
    entity — never raises.
    """
    device_id = getattr(intent_obj, "device_id", None)
    if not device_id:
        _LOGGER.debug(
            "ha_alarms: no device_id in intent — satellite will be None"
        )
        return None

    ent_reg = er.async_get(intent_obj.hass)
    for entry in er.async_entries_for_device(ent_reg, device_id):
        if entry.domain == "assist_satellite":
            return entry.entity_id

    _LOGGER.debug(
        "ha_alarms: device %s has no assist_satellite entity — satellite will be None",
        device_id,
    )
    return None


def _slot(intent_obj: intent.Intent, name: str) -> str | None:
    """Return the stripped string value of a slot, or None if absent or blank."""
    value = intent_obj.slots.get(name, {}).get("value")
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _get_coordinator(hass: HomeAssistant) -> AlarmCoordinator:
    return hass.data[DOMAIN]


def _format_dt_for_speech(dt: datetime, now: datetime) -> str:
    """Format a datetime as a natural spoken string.

    Examples: "7:30 AM", "7:30 AM tomorrow", "7:30 AM on Monday"
    """
    time_str = dt.strftime("%I:%M %p").lstrip("0")
    if dt.date() == now.date():
        return time_str
    if dt.date() == (now + timedelta(days=1)).date():
        return f"{time_str} tomorrow"
    return f"{time_str} on {dt.strftime('%A')}"


def _parse_slots(
    intent_obj: intent.Intent,
) -> tuple[datetime, None] | tuple[None, str]:
    """Parse the time and date slots into a scheduled datetime.

    Returns (datetime, None) on success or (None, error_speech) on failure.
    """
    time_text = _slot(intent_obj, "time")
    if not time_text:
        return None, "Sorry, I didn't catch the time."

    date_text = _slot(intent_obj, "date")

    try:
        scheduled_at = parse_datetime(time_text, date_text, now=dt_util.now())
        return scheduled_at, None
    except ParseAmbiguousError as exc:
        return None, str(exc)
    except ParseError:
        return None, "Sorry, I didn't understand that time."


# ---------------------------------------------------------------------------
# Set handlers
# ---------------------------------------------------------------------------

class SetAlarmHandler(intent.IntentHandler):
    """HaAlarmsSetAlarm — schedule an alarm on the originating satellite."""

    intent_type = INTENT_SET_ALARM

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        response = intent_obj.create_response()

        scheduled_at, error = _parse_slots(intent_obj)
        if error:
            response.async_set_speech(error)
            return response

        label = _slot(intent_obj, "label") or "Alarm"
        satellite_id = _extract_satellite_id(intent_obj)
        repeat = _slot(intent_obj, "repeat") or REPEAT_ONCE

        await _get_coordinator(hass).schedule_item({
            "type": ITEM_TYPE_ALARM,
            ATTR_LABEL: label,
            ATTR_SATELLITE: satellite_id,
            "scheduled_at": scheduled_at,
            ATTR_REPEAT: repeat,
        })

        spoken_time = _format_dt_for_speech(scheduled_at, dt_util.now())
        if repeat == REPEAT_ONCE:
            response.async_set_speech(f"Alarm set for {spoken_time}.")
        else:
            response.async_set_speech(f"{repeat.capitalize()} alarm set for {spoken_time}.")
        return response


class SetReminderHandler(intent.IntentHandler):
    """HaAlarmsSetReminder — schedule a named reminder on the originating satellite."""

    intent_type = INTENT_SET_REMINDER

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        response = intent_obj.create_response()

        label = _slot(intent_obj, "label")
        if not label:
            response.async_set_speech("Sorry, what should I remind you about?")
            return response

        scheduled_at, error = _parse_slots(intent_obj)
        if error:
            response.async_set_speech(error)
            return response

        satellite_id = _extract_satellite_id(intent_obj)

        await _get_coordinator(hass).schedule_item({
            "type": ITEM_TYPE_REMINDER,
            ATTR_LABEL: label,
            ATTR_SATELLITE: satellite_id,
            "scheduled_at": scheduled_at,
            ATTR_REPEAT: REPEAT_ONCE,
        })

        spoken_time = _format_dt_for_speech(scheduled_at, dt_util.now())
        response.async_set_speech(f"Reminder set for {spoken_time}: {label}.")
        return response


# ---------------------------------------------------------------------------
# Stop handlers
# ---------------------------------------------------------------------------

class StopAlarmHandler(intent.IntentHandler):
    """HaAlarmsStopAlarm — stop a ringing alarm, or cancel the next scheduled one."""

    intent_type = INTENT_STOP_ALARM

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        coordinator = _get_coordinator(hass)
        response = intent_obj.create_response()

        active = [
            i for i in coordinator.get_items()
            if i.get("type") == ITEM_TYPE_ALARM and i.get("status") == "active"
        ]
        if active:
            await coordinator.stop_all_active(item_type=ITEM_TYPE_ALARM)
            response.async_set_speech("Alarm stopped.")
        else:
            satellite_id = _extract_satellite_id(intent_obj)
            cancelled = await coordinator.cancel_next_scheduled(ITEM_TYPE_ALARM, satellite_id)
            if cancelled:
                spoken_time = _format_dt_for_speech(cancelled["scheduled_at"], dt_util.now())
                label = cancelled.get("label", "Alarm")
                response.async_set_speech(f"{label} for {spoken_time} cancelled.")
            else:
                response.async_set_speech("No alarm found.")
        return response


class StopReminderHandler(intent.IntentHandler):
    """HaAlarmsStopReminder — stop a ringing reminder, or cancel the next scheduled one."""

    intent_type = INTENT_STOP_REMINDER

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        coordinator = _get_coordinator(hass)
        response = intent_obj.create_response()

        active = [
            i for i in coordinator.get_items()
            if i.get("type") == ITEM_TYPE_REMINDER and i.get("status") == "active"
        ]
        if active:
            await coordinator.stop_all_active(item_type=ITEM_TYPE_REMINDER)
            response.async_set_speech("Reminder stopped.")
        else:
            satellite_id = _extract_satellite_id(intent_obj)
            cancelled = await coordinator.cancel_next_scheduled(ITEM_TYPE_REMINDER, satellite_id)
            if cancelled:
                label = cancelled.get("label", "Reminder")
                response.async_set_speech(f"Reminder '{label}' cancelled.")
            else:
                response.async_set_speech("No reminder found.")
        return response


# ---------------------------------------------------------------------------
# Snooze handlers
# ---------------------------------------------------------------------------

class SnoozeAlarmHandler(intent.IntentHandler):
    """HaAlarmsSnoozeAlarm — snooze the currently-ringing alarm.

    This handler also covers "snooze while ringing" — no separate handler is
    needed.  While the alarm bell is playing, the ReSpeaker microphone remains
    active (ESPHome hardware, mic and speaker are independent).  When the user
    says "snooze", HA routes the intent here; _handle_snooze finds the active
    item on the originating satellite and calls coordinator.snooze_item(), which
    stops the ring task and reschedules for now + N minutes.
    """

    intent_type = INTENT_SNOOZE_ALARM

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        return await _handle_snooze(intent_obj, ITEM_TYPE_ALARM)


class SnoozeReminderHandler(intent.IntentHandler):
    """HaAlarmsSnoozeReminder — snooze the currently-ringing reminder."""

    intent_type = INTENT_SNOOZE_REMINDER

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        return await _handle_snooze(intent_obj, ITEM_TYPE_REMINDER)


# ---------------------------------------------------------------------------
# Cancel-by-label handlers
# ---------------------------------------------------------------------------

class CancelAlarmHandler(intent.IntentHandler):
    """HaAlarmsCancelAlarm — cancel a scheduled alarm by label."""

    intent_type = INTENT_CANCEL_ALARM

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        return await _handle_cancel(intent_obj, ITEM_TYPE_ALARM)


class CancelReminderHandler(intent.IntentHandler):
    """HaAlarmsCancelReminder — cancel a scheduled reminder by label."""

    intent_type = INTENT_CANCEL_REMINDER

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        return await _handle_cancel(intent_obj, ITEM_TYPE_REMINDER)


# ---------------------------------------------------------------------------
# List handlers
# ---------------------------------------------------------------------------

_COUNT_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


def _count_word(n: int) -> str:
    """Return 'one', 'two', … 'five' for 1–5; digits for 6+."""
    return _COUNT_WORDS.get(n, str(n))


class ListAlarmsHandler(intent.IntentHandler):
    """HaAlarmsListAlarms — list scheduled alarms on the originating satellite."""

    intent_type = INTENT_LIST_ALARMS

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        coordinator = _get_coordinator(hass)
        response = intent_obj.create_response()
        satellite_id = _extract_satellite_id(intent_obj)
        now = dt_util.now()

        items = coordinator.get_scheduled_items(ITEM_TYPE_ALARM, satellite_id)

        if not items:
            response.async_set_speech("You have no alarms set.")
        elif len(items) == 1:
            t = _format_dt_for_speech(items[0]["scheduled_at"], now)
            response.async_set_speech(f"You have one alarm set: {t}.")
        elif len(items) == 2:
            t1 = _format_dt_for_speech(items[0]["scheduled_at"], now)
            t2 = _format_dt_for_speech(items[1]["scheduled_at"], now)
            response.async_set_speech(f"You have two alarms set: {t1} and {t2}.")
        else:
            n = len(items)
            first3 = [_format_dt_for_speech(i["scheduled_at"], now) for i in items[:3]]
            listed = f"{first3[0]}, {first3[1]}, and {first3[2]}"
            remaining = n - 3
            if remaining > 0:
                extra = f" and {_count_word(remaining)} more"
                response.async_set_speech(
                    f"You have {_count_word(n)} alarms set: {listed}{extra}."
                )
            else:
                response.async_set_speech(
                    f"You have {_count_word(n)} alarms set: {listed}."
                )
        return response


class ListRemindersHandler(intent.IntentHandler):
    """HaAlarmsListReminders — list scheduled reminders on the originating satellite."""

    intent_type = INTENT_LIST_REMINDERS

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        coordinator = _get_coordinator(hass)
        response = intent_obj.create_response()
        satellite_id = _extract_satellite_id(intent_obj)
        now = dt_util.now()

        items = coordinator.get_scheduled_items(ITEM_TYPE_REMINDER, satellite_id)

        def _fmt_reminder(item: dict) -> str:
            label = (item.get(ATTR_LABEL) or "").strip() or "reminder"
            t = _format_dt_for_speech(item["scheduled_at"], now)
            return f"{label} at {t}"

        if not items:
            response.async_set_speech("You have no reminders set.")
        elif len(items) == 1:
            response.async_set_speech(f"You have one reminder set: {_fmt_reminder(items[0])}.")
        elif len(items) == 2:
            r1 = _fmt_reminder(items[0])
            r2 = _fmt_reminder(items[1])
            response.async_set_speech(f"You have two reminders set: {r1} and {r2}.")
        else:
            n = len(items)
            first3 = [_fmt_reminder(i) for i in items[:3]]
            listed = f"{first3[0]}, {first3[1]}, and {first3[2]}"
            remaining = n - 3
            if remaining > 0:
                extra = f" and {_count_word(remaining)} more"
                response.async_set_speech(
                    f"You have {_count_word(n)} reminders set: {listed}{extra}."
                )
            else:
                response.async_set_speech(
                    f"You have {_count_word(n)} reminders set: {listed}."
                )
        return response


# ---------------------------------------------------------------------------
# Cancel-all handlers
# ---------------------------------------------------------------------------

class CancelAllAlarmsHandler(intent.IntentHandler):
    """HaAlarmsCancelAllAlarms — cancel every scheduled alarm."""

    intent_type = INTENT_CANCEL_ALL_ALARMS

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        return await _handle_cancel_all(intent_obj, ITEM_TYPE_ALARM)


class CancelAllRemindersHandler(intent.IntentHandler):
    """HaAlarmsCancelAllReminders — cancel every scheduled reminder."""

    intent_type = INTENT_CANCEL_ALL_REMINDERS

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        return await _handle_cancel_all(intent_obj, ITEM_TYPE_REMINDER)


async def _handle_cancel_all(
    intent_obj: intent.Intent, item_type: str
) -> intent.IntentResponse:
    hass = intent_obj.hass
    coordinator = _get_coordinator(hass)
    response = intent_obj.create_response()
    noun_plural = "alarms" if item_type == ITEM_TYPE_ALARM else "reminders"
    satellite_id = _extract_satellite_id(intent_obj)

    # Stop any currently-ringing items of this type first.
    await coordinator.stop_all_active(item_type=item_type)

    # Cancel all scheduled items.
    count = await coordinator.cancel_all_scheduled(item_type, satellite_id)

    if count == 0:
        response.async_set_speech(f"No {noun_plural} to cancel.")
    else:
        response.async_set_speech(f"All {noun_plural} cancelled.")
    return response


async def _handle_cancel(
    intent_obj: intent.Intent, item_type: str
) -> intent.IntentResponse:
    hass = intent_obj.hass
    coordinator = _get_coordinator(hass)
    response = intent_obj.create_response()
    noun = "alarm" if item_type == ITEM_TYPE_ALARM else "reminder"

    label_query = _slot(intent_obj, "label")
    satellite_id = _extract_satellite_id(intent_obj)

    cancelled = None
    if label_query:
        # 1. Try label substring match (e.g. "cancel my wake up alarm").
        cancelled = await coordinator.cancel_by_label(item_type, label_query, satellite_id)

        # 2. If nothing matched, try interpreting the label slot as a time
        #    expression (e.g. "cancel 9 am alarm", "cancel sunday 3 pm alarm").
        if not cancelled:
            try:
                target_dt = parse_datetime(label_query, now=dt_util.now())
                cancelled = await coordinator.cancel_by_time(item_type, target_dt, satellite_id)
            except (ParseAmbiguousError, ParseError):
                pass

        # 3. If still nothing, try as a bare date ("cancel tuesday alarm",
        #    "cancel tomorrow alarm") — matches any alarm on that day.
        if not cancelled:
            try:
                target_date = parse_date(label_query, now=dt_util.now())
                cancelled = await coordinator.cancel_by_date(item_type, target_date, satellite_id)
            except ParseError:
                pass
    else:
        cancelled = await coordinator.cancel_next_scheduled(item_type, satellite_id)

    if cancelled:
        label = cancelled.get("label") or noun.capitalize()
        spoken_time = _format_dt_for_speech(cancelled["scheduled_at"], dt_util.now())
        response.async_set_speech(f"{label} for {spoken_time} cancelled.")
    else:
        if label_query:
            response.async_set_speech(f"No {noun} matching '{label_query}' found.")
        else:
            response.async_set_speech(f"No {noun} found.")
    return response


async def _handle_snooze(
    intent_obj: intent.Intent, item_type: str
) -> intent.IntentResponse:
    hass = intent_obj.hass
    coordinator = _get_coordinator(hass)
    response = intent_obj.create_response()

    minutes_raw = _slot(intent_obj, "minutes")
    try:
        minutes = int(minutes_raw) if minutes_raw is not None else DEFAULT_SNOOZE_MINUTES
        if minutes <= 0:
            raise ValueError("minutes must be positive")
    except (ValueError, TypeError):
        minutes = DEFAULT_SNOOZE_MINUTES

    satellite_id = _extract_satellite_id(intent_obj)

    # Find active items of the requested type. If satellite_id is known, restrict
    # to that satellite; otherwise accept any (handles non-satellite invocations).
    active: list[dict[str, Any]] = [
        item for item in coordinator.get_items()
        if item.get("type") == item_type
        and item.get("status") == "active"
        and (satellite_id is None or item.get(ATTR_SATELLITE) == satellite_id)
    ]

    if not active:
        noun = "alarm" if item_type == ITEM_TYPE_ALARM else "reminder"
        response.async_set_speech(f"There's no {noun} currently ringing.")
        return response

    # Snooze the item that fired most recently (latest scheduled_at).
    target = max(active, key=lambda it: it.get("scheduled_at") or datetime.min)
    await coordinator.snooze_item(target["id"], minutes)

    response.async_set_speech(f"Snoozed for {minutes} minutes.")
    return response
