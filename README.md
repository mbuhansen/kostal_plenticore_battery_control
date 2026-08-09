# Kostal Plenticore Battery Control for Home Assistant

This custom integration allows for advanced Battery control of Kostal Plenticore inverters via Modbus TCP. It is specifically designed to control battery charging and discharging behavior "externally," allowing you to force charge from the grid or force discharge based on Home Assistant automations (e.g., electricity prices).

## Features

*   **External Battery Control:** Force charge or discharge your battery via Modbus.
*   **Predbat Integration:** When [Predbat](https://springfall2008.github.io/batpred/) is installed and in an active control mode, `Charge Start` follows `predbat.best_charge_limit` and switches between charging, holding the SoC, and releasing the inverter automatically.
*   **Battery SOC Limits:** Minimum and maximum SOC entities that only send to the inverter once the battery actually approaches the limit.
*   **Safety Limits:** Automatically reads the battery's current maximum Charge/Discharge limits (Registers 1076/1078) and clamps user values to ensure safety.
*   **Mutually Exclusive Switches:** Smart logic ensures you cannot accidentally enable conflicting modes simultaneously.
*   **Automatic Resume:** If Modbus communication drops while a control switch is on, the switch pauses instead of turning off and resumes by itself once the inverter is reachable again.
*   **EMS Grid Protection:** Dynamic charge control that monitors all three grid phase currents and automatically reduces charge power to prevent fuses from tripping.
*   **Smart Meter Detection:** EMS Protection can only be enabled when a supported smart meter is connected.
*   **KSEM Support:** Optional direct Modbus connection to a KOSTAL Smart Energy Meter for energy and power-flow sensors.
*   **I/O Board Outputs:** Direct control of the inverter's four switched outputs.
*   **Configurable Rates:** Set your desired Charge/Discharge wattage directly from Home Assistant.

## Prerequisites & Inverter Settings

**⚠️ IMPORTANT:** Before installing, you must configure your inverter correctly.

1.  Log in to your Kostal Inverter's Web UI (as **Installer/Parakou**).
2.  Navigate to **Settings** -> **Battery Management**.
3.  Change **Battery Management** to: **"External via protocol (Modbus TCP)"**.
4.  Note the **Timeout** setting in the Web UI (default is often 30s or 60s). This must match the timeout configured in this integration.

Step 3 is not optional. The inverter reports its battery management mode in register `1080`:

| Value | Mode | Accepts commands from this integration? |
|---|---|---|
| `0x00` | No external battery management | No |
| `0x01` | External battery management via digital I/O | No |
| `0x02` | External battery management via Modbus protocol | **Yes** |

In the first two modes the inverter **silently ignores** every write — the switches turn on, no error appears anywhere, and the battery simply does nothing. Setup reads register `1080` and shows a warning screen if it is not `0x02`, but lets you continue anyway so you can fix the inverter setting afterwards. The `Battery Management Mode` diagnostic sensor shows the current mode at any time.

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
    *   **Inverter Type:**
        *   **Plenticore Hybrid** — charge/discharge power is controlled through register `1028`.
        *   **Plenticore BI / Battery Inverter** — charge/discharge power is controlled through register `1030`.
5.  If battery management is not set to Modbus, a warning screen appears explaining what to change in the Inverter Web UI. Setup continues when you submit it.
6.  If the inverter reports a **KOSTAL Smart Energy Meter** as its connected meter (sensor type `0x03`), a second step offers to add the KSEM's IP address. This is optional — leave it empty to skip. With it configured, the integration opens a second Modbus connection to the KSEM (port `502`, unit ID `1`) and adds the energy and power-flow sensors listed below.

There are no options to configure after setup; everything else is controlled through entities.

## Entities Explained

### Switches (Controls)

*   **Charge Start:** Forces the battery to charge at the rate defined in "Set Charge Rate". Automatically respects the battery's physical charge limit. If Predbat is active this switch runs the Predbat control logic instead — see below.
*   **Discharge Start:** Forces the battery to discharge at the rate defined in "Set Discharge Rate". Automatically respects the battery's physical discharge limit.
*   **Block Charge:** Prevents the battery from charging (sets charge rate to 0). Restores the configured rate when turned off.
*   **Block Discharge:** Prevents the battery from discharging (sets discharge rate to 0). Restores the configured rate when turned off.

*Note: These four switches are mutually exclusive. Turning one ON will automatically turn the others OFF.*

*   **EMS Grid Protection** *(Configuration category)*: Dynamically adjusts charge power every poll cycle to keep all three grid phase currents below the configured fuse size. See below for details.
*   **I/O Output 1–4** *(disabled by default)*: Direct on/off control of the inverter's I/O board outputs (registers `608`–`611`). Writes `1` when turned on and `0` when turned off, and restores its last state after a Home Assistant restart.

Each control switch exposes `faulted`, `resume_pending`, `loop_running` and `auto_resume_enabled` as attributes, which is the quickest way to see what a switch is doing.

### Automatic Resume After Communication Loss

While a control switch is on, the integration keeps writing to the inverter at half the configured Modbus timeout to hold the session open. If a write fails, `Charge Start`, `Discharge Start`, `Block Charge` and `Block Discharge` do **not** turn themselves off. Instead they:

1.  Stop the write loop and mark themselves `faulted`, with `resume_pending` set.
2.  Close the Modbus connection so the next attempt reconnects cleanly.
3.  Wait for the coordinator to reach the inverter again, then automatically restart the loop and clear the fault.

The restart honours the same settling delay as a manual start (`Modbus timeout + 15s` since the last stop), so the inverter is never written to while it is still falling back to internal control.

### Predbat Control

If [Predbat](https://springfall2008.github.io/batpred/) is installed, the `Charge Start` switch changes behaviour. Predbat is considered active when `select.predbat_mode` exists and is set to `Control SOC only`, `Control charge`, or `Control charge & discharge`. The `Predbat Mode` sensor shows whether this is the case.

While active, `Charge Start` compares the battery SoC against `predbat.best_charge_limit` on every poll:

*   **Charge** — the SoC is at or below `best_charge_limit - 2%`, so the inverter is told to charge at "Set Charge Rate".
*   **Hold** — the SoC is above the start threshold. The charge setpoint is released and, after a 45 second settling wait, discharge is blocked while the SoC is at or below `best_charge_limit + 1%`, keeping the battery where Predbat wants it.
*   Above `best_charge_limit + 1%` the inverter is released completely and discharges freely again.

The 2-point start band and the 1-point hold band (`PREDBAT_CHARGE_START_DELTA` and `PREDBAT_HOLD_DELTA` in `const.py`) form a 3-point hysteresis window, so the switch does not flip between charging and holding on every poll.

Two Predbat features are followed automatically:

*   **Hold for car** — when `predbat.status` contains `Hold for car` without an active charge window, the decision is forced to hold so the battery does not discharge into the car charger.
*   **Low power charging** — when `switch.predbat_set_charge_low_power` is on, the charge rate is capped to `input_number.predbat_charge_rate` converted to a percentage of the battery's maximum charge power. If the house then exports at least 100W to the grid for 30 seconds straight, the charge setpoint writes are suspended entirely, letting the inverter's own faster zero-export regulation take over. Writes resume as soon as the measured battery charging power falls more than 15% below the low-power setpoint, for example when PV production fades.

### EMS Grid Protection

The EMS (Energy Management System) switch protects your house fuses during forced battery charging.

**How it works:**
- Every poll cycle it reads the current on all three grid phases from the smart meter.
- It calculates the available headroom per phase: `(fuse_size × 90%) - |phase_current|` converted to Watts at 230V.
- Charge power is set to the most constrained phase's headroom, capped by your configured "Set Charge Rate".
- If any phase is already at 90% of fuse capacity, charging is reduced accordingly. If headroom is zero or negative, charging stops (0W).
- The computed limit is smoothed with an exponential moving average so it does not jump on a single noisy reading.

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
*   **House Fuse Size** *(Configuration category)*: The size of your house fuses in Ampere (A). Used by EMS Grid Protection to calculate safe charge headroom.
*   **Battery Minimum SOC Limit** *(disabled by default)*: 5–99%. `5` means not in use — that is the inverter's own minimum.
*   **Battery Maximum SOC Limit** *(disabled by default)*: 50–100%. `100` means not in use — that is the inverter's own maximum.

Both SOC limits are disabled in the entity registry out of the box; enable them on the device page to use them.

### Battery SOC Limits

Registers `1042`/`1044` are governed by the inverter's Modbus timeout: a limit is only in effect while
it is actively being sent, and the inverter reverts to its own settings (minimum 5%, maximum 100%) as
soon as the writes stop. The limits are therefore **not** written as soon as you set them — a limit
*arms* 2 percentage points before the battery reaches it, so the inverter stays on its own control the
rest of the time:

*   **Maximum SOC** — with the limit at 90%, nothing is sent until the SoC reaches **88%**. From there
    register `1044` is written repeatedly (every `inverter timeout / 2` seconds, minimum 5s — the same
    cadence as the charge/discharge loops). The writes stop again when the SoC falls back below 88%.
*   **Minimum SOC** — mirrored: with the limit at 20%, register `1042` starts being written once the
    SoC drops to **22%**, and the writes stop once it rises back above 22%.

The 2-point lead is `SOC_LIMIT_ARM_MARGIN` in `const.py`. It exists because arming is only re-evaluated
once per coordinator poll (15s), so the limit needs to be in place at the inverter slightly before the
battery arrives at it. It doubles as the release band, which keeps the writes from flapping on and off
around the limit. Each limit entity exposes the resulting threshold as an `arms_at` attribute.

No release value is ever written — the inverter's own timeout handles that. Measured on a Plenticore:
writing `85` to the maximum SOC while the battery sat at 87% stopped charging right away, and the
register went back to `100` by itself once the writes stopped. Sending the limits does not interfere
with the charge/discharge switches handing control back to the inverter afterwards.

Should the SoC still drift past the limit before a write lands, that is harmless: the inverter accepts
a limit below the current SoC and stops charging immediately.

The `Battery Minimum SOC` / `Battery Maximum SOC` diagnostic sensors read the registers back if you
want to watch this happen. Each limit entity also exposes an `armed` attribute.

### Sensors (Read-Only)

| Sensor | Unit | Description |
|---|---|---|
| Battery SoC | % | State of Charge |
| Battery Power | W | Charge/discharge power (negative = charging) |
| Battery Voltage | V | Battery terminal voltage |
| Battery Temperature | °C | Battery temperature |
| Battery Max Charge Power Limit Read-out | W | Dynamic maximum charge power from inverter |
| Battery Max Discharge Power Limit Read-out | W | Dynamic maximum discharge power from inverter |
| Grid Power | W | Grid power from the powermeter |
| Grid Current Phase 1–3 | A | Phase currents at the grid connection point |
| Smart Meter Type | — | Detected smart meter model or "No sensor" |
| Battery Type | — | Detected battery manufacturer/type |
| Battery Model ID Text | — | Decoded battery model name |
| EMS Grid Protection Status | — | Current state of the EMS Grid Protection function |
| EMS Charge Limit | % | Charge limit currently computed by EMS Grid Protection |
| Predbat Status | — | What Predbat control is currently doing |
| Predbat Mode | — | Whether Predbat is installed and in an active control mode |

### Diagnostic Sensors (disabled by default)

Enable these on the device page when you need them:

| Sensor | Unit | Description |
|---|---|---|
| Inverter State / Inverter State Text | — | Inverter state from register 56, numeric and mapped |
| Grid Voltage Phase 1–3 | V | Phase voltages from the powermeter |
| Battery Current | A | Battery charge (−) / discharge (+) current |
| Battery Cycles | — | Number of battery cycles |
| Battery Work Capacity | Wh | Usable battery capacity |
| Battery Gross Capacity | Ah | Gross battery capacity |
| Battery Management Mode | — | Register 1080 mapped to text — must be "External battery management via Modbus protocol" for control to work |
| Battery Firmware | — | Battery firmware version |
| Battery BMS Serial Number | — | Battery BMS serial |
| Battery Model ID | — | Raw battery model ID |
| Battery Minimum SOC / Battery Maximum SOC | % | Read-back of registers 1042 / 1044 |
| Battery Charge Current / Power Setpoint | A / W | Current setpoint, depending on inverter type |
| Battery Max Charge / Discharge Power Setpoint | W | Configured maximum setpoints |

### KSEM Sensors (when KSEM is configured)

| Sensor | Unit | Description |
|---|---|---|
| Grid Energy Imported | kWh | Total energy imported from the grid |
| Grid Energy Exported | kWh | Total energy exported to the grid |
| Grid Power Total | W | Total grid power |
| Sum Output Inverter AC | W | Sum output inverter AC |
| Sum PV Power Inverter DC | W | Sum PV power inverter DC |
| Home Consumption | W | Total home consumption |
| Battery Charge / Discharge DC | W | Battery DC charge/discharge power |
| System State of Charge | % | System state of charge |
| Home Consumption from PV | W | Home consumption covered by PV |
| Home Consumption from Battery | W | Home consumption covered by battery |
| Home Consumption from Grid | W | Home consumption covered by grid |

KSEM sensors are grouped under their own device, separate from the inverter.

**EMS Grid Protection Status** values:

| Status | Meaning |
|---|---|
| `Inactive` | EMS switch is off — no active power control |
| `Ok` | EMS is active — all phases are well within fuse limits, full charge rate applied |
| `Protecting` | EMS is actively reducing charge power to keep phase currents below fuse limit |
| `Blocked` | EMS has set charge to 0 W — phase current is already at the fuse limit without any charging |

**Predbat Status** values:

| Status | Meaning |
|---|---|
| `Inactive` | Charge Start is off, or Predbat is not in an active control mode |
| `Waiting` | Settling after a charge stop, or the SoC / `best_charge_limit` reading is not available yet |
| `Charge` | SoC is below the start threshold — the inverter is being told to charge |
| `Hold` | SoC is at the target — discharge is blocked to hold it there |
| `Hold for car` | Predbat reported `Hold for car`, so discharge is blocked while the car charges |
| `Low Power Suspended` | Low-power charging is capped and the house is exporting, so the setpoint writes are paused |

**Predbat Mode** values: `Not installed`, `Disabled`, `Enabled`.

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

## Technical Details

*   **Control Register:** `1028` (Hybrid) / `1030` (BI) — charge/discharge power as a signed percentage (negative = charge, positive = discharge). Selected by the inverter type chosen during setup.
*   **Limit Registers:** `1076` / `1078` — Physical battery charge/discharge limits.
*   **Block Registers:** `1038` / `1040` — Battery charge/discharge rate limits (set to 0 for blocking).
*   **SOC Limit Registers:** `1042` / `1044` — Minimum/maximum SOC. Only in effect while actively written.
*   **I/O Output Registers:** `608` / `609` / `610` / `611` — I/O board switched outputs.
*   **Inverter State Register:** `56` — Inverter state2 as U32. Follows the inverter's Modbus byte-order setting (register `5`), like the float registers do.
*   **Battery Info Registers:** `512` / `525` / `527` / `586` — Gross capacity, model ID, BMS serial and firmware. These U32 values are always big-endian (most significant word first) even when the byte-order setting is little-endian (CDAB), so they are read without the word swap the other 32-bit values need. Firmware is packed as major byte then minor byte, so `794` (`0x031A`) is reported as `3.26`. Gross capacity is stored under its own coordinator key because register `512` is also the KSEM's imported-energy register.
*   **Phase Current Registers:** `222` / `232` / `242` — Grid phase currents from smart meter.
*   **Sensor Type Register:** `1082` — Installed smart meter type. Read once during setup to detect a KSEM, and on every poll for the EMS switch.
*   **Battery Management Register:** `1080` — Battery management mode. Read during setup to warn when it is not `0x02` (Modbus).
*   **KSEM Power Registers:** `40972` / `40974` / `40976` / `40982` / `40984` — Additional KSEM power flow values.
*   **KSEM SoC Register:** `40986` — KSEM system state of charge.
*   **KSEM Home Consumption Registers:** `40988` / `40990` / `40992` — Home consumption split by source.
*   **Polling:** All registers are read in a single coordinator cycle every 15 seconds.
*   **Session keepalive:** Writes are sent at half the configured inverter timeout interval (minimum 5s) to prevent session expiry.
