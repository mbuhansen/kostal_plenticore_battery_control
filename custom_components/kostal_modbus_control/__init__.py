from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ACTIVE_HYSTERESIS_W,
    CONF_ACTIVE_MAX_POWER_W,
    CONF_IDLE_HYSTERESIS_W,
    CONF_IDLE_MAX_POWER_W,
    CONF_INV1_MAX_POWER_W,
    CONF_INV1_SOC_BUFFER,
    CONF_INV2_MIN_SOC,
    CONF_UNIT_ID,
    DEFAULT_PORT,
    DEFAULT_ACTIVE_HYSTERESIS_W,
    DEFAULT_ACTIVE_MAX_POWER_W,
    DEFAULT_IDLE_HYSTERESIS_W,
    DEFAULT_IDLE_MAX_POWER_W,
    DEFAULT_INV1_MAX_POWER_W,
    DEFAULT_INV1_SOC_BUFFER,
    DEFAULT_INV2_MIN_SOC,
    DEFAULT_UNIT_ID,
    DOMAIN,
    CONF_MASTER_BLOCK_CHARGE_ENTITY,
    CONF_MASTER_BLOCK_DISCHARGE_ENTITY,
    CONF_MASTER_CHARGE_START_ENTITY,
    CONF_MASTER_DISCHARGE_START_ENTITY,
    CONF_MODBUS_TIMEOUT,
    DEFAULT_MODBUS_TIMEOUT,
    LOOP_INTERVAL,
    REG_MODBUS_BYTE_ORDER,
    REG_INVERTER_STATE,
    REG_MODEL,
    REG_POWER_CLASS,
    REG_TOTAL_ACTIVE_POWER,
    REG_VOLTAGE_PHASE1,
    REG_VOLTAGE_PHASE2,
    REG_VOLTAGE_PHASE3,
    REG_BATTERY_SOC,
    REG_BATTERY_POWER,
    REG_BATTERY_VOLTAGE,
    REG_BATTERY_TEMP,
    REG_BATTERY_MAX_CHARGE_LIMIT,
    REG_BATTERY_MAX_DISCHARGE_LIMIT,
    REG_CHARGE_DISCHARGE_LIMIT,
    REG_CHARGE_DISCHARGE_LIMIT_BI,
    REG_CHARGE_RATE,
    REG_DISCHARGE_RATE,
    CONF_INVERTER_TYPE,
    CONF_OPERATING_MODE,
    CONF_SOURCE_GRID_POWER_ENTITY,
    CONF_SOURCE_INV1_POWER_ENTITY,
    CONF_SOURCE_SOC1_ENTITY,
    INVERTER_TYPE_BI,
    OPERATING_MODE_NORMAL,
    REG_BATTERY_WORK_CAPACITY,
    REG_BATTERY_MGMT_MODE,
    REG_BATTERY_TYPE,
    REG_BATTERY_CURRENT,
    REG_BATTERY_CYCLES,
    REG_BATTERY_GROSS_CAPACITY,
    REG_BATTERY_MODEL_ID,
    REG_BATTERY_BMS_SERIAL,
    REG_BATTERY_FIRMWARE,
    BATTERY_TYPE_MAP,
    REG_BATTERY_MIN_SOC,
    REG_BATTERY_MAX_SOC,
    CONF_MIN_SOC,
    CONF_MAX_SOC,
    REG_CURRENT_PHASE1,
    REG_CURRENT_PHASE2,
    REG_CURRENT_PHASE3,
    REG_SENSOR_TYPE,
    CONF_KSEM_HOST,
    KSEM_PORT,
    KSEM_SLAVE_ID,
    REG_KSEM_ENERGY_IMPORTED,
    REG_KSEM_ENERGY_EXPORTED,
)
from .modbus_handler import KostalModbusHandler

_LOGGER = logging.getLogger(__name__)


