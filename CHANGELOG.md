# Changelog

## 1.0.0 - 2026-11-16
First release.
- Connects to EcoTech VorTech (Mobius) pumps over Home Assistant's Bluetooth, including ESPHome Bluetooth proxies.
- Pump on/off switch, speed slider, wave mode, scenes, Feed button (stops the pump for an adjustable feed time), back to schedule.
- Live readings: motor speed, flow, power, motor and driver temperature, RPM, supply voltage, running mode, scene and time left, fault, battery.
- Running totals for statistics: running time, paused time, energy, water moved, feeds, last feed, tank turnover.
- Hand over to the Mobius app for a set time, reconnect on demand.
- Pump clock and time zone kept right; firmware update check; diagnostics.
- Actions: start_scene, resume_schedule, get_schedule, set_schedule, set_wave.
