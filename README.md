# Battery-Dispatch-Controller
Creating a a control algorithm that decides how a battery charges with renewable energy sources and discharges to hit given delivery targets.

Given a goal of providing X GWh for industrial purposes in a given location, must derive an algorithm for a battery storage system.

## Data and System Modelling
Based on the following factors:
1. Solar irradiance (dhi, dni, ghi)
2. Wind at given elevations
3. Temperature 
Determined a battery discharging and charging behavior based on load and energy inputs. Used ERA5 Hourly Weather Data API. 

## Optimizing a Ratio
Must model the local conditions and determine an optimized wind/solar mix to estimate kWh generation on an hourly basis. Used LPSP (Loss of Power Supply Probability) to determine this, which is a fancy way of saying input-output repeatedly given various constraints :p

Also considered best locations for both sites (on shore for wind, flat land for solar). Was able to use constraints such as weather, load, and device specifications to minimize cost. 

Provides # of panels, turbines, and battery Wh in order to produce the desired load kWh. 

## FSM for Battery Model
Create an FSM to determine states of battery. Then, back with data generated from the energy model, and simulate behavior.
Factor in edge cases and safety constraints to realistic standards.