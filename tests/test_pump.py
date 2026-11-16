from unittest.mock import patch
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.core import HomeAssistant
from custom_components.ecotech_vortech.const import DOMAIN
from .fake_pump import FakePump


@pytest.fixture
def fake():
    return FakePump()


@pytest.fixture
async def loaded(hass: HomeAssistant, fake):
    entry = MockConfigEntry(domain=DOMAIN, title="VorTech MP40wG3QD RBC9", unique_id="7K1600C51CRBC9",
                            data={"address": "E2:E6:1D:B1:CB:B5", "serial": "7K1600C51CRBC9", "model": "VorTech MP40wG3QD"})
    entry.add_to_hass(hass)

    async def run(self, job):
        return await job(fake)

    with patch("custom_components.ecotech_vortech.pump.PumpLink.run", run), \
         patch("custom_components.ecotech_vortech.bluetooth.async_register_callback", return_value=lambda: None), \
         patch("custom_components.ecotech_vortech.bluetooth.async_last_service_info", return_value=None), \
         patch("homeassistant.loader.Integration.dependencies", new=[]):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry


async def test_entities(hass, loaded, fake):
    states = {s.entity_id: s.state for s in hass.states.async_all() if "cichlid" in s.entity_id}
    for k, v in sorted(states.items()):
        print(k, v)
    assert states["switch.cichlid_wavemaker_pump"] == "on"
    assert states["number.cichlid_wavemaker_speed"] == "42.0"
    assert states["select.cichlid_wavemaker_wave_mode"] == "constantspeed"
    assert states["select.cichlid_wavemaker_scene"] == "Schedule"
    assert float(states["sensor.cichlid_wavemaker_flow"]) > 0


async def test_controls(hass, loaded, fake):
    await hass.services.async_call("number", "set_value", {"entity_id": "number.cichlid_wavemaker_speed", "value": 55}, blocking=True)
    assert list(fake.schedule[0].pump.params.values())[0] == 550
    assert hass.states.get("number.cichlid_wavemaker_speed").state == "55.0"

    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.cichlid_wavemaker_pump"}, blocking=True)
    assert fake.scene == (3, 720 * 60)
    assert hass.states.get("sensor.cichlid_wavemaker_motor_speed").state == "0.0"
    assert hass.states.get("sensor.cichlid_wavemaker_feeds").state == "1"
    assert hass.states.get("switch.cichlid_wavemaker_pump").state == "off"
    assert hass.states.get("sensor.cichlid_wavemaker_active_scene").state == "All Off"
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.cichlid_wavemaker_pump"}, blocking=True)
    assert fake.scene is None

    await hass.services.async_call("button", "press", {"entity_id": "button.cichlid_wavemaker_feed"}, blocking=True)
    assert fake.scene == (3, 600)  # Feed stops the pump completely
    assert hass.states.get("sensor.cichlid_wavemaker_feeds").state == "2"
    assert hass.states.get("binary_sensor.cichlid_wavemaker_feeding").state == "on"

    await hass.services.async_call("select", "select_option", {"entity_id": "select.cichlid_wavemaker_wave_mode", "option": "reefcrest"}, blocking=True)
    assert fake.schedule[0].pump.mode.name == "ReefCrest"
    assert hass.states.get("number.cichlid_wavemaker_speed").state == "55.0"

    await hass.services.async_call("select", "select_option", {"entity_id": "select.cichlid_wavemaker_scene", "option": "Schedule"}, blocking=True)
    assert fake.scene is None

    dev = next(iter(__import__("homeassistant.helpers.device_registry", fromlist=["x"]).async_get(hass).devices.values()))
    resp = await hass.services.async_call(DOMAIN, "get_schedule", {"device_id": dev.id}, blocking=True, return_response=True)
    print(resp)
    assert resp["schedule"][0]["mode"] == "ReefCrest"
    await hass.services.async_call(DOMAIN, "set_wave", {"device_id": dev.id, "mode": "Gyre", "speed": 60, "gyre_seconds": 30}, blocking=True)
    assert fake.schedule[0].pump.mode.name == "Gyre"
    await hass.services.async_call(DOMAIN, "start_scene", {"device_id": dev.id, "scene": "feed mode", "minutes": 2}, blocking=True)
    assert fake.scene == (1, 120)


