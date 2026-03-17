# Kostal Modbus Control for Home Assistant

This custom integration allows for advanced control of Kostal Plenticore inverters via Modbus TCP. It is specifically designed to control battery charging and discharging behavior "externally," allowing you to force charge from the grid or force discharge based on Home Assistant automations (e.g., electricity prices).

## Features

*   **External Battery Control:** Force charge or discharge your battery via Modbus.
*   **Safety Limits:** Automatically reads the battery's current maximum Charge/Discharge limits (Registers 1076/1078) and clamps user values to ensure safety.
*   **Mutually Exclusive Switches:** Smart logic ensures you cannot accidentally enable "Charge" and "Discharge" simultaneously.
*   **Status Monitoring:** Provides sensors for Battery SoC, Power, Voltage, Current, Temperature, and Dynamic Limits.
*   **Configurable Rates:** Set your desired Charge/Discharge wattage directly from Home Assistant.

## Prerequisites & Inverter Settings

**⚠️ IMPORTANT:** Before installing, you must configure your inverter correctly.

1.  Log in to your Kostal Inverter's Web UI (as **Installer/Parakou**).
2.  Navigate to **Settings** -> **Battery Management**.
3.  Change **Battery Management** to: **"External via protocol (Modbus TCP)"**.
4.  Note your **Modbus settings** (Registers 1502 and Unit ID 71 are defaults).
5.  Note the **Timeout** setting in the Web UI (default is often 30s or 60s). This must match the timeout configured in this integration.

## Installation

1.  Copy the `kostal_modbus` folder into your Home Assistant's `custom_components` directory.
2.  Restart Home Assistant.

## Configuration

1.  Go to **Settings** -> **Devices & Services**.
2.  Click **Add Integration**.
3.  Search for **"Kostal Modbus Control"**.
4.  Enter your inverter details:
    *   **Host:** IP address of the inverter.
    *   **Port:** Default 1502.
    *   **Unit ID:** Default 71.
    *   **Modbus Timeout:** Must match the timeout set in the Inverter Web UI (allows the integration to keep the session alive).

## Entities Explained

### Switches (Controls)

*   **Charge Start:** Forces the battery to charge from the grid at the rate defined in "Set Charge Rate".
*   **Discharge Start:** Forces the battery to discharge to the grid at the rate defined in "Set Discharge Rate".
*   **Block Charge:** Prevents the battery from charging (sets rate to 0).
*   **Block Discharge:** Prevents the battery from discharging (sets rate to 0).

*Note: These switches are mutually exclusive. Turning one ON will automatically turn the others OFF.*

### Numbers (Settings)

*   **Set Charge Rate:** Define the target power (Watts) for forced charging.
    *   *Smart Logic:* If you set this to 5000W, but the battery currently only accepts 3000W (due to temp/SoC), the integration will automatically limit the command to 3000W.
*   **Set Discharge Rate:** Define the target power (Watts) for forced discharging.

### Sensors (Read-Only)

*   **Battery SoC:** State of Charge (%).
*   **Battery Power:** Current input/output power (W).
*   **Battery Voltage:** (V).
*   **Battery Current:** (A).
*   **Battery Temperature:** (°C).
*   **Battery Max Charge Limit:** The dynamic maximum charge power the battery can accept right now.
*   **Battery Max Discharge Limit:** The dynamic maximum discharge power the battery can provide right now.

## Technical Details

*   **Control Register:** Uses `1034 (Active Power Control)` for enforcement of charge/discharge.
*   **Limit Registers:** Reads `1076` and `1078` to determine physical battery limits.
*   **Blocking:** Uses `1038` and `1040` (or 0W limits) to handle blocking states.
