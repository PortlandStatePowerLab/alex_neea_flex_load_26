"""
Author: Thomas Metzler
Updated: 8/24/2026

Adjusts HPWH, ERWH, HVAC, Dryer, EV properties in the XML file that OCHRE will read.
Converts all devices in the homes to the devices specified
"""

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
import re
import random 
import pandas as pd
from copy import deepcopy
import math
import sys
from tqdm import tqdm

# ---------------------------------------------------------
# DIRECTORY SETUP
# ---------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
FL_DIR = SCRIPT_DIR.parent.parent 
WORKING_DIR = FL_DIR.parent

INPUT_DIR = SCRIPT_DIR.parent / "All Portland Input Files"
OUTPUT_DIR = SCRIPT_DIR.parent / "Combo Regulation All Input Files"

METADATA_DIR = FL_DIR / "Metadata" / "OR_upgrade0.csv"
# Load metadata once globally
# metadata_df = pd.read_csv(METADATA_DIR, low_memory=False)
# print(metadata_df)

DEVICES = {
    "device_conversion": {
        "HPWH": "ON",
        "ERWH": "OFF",
        "HVAC": "ON",
        "Dryer": "ON", 
        "EV": "ON"
    }

}

# ---------------------------------------------------------
# DEVICE MODELS
# ---------------------------------------------------------

HPWH_MODEL_CONFIG = {
    "HPWH_model": [
        # AOSmith HPTU-50N
        {"TankVolume": 46.0, "HeatingCapacity": 1391, "UniformEnergyFactor": 3.45, "BackupHeatingCapacity": 15345.0}
    ]
}

ERWH_MODEL_CONFIG = {
    "ERWH_model": [
        # RHEEM PROE50 T2
        {"TankVolume": 45.0, "HeatingCapacity": 15354.0, "EnergyFactor": 0.93}
    ]
}

# ASHP - air-to-air - single stage
# MSHP - mini-split - variable speed
HVAC_MODEL_CONFIG = {
    "HVAC_model": [
        {"Type": "ASHP", "HeatPumpType": "air-to-air", "CompressorType": "single stage", "Capacity": 36000.0, 
         "BackupHeatingCapacity": 36000.0, "SEER": 18.0, "HSPF": 10.0, "HeatingAirflowCFM": 1200.0, "CoolingAirflowCFM": 1200.0}
    ]
}

DRYER_MODEL_CONFIG = {
    "Dryer_model": [
        {"CombinedEnergyFactor": "2.9", "PowerRating": "15000"}
    ]

}

EV_MODEL_CONFIG = {
    "EV_model": [
        {"ChargingLevel":"Level1", "ChargingPower":"9500"}
    ]
}

# ---------------------------------------------------------
# CONFIGURATIONS
# ---------------------------------------------------------

HPWH_CONVERSION_CONFIG = {
    "HPWH_Conversion": {
        "FuelType": "electricity",
        "NewType": "heat pump water heater",
        "TankVolume": HPWH_MODEL_CONFIG["HPWH_model"][0]["TankVolume"],
        "HeatingCapacity": HPWH_MODEL_CONFIG["HPWH_model"][0]["HeatingCapacity"],
        "UniformEnergyFactor": HPWH_MODEL_CONFIG["HPWH_model"][0]["UniformEnergyFactor"],
        "BackupHeatingCapacity": HPWH_MODEL_CONFIG["HPWH_model"][0]["BackupHeatingCapacity"],
        "HPWHOperatingMode": "hybrid/auto",
        "UsageBin": "medium", 
        "ElementsToRemove": [
            "RecoveryEfficiency",
            "EnergyFactor",
            "PerformanceAdjustment",
            "extension"
        ]
    }
}


ERWH_CONVERSION_CONFIG = {
    "ERWH_Conversion": {
        "NewType": "storage water heater",
        "NewFuelType": "electricity",
        "TankVolume": ERWH_MODEL_CONFIG["ERWH_model"][0]["TankVolume"],         
        "HeatingCapacity": ERWH_MODEL_CONFIG["ERWH_model"][0]["HeatingCapacity"], 
        "EnergyFactor": ERWH_MODEL_CONFIG["ERWH_model"][0]["EnergyFactor"],
        "RecoveryEfficiency": "0.98",
        "ElementsToRemove": [
            "BackupHeatingCapacity", 
            "UniformEnergyFactor", 
            "HPWHOperatingMode", 
            "UsageBin",
            "FirstHourRating"
        ]
    }
}

HVAC_CONVERSION_CONFIG = {
    "HVAC_Conversion": {
        "Type": HVAC_MODEL_CONFIG["HVAC_model"][0]["Type"], # "ASHP" for Air-to-Air, "MSHP" for mini-split
        "HeatPumpType": HVAC_MODEL_CONFIG["HVAC_model"][0]["HeatPumpType"], # Use "air-to-air" for ASHP, "mini-split" for MSHP
        "CompressorType": HVAC_MODEL_CONFIG["HVAC_model"][0]["CompressorType"], # Use "single stage" for standard ASHP, "variable speed" for MSHP
        "UnitLocation": "conditioned space", 
        "Capacity": HVAC_MODEL_CONFIG["HVAC_model"][0]["Capacity"], # Max Capacity
        "SEER": HVAC_MODEL_CONFIG["HVAC_model"][0]["SEER"],
        "HSPF": HVAC_MODEL_CONFIG["HVAC_model"][0]["HSPF"],
        "BackupHeatingCapacity": HVAC_MODEL_CONFIG["HVAC_model"][0]["BackupHeatingCapacity"],
        "HeatingAirflowCFM": HVAC_MODEL_CONFIG["HVAC_model"][0]["HeatingAirflowCFM"],
        "CoolingAirflowCFM": HVAC_MODEL_CONFIG["HVAC_model"][0]["CoolingAirflowCFM"],
        
        # MSHP Specifics: Ratios and Constant COPs per temperature
        "MSHP_Cooling_Perf": [
            {"Temp": 95.0, "CapacityRatio": 1.0, "COP": 3.0, "Desc": "maximum"},
            {"Temp": 95.0, "CapacityRatio": 0.25, "COP": 4.0, "Desc": "minimum"},
            {"Temp": 82.0, "CapacityRatio": 1.03, "COP": 3.8, "Desc": "maximum"},
            {"Temp": 82.0, "CapacityRatio": 0.28, "COP": 5.2, "Desc": "minimum"},
        ],
        "MSHP_Heating_Perf": [
            {"Temp": 47.0, "CapacityRatio": 1.2, "COP": 3.5, "Desc": "maximum"},
            {"Temp": 47.0, "CapacityRatio": 0.3, "COP": 4.5, "Desc": "minimum"},
            {"Temp": 5.0, "CapacityRatio": 0.48, "COP": 2.2, "Desc": "maximum"},
            {"Temp": 5.0, "CapacityRatio": 0.18, "COP": 2.5, "Desc": "minimum"},
        ]
    }
}

DRYER_CONVERSION_CONFIG = {
    "AdoptionRate": 1, # % chance of updating or adding a dryer
    "ClothesDryer": {
        "IsSharedAppliance": "false",
        "Location": "conditioned space",
        "FuelType": "electricity",
        "CombinedEnergyFactor": DRYER_MODEL_CONFIG["Dryer_model"][0]["CombinedEnergyFactor"],
        "Vented": "true",
        "VentedFlowRate": "100.0",
        "extension": {
            "UsageMultiplier": "1.0",
            "WeekdayScheduleFractions": "0.010, 0.006, 0.004, 0.002, 0.004, 0.006, 0.016, 0.032, 0.048, 0.068, 0.078, 0.081, 0.074, 0.067, 0.058, 0.061, 0.055, 0.054, 0.051, 0.051, 0.052, 0.054, 0.044, 0.024",
            "WeekendScheduleFractions": "0.010, 0.006, 0.004, 0.002, 0.004, 0.006, 0.016, 0.032, 0.048, 0.068, 0.078, 0.081, 0.074, 0.067, 0.058, 0.061, 0.055, 0.054, 0.051, 0.051, 0.052, 0.054, 0.044, 0.024",
            "MonthlyScheduleMultipliers": "1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0"
        }
    },
    "ServiceFeeder": {
        "LoadType": "clothes dryer",
        "PowerRating": DRYER_MODEL_CONFIG["Dryer_model"][0]["PowerRating"],
        "IsNewLoad": "false"
    },
    "BranchCircuit": {
        "Voltage": "240",
        "OccupiedSpaces": "2.0"
    }
}


