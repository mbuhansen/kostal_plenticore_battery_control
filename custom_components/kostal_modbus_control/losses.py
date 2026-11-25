"""Battery and inverter losses measured from the inverter's own readings.

The figures match Predbat's battery_loss, battery_loss_discharge and
inverter_loss: losses as fractions (0.04), not efficiencies.

The inverter has no counter for the DC energy into the battery: 1046 is only
PV to battery, and charging from the AC side is counted on the AC side alone.
So the DC energy in and out is summed here from the battery power (582) on
every poll.

- Inverter loss:
    discharge: 1 - (home from battery (110) + battery to grid (1052)) / DC out of the battery (1048).
               Battery discharge always passes the inverter, so this holds all day.
    charge:    1 - DC into the battery (summed 582) / AC side to the battery (1050),
               at night only: by day PV also charges the battery DC to DC.
  Predbat has one inverter loss for both directions, so the sensor is the mean
  of the two (or the one that has enough energy behind it).
- Battery loss is the DC round trip, DC out / DC in (both summed from 582, so a
  scale error in the reading cancels), over a span where the SOC ends where it
  started — so no battery capacity is needed. It is split evenly between
  charge and discharge: 1 - sqrt(round trip).

The tracker is pure Python so it can be tested without Home Assistant.
"""

from __future__ import annotations

import math
from typing import Any

# Keys as stored in the coordinator data (the register addresses)
REG_DC_DISCHARGE_WH = 1048      # Total DC discharge energy (DC side from battery)
REG_AC_CHARGE_WH = 1050         # Total AC charge energy (AC side to battery)
REG_AC_DISCHARGE_GRID_WH = 1052  # Total AC discharge energy (battery to grid)
REG_HOME_FROM_BATTERY_WH = 110  # Total home consumption from battery
LOSS_COUNTER_REGISTERS = (
    REG_DC_DISCHARGE_WH,
    REG_AC_CHARGE_WH,
    REG_AC_DISCHARGE_GRID_WH,
    REG_HOME_FROM_BATTERY_WH,
)
REG_BATTERY_POWER = 582         # Battery power (W), negative = charge
REG_BATTERY_SOC = 210
REG_PV_POWER = 1066

# PV power below this counts as night
NIGHT_PV_MAX_W = 10.0
# A gap between polls longer than this (an outage) is not summed
MAX_POLL_GAP_SECONDS = 120.0
SNAPSHOT_INTERVAL_SECONDS = 15 * 60
WINDOW_SECONDS = 7 * 24 * 3600
# Least energy behind a figure before it is shown, in Wh
MIN_INVERTER_ENERGY_WH = 3000.0
MIN_ROUND_TRIP_CHARGE_WH = 30000.0
# Shortest span the round trip is measured over
MIN_ROUND_TRIP_SPAN_SECONDS = 24 * 3600
# How close the SOC at both ends of the round-trip span must be (percentage points)
ROUND_TRIP_SOC_TOLERANCE = 1.0

# Cumulative sums kept by the tracker and copied into every snapshot (Wh)
_DC_IN, _DC_OUT, _NIGHT_AC_IN, _NIGHT_DC_IN, _COUNTER_DC_OUT, _COUNTER_AC_OUT = range(6)
# Snapshot layout (a list, to keep the store small): time, SOC, then the sums
_TS, _SOC = 0, 1
_SNAPSHOT_LENGTH = 2 + 6


