# Kostal Plenticore Battery Control for Home Assistant

This custom integration allows for advanced Battery control of Kostal Plenticore inverters via Modbus TCP. It is specifically designed to control battery charging and discharging behavior "externally," allowing you to force charge from the grid or force discharge based on Home Assistant automations (e.g., electricity prices).

## Features

*   **External Battery Control:** Force charge or discharge your battery via Modbus.
*   **Predbat Integration:** When [Predbat](https://springfall2008.github.io/batpred/) is installed and in an active control mode, `Charge Start` follows `predbat.best_charge_limit` and switches between charging, holding the SoC, and releasing the inverter automatically.
*   **Battery SOC Limits:** Minimum and maximum SOC entities that hold the limit at the inverter for as long as it is set — cap the battery at 50% while you are away, or stop charging in the morning and raise the limit again later in the day.
*   **Control in Watts:** Charge and discharge power is sent to the inverter as an absolute setpoint in Watts, clamped to the maximum battery control power, which is derived from the battery voltage and the inverter's nominal battery current.
*   **Mutually Exclusive Switches:** Smart logic ensures you cannot accidentally enable conflicting modes simultaneously.
*   **Automatic Resume:** If Modbus communication drops while a control switch is on, the switch pauses instead of turning off and resumes by itself once the inverter is reachable again.
*   **EMS Grid Protection:** Dynamic charge control that monitors all three grid phase currents and automatically reduces charge power to prevent fuses from tripping.
*   **Smart Meter Detection:** EMS Protection can only be enabled when a supported smart meter is connected.
*   **Grid Control Without a Smart Meter:** Pick any Home Assistant grid-power entity and the battery charges or discharges to keep grid import/export near a target.
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
        *   **Plenticore Hybrid** — charge/discharge power is controlled through register `1034` (battery DC power setpoint in W).
        *   **Plenticore BI / Battery Inverter** — charge/discharge power is controlled through register `1026` (battery AC power setpoint in W). Not yet tested on a BI.
5.  If battery management is not set to Modbus, a warning screen appears explaining what to change in the Inverter Web UI. Setup continues when you submit it.
6.  If the inverter reports a **KOSTAL Smart Energy Meter** as its connected meter (sensor type `0x03`), a second step offers to add the KSEM's IP address. This is optional — leave it empty to skip. With it configured, the integration opens a second Modbus connection to the KSEM (port `502`, unit ID `1`) and adds the energy and power-flow sensors listed below.
7.  If the inverter reports **no smart meter** (sensor type `0xFF`, or the register cannot be read), a step offers to pick a Home Assistant **grid power entity** instead. This is optional — leave it empty to skip, and the charge/discharge switches work as usual. See [Grid Control Without a Smart Meter](#grid-control-without-a-smart-meter).

After setup, **Configure** on the integration holds the grid control options: the grid power entity and its tuning values. Everything else is controlled through entities.

## Entities Explained

### Switches (Controls)

*   **Charge Start:** Forces the battery to charge at the power defined in "Set Charge Rate", clamped to the maximum battery control power. If Predbat is active this switch runs the Predbat control logic instead — see below.
*   **Discharge Start:** Forces the battery to discharge at the power defined in "Set Discharge Rate", clamped to the maximum battery control power.
*   **Block Charge:** Prevents the battery from charging (sets charge rate to 0). Restores the configured rate when turned off.
*   **Block Discharge:** Prevents the battery from discharging (sets discharge rate to 0). Restores the configured rate when turned off.

*   **Inverter Control** *(only while a grid power entity is configured)*: Trims grid import/export from the external grid entity. See [Grid Control Without a Smart Meter](#grid-control-without-a-smart-meter).

*Note: These switches are mutually exclusive. Turning one ON will automatically turn the others OFF.*

*   **EMS Grid Protection** *(Configuration category)*: Dynamically adjusts charge power every poll cycle to keep all three grid phase currents below the configured fuse size. See below for details.
*   **I/O Output 1–4** *(disabled by default)*: Direct on/off control of the inverter's I/O board outputs (registers `608`–`611`). Writes `1` when turned on and `0` when turned off, and restores its last state after a Home Assistant restart.

Each control switch exposes `faulted`, `resume_pending`, `loop_running` and `auto_resume_enabled` as attributes, which is the quickest way to see what a switch is doing.

### Automatic Resume After Communication Loss

While a control switch is on, the integration keeps writing to the inverter at half the configured Modbus timeout to hold the session open. If a write fails, `Charge Start`, `Discharge Start`, `Block Charge`, `Block Discharge` and `Inverter Control` do **not** turn themselves off. Instead they:

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

The 1-point start band and the 1-point hold band (`PREDBAT_CHARGE_START_DELTA` and `PREDBAT_HOLD_DELTA` in `const.py`) form a 2-point hysteresis window, so the switch does not flip between charging and holding on every poll.

Two Predbat features are followed automatically:

*   **Hold for car** — when `predbat.status` contains `Hold for car` without an active charge window, the decision is forced to hold so the battery does not discharge into the car charger.
*   **Low power charging** — when `switch.predbat_set_charge_low_power` is on, the charge power is capped to `input_number.predbat_charge_rate`, which is used directly in Watts. If the house then exports at least 100W to the grid for 30 seconds straight, the charge setpoint writes are suspended entirely, letting the inverter's own faster zero-export regulation take over. Writes resume as soon as the measured battery charging power falls more than 5% below the low-power setpoint (15% on a BI, whose AC setpoint includes conversion loss), for example when PV production fades.

### EMS Grid Protection

The EMS (Energy Management System) switch protects your house fuses during forced battery charging.

**How it works:**
- Every poll cycle it reads the current on all three grid phases from the smart meter.
- It calculates the available headroom per phase: `(fuse_size × 90%) - |phase_current|` converted to Watts at that phase's measured voltage (230V when the meter reports none).
- Charge power is set to the most constrained phase's headroom, capped by your configured "Set Charge Rate". The limit is shown in Watts by the `EMS Charge Limit` sensor.
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

### Grid Control Without a Smart Meter

Without a smart meter the inverter cannot see grid import and export, so its own self-consumption control does not work. The **Inverter Control** switch fills that gap using a grid power entity you already have in Home Assistant, for example from a P1 reader, a Shelly EM or your utility meter.

**Requirements:**
- A Home Assistant `sensor`, `number` or `input_number` measuring grid power in **W** at the connection point: **positive while importing, negative while exporting**. If yours is the other way round, wrap it in a template sensor that inverts the sign.
- Set during setup when no smart meter is detected, or at any time under **Configure**. With a smart meter connected the option is still available for testing, and the form shows a note.

**How it works** (while the switch is on):
- The setpoint is recalculated every time the grid entity reports a new value, at most once per second. How fast the control can react therefore depends on how often your grid entity updates. Every 5 seconds the last setpoint is written again to keep the inverter's Modbus timeout from expiring, but it is only recalculated when the entity has reported a new measurement — an old grid reading next to a fresh battery power would count the battery's latest change twice and make it overshoot.
- Smoothing is applied once per grid reading, so the right **Load smoothing** depends on how often your grid entity updates — see below.
- Each calculation reads the battery power (register `582`) directly from the inverter, so the grid reading and the battery reading are from the same moment.
- The grid reading plus the battery power gives the house load the battery has to cover. PV surplus makes it negative. This load is smoothed with an exponential moving average.
- The battery setpoint is the smoothed load minus **Grid target**: a positive load → discharge, a negative load (surplus) → charge.
- While the grid is within **Grid deadband** of the target, the battery keeps its current setpoint (`Grid Idle`).
- The setpoint is capped by **Max discharge / Max charge power** and by the maximum battery control power, then written in Watts to the power setpoint register (`1034` on a hybrid, `1026` on a BI).
- The written setpoint only changes when the new value differs by more than **Setpoint hysteresis**, so the inverter is not chased by small fluctuations.
- If the grid entity or the battery data is unavailable, `0` is written and the status is `Unavailable`.
- When the switch is turned off, `0` is written and the inverter falls back to its internal control after its Modbus timeout.

**Options:**
| Option | Default | Description |
|---|---|---|
| Grid power entity | — | Source of the grid measurement. Clearing it removes the switch and its sensors. |
| Grid target | 0 W | Grid power to regulate towards. |
| Grid deadband | 50 W | The setpoint is held while the grid is within this distance of the target. |
| Max discharge power | Battery maximum | Upper limit for discharging. The form is pre-filled with the maximum battery control power (11900 W on a PLENTICORE G3). Save that value, anything above it, or a blank field and the limit follows the battery maximum; save a lower value and that value is used. |
| Max charge power | Battery maximum | Upper limit for charging, same as above. |
| Setpoint hysteresis | 50 W | Minimum change before a new setpoint is used. |
| Load smoothing | 0.8 | EMA alpha per grid reading, 0.05–1: `1` = raw value, lower = smoother but slower. |

**Choosing Load smoothing:** smoothing is applied once per grid reading, so a slow grid entity is smoothed much more in time than a fast one.
- **Grid entity updating every 5–10 seconds** (e.g. the Kostal Plenticore integration): keep the default `0.8`. Tested on a PLENTICORE G3 with an entity updating every 8–10 s, a 2–2.5 kW load step was settled within ±50 W after about 25–30 seconds without overshoot. With `0.3` the same step took about 90 seconds.
- **Grid entity updating every 1–2 seconds** (e.g. a P1 reader or Shelly EM): lower it to about `0.3`. A fast, noisy measurement with a high value makes the battery setpoint hunt back and forth; in a simulation with a 1 s entity, `0.3` held the grid within about 70 W, while `0.5` already started to swing by ±400 W.

Existing installations keep the value they saved; set it again under **Configure** to use the new default.

Deadband, hysteresis and smoothing work together: the grid settles within roughly the larger of deadband and hysteresis. Going much below 50 W, or raising smoothing to `1` on a noisy grid entity, makes the battery setpoint hunt back and forth.

**Diagnostic sensors:**
| Sensor | Description |
|---|---|
| Inverter Control Status | `Inactive`, `Grid Support`, `Grid Idle` or `Unavailable` |
| Inverter Control Target Power | Current battery setpoint in W (+ discharge, − charge), as written to the register |
| Inverter Control House Load | The smoothed house load (grid + battery) the control regulates on |

### Numbers (Settings)

*   **Set Charge Rate / Set Discharge Rate:** Target power in Watts for forced charging and discharging. A rate starts out following the maximum battery control power (the `Battery Max Control Power` sensor) rounded up to the next 100 W — 11900 W on a PLENTICORE G3, i.e. 30 A times the battery's maximum voltage of 395 V. It does not move with the state of charge: the full nominal battery current is always requested, and the inverter clamps the setpoint to 30 A times the actual battery voltage itself. Set a lower value and that value is kept, also across restarts; set it to the maximum or above and it follows the maximum again. The `follows_max` attribute shows which applies. A fixed value above the current maximum is clamped when written.

    > Earlier versions stored these rates in % of the inverter's nominal value. That cannot be converted reliably, so after upgrading both rates start out following the maximum — set them again if you used a lower value.
*   **House Fuse Size** *(Configuration category)*: The size of your house fuses in Ampere (A). Used by EMS Grid Protection to calculate safe charge headroom.
*   **Battery Minimum SOC Limit:** 5–100%. `5` means not in use — that is the inverter's own minimum.
*   **Battery Maximum SOC Limit:** 5–100%. `100` means not in use — that is the inverter's own maximum.

Both SOC limits are enabled by default. Installations that predate this were shipped with them disabled
in the entity registry, and that sticks across updates — if you do not see them on the device page,
enable them there once.

### Battery SOC Limits

Registers `1042`/`1044` are governed by the inverter's Modbus timeout: a limit is only in effect while
it is actively being sent, and the inverter reverts to its own settings (minimum 5%, maximum 100%) as
soon as the writes stop. A limit that is in use is therefore written **continuously**, from the moment
you set it, every `inverter timeout / 2` seconds (minimum 5s — the same cadence as the charge/discharge
loops). Set the maximum to 50% and the inverter holds 50% for as long as the entity says 50%, whatever
the battery is doing:

*   **Maximum SOC** — `1044` is written from the moment the limit is set, whether the battery is at 20%
    or already above the limit. Charging stops at the limit and stays stopped.
*   **Minimum SOC** — mirrored on `1042`: discharging stops at the limit and stays stopped.

Setting a limit back to `100` (maximum) or `5` (minimum) means "not in use": that value is written once,
so the release takes effect immediately rather than after the inverter's timeout expires, and nothing is
sent afterwards.

Expect the inverter to taper charge/discharge power as the SoC approaches an active limit — that taper
is the inverter enforcing the limit, and it is what makes "stop charging at 50%" hold. Earlier versions
only started writing 2 percentage points before the limit to avoid it; that left the limit out of force
the rest of the time, so a fast charge could sail straight past it ([#3](https://github.com/mbuhansen/kostal_plenticore_battery_control/issues/3)).

Writing these registers this often does not wear the inverter: `1042`/`1044` are volatile Modbus process
values guarded by the timeout, not stored settings — they revert on their own when the writes stop, which
is exactly why they have to be repeated. Sending the limits does not interfere with the charge/discharge
switches handing control back to the inverter afterwards.

The `Battery Minimum SOC` / `Battery Maximum SOC` diagnostic sensors read the registers back if you
want to watch this happen. Each limit entity also exposes `active` and `writing` attributes.

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
| EMS Charge Limit | W | Charge limit currently computed by EMS Grid Protection |
| Battery Max Control Power | W | Maximum power the integration clamps charge/discharge setpoints to — see Maximum Battery Control Power. Attributes show the observed and documented nominal battery current and the battery maximum voltage |
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
| Software Version | — | Overall inverter software version (UI / SW) from register 58. On inverters without that register it is read from the inverter's web API instead — see Unsupported Registers |
| Battery BMS Serial Number | — | Battery BMS serial |
| Battery Model ID | — | Raw battery model ID |
| Battery Minimum SOC / Battery Maximum SOC | % | Read-back of registers 1042 / 1044 |
| Battery DC / AC Power Setpoint | W | Read-back of the power setpoint register 1034 (hybrid) / 1026 (BI). It keeps the last written value after the inverter has fallen back to its own control |
| Battery Max Charge / Discharge Power Limit | W | Read-back of the limit registers 1038 / 1040 |

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

### Unsupported Registers

Not every Plenticore implements every register in KOSTAL's documentation. PLENTICORE plus G1, for
example, answers `Illegal data address` for register `58` (overall software version) even though the
register table lists it.

An inverter that refuses a register is answering, not failing, so the connection is kept: the value is
recorded as unavailable, an informational line is logged once, that register is skipped for as long as
the integration runs, and every other entity keeps updating. Timeouts and dropped connections are
unchanged — those still mark communication lost and trigger the automatic resume above.

The one exception is register `58`. Where it is missing, the `Software Version` sensor falls back to
the inverter's web API, `http://<inverter>/api/v1/info/version`, which reports the same UI version
without logging in (a G3 returns `3.07.00.25886` from both; a PLENTICORE plus G1 returns `01.30.12092`
from the web API only). It is fetched when the integration starts and again after every communication
outage — a firmware update restarts the inverter, so a new version is picked up by itself. If the web
API cannot be reached the sensor stays unknown, is retried every 10 minutes, and nothing else is
affected. Inverters that do implement register `58` never make this request.

Earlier versions treated a refusal like a broken link, closed the connection and aborted the whole poll,
so a single missing diagnostic register made *all* entities unavailable
([#4](https://github.com/mbuhansen/kostal_plenticore_battery_control/issues/4),
[#5](https://github.com/mbuhansen/kostal_plenticore_battery_control/issues/5)).

## Technical Details

*   **Control Register:** `1034` (Hybrid) / `1026` (BI) — signed absolute power setpoint in Watts (negative = charge, positive = discharge). `1034` is the battery charge power (DC) setpoint for hybrid inverters, where the battery is DC-coupled; `1026` is the battery charge power (AC) setpoint for the AC-coupled PLENTICORE BI. Selected by the inverter type chosen during setup. Tested on a PLENTICORE G3 (SW 3.07): `1034` alone is enough, the setpoint is reached within a few seconds to within a few Watts, and the inverter itself clamps it to its nominal battery current. About 30 seconds after the last write the inverter falls back to its own control, and reading the register back still shows the last value, so it cannot tell whether external control is active. Earlier versions used the relative setpoints `1028` / `1030`.
*   **Maximum Battery Control Power:** Setpoints are clamped to it, rounded up to the next 100 W so a rate that follows the maximum always requests the full nominal battery current.
    *   **Hybrid:** `battery maximum voltage × nominal battery current`. The nominal battery current is measured as `1078 / battery voltage (216)` — on a G3, `1078` is exactly 30 A times the actual battery voltage. The battery's maximum voltage is `1076 / nominal battery current` — on a G3, `1076` is 30 A times 395 V. The highest values seen since Home Assistant started are kept, so a temporary BMS derating does not lower them, and the result stays fixed instead of moving with the state of charge. If `1076` gives a maximum voltage more than 1.3 times the actual voltage (a model where `1076` is not based on the same current), the actual battery voltage is used instead. The current is capped by the documented current of the inverter generation, taken from the first number of the software version:

        | Inverter | Software version | Nominal battery current |
        |---|---|---|
        | PLENTICORE plus G1 | `01.xx` | 13 A |
        | PLENTICORE plus G2 | `02.xx` | 13 A |
        | PLENTICORE G3 / MP G3 | `3.xx` / `03.xx` | 30 A |

    *   **BI:** the nominal AC power from the power class (register `800`): 5500 W for the BI 5.5/26 and 10000 W for the BI 10/26, or `1078` when the power class is unknown.
    *   The `Battery Max Control Power` sensor exposes the observed and documented nominal current and the battery maximum voltage as attributes.
*   **Limit Registers:** `1076` / `1078` — Maximum charge/discharge power limits read out from the battery.
*   **Block Registers:** `1038` / `1040` — Battery max. charge/discharge power limits. Only used for blocking: written to 0 to block, and restored to the battery's own maximum (`1076` / `1078`) afterwards.
*   **SOC Limit Registers:** `1042` / `1044` — Minimum/maximum SOC. Only in effect while actively written.
*   **I/O Output Registers:** `608` / `609` / `610` / `611` — I/O board switched outputs.
*   **Inverter State Register:** `56` — Inverter state2 as U32. Follows the inverter's Modbus byte-order setting (register `5`), like the float registers do.
*   **Software Version Register:** `58` (`0x3A`) — Overall software version (UI / SW), read as a 13-register string.
*   **Battery Info Registers:** `512` / `525` / `527` / `586` — Gross capacity, model ID, BMS serial and firmware. These U32 values are always big-endian (most significant word first) even when the byte-order setting is little-endian (CDAB), so they are read without the word swap the other 32-bit values need. Firmware is packed as major byte then minor byte, so `794` (`0x031A`) is reported as `3.26`. Gross capacity is stored under its own coordinator key because register `512` is also the KSEM's imported-energy register.
*   **Phase Current Registers:** `222` / `232` / `242` — Grid phase currents from smart meter.
*   **Sensor Type Register:** `1082` — Installed smart meter type. Read once during setup to detect a KSEM, and on every poll for the EMS switch.
*   **Battery Management Register:** `1080` — Battery management mode. Read during setup to warn when it is not `0x02` (Modbus).
*   **KSEM Power Registers:** `40972` / `40974` / `40976` / `40982` / `40984` — Additional KSEM power flow values.
*   **KSEM SoC Register:** `40986` — KSEM system state of charge.
*   **KSEM Home Consumption Registers:** `40988` / `40990` / `40992` — Home consumption split by source.
*   **Polling:** All registers are read in a single coordinator cycle every 15 seconds.
*   **Session keepalive:** Writes are sent at half the configured inverter timeout interval (minimum 5s) to prevent session expiry.
