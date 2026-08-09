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
    CONF_UNIT_ID,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    DOMAIN,
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
    INVERTER_TYPE_BI,
    REG_BATTERY_WORK_CAPACITY,
    REG_BATTERY_MGMT_MODE,
    REG_BATTERY_TYPE,
    REG_BATTERY_CURRENT,
    REG_BATTERY_CYCLES,
    REG_BATTERY_GROSS_CAPACITY,
    KEY_BATTERY_GROSS_CAPACITY,
    REG_BATTERY_MODEL_ID,
    REG_BATTERY_BMS_SERIAL,
    REG_BATTERY_FIRMWARE,
    REG_FIRMWARE_MC,
    BATTERY_TYPE_MAP,
    REG_BATTERY_MIN_SOC,
    REG_BATTERY_MAX_SOC,
    DEFAULT_MIN_SOC_LIMIT,
    DEFAULT_MAX_SOC_LIMIT,
    REG_CURRENT_PHASE1,
    REG_CURRENT_PHASE2,
    REG_CURRENT_PHASE3,
    REG_SENSOR_TYPE,
    CONF_KSEM_HOST,
    KSEM_PORT,
    KSEM_SLAVE_ID,
    REG_KSEM_ENERGY_IMPORTED,
    REG_KSEM_ENERGY_EXPORTED,
    REG_KSEM_GRID_POWER_TOTAL,
    REG_KSEM_SUM_OUTPUT_INVERTER_AC,
    REG_KSEM_SUM_PV_POWER_INVERTER_DC,
    REG_KSEM_HOME_CONSUMPTION,
    REG_KSEM_BATTERY_CHARGE_DISCHARGE_DC,
    REG_KSEM_SYSTEM_SOC,
    REG_KSEM_HOME_CONSUMPTION_FROM_PV,
    REG_KSEM_HOME_CONSUMPTION_FROM_BATTERY,
    REG_KSEM_HOME_CONSUMPTION_FROM_GRID,
)
from .modbus_handler import KostalModbusHandler

_LOGGER = logging.getLogger(__name__)


class KostalCoordinator(DataUpdateCoordinator[dict[Any, Any]]):
    """Coordinator that batches all sensor reads into a single update cycle.

    Values are keyed by register address, except where two devices share an
    address — see KEY_BATTERY_GROSS_CAPACITY.
    """

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
            # The battery info block is big-endian regardless of the inverter's
            # byte-order setting, unlike the state register above
            data[KEY_BATTERY_GROSS_CAPACITY] = await self._handler.read_uint32_big_endian(REG_BATTERY_GROSS_CAPACITY)
            data[REG_FIRMWARE_MC] = await self._handler.read_uint32_big_endian(REG_FIRMWARE_MC)
            data[REG_BATTERY_MODEL_ID] = await self._handler.read_uint32_big_endian(REG_BATTERY_MODEL_ID)
            data[REG_BATTERY_BMS_SERIAL] = await self._handler.read_uint32_big_endian(REG_BATTERY_BMS_SERIAL)
            data[REG_BATTERY_FIRMWARE] = await self._handler.read_uint32_big_endian(REG_BATTERY_FIRMWARE)
            # U16 register
            data[REG_BATTERY_TYPE] = await self._handler.read_uint16(REG_BATTERY_TYPE)
            # KSEM energy registers (separate handler, optional)
            ksem = self._kostal_data.ksem_handler
            if ksem is not None:
                for reg, label in (
                    (REG_KSEM_ENERGY_IMPORTED, "KSEM energy imported"),
                    (REG_KSEM_ENERGY_EXPORTED, "KSEM energy exported"),
                    (REG_KSEM_GRID_POWER_TOTAL, "KSEM grid power total"),
                    (REG_KSEM_SUM_OUTPUT_INVERTER_AC, "KSEM sum output inverter AC"),
                    (REG_KSEM_SUM_PV_POWER_INVERTER_DC, "KSEM sum PV power inverter DC"),
                    (REG_KSEM_HOME_CONSUMPTION, "KSEM home consumption"),
                    (REG_KSEM_BATTERY_CHARGE_DISCHARGE_DC, "KSEM battery charge/discharge DC"),
                ):
                    try:
                        if reg in (REG_KSEM_ENERGY_IMPORTED, REG_KSEM_ENERGY_EXPORTED):
                            data[reg] = await ksem.read_int64(reg)
                        else:
                            data[reg] = await ksem.read_int32(reg)
                    except Exception as err:
                        _LOGGER.debug("Failed to read %s: %s", label, err)
                        data[reg] = None
                try:
                    data[REG_KSEM_SYSTEM_SOC] = await ksem.read_uint16(REG_KSEM_SYSTEM_SOC)
                except Exception as err:
                    _LOGGER.debug("Failed to read KSEM system SoC: %s", err)
                    data[REG_KSEM_SYSTEM_SOC] = None
                for reg, label in (
                    (REG_KSEM_HOME_CONSUMPTION_FROM_PV, "KSEM home consumption from PV"),
                    (REG_KSEM_HOME_CONSUMPTION_FROM_BATTERY, "KSEM home consumption from battery"),
                    (REG_KSEM_HOME_CONSUMPTION_FROM_GRID, "KSEM home consumption from grid"),
                ):
                    try:
                        data[reg] = await ksem.read_uint32(reg)
                    except Exception as err:
                        _LOGGER.debug("Failed to read %s: %s", label, err)
                        data[reg] = None
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
    # User setpoints from the SOC limit numbers. The defaults equal the
    # inverter's own limits, i.e. "not in use". The number entities own the
    # register writes — see KostalSocLimitNumber in number.py.
    min_soc: float = DEFAULT_MIN_SOC_LIMIT
    max_soc: float = DEFAULT_MAX_SOC_LIMIT
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
        # KSEM always uses big-endian word order (ABCD) — no word swap
        ksem_handler._word_swapped_32bit = False
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

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data: KostalData = hass.data[DOMAIN].pop(entry.entry_id)
        await data.handler.close()
        if data.ksem_handler is not None:
            await data.ksem_handler.close()

    return unload_ok
