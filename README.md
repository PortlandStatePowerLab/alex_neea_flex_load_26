# NEEA Flex Load Calculator

Excel and Python based calculators to find the ability of a flex load to contribute to different grid services. Currently includes a Python version of the FLS for Energy Service, an XML template for flex loads for the Regulation calculator, and the VBA code for importing XML flex load files to Excel for the Regulation calculator (7/5/26).

## Contributors
Thomas: [Thomas' Repository](https://github.com/PortlandStatePowerLab/thomas_neea_flex_load_26)

Othman: [Othman's Repository](https://github.com/PortlandStatePowerLab/othman_neea_flex_load_calculator_26)

## Short Description

Currently contains (7/5/26):
* Python version of FLS from the Energy Service calculator
* VBA code for importing XML flex load files to the Excel Regulation calculator
* XML template for flex loads (for the Excel Regulation calculator) with imaginary values

## Tech Stack

* **Language:** Python, VBA, XML

## Repository Contents

* **Energy Service Calculator (Python)** - A Python version of the Energy Service calculator's FLS. Currently (7/5/26) the XML import functionality doesn't exist.
* **Regulation Calculator (Excel)** - VBA code allowing for XML files of different flex loads to be imported to the Excel Regulation calculator.
* **XML Flex Load Structure (Regulation)** - A test XML file demonstrating the expected structure of the flex load XML files that can be imported to the Excel Regulation calculator, with imaginary values.

## Getting Started

Follow these steps to set up the project locally.

### Prerequisites

List any software, tools, or global packages needed:
* Python (I used 3.11.9)
* Python's dataclasses
* Excel, with Developer tools enabled ([How to show the Developer tab](https://support.microsoft.com/en-us/office/add-ins/show-the-developer-tab))

### Installation

1. **Clone the repository:**
   ```bash
   git clone
   ```

### If I want to work on this project, where should I start from?
* **Energy Service** - Run energyserviceFLS.py
* **Regulation Calculator** - Used as reference/storage, all functionality should be inherent in Excel file.
* **XML Flex Load Structure** - Duplicate XML file structure, replacing current imaginary values with actual values for flex load under study. Eventually there will be a library of different flex loads in XML.
