"""Constants for the Kostal Modbus Control integration."""

DOMAIN = "kostal_modbus_control"
CONF_PORT = "port"
CONF_UNIT_ID = "unit_id"
CONF_MODBUS_TIMEOUT = "modbus_timeout"  # The configured timeout on the inverter
CONF_INVERTER_TYPE = "inverter_type"
INVERTER_TYPE_HYBRID = "hybrid"
INVERTER_TYPE_BI = "bi"

DEFAULT_PORT = 1502
DEFAULT_UNIT_ID = 71
DEFAULT_MODBUS_TIMEOUT = 30  # Default inverter timeout setting

# Modbus Registers (Holding Registers)
REG_MODBUS_BYTE_ORDER = 5        # Modbus byte order - U16 (0x05) 0=little-endian CDAB, 1=big-endian ABCD
REG_MANUFACTURER = 535        # Inverter Manufacturer (String 16)
REG_MODEL = 768               # Productname (String 32)
REG_POWER_CLASS = 800         # Power class e.g. "10" (String 32)
REG_SERIAL = 559              # Inverter Serial Number (String 16)
REG_SOFTWARE_VERSION = 58     # Overall software version (UI / SW) - String 13 (0x3A)
SOFTWARE_VERSION_LENGTH = 13  # Registers, per the Kostal register table
# Fallback for inverters without register 58 (PLENTICORE plus G1): the web
# API reports the same UI version without logging in. On a G3 both sources
# return 3.07.00.25886; a G1 answers 01.30.12092 here and nothing over Modbus.
REST_VERSION_PATH = "/api/v1/info/version"
REST_VERSION_TIMEOUT_SECONDS = 10
REST_VERSION_RETRY_SECONDS = 600  # After a failed fetch, e.g. web server still starting
REG_INVERTER_STATE = 56       # Inverter state - U32 (0x38)
# External battery management (Kostal Modbus doc section 3.4). Setpoints are
# signed: negative = charge, positive = discharge. The integration controls the
# battery with the absolute setpoints in Watts; the inverter holds a setpoint
# for about 30 s after the last write, then falls back to its own control.
REG_BATTERY_AC_POWER_SETPOINT_W = 1026      # Battery charge power (AC) setpoint, absolute (W) - Float (0x402) RW. PLENTICORE BI and (MP) G3 only; used for BI
REG_BATTERY_DC_POWER_SETPOINT_W = 1034      # Battery charge power (DC) setpoint, absolute (W) - Float (0x40A) RW. Used for hybrid inverters
REG_BATTERY_MAX_CHARGE_POWER_W = 1038       # Battery max. charge power limit, absolute (W) - Float (0x40E) RW. Written 0 to block charging
REG_BATTERY_MAX_DISCHARGE_POWER_W = 1040    # Battery max. discharge power limit, absolute (W) - Float (0x410) RW. Written 0 to block discharging
REG_BATTERY_MIN_SOC = 1042        # Minimum SOC % - Float (0x412) RW
REG_BATTERY_MAX_SOC = 1044        # Maximum SOC % - Float (0x414) RW

# Maximum battery control power. Hybrid inverters: the battery's maximum
# voltage times the nominal battery current (Inom). Inom is measured as
# 1078 / battery voltage (on a G3, 1078 is exactly 30 A times the actual
# voltage), keeping the highest value seen so a BMS derating does not lower it,
# and capped by the documented Inom of the inverter generation — the first
# number of the software version: 01.30.12092 = G1, 02.15.xxxxx = G2,
# 3.07.00.xxxxx = G3 (and MP G3). The maximum voltage is the highest 1076 / Inom
# (on a G3, 1076 is 30 A times 395 V), which keeps the value fixed instead of
# moving with the state of charge.
# A maximum voltage derived from 1076 above this many times the actual battery
# voltage means 1076 is not based on Inom on that model; the actual voltage is
# used instead. Lithium packs span roughly 1.2x from empty to full.
BATTERY_MAX_VOLTAGE_PLAUSIBLE_RATIO = 1.3
BATTERY_NOMINAL_CURRENT_BY_GENERATION = {
    1: 13.0,  # PLENTICORE plus G1
    2: 13.0,  # PLENTICORE plus G2
    3: 30.0,  # PLENTICORE G3 / MP G3
}
# PLENTICORE BI: the AC setpoint is limited by the nominal AC power, i.e. the
# power class (register 800) of the BI 5.5/26 or BI 10/26 — the 26 A battery
# current is not reachable within it.
BI_NOMINAL_POWER_BY_POWER_CLASS = {
    5.5: 5500.0,    # PLENTICORE BI 5.5/26
    10.0: 10000.0,  # PLENTICORE BI 10/26
}

