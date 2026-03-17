"""Constants for the Kostal Modbus Control integration."""

DOMAIN = "kostal_modbus_control"
CONF_PORT = "port"
CONF_UNIT_ID = "unit_id"
CONF_MODBUS_TIMEOUT = "modbus_timeout"  # The configured timeout on the inverter

DEFAULT_PORT = 1502
DEFAULT_UNIT_ID = 71
DEFAULT_MODBUS_TIMEOUT = 30  # Default inverter timeout setting

# Modbus Registers (Holding Registers)
REG_MANUFACTURER = 535        # Inverter Manufacturer (String 16)
REG_MODEL = 768               # Productname (String 32)
REG_SERIAL = 559              # Inverter Serial Number (String 16)
REG_CHARGE_DISCHARGE_LIMIT = 1028 # Controls max charge/discharge power (%)
REG_POWER_LIMIT_W = 1034          # Power Limit (Watts) - Negative=Charge, Positive=Discharge
REG_CHARGE_RATE = 1038            # Battery Charge Rate (Watts) - Positive
REG_DISCHARGE_RATE = 1040         # Battery Discharge Rate (Watts) - Positive

# Read-Only Registers (Battery Data)
REG_BATTERY_SOC = 210             # Act. state of charge (%) - Float (0xD2)
REG_BATTERY_TEMP = 214            # Battery Temperature (°C) - Float (0xD6)
REG_BATTERY_VOLTAGE = 216         # Battery Voltage (V) - Float (0xD8)
REG_BATTERY_POWER = 582           # Actual battery charge/discharge power (W) - S16, negative=charge

# Read-Only Registers (Grid/Powermeter)
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

REG_BATTERY_MAX_CHARGE_LIMIT = 1076    # Max Charge Limit (W) - Float
REG_BATTERY_MAX_DISCHARGE_LIMIT = 1078 # Max Discharge Limit (W) - Float

# Entity descriptions (Sensors)
SENSOR_BATTERY_SOC = "battery_soc"
SENSOR_BATTERY_POWER = "battery_power"
SENSOR_BATTERY_VOLTAGE = "battery_voltage"
SENSOR_BATTERY_TEMP = "battery_temp"
SENSOR_BATTERY_MAX_CHARGE_LIMIT = "battery_max_charge_limit"
SENSOR_BATTERY_MAX_DISCHARGE_LIMIT = "battery_max_discharge_limit"
SENSOR_CURRENT_PHASE1 = "current_phase1"
SENSOR_CURRENT_PHASE2 = "current_phase2"
SENSOR_CURRENT_PHASE3 = "current_phase3"
SENSOR_SENSOR_TYPE = "sensor_type"
SENSOR_EMS_STATUS = "ems_status"

# Dispatcher signal for EMS status updates (append _{entry_id} when used)
SIGNAL_EMS_STATUS_UPDATED = "kostal_modbus_ems_status"

# Default loop interval in seconds (from automation: usually 15s)
LOOP_INTERVAL = 15

# Entity descriptions (Switches)
SWITCH_CHARGE_START = "charge_start"
SWITCH_DISCHARGE_START = "discharge_start"
SWITCH_BLOCK_CHARGE = "block_charge"
SWITCH_BLOCK_DISCHARGE = "block_discharge"
SWITCH_EMS = "ems_grid_protection"
SWITCH_PREDBAT_CONTROL = "predbat_control"

# Entity descriptions (Numbers/Input Numbers)
NUMBER_CHARGE_RATE = "charge_rate"
NUMBER_DISCHARGE_RATE = "discharge_rate"
NUMBER_FUSE_SIZE = "fuse_size"

# Defaults
DEFAULT_MAX_PERCENT = 100.0
DEFAULT_CHARGE_RATE = 5000.0
DEFAULT_DISCHARGE_RATE = 5000.0
DEFAULT_FUSE_SIZE = 25.0

# EMS settings
EMS_SAFETY_MARGIN = 0.90   # Trigger at 90% of fuse size
EMS_PHASE_VOLTAGE = 230.0  # Assumed phase voltage (V)
