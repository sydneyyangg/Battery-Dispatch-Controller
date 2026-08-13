"""
Determine the best solar:wind capacity mix using the per-unit hourly series


Core idea: scaling is linear, so any mix is just
    total_hourly = n_panels * pv_series + n_turbines * wind_series
which is nearly free to compute -- the expensive part (weather -> physical
model) only has to run once per resource, not once per ratio.

using LSPS (Loss of Power Supply) method to find a wind and solar mix that
holds up against a set load and battery on an hourly basis. 
So this script grid-searches over capacity combinations and scores each one 
against your existing battery state machine
(loss-of-power-supply probability, required battery size, and a placeholder
cost model you should replace with your real installed costs).

Methodology and citations
--------------------------
The overall approach (evaluate candidate PV/wind/battery configurations
against a Loss of Power Supply Probability constraint, then pick the
lowest-cost configuration meeting that constraint) follows:
"""
import numpy as np
import pandas as pd
import wind_calcs
import solar_calcs


# ---------------------------------------------------------------------------
# 1. Complementarity check -- cheap diagnostic, do this first
# ---------------------------------------------------------------------------
def complementarity_check(pv_series, wind_series):
    """
    Pearson correlation between the two per-unit hourly series -- the most
    widely used complementarity metric per Jurasz et al. (2020, Solar
    Energy 195:703-724).

    Negative -> genuinely complementary (hybridizing pays off directly).
    Near zero -> independent (hybridizing still reduces variance via
      diversification, just less dramatically).
    Positive -> resources tend to be high/low together (hybridizing buys
      you less; lean toward whichever resource is cheaper/more available,
      or invest more in storage instead).
    """
    
    print(f"Type of pv_series: {type(pv_series)}")
    print(f"Type of wind_series: {type(wind_series)}")
    corr = pv_series.corr(wind_series)
    print(f"Hourly correlation (pv vs wind): {corr:+.3f}")
    return corr


def battery_state_machine(total_hourly_wh, load_w, capacity_wh, soc0_wh=None,
                           charge_eff=0.95, discharge_eff=0.95):
    """
    Returns (LPSP, unmet_total_wh). LPSP -- Loss of Power Supply
    Probability, the fraction of hours the battery+generation can't meet
    load -- is the reliability metric introduced by Borowy & Salameh
    (1996, IEEE Trans. Energy Conversion 11(2):367-375) and used
    throughout the hybrid PV/wind sizing literature since.
    """
    soc = capacity_wh / 2 if soc0_wh is None else soc0_wh
    unmet_total = 0.0
    unmet_hours = 0
    for gen in total_hourly_wh:
        net = gen - load_w  # Wh for a 1-hour step. generated power - used power. 
        # if the net is positive, battery produces enough power, so update soc
        if net >= 0:
            soc = min(capacity_wh, soc + net * charge_eff)
        else: # net negative, battery needs to discharge to meet load.
            deliverable = min(-net, soc * discharge_eff) # either the net, or the rest of the battery
            deliverable = deliverable * discharge_eff  # Convert to power (W)
            soc = max(0.0, soc - deliverable / discharge_eff) # remaining battery %
            unmet = max(0.0, -net - deliverable) # energy unfulfilled
            if unmet > 0:
                unmet_total += unmet
                unmet_hours += 1
    lpsp = unmet_hours / len(total_hourly_wh)  # loss-of-power-supply probability
    return lpsp, unmet_total


