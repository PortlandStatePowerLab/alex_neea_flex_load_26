"""
Author: Thomas Metzler
Updated: 7/27/2026

Adjusts Dryer properties in the XML file that OCHRE will read.
Updated to dynamically convert all systems to electric dryers
and configure matching service feeders and branch circuits.
"""

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
import re
import random  # Added for the distribution function

# ---------------------------------------------------------
# DIRECTORY SETUP
# ---------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
FL_DIR = SCRIPT_DIR.parent 
WORKING_DIR = FL_DIR.parent

INPUT_DIR = WORKING_DIR / "All Portland Input Files"
OUTPUT_DIR = WORKING_DIR / "Dryer All Portland Input Files"

# ---------------------------------------------------------
# CONFIGURATIONS
# ---------------------------------------------------------
HPWH_SIZE_CONFIG = {
    "HPWH_size": {
        # Current Volume : {"TankVolume": New Volume, "HeatingCapacity": New Capacity (BTU/hr)}
        50.0: {"TankVolume": 66.0, "HeatingCapacity": 7203.0, "UniformEnergyFactor": 3.95},
        66.0: {"TankVolume": 80.0, "HeatingCapacity": 7334.0, "UniformEnergyFactor": 3.98},
        80.0: {"TankVolume": 80.0, "HeatingCapacity": 7334.0, "UniformEnergyFactor": 3.98}
    },
}

