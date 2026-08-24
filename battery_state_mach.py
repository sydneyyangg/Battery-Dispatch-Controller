from transitions import Machine
from battery_class import Battery, BatteryStates
from solar_calcs import run_pv_model
import wind_calcs

class BatteryController(object):
    states = BatteryStates

    def __init__(self, name):
        self.battery = Battery(capacity=10, temp=25, temp_limit_l=0, temp_limit_h=40)

        self.name = name
        self.net_power_hr = 0
        self.current_hour = 0

        transitions = [
            { 'trigger': 'needs_met', 'source': ['BatteryStates.IDLE', 'BatteryStates.CHARGING', 'BatteryStates.DISCHARGING'], 'dest': 'BatteryStates.IDLE', 'conditions': ['net_0', 'temp_in_range']},
            { 'trigger': 'charging', 'source': ['BatteryStates.CHARGING', 'BatteryStates.DISCHARGING'], 'dest': 'BatteryStates.CHARGING', 'conditions': ['net_pos', 'acp_pos', 'temp_in_range'] },
            { 'trigger': 'start_charging', 'source': ['BatteryStates.EMPTY', 'BatteryStates.IDLE'], 'dest': 'BatteryStates.CHARGING', 'conditions': ['net_pos', 'temp_in_range'] },
            { 'trigger': 'discharging', 'source': ['BatteryStates.CHARGING', 'BatteryStates.DISCHARGING'], 'dest': 'BatteryStates.DISCHARGING', 'conditions': ['net_neg', 'adp_pos', 'temp_in_range'] },
            { 'trigger': 'start_discharging', 'source': ['BatteryStates.FULL', 'BatteryStates.IDLE'], 'dest': 'BatteryStates.DISCHARGING', 'conditions': ['net_neg', 'temp_in_range']},
            { "trigger": 'reach_full', 'source': 'BatteryStates.CHARGING', 'dest': 'BatteryStates.FULL', 'conditions': ['net_pos', 'acp_0', 'temp_in_range'] },
            { "trigger": 'remain_full', 'source': 'BatteryStates.FULL', 'dest': 'BatteryStates.FULL', 'conditions': ['net_pos', 'temp_in_range'] },
            { "trigger": 'reach_empty', 'source': 'BatteryStates.DISCHARGING', 'dest': 'BatteryStates.EMPTY', 'conditions': ['net_neg', 'adp_0', 'temp_in_range'] },
            { "trigger": 'remain_empty', 'source': 'BatteryStates.EMPTY', 'dest': 'BatteryStates.EMPTY', 'conditions': ['net_neg', 'temp_in_range'] },
            { "trigger": 'fault', 'source': '*', 'dest': 'BatteryStates.FAULT' },
            { "trigger": 'recover', 'source': 'BatteryStates.FAULT', 'dest': 'BatteryStates.IDLE' }
        ]


        # Initialize the state machine
        self.machine = Machine(model=self, states=list(self.states), before_state_change='calculate_hourly_net_and_soc', transitions = transitions, initial='BatteryStates.IDLE')

        self.pv_series = run_pv_model(show_plot=False)  # one panel's hourly output, in Wh

        weather = wind_calcs.get_weather_data()
        my_turbine, e126, my_turbine2 = wind_calcs.initialize_wind_turbines()
        wind_calcs.calculate_power_output(weather, my_turbine, e126, my_turbine2)
        self.wind_series = e126.power_output  # one turbine's hourly output, in Wh
        total_wph = self.pv_series + self.wind_series
        load = 10000  # Example load in W
        self.net_power = total_wph - load

        self.current_hour = 0  # Initialize the current hour

# NEED TO MULT BY RESULTING PANELS AND TURBINES FOR ACCURATE WATT RATIO
# AND REDETERMINE LOAD
    def get_hourly_net_and_soc(self):
        # pull entry from self.net_power based on current hour
        self.net_power_hr = self.net_power.iloc[self.current_hour]
        self.current_hour += 1
        if self.current_hour >= len(self.net_power):    
            self.current_hour = 0  # Reset to the beginning of the year
        self.battery.update_SOC(self.net_power_hr, dt=1)  # Assuming dt is 1 hour

    @property
    def net_pos(self):
        return self.net_power_hr > 0

    @property
    def net_neg(self):
        return self.net_power_hr < 0

    @property
    def net_0(self):
        return self.net_power_hr == 0

    @property
    def acp_pos(self):
        return self.battery.available_charge_power() > 0

    @property
    def acp_0(self):
        return self.battery.available_charge_power() == 0

    @property
    def adp_0(self):
        return self.battery.available_discharge_power() == 0

    @property
    def adp_pos(self):
        return self.battery.available_discharge_power() > 0
