# Battery-Dispatch-Controller
Creating a a control algorithm that decides how a battery charges with renewable energy sources and discharges to hit given delivery targets.

Given a goal of providing X GWh for industrial purposes in a given location, must derive an algorithm for a battery storage system.

## Data and System Modelling
Based on the following factors:
1. Solar irradiance
2. Wind at given elevations

Used NASA POWER Hourly Temporal API.
Must model the local conditions and determine an optimized wind/solar mix to estimate kWh generation on an hourly basis. 

## FSM for Battery Model
Create an FSM to determine states of battery. Then, back with data generated from the energy model, and simulate behavior.
Factor in edge cases and safety constraints to realistic standards.
