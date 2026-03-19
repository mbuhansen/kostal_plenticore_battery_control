"""Config flow for Kostal Modbus Control integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResult

from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

from .const import (
    DEFAULT_PORT, DOMAIN, CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT, DEFAULT_UNIT_ID,
    CONF_INVERTER_TYPE, INVERTER_TYPE_HYBRID, INVERTER_TYPE_BI,
    CONF_MIN_SOC, CONF_MAX_SOC,
)
from .modbus_handler import KostalModbusHandler

_LOGGER = logging.getLogger(__name__)

_SOC_OPTIONS = [""] + [str(v) for v in range(5, 105, 5)]


def _soc_selector():
    return SelectSelector(
        SelectSelectorConfig(
            options=_SOC_OPTIONS,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kostal Modbus Control."""

    VERSION = 1
    
    # Compatibility with different HA versions
    _attr_domain = DOMAIN

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> KostalOptionsFlowHandler:
        return KostalOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            handler = KostalModbusHandler(
                user_input[CONF_HOST],
                DEFAULT_PORT,
                DEFAULT_UNIT_ID,
            )
            try:
                await handler.connect()
                await handler.close()
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                title = f"Kostal {user_input[CONF_HOST]}"
                return self.async_create_entry(title=title, data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_MODBUS_TIMEOUT, default=DEFAULT_MODBUS_TIMEOUT): int,
                vol.Required(CONF_INVERTER_TYPE, default=INVERTER_TYPE_HYBRID): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": INVERTER_TYPE_HYBRID, "label": "Plenticore Hybrid (reg. 1028)"},
                            {"value": INVERTER_TYPE_BI, "label": "Plenticore BI / Battery Inverter (reg. 1030)"},
                        ],
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )


class KostalOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Kostal Modbus Control."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MIN_SOC,
                    default=current.get(CONF_MIN_SOC, ""),
                ): _soc_selector(),
                vol.Optional(
                    CONF_MAX_SOC,
                    default=current.get(CONF_MAX_SOC, ""),
                ): _soc_selector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