class LossTracker:
    """Collects the readings poll by poll and works out the losses over a rolling window."""

    def __init__(self) -> None:
        self._sums = [0.0] * 6
        self._prev: tuple[float, list[float], float, bool] | None = None
        self._snapshots: list[list[float]] = []
        self.battery_loss: float | None = None
        self.inverter_loss: float | None = None
        self.battery_attributes: dict[str, Any] = {}
        self.inverter_attributes: dict[str, Any] = {}

    # -- storage -------------------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": 2,
            "sums": list(self._sums),
            "snapshots": [list(s) for s in self._snapshots],
            "battery_loss": self.battery_loss,
            "battery_attributes": self.battery_attributes,
        }

    def load(self, stored: dict[str, Any] | None) -> None:
        if not stored or stored.get("version") != 2:
            return
        sums = stored.get("sums")
        if isinstance(sums, list) and len(sums) == len(self._sums):
            self._sums = [float(v) for v in sums]
        snapshots = stored.get("snapshots")
        if isinstance(snapshots, list):
            self._snapshots = [
                [float(v) for v in s] for s in snapshots if isinstance(s, list) and len(s) == _SNAPSHOT_LENGTH
            ]
        if isinstance(stored.get("battery_loss"), (int, float)):
            self.battery_loss = float(stored["battery_loss"])
            self.battery_attributes = dict(stored.get("battery_attributes") or {})
        self._compute()

    # -- feeding -------------------------------------------------------------

    def update(self, now: float, data: dict) -> bool:
        """Feed one poll. Returns True when a snapshot was taken (time to save)."""
        counters = [data.get(reg) for reg in LOSS_COUNTER_REGISTERS]
        power = data.get(REG_BATTERY_POWER)
        soc = data.get(REG_BATTERY_SOC)
        if any(v is None for v in counters) or power is None or soc is None:
            self._prev = None
            return False
        counters = [float(v) for v in counters]
        power = float(power)
        # A battery inverter has no PV, and some models lack the PV power register
        pv = data.get(REG_PV_POWER)
        is_night = pv is None or pv < NIGHT_PV_MAX_W

        if self._prev is not None:
            prev_time, prev_counters, prev_power, prev_night = self._prev
            gap = now - prev_time
            deltas = [c - p for c, p in zip(counters, prev_counters)]
            if 0 < gap <= MAX_POLL_GAP_SECONDS and all(d >= 0 for d in deltas):
                hours = gap / 3600
                # Trapezoid, charge and discharge summed apart (582 is negative while charging)
                dc_in = (max(-prev_power, 0.0) + max(-power, 0.0)) / 2 * hours
                dc_out = (max(prev_power, 0.0) + max(power, 0.0)) / 2 * hours
                dc_out_counter, ac_in, ac_to_grid, home_from_battery = deltas
                self._sums[_DC_IN] += dc_in
                self._sums[_DC_OUT] += dc_out
                self._sums[_COUNTER_DC_OUT] += dc_out_counter
                self._sums[_COUNTER_AC_OUT] += home_from_battery + ac_to_grid
                if is_night and prev_night:
                    self._sums[_NIGHT_AC_IN] += ac_in
                    self._sums[_NIGHT_DC_IN] += dc_in
        self._prev = (now, counters, power, is_night)

        if self._snapshots and now - self._snapshots[-1][_TS] < SNAPSHOT_INTERVAL_SECONDS:
            return False
        self._snapshots.append([now, float(soc), *self._sums])
        cutoff = now - WINDOW_SECONDS
        # Keep the newest snapshot older than the window so the window is full
        while len(self._snapshots) > 2 and self._snapshots[1][_TS] <= cutoff:
            self._snapshots.pop(0)
        self._compute()
        return True

    # -- computing -----------------------------------------------------------

    def _compute(self) -> None:
        self._compute_inverter()
        self._compute_battery()

    @staticmethod
    def _delta(start: list[float], end: list[float], index: int) -> float:
        return end[2 + index] - start[2 + index]

    def _compute_inverter(self) -> None:
        self.inverter_loss = None
        self.inverter_attributes = {}
        if len(self._snapshots) < 2:
            return
        first, last = self._snapshots[0], self._snapshots[-1]
        ac_in = self._delta(first, last, _NIGHT_AC_IN)
        dc_in = self._delta(first, last, _NIGHT_DC_IN)
        dc_out = self._delta(first, last, _COUNTER_DC_OUT)
        ac_out = self._delta(first, last, _COUNTER_AC_OUT)
        charge_loss = 1.0 - dc_in / ac_in if ac_in >= MIN_INVERTER_ENERGY_WH else None
        discharge_loss = 1.0 - ac_out / dc_out if dc_out >= MIN_INVERTER_ENERGY_WH else None
        parts = [v for v in (charge_loss, discharge_loss) if v is not None and 0.0 <= v < 0.5]
        if parts:
            self.inverter_loss = round(sum(parts) / len(parts), 3)
        self.inverter_attributes = {
            "charge_loss": round(charge_loss, 3) if charge_loss is not None else None,
            "discharge_loss": round(discharge_loss, 3) if discharge_loss is not None else None,
            "night_ac_charged_kwh": round(ac_in / 1000, 2),
            "night_dc_charged_kwh": round(dc_in / 1000, 2),
            "dc_discharged_kwh": round(dc_out / 1000, 2),
            "ac_discharged_kwh": round(ac_out / 1000, 2),
            "window_days": round((last[_TS] - first[_TS]) / 86400, 1),
        }

    def _compute_battery(self) -> None:
        """Update the battery loss when a span qualifies; otherwise keep the last one."""
        if len(self._snapshots) < 2:
            return
        last = self._snapshots[-1]
        # The longest span ending now that starts at the same SOC
        for start in self._snapshots[:-1]:
            if last[_TS] - start[_TS] < MIN_ROUND_TRIP_SPAN_SECONDS:
                break
            if abs(last[_SOC] - start[_SOC]) > ROUND_TRIP_SOC_TOLERANCE:
                continue
            dc_in = self._delta(start, last, _DC_IN)
            dc_out = self._delta(start, last, _DC_OUT)
            if dc_in < MIN_ROUND_TRIP_CHARGE_WH or dc_out <= 0:
                continue
            round_trip = dc_out / dc_in
            if not 0.5 < round_trip <= 1.0:
                continue
            self.battery_loss = round(1.0 - math.sqrt(round_trip), 3)
            self.battery_attributes = {
                "round_trip_efficiency": round(round_trip, 3),
                "dc_charged_kwh": round(dc_in / 1000, 2),
                "dc_discharged_kwh": round(dc_out / 1000, 2),
                "soc_start": round(start[_SOC], 1),
                "soc_end": round(last[_SOC], 1),
                "span_days": round((last[_TS] - start[_TS]) / 86400, 1),
            }
            return
