# -*- coding: utf-8 -*-
"""
Created on Wed Sep 24 14:46:47 2025

@author: Joe_admin
@modified by: Jeff Dinsmore
@modified date: 12/14/2025
@modified by: Thomas Metzler
@modified date: 6/17/2026
@modified by: Alex Wardwell
@modified date: 8/119/2026
"""


import pandas as pd
import csv
import os
import argparse
from datetime import datetime

# Converts the datetime information in the HEMS data to usable datetimes
def convert_custom_datetime(series):
    return series.apply(lambda x: datetime.strptime(x, "%d/%m/%Y %H:%M"))


############################################################################
#                           Enter inputs here                              #
############################################################################

script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(script_dir)

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
    # print("Column Titles:")
    # The .columns attribute returns an Index object, which can be printed directly or iterated
    # for col in df.columns:
    #     print(f"- {col}")
    # convert time column to a usable datetime fomat
    df['time'] = pd.to_datetime(df['Time'], errors='coerce')

    # Create column that contains hour and minute data
    df['hr_min'] = df['time'].dt.strftime('%H:%M')

    cols = ['Time', 'Total Electric Power (kW)', 'Total Electric Energy (kWh)', 'Water Heating Electric Power (kW)', 
    'Water Heating COP (-)', 
    'Hot Water Outlet Temperature (C)', 'Temperature - Indoor (C)', 'time']

    #identify unwanted columns to drop
    unwanted_cols = cols.copy()
    unwanted_cols.remove(wanted_col)

    # drop unwanted columns
    df = df.drop(unwanted_cols, axis=1)

    # pivot the table
    df_pivot = df.pivot_table(index = 'Home', columns = 'hr_min', values = wanted_col)

    # write data to csv
    df_pivot.to_csv(output_file, index=True)

def main(run_id):
    print("Beginning OCHRE data processing...")

    input_file_1 = os.path.join(script_dir, f"{run_id}_baseline.csv")
    input_file_2 = os.path.join(script_dir, f"{run_id}_controlled.csv")
    folder_path = os.path.join(script_dir, "Ready_data", run_id)
    os.makedirs(folder_path, exist_ok=True)

    output_file_1 = os.path.join(folder_path, f"{run_id}_baseline_WH_power.csv")
    output_file_2 = os.path.join(folder_path, f"{run_id}_controlled_WH_power.csv")
    output_file_3 = os.path.join(folder_path, f"{run_id}_baseline_total_power.csv")
    output_file_4 = os.path.join(folder_path, f"{run_id}_controlled_total_power.csv")

    process_data(input_file_1, output_file_1, 'Water Heating Electric Power (kW)')
    process_data(input_file_2, output_file_2, 'Water Heating Electric Power (kW)')
    process_data(input_file_1, output_file_3, 'Total Electric Power (kW)')
    process_data(input_file_2, output_file_4, 'Total Electric Power (kW)')

    print("OCHRE data processed!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    main(parser.parse_args().run_id)