# I/O Board Output Registers
REG_IO_OUTPUT_1 = 608             # I/O-Board Switched Output 1 - U16 (0x260) RW
REG_IO_OUTPUT_2 = 609             # I/O-Board Switched Output 2 - U16 (0x261) RW
REG_IO_OUTPUT_3 = 610             # I/O-Board Switched Output 3 - U16 (0x262) RW
REG_IO_OUTPUT_4 = 611             # I/O-Board Switched Output 4 - U16 (0x263) RW

# Read-Only Registers (Battery Data)
REG_BATTERY_SOC = 210             # Act. state of charge (%) - Float (0xD2)
REG_BATTERY_TEMP = 214            # Battery Temperature (°C) - Float (0xD6)
REG_BATTERY_VOLTAGE = 216         # Battery Voltage (V) - Float (0xD8)
REG_BATTERY_CURRENT = 200         # Actual battery charge (-) / discharge (+) current (A) - Float (0xC8)
REG_BATTERY_CYCLES = 194          # Number of battery cycles - Float (0xC2)
REG_BATTERY_GROSS_CAPACITY = 512  # Battery gross capacity (Ah) - U32 (0x200)
# Coordinator data key for the value above. Register 512 is also the KSEM's
# imported-energy register, and both devices are read into the same dict, so
# the KSEM value would otherwise overwrite the gross capacity.
KEY_BATTERY_GROSS_CAPACITY = "battery_gross_capacity_value"
REG_BATTERY_MODEL_ID = 525        # Battery Model ID - U32 (0x20D)
REG_BATTERY_BMS_SERIAL = 527      # Battery serial number - U32 (0x20F)
REG_BATTERY_POWER = 582           # Actual battery charge/discharge power (W) - S16, negative=charge
REG_BATTERY_FIRMWARE = 586        # Battery Firmware - U32 (0x24A)
REG_BATTERY_TYPE = 588            # Battery type - U16 (0x24C)

# Read-Only Registers (Grid/Powermeter)
REG_TOTAL_ACTIVE_POWER = 252      # Grid power (powermeter) (W) - Float (0xFC)
REG_VOLTAGE_PHASE1 = 230          # Voltage phase 1 powermeter (V) - Float (0xE6)
REG_VOLTAGE_PHASE2 = 240          # Voltage phase 2 powermeter (V) - Float (0xF0)
REG_VOLTAGE_PHASE3 = 250          # Voltage phase 3 powermeter (V) - Float (0xFA)
REG_CURRENT_PHASE1 = 222          # Current phase 1 powermeter (A) - Float (0xDE)
REG_CURRENT_PHASE2 = 232          # Current phase 2 powermeter (A) - Float (0xE8)
REG_CURRENT_PHASE3 = 242          # Current phase 3 powermeter (A) - Float (0xF2)
REG_SENSOR_TYPE = 1082            # Installed sensor type - U8 (0x43A)

SENSOR_TYPE_MAP = {
    0x00: "SDM 630 (B+G E-Tech GmbH)",
    0x01: "B-Control EM-300 LR (TQ Systems)",
    0x02: "Reserved",
    0x03: "KOSTAL Smart Energy Meter (KOSTAL)",
    0xFF: "No sensor",
}
SENSOR_TYPE_KSEM = 0x03
SENSOR_TYPE_NONE = 0xFF

