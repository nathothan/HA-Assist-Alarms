"""Sensor platform for ha_alarms — exposes scheduled items as HA state.

Creates two sensor entities per config entry:
  sensor.ha_alarms_alarms    — upcoming + active alarms
  sensor.ha_alarms_reminders — upcoming + active reminders

State  = count of scheduled/active items of that type.
Attributes = list of items with id, label, scheduled_at, status, repeat,
             satellite, and a human-readable 'when' string.

Both sensors update instantly via the SIGNAL_ITEMS_UPDATED dispatcher signal
fired by the coordinator on every mutation.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    DEVICE_CONFIG,
    DOMAIN,
    ITEM_TYPE_ALARM,
    ITEM_TYPE_REMINDER,
    SIGNAL_ITEMS_UPDATED,
)
from .coordinator import AlarmCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ha_alarms sensor entities."""
    coordinator: AlarmCoordinator = hass.data[DOMAIN]
    async_add_entities([
        HaAlarmsSensor(coordinator, ITEM_TYPE_ALARM),
        HaAlarmsSensor(coordinator, ITEM_TYPE_REMINDER),
    ])


class HaAlarmsSensor(SensorEntity):
    """A sensor that surfaces the list of upcoming alarms or reminders."""

    _attr_should_poll = False
    _attr_native_unit_of_measurement = "items"

    def __init__(self, coordinator: AlarmCoordinator, item_type: str) -> None:
        self._coordinator = coordinator
        self._item_type = item_type
        noun = "Alarms" if item_type == ITEM_TYPE_ALARM else "Reminders"
        self._attr_name = f"HA {noun}"
        self._attr_unique_id = f"{DOMAIN}_{item_type}s"
        self._attr_icon = "mdi:alarm" if item_type == ITEM_TYPE_ALARM else "mdi:bell"

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def native_value(self) -> int:
        """Return count of scheduled + active items."""
        return sum(
            1 for item in self._coordinator.get_items()
            if item.get("type") == self._item_type
            and item.get("status") in ("scheduled", "active")
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all items of this type as a structured list."""
        now = dt_util.now()
        items = []
        for item in self._coordinator.get_items():
            if item.get("type") != self._item_type:
                continue
            scheduled_at: datetime | None = item.get("scheduled_at")
            satellite = item.get("satellite")
            satellite_name = (
                DEVICE_CONFIG.get(satellite or "", {}).get("name")
                or satellite
            )
            items.append({
                "id": item.get("id"),
                "label": item.get("label", ""),
                "status": item.get("status", ""),
                "repeat": item.get("repeat", "once"),
                "satellite": satellite,
                "satellite_name": satellite_name,
                "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
                "when": _human_when(scheduled_at, now) if scheduled_at else "unknown",
            })

        # Sort: active first, then by scheduled time ascending.
        items.sort(key=lambda i: (
            0 if i["status"] == "active" else 1,
            i["scheduled_at"] or "",
        ))

        return {
            "items": items,
            "count": len(items),
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ITEMS_UPDATED,
                self.async_write_ha_state,
            )
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _human_when(scheduled_at: datetime, now: datetime) -> str:
    """Return a compact human-readable relative time string."""
    delta = scheduled_at - now
    total_seconds = int(delta.total_seconds())

    if total_seconds < 0:
        return f"missed ({scheduled_at.strftime('%-I:%M %p')})"

    if total_seconds < 60:
        return f"in {total_seconds}s"

    minutes = total_seconds // 60
    if minutes < 60:
        return f"in {minutes}m"

    hours = minutes // 60
    remaining_minutes = minutes % 60
    if scheduled_at.date() == now.date():
        base = f"today at {_fmt_time(scheduled_at)}"
    elif scheduled_at.date() == (now + __import__('datetime').timedelta(days=1)).date():
        base = f"tomorrow at {_fmt_time(scheduled_at)}"
    else:
        base = f"{scheduled_at.strftime('%A')} at {_fmt_time(scheduled_at)}"

    if hours < 24 and remaining_minutes:
        return f"in {hours}h {remaining_minutes}m ({base})"
    return base


def _fmt_time(dt: datetime) -> str:
    try:
        return dt.strftime("%-I:%M %p").lstrip("0") or dt.strftime("%I:%M %p")
    except ValueError:
        return dt.strftime("%I:%M %p").lstrip("0")