HPWH_CONVERSION_CONFIG = {
    "HPWH_Conversion": {
        "FuelType": "electricity",
        "NewType": "heat pump water heater",
        "TankVolume": "80.0",
        "HeatingCapacity": "7334.0",
        "UniformEnergyFactor": "3.98",
        "BackupHeatingCapacity": "15355.0",
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

#Adjust weights for each size to be randomly distributed
HPWH_SIZE_DISTRIB_CONFIG = {
    "HPWH_size_distrib": [
        {"weight": 0.50, "TankVolume": 50.0, "HeatingCapacity": 6887.0, "UniformEnergyFactor": 3.78},
        {"weight": 0.20, "TankVolume": 66.0, "HeatingCapacity": 7203.0, "UniformEnergyFactor": 3.95},
        {"weight": 0.30, "TankVolume": 80.0, "HeatingCapacity": 7334.0, "UniformEnergyFactor": 3.98}
    ]
}

HPWH_MODEL_CONFIG = {
    "HPWH_model": [
        # AOSmith HPTU-50N
        {"TankVolume": 46.0, "HeatingCapacity": 1391, "UniformEnergyFactor": 3.45, "BackupHeatingCapacity": 15345.0}
    ]
}

HVAC_CONVERSION_CONFIG = {
    "HVAC_Conversion": {
        "Type": "ASHP", # "ASHP" for Air-to-Air, "MSHP" for mini-split
        "HeatPumpType": "air-to-air", # Use "air-to-air" for ASHP, "mini-split" for MSHP
        "CompressorType": "single stage", # Use "single stage" for standard ASHP, "variable speed" for MSHP
        "UnitLocation": "conditioned space", 
        "Capacity": 36000.0, # Max Capacity
        "SEER": 18.0,
        "HSPF": 10.0,
        "BackupHeatingCapacity": 36000.0,
        "HeatingAirflowCFM": 1200.0,
        "CoolingAirflowCFM": 1200.0,
        
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

# --- NEW CONFIG FOR DRYER UPDATE ---
DRYER_CONVERSION_CONFIG = {
    "AdoptionRate": 1, # % chance of updating or adding a dryer
    "ClothesDryer": {
        "IsSharedAppliance": "false",
        "Location": "conditioned space",
        "FuelType": "electricity",
        "CombinedEnergyFactor": "2.7",
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
        "PowerRating": "5760.0",
        "IsNewLoad": "false"
    },
    "BranchCircuit": {
        "Voltage": "240",
        "OccupiedSpaces": "2.0"
    }
}


# ---------------------------------------------------------
# MODIFIER FUNCTIONS
# ---------------------------------------------------------
def update_ERWH_size(root, config):
    """Updates the size of existing ERWH systems based on original size."""
    ns_match = re.match(r'\{.*\}', root.tag)
    ns_bracket = ns_match.group(0) if ns_match else ''

    for elem in root.iter():
        if elem.tag.split('}')[-1] == 'WaterHeatingSystem':
            vol_elem = None
            cap_elem = None
            ef_elem = None
            
            for child in elem:
                tag_name = child.tag.split('}')[-1]
                if tag_name == 'TankVolume':
                    vol_elem = child
                elif tag_name == 'HeatingCapacity':
                    cap_elem = child
                elif tag_name == 'UniformEnergyFactor':
                    ef_elem = child
            
            if vol_elem is not None and vol_elem.text:
                try:
                    current_vol = float(vol_elem.text.strip())
                except ValueError:
                    continue
                
                if current_vol in config["HPWH_size"]:
                    updates = config["HPWH_size"][current_vol]
                    
                    # 1. Update Tank Volume
                    vol_elem.text = str(updates["TankVolume"])
                    
                    # 2. Update Heating Capacity
                    if cap_elem is not None:
                        cap_elem.text = str(updates["HeatingCapacity"])
                    else:
                        new_cap_elem = ET.Element(f'{ns_bracket}HeatingCapacity')
                        new_cap_elem.text = str(updates["HeatingCapacity"])
                        idx = list(elem).index(vol_elem)
                        elem.insert(idx + 1, new_cap_elem)

                    # 3. Update Energy Factor
                    if ef_elem is not None:
                        ef_elem.text = str(updates["UniformEnergyFactor"])
                    else:
                        new_ef_elem = ET.Element(f'{ns_bracket}UniformEnergyFactor')
                        new_ef_elem.text = str(updates["UniformEnergyFactor"])
                        idx = list(elem).index(vol_elem)
                        elem.insert(idx + 2, new_ef_elem)

def distribute_HPWH_size(root, config):
    """Updates HPWH size based on a weighted random distribution."""
    ns_match = re.match(r'\{.*\}', root.tag)
    ns_bracket = ns_match.group(0) if ns_match else ''

    dist_data = config["HPWH_size_distrib"]
    # Extract the weights to feed into the random choice
    weights = [item["weight"] for item in dist_data]

    for elem in root.iter():
        if elem.tag.split('}')[-1] == 'WaterHeatingSystem':
            vol_elem = None
            cap_elem = None
            ef_elem = None
            
            for child in elem:
                tag_name = child.tag.split('}')[-1]
                if tag_name == 'TankVolume':
                    vol_elem = child
                elif tag_name == 'HeatingCapacity':
                    cap_elem = child
                elif tag_name == 'UniformEnergyFactor':
                    ef_elem = child
            
            # As long as there is an existing water heater to update
            if vol_elem is not None and vol_elem.text:
                # Select a new configuration based on the defined weights
                chosen_update = random.choices(dist_data, weights=weights, k=1)[0]
                
                # 1. Update Tank Volume
                vol_elem.text = str(chosen_update["TankVolume"])
                
                # 2. Update Heating Capacity
                if cap_elem is not None:
                    cap_elem.text = str(chosen_update["HeatingCapacity"])
                else:
                    new_cap_elem = ET.Element(f'{ns_bracket}HeatingCapacity')
                    new_cap_elem.text = str(chosen_update["HeatingCapacity"])
                    idx = list(elem).index(vol_elem)
                    elem.insert(idx + 1, new_cap_elem)
                
                # 3. Update Energy Factor
                if ef_elem is not None:
                    ef_elem.text = str(chosen_update["UniformEnergyFactor"])
                else:
                    new_ef_elem = ET.Element(f'{ns_bracket}UniformEnergyFactor')
                    new_ef_elem.text = str(chosen_update["UniformEnergyFactor"])
                    idx = list(elem).index(vol_elem)
                    elem.insert(idx + 2, new_ef_elem)

def convert_to_HPWH(root, config):
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

def convert_single_model(root, config):
    """Converts all HPWH to a single model."""
    ns_match = re.match(r'\{.*\}', root.tag)
    ns_bracket = ns_match.group(0) if ns_match else ''
    
    # Access the first item in the list
    model_data = config["HPWH_model"][0]

    for elem in root.iter():
        if elem.tag.split('}')[-1] == 'WaterHeatingSystem':
            type_elem = None
            cap_elem = None
            ef_elem = None
            vol_elem = None
            backheat_elem = None
            
            # Locate identifying elements using exact match
            for child in elem:
                tag_name = child.tag.split('}')[-1]
                if tag_name == 'TankVolume':
                    vol_elem = child
                elif tag_name == 'HeatingCapacity':
                    cap_elem = child
                elif tag_name == 'UniformEnergyFactor':
                    ef_elem = child
                elif tag_name == 'BackupHeatingCapacity':
                    backheat_elem = child
            
            if vol_elem is not None and vol_elem.text:
                try:
                    current_vol = float(vol_elem.text.strip())
                except ValueError:
                    continue
                
                # 1. Update Tank Volume
                vol_elem.text = str(model_data["TankVolume"])
                    
                # 2. Update Heating Capacity
                if cap_elem is not None:
                    cap_elem.text = str(model_data["HeatingCapacity"])
                else:
                    new_cap_elem = ET.Element(f'{ns_bracket}HeatingCapacity')
                    new_cap_elem.text = str(model_data["HeatingCapacity"])
                    idx = list(elem).index(vol_elem)
                    elem.insert(idx + 1, new_cap_elem)

                # 3. Update Energy Factor
                if ef_elem is not None:
                    ef_elem.text = str(model_data["UniformEnergyFactor"])
                else:
                    new_ef_elem = ET.Element(f'{ns_bracket}UniformEnergyFactor')
                    new_ef_elem.text = str(model_data["UniformEnergyFactor"])
                    idx = list(elem).index(vol_elem)
                    elem.insert(idx + 2, new_ef_elem)

                # 4. Update Backup Heating
                if backheat_elem is not None:
                    backheat_elem.text = str(model_data["BackupHeatingCapacity"])
                else:
                    new_backheat_elem = ET.Element(f'{ns_bracket}BackupHeatingCapacity')
                    new_backheat_elem.text = str(model_data["BackupHeatingCapacity"])
                    idx = list(elem).index(vol_elem)
                    elem.insert(idx + 3, new_backheat_elem)

def convert_to_HeatPump(root, config):
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
        ET.SubElement(hp, f'{ns}HeatingCapacity').text = str(conv["Capacity"])
        ET.SubElement(hp, f'{ns}CoolingCapacity').text = str(conv["Capacity"])
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
                calc_capacity = round(conv["Capacity"] * pt["CapacityRatio"], 1)
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
                calc_capacity = round(conv["Capacity"] * pt["CapacityRatio"], 1)
                ET.SubElement(pdp, f'{ns}Capacity').text = str(calc_capacity)
                ET.SubElement(pdp, f'{ns}CapacityDescription').text = pt["Desc"]
                
                eff = ET.SubElement(pdp, f'{ns}Efficiency')
                ET.SubElement(eff, f'{ns}Units').text = 'COP'
                ET.SubElement(eff, f'{ns}Value').text = str(pt["COP"])
                
        # 5. Insert airflow extensions
        ext = ET.SubElement(hp, f'{ns}extension')
        ET.SubElement(ext, f'{ns}HeatingAirflowCFM').text = str(conv["HeatingAirflowCFM"])
        ET.SubElement(ext, f'{ns}CoolingAirflowCFM').text = str(conv["CoolingAirflowCFM"])

def convert_to_electric_dryer(root, config):
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

    print(f"Copying files from '{input_path.name}' to '{output_path.name}'...")
    if output_path.exists():
        shutil.copytree(input_path, output_path, dirs_exist_ok=True)
    else:
        shutil.copytree(input_path, output_path)
    return True

# ---------------------------------------------------------
# MAIN EXECUTION BLOCK
# ---------------------------------------------------------
if __name__ == "__main__":
    print("Starting OCHRE HPXML batch update...")
    
    # 1. Duplicate the directory once
    success = duplicate_directories(INPUT_DIR, OUTPUT_DIR)
    
    if success:
        # 2. Iterate through the newly created output directory
        output_path = Path(OUTPUT_DIR)
        
        for xml_file in output_path.rglob('*.xml'):
            
            try:
                # Dynamically register namespaces
                for event, (prefix, uri) in ET.iterparse(xml_file, events=['start-ns']):
                    ET.register_namespace(prefix, uri)
                
                tree = ET.parse(xml_file)
                root = tree.getroot()
                
                # ==========================================
                # TURN YOUR UPDATES ON OR OFF HERE
                # ==========================================
                
                # update_ERWH_size(root, HPWH_SIZE_CONFIG)
                # convert_to_HPWH(root, HPWH_CONVERSION_CONFIG)
                # distribute_HPWH_size(root, HPWH_SIZE_DISTRIB_CONFIG)
                # convert_single_model(root, HPWH_MODEL_CONFIG)
                # convert_to_HeatPump(root, HVAC_CONVERSION_CONFIG)
                convert_to_electric_dryer(root, DRYER_CONVERSION_CONFIG)
                
                # ==========================================
                
                # Apply pretty-print formatting to the tree
                if hasattr(ET, 'indent'):
                    ET.indent(tree, space="  ", level=0)

                # Write changes back to the duplicated file
                tree.write(xml_file, encoding='UTF-8', xml_declaration=True)
                
            except ET.ParseError as e:
                print(f"Failed to parse XML for {xml_file}: {e}")
            except Exception as e:
                print(f"An error occurred while processing {xml_file}: {e}")

        print("Batch update complete.")