if EV_MODEL_CONFIG["EV_model"][0]["ChargingLevel"] == "Level1":
    EV_rates = {
        "Level1": 1.0,
        "Level2": 0,
        "None": 0
    }
    EV_max_current = int(EV_MODEL_CONFIG["EV_model"][0]["ChargingPower"])/120
elif EV_MODEL_CONFIG["EV_model"][0]["ChargingLevel"] == "Level2":
    EV_rates = {
        "Level1": 0,
        "Level2": 1.0,
        "None": 0
    }
    EV_max_current = int(EV_MODEL_CONFIG["EV_model"][0]["ChargingPower"])/240
else:
    EV_rates = {}
    EV_max_current = 100.0

EV_CONVERSION_CONFIG = {
    # Distribution of charger levels.
    "ChargerAdoptionRates": EV_rates,
    
    # Details for the Service Feeders and Branch Circuits for EV chargers
    "ChargerDetails": {
        "1": {
            "ChargingPower": EV_MODEL_CONFIG["EV_model"][0]["ChargingPower"],
            "Voltage": "120",
            "MaxCurrentRating": str(EV_max_current),
            "OccupiedSpaces": "1.0",
        },
        "2": {
            "ChargingPower": EV_MODEL_CONFIG["EV_model"][0]["ChargingPower"],
            "Voltage": "240",
            "MaxCurrentRating": str(EV_max_current),
            "OccupiedSpaces": "2.0",
        }
    },

    # Predefined Vehicle Types Specs, Vehicle Type Listed in Metadata
    "VehicleSpecs": {
        "SUV, Battery Electric Vehicle, 200 mile range": {
            "NominalCapacity": "66.88", "UsableCapacity": "53.503", "FuelEconomy": "0.267513"
        },
        "Pickup, Battery Electric Vehicle, 300 mile range": {
            "NominalCapacity": "132.43", "UsableCapacity": "105.946", "FuelEconomy": "0.373794"
        },
        "SUV, Battery Electric Vehicle, 300 mile range": {
            "NominalCapacity": "104.6", "UsableCapacity": "83.68", "FuelEconomy": "0.278934"
        },
        "Compact, Battery Electric Vehicle, 300 mile range": {
            "NominalCapacity": "79.29", "UsableCapacity": "63.433", "FuelEconomy": "0.22002"
        },
        "Midsize, Battery Electric Vehicle, 300 mile range": {
            "NominalCapacity": "81.8", "UsableCapacity": "65.441", "FuelEconomy": "0.229449"
        },
        "Compact, Battery Electric Vehicle, 200 mile range": {
            "NominalCapacity": "50.21", "UsableCapacity": "40.168", "FuelEconomy": "0.209901"
        },
        "Midsize, Battery Electric Vehicle, 200 mile range": {
            "NominalCapacity": "52.47", "UsableCapacity": "41.978", "FuelEconomy": "0.219174"
        }
    }
}

# ---------------------------------------------------------
# XML SCHEME ORDERS (USED FOR EV CODE)
# ---------------------------------------------------------

SYSTEMS_ORDER = [
    "SystemIdentifier",
    "HVAC",
    "MechanicalVentilation",
    "CombustionVentilation",
    "WaterHeating",
    "SolarThermal",
    "Photovoltaics",
    "ElectricPanels",
    "ElectricalLoadCenter",
    "Batteries",
    "Vehicles",
    "ElectricVehicleChargers",
    "Generators",
    "Pools",
    "PermanentSpas",
    "HotTubs",
    "PlugLoads",
    "FuelLoads"
]

ELEC_ORDER = [
    "SystemIdentifier",
    "Voltage",
    "MaximumCurrentRating",
    "Capacity",
    "OccupiedSpaces",
    "TotalSpaces",
    "BranchCircuits",
    "BranchCircuit",
    "ServiceFeeders",
    "ServiceFeeder"
]

# ---------------------------------------------------------
# EV SPECIFIC HELPER FUNCTIONS
# ---------------------------------------------------------

def sort_hpxml_node(node, order_list):
    """Sorts the children of an XML node based on a standardized schema order."""
    if node is None:
        return
    
    def get_order(child):
        tag_name = child.tag.split('}')[-1]
        try:
            return order_list.index(tag_name)
        except ValueError:
            return len(order_list) # Unknown tags go to the end
            
    # Re-order the elements internally
    node[:] = sorted(node, key=get_order)

def parse_charge_fraction(val):
    if pd.isna(val): return 0.9
    val = str(val).lower()
    if '100' in val: return 1.0
    if '80-99' in val: return 0.9
    if '60-79' in val: return 0.7
    if '40-59' in val: return 0.5
    if '20-39' in val: return 0.3
    if '0-19' in val: return 0.1
    return 0.9 # Default fallback

def get_building_metadata(bldg_id, metadata_df):
    try:
        row = metadata_df[metadata_df['bldg_id'] == int(bldg_id)]
    except KeyError:
        print(f"[Warning] Bldg {bldg_id}: 'bldg_id' column not found in metadata CSV!")
        return None
    except ValueError:
        print(f"[Warning] Bldg {bldg_id}: Could not convert building ID to an integer.")
        return None
        
    if row.empty:
        print(f"[Warning] Bldg {bldg_id}: No matching row found in metadata CSV.")
        return None
    return row.iloc[0]


# ---------------------------------------------------------
# MODIFIER FUNCTIONS
# ---------------------------------------------------------

def convert_HPWH(root, config):
    """Converts ERWH, Natural Gas, and Tankless heaters to an HPWH."""
    ns_match = re.match(r'\{.*\}', root.tag)
    ns_bracket = ns_match.group(0) if ns_match else ''
    
    conv_data = config["HPWH_Conversion"]

    for elem in root.iter():
        if elem.tag.split('}')[-1] == 'WaterHeatingSystem':
            type_elem = None
            fuel_elem = None
            
            # Locate base identifying elements
            for child in elem:
                tag_name = child.tag.split('}')[-1]
                if tag_name == 'WaterHeaterType':
                    type_elem = child
                elif tag_name == 'FuelType':
                    fuel_elem = child

            # Check if it is a storage (ERWH/Gas) or instantaneous (Tankless) heater
            if type_elem is not None and type_elem.text in ['storage water heater', 'instantaneous water heater']:
                
                # 1. Update Water Heater Type and Fuel Type
                type_elem.text = conv_data["NewType"]
                if fuel_elem is not None:
                    fuel_elem.text = conv_data["FuelType"]
                
                # 2. Remove conflicting elements
                to_remove = [child for child in elem if child.tag.split('}')[-1] in conv_data["ElementsToRemove"]]
                for child in to_remove:
                    elem.remove(child)
                    
                # 3. Add or update HPWH specific elements in correct schema order
                # We anchor around FractionDHWLoadServed to maintain valid XML sequences
                fraction_elem = next((c for c in elem if c.tag.split('}')[-1] == 'FractionDHWLoadServed'), None)
                
                # Schema insertion order: (Tag Name, Value, Anchor Element, Insert After Anchor?)
                updates = [
                    ("TankVolume", conv_data["TankVolume"], fraction_elem, False), 
                    ("HeatingCapacity", conv_data["HeatingCapacity"], fraction_elem, True), 
                    ("BackupHeatingCapacity", conv_data["BackupHeatingCapacity"], fraction_elem, True),
                    ("UniformEnergyFactor", conv_data["UniformEnergyFactor"], fraction_elem, True),
                    ("HPWHOperatingMode", conv_data["HPWHOperatingMode"], fraction_elem, True),
                    ("UsageBin", conv_data["UsageBin"], fraction_elem, True)
                ]

                # Tracks our moving target for schema placement
                current_anchor = fraction_elem

                for tag, value, anchor, insert_after in updates:
                    existing = next((c for c in elem if c.tag.split('}')[-1] == tag), None)
                    
                    # Update if it exists
                    if existing is not None:
                        existing.text = str(value)
                        if insert_after:
                            current_anchor = existing
                    # Create and place if missing
                    else:
                        new_elem = ET.Element(f'{ns_bracket}{tag}')
                        new_elem.text = str(value)
                        
                        if anchor is not None and current_anchor in list(elem):
                            idx = list(elem).index(current_anchor if insert_after else anchor)
                            insert_pos = idx + 1 if insert_after else idx
                            elem.insert(insert_pos, new_elem)
                            if insert_after:
                                current_anchor = new_elem
                        else:
                            # Fallback if anchor is totally missing from file
                            elem.append(new_elem)


