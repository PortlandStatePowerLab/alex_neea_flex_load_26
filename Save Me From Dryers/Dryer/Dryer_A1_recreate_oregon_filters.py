# -*- coding: utf-8 -*-
"""
Recreate Filtered Dryer files from
OR_upgrade0.csv.

Recovered filter logic:
  - upgrade == 0
  - in.state == "OR"
  - in.city == "OR, Portland"
  - in.geometry_building_type_recs == "Single-Family Detached"
  - in.clothes_dryer == "Electric" 
  - 

This script preserves the original master-file row order and columns.


Authors Jeff Dinsmore & Thomas Metzler 6/17/2026
Modified by Thomas Metzler for Heating 7/27/26
"""

from pathlib import Path
import pandas as pd
import os


script_dir = os.path.dirname(os.path.abspath(__file__))
FL_dir = os.path.dirname(script_dir)
working_dir = os.path.dirname(FL_dir)


#-------------------------------------------------------
#metadata file name
input_file = "OR_upgrade0.csv"

#filtered file save folder
save_folder = "Dryer Filtered"
#-------------------------------------------------------

SOURCE_FILE = Path(
        os.path.join(
        working_dir,
        "Metadata",
        input_file
    )
)

OUTPUT_DIR = Path(
        os.path.join(
        working_dir,
        save_folder
    )
)

#EXCLUDE_BLDG_IDS = {11875, 234402, 433735}
EXCLUDE_BLDG_IDS = {}

print(SOURCE_FILE)
print(OUTPUT_DIR)


def recreate_files(source_file: Path = SOURCE_FILE, output_dir: Path = OUTPUT_DIR) -> None:
    if not source_file.exists():
        raise FileNotFoundError(f"Source file not found: {source_file}")

    output_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(source_file, low_memory=False)

    required_columns = [
        "bldg_id",
        "upgrade",
        "in.state",
        "in.city",
        "in.geometry_building_type_recs",
        "in.clothes_dryer"
        
    ]
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


    base_filter = (
        (df["upgrade"] == 0)
        & (df["in.state"] == "OR")
        & (df["in.city"] == "OR, Portland")
        & (df["in.geometry_building_type_recs"] == "Single-Family Detached")
        & (df["in.clothes_dryer"] == "Electric")
        & (~df["bldg_id"].isin(EXCLUDE_BLDG_IDS))
    )

    df[base_filter].to_csv (output_dir / 'Dryer_OR.csv', index=False)


if __name__ == "__main__":
    recreate_files()
