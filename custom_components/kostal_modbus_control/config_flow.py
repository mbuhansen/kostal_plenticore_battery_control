"""Config flow for Kostal Modbus Control integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResult

from .const import DEFAULT_PORT, DOMAIN, CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT, DEFAULT_UNIT_ID, CONF_DEVICE_NAME
from .modbus_handler import KostalModbusHandler

_LOGGER = logging.getLogger(__name__)

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kostal Modbus Control."""

    VERSION = 1
    
    # Compatibility with different HA versions
    _attr_domain = DOMAIN 

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            handler = KostalModbusHandler(
                user_input[CONF_HOST],
                user_input.get(CONF_PORT, DEFAULT_PORT),
                DEFAULT_UNIT_ID,
            )
            try:
                await handler.connect()
                await handler.close()
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                title = user_input.get(CONF_DEVICE_NAME) or f"Kostal {user_input[CONF_HOST]}"
                return self.async_create_entry(title=title, data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Required(CONF_MODBUS_TIMEOUT, default=DEFAULT_MODBUS_TIMEOUT): int,
                vol.Optional(CONF_DEVICE_NAME, default=""): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )
