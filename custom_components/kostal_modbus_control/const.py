"""Constants for the Kostal Modbus Control integration."""

DOMAIN = "kostal_modbus_control"
CONF_PORT = "port"
CONF_UNIT_ID = "unit_id"
CONF_MODBUS_TIMEOUT = "modbus_timeout"  # The configured timeout on the inverter
CONF_INVERTER_TYPE = "inverter_type"
CONF_OPERATING_MODE = "operating_mode"
INVERTER_TYPE_HYBRID = "hybrid"
INVERTER_TYPE_BI = "bi"
OPERATING_MODE_NORMAL = "normal"
OPERATING_MODE_HA_INVERTER_CONTROL = "ha_inverter_control"
OPERATING_MODE_EXTERNAL_GRID_CONTROL = "external_grid_control"
CONF_MIN_SOC = "min_soc"
CONF_MAX_SOC = "max_soc"
CONF_MASTER_CHARGE_START_ENTITY = "master_charge_start_entity"
CONF_MASTER_DISCHARGE_START_ENTITY = "master_discharge_start_entity"
CONF_MASTER_BLOCK_CHARGE_ENTITY = "master_block_charge_entity"
CONF_MASTER_BLOCK_DISCHARGE_ENTITY = "master_block_discharge_entity"
CONF_SOURCE_SOC1_ENTITY = "source_soc1_entity"
CONF_SOURCE_INV1_POWER_ENTITY = "source_inv1_power_entity"
CONF_SOURCE_GRID_POWER_ENTITY = "source_grid_power_entity"
CONF_GRID_TARGET_W = "grid_target_w"
CONF_GRID_DEADBAND_W = "grid_deadband_w"
CONF_EXTERNAL_CONTROL_MAX_DISCHARGE_W = "external_control_max_discharge_w"
CONF_EXTERNAL_CONTROL_MAX_CHARGE_W = "external_control_max_charge_w"
CONF_EXTERNAL_CONTROL_HYSTERESIS_W = "external_control_hysteresis_w"
CONF_EXTERNAL_CONTROL_EMA_ALPHA = "external_control_ema_alpha"
CONF_INV2_MIN_SOC = "inv2_min_soc"
CONF_INV1_SOC_BUFFER = "inv1_soc_buffer"
CONF_INV1_MAX_POWER_W = "inv1_max_power_w"
CONF_ACTIVE_MAX_POWER_W = "active_max_power_w"
CONF_ACTIVE_HYSTERESIS_W = "active_hysteresis_w"
CONF_IDLE_MAX_POWER_W = "idle_max_power_w"
CONF_IDLE_HYSTERESIS_W = "idle_hysteresis_w"

DEFAULT_PORT = 1502
DEFAULT_UNIT_ID = 71
DEFAULT_MODBUS_TIMEOUT = 30  # Default inverter timeout setting
DEFAULT_GRID_TARGET_W = 0.0
DEFAULT_GRID_DEADBAND_W = 150.0
DEFAULT_EXTERNAL_CONTROL_MAX_DISCHARGE_W = 5000.0
DEFAULT_EXTERNAL_CONTROL_MAX_CHARGE_W = 5000.0
DEFAULT_EXTERNAL_CONTROL_HYSTERESIS_W = 200.0
DEFAULT_EXTERNAL_CONTROL_EMA_ALPHA = 0.3
DEFAULT_INV2_MIN_SOC = 5.0
DEFAULT_INV1_SOC_BUFFER = 60.0
DEFAULT_INV1_MAX_POWER_W = 12000.0
DEFAULT_ACTIVE_MAX_POWER_W = 5000.0
DEFAULT_ACTIVE_HYSTERESIS_W = 100.0
DEFAULT_IDLE_MAX_POWER_W = 2000.0
DEFAULT_IDLE_HYSTERESIS_W = 300.0

# Modbus Registers (Holding Registers)
REG_MODBUS_BYTE_ORDER = 5        # Modbus byte order - U16 (0x05) 0=little-endian CDAB, 1=big-endian ABCD
REG_MANUFACTURER = 535        # Inverter Manufacturer (String 16)
REG_MODEL = 768               # Productname (String 32)
REG_POWER_CLASS = 800         # Power class e.g. "10" (String 32)
REG_SERIAL = 559              # Inverter Serial Number (String 16)
REG_INVERTER_STATE = 56       # Inverter state - U32 (0x38)
REG_CHARGE_DISCHARGE_LIMIT = 1028      # Hybrid: Controls max charge/discharge power (%)
REG_CHARGE_DISCHARGE_LIMIT_BI = 1030   # BI: Controls max charge/discharge power (%)
REG_POWER_LIMIT_W = 1034               # Power Limit (Watts) - Negative=Charge, Positive=Discharge
REG_CHARGE_RATE = 1038            # Battery Charge Rate (Watts) - Positive
REG_DISCHARGE_RATE = 1040         # Battery Discharge Rate (Watts) - Positive
REG_BATTERY_MIN_SOC = 1042        # Minimum SOC % - Float (0x412) RW
REG_BATTERY_MAX_SOC = 1044        # Maximum SOC % - Float (0x414) RW

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

REG_BATTERY_MAX_CHARGE_LIMIT = 1076    # Max Charge Limit (W) - Float
REG_BATTERY_MAX_DISCHARGE_LIMIT = 1078 # Max Discharge Limit (W) - Float
REG_BATTERY_WORK_CAPACITY = 1068       # Battery work capacity (Wh) - Float
REG_BATTERY_MGMT_MODE = 1080          # Battery management mode - U8

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
SENSOR_EMS_CHARGE_LIMIT = "ems_charge_limit"
SENSOR_PREDBAT_STATUS = "predbat_status"
SENSOR_PREDBAT_MODE = "predbat_mode"
SENSOR_BATTERY_CHARGE_CURRENT_SETPOINT = "battery_charge_current_setpoint"
SENSOR_BATTERY_CHARGE_POWER_SETPOINT = "battery_charge_power_setpoint"
SENSOR_BATTERY_MAX_CHARGE_POWER_LIMIT = "battery_max_charge_power_limit"
SENSOR_BATTERY_MAX_DISCHARGE_POWER_LIMIT = "battery_max_discharge_power_limit"
SENSOR_BATTERY_WORK_CAPACITY = "battery_work_capacity"
SENSOR_BATTERY_MGMT_MODE = "battery_mgmt_mode"
SENSOR_BATTERY_TYPE = "battery_type"
SENSOR_BATTERY_FIRMWARE = "battery_firmware"
SENSOR_BATTERY_BMS_SERIAL = "battery_bms_serial"
SENSOR_BATTERY_MODEL_ID = "battery_model_id"
SENSOR_BATTERY_GROSS_CAPACITY = "battery_gross_capacity"
SENSOR_BATTERY_CYCLES = "battery_cycles"
SENSOR_BATTERY_CURRENT = "battery_current"
SENSOR_BATTERY_MIN_SOC = "battery_min_soc"
SENSOR_BATTERY_MAX_SOC = "battery_max_soc"
SENSOR_INVERTER_STATE = "inverter_state"
SENSOR_INVERTER_STATE_TEXT = "inverter_state_text"
SENSOR_INVERTER_CONTROL_STATUS = "inverter_control_status"
SENSOR_INVERTER_CONTROL_TARGET_POWER = "inverter_control_target_power"
SENSOR_INVERTER_CONTROL_TARGET_PERCENT = "inverter_control_target_percent"
SENSOR_INVERTER_CONTROL_HOUSE_LOAD = "inverter_control_house_load"

# KSEM (KOSTAL Smart Energy Meter) Modbus configuration
CONF_KSEM_HOST = "ksem_host"
KSEM_PORT = 502
KSEM_SLAVE_ID = 1
KSEM_SCALE = 0.0001                   # int64 raw → kWh
REG_KSEM_ENERGY_IMPORTED = 512        # Consumption from grid (int64)
REG_KSEM_ENERGY_EXPORTED = 516        # Feed-in to grid (int64)
SENSOR_KSEM_ENERGY_IMPORTED = "ksem_energy_imported"
SENSOR_KSEM_ENERGY_EXPORTED = "ksem_energy_exported"

# Dispatcher signal for EMS status updates (append _{entry_id} when used)
SIGNAL_EMS_STATUS_UPDATED = "kostal_modbus_ems_status"
SIGNAL_PREDBAT_STATUS_UPDATED = "kostal_modbus_predbat_status"
SIGNAL_INVERTER_CONTROL_UPDATED = "kostal_modbus_inverter_control"

# Default loop interval in seconds (from automation: usually 15s)
LOOP_INTERVAL = 15

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

# Defaults
DEFAULT_MAX_PERCENT = 100.0
DEFAULT_CHARGE_RATE = 100.0
DEFAULT_DISCHARGE_RATE = 100.0
DEFAULT_FUSE_SIZE = 25.0  # Amps — old Kostal default; user should set to actual value

# EMS settings
EMS_SAFETY_MARGIN = 0.90   # Trigger at 90% of fuse size
EMS_PHASE_VOLTAGE = 230.0  # Assumed phase voltage (V)