INVERTER_STATE_MAP = {
    0: "Off",
    1: "Init",
    2: "IsoMeas",
    3: "GridCheck",
    4: "StartUp",
    5: "-",
    6: "FeedIn",
    7: "Throttled",
    8: "ExtSwitchOff",
    9: "Update",
    10: "Standby",
    11: "GridSync",
    12: "GridPreCheck",
    13: "GridSwitchOff",
    14: "Overheating",
    15: "Shutdown",
    16: "ImproperDcVoltage",
    17: "ESB",
    18: "Unknown",
}

REG_BATTERY_MAX_CHARGE_LIMIT = 1076    # Maximum charge power limit, read-out from battery (W) - Float
REG_BATTERY_MAX_DISCHARGE_LIMIT = 1078 # Maximum discharge power limit, read-out from battery (W) - Float
REG_BATTERY_WORK_CAPACITY = 1068       # Battery work capacity (Wh) - Float
REG_BATTERY_MGMT_MODE = 1080          # Battery management mode - U8

# Battery management modes reported by register 1080. Only MODBUS accepts the
# external charge/discharge commands this integration sends — in the other two
# modes the inverter silently ignores every write.
BATTERY_MGMT_MODE_NONE = 0x00
BATTERY_MGMT_MODE_DIGITAL_IO = 0x01
BATTERY_MGMT_MODE_MODBUS = 0x02
BATTERY_MGMT_MODE_MAP = {
    BATTERY_MGMT_MODE_NONE: "No external battery management",
    BATTERY_MGMT_MODE_DIGITAL_IO: "External battery management via digital I/O",
    BATTERY_MGMT_MODE_MODBUS: "External battery management via Modbus protocol",
}

BATTERY_TYPE_MAP = {
    0x0000: "No battery (PV only)",
    0x0002: "PIKO Battery Li",
    0x0004: "BYD",
    0x0008: "BMZ",
    0x0010: "AXIstorage Li SH",
    0x0040: "LG",
    0x0200: "Pyontech Force H",
    0x0400: "AXIstorage Li SV",
    0x1000: "Dyness Tower / TowerPro",
    0x2000: "VARTA.wall",
    0x4000: "ZYC",
}

BATTERY_TYPE_BYD = 0x0004

# Battery Model ID (register 525) decoded for BYD packs
BYD_MODEL_MAP = {
    1: "HVS 5.1",
    2: "HVS 7.7",
    3: "HVS 10.2",
    4: "HVS 12.8",
    5: "HVM 8.3",
    6: "HVM 11.0",
    7: "HVM 13.8",
    8: "HVM 16.6",
    9: "HVM 19.3",
    10: "HVM 22.1",
}

