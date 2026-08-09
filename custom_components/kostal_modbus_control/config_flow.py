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
    CONF_KSEM_HOST, KSEM_PORT, KSEM_SLAVE_ID,
    REG_SENSOR_TYPE, REG_BATTERY_MGMT_MODE,
    BATTERY_MGMT_MODE_MODBUS, BATTERY_MGMT_MODE_MAP,
)
from .modbus_handler import KostalModbusHandler

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kostal Modbus Control."""

    VERSION = 1
    
    # Compatibility with different HA versions
    _attr_domain = DOMAIN

    def __init__(self) -> None:
        self._inverter_data: dict[str, Any] = {}
        self._sensor_type: int | None = None
        self._battery_mgmt_mode: int | None = None

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
                sensor_type = await handler.read_uint8(REG_SENSOR_TYPE)
                # Battery management mode — the inverter ignores every write
                # this integration makes unless this is set to Modbus
                battery_mgmt_mode = await handler.read_uint8(REG_BATTERY_MGMT_MODE)
                await handler.close()
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                self._inverter_data = dict(user_input)
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                self._sensor_type = sensor_type
                self._battery_mgmt_mode = battery_mgmt_mode
                # Warn when battery management is not set to Modbus. A failed
                # read leaves the mode unknown — don't raise a false alarm.
                if battery_mgmt_mode is not None and battery_mgmt_mode != BATTERY_MGMT_MODE_MODBUS:
                    _LOGGER.warning(
                        "Battery management mode is 0x%02X (%s) — the inverter will ignore "
                        "external charge/discharge commands until it is set to Modbus",
                        battery_mgmt_mode,
                        BATTERY_MGMT_MODE_MAP.get(battery_mgmt_mode, "unknown"),
                    )
                    return await self.async_step_battery_management()
                return await self._async_continue()

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

    async def _async_continue(self) -> FlowResult:
        """Continue to the KSEM step if one was detected, otherwise finish."""
        # KSEM detected (0x03) — offer to read it directly
        if self._sensor_type == 0x03:
            return await self.async_step_ksem()
        return self.async_create_entry(
            title=f"Kostal {self._inverter_data[CONF_HOST]}",
            data=self._inverter_data,
        )

    async def async_step_battery_management(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Warn that battery management is not set to Modbus, but let setup continue."""
        if user_input is not None:
            return await self._async_continue()

        mode = self._battery_mgmt_mode
        current_mode = BATTERY_MGMT_MODE_MAP.get(
            mode, f"Unknown (0x{mode:02X})" if mode is not None else "Unknown"
        )
        return self.async_show_form(
            step_id="battery_management",
            data_schema=vol.Schema({}),
            description_placeholders={"current_mode": current_mode},
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