def convert_ERWH(root, config):
    """
    Standardizes ALL water heaters in the XML to standard 
    ERWHs using the parameters defined in the conversion config.
    """
    ns_match = re.match(r'\{.*\}', root.tag)
    ns_bracket = ns_match.group(0) if ns_match else ''
    
    conv_data = config["ERWH_Conversion"]

    for elem in root.iter():
        if elem.tag.split('}')[-1] == 'WaterHeatingSystem':
            type_elem = None
            fuel_elem = None
            cap_elem = None
            vol_elem = None
            
            # Locate existing identifying elements
            for child in elem:
                tag_name = child.tag.split('}')[-1]
                if tag_name == 'WaterHeaterType':
                    type_elem = child
                elif tag_name == 'FuelType':
                    fuel_elem = child
                elif tag_name == 'HeatingCapacity':
                    cap_elem = child
                elif tag_name == 'TankVolume':
                    vol_elem = child
            
            # 1. Force Water Heater Type
            if type_elem is not None:
                type_elem.text = conv_data["NewType"]
            else:
                type_elem = ET.Element(f'{ns_bracket}WaterHeaterType')
                type_elem.text = conv_data["NewType"]
                elem.insert(0, type_elem)
            
            # 2. Force Fuel Type to Electricity
            if fuel_elem is not None:
                fuel_elem.text = conv_data["NewFuelType"]
            else:
                new_fuel = ET.Element(f'{ns_bracket}FuelType')
                new_fuel.text = conv_data["NewFuelType"]
                # Insert right after WaterHeaterType
                idx = list(elem).index(type_elem)
                elem.insert(idx + 1, new_fuel)

            # 3. Force Tank Volume Override
            if vol_elem is not None:
                vol_elem.text = str(conv_data["TankVolume"])
            else:
                vol_elem = ET.Element(f'{ns_bracket}TankVolume')
                vol_elem.text = str(conv_data["TankVolume"])
                # Try to insert before heating capacity if it exists
                if cap_elem is not None:
                    idx = list(elem).index(cap_elem)
                    elem.insert(idx, vol_elem)
                else:
                    elem.append(vol_elem)
            
            # 4. Force Heating Capacity Override
            if cap_elem is not None:
                cap_elem.text = str(conv_data["HeatingCapacity"])
            else:
                cap_elem = ET.Element(f'{ns_bracket}HeatingCapacity')
                cap_elem.text = str(conv_data["HeatingCapacity"])
                idx = list(elem).index(vol_elem)
                elem.insert(idx + 1, cap_elem)
            
            # 5. Remove incompatible tags (from HPWH, Gas, or Tankless)
            to_remove = []
            for child in elem:
                tag_name = child.tag.split('}')[-1]
                if tag_name in conv_data["ElementsToRemove"]:
                    to_remove.append(child)
            
            for child in to_remove:
                elem.remove(child)
            
            # 6. Apply or Override ERWH-specific elements
            ef_elem = None
            re_elem = None
            for child in elem:
                tag_name = child.tag.split('}')[-1]
                if tag_name == 'EnergyFactor':
                    ef_elem = child
                elif tag_name == 'RecoveryEfficiency':
                    re_elem = child

            idx = list(elem).index(cap_elem)
            
            if ef_elem is not None:
                ef_elem.text = str(conv_data["EnergyFactor"])
            else:
                ef_elem = ET.Element(f'{ns_bracket}EnergyFactor')
                ef_elem.text = str(conv_data["EnergyFactor"])
                elem.insert(idx + 1, ef_elem)
            
            if re_elem is not None:
                re_elem.text = str(conv_data["RecoveryEfficiency"])
            else:
                re_elem = ET.Element(f'{ns_bracket}RecoveryEfficiency')
                re_elem.text = str(conv_data["RecoveryEfficiency"]) 
                # Insert immediately after EnergyFactor
                idx_ef = list(elem).index(ef_elem)
                elem.insert(idx_ef + 1, re_elem)
            
            if re_elem is not None:
                re_elem.text = conv_data["RecoveryEfficiency"]
            else:
                re_elem = ET.Element(f'{ns_bracket}RecoveryEfficiency')
                re_elem.text = conv_data["RecoveryEfficiency"]
                # Insert immediately after EnergyFactor
                idx_ef = list(elem).index(ef_elem)
                elem.insert(idx_ef + 1, re_elem)


