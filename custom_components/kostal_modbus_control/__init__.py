from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from functools import partial
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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
    REG_SOFTWARE_VERSION,
    SOFTWARE_VERSION_LENGTH,
    REST_VERSION_PATH,
    REST_VERSION_TIMEOUT_SECONDS,
    REST_VERSION_RETRY_SECONDS,
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
from .modbus_handler import KostalModbusHandler, KostalModbusRequestError

_LOGGER = logging.getLogger(__name__)


class KostalCoordinator(DataUpdateCoordinator[dict[Any, Any]]):
    """Coordinator that batches all sensor reads into a single update cycle.

    Values are keyed by register address, except where two devices share an
    address — see KEY_BATTERY_GROSS_CAPACITY.
    """

    def __init__(
        self, hass: HomeAssistant, handler: KostalModbusHandler, kostal_data: "KostalData", host: str
    ) -> None:
        super().__init__(
            hass,
            logging.getLogger(f"{__name__}.coordinator"),
            name=DOMAIN,
            update_interval=timedelta(seconds=LOOP_INTERVAL),
        )
        self._handler = handler
        self._kostal_data = kostal_data
        # Registers this inverter answered "no such address" for. Not every
        # Plenticore implements every documented register, so they are read
        # once and then skipped for the life of the entry.
        self._unsupported: set = set()
        self._host = host
        # Software version from the REST API, used only when register 58 is
        # refused. Fetched once per connection — see _async_rest_software_version.
        self._rest_version: str | None = None
        self._rest_version_next_try = 0.0
        self._rest_version_logged_failure = False

    async def _read_optional(self, key, description, read):
        """Read a register that some inverter models may not implement.

        An "illegal data address" reply is the inverter telling us the register
        does not exist on this firmware — record that, skip it from then on and
        carry on with the rest of the update. Timeouts and transport errors are
        left to propagate: those really do mean the inverter is unreachable.
        """
        if key in self._unsupported:
            return None
        try:
            return await read()
        except KostalModbusRequestError as err:
            self._unsupported.add(key)
            _LOGGER.info(
                "This inverter does not implement %s — it will be skipped from now on (%s)",
                description,
                err,
            )
            return None

    async def _async_rest_software_version(self) -> str | None:
        """UI software version from the inverter's REST API.

        Only used when the inverter refuses register 58. The web API reports the
        same version without logging in, and it only changes with a firmware
        update — which restarts the inverter, i.e. a communication outage — so
        it is fetched once per connection rather than on every poll. A failed
        fetch is retried after REST_VERSION_RETRY_SECONDS, and the last known
        version is kept in the meantime.
        """
        now = time.monotonic()
        if now < self._rest_version_next_try:
            return self._rest_version
        url = f"http://{self._host}{REST_VERSION_PATH}"
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=REST_VERSION_TIMEOUT_SECONDS)
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
            version = payload.get("sw_version") if isinstance(payload, dict) else None
            if not version:
                raise ValueError(f"no sw_version in {payload!r}")
        except Exception as err:
            self._rest_version_next_try = now + REST_VERSION_RETRY_SECONDS
            log = _LOGGER.debug if self._rest_version_logged_failure else _LOGGER.info
            log(
                "Could not read the software version from %s, retrying later: %s %s",
                url,
                type(err).__name__,
                err,
            )
            self._rest_version_logged_failure = True
            return self._rest_version

        self._rest_version = str(version).strip()
        self._rest_version_next_try = float("inf")
        self._rest_version_logged_failure = False
        _LOGGER.debug("Software version %s read from %s", self._rest_version, url)
        return self._rest_version

    async def _async_update_data(self) -> dict:
        try:
            # First poll after an outage: re-probe everything. A register refused
            # while the inverter was rebooting is not necessarily missing, and a
            # transient must never disable an entity for the rest of the session.
            # Costs one failed read per genuinely absent register per reconnect.
            if not self._kostal_data.communication_ok and self._unsupported:
                _LOGGER.debug(
                    "Communication was lost — re-probing %d previously unsupported register(s)",
                    len(self._unsupported),
                )
                self._unsupported.clear()
            if not self._kostal_data.communication_ok:
                # A firmware update restarts the inverter, so fetch the REST
                # version again once the connection is back
                self._rest_version_next_try = 0.0
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
                data[address] = await self._read_optional(
                    address,
                    f"register {address}",
                    partial(self._handler.read_float, address),
                )
            for key, description, read in (
                # S16 register (1 register, signed int)
                (REG_BATTERY_POWER, "battery power", partial(self._handler.read_int16, REG_BATTERY_POWER)),
                # U8 registers
                (REG_SENSOR_TYPE, "sensor type", partial(self._handler.read_uint8, REG_SENSOR_TYPE)),
                (REG_BATTERY_MGMT_MODE, "battery management mode", partial(self._handler.read_uint8, REG_BATTERY_MGMT_MODE)),
                # U32 register
                (REG_INVERTER_STATE, "inverter state", partial(self._handler.read_uint32, REG_INVERTER_STATE)),
                # The battery info block is big-endian regardless of the inverter's
                # byte-order setting, unlike the state register above
                (
                    KEY_BATTERY_GROSS_CAPACITY,
                    "battery gross capacity",
                    partial(self._handler.read_uint32_big_endian, REG_BATTERY_GROSS_CAPACITY),
                ),
                (
                    REG_BATTERY_MODEL_ID,
                    "battery model ID",
                    partial(self._handler.read_uint32_big_endian, REG_BATTERY_MODEL_ID),
                ),
                (
                    REG_BATTERY_BMS_SERIAL,
                    "battery BMS serial",
                    partial(self._handler.read_uint32_big_endian, REG_BATTERY_BMS_SERIAL),
                ),
                (
                    REG_BATTERY_FIRMWARE,
                    "battery firmware",
                    partial(self._handler.read_uint32_big_endian, REG_BATTERY_FIRMWARE),
                ),
                # U16 register
                (REG_BATTERY_TYPE, "battery type", partial(self._handler.read_uint16, REG_BATTERY_TYPE)),
                # String register — byte order is fixed, no word swap involved.
                # PLENTICORE plus G1 does not implement this one at all.
                (
                    REG_SOFTWARE_VERSION,
                    f"the software version register {REG_SOFTWARE_VERSION}",
                    partial(self._handler.read_string, REG_SOFTWARE_VERSION, SOFTWARE_VERSION_LENGTH),
                ),
            ):
                data[key] = await self._read_optional(key, description, read)
            if REG_SOFTWARE_VERSION in self._unsupported:
                data[REG_SOFTWARE_VERSION] = await self._async_rest_software_version()
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