class KostalCoordinator(DataUpdateCoordinator):
    """Coordinator that batches all sensor reads into a single update cycle."""

    def __init__(self, hass: HomeAssistant, handler: KostalModbusHandler, kostal_data: "KostalData") -> None:
        super().__init__(
            hass,
            logging.getLogger(f"{__name__}.coordinator"),
            name=DOMAIN,
            update_interval=timedelta(seconds=LOOP_INTERVAL),
        )
        self._handler = handler
        self._kostal_data = kostal_data

    async def _async_update_data(self) -> dict:
        try:
            data: dict = {}
            # Float registers (2 registers each)
            for address in (
                REG_TOTAL_ACTIVE_POWER,
                REG_VOLTAGE_PHASE1,
                REG_VOLTAGE_PHASE2,
                REG_VOLTAGE_PHASE3,
                REG_BATTERY_SOC,
                REG_BATTERY_VOLTAGE,
                REG_BATTERY_TEMP,
                REG_BATTERY_MAX_CHARGE_LIMIT,
                REG_BATTERY_MAX_DISCHARGE_LIMIT,
                REG_CHARGE_DISCHARGE_LIMIT,
                REG_CHARGE_DISCHARGE_LIMIT_BI,
                REG_CHARGE_RATE,
                REG_DISCHARGE_RATE,
                REG_BATTERY_WORK_CAPACITY,
                REG_BATTERY_CURRENT,
                REG_BATTERY_CYCLES,
                REG_BATTERY_MIN_SOC,
                REG_BATTERY_MAX_SOC,
                REG_CURRENT_PHASE1,
                REG_CURRENT_PHASE2,
                REG_CURRENT_PHASE3,
            ):
                data[address] = await self._handler.read_float(address)
            # S16 register (1 register, signed int)
            data[REG_BATTERY_POWER] = await self._handler.read_int16(REG_BATTERY_POWER)
            # U8 registers
            data[REG_SENSOR_TYPE] = await self._handler.read_uint8(REG_SENSOR_TYPE)
            data[REG_BATTERY_MGMT_MODE] = await self._handler.read_uint8(REG_BATTERY_MGMT_MODE)
            # U32 registers
            data[REG_INVERTER_STATE] = await self._handler.read_uint32(REG_INVERTER_STATE)
            data[REG_BATTERY_GROSS_CAPACITY] = await self._handler.read_uint32(REG_BATTERY_GROSS_CAPACITY)
            data[REG_BATTERY_MODEL_ID] = await self._handler.read_uint32(REG_BATTERY_MODEL_ID)
            data[REG_BATTERY_BMS_SERIAL] = await self._handler.read_uint32(REG_BATTERY_BMS_SERIAL)
            data[REG_BATTERY_FIRMWARE] = await self._handler.read_uint32(REG_BATTERY_FIRMWARE)
            # U16 register
            data[REG_BATTERY_TYPE] = await self._handler.read_uint16(REG_BATTERY_TYPE)
            # KSEM energy registers (separate handler, optional)
            ksem = self._kostal_data.ksem_handler
            if ksem is not None:
                for reg, label in (
                    (REG_KSEM_ENERGY_IMPORTED, "KSEM energy imported"),
                    (REG_KSEM_ENERGY_EXPORTED, "KSEM energy exported"),
                ):
                    try:
                        data[reg] = await ksem.read_int64(reg)
                    except Exception as err:
                        _LOGGER.debug("Failed to read %s: %s", label, err)
                        data[reg] = None
            # Write SOC limits periodically if configured
            if self._kostal_data.min_soc is not None:
                await self._handler.write_float(REG_BATTERY_MIN_SOC, self._kostal_data.min_soc)
            if self._kostal_data.max_soc is not None:
                await self._handler.write_float(REG_BATTERY_MAX_SOC, self._kostal_data.max_soc)
            recovered = self._kostal_data.mark_communication_restored()
            if recovered:
                _LOGGER.info("Communication with Kostal inverter restored")
                self._kostal_data.notify_connection_restored()
            return data
        except Exception as err:
            self._kostal_data.mark_communication_lost(str(err))
            raise UpdateFailed(f"Error communicating with Kostal inverter: {err}") from err


PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.NUMBER, Platform.SENSOR]