def convert_HVAC(root, config):
    """Converts existing HVAC systems to an all-electric ASHP or MSHP."""
    ns_match = re.match(r'\{.*\}', root.tag)
    ns = ns_match.group(0) if ns_match else ''
    
    conv = config["HVAC_Conversion"]
    
    # Locate all HVACPlants in the XML
    for hvac_plant in root.findall(f'.//{ns}HVACPlant'):
        
        # 1. Update Primary Systems to reference the new HeatPump1
        primary_systems = hvac_plant.find(f'{ns}PrimarySystems')
        if primary_systems is not None:
            for child in list(primary_systems):
                primary_systems.remove(child)
            
            ph = ET.SubElement(primary_systems, f'{ns}PrimaryHeatingSystem')
            ph.set('idref', 'HeatPump1')
            pc = ET.SubElement(primary_systems, f'{ns}PrimaryCoolingSystem')
            pc.set('idref', 'HeatPump1')
        
        # 2. Strip out legacy systems AND capture the existing distribution system
        dist_idref = None
        for sys_tag in ['HeatingSystem', 'CoolingSystem', 'HeatPump']:
            for sys_elem in hvac_plant.findall(f'{ns}{sys_tag}'):
                # Try to salvage the distribution system link before deleting
                dist_node = sys_elem.find(f'{ns}DistributionSystem')
                if dist_node is not None and not dist_idref:
                    dist_idref = dist_node.get('idref')
                
                hvac_plant.remove(sys_elem)
                
        # 3. Build the unified HeatPump XML structure in EXACT schema order
        hp = ET.SubElement(hvac_plant, f'{ns}HeatPump')
        
        ET.SubElement(hp, f'{ns}SystemIdentifier', id='HeatPump1')
        
        unit_loc = ET.SubElement(hp, f'{ns}UnitLocation')
        unit_loc.text = conv.get("UnitLocation", "conditioned space")
        
        # Distribution System MUST go exactly here (after UnitLocation, before HeatPumpType)
        if dist_idref and conv["HeatPumpType"] == "air-to-air":
            ET.SubElement(hp, f'{ns}DistributionSystem', idref=dist_idref)
            
        hp_type = ET.SubElement(hp, f'{ns}HeatPumpType')
        hp_type.text = conv["HeatPumpType"]
        
        ET.SubElement(hp, f'{ns}HeatPumpFuel').text = 'electricity'
        ET.SubElement(
            hp, f"{ns}HeatingCapacity"
        ).text = str(conv["HeatingCapacity"])

        ET.SubElement(
            hp, f"{ns}CoolingCapacity"
        ).text = str(conv["CoolingCapacity"])
        ET.SubElement(hp, f'{ns}CompressorType').text = conv["CompressorType"]
        
        # Lockout temps and sensible heat fraction (Required by OCHRE/HPXML)
        lockout = "-20.0" if conv["Type"] == "MSHP" else "0.0"
        ET.SubElement(hp, f'{ns}CompressorLockoutTemperature').text = lockout
        ET.SubElement(hp, f'{ns}CoolingSensibleHeatFraction').text = '0.73'
        
        # Backup Heating specs
        ET.SubElement(hp, f'{ns}BackupType').text = 'integrated'
        ET.SubElement(hp, f'{ns}BackupSystemFuel').text = 'electricity'
        
        bahe = ET.SubElement(hp, f'{ns}BackupAnnualHeatingEfficiency')
        ET.SubElement(bahe, f'{ns}Units').text = 'Percent'
        ET.SubElement(bahe, f'{ns}Value').text = '1.0'
        
        ET.SubElement(hp, f'{ns}BackupHeatingCapacity').text = str(conv["BackupHeatingCapacity"])
        ET.SubElement(hp, f'{ns}BackupHeatingLockoutTemperature').text = '40.0'
        
        # Load Served
        ET.SubElement(hp, f'{ns}FractionHeatLoadServed').text = '1.0'
        ET.SubElement(hp, f'{ns}FractionCoolLoadServed').text = '1.0'
        
        # Efficiencies based on configuration inputs
        ace = ET.SubElement(hp, f'{ns}AnnualCoolingEfficiency')
        ET.SubElement(ace, f'{ns}Units').text = 'SEER'
        ET.SubElement(ace, f'{ns}Value').text = str(conv["SEER"])
        
        ahe = ET.SubElement(hp, f'{ns}AnnualHeatingEfficiency')
        ET.SubElement(ahe, f'{ns}Units').text = 'HSPF'
        ET.SubElement(ahe, f'{ns}Value').text = str(conv["HSPF"])
        
        # 4. Insert dynamic detailed performance tables if it's an MSHP
        if conv["Type"] == "MSHP":
            # Generate cooling performance points
            cdpd = ET.SubElement(hp, f'{ns}CoolingDetailedPerformanceData')
            for pt in conv.get("MSHP_Cooling_Perf", []):
                pdp = ET.SubElement(cdpd, f'{ns}PerformanceDataPoint')
                ET.SubElement(pdp, f'{ns}OutdoorTemperature').text = str(pt["Temp"])
                
                # Multiply constant capacity ratio by configured max capacity
                calc_capacity = round(
                    conv["CoolingCapacity"] * pt["CapacityRatio"], 1
                )
                ET.SubElement(pdp, f'{ns}Capacity').text = str(calc_capacity)
                ET.SubElement(pdp, f'{ns}CapacityDescription').text = pt["Desc"]
                
                eff = ET.SubElement(pdp, f'{ns}Efficiency')
                ET.SubElement(eff, f'{ns}Units').text = 'COP'
                ET.SubElement(eff, f'{ns}Value').text = str(pt["COP"])
                
            # Generate heating performance points
            hdpd = ET.SubElement(hp, f'{ns}HeatingDetailedPerformanceData')
            for pt in conv.get("MSHP_Heating_Perf", []):
                pdp = ET.SubElement(hdpd, f'{ns}PerformanceDataPoint')
                ET.SubElement(pdp, f'{ns}OutdoorTemperature').text = str(pt["Temp"])
                
                # Multiply constant capacity ratio by configured max capacity
                calc_capacity = round(
                    conv["HeatingCapacity"] * pt["CapacityRatio"], 1
                )
                ET.SubElement(pdp, f'{ns}Capacity').text = str(calc_capacity)
                ET.SubElement(pdp, f'{ns}CapacityDescription').text = pt["Desc"]
                
                eff = ET.SubElement(pdp, f'{ns}Efficiency')
                ET.SubElement(eff, f'{ns}Units').text = 'COP'
                ET.SubElement(eff, f'{ns}Value').text = str(pt["COP"])
                
        # 5. Insert airflow extensions
        ext = ET.SubElement(hp, f'{ns}extension')
        ET.SubElement(ext, f'{ns}HeatingAirflowCFM').text = str(conv["HeatingAirflowCFM"])
        ET.SubElement(ext, f'{ns}CoolingAirflowCFM').text = str(conv["CoolingAirflowCFM"])


