
from enum import Enum


class BatteryState(str, Enum):
    IDLE = "idle"
    CHARGING = "charging"
    DISCHARGING = "discharging"
    FAULT = "fault"


class Battery:
    current: float
    crate: float
    voltage: float
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
        current,
        voltage,
        SOC,
        capacity,
        temp,
        temp_limit_l,
        temp_limit_h,
        SOC_limit_l=0.0,
        SOC_limit_h=1.0,
        max_charge_current=100.0,
        max_discharge_current=100.0,
        efficiency=0.95,
    ):
        self.current = current
        self.voltage = voltage
        self.SOC = SOC
        self.capacity = capacity
        self.temp = temp
        self.temp_limit_l = temp_limit_l
        self.temp_limit_h = temp_limit_h
        self.SOC_limit_l = SOC_limit_l
        self.SOC_limit_h = SOC_limit_h
        self.max_charge_current = max_charge_current
        self.max_discharge_current = max_discharge_current
        self.efficiency = efficiency
        self.crate = 0.0
        self.current_power = 0.0
        self.state = BatteryState.IDLE
        self.last_fault = None

    def update_SOC(self, current, dt):
        # (q0 + q) / qmax
        # or soc0 + q/qmax
        # q is the charge in mah. this is I*dt.
        self.SOC += (current * dt) / self.capacity
        # limit soc
        self.SOC = max(self.SOC_limit_l, min(self.SOC, self.SOC_limit_h))
        if self.SOC == self.SOC_limit_l:
            self.set_state(BatteryState.CHARGING)
            self.last_fault = "SOC below limit"
        if self.SOC == self.SOC_limit_h:
            self.set_state(BatteryState.DISCHARGING)
            self.last_fault = "SOC above limit"

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

    def request_power(self, power_w, dt, temp=None):
        # must be within temperature limits
        # not overcharging, ie not above SOC limit
        # no faulting
        # requesting a certain wattage, can it provide that wattage? if not, return the max it can provide.
        

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