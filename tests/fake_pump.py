"""A fake VorTech that answers like the real library objects."""
import time
from mobius import (
    FullPollResult, MetadataSnapshot, PumpSchedulePoint, PumpPrimitiveValue, PumpMode, PumpParam,
    Scene, ActiveScene, SceneID, OperationState, PrimitiveType, BatteryBackupInfo, AdvancedFeatures,
)
from mobius.constants import Model


class FakePump:
    def __init__(self):
        self.schedule = [PumpSchedulePoint(0, 0, PumpPrimitiveValue(PumpMode.ConstantSpeed, {PumpParam.MaxSpeed: 420}))]
        self.scene = None  # (id, remaining)
        self.calls = []
        self.speed = 419
        self.local = True
        self.dim = 0
        self.bb = 200
        self.is_connected = True

    async def get_supported_attributes(self):
        return []

    def _poll(self):
        active = self.schedule[0].pump.params.get(PumpParam.MaxSpeed, 0)
        speed = 0 if self.scene and self.scene[0] == SceneID.AllOff else active
        meta = MetadataSnapshot(
            advanced_features=AdvancedFeatures(self.local, self.dim, None, None), calibration=None,
            hardware_info={"Revision": 33, "RadioType": "K32W"}, firmware_versions={"Product OS": "3.0.35", "Radio OS": "5.1.38"},
            supported_channels=[], error_state="NoError", epoch=int(time.time()) - 5, local_time=None, tz_offset=None,
            posix_tz="GMT0BST,M3.5.0/1,M10.5.0", olson_tz="Europe/London",
        )
        meta.firmware_version = "3.0.35"
        return FullPollResult(
            device_info={"model_raw": 42, "model": "VorTechMP40wG3QD", "manufacturer": "EcoTech Marine", "name": "Cichlid WAVEMAKER",
                         "serial": "7K1600C51CRBC9", "primitive_type": "VorTechV1", "error_state": "NoError",
                         "mac_address": "00", "group_mask": 1},
            metadata=meta, light_poll=None,
            pump_telemetry={"speed": speed, "speed_percent": speed / 10, "gph": int(4500 * speed / 1000), "motor_power_watts": int(speed / 25),
                            "minimum_gph": 0, "maximum_gph": 4500, "gph_reliable": True,
                            "operation_mode": "MotorOff" if speed == 0 else "ConstantSpeed"},
            pump_schedule_points=list(self.schedule),
            configured_scenes=[
                Scene(0, 1, SceneID.FeedMode, "Feed Mode", 600, None, None),
                Scene(1, 3, SceneID.AllOff, "All Off", 43200, None, None),
                Scene(2, 0, SceneID.EmptyScene, "", 0, None, None),
            ],
            current_scene=ActiveScene(self.scene[0], SceneID(self.scene[0]), self.scene[1], self.scene[1]) if self.scene else None,
            battery_backup=BatteryBackupInfo(self.bb, 500),
            operation_state=OperationState.Scene if self.scene else OperationState.Schedule,
            primitive=PrimitiveType.VorTechV1, model=Model.VorTechMP40wG3QD,
        )

    async def get_full_poll_batch(self, **kw):
        self.calls.append("poll")
        return self._poll()

    async def get_extra_physical_values(self):
        return {"DriverTemperature": 36, "MotorTemperature": 40, "MotorRPM": 1769, "InputVoltage": 32, "BatteryVoltage": 0}

    async def start_scene(self, scene_id, seconds=None, **kw):
        self.calls.append(("scene", int(scene_id), seconds))
        self.scene = (int(scene_id), seconds or 600)

    async def start_feed_mode(self, seconds=None, **kw):
        await self.start_scene(SceneID.FeedMode, seconds)

    async def resume_schedule(self, **kw):
        self.calls.append("resume")
        self.scene = None

    async def set_pump_schedule(self, points, primitive_type=None, model=None):
        self.calls.append(("schedule", [(p.pump.mode.name, dict(p.pump.params)) for p in points]))
        self.schedule = points

    async def set_battery_backup_speed(self, percent, max_speed=None):
        self.bb = int(percent * 10)

    async def set_advanced_features(self, **kw):
        if "local_control_enabled" in kw:
            self.local = kw["local_control_enabled"]
        if "auto_dim_timeout" in kw:
            self.dim = kw["auto_dim_timeout"]
        return {k: None for k in kw}

    async def set_time_zone(self, tz):
        self.calls.append(("tz", tz))

    async def set_time_to_now(self):
        self.calls.append("time")

    async def reboot(self):
        self.calls.append("reboot")