def convert_dryer(root, config):
    """Converts or adds a Clothes Dryer to be an electric dryer based on adoption rate."""
    if random.random() > config["AdoptionRate"]:
        return  # Roll failed; skip conversion

    ns_match = re.match(r'\{.*\}', root.tag)
    ns = ns_match.group(0) if ns_match else ''
    
    dryer_config = config["ClothesDryer"]
    feeder_config = config["ServiceFeeder"]
    branch_config = config.get("BranchCircuit", {})

    # Generate a parent map globally to accurately place nodes
    parent_map = {c: p for p in root.iter() for c in p}

    # --- 1. HANDLE DRYER ELEMENT ---
    dryer = root.find(f'.//{ns}ClothesDryer')
    dryer_id = 'ClothesDryer1'

    if dryer is not None:
        # Dryer exists, update its ID if needed and check fuel type
        sys_id_elem = dryer.find(f'{ns}SystemIdentifier')
        if sys_id_elem is not None:
            dryer_id = sys_id_elem.get('id', 'ClothesDryer1')
            
        fuel_elem = dryer.find(f'{ns}FuelType')
        if fuel_elem is None or fuel_elem.text != 'electricity':
            # Update to Electric
            if fuel_elem is not None:
                fuel_elem.text = 'electricity'
            else:
                ET.SubElement(dryer, f'{ns}FuelType').text = 'electricity'            
                
            # Update Extension Usage Multiplier
            ext = dryer.find(f'{ns}extension')
            if ext is None:
                ext = ET.SubElement(dryer, f'{ns}extension')
                
            um = ext.find(f'{ns}UsageMultiplier')
            if um is not None:
                um.text = dryer_config["extension"]["UsageMultiplier"]
            else:
                ET.SubElement(ext, f'{ns}UsageMultiplier').text = dryer_config["extension"]["UsageMultiplier"]

        # Update CEF
        cef_elem = dryer.find(f'{ns}CombinedEnergyFactor')
        if cef_elem is not None:
            cef_elem.text = dryer_config["CombinedEnergyFactor"]
        else:
            ET.SubElement(dryer, f'{ns}CombinedEnergyFactor').text = dryer_config["CombinedEnergyFactor"]
        
    else:
        # Dryer does not exist, add it to Appliances node
        appliances = root.find(f'.//{ns}Appliances')
        if appliances is not None:
            dryer = ET.SubElement(appliances, f'{ns}ClothesDryer')
            ET.SubElement(dryer, f'{ns}SystemIdentifier', id=dryer_id)
            ET.SubElement(dryer, f'{ns}IsSharedAppliance').text = dryer_config["IsSharedAppliance"]
            ET.SubElement(dryer, f'{ns}Location').text = dryer_config["Location"]
            ET.SubElement(dryer, f'{ns}FuelType').text = dryer_config["FuelType"]
            ET.SubElement(dryer, f'{ns}CombinedEnergyFactor').text = dryer_config["CombinedEnergyFactor"]
            ET.SubElement(dryer, f'{ns}Vented').text = dryer_config["Vented"]
            ET.SubElement(dryer, f'{ns}VentedFlowRate').text = dryer_config["VentedFlowRate"]
            
            ext = ET.SubElement(dryer, f'{ns}extension')
            ET.SubElement(ext, f'{ns}UsageMultiplier').text = dryer_config["extension"]["UsageMultiplier"]
            ET.SubElement(ext, f'{ns}WeekdayScheduleFractions').text = dryer_config["extension"]["WeekdayScheduleFractions"]
            ET.SubElement(ext, f'{ns}WeekendScheduleFractions').text = dryer_config["extension"]["WeekendScheduleFractions"]
            ET.SubElement(ext, f'{ns}MonthlyScheduleMultipliers').text = dryer_config["extension"]["MonthlyScheduleMultipliers"]

    # --- 2. HANDLE SERVICE FEEDER ---
    all_feeders = root.findall(f'.//{ns}ServiceFeeder')
    max_feeder_num = 0
    feeder_exists = False
    feeder_parent = None

    for f in all_feeders:
        # Locate the highest existing ServiceFeeder ID number
        sys_id = f.find(f'{ns}SystemIdentifier')
        if sys_id is not None:
            fid = sys_id.get('id', '')
            match = re.search(r'\d+', fid)
            if match:
                max_feeder_num = max(max_feeder_num, int(match.group()))
        
        # Check if this feeder is already attached to our dryer
        attached = f.find(f'{ns}AttachedToComponent')
        if attached is not None and attached.get('idref') == dryer_id:
            feeder_exists = True
            # FIX: Update the existing feeder's PowerRating
            pr_elem = f.find(f'{ns}PowerRating')
            if pr_elem is not None:
                pr_elem.text = feeder_config["PowerRating"]
            else:
                ET.SubElement(f, f'{ns}PowerRating').text = feeder_config["PowerRating"]

        if feeder_parent is None:
            feeder_parent = parent_map.get(f)

    # Add the new service feeder if one does not exist for the dryer
    if not feeder_exists:
        if feeder_parent is None:
            # Fallback if there are completely zero ServiceFeeders in the document
            feeder_parent = root.find(f'.//{ns}ElectricalLoadCenter')
            
        if feeder_parent is not None:
            new_feeder = ET.SubElement(feeder_parent, f'{ns}ServiceFeeder')
            ET.SubElement(new_feeder, f'{ns}SystemIdentifier', id=f'ServiceFeeder{max_feeder_num + 1}')
            ET.SubElement(new_feeder, f'{ns}LoadType').text = feeder_config["LoadType"]
            ET.SubElement(new_feeder, f'{ns}PowerRating').text = feeder_config["PowerRating"]
            ET.SubElement(new_feeder, f'{ns}IsNewLoad').text = feeder_config["IsNewLoad"]
            ET.SubElement(new_feeder, f'{ns}AttachedToComponent', idref=dryer_id)

    # --- 3. HANDLE BRANCH CIRCUIT ---
    if branch_config:
        all_circuits = root.findall(f'.//{ns}BranchCircuit')
        max_circuit_num = 0
        circuit_exists = False
        circuit_parent = None

        for c in all_circuits:
            sys_id = c.find(f'{ns}SystemIdentifier')
            if sys_id is not None:
                cid = sys_id.get('id', '')
                match = re.search(r'\d+', cid)
                if match:
                    max_circuit_num = max(max_circuit_num, int(match.group()))
            
            # Check if this circuit is already attached to our dryer
            attached = c.find(f'{ns}AttachedToComponent')
            if attached is not None and attached.get('idref') == dryer_id:
                circuit_exists = True
                
                # Calculate and update existing circuit values
                power = float(feeder_config["PowerRating"])
                voltage = float(branch_config["Voltage"])
                max_current = str(power / voltage)
                
                for tag, val in [('Voltage', branch_config["Voltage"]), 
                                 ('MaxCurrentRating', max_current), 
                                 ('OccupiedSpaces', branch_config["OccupiedSpaces"])]:
                    elem = c.find(f'{ns}{tag}')
                    if elem is not None:
                        elem.text = val
                    else:
                        ET.SubElement(c, f'{ns}{tag}').text = val

            if circuit_parent is None:
                circuit_parent = parent_map.get(c)

        if not circuit_exists:
            if circuit_parent is None:
                circuit_parent = root.find(f'.//{ns}ElectricalLoadCenter')
                
            if circuit_parent is not None:
                new_circuit = ET.SubElement(circuit_parent, f'{ns}BranchCircuit')
                ET.SubElement(new_circuit, f'{ns}SystemIdentifier', id=f'BranchCircuit{max_circuit_num + 1}')
                
                # Derive maximum current rating dynamically (Amps = Watts / Volts)
                power = float(feeder_config["PowerRating"])
                voltage = float(branch_config["Voltage"])
                max_current = str(power / voltage)

                ET.SubElement(new_circuit, f'{ns}Voltage').text = branch_config["Voltage"]
                ET.SubElement(new_circuit, f'{ns}MaximumCurrentRating').text = max_current
                ET.SubElement(new_circuit, f'{ns}OccupiedSpaces').text = branch_config["OccupiedSpaces"]
                ET.SubElement(new_circuit, f'{ns}AttachedToComponent', idref=dryer_id)


