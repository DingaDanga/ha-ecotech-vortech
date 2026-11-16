# DingaDanga's bespoke EcoTech VorTech Connector

Local Home Assistant control and statistics for **EcoTech Marine VorTech** wavemakers (the Mobius Bluetooth models, such as the MP40 G3 QuietDrive), normally run from the Mobius app.

Home Assistant connects to the pump itself over Bluetooth, through its own Bluetooth adapter or an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html) placed near the tank. No cloud account, no bridge, nothing else to install.

> Not made by, endorsed by or affiliated with EcoTech Marine. "EcoTech", "VorTech" and "Mobius" are trademarks of their owner and are used here only to say which pumps this works with. Use at your own risk.

## What you get

**Controls**

| Entity | What it does |
|---|---|
| Pump (switch) | Off stops the pump (its "All Off" scene) for feeding or tank work; on puts it straight back on its schedule. As a safety net the pump comes back on by itself after 12 hours (you can change this). |
| Speed (slider, 1–100 %) | The speed of the schedule block running now, like the app's speed slider. The wave mode and every other block are left as they are. |
| Wave mode (select) | Constant speed, ReefCrest, Lagoon, Nutrient transport or Tidal swell for the block running now, keeping its speed. |
| Scene (select) | Runs any scene set up on the pump (Feed Mode, All Off, your own), or goes back to the schedule. |
| Feed (button) and Feed time | Stops the pump completely for the time you choose (10 minutes by default), then it goes back to its schedule by itself. |
| Back to schedule (button) | Ends any scene. |
| Hand over to Mobius app (button) | The pump takes only one Bluetooth connection. This lets go of it for 15 minutes (you can change this) so you can use the Mobius app, then Home Assistant reconnects. **Reconnect now** takes it back early. |
| Battery backup speed, Buttons on driver, Status light dims after | The pump's own settings, as in the app. |
| Set pump clock, Restart | Maintenance. |

**Readings** (all kept as long-term statistics)

Motor speed, flow, motor power, motor and driver temperature, motor RPM, supply voltage, running mode, control (schedule or scene), active scene and the time left on it, fault, feeding (paused), running on battery.

**Statistics the app doesn't give you**

| Entity | |
|---|---|
| Running time / Paused time | Running totals, so Home Assistant's statistics show hours per day, week and month. |
| Energy | kWh used by the pump, worked out from its own power reading. Can be added to the Energy dashboard as an individual device. |
| Water moved | Litres pumped, from the pump's own flow reading. |
| Feeds / Last feed | How often and when the pump was paused (Feed button, Pump switch, or the pump's own Feed Mode). |
| Tank turnover | Times per hour the tank volume goes through the pump (set your tank volume in the options). |

**Looking after itself**

- Keeps the pump's clock and time zone right (its schedule runs on its own clock). Checked every 6 hours.
- Shows whether EcoTech has newer firmware (the same check the app makes; install it from the app).
- Follows the pump if its Bluetooth address changes.
- Diagnostics download with everything read from the pump (serial numbers and addresses removed).

**Actions** for automations and scripts: `start_scene` (any scene, with your own run time), `resume_schedule`, `get_schedule` (returns the schedule), `set_schedule` (writes a whole schedule) and `set_wave` (wave mode, speed and timing, including Short pulse, Gyre and Expanding pulse).

A ready-made dashboard (controls, live gauges and the statistics graphs) is in [`examples/dashboard.json`](examples/dashboard.json): Settings → Dashboards → Add dashboard → open it → three-dot menu → Raw configuration editor → paste. Change `cichlid_wavemaker` to your pump's name.

## Install

### HACS (recommended)
1. HACS → three-dot menu → **Custom repositories**.
2. Add `https://github.com/DingaDanga/ha-ecotech-vortech`, type **Integration**.
3. Install **DingaDanga's bespoke EcoTech VorTech Connector** and restart Home Assistant.

### Manual
Copy `custom_components/ecotech_vortech` into your Home Assistant `config/custom_components/` folder and restart.

## Set up
1. Close the Mobius app on your phone (the pump takes one connection at a time), and remove any other integration that connects to the pump.
2. Settings → Devices & services. The pump is usually found by itself; otherwise **Add integration** → search **EcoTech VorTech**.

Everything appears on one device, named as the pump is named in the Mobius app.

## Requirements
- Home Assistant 2025.2 or newer with working Bluetooth: a local adapter in range, or an ESPHome Bluetooth proxy near the tank (an M5Stack Atom works well). A proxy a metre or two from the pump gives a much steadier link than an adapter in another room.
- For an ESPHome proxy, active scanning helps the pump's serial number come through (`esp32_ble_tracker: scan_parameters: active: true`). Without it, setup connects once to read it.
- The pump already set up with the Mobius app.

## Options
Settings → Devices & services → the pump → **Configure**: how often to read the pump (30 s), keep the Bluetooth connection open (on; turn off to connect only for each reading), how long the Pump switch holds the pump off, how long the hand-over to the Mobius app lasts, tank volume, clock keeping and the firmware check.

## Notes
- The speed slider changes the block of the schedule that is running now. With a single-block schedule (the usual "constant" setup) that is the pump's speed all day.
- If a reading fails now and then (Bluetooth), the last values are kept; entities only go unavailable after three failed readings in a row.
- Statistics start when the integration is added; daily figures fill in from the first full hour.

## Credits and licence
Built on [python-mobius](https://code.r3pek.org/r3pek/python-mobius) by r3pek, which decodes the Mobius Bluetooth protocol. Like python-mobius, this integration is released under the **GNU General Public License v2** (see [LICENSE](LICENSE)).
