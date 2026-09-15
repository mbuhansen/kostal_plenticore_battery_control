"""Config flow for Kostal Modbus Control integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST

from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    DEFAULT_PORT, DOMAIN, CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT, DEFAULT_UNIT_ID,
    CONF_INVERTER_TYPE, INVERTER_TYPE_HYBRID, INVERTER_TYPE_BI,
    CONF_KSEM_HOST, KSEM_PORT, KSEM_SLAVE_ID,
    REG_SENSOR_TYPE, REG_BATTERY_MGMT_MODE,
    BATTERY_MGMT_MODE_MODBUS, BATTERY_MGMT_MODE_MAP,
    SENSOR_TYPE_KSEM, SENSOR_TYPE_NONE,
    CONF_SOURCE_GRID_POWER_ENTITY,
    CONF_GRID_TARGET_W, DEFAULT_GRID_TARGET_W,
    CONF_GRID_DEADBAND_W, DEFAULT_GRID_DEADBAND_W,
    CONF_EXTERNAL_CONTROL_MAX_DISCHARGE_W,
    CONF_EXTERNAL_CONTROL_MAX_CHARGE_W,
    CONF_EXTERNAL_CONTROL_HYSTERESIS_W, DEFAULT_EXTERNAL_CONTROL_HYSTERESIS_W,
    CONF_EXTERNAL_CONTROL_EMA_ALPHA, DEFAULT_EXTERNAL_CONTROL_EMA_ALPHA, MIN_EXTERNAL_CONTROL_EMA_ALPHA,
)
from .modbus_handler import KostalModbusHandler

_LOGGER = logging.getLogger(__name__)


def _has_smart_meter(sensor_type: int | None) -> bool:
    """A failed read counts as no meter, so the user is still offered a grid entity."""
    return sensor_type is not None and sensor_type != SENSOR_TYPE_NONE


def _grid_entity_selector() -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain=["sensor", "number", "input_number"]))


def _number_selector(min_value: float, max_value: float, step: float, unit: str | None = None) -> NumberSelector:
    config = NumberSelectorConfig(min=min_value, max=max_value, step=step, mode=NumberSelectorMode.BOX)
    if unit is not None:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _grid_entity_field(current: str | None) -> vol.Optional:
    # suggested_value instead of default, so the field can be cleared again
    return vol.Optional(CONF_SOURCE_GRID_POWER_ENTITY, description={"suggested_value": current})


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kostal Modbus Control."""

    VERSION = 1
    
    # Compatibility with different HA versions
    _attr_domain = DOMAIN

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> KostalOptionsFlowHandler:
        """Return the options flow handler."""
        return KostalOptionsFlowHandler()

    def __init__(self) -> None:
        self._inverter_data: dict[str, Any] = {}
        self._sensor_type: int | None = None
        self._battery_mgmt_mode: int | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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
                            {"value": INVERTER_TYPE_HYBRID, "label": "Plenticore Hybrid (reg. 1034)"},
                            {"value": INVERTER_TYPE_BI, "label": "Plenticore BI / Battery Inverter (reg. 1026)"},
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

    async def _async_continue(self) -> ConfigFlowResult:
        """Continue to the KSEM or grid source step, otherwise finish."""
        # KSEM detected (0x03) — offer to read it directly
        if self._sensor_type == SENSOR_TYPE_KSEM:
            return await self.async_step_ksem()
        # No smart meter — offer grid control from a Home Assistant entity
        if not _has_smart_meter(self._sensor_type):
            return await self.async_step_grid_source()
        return self.async_create_entry(
            title=f"Kostal {self._inverter_data[CONF_HOST]}",
            data=self._inverter_data,
        )

    async def async_step_grid_source(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Optional step to pick a grid-power entity when the inverter has no smart meter."""
        if user_input is not None:
            grid_entity = user_input.get(CONF_SOURCE_GRID_POWER_ENTITY)
            # Empty = skip; the plain charge/discharge switches still work
            options = {CONF_SOURCE_GRID_POWER_ENTITY: grid_entity} if grid_entity else None
            return self.async_create_entry(
                title=f"Kostal {self._inverter_data[CONF_HOST]}",
                data=self._inverter_data,
                options=options,
            )

        return self.async_show_form(
            step_id="grid_source",
            data_schema=vol.Schema({_grid_entity_field(None): _grid_entity_selector()}),
        )

    async def async_step_battery_management(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Warn that battery management is not set to Modbus, but let setup continue."""
        if user_input is not None:
            return await self._async_continue()

        mode = self._battery_mgmt_mode
        if mode is None:
            current_mode = "Unknown"
        else:
            current_mode = BATTERY_MGMT_MODE_MAP.get(mode, f"Unknown (0x{mode:02X})")
        return self.async_show_form(
            step_id="battery_management",
            data_schema=vol.Schema({}),
            description_placeholders={"current_mode": current_mode},
        )

    async def async_step_ksem(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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
    """Options for grid control from an external grid-power entity.

    Always offered — also with a smart meter, so the feature can be tested on
    such an installation — but the form warns when a meter is detected.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        max_power = self._max_battery_power_w()
        if user_input is not None:
            if not user_input.get(CONF_SOURCE_GRID_POWER_ENTITY):
                user_input.pop(CONF_SOURCE_GRID_POWER_ENTITY, None)
            for key in (CONF_EXTERNAL_CONTROL_MAX_DISCHARGE_W, CONF_EXTERNAL_CONTROL_MAX_CHARGE_W):
                value = user_input.get(key)
                # Empty, or the battery maximum or above: store nothing, so the
                # limit follows the maximum battery control power
                if value is None or (max_power is not None and value >= max_power):
                    user_input.pop(key, None)
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options
        schema = vol.Schema(
            {
                _grid_entity_field(current.get(CONF_SOURCE_GRID_POWER_ENTITY)): _grid_entity_selector(),
                vol.Optional(
                    CONF_GRID_TARGET_W,
                    default=current.get(CONF_GRID_TARGET_W, DEFAULT_GRID_TARGET_W),
                ): _number_selector(-20000.0, 20000.0, 50.0, "W"),
                vol.Optional(
                    CONF_GRID_DEADBAND_W,
                    default=current.get(CONF_GRID_DEADBAND_W, DEFAULT_GRID_DEADBAND_W),
                ): _number_selector(0.0, 5000.0, 10.0, "W"),
                # suggested_value instead of default, so the field can be cleared
                # to follow the battery maximum again
                vol.Optional(
                    CONF_EXTERNAL_CONTROL_MAX_DISCHARGE_W,
                    description={"suggested_value": current.get(CONF_EXTERNAL_CONTROL_MAX_DISCHARGE_W, max_power)},
                ): _number_selector(0.0, 50000.0, 100.0, "W"),
                vol.Optional(
                    CONF_EXTERNAL_CONTROL_MAX_CHARGE_W,
                    description={"suggested_value": current.get(CONF_EXTERNAL_CONTROL_MAX_CHARGE_W, max_power)},
                ): _number_selector(0.0, 50000.0, 100.0, "W"),
                vol.Optional(
                    CONF_EXTERNAL_CONTROL_HYSTERESIS_W,
                    default=current.get(CONF_EXTERNAL_CONTROL_HYSTERESIS_W, DEFAULT_EXTERNAL_CONTROL_HYSTERESIS_W),
                ): _number_selector(0.0, 5000.0, 10.0, "W"),
                vol.Optional(
                    CONF_EXTERNAL_CONTROL_EMA_ALPHA,
                    default=current.get(CONF_EXTERNAL_CONTROL_EMA_ALPHA, DEFAULT_EXTERNAL_CONTROL_EMA_ALPHA),
                ): _number_selector(MIN_EXTERNAL_CONTROL_EMA_ALPHA, 1.0, 0.05),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={"meter_note": self._meter_note()},
        )

    def _max_battery_power_w(self) -> float | None:
        """Maximum battery control power rounded up to 100 W, when the integration knows it."""
        data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        return data.max_battery_power_step_w() if data is not None else None

    def _meter_note(self) -> str:
        data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        coordinator = getattr(data, "coordinator", None)
        sensor_type = coordinator.data.get(REG_SENSOR_TYPE) if coordinator and coordinator.data else None
        if not _has_smart_meter(sensor_type):
            return ""
        return (
            "\n\n**Note:** a smart meter is connected to this inverter. Grid control from an "
            "external entity is meant for inverters without one — use it here for testing only."
        )
