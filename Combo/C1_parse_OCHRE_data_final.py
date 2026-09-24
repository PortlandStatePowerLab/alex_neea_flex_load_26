# -*- coding: utf-8 -*-
"""
Created on Wed Sep 24 14:46:47 2025

@author: Joe_admin
@modified by: Jeff Dinsmore
@modified date: 12/14/2025
@modified by: Thomas Metzler
@modified date: 6/17/2026
"""


import pandas as pd
from datetime import datetime
import csv
import os

# Converts the datetime information in the HEMS data to usable datetimes
def convert_custom_datetime(series):
    return series.apply(lambda x: datetime.strptime(x, "%d/%m/%Y %H:%M"))


############################################################################
#                           Enter inputs here                              #
############################################################################

# enter in the input and output file names. 

script_dir = os.path.dirname(os.path.abspath(__file__))
fl_dir = os.path.dirname(script_dir)
working_dir = os.path.dirname(fl_dir)   

input_file_root = 'Combo_WH_HVAC_Dryer_EV_Battery_TEST_3'

# ---------------------------------------------------------
# LOAD DEVICES FROM CSV
# ---------------------------------------------------------
devices_file = os.path.join(script_dir, "B0_Devices.csv")
try:
    df_devices = pd.read_csv(devices_file)
    # Convert to dictionary mapping 'Device' to 'Simulation'
    device_sim_map = dict(zip(df_devices['Device'], df_devices['Simulation']))
except FileNotFoundError:
    print(f"[WARNING] {devices_file} not found. Defaulting to OFF.")
    device_sim_map = {}

WH_SIMULATION = device_sim_map.get("WH", "OFF")
HVAC_SIMULATION = device_sim_map.get("HVAC", "OFF")
DRYER_SIMULATION = device_sim_map.get("Dryer", "OFF")
EV_SIMULATION = device_sim_map.get("EV", "OFF")
BATTERY_SIMULATION = device_sim_map.get("Battery", "OFF")


input_file_name_base = input_file_root + "_baseline"
input_file_name_ctrl = input_file_root + "_controlled"
input_file_base  = os.path.join(working_dir, input_file_name_base +".csv")
input_file_ctrl  = os.path.join(working_dir, input_file_name_ctrl +".csv")

folder_path = os.path.join(working_dir, "Ready_data", input_file_root)

if WH_SIMULATION == "ON":
    output_append_WHpower = "_WH_power"
    output_file_name_base_WH = input_file_name_base + output_append_WHpower + ".csv"
    output_file_name_ctrl_WH = input_file_name_ctrl + output_append_WHpower + ".csv"
    output_file_base_WH = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_WH)
    output_file_ctrl_WH = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_WH)

if HVAC_SIMULATION == "ON":
    output_append_ACpower = "_AC_power"
    output_file_name_base_AC = input_file_name_base + output_append_ACpower + ".csv"
    output_file_name_ctrl_AC = input_file_name_ctrl + output_append_ACpower + ".csv"
    output_file_base_AC = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_AC)
    output_file_ctrl_AC = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_AC)

    output_append_HEATpower = "_HEAT_power"
    output_file_name_base_HEAT = input_file_name_base + output_append_HEATpower + ".csv"
    output_file_name_ctrl_HEAT = input_file_name_ctrl + output_append_HEATpower + ".csv"
    output_file_base_HEAT = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_HEAT)
    output_file_ctrl_HEAT = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_HEAT)


if DRYER_SIMULATION == "ON":
    output_append_Dryerpower = "_Dryer_power"
    output_file_name_base_Dryer = input_file_name_base + output_append_Dryerpower + ".csv"
    output_file_name_ctrl_Dryer = input_file_name_ctrl + output_append_Dryerpower + ".csv"
    output_file_base_Dryer = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_Dryer)
    output_file_ctrl_Dryer = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_Dryer)

if EV_SIMULATION == "ON":
    output_append_EVpower = "_EV_power"
    output_file_name_base_EV = input_file_name_base + output_append_EVpower + ".csv"
    output_file_name_ctrl_EV = input_file_name_ctrl + output_append_EVpower + ".csv"
    output_file_base_EV = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_EV)
    output_file_ctrl_EV = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_EV)

    output_append_EVSOC = "_EV_SOC"
    output_file_name_base_EVSOC = input_file_name_base + output_append_EVSOC + ".csv"
    output_file_name_ctrl_EVSOC = input_file_name_ctrl + output_append_EVSOC + ".csv"
    output_file_base_EVSOC = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_EVSOC)
    output_file_ctrl_EVSOC = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_EVSOC)

if BATTERY_SIMULATION == "ON":
    output_append_BATTpower = "_BATT_power"
    output_file_name_base_BATT = input_file_name_base + output_append_BATTpower + ".csv"
    output_file_name_ctrl_BATT = input_file_name_ctrl + output_append_BATTpower + ".csv"
    output_file_base_BATT = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_BATT)
    output_file_ctrl_BATT = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_BATT)

    output_append_BATTSOC = "_BATT_SOC"
    output_file_name_base_BATTSOC = input_file_name_base + output_append_BATTSOC + ".csv"
    output_file_name_ctrl_BATTSOC = input_file_name_ctrl + output_append_BATTSOC + ".csv"
    output_file_base_BATTSOC = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_BATTSOC)
    output_file_ctrl_BATTSOC = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_BATTSOC)


