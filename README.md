# Kostal Plenticore Battery Control for Home Assistant

This custom integration allows for advanced Battery control of Kostal Plenticore inverters via Modbus TCP. It is specifically designed to control battery charging and discharging behavior "externally," allowing you to force charge from the grid or force discharge based on Home Assistant automations (e.g., electricity prices).

## Features

*   **External Battery Control:** Force charge or discharge your battery via Modbus.
*   **Multiple Operating Modes:** Supports Normal control with KSEM, Single Inverter Grid Control, and HA Inverter Grid Control for 2 inverter setups.
*   **Safety Limits:** Automatically reads the battery's current maximum Charge/Discharge limits (Registers 1076/1078) and clamps user values to ensure safety.
*   **Mutually Exclusive Switches:** Smart logic ensures you cannot accidentally enable conflicting modes simultaneously.
*   **EMS Grid Protection:** Dynamic charge control that monitors all three grid phase currents and automatically reduces charge power to prevent fuses from tripping.
*   **2-Inverter Assist Logic:** In HA Inverter Grid Control mode, inverter 2 can share load based on inverter 1 SoC, battery power, and grid point data.
*   **Grid Fallback:** If inverter 1 is not in `FeedIn` state, inverter 2 can fall back to controlling from the grid point instead of waiting for inverter 1 power to recover.
*   **Smart Meter Detection:** EMS Protection can only be enabled when a supported smart meter is connected.
*   **Status Monitoring:** Provides sensors for Battery SoC, Power, Voltage, Temperature, Dynamic Limits, Grid Phase Currents, Smart Meter Type, and Inverter State.
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
    *   **Operating Mode:**
        *   **Normal (with KSEM):** Standard standalone operation with the local Kostal Smart Energy Meter.
        *   **HA Inverter Grid Control (2 inverter):** Lets inverter 2 follow Home Assistant source entities from inverter 1 and the grid point.
        *   **Single Inverter Grid Control:** Lets one inverter trim grid import/export directly from an external grid-power entity.

### 2-Inverter Mode Notes

In **HA Inverter Grid Control (2 inverter)** mode:

*   Mirror switch entities are optional. If they are left empty, inverter 2 uses its own local `Charge Start`, `Discharge Start`, `Block Charge`, and `Block Discharge` switches.
*   `Source SOC1`, `Source inverter 1 power`, and `Source grid power` are used for the sharing logic.
*   `Source inverter 1 status entity` is optional, but recommended. The best source is inverter 1's own `Inverter State` sensor from this integration.
*   Inverter 1 is only treated as active when its state is `FeedIn` (Modbus state `6`).
*   If inverter 1 leaves `FeedIn`, inverter 2 enters **Grid Fallback** and follows the grid point directly until inverter 1 returns to `FeedIn`.

### Control Tuning (Hysteresis)

The integration includes several hysteresis settings to avoid rapid power oscillation and unnecessary Modbus writes.

*   **External control hysteresis (W)**
    *   Used in **Single Inverter Grid Control** mode.
    *   Compares the newly calculated grid-support setpoint with the previous setpoint.
    *   A new value is only applied when the change exceeds this threshold.
    *   Higher value = fewer adjustments and smoother behavior, but slower reaction.
*   **Active mirrored hysteresis (W)**
    *   Used in **HA Inverter Grid Control (2 inverter)** mode when control is actively in `Charge` or `Discharge`.
    *   Prevents frequent small setpoint changes while following mirror/assist logic.
    *   Lower value = faster and tighter tracking, but potentially more frequent write updates.
*   **Idle assist hysteresis (W)**
    *   Used in **HA Inverter Grid Control (2 inverter)** mode while status is `Idle Assist`.
    *   Applies the same anti-chatter principle, but for idle balancing behavior.
    *   Higher value = calmer idle regulation with fewer small corrections.

Practical guidance:

*   If power jumps too often, increase the relevant hysteresis.
*   If control feels too slow to react, reduce the relevant hysteresis.
*   Tune one setting at a time and observe `Inverter Control Status` together with the resulting battery power.

### 2-Inverter Tuning Options (All Key Fields)

In **HA Inverter Grid Control (2 inverter)** mode, these settings define how inverter 2 assists inverter 1 and the grid point:

*   **Inverter 2 minimum SOC (%)**
    *   Lower SOC limit for inverter 2 in assist logic.
    *   Above this value, inverter 2 participates in shared discharge.
    *   At/below this value, inverter 2 discharge assist is reduced to protect SOC reserve.

*   **Inverter 1 SOC buffer (%)**
    *   SOC threshold used as reserve protection for inverter 1 when inverter 2 is near minimum SOC.
    *   Higher value keeps more reserve on inverter 1 before its share in discharge support becomes significant.

During shared discharge, the integration dynamically biases the inverter with the lower currently available discharge capacity so it can deplete first.

*   **Inverter 1 max power (W)**
    *   Estimated available inverter 1 power used in load-sharing calculations.
    *   This is not written to inverter 1; it is a modeling value for proportional split logic.
    *   Set this close to realistic inverter 1 battery power capability for best balancing.

*   **Active mirrored max power (W)**
    *   Maximum absolute assist power used when mirrored control is active (`Charge` or `Discharge`).
    *   Acts as a cap before conversion to battery percent setpoint.
    *   Higher value allows stronger response in active mirrored mode.

