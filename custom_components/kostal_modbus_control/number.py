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
    SOC_LIMIT_ARM_MARGIN,
    REG_BATTERY_SOC,
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
    settings (min 5%, max 100%) once the writes stop. So the limit is left alone
    while the battery is far away from it, and the entity "arms"
    SOC_LIMIT_ARM_MARGIN percent points before the limit — early enough that the
    inverter already has it by the time the battery gets there. While armed the
    register is written on the same cadence as the charge/discharge loops to keep
    the watchdog fed. Moving back past the arm threshold simply stops the writes;
    no release value is ever sent.
    """

    _key: str
    _register: int
    _data_attr: str
    _inactive_value: float
    _arms_when_falling: bool  # True for the minimum limit, False for the maximum

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_step = 1.0
    _attr_mode = NumberMode.BOX
    _attr_entity_registry_enabled_default = False

    def __init__(self, data, entry_id: str) -> None:
        self._data = data
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_native_value = self._inactive_value
        self._armed = False
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
            "armed": self._armed,
            "active": self._is_active(),
            "arms_at": self._arm_threshold(),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (state := await self.async_get_last_number_data()) is not None and state.native_value is not None:
            self._attr_native_value = self._clamp(float(state.native_value))
        if self._attr_native_value is None:
            self._attr_native_value = self._inactive_value
        self._store_value(self._attr_native_value)
        self.async_write_ha_state()

        coordinator = self._data.coordinator
        if coordinator is not None:
            self.async_on_remove(coordinator.async_add_listener(self._evaluate))
        self._evaluate()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_timer()
        self._armed = False

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = self._clamp(value)
        self._store_value(self._attr_native_value)
        self.async_write_ha_state()

        was_armed = self._armed
        self._evaluate()
        if was_armed and self._armed:
            # Still armed, but on a different value — push it straight away
            self._schedule_write()

    def _clamp(self, value: float) -> float:
        return max(self._attr_native_min_value, min(self._attr_native_max_value, value))

    def _store_value(self, value: float) -> None:
        setattr(self._data, self._data_attr, value)

    def _is_active(self) -> bool:
        """False when the limit equals the inverter's own limit, i.e. unused."""
        if self._attr_native_value is None:
            return False
        return abs(self._attr_native_value - self._inactive_value) >= 0.5

    def _arm_threshold(self) -> float | None:
        """SoC at which writing starts, or None when the limit is not in use."""
        value = self._attr_native_value
        if value is None or not self._is_active():
            return None
        margin = SOC_LIMIT_ARM_MARGIN if self._arms_when_falling else -SOC_LIMIT_ARM_MARGIN
        return float(value) + margin

    def _wants_arm(self, soc: float, threshold: float) -> bool:
        return soc <= threshold if self._arms_when_falling else soc >= threshold

    @callback
    def _evaluate(self) -> None:
        threshold = self._arm_threshold()
        if threshold is None:
            self._disarm("limit not in use")
            return

        coordinator = self._data.coordinator
        soc = None
        if coordinator is not None and coordinator.data is not None:
            soc = coordinator.data.get(REG_BATTERY_SOC)
        if soc is None:
            _LOGGER.debug("%s: no battery SoC available, keeping armed=%s", self.name, self._armed)
            return

        if self._wants_arm(float(soc), threshold):
            self._arm(float(soc), threshold)
        else:
            self._disarm(f"battery SoC {float(soc):.1f}% moved past {threshold:.0f}%")

    def _arm(self, soc: float, threshold: float) -> None:
        if self._armed:
            return
        self._armed = True
        _LOGGER.info(
            "%s armed at %.0f%% (battery SoC %.1f%% reached %.0f%%) — writing register %d every %ds",
            self.name,
            self._attr_native_value,
            soc,
            threshold,
            self._register,
            self._loop_interval,
        )
        self._remove_timer = async_track_time_interval(
            self.hass, self._async_write_tick, timedelta(seconds=self._loop_interval)
        )
        self._schedule_write()
        self.async_write_ha_state()

    def _disarm(self, reason: str) -> None:
        self._cancel_timer()
        if not self._armed:
            return
        self._armed = False
        _LOGGER.info(
            "%s released (%s) — no longer writing register %d, the inverter falls back to its own limit",
            self.name,
            reason,
            self._register,
        )
        self.async_write_ha_state()

    def _cancel_timer(self) -> None:
        if self._remove_timer is not None:
            self._remove_timer()
            self._remove_timer = None

    def _schedule_write(self) -> None:
        if self._write_task is not None and not self._write_task.done():
            return
        self._write_task = self.hass.async_create_task(self._async_write_limit())

    async def _async_write_tick(self, *args) -> None:
        await self._async_write_limit()

    async def _async_write_limit(self) -> None:
        value = self._attr_native_value
        if not self._armed or value is None:
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
    _arms_when_falling = True
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
    _arms_when_falling = False
    _attr_name = "Battery Maximum SOC Limit"
    _attr_icon = "mdi:battery-arrow-up-outline"
    _attr_native_min_value = MAX_SOC_LIMIT_RANGE[0]
    _attr_native_max_value = MAX_SOC_LIMIT_RANGE[1]