async def _read_optional_at_setup(read, description):
    """Read an identity register, tolerating an inverter that lacks it.

    Setup only reads diagnostics here and every caller already copes with None,
    so a missing register must not stop the integration from loading. A real
    connection problem still raises and lands as ConfigEntryNotReady.
    """
    try:
        return await read()
    except KostalModbusRequestError as err:
        _LOGGER.info("This inverter does not implement %s: %s", description, err)
        return None


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

    modbus_byte_order = await _read_optional_at_setup(
        partial(handler.read_uint16, REG_MODBUS_BYTE_ORDER), "the byte-order register"
    )
    handler.set_modbus_byte_order(modbus_byte_order)

    # Read static string registers from inverter
    inverter_model = await _read_optional_at_setup(
        partial(handler.read_string, REG_MODEL, 16), "the model register"
    ) or ""
    inverter_power_class = await _read_optional_at_setup(
        partial(handler.read_string, REG_POWER_CLASS, 16), "the power class register"
    ) or ""
    _LOGGER.info("Inverter model=%r power_class=%r", inverter_model, inverter_power_class)

    battery_type_raw = await _read_optional_at_setup(
        partial(handler.read_uint16, REG_BATTERY_TYPE), "the battery type register"
    )
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

    coordinator = KostalCoordinator(hass, handler, data, host)
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