@dataclass
class KostalData:
    handler: KostalModbusHandler
    coordinator: KostalCoordinator | None = None
    charge_rate: float = 100.0
    discharge_rate: float = 100.0
    fuse_size: float = 25.0
    last_stop_time: float = 0.0
    inverter_timeout: int = DEFAULT_MODBUS_TIMEOUT
    ems_status: str = "Inactive"
    ems_charge_limit_pct: float = 100.0
    predbat_status: str = "Inactive"
    inverter_model: str = ""
    inverter_power_class: str = ""
    charge_discharge_reg: int = REG_CHARGE_DISCHARGE_LIMIT
    min_soc: float | None = None
    max_soc: float | None = None
    auto_resume_on_recovery: bool = True
    communication_ok: bool = True
    last_error: str | None = None
    control_fault_latched: bool = False
    ksem_handler: KostalModbusHandler | None = None
    runtime_switches: dict[str, Any] = field(default_factory=dict)
    resume_pending_switches: set[str] = field(default_factory=set)

    def register_runtime_switch(self, switch: Any) -> None:
        self.runtime_switches[switch._key] = switch

    def mark_communication_lost(self, error: str | None) -> None:
        self.communication_ok = False
        self.last_error = error

    def mark_communication_restored(self) -> bool:
        was_disconnected = not self.communication_ok
        self.communication_ok = True
        self.last_error = None
        return was_disconnected

    def set_resume_pending(self, switch_key: str, pending: bool) -> None:
        if pending:
            self.resume_pending_switches.add(switch_key)
            self.control_fault_latched = True
            return

        self.resume_pending_switches.discard(switch_key)
        self.control_fault_latched = bool(self.resume_pending_switches)

    def notify_connection_restored(self) -> None:
        for switch in self.runtime_switches.values():
            handler = getattr(switch, "handle_connection_restored", None)
            if handler is not None:
                handler()
    operating_mode: str = OPERATING_MODE_NORMAL
    master_charge_start_entity: str | None = None
    master_discharge_start_entity: str | None = None
    master_block_charge_entity: str | None = None
    master_block_discharge_entity: str | None = None
    source_soc1_entity: str | None = None
    source_inv1_power_entity: str | None = None
    source_grid_power_entity: str | None = None
    inv2_min_soc: float = DEFAULT_INV2_MIN_SOC
    inv1_soc_buffer: float = DEFAULT_INV1_SOC_BUFFER
    active_max_power_w: float = DEFAULT_ACTIVE_MAX_POWER_W
    active_hysteresis_w: float = DEFAULT_ACTIVE_HYSTERESIS_W
    idle_max_power_w: float = DEFAULT_IDLE_MAX_POWER_W
    idle_hysteresis_w: float = DEFAULT_IDLE_HYSTERESIS_W
    inv1_max_power_w: float = DEFAULT_INV1_MAX_POWER_W
    last_inverter_control_setpoint_w: float | None = None
    last_inverter_control_mode: str | None = None
    inverter_control_status: str = "Inactive"
    inverter_control_target_w: float | None = None
    inverter_control_target_pct: float | None = None
    inverter_control_house_load_w: float | None = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Kostal Modbus Control from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    port = DEFAULT_PORT  # Always 1502 for Plenticore
    unit_id = DEFAULT_UNIT_ID  # Always 71 for Plenticore battery management
    timeout = entry.data.get(CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT)

    _LOGGER.info("Setting up Kostal Modbus: host=%s port=%s unit_id=%s", host, port, unit_id)

    handler = KostalModbusHandler(host, port, unit_id)
    try:
        await handler.connect()
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot connect to Kostal inverter at {host}:{port}") from err

    modbus_byte_order = await handler.read_uint16(REG_MODBUS_BYTE_ORDER)
    handler.set_modbus_byte_order(modbus_byte_order)

    # Read static string registers from inverter
    inverter_model = await handler.read_string(REG_MODEL, 16) or ""
    inverter_power_class = await handler.read_string(REG_POWER_CLASS, 16) or ""
    _LOGGER.info("Inverter model=%r power_class=%r", inverter_model, inverter_power_class)

    battery_type_raw = await handler.read_uint16(REG_BATTERY_TYPE)
    battery_type_name = BATTERY_TYPE_MAP.get(battery_type_raw, f"Unknown (0x{battery_type_raw:04X})") if battery_type_raw is not None else None

    # Register device with static info (string registers are not reliable via Modbus on all firmware)
    device_registry = dr.async_get(hass)
    if inverter_model and inverter_power_class:
        device_name = f"{inverter_model} {inverter_power_class}"
    elif inverter_model:
        device_name = inverter_model
    else:
        device_name = f"Kostal Inverter {host}"
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="Kostal",
        model=device_name,
        name=device_name,
        hw_version=battery_type_name,
    )
    
    inverter_type = entry.data.get(CONF_INVERTER_TYPE, "hybrid")
    charge_discharge_reg = REG_CHARGE_DISCHARGE_LIMIT_BI if inverter_type == INVERTER_TYPE_BI else REG_CHARGE_DISCHARGE_LIMIT
    _LOGGER.info("Inverter type=%r → charge/discharge register=%d", inverter_type, charge_discharge_reg)

    # Set up KSEM handler if configured
    ksem_handler: KostalModbusHandler | None = None
    ksem_host = entry.data.get(CONF_KSEM_HOST, "").strip()
    if ksem_host:
        ksem_handler = KostalModbusHandler(ksem_host, KSEM_PORT, KSEM_SLAVE_ID)
        try:
            await ksem_handler.connect()
            _LOGGER.info("Connected to KSEM at %s:%s", ksem_host, KSEM_PORT)
        except Exception as err:
            _LOGGER.warning("Cannot connect to KSEM at %s — energy sensors will be unavailable: %s", ksem_host, err)
            ksem_handler = None

    data = KostalData(
        handler=handler,
        inverter_timeout=timeout,
        inverter_model=inverter_model,
        inverter_power_class=inverter_power_class,
        charge_discharge_reg=charge_discharge_reg,
        ksem_handler=ksem_handler,
        operating_mode=entry.data.get(CONF_OPERATING_MODE, OPERATING_MODE_NORMAL),
    )

    coordinator = KostalCoordinator(hass, handler, data)
    # Use hass.async_create_background_task for broad HA version compatibility
    hass.async_create_background_task(
        coordinator.async_refresh(),
        "kostal_modbus_initial_refresh",
    )
    data.coordinator = coordinator

    hass.data[DOMAIN][entry.entry_id] = data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Apply SOC limits from options (if set)
    await _apply_soc_options(handler, entry.options, data)
    _apply_inverter_control_options(entry.options, data)

    # Re-apply SOC limits when options are updated
    entry.async_on_unload(
        entry.add_update_listener(_async_options_update_listener)
    )

    return True