def add_ev_components(root, ns, ns_bracket, bldg_id, config, metadata_df):
    meta = get_building_metadata(bldg_id, metadata_df)
    if meta is None:
        # print(f"[Warning] Bldg {bldg_id}: Metadata row check failed. Skipping.")
        return
    
    # 1. Determine Charger Level
    rand_val = random.random()
    rates = config["ChargerAdoptionRates"]
    if rand_val < rates["Level1"]:
        charger_level = "1"
    elif rand_val < rates["Level1"] + rates["Level2"]:
        charger_level = "2"
    else:
        # print(f"[Info] Bldg {bldg_id}: No charger chosen based on adoption rates (Rolled {rand_val:.3f}). Skipping.")
        return # No charger chosen

    charger_config = config["ChargerDetails"][charger_level]
    
    # Extract Metadata
    veh_type = meta.get('in.electric_vehicle_battery', None)
    
    # Clean string to avoid silent mismatches due to hidden spaces in CSV
    if isinstance(veh_type, str):
        veh_type = veh_type.strip()
        
    miles_yr = meta.get('in.electric_vehicle_miles_traveled', 11000.0)
    charge_loc = meta.get('in.electric_vehicle_charge_at_home', '80-99%')
    
    # Print exactly what is triggering the skip if the vehicle type doesn't match
    if pd.isna(veh_type):
        print(f"[Warning] Bldg {bldg_id}: 'in.electric_vehicle_battery' is missing or NaN in CSV. Skipping.")
        return
    if veh_type not in config["VehicleSpecs"]:
        print(f"[Warning] Bldg {bldg_id}: veh_type '{veh_type}' not found in VehicleSpecs config dictionary. Skipping.")
        return
    
    veh_specs = config["VehicleSpecs"][veh_type]
    charge_frac = parse_charge_fraction(charge_loc)
    
    # Average driving speed is 22mph (derived from matching hours to miles from sample data)
    hours_week = float(miles_yr) / 365.0 * 7.0 / 22.0

    # --- 2. Find Correct Parent Node (Systems) ---
    # HPXML standard places EV elements inside <Systems>
    parent_node = root.find(f'.//{ns}Systems')
    
    # Fallback to BuildingDetails if Systems somehow doesn't exist
    if parent_node is None:
        parent_node = root.find(f'.//{ns}BuildingDetails')
        # print(f"[Info] Bldg {bldg_id}: <Systems> not found, falling back to <BuildingDetails>.")
        
    if parent_node is None:
        # print(f"[Warning] Bldg {bldg_id}: Neither <Systems> nor <BuildingDetails> found. Skipping.")
        return

    # --- 3. Create or Locate Elements Independently ---
    vehicles_node = root.find(f'.//{ns}Vehicles')
    if vehicles_node is None:
        # print(f"[Info] Bldg {bldg_id}: Creating new <Vehicles> node.")
        vehicles_node = ET.Element(f'{ns}Vehicles')
    else:
        # print(f"[Info] Bldg {bldg_id}: Existing <Vehicles> node found. Overwriting contents.")
        for child in list(vehicles_node):
            vehicles_node.remove(child)

    chargers_node = root.find(f'.//{ns}ElectricVehicleChargers')
    charger_id = 'EVCharger1'
    if chargers_node is None:
        # print(f"[Info] Bldg {bldg_id}: Creating new <ElectricVehicleChargers> node.")
        chargers_node = ET.Element(f'{ns}ElectricVehicleChargers')
    else:
        # print(f"[Info] Bldg {bldg_id}: Existing <ElectricVehicleChargers> node found. Overwriting contents.")
        for child in list(chargers_node):
            chargers_node.remove(child)

    # --- 4. Build Charger Properties ---
    charger_elem = ET.SubElement(chargers_node, f'{ns}ElectricVehicleCharger')
    ET.SubElement(charger_elem, f'{ns}SystemIdentifier', id=charger_id)
    ET.SubElement(charger_elem, f'{ns}ChargingLevel').text = charger_level
    ET.SubElement(charger_elem, f'{ns}ChargingPower').text = charger_config["ChargingPower"]

    # --- 5. Build Vehicle Properties ---
    veh_elem = ET.SubElement(vehicles_node, f'{ns}Vehicle')
    ET.SubElement(veh_elem, f'{ns}SystemIdentifier', id='Vehicle1')
    
    veh_type_elem = ET.SubElement(veh_elem, f'{ns}VehicleType')
    bev = ET.SubElement(veh_type_elem, f'{ns}BatteryElectricVehicle')
    
    batt = ET.SubElement(bev, f'{ns}Battery')
    ET.SubElement(batt, f'{ns}BatteryType').text = 'Li-ion'
    
    nom = ET.SubElement(batt, f'{ns}NominalCapacity')
    ET.SubElement(nom, f'{ns}Units').text = 'kWh'
    ET.SubElement(nom, f'{ns}Value').text = veh_specs["NominalCapacity"]
    
    usable = ET.SubElement(batt, f'{ns}UsableCapacity')
    ET.SubElement(usable, f'{ns}Units').text = 'kWh'
    ET.SubElement(usable, f'{ns}Value').text = veh_specs["UsableCapacity"]
    
    ET.SubElement(batt, f'{ns}NominalVoltage').text = '50.0'
    
    fcl = ET.SubElement(bev, f'{ns}FractionChargedLocation')
    ET.SubElement(fcl, f'{ns}Location').text = 'Home'
    ET.SubElement(fcl, f'{ns}Percentage').text = str(charge_frac)
    
    ET.SubElement(bev, f'{ns}ConnectedCharger', idref=charger_id)
    
    ext = ET.SubElement(bev, f'{ns}extension')
    ET.SubElement(ext, f'{ns}WeekdayScheduleFractions').text = "0.0714, 0.0714, 0.0714, 0.0714, 0.0714, 0.0714, 0.0714, -0.3535, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -0.3221, -0.3244, 0.0714, 0.0714, 0.0714, 0.0714, 0.0714, 0.0714, 0.0714"
    ET.SubElement(ext, f'{ns}WeekendScheduleFractions').text = "0.0588, 0.0588, 0.0588, 0.0588, 0.0588, 0.0588, 0.0588, 0.0588, 0.0588, -0.3334, 0, 0, 0, 0, -0.3293, -0.3372, 0.0588, 0.0588, 0.0588, 0.0588, 0.0588, 0.0588, 0.0588, 0.0588"
    ET.SubElement(ext, f'{ns}MonthlyScheduleMultipliers').text = "1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0"
    
    ET.SubElement(veh_elem, f'{ns}MilesDrivenPerYear').text = str(miles_yr)
    ET.SubElement(veh_elem, f'{ns}HoursDrivenPerWeek').text = str(hours_week)
    
    fec = ET.SubElement(veh_elem, f'{ns}FuelEconomyCombined')
    ET.SubElement(fec, f'{ns}Units').text = 'kWh/mile'
    ET.SubElement(fec, f'{ns}Value').text = veh_specs["FuelEconomy"]

    # --- 6. Append & Enforce Schema Order on Systems Node ---
    if vehicles_node not in list(parent_node):
        parent_node.append(vehicles_node)
        # print(f"[Info] Bldg {bldg_id}: Appended <Vehicles> to parent.")
    if chargers_node not in list(parent_node):
        parent_node.append(chargers_node)
        # print(f"[Info] Bldg {bldg_id}: Appended <ElectricVehicleChargers> to parent.")
        
    sort_hpxml_node(parent_node, SYSTEMS_ORDER)

    # --- 7. Service Feeder & Branch Circuit ---
    circuit_parent = root.find(f'.//{ns}ElectricalLoadCenter')
    
    # Fallback for newer HPXML versions utilizing ElectricPanels
    if circuit_parent is None:
        circuit_parent = root.find(f'.//{ns}ElectricPanel')
        if circuit_parent is not None:
            # print(f"[Info] Bldg {bldg_id}: <ElectricalLoadCenter> missing. Falling back to <ElectricPanel>.")
            return
    
    if circuit_parent is not None:
        # Determine targets (some HPXML versions use wrapper nodes, some don't)
        branch_wrapper = circuit_parent.find(f'{ns}BranchCircuits')
        circuit_target = branch_wrapper if branch_wrapper is not None else circuit_parent
        
        feeder_wrapper = circuit_parent.find(f'{ns}ServiceFeeders')
        feeder_target = feeder_wrapper if feeder_wrapper is not None else circuit_parent

        all_circuits = root.findall(f'.//{ns}BranchCircuit')
        max_c_num = max([int(re.search(r'\d+', c.find(f'{ns}SystemIdentifier').get('id', '0')).group()) for c in all_circuits if c.find(f'{ns}SystemIdentifier') is not None] + [0])
        circuit_exists = any(c.find(f'{ns}AttachedToComponent') is not None and c.find(f'{ns}AttachedToComponent').get('idref') == charger_id for c in all_circuits)
        
        # Insert Branch Circuit first to respect schema load center sequence
        if not circuit_exists:
            new_circuit = ET.SubElement(circuit_target, f'{ns}BranchCircuit')
            ET.SubElement(new_circuit, f'{ns}SystemIdentifier', id=f'BranchCircuit{max_c_num + 1}')
            ET.SubElement(new_circuit, f'{ns}Voltage').text = charger_config["Voltage"]
            ET.SubElement(new_circuit, f'{ns}MaximumCurrentRating').text = charger_config["MaxCurrentRating"]
            ET.SubElement(new_circuit, f'{ns}OccupiedSpaces').text = charger_config["OccupiedSpaces"]
            ET.SubElement(new_circuit, f'{ns}AttachedToComponent', idref=charger_id)
            # print(f"[Info] Bldg {bldg_id}: Added new BranchCircuit.")
        else:
            # print(f"[Info] Bldg {bldg_id}: BranchCircuit already exists for {charger_id}.")
            return


        all_feeders = root.findall(f'.//{ns}ServiceFeeder')
        max_f_num = max([int(re.search(r'\d+', f.find(f'{ns}SystemIdentifier').get('id', '0')).group()) for f in all_feeders if f.find(f'{ns}SystemIdentifier') is not None] + [0])
        feeder_exists = any(f.find(f'{ns}AttachedToComponent') is not None and f.find(f'{ns}AttachedToComponent').get('idref') == charger_id for f in all_feeders)
        
        if not feeder_exists:
            new_feeder = ET.SubElement(feeder_target, f'{ns}ServiceFeeder')
            ET.SubElement(new_feeder, f'{ns}SystemIdentifier', id=f'ServiceFeeder{max_f_num + 1}')
            ET.SubElement(new_feeder, f'{ns}LoadType').text = 'electric vehicle charging'
            ET.SubElement(new_feeder, f'{ns}PowerRating').text = charger_config["ChargingPower"]
            ET.SubElement(new_feeder, f'{ns}IsNewLoad').text = "false"
            ET.SubElement(new_feeder, f'{ns}AttachedToComponent', idref=charger_id)
            # print(f"[Info] Bldg {bldg_id}: Added new ServiceFeeder.")
        else:
            # print(f"[Info] Bldg {bldg_id}: ServiceFeeder already exists for {charger_id}.")
            return

        # Enforce exact XML child sequence on the Electric Panel/Load Center 
        sort_hpxml_node(circuit_parent, ELEC_ORDER)
    else:
        # print(f"[Warning] Bldg {bldg_id}: No <ElectricalLoadCenter> or <ElectricPanel> found! Cannot attach BranchCircuit or ServiceFeeder.")
        return
        
    # print(f"[Success] Bldg {bldg_id}: Successfully processed EV components.")

