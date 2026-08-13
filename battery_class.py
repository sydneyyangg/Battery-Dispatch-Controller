
from enum import Enum


class BatteryState(str, Enum):
    IDLE = "idle"
    CHARGING = "charging"
    DISCHARGING = "discharging"
    FAULT = "fault"


class Battery:
    crate: float
    SOC: float
    SOC_limit_l: float
    SOC_limit_h: float
    capacity: float
    temp: float
    temp_limit_l: float
    temp_limit_h: float
    current_power: float
    state: BatteryState
    last_fault: str | None

    def __init__(
        self,
        capacity,
        temp,
        temp_limit_l,
        temp_limit_h,
        SOC=0.5,
        SOC_limit_l=0.1,
        SOC_limit_h=0.9,
        efficiency=0.95,
    ):
        self.SOC = SOC
        self.capacity = capacity #(kwh)
        self.temp = temp
        self.temp_limit_l = temp_limit_l
        self.temp_limit_h = temp_limit_h
        self.SOC_limit_l = SOC_limit_l
        self.SOC_limit_h = SOC_limit_h
        self.efficiency = efficiency
        self.crate = 0.0
        self.current_power = 0.0
        self.state = BatteryState.IDLE
        self.last_fault = None

    def update_SOC(self, req_w, dt):
        # (q0 + q) / qmax ( capacity )
        # or soc0 + q/qmax
        # irl its Kalman Filter Method
        if self.state == BatteryState.CHARGING:
            self.SOC += (req_w * dt) / 1000 / self.capacity * self.efficiency
        elif self.state == BatteryState.DISCHARGING:
            self.SOC -= (req_w * dt) / 1000 / self.capacity * self.efficiency

        self.SOC = max(self.SOC_limit_l, min(self.SOC, self.SOC_limit_h))

    # returns watts

    def available_charge_power(self):
        """Max power battery can accept right now, given SoC headroom and C-rate."""
        # higher limit - soc = headroom (in % of capacity)
        # headroom * capacity = max charge in kwh
        headroom = self.SOC_limit_h - self.SOC
        return headroom * self.capacity
    
    def available_discharge_power(self):
        """Max power battery can provide right now, given SoC headroom and C-rate."""
        # soc - lower limit = headroom (in % of capacity)
        # headroom * capacity = max discharge in kwh
        headroom = self.SOC - self.SOC_limit_l
        return headroom * self.capacity

    def charge(self, power_w, dt):
        self.set_state(BatteryState.CHARGING)
        actual_power = min(power_w, self.available_charge_power())
        self.update_SOC(actual_power, dt)

    def discharge(self, power_w, dt):
        self.set_state(BatteryState.DISCHARGING)
        actual_power = min(power_w, self.available_discharge_power())
        self.update_SOC(-actual_power, dt)

    def update_temp(self, temp):
        self.temp = temp
        self.temp = max(self.temp_limit_l, min(self.temp, self.temp_limit_h))

    def set_state(self, new_state):
        if self.state == BatteryState.FAULT and new_state != BatteryState.FAULT:
            self.last_fault = None
        self.state = new_state

    def clear_fault(self):
        self.last_fault = None
        self.state = BatteryState.IDLE

    def get_status(self):
        return {
            "state": self.state.value,
            "soc": self.SOC,
            "voltage": self.voltage,
            "current": self.current,
            "power_w": self.current_power,
            "temp": self.temp,
            "last_fault": self.last_fault,
        }