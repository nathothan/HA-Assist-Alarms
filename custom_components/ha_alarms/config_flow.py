"""Config flow for ha_alarms.

Single-step, zero-credential flow. Aborts if the domain is already configured
so there is always at most one entry.

The options flow (accessible via the "Configure" button in Settings →
Devices & Services) lets users assign a custom alarm sound to each satellite
without editing const.py.  One text field per discovered assist_satellite.*
entity, pre-populated with the current option or the DEVICE_SOUNDS default.
"""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector
import voluptuous as vol

from .const import DEFAULT_ALARM_SOUND, DEVICE_CONFIG, DOMAIN


class HaAlarmsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the HA Alarms config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Single confirmation step — no credentials or host required."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            return self.async_create_entry(title="HA Alarms", data={})

        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow — configure per-satellite alarm sounds."""

    async def async_step_init(self, user_input=None):
        """Show one text field per assist_satellite entity."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        ent_reg = er.async_get(self.hass)
        satellites = sorted(
            [e for e in ent_reg.entities.values() if e.domain == "assist_satellite"],
            key=lambda e: e.entity_id,
        )

        current = self.config_entry.options
        schema_dict: dict = {}
        for sat in satellites:
            default = (
                current.get(sat.entity_id)
                or DEVICE_CONFIG.get(sat.entity_id, {}).get("sound")
                or DEFAULT_ALARM_SOUND
            )
            schema_dict[vol.Optional(sat.entity_id, default=default)] = (
                selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                )
            )

        if not schema_dict:
            # No satellites found yet — show a plain info form with no fields.
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema({}),
                description_placeholders={"note": "No assist_satellite entities found."},
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
        )