output_append_totpower = "_total_power"
output_file_name_base_total = input_file_name_base + output_append_totpower + ".csv"
output_file_name_ctrl_total = input_file_name_ctrl + output_append_totpower + ".csv"
output_file_base_total = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_total)
output_file_ctrl_total = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_total)


############################################################################
#                             Create Folder                                #
############################################################################

# Check for file path and create if does not exist
if not os.path.exists(folder_path):
    os.makedirs(folder_path) # os.mkdir() creates only one level; os.makedirs() creates intermediate parents
    print(f"Directory created: {folder_path}")
else:
    print(f"Directory already exists: {folder_path}")

############################################################################
#                             Program Start                                #
############################################################################

def process_data(input_file, output_file, wanted_col):
    # read data 
    df = pd.read_csv(input_file)

    # remove any NAN values that will mess up the datetime conversion. 
    df = df.dropna(axis=0)

    reader = csv.DictReader(input_file)

    # Access the columns attribute
    print("Column Titles:")
    # The .columns attribute returns an Index object, which can be printed directly or iterated
    for col in df.columns:
        print(f"- {col}")
    # convert time column to a usable datetime fomat
    df['time'] = pd.to_datetime(df['Time'], errors='coerce')
    #df['time'] = convert_custom_datetime(df['Time'])

    # Create column that contains hour and minute data
    df['hr_min'] = df['time'].dt.strftime('%H:%M')

    cols = ['Time', 'Total Electric Power (kW)', 'Total Electric Energy (kWh)']

    if WH_SIMULATION == "ON":
        cols.append('Water Heating Electric Power (kW)')
    if HVAC_SIMULATION == "ON":
        cols.append('HVAC Heating Electric Power (kW)')
        cols.append('HVAC Cooling Electric Power (kW)')
    if DRYER_SIMULATION == "ON":
        cols.append('Clothes Dryer Electric Power (kW)')
    if EV_SIMULATION == "ON":
        cols.append('EV Electric Power (kW)')
        cols.append('EV SOC (-)')
    if BATTERY_SIMULATION == "ON":
        cols.append("Battery Electric Power (kW)")
        cols.append("Battery SOC (-)")

    #identify unwanted columns to drop
    unwanted_cols = cols.copy()
    unwanted_cols.remove(wanted_col)

    # drop unwanted columns
    df = df.drop(unwanted_cols, axis=1)

    # pivot the table
    df_pivot = df.pivot_table(index = 'Home', columns = 'hr_min', values = wanted_col)

    # write data to csv
    df_pivot.to_csv(output_file, index=True)

if WH_SIMULATION == "ON":
    process_data(input_file_base, output_file_base_WH, 'Water Heating Electric Power (kW)')
    process_data(input_file_ctrl, output_file_ctrl_WH, 'Water Heating Electric Power (kW)')

if HVAC_SIMULATION == "ON":
    process_data(input_file_base, output_file_base_AC, 'HVAC Cooling Electric Power (kW)')
    process_data(input_file_ctrl, output_file_ctrl_AC, 'HVAC Cooling Electric Power (kW)')
    process_data(input_file_base, output_file_base_HEAT, 'HVAC Heating Electric Power (kW)')
    process_data(input_file_ctrl, output_file_ctrl_HEAT, 'HVAC Heating Electric Power (kW)')    

if DRYER_SIMULATION == "ON":
    process_data(input_file_base, output_file_base_Dryer, 'Clothes Dryer Electric Power (kW)')
    process_data(input_file_ctrl, output_file_ctrl_Dryer, 'Clothes Dryer Electric Power (kW)')

if EV_SIMULATION == "ON":
    process_data(input_file_base, output_file_base_EV, 'EV Electric Power (kW)')
    process_data(input_file_ctrl, output_file_ctrl_EV, 'EV Electric Power (kW)')
    process_data(input_file_base, output_file_base_EVSOC, 'EV SOC (-)')
    process_data(input_file_ctrl, output_file_ctrl_EVSOC, 'EV SOC (-)')

if BATTERY_SIMULATION == "ON":
    process_data(input_file_base, output_file_base_BATT, 'Battery Electric Power (kW)')
    process_data(input_file_ctrl, output_file_ctrl_BATT, 'Battery Electric Power (kW)')
    process_data(input_file_base, output_file_base_BATTSOC, 'Battery SOC (-)')
    process_data(input_file_ctrl, output_file_ctrl_BATTSOC, 'Battery SOC (-)')

process_data(input_file_base, output_file_base_total, 'Total Electric Power (kW)')
process_data(input_file_ctrl, output_file_ctrl_total, 'Total Electric Power (kW)')
