import win32com.client
import pandas as pd
import subprocess
import os
import sys
from pathlib import Path
import re
from datetime import datetime
import shutil

base_dir = Path(__file__).resolve().parent

OLD_BLDG_DIR = os.path.join(base_dir, "HPWH All Portland Input Files")

WS_NAME = "Calculator"
excel = win32com.client.GetActiveObject("Excel.Application")
wb = excel.ActiveWorkbook
WS = wb.Worksheets(WS_NAME)

if WS.Range("N38").Value == "Yes":
    if os.path.isdir(OLD_BLDG_DIR):
        shutil.rmtree(OLD_BLDG_DIR)