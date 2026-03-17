from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
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
    REG_BATTERY_SOC,
    REG_BATTERY_POWER,
    REG_BATTERY_VOLTAGE,
    REG_BATTERY_CURRENT,
    REG_BATTERY_TEMP,
    REG_BATTERY_MAX_CHARGE_LIMIT,
    REG_BATTERY_MAX_DISCHARGE_LIMIT,
)
import pymodbus

from .modbus_handler import KostalModbusHandler

_LOGGER = logging.getLogger(__name__)
_LOGGER.warning("pymodbus version: %s", pymodbus.__version__)


class KostalCoordinator(DataUpdateCoordinator):
    """Coordinator that batches all sensor reads into a single update cycle."""

    def __init__(self, hass: HomeAssistant, handler: KostalModbusHandler, kostal_data: "KostalData") -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=LOOP_INTERVAL),
        )
        self._handler = handler
        self._kostal_data = kostal_data

    async def _async_update_data(self) -> dict:
        try:
            data: dict = {}
            for address in (
                REG_BATTERY_SOC,
                REG_BATTERY_POWER,
                REG_BATTERY_VOLTAGE,
                REG_BATTERY_CURRENT,
                REG_BATTERY_TEMP,
                REG_BATTERY_MAX_CHARGE_LIMIT,
                REG_BATTERY_MAX_DISCHARGE_LIMIT,
            ):
                data[address] = await self._handler.read_float(address)
            if (val := data.get(REG_BATTERY_MAX_CHARGE_LIMIT)) is not None:
                self._kostal_data.current_max_charge_watts = val
            if (val := data.get(REG_BATTERY_MAX_DISCHARGE_LIMIT)) is not None:
                self._kostal_data.current_max_discharge_watts = val
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
    last_stop_time: float = 0.0
    inverter_timeout: int = DEFAULT_MODBUS_TIMEOUT
    current_max_charge_watts: float = 0.0
    current_max_discharge_watts: float = 0.0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Kostal Modbus Control from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    unit_id = DEFAULT_UNIT_ID  # Always 71 for Plenticore battery management
    timeout = entry.data.get(CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT)

    _LOGGER.info("Setting up Kostal Modbus: host=%s port=%s unit_id=%s", host, port, unit_id)

    handler = KostalModbusHandler(host, port, unit_id)
    try:
        await handler.connect()
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot connect to Kostal inverter at {host}:{port}") from err

    # Register device with static info (string registers are not reliable via Modbus on all firmware)
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="Kostal",
        model="Plenticore",
        name=f"Kostal Inverter {host}",
    )
    
    data = KostalData(handler=handler, inverter_timeout=timeout)

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

    return unload_ok