# Entity descriptions (Sensors)
SENSOR_BATTERY_SOC = "battery_soc"
SENSOR_BATTERY_POWER = "battery_power"
SENSOR_BATTERY_VOLTAGE = "battery_voltage"
SENSOR_BATTERY_TEMP = "battery_temp"
SENSOR_BATTERY_MAX_CHARGE_LIMIT = "battery_max_charge_limit"
SENSOR_BATTERY_MAX_DISCHARGE_LIMIT = "battery_max_discharge_limit"
SENSOR_TOTAL_ACTIVE_POWER = "total_active_power"
SENSOR_VOLTAGE_PHASE1 = "voltage_phase1"
SENSOR_VOLTAGE_PHASE2 = "voltage_phase2"
SENSOR_VOLTAGE_PHASE3 = "voltage_phase3"
SENSOR_CURRENT_PHASE1 = "current_phase1"
SENSOR_CURRENT_PHASE2 = "current_phase2"
SENSOR_CURRENT_PHASE3 = "current_phase3"
SENSOR_SENSOR_TYPE = "sensor_type"
SENSOR_EMS_STATUS = "ems_status"
SENSOR_EMS_CHARGE_LIMIT_POWER = "ems_charge_limit_power"
SENSOR_PREDBAT_STATUS = "predbat_status"
SENSOR_PREDBAT_MODE = "predbat_mode"
SENSOR_BATTERY_DC_POWER_SETPOINT = "battery_dc_power_setpoint"
SENSOR_BATTERY_AC_POWER_SETPOINT = "battery_ac_power_setpoint"
SENSOR_BATTERY_MAX_CONTROL_POWER = "battery_max_control_power"
SENSOR_BATTERY_MAX_CHARGE_POWER_LIMIT = "battery_max_charge_power_limit"
SENSOR_BATTERY_MAX_DISCHARGE_POWER_LIMIT = "battery_max_discharge_power_limit"
SENSOR_BATTERY_WORK_CAPACITY = "battery_work_capacity"
SENSOR_BATTERY_MGMT_MODE = "battery_mgmt_mode"
SENSOR_BATTERY_TYPE = "battery_type"
SENSOR_BATTERY_FIRMWARE = "battery_firmware"
SENSOR_BATTERY_BMS_SERIAL = "battery_bms_serial"
SENSOR_SOFTWARE_VERSION = "software_version"
SENSOR_BATTERY_MODEL_ID = "battery_model_id"
SENSOR_BATTERY_MODEL_ID_TEXT = "battery_model_id_text"
SENSOR_BATTERY_GROSS_CAPACITY = "battery_gross_capacity"
SENSOR_BATTERY_CYCLES = "battery_cycles"
SENSOR_BATTERY_CURRENT = "battery_current"
SENSOR_BATTERY_MIN_SOC = "battery_min_soc"
SENSOR_BATTERY_MAX_SOC = "battery_max_soc"
SENSOR_INVERTER_STATE = "inverter_state"
SENSOR_INVERTER_STATE_TEXT = "inverter_state_text"
SENSOR_INVERTER_CONTROL_STATUS = "inverter_control_status"
SENSOR_INVERTER_CONTROL_TARGET_POWER = "inverter_control_target_power"
SENSOR_INVERTER_CONTROL_HOUSE_LOAD = "inverter_control_house_load"

# KSEM (KOSTAL Smart Energy Meter) Modbus configuration
CONF_KSEM_HOST = "ksem_host"
KSEM_PORT = 502
KSEM_SLAVE_ID = 1
KSEM_SCALE = 0.0001                   # int64 raw → kWh
REG_KSEM_ENERGY_IMPORTED = 512        # Consumption from grid (int64)
REG_KSEM_ENERGY_EXPORTED = 516        # Feed-in to grid (int64)
REG_KSEM_GRID_POWER_TOTAL = 40972     # Grid power Total (int32)
REG_KSEM_SUM_OUTPUT_INVERTER_AC = 40974  # Sum output inverter AC (int32)
REG_KSEM_SUM_PV_POWER_INVERTER_DC = 40976  # Sum pv power inverter DC (int32)
REG_KSEM_HOME_CONSUMPTION = 40982     # Home consumption (int32)
REG_KSEM_BATTERY_CHARGE_DISCHARGE_DC = 40984  # Sum battery charge / discharge DC (int32)
REG_KSEM_SYSTEM_SOC = 40986           # System state of charge (uint16)
REG_KSEM_HOME_CONSUMPTION_FROM_PV = 40988  # Home consumption from PV (uint32)
REG_KSEM_HOME_CONSUMPTION_FROM_BATTERY = 40990  # Home consumption from battery (uint32)
REG_KSEM_HOME_CONSUMPTION_FROM_GRID = 40992  # Home consumption from grid (uint32)
SENSOR_KSEM_ENERGY_IMPORTED = "ksem_energy_imported"
SENSOR_KSEM_ENERGY_EXPORTED = "ksem_energy_exported"
SENSOR_KSEM_GRID_POWER_TOTAL = "ksem_grid_power_total"
SENSOR_KSEM_SUM_OUTPUT_INVERTER_AC = "ksem_sum_output_inverter_ac"
SENSOR_KSEM_SUM_PV_POWER_INVERTER_DC = "ksem_sum_pv_power_inverter_dc"
SENSOR_KSEM_HOME_CONSUMPTION = "ksem_home_consumption"
SENSOR_KSEM_BATTERY_CHARGE_DISCHARGE_DC = "ksem_battery_charge_discharge_dc"
SENSOR_KSEM_SYSTEM_SOC = "ksem_system_soc"
SENSOR_KSEM_HOME_CONSUMPTION_FROM_PV = "ksem_home_consumption_from_pv"
SENSOR_KSEM_HOME_CONSUMPTION_FROM_BATTERY = "ksem_home_consumption_from_battery"
SENSOR_KSEM_HOME_CONSUMPTION_FROM_GRID = "ksem_home_consumption_from_grid"

