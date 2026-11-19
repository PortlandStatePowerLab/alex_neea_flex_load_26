# -*- coding: utf-8 -*-
"""
Created on Wed Sep 24 14:46:47 2025

@author: Joe_admin
@modified by: Jeff Dinsmore
@modified date: 12/14/2025
@modified by: Thomas Metzler
@modified date: 7/28/2026
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

input_file_root = "Dryer_test_Loadshape_17"

input_file_name1 = input_file_root + "_baseline"
input_file_name2 = input_file_root + "_controlled"
input_file_1  = os.path.join(working_dir, input_file_name1 +".csv")
input_file_2  = os.path.join(working_dir, input_file_name2 +".csv")

output_append_dryerpower = "_dryer_power"
output_file_name1 = input_file_name1 + output_append_dryerpower + ".csv"
output_file_name2 = input_file_name2 + output_append_dryerpower + ".csv"
folder_path = os.path.join(working_dir, "Ready_data", input_file_root)
output_file_1 = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name1)
output_file_2 = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name2)

output_append_totpower = "_total_power"
output_file_name3 = input_file_name1 + output_append_totpower + ".csv"
output_file_name4 = input_file_name2 + output_append_totpower + ".csv"
output_file_3 = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name3)
output_file_4 = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name4)


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

    cols = ['Time',
        "Total Electric Power (kW)",
        "Total Electric Energy (kWh)",
        "Clothes Dryer Electric Power (kW)" 
        ]

    #identify unwanted columns to drop
    unwanted_cols = cols.copy()
    unwanted_cols.remove(wanted_col)

    # drop unwanted columns
    df = df.drop(unwanted_cols, axis=1)

    # pivot the table
    df_pivot = df.pivot_table(index = 'Home', columns = 'hr_min', values = wanted_col)

    # write data to csv
    df_pivot.to_csv(output_file, index=True)

process_data(input_file_1, output_file_1, 'Clothes Dryer Electric Power (kW)')
process_data(input_file_2, output_file_2, 'Clothes Dryer Electric Power (kW)')
process_data(input_file_1, output_file_3, 'Total Electric Power (kW)')
process_data(input_file_2, output_file_4, 'Total Electric Power (kW)')
