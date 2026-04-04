"""The ha_alarms integration.

Config-entry setup only — there is no YAML (async_setup) path. One coordinator
instance is created per entry and stored at hass.data[DOMAIN]. Because the
integration enforces a single entry via the config flow's already_configured
guard, hass.data[DOMAIN] always holds exactly one AlarmCoordinator.

Services registered:
  ha_alarms.set_alarm      satellite (opt), time, date (opt), label (opt)
  ha_alarms.set_reminder   satellite (opt), time, date (opt), label
  ha_alarms.cancel_alarm   item_id
  ha_alarms.cancel_reminder item_id
  ha_alarms.snooze         item_id, minutes (opt, default 10)
  ha_alarms.stop_all       (no parameters)
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent
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
    SERVICE_CANCEL_ALARM,
    SERVICE_CANCEL_REMINDER,
    SERVICE_SET_ALARM,
    SERVICE_SET_REMINDER,
    SERVICE_SNOOZE,
    SERVICE_STOP_ALL,
)
from .coordinator import AlarmCoordinator
from .datetime_parser import ParseAmbiguousError, ParseError, parse_datetime
from .intent_handler import (
    INTENT_CANCEL_ALARM,
    INTENT_CANCEL_REMINDER,
    INTENT_CANCEL_ALL_ALARMS,
    INTENT_CANCEL_ALL_REMINDERS,
    INTENT_LIST_ALARMS,
    INTENT_LIST_REMINDERS,
    INTENT_SET_ALARM,
    INTENT_SET_REMINDER,
    INTENT_SNOOZE_ALARM,
    INTENT_SNOOZE_REMINDER,
    INTENT_STOP_ALARM,
    INTENT_STOP_REMINDER,
    async_setup_intents,
)

_LOGGER = logging.getLogger(__name__)

_ALL_INTENTS = (
    INTENT_SET_ALARM,
    INTENT_SET_REMINDER,
    INTENT_STOP_ALARM,
    INTENT_STOP_REMINDER,
    INTENT_SNOOZE_ALARM,
    INTENT_SNOOZE_REMINDER,
    INTENT_CANCEL_ALARM,
    INTENT_CANCEL_REMINDER,
    INTENT_LIST_ALARMS,
    INTENT_LIST_REMINDERS,
    INTENT_CANCEL_ALL_ALARMS,
    INTENT_CANCEL_ALL_REMINDERS,
)

# ---------------------------------------------------------------------------
# Service schemas
# ---------------------------------------------------------------------------

_SCHEMA_SET_ALARM = vol.Schema(
    {
        vol.Optional(ATTR_SATELLITE): str,
        vol.Required("time_str"): str,
        vol.Optional("date_str"): str,
        vol.Optional(ATTR_LABEL, default="Alarm"): str,
        vol.Optional(ATTR_REPEAT, default=REPEAT_ONCE): str,
    }
)

_SCHEMA_SET_REMINDER = vol.Schema(
    {
        vol.Optional(ATTR_SATELLITE): str,
        vol.Required("time_str"): str,
        vol.Optional("date_str"): str,
        vol.Required(ATTR_LABEL): str,
        vol.Optional(ATTR_REPEAT, default=REPEAT_ONCE): str,
    }
)

_SCHEMA_ITEM_ID = vol.Schema({vol.Required("item_id"): str})

_SCHEMA_SNOOZE = vol.Schema(
    {
        vol.Required("item_id"): str,
        vol.Optional("minutes", default=DEFAULT_SNOOZE_MINUTES): vol.All(
            int, vol.Range(min=1)
        ),
    }
)


# ---------------------------------------------------------------------------
# Entry setup / teardown
# ---------------------------------------------------------------------------

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ha_alarms from a config entry."""
    coordinator = AlarmCoordinator(hass, entry)
    hass.data[DOMAIN] = coordinator

    await coordinator.async_load()

    # --- Service handlers -------------------------------------------------

    async def handle_set_alarm(call: ServiceCall) -> None:
        scheduled_at, error = _parse_time_from_call(call)
        if error:
            raise HomeAssistantError(error)
        await coordinator.schedule_item(
            {
                "type": ITEM_TYPE_ALARM,
                ATTR_LABEL: call.data.get(ATTR_LABEL, "Alarm"),
                ATTR_SATELLITE: call.data.get(ATTR_SATELLITE),
                "scheduled_at": scheduled_at,
                ATTR_REPEAT: call.data.get(ATTR_REPEAT, REPEAT_ONCE),
            }
        )

    async def handle_set_reminder(call: ServiceCall) -> None:
        scheduled_at, error = _parse_time_from_call(call)
        if error:
            raise HomeAssistantError(error)
        await coordinator.schedule_item(
            {
                "type": ITEM_TYPE_REMINDER,
                ATTR_LABEL: call.data[ATTR_LABEL],
                ATTR_SATELLITE: call.data.get(ATTR_SATELLITE),
                "scheduled_at": scheduled_at,
                ATTR_REPEAT: call.data.get(ATTR_REPEAT, REPEAT_ONCE),
            }
        )

    async def handle_cancel_alarm(call: ServiceCall) -> None:
        item_id = call.data["item_id"]
        if not await coordinator.cancel_item(item_id):
            raise HomeAssistantError(f"Alarm not found: {item_id}")

    async def handle_cancel_reminder(call: ServiceCall) -> None:
        item_id = call.data["item_id"]
        if not await coordinator.cancel_item(item_id):
            raise HomeAssistantError(f"Reminder not found: {item_id}")

    async def handle_snooze(call: ServiceCall) -> None:
        item_id = call.data["item_id"]
        minutes = call.data.get("minutes", DEFAULT_SNOOZE_MINUTES)
        if not await coordinator.snooze_item(item_id, minutes):
            raise HomeAssistantError(f"Item not found: {item_id}")

    async def handle_stop_all(call: ServiceCall) -> None:  # noqa: ARG001
        await coordinator.stop_all_active()

    async def handle_purge(call: ServiceCall) -> None:  # noqa: ARG001
        count = await coordinator.purge_missed()
        _LOGGER.info("ha_alarms: purged %d missed item(s)", count)

    hass.services.async_register(DOMAIN, SERVICE_SET_ALARM, handle_set_alarm, schema=_SCHEMA_SET_ALARM)
    hass.services.async_register(DOMAIN, SERVICE_SET_REMINDER, handle_set_reminder, schema=_SCHEMA_SET_REMINDER)
    hass.services.async_register(DOMAIN, SERVICE_CANCEL_ALARM, handle_cancel_alarm, schema=_SCHEMA_ITEM_ID)
    hass.services.async_register(DOMAIN, SERVICE_CANCEL_REMINDER, handle_cancel_reminder, schema=_SCHEMA_ITEM_ID)
    hass.services.async_register(DOMAIN, SERVICE_SNOOZE, handle_snooze, schema=_SCHEMA_SNOOZE)
    hass.services.async_register(DOMAIN, SERVICE_STOP_ALL, handle_stop_all)
    hass.services.async_register(DOMAIN, "purge", handle_purge)

    # --- Sensor platform --------------------------------------------------
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    # --- Intents ----------------------------------------------------------
    async_setup_intents(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload ha_alarms config entry."""
    await hass.config_entries.async_unload_platforms(entry, ["sensor"])

    coordinator: AlarmCoordinator = hass.data.pop(DOMAIN, None)
    if coordinator is not None:
        coordinator.async_cancel_all()

    for service in (
        SERVICE_SET_ALARM,
        SERVICE_SET_REMINDER,
        SERVICE_CANCEL_ALARM,
        SERVICE_CANCEL_REMINDER,
        SERVICE_SNOOZE,
        SERVICE_STOP_ALL,
    ):
        hass.services.async_remove(DOMAIN, service)

    # Clear the registration guard so intents are re-registered on reload.
    from .intent_handler import _INTENTS_REGISTERED_KEY
    hass.data.pop(_INTENTS_REGISTERED_KEY, None)

    # Unregister intent handlers (async_remove available in HA 2024.4+).
    if hasattr(intent, "async_remove"):
        for intent_type in _ALL_INTENTS:
            intent.async_remove(hass, intent_type)

    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_time_from_call(call: ServiceCall) -> tuple:
    """Parse time/date strings from a service call into a tz-aware datetime.

    Returns (datetime, None) on success or (None, error_message) on failure.
    """
    time_text = call.data.get("time_str", "")
    date_text = call.data.get("date_str") or None
    try:
        scheduled_at = parse_datetime(time_text, date_text, now=dt_util.now())
        return scheduled_at, None
    except ParseAmbiguousError as exc:
        return None, str(exc)
    except ParseError as exc:
        return None, f"Could not parse time: {exc}"