# Dispatcher signal for EMS status updates (append _{entry_id} when used)
SIGNAL_EMS_STATUS_UPDATED = "kostal_modbus_ems_status"
SIGNAL_PREDBAT_STATUS_UPDATED = "kostal_modbus_predbat_status"
SIGNAL_INVERTER_CONTROL_UPDATED = "kostal_modbus_inverter_control"

# Default loop interval in seconds (from automation: usually 15s)
LOOP_INTERVAL = 15

# Grid control from an external Home Assistant grid-power entity, for
# inverters without a smart meter. Configured in the options flow; the
# Inverter Control switch only exists while a grid entity is selected.
CONF_SOURCE_GRID_POWER_ENTITY = "source_grid_power_entity"
CONF_GRID_TARGET_W = "grid_target_w"
CONF_GRID_DEADBAND_W = "grid_deadband_w"
CONF_EXTERNAL_CONTROL_MAX_DISCHARGE_W = "external_control_max_discharge_w"
CONF_EXTERNAL_CONTROL_MAX_CHARGE_W = "external_control_max_charge_w"
CONF_EXTERNAL_CONTROL_HYSTERESIS_W = "external_control_hysteresis_w"
CONF_EXTERNAL_CONTROL_EMA_ALPHA = "external_control_ema_alpha"
DEFAULT_GRID_TARGET_W = 0.0
# Alpha applies once per grid reading. Default 0.8 is tuned on a PLENTICORE G3
# with a grid entity updating every 8-10 s (Kostal Plenticore integration): a
# 2-2.5 kW load step settled within ±50 W in about 25-30 s without overshoot,
# where 0.3 took about 90 s. For a grid entity updating every second, a
# closed-loop simulation found 0.3 better: with 50/50/0.3, 50 W measurement
# noise, a 3 s inverter response and 2 s entity lag the grid held within
# ~70 W, while 0.5 started to hunt (±400 W).
DEFAULT_GRID_DEADBAND_W = 50.0
# Max charge/discharge power have no default: without a stored value they
# follow the maximum battery control power, like the charge/discharge rates.
DEFAULT_EXTERNAL_CONTROL_HYSTERESIS_W = 50.0
DEFAULT_EXTERNAL_CONTROL_EMA_ALPHA = 0.8
MIN_EXTERNAL_CONTROL_EMA_ALPHA = 0.05
# Grid control recalculates whenever the grid entity reports a new value, but
# at most once per GRID_CONTROL_MIN_UPDATE_SECONDS. The loop interval is the
# fallback for an entity that stops updating, and keeps the inverter's Modbus
# timeout from expiring.
GRID_CONTROL_MIN_UPDATE_SECONDS = 1.0
GRID_CONTROL_LOOP_INTERVAL = 5

# Predbat auto-detect
PREDBAT_MODE_ENTITY = "select.predbat_mode"
PREDBAT_ACTIVE_MODES = frozenset({
    "Control SOC only",
    "Control charge",
    "Control charge & discharge",
})
# Predbat charge-start hysteresis in percent points relative to
# predbat.best_charge_limit.
PREDBAT_CHARGE_START_DELTA = 1.0
PREDBAT_HOLD_DELTA = 1.0

