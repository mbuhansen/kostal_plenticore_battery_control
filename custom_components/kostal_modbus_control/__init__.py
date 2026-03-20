from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

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
    REG_MODEL,
    REG_POWER_CLASS,
    REG_TOTAL_HOME_CONSUMPTION,
    REG_BATTERY_SOC,
    REG_BATTERY_POWER,
    REG_BATTERY_VOLTAGE,
    REG_BATTERY_TEMP,
    REG_BATTERY_MAX_CHARGE_LIMIT,
    REG_BATTERY_MAX_DISCHARGE_LIMIT,
    REG_CHARGE_DISCHARGE_LIMIT,
    REG_CHARGE_DISCHARGE_LIMIT_BI,
    CONF_INVERTER_TYPE,
    INVERTER_TYPE_BI,
    REG_BATTERY_WORK_CAPACITY,
    REG_BATTERY_SERIAL,
    REG_BATTERY_MGMT_MODE,
    REG_BATTERY_TYPE,
    REG_BATTERY_CHARGE_CURRENT,
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
                REG_TOTAL_HOME_CONSUMPTION,
                REG_BATTERY_SOC,
                REG_BATTERY_VOLTAGE,
                REG_BATTERY_TEMP,
                REG_BATTERY_MAX_CHARGE_LIMIT,
                REG_BATTERY_MAX_DISCHARGE_LIMIT,
                REG_BATTERY_WORK_CAPACITY,
                REG_BATTERY_CHARGE_CURRENT,
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
            data[REG_BATTERY_SERIAL] = await self._handler.read_uint32(REG_BATTERY_SERIAL)
            data[REG_BATTERY_GROSS_CAPACITY] = await self._handler.read_uint32(REG_BATTERY_GROSS_CAPACITY)
            data[REG_BATTERY_MODEL_ID] = await self._handler.read_uint32(REG_BATTERY_MODEL_ID)
            data[REG_BATTERY_BMS_SERIAL] = await self._handler.read_uint32(REG_BATTERY_BMS_SERIAL)
            data[REG_BATTERY_FIRMWARE] = await self._handler.read_uint32(REG_BATTERY_FIRMWARE)
            # U16 register
            data[REG_BATTERY_TYPE] = await self._handler.read_uint16(REG_BATTERY_TYPE)
            # Write SOC limits periodically if configured
            if self._kostal_data.min_soc is not None:
                await self._handler.write_float(REG_BATTERY_MIN_SOC, self._kostal_data.min_soc)
            if self._kostal_data.max_soc is not None:
                await self._handler.write_float(REG_BATTERY_MAX_SOC, self._kostal_data.max_soc)
            return data
        except Exception as err:
            raise UpdateFailed(f"Error communicating with Kostal inverter: {err}") from err


PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.NUMBER, Platform.SENSOR]

@dataclass
class KostalData:
    handler: KostalModbusHandler
    coordinator: KostalCoordinator | None = None
    charge_rate: float = 5000.0
    discharge_rate: float = 5000.0
    fuse_size: float = 25.0
    last_stop_time: float = 0.0
    inverter_timeout: int = DEFAULT_MODBUS_TIMEOUT
    ems_status: str = "Inactive"
    ems_charge_limit_pct: float = 100.0
    inverter_model: str = ""
    inverter_power_class: str = ""
    charge_discharge_reg: int = REG_CHARGE_DISCHARGE_LIMIT
    min_soc: float | None = None
    max_soc: float | None = None


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

    data = KostalData(
        handler=handler,
        inverter_timeout=timeout,
        inverter_model=inverter_model,
        inverter_power_class=inverter_power_class,
        charge_discharge_reg=charge_discharge_reg,
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
                val = float(raw)
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

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data: KostalData = hass.data[DOMAIN].pop(entry.entry_id)
        await data.handler.close()

    return unload_ok
