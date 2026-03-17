from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_UNIT_ID, 
    DEFAULT_PORT, 
    DEFAULT_UNIT_ID, 
    DOMAIN, 
    CONF_MODBUS_TIMEOUT, 
    DEFAULT_MODBUS_TIMEOUT,
    REG_MANUFACTURER,
    REG_MODEL,
    REG_SERIAL,
    REG_BATTERY_MAX_CHARGE_LIMIT,
    REG_BATTERY_MAX_DISCHARGE_LIMIT
)
from .modbus_handler import KostalModbusHandler

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.NUMBER, Platform.SENSOR]

@dataclass
class KostalData:
    handler: KostalModbusHandler
    charge_rate: float = 5000.0
    discharge_rate: float = 5000.0
    last_stop_time: float = 0.0
    inverter_timeout: int = DEFAULT_MODBUS_TIMEOUT
    current_max_charge_watts: float = 0.0
    current_max_discharge_watts: float = 0.0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Kostal Modbus Control from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    unit_id = entry.data.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)
    timeout = entry.data.get(CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT)

    handler = KostalModbusHandler(host, port, unit_id)
    # Ensure connection is established (or at least attempted)
    await handler.connect()

    # Read device info for registry
    # String 16 -> 8 registers, String 32 -> 16 registers
    manufacturer = await handler.read_string(REG_MANUFACTURER, 8) 
    if not manufacturer:
        manufacturer = "Kostal"
    
    model = await handler.read_string(REG_MODEL, 16)
    if not model:
         model = "Unknown Model"

    serial = await handler.read_string(REG_SERIAL, 8)
    if not serial:
         serial = "Unknown Serial"

    _LOGGER.info(f"Discovered Kostal device: {manufacturer} {model} (Serial: {serial})")

    # Register device
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=manufacturer,
        model=model,
        name=f"Kostal Inverter {host}",
        serial_number=serial,
    )
    
    # Read initial values for charge/discharge rates from battery limits
    initial_charge_rate = 5000.0
    initial_discharge_rate = 5000.0

    try:
        val_charge = await handler.read_float(REG_BATTERY_MAX_CHARGE_LIMIT)
        if val_charge is not None:
            initial_charge_rate = val_charge
            
        val_discharge = await handler.read_float(REG_BATTERY_MAX_DISCHARGE_LIMIT)
        if val_discharge is not None:
            initial_discharge_rate = val_discharge
    except Exception as e:
        _LOGGER.warning(f"Failed to read initial battery limits: {e}")

    data = KostalData(
        handler=handler, 
        inverter_timeout=timeout,
        charge_rate=initial_charge_rate,
        discharge_rate=initial_discharge_rate
    )
    hass.data[DOMAIN][entry.entry_id] = data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data: KostalData = hass.data[DOMAIN].pop(entry.entry_id)
        await data.handler.close()

    return unload_ok