# Grid connection point export threshold (Watts) that must be sustained for
# PREDBAT_LOW_POWER_SUSPEND_DELAY_SECONDS before the low-power charge loop
# stops writing the charge setpoint, letting the inverter's own timeout on
# the power setpoint expire and fall back to internal 0-export self-consumption
# control (which reacts faster than this integration's own loop).
PREDBAT_LOW_POWER_EXPORT_THRESHOLD_WATTS = 100.0
PREDBAT_LOW_POWER_SUSPEND_DELAY_SECONDS = 30.0

# Tolerance fraction subtracted from the low-power setpoint before comparing
# against measured battery charging power (register 582, DC) to decide whether
# to resume writes. The comparison is relative to the setpoint size, not a
# fixed Watt margin, or it would look "below target" and resume immediately
# after every suspend. On a hybrid inverter the DC setpoint 1034 is met within
# a few Watts; the BI's AC setpoint 1026 includes conversion loss, so it needs
# a wider margin.
PREDBAT_LOW_POWER_RESUME_TOLERANCE_FRACTION = 0.05
PREDBAT_LOW_POWER_RESUME_TOLERANCE_FRACTION_BI = 0.15

# Entity descriptions (Switches)
SWITCH_CHARGE_START = "charge_start"
SWITCH_DISCHARGE_START = "discharge_start"
SWITCH_BLOCK_CHARGE = "block_charge"
SWITCH_BLOCK_DISCHARGE = "block_discharge"
SWITCH_EMS = "ems_grid_protection"
SWITCH_AUTO_RESUME_ON_RECOVERY = "auto_resume_on_recovery"
SWITCH_INVERTER_CONTROL = "inverter_control"
SWITCH_IO_OUTPUT_1 = "io_output_1"
SWITCH_IO_OUTPUT_2 = "io_output_2"
SWITCH_IO_OUTPUT_3 = "io_output_3"
SWITCH_IO_OUTPUT_4 = "io_output_4"

# Entity descriptions (Numbers/Input Numbers)
NUMBER_CHARGE_RATE = "charge_rate"
NUMBER_DISCHARGE_RATE = "discharge_rate"
NUMBER_FUSE_SIZE = "fuse_size"
NUMBER_MIN_SOC_LIMIT = "min_soc_limit"
NUMBER_MAX_SOC_LIMIT = "max_soc_limit"

# Defaults
# Charge/discharge rates in Watts. A rate follows the maximum battery control
# power until the user sets a lower value. The fallback is only used while the
# maximum is still unknown (e.g. before the first poll); the inverter clamps an
# out-of-range setpoint itself.
POWER_RATE_STEP_W = 100.0
POWER_RATE_FALLBACK_MAX_W = 20000.0
DEFAULT_FUSE_SIZE = 25.0  # Amps — old Kostal default; user should set to actual value

# SOC limits. The bottom of the min range and the top of the max range are the
# inverter's own built-in limits, so those values mean "not in use": the value
# is written to register 1042/1044 once, so the release takes effect straight
# away, and nothing is sent afterwards. Any other value is written continuously
# for as long as it is set — see KostalSocLimitNumber in number.py.
MIN_SOC_LIMIT_RANGE = (5.0, 100.0)
MAX_SOC_LIMIT_RANGE = (5.0, 100.0)
DEFAULT_MIN_SOC_LIMIT = MIN_SOC_LIMIT_RANGE[0]
DEFAULT_MAX_SOC_LIMIT = MAX_SOC_LIMIT_RANGE[1]

# EMS settings
EMS_SAFETY_MARGIN = 0.90   # Trigger at 90% of fuse size
EMS_PHASE_VOLTAGE = 230.0  # Fallback phase voltage (V) when the smart meter reports none