# ---------------------------------------------------------------------------
# 3. Required battery size for a target reliability, via bisection
# CHANGE target lpsp
# ---------------------------------------------------------------------------
def min_battery_for_target_lpsp(total_hourly_wh, load_w, target_lpsp=0.02,
                                 lo_wh=0.0, hi_wh=None, tol_wh=500.0):
    """
    Bisection search for the smallest battery capacity that keeps LPSP at or
    below target_lpsp for this generation mix. Cheap because each trial is
    just one pass through the (already-computed) hourly series.

    This is the "given a desired LPSP, find the minimum-cost configuration
    that achieves it" logic from Diaf et al. (2007, Energy Policy
    35(11):5708-5718), just solved by bisection on one variable (battery
    size) instead of their graphical/tabulated approach.
    """
    if hi_wh is None:
        hi_wh = load_w * 24 * 14  # CHANGE: generous upper bound: 2 weeks of autonomy
    while hi_wh - lo_wh > tol_wh:
        mid = (lo_wh + hi_wh) / 2
        lpsp, _ = battery_state_machine(total_hourly_wh, load_w, mid)
        if lpsp <= target_lpsp:
            hi_wh = mid
        else:
            lo_wh = mid
    return hi_wh


# ---------------------------------------------------------------------------
# 4. Grid search over capacity mixes
# CHANGE:  can change the ranges and costs here 
# ---------------------------------------------------------------------------
def grid_search_mix(pv_series, wind_series, load_w, target_lpsp=0.02,
                     n_panels_range=range(0, 21, 2),
                     n_turbines_range=range(0, 3),
                     cost_per_panel=250.0,      # PLACEHOLDER -- use your real
                     cost_per_turbine=8_000_000.0,  # installed costs here
                     cost_per_wh_battery=0.30):
    """
    For each (n_panels, n_turbines) combination, find the minimum battery
    needed to hit target_lpsp, then estimate total system cost. Returns a
    DataFrame sorted by cost -- read it as a Pareto-style comparison rather
    than trusting the single "cheapest" row blindly, since the placeholder
    costs above are almost certainly not your real numbers.

    Brute-force grid search over (n_panels, n_turbines) is a direct,
    automated version of the tangency-plot method Borowy & Salameh (1996)
    solved graphically, combined with the LPSP-then-minimum-cost selection
    rule from Diaf et al. (2007). It's a reasonable substitute for the
    genetic-algorithm approach of Yang, Lu, and Zhou (2007, Solar Energy
    81(1):76-84) specifically because the decision space here is small
    (2-3 variables) -- their GA earns its keep on larger decision spaces
    (e.g. also optimizing PV tilt angle and turbine hub height at once),
    where brute force stops being practical.
    """
    records = []
    for n_panels in n_panels_range:
        for n_turbines in n_turbines_range:
            if n_panels == 0 and n_turbines == 0:
                continue
            total_hourly = n_panels * pv_series + n_turbines * wind_series
            battery_wh = min_battery_for_target_lpsp(
                total_hourly.values, load_w, target_lpsp
            )
            annual_kwh = total_hourly.sum() / 1000
            capex = (n_panels * cost_per_panel
                     + n_turbines * cost_per_turbine
                     + battery_wh * cost_per_wh_battery)
            records.append({
                "n_panels": n_panels,
                "n_turbines": n_turbines,
                "annual_kwh": annual_kwh,
                "battery_wh_needed": battery_wh,
                "estimated_capex": capex,
            })
    df = pd.DataFrame(records).sort_values("estimated_capex").reset_index(drop=True)
    return df

#CHANGE: model of solar and turbine
if __name__ == "__main__":
    pv_series = solar_calcs.run_pv_model(show_plot=False)  # one panel's hourly output, in Wh
    weather = wind_calcs.get_weather_data()
    my_turbine, e126, my_turbine2 = wind_calcs.initialize_wind_turbines()
    wind_calcs.calculate_power_output(weather, my_turbine, e126, my_turbine2)
    wind_series = e126.power_output  # one turbine's hourly output, in Wh

    if pv_series is None or wind_series is None:
        raise RuntimeError("Failed to build the PV or wind hourly series.")

    complementarity_check(pv_series, wind_series)
# CHANGE: load per hour, in w. need fluctuating load w for realism
    load_w = 400000 
# CHANGE: range
    results = grid_search_mix(
        pv_series, wind_series, load_w,
        n_panels_range=range(0, 50, 4),
        n_turbines_range=range(0, 4),
    )
    print("\nTop 10 lowest-estimated-cost mixes meeting target LPSP:")
    print(results.head(10).to_string(index=False))