from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DOMAIN,
    NUMBER_CHARGE_RATE,
    NUMBER_DISCHARGE_RATE,
    NUMBER_FUSE_SIZE,
    NUMBER_MIN_SOC_LIMIT,
    NUMBER_MAX_SOC_LIMIT,
    DEFAULT_CHARGE_RATE,
    DEFAULT_DISCHARGE_RATE,
    DEFAULT_FUSE_SIZE,
    DEFAULT_MIN_SOC_LIMIT,
    DEFAULT_MAX_SOC_LIMIT,
    MIN_SOC_LIMIT_RANGE,
    MAX_SOC_LIMIT_RANGE,
    REG_BATTERY_MIN_SOC,
    REG_BATTERY_MAX_SOC,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Kostal Modbus numbers."""
    data = hass.data[DOMAIN][entry.entry_id]

    entities = [
        KostalNumber(data, entry.entry_id, NUMBER_CHARGE_RATE, "Set Charge Rate", "%", DEFAULT_CHARGE_RATE),
        KostalNumber(data, entry.entry_id, NUMBER_DISCHARGE_RATE, "Set Discharge Rate", "%", DEFAULT_DISCHARGE_RATE),
        KostalFuseSizeNumber(data, entry.entry_id),
        KostalMinSocLimitNumber(data, entry.entry_id),
        KostalMaxSocLimitNumber(data, entry.entry_id),
    ]

    async_add_entities(entities)

class KostalNumber(RestoreNumber):
    """Representation of a Kostal Modbus Number."""

    _attr_has_entity_name = True
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_mode = NumberMode.BOX

    def __init__(self, data, entry_id, key, name, unit, default):
        self._data = data
        self._entry_id = entry_id
        self._key = key
        self._default = default
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_name = name
        self._attr_native_value = default
        self._attr_native_unit_of_measurement = unit
        self._update_data_store(default)

    async def async_added_to_hass(self) -> None:
        """Restore last user-set value on HA restart."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_number_data()) is not None and state.native_value is not None:
            self._attr_native_value = state.native_value
            self._update_data_store(state.native_value)
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
        )

    def _update_data_store(self, value):
        if self._key == NUMBER_CHARGE_RATE:
            self._data.charge_rate = value
        elif self._key == NUMBER_DISCHARGE_RATE:
            self._data.discharge_rate = value

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self._update_data_store(value)
        self.async_write_ha_state()


class KostalFuseSizeNumber(RestoreNumber):
    """Input for house fuse size in Ampere."""

    _attr_has_entity_name = True
    _attr_unique_id = None  # Set in __init__
    _attr_native_min_value = 6.0
    _attr_native_max_value = 125.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "A"
    _attr_mode = NumberMode.BOX
    _attr_name = "House Fuse Size"
    _attr_icon = "mdi:fuse"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, data, entry_id: str) -> None:
        self._data = data
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{NUMBER_FUSE_SIZE}"
        self._attr_native_value = DEFAULT_FUSE_SIZE
        self._data.fuse_size = DEFAULT_FUSE_SIZE

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (state := await self.async_get_last_number_data()) is not None and state.native_value is not None:
            self._attr_native_value = state.native_value
            self._data.fuse_size = float(state.native_value)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self._data.fuse_size = value
        self.async_write_ha_state()