def convert_ev(root, xml_filename, config, metadata_df):
    """Parses bldg_id from the parent folder name and routes to ev component adder"""
    ns_match = re.match(r'\{.*\}', root.tag)
    ns_bracket = ns_match.group(0) if ns_match else ''
    
    # Extract the name of the folder containing home.xml (e.g., 'bldg0000062-up00')
    parent_folder_name = xml_filename.parent.name
    
    # Search for the building ID in the folder name
    match = re.search(r'\d+', parent_folder_name)
    
    if match:
        bldg_id = match.group()
        # print(f"\n--- Processing {parent_folder_name}/{xml_filename.name} (Extracted ID: {int(bldg_id)}) ---")
        add_ev_components(root, ns_bracket, ns_bracket, bldg_id, config, metadata_df)
    else:
        print(f"[Warning] Could not extract numeric bldg_id from path: {xml_filename}")


# ---------------------------------------------------------
# DUPLICATION LOGIC
# ---------------------------------------------------------
def duplicate_directories(input_dir, output_dir):
    """Safely copies the entire directory structure over."""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    
    if not input_path.exists():
        print(f"Error: Could not find input directory at {input_path.resolve()}")
        return False

    # print(f"Copying files from '{input_path.name}' to '{output_path.name}'...")
    if output_path.exists():
        shutil.copytree(input_path, output_path, dirs_exist_ok=True)
    else:
        shutil.copytree(input_path, output_path)
    return True

# ---------------------------------------------------------
# MAIN EXECUTION BLOCK
# ---------------------------------------------------------
# if __name__ == "__main__":
#     print("Starting OCHRE HPXML batch update...")
    
#     # 1. Duplicate the directory once
#     success = duplicate_directories(INPUT_DIR, OUTPUT_DIR)
    
#     if success:
#         # 2. Iterate through the newly created output directory
#         output_path = Path(OUTPUT_DIR)
        
#         for xml_file in output_path.rglob('*.xml'):
            
#             try:
#                 # Dynamically register namespaces
#                 for event, (prefix, uri) in ET.iterparse(xml_file, events=['start-ns']):
#                     ET.register_namespace(prefix, uri)
                
#                 tree = ET.parse(xml_file)
#                 root = tree.getroot()
                
#                 # ==========================================
#                 # TURN UPDATES ON OR OFF HERE
#                 # ==========================================
                
#                 if DEVICES["device_conversion"]["HPWH"] == "ON":
#                     convert_HPWH(root, HPWH_CONVERSION_CONFIG)
                
#                 if DEVICES["device_conversion"]["ERWH"] == "ON":
#                     convert_ERWH(root, ERWH_CONVERSION_CONFIG)

#                 if DEVICES["device_conversion"]["HVAC"] == "ON":
#                     convert_HVAC(root, HVAC_CONVERSION_CONFIG)

#                 if DEVICES["device_conversion"]["Dryer"] == "ON":
#                     convert_dryer(root, DRYER_CONVERSION_CONFIG)

#                 if DEVICES["device_conversion"]["EV"] == "ON":
#                     convert_ev(root, xml_file, EV_CONVERSION_CONFIG)

                
#                 # ==========================================
                
#                 # Apply pretty-print formatting to the tree
#                 if hasattr(ET, 'indent'):
#                     ET.indent(tree, space="  ", level=0)

#                 # Write changes back to the duplicated file
#                 tree.write(xml_file, encoding='UTF-8', xml_declaration=True)
                
#             except ET.ParseError as e:
#                 print(f"Failed to parse XML for {xml_file}: {e}")
#             except Exception as e:
#                 print(f"An error occurred while processing {xml_file}: {e}")

#         print("Batch update complete.")


def capability_fields():
    """Return independent capability dictionaries for each device."""
    return {
        "control": {
            "can_schedule": None,
            "app_exists": None,
            "wireless_connection": None,
            "connect_to_tou_data": None,
        },
        "interoperability": {
            "open_standard": None,
            "ucm_dcm_ready": None,
            "compliant": None,
            "data_conformant": None,
            "shift_conformant": None,
        },
    }


device_parameters = {
    "HPWH": {
        "physical": {
            "rated_compressor_power_w": None,
            "rated_resistance_element_power_w": None,
            "tank_volume_gal": None,
            "rated_efficiency": {
                "type": "COP",   # Rated heat-pump coefficient of performance
                "value": None,
            },
            "heating_capacity_btu_per_hr": None,
        },
        "controller": {
            "max_water_temperature_f": None,
            "min_water_temperature_f": None,
            "response_time_s": None,
            "control_interval_s": None,
        },
        **capability_fields(),
    },

    "ERWH": {
        "physical": {
            "heating_element_power_w": None,
            "tank_volume_gal": None,
            "heating_capacity_btu_per_hr": None,
        },
        "controller": {
            "max_water_temperature_f": None,
            "min_water_temperature_f": None,
            "response_time_s": None,
            "control_interval_s": None,
        },
        **capability_fields(),
    },

    "HVAC": {
        "physical": {
            "rated_electrical_power_w": None,
            "heating_capacity_btu_per_hr": None,
            "cooling_capacity_btu_per_hr": None,
            "effective_building_thermal_capacity_kwh_per_f": None,
        },
        "controller": {
            "minimum_modulation_pct": None,
            "max_indoor_temperature_f": None,
            "min_indoor_temperature_f": None,
            "response_time_s": None,
            "control_interval_s": None,
        },
        **capability_fields(),
    },

    "EV": {
        "physical": {
            "rated_charging_power_kw": None,
            "maximum_battery_capacity_kwh": None,
            "charging_efficiency_pct": None,
        },
        "controller": {
            "usable_battery_flexibility_pct": None,
            "response_time_s": None,
            "control_interval_s": None,
        },
        **capability_fields(),
    },

    "Dryer": {
        "physical": {
            "rated_power_kw": None,
            "cycle_energy_kwh": None,
            "typical_cycle_duration_min": None,
        },
        "controller": {
            "maximum_deferral_time_min": None,
            "response_time_s": None,
            "control_interval_s": None,
        },
        **capability_fields(),
    },
}

