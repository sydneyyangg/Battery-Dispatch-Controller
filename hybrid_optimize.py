"""
Determine the best solar:wind capacity mix using per-MW-installed hourly
series.

using LSPS (Loss of Power Supply) method to find a wind and solar mix that
holds up against a set load and battery on an hourly basis.
So this script grid-searches over capacity combinations and scores each one
against your existing battery state machine
(loss-of-power-supply probability, required battery size, and a placeholder
cost model you should replace with your real installed costs).

"""
import numpy as np
import pandas as pd
import wind_calcs
import solar_calcs


# ---------------------------------------------------------------------------
# 0. Rescale one device's hourly output to "per MW installed"
# ---------------------------------------------------------------------------
def to_per_mw(device_series, device_nameplate_w):
    """
    Rescale a single device's hourly output series into the hourly output
    of a 1 MW *fleet* of that device, assuming the fleet's weather-driven
    output ratio matches the single unit exactly 

    device_nameplate_w: the device's rated capacity in watts (e.g. a solar
        module's DC nameplate rating, or a turbine's nominal_power).

    device_series / device_nameplate_w is basically an efficiency ratio, ie how much
    of the capacity is actually being produced each hour

    """
    return device_series * (1_000_000.0 / device_nameplate_w)


# ---------------------------------------------------------------------------
# 1. Complementarity check -- cheap diagnostic, do this first
# ---------------------------------------------------------------------------
def complementarity_check(pv_series, wind_series):
    """
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
        else:  # net negative, battery needs to discharge to meet load.
            deliverable = min(-net, soc * discharge_eff)  # either the net, or the rest of the battery
            soc = max(0.0, soc - deliverable / discharge_eff)  # remaining battery %
            unmet = max(0.0, -net - deliverable)  # energy unfulfilled
            if unmet > 0:
                unmet_total += unmet
                unmet_hours += 1
    lpsp = unmet_hours / len(total_hourly_wh)  # loss-of-power-supply probability
    return lpsp, unmet_total


# ---------------------------------------------------------------------------
# 2. Battery-ceiling helper -- shared by the bisection and the diagnostic print
# ---------------------------------------------------------------------------
def battery_ceiling_wh(load_w, days=14):
    """Generous upper bound for battery search: N days of full-load autonomy."""
    return load_w * 24 * days


# ---------------------------------------------------------------------------
# 3. Required battery size for a target reliability, via bisection
# CHANGE target lpsp
# ---------------------------------------------------------------------------
def min_battery_for_target_lpsp(total_hourly_wh, load_w, target_lpsp=0.02,
                                 lo_wh=0.0, hi_wh=None, tol_wh=500.0):
    """
    Bisection search for the smallest battery capacity that keeps LPSP at or
    below target_lpsp for this generation mix. 

    Returns (battery_wh, lpsp_achieved, hit_target):
    - battery_wh: the battery size found. If hit_target is False, this is
      just hi_wh (the search ceiling) -- generation is insufficient to
      reach target_lpsp no matter how much battery you add, so the
      bisection can't converge on a real answer and this value should be
      treated as "not achievable," not as a sizing recommendation.
    - lpsp_achieved: the actual LPSP measured at battery_wh, so you can see
      *how far off* target you are even when hit_target is False.
    - hit_target: whether target_lpsp was actually reached anywhere in
      [lo_wh, hi_wh].
    """
    if hi_wh is None:
        hi_wh = battery_ceiling_wh(load_w, 5)  # CHANGE: generous upper bound: 2 weeks of autonomy

    # Check feasibility first: even max battery might not be enough if
    # generation itself is too small to ever satisfy target_lpsp.
    lpsp_at_ceiling, _ = battery_state_machine(total_hourly_wh, load_w, hi_wh)
    if lpsp_at_ceiling > target_lpsp:
        return hi_wh, lpsp_at_ceiling, False

    while hi_wh - lo_wh > tol_wh:
        mid = (lo_wh + hi_wh) / 2
        lpsp, _ = battery_state_machine(total_hourly_wh, load_w, mid)
        if lpsp <= target_lpsp:
            hi_wh = mid
        else:
            lo_wh = mid

    lpsp_final, _ = battery_state_machine(total_hourly_wh, load_w, hi_wh)
    return hi_wh, lpsp_final, True


# ---------------------------------------------------------------------------
# 4. Grid search over capacity mixes (MW solar x MW wind)
# CHANGE:  can change the ranges, derates, and costs here
# ---------------------------------------------------------------------------
def grid_search_mix(pv_per_mw, wind_per_mw, load_w, target_lpsp=0.02,
                     mw_solar_range=range(0, 1250, 50),
                     mw_wind_range=range(0, 1250, 50),
                     solar_derate=0.95,            # array/inverter losses at scale
                     wind_derate=0.90,              # wake losses across a farm
                     cost_per_mw_solar=450_000.0,       # ~$0.9/W, PLACEHOLDER, investor said 50% off so 450000
                     cost_per_mw_wind=1_500_000.0,      # ~$1.5/W, PLACEHOLDER
                     cost_per_wh_battery=0.15):         # ~$150/kWh, PLACEHOLDER
    """
    For each (mw_solar, mw_wind) combination, find the minimum battery
    needed to hit target_lpsp, then estimate total system cost.

    Returns (feasible, infeasible):
    - feasible: rows that actually reached target_lpsp somewhere in the
      battery search range, sorted by estimated cost 
    - infeasible: rows that never reached target_lpsp even at the battery
      ceiling. 

    Brute-force grid search over (mw_solar, mw_wind)
    
    """
    pv_farm = pv_per_mw * solar_derate
    wind_farm = wind_per_mw * wind_derate

    records = []
    infeasible_count = 0
    for mw_solar in mw_solar_range:
        for mw_wind in mw_wind_range:
            if mw_solar == 0 and mw_wind == 0:
                continue
            total_hourly = mw_solar * pv_farm + mw_wind * wind_farm
            battery_wh, lpsp_achieved, hit_target = min_battery_for_target_lpsp(
                total_hourly.values, load_w, target_lpsp
            )
            if not hit_target:
                infeasible_count += 1
            annual_kwh = total_hourly.sum() / 1000
            capex = (mw_solar * cost_per_mw_solar
                     + mw_wind * cost_per_mw_wind
                     + battery_wh * cost_per_wh_battery)
            records.append({
                "mw_solar": mw_solar,
                "mw_wind": mw_wind,
                "annual_kwh": annual_kwh,
                "battery_wh_needed": battery_wh,
                "lpsp_achieved": lpsp_achieved,
                "hit_target": hit_target,
                "estimated_capex": capex,
            })

    total = len(records)
    print(f"\n[grid_search_mix] target_lpsp={target_lpsp:.3f} | "
          f"{total - infeasible_count}/{total} combos reached target "
          f"({infeasible_count} did not, even at the "
          f"{battery_ceiling_wh(load_w):,.0f} Wh battery ceiling). "
          f"Infeasible rows report the LPSP they actually achieved instead "
          f"of a real battery size.")

    df = pd.DataFrame(records)
    feasible = df[df["hit_target"]].sort_values("estimated_capex").reset_index(drop=True)
    infeasible = df[~df["hit_target"]].sort_values("lpsp_achieved").reset_index(drop=True)
    return feasible, infeasible


#CHANGE: model of solar and turbine
if __name__ == "__main__":
    pv_series = solar_calcs.run_pv_model(show_plot=False)  # one panel's hourly output, in Wh
    weather = wind_calcs.get_weather_data()
    my_turbine, e126, my_turbine2 = wind_calcs.initialize_wind_turbines()
    wind_calcs.calculate_power_output(weather, my_turbine, e126, my_turbine2)
    wind_series = e126.power_output  # one turbine's hourly output, in Wh

    if pv_series is None or wind_series is None:
        raise RuntimeError("Failed to build the PV or wind hourly series.")

    # Rescale each device's series into "per MW installed" so the grid
    # search can sweep capacity (MW) instead of device counts.
    module_nameplate_w = solar_calcs.module['Impo'] * solar_calcs.module['Vmpo']  # ~219.66 W
    turbine_nameplate_w = e126.nominal_power  # 4,200,000 W

    pv_per_mw = to_per_mw(pv_series, module_nameplate_w)
    wind_per_mw = to_per_mw(wind_series, turbine_nameplate_w)

    complementarity_check(pv_per_mw, wind_per_mw)

# CHANGE: load per hour, in w. need fluctuating load w for realism
    load_w = 500_000_000  # 1 gigawatt, but do 500 MW for testing

# CHANGE: LPSP target -- see conversation notes / docstrings for guidance.
# 0.02 (98% reliability) is a reasonable off-grid-microgrid default from the
# literature, but is almost certainly too loose for a real data center --
# see the discussion in the chat for why critical loads usually target
# LPSP several orders of magnitude lower, or rely on non-battery backup.
    target_lpsp = 0.05

# CHANGE: range -- widen this if most/all combos come back infeasible
    feasible, infeasible = grid_search_mix(
        pv_per_mw, wind_per_mw, load_w,
        target_lpsp=target_lpsp,
        mw_solar_range=range(0, 3000, 50),
        mw_wind_range=range(0, 1250, 50),
    )

    if len(feasible) > 0:
        print("\nTop 10 lowest-estimated-cost mixes meeting target LPSP:")
        print(feasible.head(10).to_string(index=False))
    else:
        print("\nNo combo in the search range reached target_lpsp "
              f"={target_lpsp:.3f}. Showing the 10 closest misses instead "
              "(ranked by lowest achieved LPSP) -- widen mw_solar_range / "
              "mw_wind_range and re-run:")
        print(infeasible.head(10).to_string(index=False))