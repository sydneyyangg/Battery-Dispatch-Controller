import pvlib

import pandas as pd

import matplotlib.pyplot as plt

import numpy as np

import requests

from datetime import datetime, date, time
from http.client import IncompleteRead
from time import sleep

from urllib3.exceptions import ProtocolError


#1 Define coordinates for the locations of interest
# create the modules and inverters using the pvlib library
# use the procedural method first to try and get the weather -> power output


# # latitude, longitude, name, altitude, timezone
# # approx altitude, region is mountainous but double check land access
# coordinates = [
#     (14.8, 120.3, 'Subic', 350, 'Pht/GMT+8'),
#     (35.1, -106.6, 'Albuquerque', 1500, 'Etc/GMT+7'),
# ]


coordinates = [
    (32.2, -111.0, 'Tucson', 700, 'Etc/GMT+7'),
    (35.1, -106.6, 'Albuquerque', 1500, 'Etc/GMT+7'),
    (37.8, -122.4, 'San Francisco', 10, 'Etc/GMT+8'),
    (52.5, 13.4, 'Berlin', 34, 'Etc/GMT-1'),
    (14.8, 120.3, 'Subic', 350, 'Etc/GMT+8'),
]

# 2. Load equipment models

sandia_modules = pvlib.pvsystem.retrieve_sam('SandiaMod')

sapm_inverters = pvlib.pvsystem.retrieve_sam('cecinverter')

module = sandia_modules['Canadian_Solar_CS5P_220M___2009_']

inverter = sapm_inverters['ABB__MICRO_0_25_I_OUTD_US_208__208V_']

temperature_model_parameters = pvlib.temperature.TEMPERATURE_MODEL_PARAMETERS['sapm']['open_rack_glass_glass']


def load_weather(latitude, longitude, altitude, start, end, variables, api_key, retries=3):
    isera5 = True

    for attempt in range(1, retries + 1):
        try:
            weather = pvlib.iotools.get_era5(latitude, longitude, start, end, variables, api_key)[0].copy()
            weather['pressure'] = pvlib.atmosphere.alt2pres(altitude)
            weather['wind_speed'] = np.hypot(
                weather['u10'],
                weather['v10'],
            )
            weather['dhi'] = weather['ghi'] - weather['fdir']
            print(f"Era5 used: {isera5}")
            return weather
        except (
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ConnectionError,
            ProtocolError,
            IncompleteRead,
        ) as error:
            if attempt == retries:
                break
            sleep(2 ** (attempt - 1))

    isera5 = False
    weather, meta = pvlib.iotools.get_pvgis_tmy(latitude, longitude)
    weather = weather.copy()
    weather['pressure'] = pvlib.atmosphere.alt2pres(altitude)
    if 'wind_speed' not in weather.columns:
        weather['wind_speed'] = 0.0

    if 'dni' not in weather.columns or 'dhi' not in weather.columns:
        raise RuntimeError('PVGIS fallback did not return DNI and DHI columns.')

    print(f"Era5 used: {isera5}")

    return weather

# 3. Get weather data for each location using a database

tmys = []

start = datetime(2020, 1, 1)
end = datetime(2020, 12, 31)
variables = ['ghi', 'total_sky_direct_solar_radiation_at_surface', 'temp_air', '10m_u_component_of_wind', '10m_v_component_of_wind']
api_key = ''

for location in coordinates:
    latitude, longitude, name, altitude, timezone = location
    #weather = pvlib.iotools.get_pvgis_tmy(latitude, longitude)[0]
    weather = load_weather(latitude, longitude, altitude, start, end, variables, api_key)
    # these return a dataframe 
    # gives an hour-by-hour year of representative irradiance, temperature, wind, and pressure data for that location.

    #weather.index.name = "utc_time"
    #weather.index = "utc_time"
    tmys.append(weather)

system = {'module': module, 'inverter': inverter,
          'surface_azimuth': 180}


energies = {}

for location, weather in zip(coordinates, tmys):
    latitude, longitude, name, altitude, timezone = location
    system['surface_tilt'] = latitude

    # Computes solar position (sun's zenith/azimuth angle) for every timestamp.
    solpos = pvlib.solarposition.get_solarposition(
        time=weather.index,
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        temperature=weather["temp_air"],
        pressure=weather["pressure"],
    )

    if 'dni' not in weather.columns:
        weather['dni'] = (weather['ghi'] - weather['dhi']) / np.cos(np.radians(solpos['apparent_zenith']))

    # Computes extraterrestrial irradiance, airmass, 
    # and angle-of-incidence (AOI) of sunlight on the panel (tilted at an angle 
    # equal to the site's latitude, facing south — surface_azimuth=180).
    dni_extra = pvlib.irradiance.get_extra_radiation(weather.index)
    airmass = pvlib.atmosphere.get_relative_airmass(solpos['apparent_zenith'])
    pressure = pvlib.atmosphere.alt2pres(altitude)
    am_abs = pvlib.atmosphere.get_absolute_airmass(airmass, pressure)
    aoi = pvlib.irradiance.aoi(
        system['surface_tilt'],
        system['surface_azimuth'],
        solpos["apparent_zenith"],
        solpos["azimuth"],
    )

    # Converts DNI/GHI/DHI weather components into plane-of-array irradiance 
    # using the Hay-Davies transposition model.
    total_irradiance = pvlib.irradiance.get_total_irradiance(
        system['surface_tilt'],
        system['surface_azimuth'],
        solpos['apparent_zenith'],
        solpos['azimuth'],
        weather['dni'],
        weather['ghi'],
        weather['dhi'],
        dni_extra=dni_extra,
        model='haydavies',
    )

    # Estimates module cell temperature from irradiance, air temp, and wind speed (Sandia thermal model).
    cell_temperature = pvlib.temperature.sapm_cell(
        total_irradiance['poa_global'],
        weather["temp_air"],
        weather["wind_speed"],
        **temperature_model_parameters,
    )

    # Computes "effective irradiance" seen by the cell (accounting for spectral/angular losses).
    effective_irradiance = pvlib.pvsystem.sapm_effective_irradiance(
        total_irradiance['poa_direct'],
        total_irradiance['poa_diffuse'],
        am_abs,
        aoi,
        module,
    )
    #Runs the Sandia PV array performance model (sapm) to get DC output (voltage, power) at each timestep.
    dc = pvlib.pvsystem.sapm(effective_irradiance, cell_temperature, module)
    ac = pvlib.inverter.sandia(dc['v_mp'], dc['p_mp'], inverter)
    # Sums the AC power over the whole year to get total annual energy yield for that location.
    annual_energy = ac.sum()
    energies[name] = annual_energy


energies = pd.Series(energies)


print(energies)


energies.plot(kind='bar', rot=0)


plt.ylabel('Yearly energy yield (W hr)')

plt.show()

