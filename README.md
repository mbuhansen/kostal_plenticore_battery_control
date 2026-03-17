# Kostal Plenticore Battery Control for Home Assistant

This custom integration allows for advanced Battery control of Kostal Plenticore inverters via Modbus TCP. It is specifically designed to control battery charging and discharging behavior "externally," allowing you to force charge from the grid or force discharge based on Home Assistant automations (e.g., electricity prices).

## Features

*   **External Battery Control:** Force charge or discharge your battery via Modbus.
*   **Safety Limits:** Automatically reads the battery's current maximum Charge/Discharge limits (Registers 1076/1078) and clamps user values to ensure safety.
*   **Mutually Exclusive Switches:** Smart logic ensures you cannot accidentally enable conflicting modes simultaneously.
*   **EMS Grid Protection:** Dynamic charge control that monitors all three grid phase currents and automatically reduces charge power to prevent fuses from tripping.
*   **Smart Meter Detection:** EMS Protection can only be enabled when a supported smart meter is connected.
*   **Status Monitoring:** Provides sensors for Battery SoC, Power, Voltage, Temperature, Dynamic Limits, Grid Phase Currents, and Smart Meter Type.
*   **Configurable Rates:** Set your desired Charge/Discharge wattage directly from Home Assistant.

## Prerequisites & Inverter Settings

**⚠️ IMPORTANT:** Before installing, you must configure your inverter correctly.

1.  Log in to your Kostal Inverter's Web UI (as **Installer/Parakou**).
2.  Navigate to **Settings** -> **Battery Management**.
3.  Change **Battery Management** to: **"External via protocol (Modbus TCP)"**.
4.  Note the **Timeout** setting in the Web UI (default is often 30s or 60s). This must match the timeout configured in this integration.

> Port **1502** and Unit ID **71** are fixed and used automatically — no manual configuration needed.

## Installation

### HACS (Recommended)
1. Add this repository as a custom repository in HACS.
2. Install **Kostal Plenticore Battery Control**.
3. Restart Home Assistant.

### Manual
1.  Copy the `kostal_modbus_control` folder into your Home Assistant's `custom_components` directory.
2.  Restart Home Assistant.

## Configuration

1.  Go to **Settings** -> **Devices & Services**.
2.  Click **Add Integration**.
3.  Search for **"Kostal Plenticore Battery Control"**.
4.  Enter your inverter details:
    *   **Host:** IP address of the inverter.
    *   **Modbus Timeout:** Must match the timeout set in the Inverter Web UI — this keeps the Modbus session alive.

## Entities Explained

### Switches (Controls)

*   **Charge Start:** Forces the battery to charge at the rate defined in "Set Charge Rate". Automatically respects the battery's physical charge limit.
*   **Discharge Start:** Forces the battery to discharge at the rate defined in "Set Discharge Rate". Automatically respects the battery's physical discharge limit.
*   **Block Charge:** Prevents the battery from charging (sets charge rate to 0). Restores the configured rate when turned off.
*   **Block Discharge:** Prevents the battery from discharging (sets discharge rate to 0). Restores the configured rate when turned off.
*   **EMS Grid Protection:** Dynamically adjusts charge power every poll cycle to keep all three grid phase currents below the configured fuse size. See below for details.

*Note: All switches are mutually exclusive. Turning one ON will automatically turn the others OFF.*

### EMS Grid Protection

The EMS (Energy Management System) switch protects your house fuses during forced battery charging.

**How it works:**
- Every poll cycle it reads the current on all three grid phases from the smart meter.
- It calculates the available headroom per phase: `(fuse_size × 90%) - |phase_current|` converted to Watts at 230V.
- Charge power is set to the most constrained phase's headroom, capped by your configured "Set Charge Rate".
- If any phase is already at 90% of fuse capacity, charging is reduced accordingly. If headroom is zero or negative, charging stops (0W).

**Requirements:**
- A supported smart meter must be connected to the inverter (detected automatically via register 1082).
- If no smart meter is detected (`No sensor`), the EMS switch cannot be turned on.

**Supported smart meters:**
| Code | Meter |
|---|---|
| 0x00 | SDM 630 (B+G E-Tech GmbH) |
| 0x01 | B-Control EM-300 LR (TQ Systems) |
| 0x03 | KOSTAL Smart Energy Meter (KOSTAL) |
| 0xFF | No sensor |

### Numbers (Settings)

*   **Set Charge Rate:** Target power (W) for forced charging. Automatically clamped to the battery's physical limit.
*   **Set Discharge Rate:** Target power (W) for forced discharging. Automatically clamped to the battery's physical limit.
*   **House Fuse Size:** The size of your house fuses in Ampere (A). Used by EMS Grid Protection to calculate safe charge headroom.

### Sensors (Read-Only)

| Sensor | Unit | Description |
|---|---|---|
| Battery SoC | % | State of Charge |
| Battery Power | W | Charge/discharge power (negative = charging) |
| Battery Voltage | V | Battery terminal voltage |
| Battery Temperature | °C | Battery temperature |
| Battery Max Charge Limit | W | Dynamic maximum charge power from inverter |
| Battery Max Discharge Limit | W | Dynamic maximum discharge power from inverter |
| Grid Current Phase 1 | A | Phase 1 current at grid connection point |
| Grid Current Phase 2 | A | Phase 2 current at grid connection point |
| Grid Current Phase 3 | A | Phase 3 current at grid connection point |
| Smart Meter Type | — | Detected smart meter model or "No sensor" |

## Technical Details

*   **Control Register:** `1034` — Active Power Control (negative = charge, positive = discharge).
*   **Limit Registers:** `1076` / `1078` — Physical battery charge/discharge limits.
*   **Block Registers:** `1038` / `1040` — Battery charge/discharge rate limits (set to 0 for blocking).
*   **Phase Current Registers:** `222` / `232` / `242` — Grid phase currents from smart meter.
*   **Sensor Type Register:** `1082` — Installed smart meter type.
*   **Session keepalive:** Writes are sent at half the configured inverter timeout interval to prevent session expiry.
