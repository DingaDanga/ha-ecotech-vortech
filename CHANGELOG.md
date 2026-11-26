# Changelog

## 1.1.0 - 2026-11-26
Fixes the pump staying "not answering" after a dropped Bluetooth link.
- Frees a stuck Bluetooth proxy: after a drop an ESPHome proxy can keep the old connection open, which keeps the pump silent. When the pump has been out of reach for 90 seconds the proxy is asked to let go, and reloaded if Home Assistant still shows it holding the pump. Can be turned off in the pump settings.
- Will not connect through a path weaker than -80 dBm (adjustable, -100 = off), so a far adapter that only just hears the pump is no longer used in place of a nearby proxy.
- Diagnostics now show the path used for the connection, the proxies found and what the recovery has done.

## 1.0.0 - 2026-11-16
First release.
- Connects to EcoTech VorTech (Mobius) pumps over Home Assistant's Bluetooth, including ESPHome Bluetooth proxies.
- Pump on/off switch, speed slider, wave mode, scenes, Feed button (stops the pump for an adjustable feed time), back to schedule.
- Live readings: motor speed, flow, power, motor and driver temperature, RPM, supply voltage, running mode, scene and time left, fault, battery.
- Running totals for statistics: running time, paused time, energy, water moved, feeds, last feed, tank turnover.
- Hand over to the Mobius app for a set time, reconnect on demand.
- Pump clock and time zone kept right; firmware update check; diagnostics.
- Actions: start_scene, resume_schedule, get_schedule, set_schedule, set_wave.