def build_device_config(device_type, parameters):
    """Translate one device's calculator inputs into an A3 config."""
    defaults = {
        "HPWH": HPWH_CONVERSION_CONFIG,
        "ERWH": ERWH_CONVERSION_CONFIG,
        "HVAC": HVAC_CONVERSION_CONFIG,
        "EV": EV_CONVERSION_CONFIG,
        "Dryer": DRYER_CONVERSION_CONFIG,
        "Battery": {},
    }

    if device_type not in defaults:
        raise ValueError(f"Unknown device type: {device_type}")

    if not isinstance(parameters, dict):
        raise TypeError("parameters must be a dictionary")

    allowed_sections = {
        "physical", "controller", "control", "interoperability"
    }
    unknown_sections = set(parameters) - allowed_sections
    if unknown_sections:
        raise ValueError(
            f"Unknown parameter sections: {sorted(unknown_sections)}"
        )

    for section in allowed_sections:
        if not isinstance(parameters.get(section, {}), dict):
            raise TypeError(f"{section} must be a dictionary")

    config = deepcopy(defaults[device_type])
    physical = parameters.get("physical", {})
    applied = {}

    allowed_physical = {
        "HPWH": {
            "rated_compressor_power_w",
            "rated_resistance_element_power_w",
            "tank_volume_gal",
            "rated_efficiency",
            "heating_capacity_btu_per_hr",
        },
        "ERWH": {
            "heating_element_power_w",
            "tank_volume_gal",
            "heating_capacity_btu_per_hr",
        },
        "HVAC": {
            "rated_electrical_power_w",
            "heating_capacity_btu_per_hr",
            "cooling_capacity_btu_per_hr",
            "effective_building_thermal_capacity_kwh_per_f",
        },
        "EV": {
            "rated_charging_power_kw",
            "maximum_battery_capacity_kwh",
            "charging_efficiency_pct",
        },
        "Dryer": {
            "rated_power_kw",
            "cycle_energy_kwh",
            "typical_cycle_duration_min",
        },
        "Battery": {"rated_power_kw", "usable_energy_capacity_kwh"},
    }

    unknown = set(physical) - allowed_physical[device_type]
    if unknown:
        raise ValueError(
            f"Unknown {device_type} physical parameters: {sorted(unknown)}"
        )

    def number(key):
        value = physical.get(key)
        if value is None:
            return None

        if isinstance(value, bool):
            raise ValueError(f"{key} must be numeric")

        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be finite and positive")

        return value

    def assign(target, key, xml_key, multiplier=1.0, as_text=False):
        value = number(key)
        if value is None:
            return

        converted = value * multiplier
        target[xml_key] = str(converted) if as_text else converted
        applied[key] = value

    if device_type == "HPWH":
        conv = config["HPWH_Conversion"]

        assign(conv, "tank_volume_gal", "TankVolume")
        assign(
            conv,
            "heating_capacity_btu_per_hr",
            "HeatingCapacity",
        )
        assign(
            conv,
            "rated_resistance_element_power_w",
            "BackupHeatingCapacity",
            multiplier=3.412141633,
        )

        efficiency = physical.get("rated_efficiency")
        if efficiency is not None:
            if not isinstance(efficiency, dict):
                raise TypeError("rated_efficiency must be a dictionary")

            if set(efficiency) - {"type", "value"}:
                raise ValueError("Unknown rated_efficiency field")

            kind = efficiency.get("type")
            value = efficiency.get("value")

            if kind is not None or value is not None:
                if kind != "COP" or value is None:
                    raise ValueError(
                        "Supply efficiency type COP and a value"
                    )

                if isinstance(value, bool):
                    raise ValueError("Efficiency must be numeric")

                value = float(value)
                if not math.isfinite(value) or value <= 0:
                    raise ValueError("Efficiency must be positive")

                # COP is applied through OCHRE runtime equipment settings.

    elif device_type == "ERWH":
        conv = config["ERWH_Conversion"]
        assign(conv, "tank_volume_gal", "TankVolume")

        element_w = number("heating_element_power_w")
        capacity = number("heating_capacity_btu_per_hr")

        if element_w is not None:
            # Use electrical element power as the authoritative input.
            derived_capacity = element_w * 3.412141633

            if capacity is not None and not math.isclose(
                capacity, derived_capacity, rel_tol=0.02
            ):
                raise ValueError(
                    "ERWH heating capacity conflicts with element power"
                )

            conv["HeatingCapacity"] = derived_capacity
            applied["heating_element_power_w"] = element_w

            if capacity is not None:
                applied["heating_capacity_btu_per_hr"] = capacity

        elif capacity is not None:
            conv["HeatingCapacity"] = capacity
            applied["heating_capacity_btu_per_hr"] = capacity

    elif device_type == "HVAC":
        conv = config["HVAC_Conversion"]

        # Preserve existing defaults when no override is supplied.
        conv["HeatingCapacity"] = conv["Capacity"]
        conv["CoolingCapacity"] = conv["Capacity"]

        assign(
            conv,
            "heating_capacity_btu_per_hr",
            "HeatingCapacity",
        )
        assign(
            conv,
            "cooling_capacity_btu_per_hr",
            "CoolingCapacity",
        )

    elif device_type == "EV":
        power_kw = number("rated_charging_power_kw")
        if power_kw is not None:
            for details in config["ChargerDetails"].values():
                power_w = power_kw * 1000.0
                voltage = float(details["Voltage"])

                details["ChargingPower"] = str(power_w)
                details["MaxCurrentRating"] = str(power_w / voltage)

            applied["rated_charging_power_kw"] = power_kw

        # Battery capacity needs a separate nominal/usable policy.
        # Keep it in the returned runtime inputs for now.

    elif device_type == "Dryer":
        assign(
            config["ServiceFeeder"],
            "rated_power_kw",
            "PowerRating",
            multiplier=1000.0,
            as_text=True,
        )

    remaining_physical = {
        key: deepcopy(value)
        for key, value in physical.items()
        if key not in applied
        and value is not None
        and not (
            isinstance(value, dict)
            and all(v is None for v in value.values())
        )
    }

    runtime_parameters = {
        "physical": remaining_physical,
        "controller": deepcopy(parameters.get("controller", {})),
        "control": deepcopy(parameters.get("control", {})),
        "interoperability": deepcopy(
            parameters.get("interoperability", {})
        ),
    }

    return config, applied, runtime_parameters


def main(
    device_type,
    parameters,
    input_dir=INPUT_DIR,
    output_dir=OUTPUT_DIR,
    metadata_path=METADATA_DIR,
):
    """Copy building inputs and parameterize one flex-load type."""
    config, applied, runtime_parameters = build_device_config(
        device_type, parameters
    )

    input_path = Path(input_dir).resolve()
    output_path = Path(output_dir).resolve()

    if not input_path.is_dir():
        raise FileNotFoundError(input_path)

    # Avoid copying a directory into itself or an overlapping tree.
    if (
        input_path == output_path
        or input_path in output_path.parents
        or output_path in input_path.parents
    ):
        raise ValueError("Input and output directories must not overlap")

    # Identify source files before copying so stale output XMLs
    # from older runs are not included in this run.
    source_xmls = sorted(input_path.rglob("*.xml"))
    if not source_xmls:
        raise ValueError(f"No XML files found in {input_path}")

    metadata_df = None
    if device_type == "EV":
        metadata_df = pd.read_csv(metadata_path, low_memory=False)

    if not duplicate_directories(input_path, output_path):
        raise RuntimeError("Could not copy building input files")

    converters = {
        "HPWH": convert_HPWH,
        "ERWH": convert_ERWH,
        "HVAC": convert_HVAC,
        "Dryer": convert_dryer,
    }

    processed_files = 0
    failures = []

    with tqdm(
        total=len(source_xmls),
        desc="A3 preparing XML files",
        unit="file",
        file=sys.__stderr__,
        dynamic_ncols=True,
        bar_format=(
            "{desc}: {percentage:3.0f}%|{bar}| "
            "{n_fmt}/{total_fmt} "
            "[Elapsed: {elapsed} | ETR: {remaining}]"
        ),
    ) as progress:
        for source_xml in source_xmls:
            if device_type == "Battery":
                # B1/B2 supply the battery directly as an OCHRE equipment override.
                progress.update(1)
                continue
            xml_file = output_path / source_xml.relative_to(input_path)

            try:
                for _, (prefix, uri) in ET.iterparse(
                    xml_file, events=["start-ns"]
                ):
                    ET.register_namespace(prefix, uri)

                tree = ET.parse(xml_file)
                root = tree.getroot()

                if device_type == "EV":
                    convert_ev(
                        root, xml_file, config, metadata_df
                    )
                else:
                    converters[device_type](root, config)

                ET.indent(tree, space="  ")
                tree.write(
                    xml_file,
                    encoding="UTF-8",
                    xml_declaration=True,
                )
                processed_files += 1

            except (ET.ParseError, OSError, ValueError, KeyError) as exc:
                failures.append(f"{xml_file}: {exc}")
            progress.update(1)

    if failures:
        raise RuntimeError(
            "A3 preparation failed:\n- " + "\n- ".join(failures)
        )

    return {
        "device_type": device_type,
        "output_dir": str(output_path),
        "processed_files": processed_files,
        "parameters_applied": applied,
        "runtime_parameters_not_applied": runtime_parameters,
    }