class KostalSocLimitNumber(RestoreNumber):
    """Base for the battery min/max SOC limits.

    Registers 1042/1044 are governed by the inverter's Modbus timeout: a limit
    only holds while it is being sent, and the inverter reverts to its own
    settings (min 5%, max 100%) once the writes stop. A limit that is in use is
    therefore written continuously — from the moment it is set, on the same
    cadence as the charge/discharge loops — so it stays in force for as long as
    it is set. The inverter tapers charge/discharge power as the SoC approaches
    the limit; that taper is what makes "stop charging at 50%" actually hold.

    Setting a limit back to the inverter's own value (min 5%, max 100%) means
    "not in use": that value is written once so the release takes effect
    straight away instead of waiting out the inverter's timeout, and nothing is
    sent afterwards.
    """

    _key: str
    _register: int
    _data_attr: str
    _inactive_value: float

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_step = 1.0
    _attr_mode = NumberMode.BOX

    def __init__(self, data, entry_id: str) -> None:
        self._data = data
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_native_value = self._inactive_value
        self._remove_timer = None
        self._write_task = None
        # Write twice per inverter timeout, same as the charge/discharge loops
        self._loop_interval = max(int(self._data.inverter_timeout / 2), 5)
        self._store_value(self._inactive_value)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "active": self._is_active(),
            "writing": self._remove_timer is not None,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (state := await self.async_get_last_number_data()) is not None and state.native_value is not None:
            self._attr_native_value = self._clamp(float(state.native_value))
        if self._attr_native_value is None:
            self._attr_native_value = self._inactive_value
        self._store_value(self._attr_native_value)
        self._apply()
        if self._is_active():
            # Fire and forget — awaiting a Modbus round-trip here would hold up
            # entity setup on a slow or unreachable inverter
            self._schedule_write()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_timer()
        if self._write_task is not None and not self._write_task.done():
            self._write_task.cancel()
        self._write_task = None

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = self._clamp(value)
        self._store_value(self._attr_native_value)
        self._apply()
        self.async_write_ha_state()
        pending = self._write_task
        if pending is not None and not pending.done():
            # A keep-alive write already in flight captured the previous value,
            # so let it land before writing the new one — the other order would
            # undo the change until the next tick, or for good on a release
            try:
                await pending
            except Exception:  # already logged and handled inside the write
                pass
        # Awaited rather than scheduled so a value change is never dropped
        # behind an in-flight keep-alive write. This is also the one-shot
        # release write when the limit was just set back to its inactive value.
        await self._async_write_limit()

    def _clamp(self, value: float) -> float:
        return max(self._attr_native_min_value, min(self._attr_native_max_value, value))

    def _store_value(self, value: float) -> None:
        setattr(self._data, self._data_attr, value)

    def _is_active(self) -> bool:
        """False when the limit equals the inverter's own limit, i.e. unused."""
        if self._attr_native_value is None:
            return False
        return abs(self._attr_native_value - self._inactive_value) >= 0.5

    @callback
    def _apply(self) -> None:
        """Bring the keep-alive write loop in line with the current value."""
        if self._is_active():
            self._start_timer()
        else:
            self._cancel_timer()

    def _start_timer(self) -> None:
        if self._remove_timer is not None:
            return
        _LOGGER.info(
            "%s set to %.0f%% — writing register %d every %ds",
            self.name,
            self._attr_native_value,
            self._register,
            self._loop_interval,
        )
        self._remove_timer = async_track_time_interval(
            self.hass, self._async_write_tick, timedelta(seconds=self._loop_interval)
        )

    def _cancel_timer(self) -> None:
        if self._remove_timer is None:
            return
        self._remove_timer()
        self._remove_timer = None
        _LOGGER.info(
            "%s released — register %d set back to %.0f%% and no longer written",
            self.name,
            self._register,
            self._inactive_value,
        )

    def _schedule_write(self) -> None:
        if self._write_task is not None and not self._write_task.done():
            return
        self._write_task = self.hass.async_create_task(self._async_write_limit())

    async def _async_write_tick(self, *args) -> None:
        await self._async_write_limit()

    async def _async_write_limit(self) -> None:
        value = self._attr_native_value
        if value is None:
            return
        try:
            await self._data.handler.write_float(self._register, float(value))
        except Exception as err:
            self._data.mark_communication_lost(f"{self.name}: {err}")
            _LOGGER.warning("%s failed to write register %d: %s", self.name, self._register, err)
            await self._data.handler.close()


class KostalMinSocLimitNumber(KostalSocLimitNumber):
    """Minimum SOC. 5% means unused — that is the inverter's own minimum."""

    _key = NUMBER_MIN_SOC_LIMIT
    _register = REG_BATTERY_MIN_SOC
    _data_attr = "min_soc"
    _inactive_value = DEFAULT_MIN_SOC_LIMIT
    _attr_name = "Battery Minimum SOC Limit"
    _attr_icon = "mdi:battery-arrow-down-outline"
    _attr_native_min_value = MIN_SOC_LIMIT_RANGE[0]
    _attr_native_max_value = MIN_SOC_LIMIT_RANGE[1]


class KostalMaxSocLimitNumber(KostalSocLimitNumber):
    """Maximum SOC. 100% means unused — that is the inverter's own maximum."""

    _key = NUMBER_MAX_SOC_LIMIT
    _register = REG_BATTERY_MAX_SOC
    _data_attr = "max_soc"
    _inactive_value = DEFAULT_MAX_SOC_LIMIT
    _attr_name = "Battery Maximum SOC Limit"
    _attr_icon = "mdi:battery-arrow-up-outline"
    _attr_native_min_value = MAX_SOC_LIMIT_RANGE[0]
    _attr_native_max_value = MAX_SOC_LIMIT_RANGE[1]