async def _apply_soc_options(handler, options: dict, data: "KostalData | None" = None) -> None:
    """Write min/max SOC to inverter if configured in options, and update KostalData."""
    for conf_key, reg, attr in (
        (CONF_MIN_SOC, REG_BATTERY_MIN_SOC, "min_soc"),
        (CONF_MAX_SOC, REG_BATTERY_MAX_SOC, "max_soc"),
    ):
        raw = options.get(conf_key, "")
        if raw:
            try:
                val = max(0.0, min(100.0, float(raw)))
                if data is not None:
                    setattr(data, attr, val)
                await handler.write_float(reg, val)
                _LOGGER.info("Wrote SOC limit %s=%.1f to register %d", conf_key, val, reg)
            except Exception as err:
                _LOGGER.warning("Failed to write SOC limit %s: %s", conf_key, err)
        else:
            if data is not None:
                setattr(data, attr, None)


async def _async_options_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    data: KostalData = hass.data[DOMAIN][entry.entry_id]
    await _apply_soc_options(data.handler, entry.options, data)
    _apply_inverter_control_options(entry.options, data)


def _apply_inverter_control_options(options: dict, data: KostalData) -> None:
    """Apply HA inverter control settings from options to runtime data."""
    data.master_charge_start_entity = options.get(CONF_MASTER_CHARGE_START_ENTITY) or None
    data.master_discharge_start_entity = options.get(CONF_MASTER_DISCHARGE_START_ENTITY) or None
    data.master_block_charge_entity = options.get(CONF_MASTER_BLOCK_CHARGE_ENTITY) or None
    data.master_block_discharge_entity = options.get(CONF_MASTER_BLOCK_DISCHARGE_ENTITY) or None
    data.source_soc1_entity = options.get(CONF_SOURCE_SOC1_ENTITY) or None
    data.source_inv1_power_entity = options.get(CONF_SOURCE_INV1_POWER_ENTITY) or None
    data.source_grid_power_entity = options.get(CONF_SOURCE_GRID_POWER_ENTITY) or None

    data.inv2_min_soc = float(options.get(CONF_INV2_MIN_SOC, DEFAULT_INV2_MIN_SOC))
    data.inv1_soc_buffer = float(options.get(CONF_INV1_SOC_BUFFER, DEFAULT_INV1_SOC_BUFFER))
    data.active_max_power_w = float(options.get(CONF_ACTIVE_MAX_POWER_W, DEFAULT_ACTIVE_MAX_POWER_W))
    data.active_hysteresis_w = float(options.get(CONF_ACTIVE_HYSTERESIS_W, DEFAULT_ACTIVE_HYSTERESIS_W))
    data.idle_max_power_w = float(options.get(CONF_IDLE_MAX_POWER_W, DEFAULT_IDLE_MAX_POWER_W))
    data.idle_hysteresis_w = float(options.get(CONF_IDLE_HYSTERESIS_W, DEFAULT_IDLE_HYSTERESIS_W))
    data.inv1_max_power_w = float(options.get(CONF_INV1_MAX_POWER_W, DEFAULT_INV1_MAX_POWER_W))

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data: KostalData = hass.data[DOMAIN].pop(entry.entry_id)
        await data.handler.close()
        if data.ksem_handler is not None:
            await data.ksem_handler.close()

    return unload_ok