async def test_unload(hass, loaded):
    assert await hass.config_entries.async_unload(loaded.entry_id)


async def test_link_release(hass):
    from custom_components.ecotech_vortech.pump import PumpLink, PumpReleased
    link = PumpLink(hass, "AA", "x")
    fake = FakePump()
    fake.is_connected = False
    state = {"conn": 0}

    async def connect():
        state["conn"] += 1
        fake.is_connected = True

    async def disconnect():
        fake.is_connected = False

    fake.connect, fake.disconnect = connect, disconnect
    link.device = fake
    assert (await link.run(lambda d: d.get_full_poll_batch())).primitive is not None
    assert state["conn"] == 1 and link.is_connected
    await link.run(lambda d: d.get_full_poll_batch())
    assert state["conn"] == 1  # kept open
    await link.release(1)
    assert not link.is_connected
    with pytest.raises(PumpReleased):
        await link.run(lambda d: d.get_full_poll_batch())
    link.cancel_release()
    link.keep_connected = False
    await link.run(lambda d: d.get_full_poll_batch())
    assert state["conn"] == 2 and not link.is_connected


async def test_options_flow(hass, loaded):
    result = await hass.config_entries.options.async_init(loaded.entry_id)
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "poll_interval": 60, "keep_connected": True, "off_hold_minutes": 30, "app_release_minutes": 10,
        "tank_volume": 450, "time_sync": True, "firmware_check": False})
    await hass.async_block_till_done()
    assert loaded.options["off_hold_minutes"] == 30
    assert hass.states.get("sensor.cichlid_wavemaker_tank_turnover") is not None
    print(hass.states.get("sensor.cichlid_wavemaker_tank_turnover"))


def _info(mfr=None):
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData
    adv = AdvertisementData(local_name="MOBIUS", manufacturer_data=mfr or {}, service_data={},
                            service_uuids=["01ff0100-ba5e-f4ee-5ca1-eb1e5e4b1ce0"], tx_power=-127, rssi=-37, platform_data=())
    return BluetoothServiceInfoBleak(name="MOBIUS", address="E2:E6:1D:B1:CB:B5", rssi=-37, manufacturer_data=mfr or {},
        service_data={}, service_uuids=adv.service_uuids, source="proxy", device=BLEDevice("E2:E6:1D:B1:CB:B5", "MOBIUS", {}),
        advertisement=adv, connectable=True, time=0, tx_power=-127)


async def test_flow_passive_discovery(hass):
    with patch("custom_components.ecotech_vortech.config_flow._read_identity",
               return_value=("7K1600C51CRBC9", "VorTech MP40wG3QD", "VorTech MP40wG3QD RBC9")), \
         patch("custom_components.ecotech_vortech.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "bluetooth"}, data=_info())
        assert result["step_id"] == "confirm", result
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] == "create_entry", result
        assert result["result"].unique_id == "7K1600C51CRBC9"


async def test_flow_with_serial(hass):
    import struct
    payload = struct.pack("<H", 42) + b"\x00" + struct.pack("<I", 0) + struct.pack("<H", 0x102) + b"7K1600C51CRBC9"
    with patch("custom_components.ecotech_vortech.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "bluetooth"}, data=_info({514: payload}))
        assert result["step_id"] == "confirm", result
        assert result["description_placeholders"]["name"].startswith("VorTech MP40wG3QD")
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["result"].unique_id == "7K1600C51CRBC9"


async def test_flow_ignores_other_devices(hass):
    """A busy adapter can attach the Mobius service UUID to other devices."""
    info = _info({117: bytes(24)})
    info.name = "S45 71C8 LE"
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "bluetooth"}, data=info)
    assert result["type"] == "abort" and result["reason"] == "not_supported"