*   **Active mirrored hysteresis (W)**
    *   Hysteresis threshold while in active mirrored mode (`Charge` / `Discharge`).
    *   Reduces micro-adjustments and write chatter in active control.

*   **Idle assist max power (W)**
    *   Maximum absolute assist power while status is `Idle Assist`.
    *   Caps how much inverter 2 is allowed to charge/discharge when no forced mirror direction is active.
    *   A lower value gives gentler background balancing.

*   **Idle assist hysteresis (W)**
    *   Hysteresis threshold while in `Idle Assist`.
    *   Prevents frequent tiny setpoint changes around neutral operation.

Recommended tuning order:

1. Set realistic `Inverter 1 max power (W)`.
2. Set safety limits: `Inverter 2 minimum SOC (%)` and `Inverter 1 SOC buffer (%)`.
3. Tune response strength with `Active mirrored max power (W)` and `Idle assist max power (W)`.
4. Tune smoothness with `Active mirrored hysteresis (W)` and `Idle assist hysteresis (W)`.

## Entities Explained

### Switches (Controls)

*   **Charge Start:** Forces the battery to charge at the rate defined in "Set Charge Rate". Automatically respects the battery's physical charge limit.
*   **Discharge Start:** Forces the battery to discharge at the rate defined in "Set Discharge Rate". Automatically respects the battery's physical discharge limit.
*   **Block Charge:** Prevents the battery from charging (sets charge rate to 0). Restores the configured rate when turned off.
*   **Block Discharge:** Prevents the battery from discharging (sets discharge rate to 0). Restores the configured rate when turned off.
*   **Inverter Control:** Available in Single Inverter Grid Control and HA Inverter Grid Control modes. Runs the automatic grid-control logic for that mode.
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
| Inverter State | — | Current inverter state mapped from Modbus register 56 |
| EMS Grid Protection Status | — | Current state of the EMS Grid Protection function |
| Inverter Control Status | — | Current automatic control mode, including `Grid Fallback` when inverter 1 is not in `FeedIn` |

### KSEM Sensors (when KSEM is configured)

| Sensor | Unit | Description |
|---|---|---|
| Grid Power Total | W | Total grid power |
| Sum Output Inverter AC | W | Sum output inverter AC |
| Sum PV Power Inverter DC | W | Sum PV power inverter DC |
| Home Consumption | W | Total home consumption |
| Battery Charge / Discharge DC | W | Battery DC charge/discharge power |
| System State of Charge | % | System state of charge |
| Home Consumption from PV | W | Home consumption covered by PV |
| Home Consumption from Battery | W | Home consumption covered by battery |
| Home Consumption from Grid | W | Home consumption covered by grid |

**EMS Grid Protection Status** values:

| Status | Meaning |
|---|---|
| `inactive` | EMS switch is off — no active power control |
| `ok` | EMS is active — all phases are well within fuse limits, full charge rate applied |
| `protecting` | EMS is actively reducing charge power to keep phase currents below fuse limit |
| `blocked` | EMS has set charge to 0 W — phase current is already at the fuse limit without any charging |

**Inverter State** values:

| Code | State |
|---|---|
| `0` | Off |
| `1` | Init |
| `2` | IsoMeas |
| `3` | GridCheck |
| `4` | StartUp |
| `5` | Unknown-5 |
| `6` | FeedIn |
| `7` | Throttled |
| `8` | ExtSwitchOff |
| `9` | Update |
| `10` | Standby |
| `11` | GridSync |
| `12` | GridPreCheck |
| `13` | GridSwitchOff |
| `14` | Overheating |
| `15` | Shutdown |
| `16` | ImproperDcVoltage |
| `17` | ESB |
| `18` | Unknown |

In 2-inverter mode, only `FeedIn` (`6`) is treated as an active inverter 1 state for the purpose of load sharing. All other states cause inverter 2 to fall back to the grid point if a status entity is configured.

**Inverter Control Status** may show:

| Status | Meaning |
|---|---|
| `Grid Support` | Single-inverter grid control is trimming import/export from the grid point |
| `Grid Idle` | Single-inverter grid control is inside the configured deadband |
| `Idle Assist` | 2-inverter mode is active but not forcing charge/discharge |
| `Charge` / `Discharge` | 2-inverter mode is actively following the selected control direction |
| `Grid Fallback` | Inverter 1 is not in `FeedIn`, so inverter 2 is following the grid point directly |

## Technical Details

*   **Control Register:** `1034` — Active Power Control (negative = charge, positive = discharge).
*   **Limit Registers:** `1076` / `1078` — Physical battery charge/discharge limits.
*   **Block Registers:** `1038` / `1040` — Battery charge/discharge rate limits (set to 0 for blocking).
*   **Inverter State Register:** `56` — Inverter state2 as U32.
*   **Phase Current Registers:** `222` / `232` / `242` — Grid phase currents from smart meter.
*   **Sensor Type Register:** `1082` — Installed smart meter type.
*   **KSEM Power Registers:** `40972` / `40974` / `40976` / `40982` / `40984` — Additional KSEM power flow values.
*   **KSEM SoC Register:** `40986` — KSEM system state of charge.
*   **KSEM Home Consumption Registers:** `40988` / `40990` / `40992` — Home consumption split by source.
*   **Session keepalive:** Writes are sent at half the configured inverter timeout interval to prevent session expiry.
