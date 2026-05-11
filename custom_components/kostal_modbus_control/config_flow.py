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
    CONF_KSEM_HOST, KSEM_PORT, KSEM_SLAVE_ID,
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

    def __init__(self) -> None:
        self._inverter_data: dict[str, Any] = {}

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
                # Detect sensor type to check for KSEM
                from .const import REG_SENSOR_TYPE
                sensor_type = await handler.read_uint8(REG_SENSOR_TYPE)
                await handler.close()
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                self._inverter_data = dict(user_input)
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                # KSEM detected (0x03) — proceed to KSEM step
                if sensor_type == 0x03:
                    return await self.async_step_ksem()
                # No KSEM — create entry directly
                return self.async_create_entry(
                    title=f"Kostal {user_input[CONF_HOST]}",
                    data=self._inverter_data,
                )

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

    async def async_step_ksem(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Optional step to configure KOSTAL Smart Energy Meter (KSEM)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            ksem_host = user_input.get(CONF_KSEM_HOST, "").strip()
            if ksem_host:
                # Test connection to KSEM
                ksem_handler = KostalModbusHandler(ksem_host, KSEM_PORT, KSEM_SLAVE_ID)
                try:
                    await ksem_handler.connect()
                    await ksem_handler.close()
                except Exception:
                    errors["base"] = "cannot_connect_ksem"
                else:
                    self._inverter_data[CONF_KSEM_HOST] = ksem_host
            # Empty host = skip KSEM
            if not errors:
                inverter_host = self._inverter_data[CONF_HOST]
                return self.async_create_entry(
                    title=f"Kostal {inverter_host}",
                    data=self._inverter_data,
                )

        data_schema = vol.Schema(
            {
                vol.Optional(CONF_KSEM_HOST, default=""): str,
            }
        )

        return self.async_show_form(
            step_id="ksem",
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
