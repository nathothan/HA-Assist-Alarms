"""Alarm and reminder coordinator for ha_alarms.

Owns all runtime state for scheduled alarms and reminders.

Storage layout (JSON via HA Store):
  { "items": { "<item_id>": { ... item dict with scheduled_at as ISO string ... } } }

Item dict fields:
  id           str           UUID, set at creation
  type         str           ITEM_TYPE_ALARM | ITEM_TYPE_REMINDER
  label        str           spoken name, may be empty
  satellite    str | None    assist_satellite.* entity ID; None = log & skip at fire
  scheduled_at datetime      tz-aware; ISO string in storage
  repeat       str           REPEAT_ONCE | REPEAT_DAILY | REPEAT_WEEKDAYS | REPEAT_WEEKENDS
  enabled      bool
  status       str           "scheduled" | "active" | "missed"
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .announcer import Announcer
from .const import (
    ATTR_LABEL,
    ATTR_REPEAT,
    ATTR_SATELLITE,
    ATTR_SOUND,
    ATTR_VOLUME_END,
    ATTR_VOLUME_RAMP,
    ATTR_VOLUME_START,
    DEFAULT_ALARM_SOUND,
    DEFAULT_VOLUME_END,
    DEFAULT_VOLUME_RAMP,
    DEFAULT_VOLUME_START,
    DEVICE_CONFIG,
    ITEM_TYPE_ALARM,
    REPEAT_DAILY,
    REPEAT_ONCE,
    REPEAT_WEEKDAYS,
    REPEAT_WEEKENDS,
    SIGNAL_ITEMS_UPDATED,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

_STATUS_SCHEDULED = "scheduled"
_STATUS_ACTIVE = "active"
_STATUS_MISSED = "missed"


class AlarmCoordinator:
    """Central coordinator: persists items, schedules callbacks, drives the Announcer."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._items: dict[str, dict[str, Any]] = {}
        # async_track_point_in_time cancel handles, one per pending item.
        self._cancel_handles: dict[str, Any] = {}
        # Active ring tasks, one per currently-ringing item.
        self._ring_tasks: dict[str, asyncio.Task] = {}
        self._announcer = Announcer(hass)

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def async_load(self) -> None:
        """Load persisted items and re-register callbacks for future-dated ones.

        Recovery rules on startup:
        - One-shot items that are past-due or were active at shutdown → deleted.
        - Repeating items that are past-due or were active at shutdown → advanced
          to next occurrence and rescheduled.
        - Future scheduled items → rescheduled normally.
        - Disabled items → kept in storage but not scheduled.
        """
        raw = await self._store.async_load()
        if not raw:
            return

        now = dt_util.now()
        changed = False

        for item_id, item in (raw.get("items") or {}).items():
            scheduled_at = _parse_stored_dt(item_id, item.get("scheduled_at"))
            if scheduled_at is None:
                changed = True  # unparseable — omit from self._items → pruned on save
                continue

            item["scheduled_at"] = scheduled_at
            label = item.get(ATTR_LABEL) or "<unlabelled>"
            repeat = item.get(ATTR_REPEAT, REPEAT_ONCE)
            status = item.get("status", _STATUS_SCHEDULED)
            enabled = item.get("enabled", True)

            needs_recovery = (
                status == _STATUS_ACTIVE
                or status == _STATUS_MISSED
                or (status == _STATUS_SCHEDULED and scheduled_at <= now)
            )

            if needs_recovery:
                changed = True
                if repeat == REPEAT_ONCE or not enabled:
                    if status == _STATUS_ACTIVE:
                        _LOGGER.warning(
                            "ha_alarms: '%s' (id=%s) was active at shutdown — removing",
                            label, item_id,
                        )
                    elif status != _STATUS_MISSED:
                        _LOGGER.warning(
                            "ha_alarms: '%s' (id=%s) scheduled for %s was missed — removing",
                            label, item_id, scheduled_at.isoformat(),
                        )
                    # Do not add to self._items — omitting = deletion on next save.
                    continue

                # Repeating: advance to next future occurrence.
                next_dt = _next_occurrence(scheduled_at, repeat, now)
                if next_dt is None:
                    _LOGGER.warning(
                        "ha_alarms: '%s' (id=%s) repeating but has no next "
                        "occurrence — removing",
                        label, item_id,
                    )
                    continue
                _LOGGER.warning(
                    "ha_alarms: '%s' (id=%s) was %s — advanced to %s",
                    label, item_id, status, next_dt.isoformat(),
                )
                item["scheduled_at"] = next_dt
                item["status"] = _STATUS_SCHEDULED
                self._items[item_id] = item
                self._schedule_callback(item_id, next_dt)
                continue

            # Normal case: future item.
            self._items[item_id] = item
            if enabled and status == _STATUS_SCHEDULED:
                self._schedule_callback(item_id, scheduled_at)

        if changed:
            await self._async_save()

    # ------------------------------------------------------------------
    # Public mutations
    # ------------------------------------------------------------------

    async def schedule_item(self, data: dict[str, Any]) -> str:
        """Validate, persist, schedule a new item. Returns the new item_id."""
        item_id = str(uuid.uuid4())
        satellite_id = data.get(ATTR_SATELLITE)
        dev_cfg = DEVICE_CONFIG.get(satellite_id or "", {})
        sound = (
            data.get(ATTR_SOUND)
            or self._entry.options.get(satellite_id or "")
            or dev_cfg.get("sound")
            or DEFAULT_ALARM_SOUND
        )
        volume_start = dev_cfg.get("volume_start", DEFAULT_VOLUME_START)
        volume_end = dev_cfg.get("volume_end", DEFAULT_VOLUME_END)
        volume_ramp = dev_cfg.get("volume_ramp", DEFAULT_VOLUME_RAMP)
        item: dict[str, Any] = {
            "id": item_id,
            "type": data.get("type", ITEM_TYPE_ALARM),
            ATTR_LABEL: (data.get(ATTR_LABEL) or "").strip(),
            ATTR_SATELLITE: satellite_id,
            "scheduled_at": data["scheduled_at"],  # caller must supply tz-aware datetime
            ATTR_REPEAT: data.get(ATTR_REPEAT, REPEAT_ONCE),
            ATTR_SOUND: sound,
            ATTR_VOLUME_START: volume_start,
            ATTR_VOLUME_END: volume_end,
            ATTR_VOLUME_RAMP: volume_ramp,
            "enabled": data.get("enabled", True),
            "status": _STATUS_SCHEDULED,
        }
        self._items[item_id] = item
        self._schedule_callback(item_id, item["scheduled_at"])
        await self._async_save()
        self._signal_update()
        return item_id

    async def cancel_item(self, item_id: str) -> bool:
        """Cancel and permanently remove an item. Returns False if not found."""
        if item_id not in self._items:
            return False
        self._cancel_callback(item_id)
        self._stop_ring_externally(item_id)
        del self._items[item_id]
        await self._async_save()
        self._signal_update()
        return True

    async def snooze_item(self, item_id: str, minutes: int) -> bool:
        """Stop active ring and reschedule for now + minutes. Returns False if not found."""
        if item_id not in self._items:
            return False
        # Stop ring first — done callback checks status to skip lifecycle logic.
        self._stop_ring_externally(item_id)
        self._cancel_callback(item_id)

        item = self._items[item_id]
        item["scheduled_at"] = dt_util.now() + timedelta(minutes=minutes)
        item["status"] = _STATUS_SCHEDULED
        self._schedule_callback(item_id, item["scheduled_at"])
        await self._async_save()
        self._signal_update()
        return True

    async def stop_all_active(self, item_type: str | None = None) -> None:
        """Stop all currently-ringing items without removing them.

        If item_type is given (ITEM_TYPE_ALARM or ITEM_TYPE_REMINDER) only items
        of that type are stopped.  For one-shot items the ring task's done
        callback will remove the item; for repeating items it advances the
        schedule.
        """
        for item_id, item in list(self._items.items()):
            if item.get("status") == _STATUS_ACTIVE:
                if item_type is not None and item.get("type") != item_type:
                    continue
                satellite = item.get(ATTR_SATELLITE)
                if satellite:
                    self._announcer.stop(satellite)
                # Do NOT cancel the task directly — let the announcer exit cleanly
                # so _on_ring_done runs in normal flow and handles lifecycle.

    async def cancel_by_label(
        self, item_type: str, label_query: str, satellite_id: str | None = None
    ) -> dict[str, Any] | None:
        """Cancel the soonest scheduled item whose label contains label_query.

        Case-insensitive substring match.  satellite_id is not used as a filter
        (same reasoning as cancel_next_scheduled).  Returns a copy of the
        cancelled item, or None if nothing matched.
        """
        query = label_query.lower().strip()
        candidates = [
            item for item in self._items.values()
            if item.get("type") == item_type
            and item.get("status") == _STATUS_SCHEDULED
            and item.get("scheduled_at") is not None
            and query in (item.get(ATTR_LABEL) or "").lower()
        ]
        if not candidates:
            return None
        target = min(candidates, key=lambda i: i["scheduled_at"])
        snapshot = dict(target)
        await self.cancel_item(target["id"])
        return snapshot

    async def cancel_next_scheduled(
        self, item_type: str, satellite_id: str | None
    ) -> dict[str, Any] | None:
        """Cancel the soonest upcoming (not yet ringing) item of item_type.

        Satellite filtering is intentionally NOT applied here — you should be
        able to cancel any alarm regardless of which satellite it was set on.
        satellite_id is accepted for API consistency but unused.
        Returns a copy of the cancelled item, or None if nothing matched.
        """
        candidates = [
            item for item in self._items.values()
            if item.get("type") == item_type
            and item.get("status") == _STATUS_SCHEDULED
            and item.get("scheduled_at") is not None
        ]
        if not candidates:
            return None
        target = min(candidates, key=lambda i: i["scheduled_at"])
        snapshot = dict(target)
        await self.cancel_item(target["id"])
        return snapshot

    async def cancel_by_time(
        self, item_type: str, dt: datetime, satellite_id: str | None = None
    ) -> dict[str, Any] | None:
        """Cancel the soonest scheduled item whose hour+minute matches dt.

        Used when the user says "cancel my 9 AM alarm" — the label slot captured
        a time string rather than a named label.  Matches hour and minute only so
        "9 am" matches an alarm stored as 09:00 on any date.
        """
        candidates = [
            item for item in self._items.values()
            if item.get("type") == item_type
            and item.get("status") == _STATUS_SCHEDULED
            and item.get("scheduled_at") is not None
            and item["scheduled_at"].hour == dt.hour
            and item["scheduled_at"].minute == dt.minute
        ]
        if not candidates:
            return None
        target = min(candidates, key=lambda i: i["scheduled_at"])
        snapshot = dict(target)
        await self.cancel_item(target["id"])
        return snapshot

    async def cancel_by_date(
        self, item_type: str, target_date, satellite_id: str | None = None
    ) -> dict[str, Any] | None:
        """Cancel the soonest scheduled item on target_date (a datetime.date).

        Used when the user says "cancel tuesday alarm" — label slot captured a
        bare day name with no time.  Matches any alarm on that calendar date.
        """
        candidates = [
            item for item in self._items.values()
            if item.get("type") == item_type
            and item.get("status") == _STATUS_SCHEDULED
            and item.get("scheduled_at") is not None
            and item["scheduled_at"].date() == target_date
        ]
        if not candidates:
            return None
        target = min(candidates, key=lambda i: i["scheduled_at"])
        snapshot = dict(target)
        await self.cancel_item(target["id"])
        return snapshot

    async def purge_missed(self) -> int:
        """Delete all 'missed' items from storage. Returns count removed."""
        to_delete = [
            item_id for item_id, item in self._items.items()
            if item.get("status") == _STATUS_MISSED
        ]
        for item_id in to_delete:
            del self._items[item_id]
        if to_delete:
            await self._async_save()
            self._signal_update()
        return len(to_delete)

    def get_items(self) -> list[dict[str, Any]]:
        """Return a snapshot of all items (coordinator retains ownership)."""
        return list(self._items.values())

    def get_scheduled_items(
        self, item_type: str, satellite_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return all scheduled (not yet active) items of item_type, sorted by scheduled_at.

        If satellite_id is provided, only items assigned to that satellite are returned.
        """
        results = [
            item for item in self._items.values()
            if item.get("type") == item_type
            and item.get("status") == _STATUS_SCHEDULED
            and item.get("scheduled_at") is not None
            and (satellite_id is None or item.get(ATTR_SATELLITE) == satellite_id)
        ]
        results.sort(key=lambda i: i["scheduled_at"])
        return results

    async def cancel_all_scheduled(
        self, item_type: str, satellite_id: str | None = None
    ) -> int:
        """Cancel all scheduled (not yet active) items of item_type.

        If satellite_id is provided, only items assigned to that satellite are cancelled.
        Returns the count of items cancelled.
        """
        targets = [
            item["id"] for item in self._items.values()
            if item.get("type") == item_type
            and item.get("status") == _STATUS_SCHEDULED
            and (satellite_id is None or item.get(ATTR_SATELLITE) == satellite_id)
        ]
        for item_id in targets:
            await self.cancel_item(item_id)
        return len(targets)

    def async_cancel_all(self) -> None:
        """Cancel all pending callbacks and ring tasks. Called on integration unload."""
        for cancel in list(self._cancel_handles.values()):
            cancel()
        self._cancel_handles.clear()

        for item_id, item in list(self._items.items()):
            satellite = item.get(ATTR_SATELLITE)
            if satellite:
                self._announcer.stop(satellite)

        for task in list(self._ring_tasks.values()):
            if not task.done():
                task.cancel()
        self._ring_tasks.clear()

    # ------------------------------------------------------------------
    # Scheduling internals
    # ------------------------------------------------------------------

    def _schedule_callback(self, item_id: str, fire_at: datetime) -> None:
        """Register async_track_point_in_time for item_id, cancelling any prior handle."""
        self._cancel_callback(item_id)

        @callback
        def _fire(_now: datetime) -> None:
            self._hass.async_create_task(
                self._on_alarm_fire(item_id),
                name=f"ha_alarms_fire_{item_id}",
            )

        self._cancel_handles[item_id] = async_track_point_in_time(
            self._hass, _fire, fire_at
        )

    def _cancel_callback(self, item_id: str) -> None:
        cancel = self._cancel_handles.pop(item_id, None)
        if cancel is not None:
            cancel()

    def _stop_ring_externally(self, item_id: str) -> None:
        """Signal the announcer to stop, then cancel the task.

        Sets item status to _STATUS_SCHEDULED before the task's done callback
        runs so _on_ring_done knows the stop was external and skips lifecycle.
        """
        item = self._items.get(item_id)
        if item is not None and item.get("status") == _STATUS_ACTIVE:
            item["status"] = _STATUS_SCHEDULED  # sentinel for _on_ring_done

        satellite = (item or {}).get(ATTR_SATELLITE)
        if satellite:
            self._announcer.stop(satellite)

        task = self._ring_tasks.pop(item_id, None)
        if task and not task.done():
            task.cancel()

    # ------------------------------------------------------------------
    # Fire & ring lifecycle
    # ------------------------------------------------------------------

    async def _on_alarm_fire(self, item_id: str) -> None:
        """Called when an item's scheduled time arrives."""
        item = self._items.get(item_id)
        if item is None:
            _LOGGER.debug("ha_alarms: fire for unknown item_id=%s (already removed)", item_id)
            return
        if not item.get("enabled", True):
            _LOGGER.debug("ha_alarms: item_id=%s is disabled, skipping", item_id)
            return

        satellite = item.get(ATTR_SATELLITE)
        if satellite is None:
            _LOGGER.warning(
                "ha_alarms: '%s' (id=%s) has no satellite — cannot ring",
                item.get(ATTR_LABEL) or "<unlabelled>",
                item_id,
            )
            self._handle_no_satellite(item_id, item)
            return

        item["status"] = _STATUS_ACTIVE
        await self._async_save()

        task = self._hass.async_create_task(
            self._announcer.ring(satellite, item),
            name=f"ha_alarms_ring_{item_id}",
        )
        self._ring_tasks[item_id] = task
        task.add_done_callback(
            lambda _t: self._hass.async_create_task(
                self._on_ring_done(item_id),
                name=f"ha_alarms_ring_done_{item_id}",
            )
        )

    def _handle_no_satellite(self, item_id: str, item: dict[str, Any]) -> None:
        """Handle fire for an item with no satellite (log already emitted by caller)."""
        repeat = item.get(ATTR_REPEAT, REPEAT_ONCE)
        if repeat == REPEAT_ONCE:
            del self._items[item_id]
        else:
            next_dt = _next_occurrence(item["scheduled_at"], repeat, dt_util.now())
            if next_dt is not None:
                item["scheduled_at"] = next_dt
                item["status"] = _STATUS_SCHEDULED
                self._schedule_callback(item_id, next_dt)
            else:
                item["status"] = _STATUS_MISSED
        self._hass.async_create_task(self._async_save())
        self._signal_update()

    async def _on_ring_done(self, item_id: str) -> None:
        """Called when the ring task for item_id completes (dismissed, stopped, or error)."""
        self._ring_tasks.pop(item_id, None)
        item = self._items.get(item_id)
        if item is None:
            # Item was removed externally (cancel_item) while ring was active.
            return

        # If status is no longer _STATUS_ACTIVE the ring was stopped externally
        # (snooze or cancel_item restored/removed the item already).
        if item.get("status") != _STATUS_ACTIVE:
            return

        repeat = item.get(ATTR_REPEAT, REPEAT_ONCE)
        if repeat == REPEAT_ONCE:
            del self._items[item_id]
        else:
            next_dt = _next_occurrence(item["scheduled_at"], repeat, dt_util.now())
            if next_dt is not None:
                item["scheduled_at"] = next_dt
                item["status"] = _STATUS_SCHEDULED
                self._schedule_callback(item_id, next_dt)
            else:
                item["status"] = _STATUS_MISSED

        await self._async_save()
        self._signal_update()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _async_save(self) -> None:
        serialized: dict[str, Any] = {}
        for item_id, item in self._items.items():
            entry = dict(item)
            if isinstance(entry.get("scheduled_at"), datetime):
                entry["scheduled_at"] = entry["scheduled_at"].isoformat()
            serialized[item_id] = entry
        await self._store.async_save({"items": serialized})

    def _signal_update(self) -> None:
        async_dispatcher_send(self._hass, SIGNAL_ITEMS_UPDATED)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _next_occurrence(scheduled_at: datetime, repeat: str, now: datetime) -> datetime | None:
    """Return the next future fire time for a repeating item.

    Starts from scheduled_at + 1 day and advances until the result is both in
    the future and satisfies the repeat constraint.  O(n days missed) but n is
    always small in practice.
    """
    if repeat == REPEAT_ONCE:
        return None

    candidate = scheduled_at + timedelta(days=1)

    if repeat == REPEAT_DAILY:
        while candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    if repeat == REPEAT_WEEKDAYS:
        while candidate <= now or candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate

    if repeat == REPEAT_WEEKENDS:
        while candidate <= now or candidate.weekday() < 5:
            candidate += timedelta(days=1)
        return candidate

    return None


def _parse_stored_dt(item_id: str, value: Any) -> datetime | None:
    """Parse a stored ISO datetime string into a tz-aware datetime, or return None."""
    if not value:
        _LOGGER.warning("ha_alarms: item %s has no scheduled_at — skipping", item_id)
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        _LOGGER.warning(
            "ha_alarms: item %s has unparseable scheduled_at %r — skipping", item_id, value
        )
        return None
    if dt.tzinfo is None:
        # Shouldn't happen with our save code, but be defensive.
        _LOGGER.warning(
            "ha_alarms: item %s stored scheduled_at has no timezone — assuming UTC", item_id
        )
        dt = dt.replace(tzinfo=dt_util.UTC)
    return dt
