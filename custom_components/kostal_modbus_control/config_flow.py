"""Config flow for Kostal Modbus Control integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResult

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
    CONF_ACTIVE_HYSTERESIS_W,
    CONF_ACTIVE_MAX_POWER_W,
    CONF_EXTERNAL_CONTROL_EMA_ALPHA,
    CONF_EXTERNAL_CONTROL_HYSTERESIS_W,
    CONF_EXTERNAL_CONTROL_MAX_CHARGE_W,
    CONF_EXTERNAL_CONTROL_MAX_DISCHARGE_W,
    CONF_GRID_DEADBAND_W,
    CONF_GRID_TARGET_W,
    CONF_IDLE_HYSTERESIS_W,
    CONF_IDLE_MAX_POWER_W,
    CONF_INV1_MAX_POWER_W,
    CONF_INV1_SOC_BUFFER,
    CONF_INV2_MIN_SOC,
    CONF_INVERTER_TYPE,
    CONF_KSEM_HOST,
    CONF_MASTER_BLOCK_CHARGE_ENTITY,
    CONF_MASTER_BLOCK_DISCHARGE_ENTITY,
    CONF_MASTER_CHARGE_START_ENTITY,
    CONF_MASTER_DISCHARGE_START_ENTITY,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_MODBUS_TIMEOUT,
    CONF_OPERATING_MODE,
    CONF_SOURCE_GRID_POWER_ENTITY,
    CONF_SOURCE_INV1_POWER_ENTITY,
    CONF_SOURCE_INV1_STATUS_ENTITY,
    CONF_SOURCE_SOC1_ENTITY,
    DEFAULT_ACTIVE_HYSTERESIS_W,
    DEFAULT_ACTIVE_MAX_POWER_W,
    DEFAULT_EXTERNAL_CONTROL_EMA_ALPHA,
    DEFAULT_EXTERNAL_CONTROL_HYSTERESIS_W,
    DEFAULT_EXTERNAL_CONTROL_MAX_CHARGE_W,
    DEFAULT_EXTERNAL_CONTROL_MAX_DISCHARGE_W,
    DEFAULT_GRID_DEADBAND_W,
    DEFAULT_GRID_TARGET_W,
    DEFAULT_IDLE_HYSTERESIS_W,
    DEFAULT_IDLE_MAX_POWER_W,
    DEFAULT_INV1_MAX_POWER_W,
    DEFAULT_INV1_SOC_BUFFER,
    DEFAULT_INV2_MIN_SOC,
    DEFAULT_MODBUS_TIMEOUT,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    DOMAIN,
    INVERTER_TYPE_BI,
    INVERTER_TYPE_HYBRID,
    KSEM_PORT,
    KSEM_SLAVE_ID,
    OPERATING_MODE_EXTERNAL_GRID_CONTROL,
    OPERATING_MODE_HA_INVERTER_CONTROL,
    OPERATING_MODE_NORMAL,
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


def _entity_selector(domains: list[str]):
    return EntitySelector(EntitySelectorConfig(domain=domains))


def _number_selector(
    min_value: float,
    max_value: float,
    step: float,
    unit: str | None = None,
):
    config_kwargs: dict[str, Any] = {
        "min": min_value,
        "max": max_value,
        "step": step,
        "mode": NumberSelectorMode.BOX,
    }
    if unit is not None:
        config_kwargs["unit_of_measurement"] = unit
    return NumberSelector(NumberSelectorConfig(**config_kwargs))


def _add_option_field(schema: dict, key: str, selector, default: Any | None = None) -> None:
    if default is None:
        schema[vol.Optional(key)] = selector
    else:
        schema[vol.Optional(key, default=default)] = selector

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
                vol.Required(CONF_OPERATING_MODE, default=OPERATING_MODE_NORMAL): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": OPERATING_MODE_NORMAL, "label": "Normal (with KSEM)"},
                            {"value": OPERATING_MODE_HA_INVERTER_CONTROL, "label": "HA Inverter Grid Control (2 inverter)"},
                            {"value": OPERATING_MODE_EXTERNAL_GRID_CONTROL, "label": "Single Inverter Grid Control"},
                        ],
                        mode=SelectSelectorMode.LIST,
                    )
                ),
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
        operating_mode = self._entry.data.get(CONF_OPERATING_MODE, OPERATING_MODE_NORMAL)

        if user_input is not None:
            if operating_mode == OPERATING_MODE_HA_INVERTER_CONTROL:
                required_keys = (
                    CONF_SOURCE_SOC1_ENTITY,
                    CONF_SOURCE_INV1_POWER_ENTITY,
                    CONF_SOURCE_GRID_POWER_ENTITY,
                )
                missing_keys = [key for key in required_keys if not user_input.get(key)]
                if missing_keys:
                    return self.async_show_form(
                        step_id="init",
                        data_schema=vol.Schema(self._build_schema()),
                        errors={"base": "missing_ha_control_fields"},
                    )
            if operating_mode == OPERATING_MODE_EXTERNAL_GRID_CONTROL:
                if not user_input.get(CONF_SOURCE_GRID_POWER_ENTITY):
                    return self.async_show_form(
                        step_id="init",
                        data_schema=vol.Schema(self._build_schema()),
                        errors={"base": "missing_external_control_fields"},
                    )
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(self._build_schema())
        return self.async_show_form(step_id="init", data_schema=schema)

    def _build_schema(self) -> dict:
        current = self._entry.options
        operating_mode = self._entry.data.get(CONF_OPERATING_MODE, OPERATING_MODE_NORMAL)

        schema: dict = {
            vol.Optional(
                CONF_MIN_SOC,
                default=current.get(CONF_MIN_SOC, ""),
            ): _soc_selector(),
            vol.Optional(
                CONF_MAX_SOC,
                default=current.get(CONF_MAX_SOC, ""),
            ): _soc_selector(),
        }

        if operating_mode == OPERATING_MODE_NORMAL:
            return schema

        sensor_selector = _entity_selector(["sensor", "number", "input_number"])
        status_selector = _entity_selector(["sensor", "binary_sensor", "input_boolean"])

        if operating_mode == OPERATING_MODE_EXTERNAL_GRID_CONTROL:
            _add_option_field(schema, CONF_SOURCE_GRID_POWER_ENTITY, sensor_selector, current.get(CONF_SOURCE_GRID_POWER_ENTITY))
            _add_option_field(schema, CONF_GRID_TARGET_W, _number_selector(-20000.0, 20000.0, 50.0, "W"), current.get(CONF_GRID_TARGET_W, DEFAULT_GRID_TARGET_W))
            _add_option_field(schema, CONF_GRID_DEADBAND_W, _number_selector(0.0, 5000.0, 10.0, "W"), current.get(CONF_GRID_DEADBAND_W, DEFAULT_GRID_DEADBAND_W))
            _add_option_field(schema, CONF_EXTERNAL_CONTROL_MAX_DISCHARGE_W, _number_selector(0.0, 50000.0, 100.0, "W"), current.get(CONF_EXTERNAL_CONTROL_MAX_DISCHARGE_W, DEFAULT_EXTERNAL_CONTROL_MAX_DISCHARGE_W))
            _add_option_field(schema, CONF_EXTERNAL_CONTROL_MAX_CHARGE_W, _number_selector(0.0, 50000.0, 100.0, "W"), current.get(CONF_EXTERNAL_CONTROL_MAX_CHARGE_W, DEFAULT_EXTERNAL_CONTROL_MAX_CHARGE_W))
            _add_option_field(schema, CONF_EXTERNAL_CONTROL_HYSTERESIS_W, _number_selector(0.0, 5000.0, 10.0, "W"), current.get(CONF_EXTERNAL_CONTROL_HYSTERESIS_W, DEFAULT_EXTERNAL_CONTROL_HYSTERESIS_W))
            _add_option_field(schema, CONF_EXTERNAL_CONTROL_EMA_ALPHA, _number_selector(0.0, 1.0, 0.05), current.get(CONF_EXTERNAL_CONTROL_EMA_ALPHA, DEFAULT_EXTERNAL_CONTROL_EMA_ALPHA))
            return schema

        switch_selector = _entity_selector(["switch", "input_boolean"])

        _add_option_field(schema, CONF_MASTER_CHARGE_START_ENTITY, switch_selector, current.get(CONF_MASTER_CHARGE_START_ENTITY))
        _add_option_field(schema, CONF_MASTER_DISCHARGE_START_ENTITY, switch_selector, current.get(CONF_MASTER_DISCHARGE_START_ENTITY))
        _add_option_field(schema, CONF_MASTER_BLOCK_CHARGE_ENTITY, switch_selector, current.get(CONF_MASTER_BLOCK_CHARGE_ENTITY))
        _add_option_field(schema, CONF_MASTER_BLOCK_DISCHARGE_ENTITY, switch_selector, current.get(CONF_MASTER_BLOCK_DISCHARGE_ENTITY))
        _add_option_field(schema, CONF_SOURCE_SOC1_ENTITY, sensor_selector, current.get(CONF_SOURCE_SOC1_ENTITY))
        _add_option_field(schema, CONF_SOURCE_INV1_POWER_ENTITY, sensor_selector, current.get(CONF_SOURCE_INV1_POWER_ENTITY))
        _add_option_field(schema, CONF_SOURCE_INV1_STATUS_ENTITY, status_selector, current.get(CONF_SOURCE_INV1_STATUS_ENTITY))
        _add_option_field(schema, CONF_SOURCE_GRID_POWER_ENTITY, sensor_selector, current.get(CONF_SOURCE_GRID_POWER_ENTITY))
        _add_option_field(schema, CONF_INV2_MIN_SOC, _number_selector(0.0, 100.0, 1.0, "%"), current.get(CONF_INV2_MIN_SOC, DEFAULT_INV2_MIN_SOC))
        _add_option_field(schema, CONF_INV1_SOC_BUFFER, _number_selector(0.0, 100.0, 1.0, "%"), current.get(CONF_INV1_SOC_BUFFER, DEFAULT_INV1_SOC_BUFFER))
        _add_option_field(schema, CONF_INV1_MAX_POWER_W, _number_selector(0.0, 100000.0, 100.0, "W"), current.get(CONF_INV1_MAX_POWER_W, DEFAULT_INV1_MAX_POWER_W))
        _add_option_field(schema, CONF_ACTIVE_MAX_POWER_W, _number_selector(0.0, 50000.0, 100.0, "W"), current.get(CONF_ACTIVE_MAX_POWER_W, DEFAULT_ACTIVE_MAX_POWER_W))
        _add_option_field(schema, CONF_ACTIVE_HYSTERESIS_W, _number_selector(0.0, 5000.0, 10.0, "W"), current.get(CONF_ACTIVE_HYSTERESIS_W, DEFAULT_ACTIVE_HYSTERESIS_W))
        _add_option_field(schema, CONF_IDLE_MAX_POWER_W, _number_selector(0.0, 50000.0, 100.0, "W"), current.get(CONF_IDLE_MAX_POWER_W, DEFAULT_IDLE_MAX_POWER_W))
        _add_option_field(schema, CONF_IDLE_HYSTERESIS_W, _number_selector(0.0, 5000.0, 10.0, "W"), current.get(CONF_IDLE_HYSTERESIS_W, DEFAULT_IDLE_HYSTERESIS_W))

        return schema
