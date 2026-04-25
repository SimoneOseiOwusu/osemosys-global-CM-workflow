# Revised Demand Scenario Workflow

This guide explains how to run the revised demand scenario workflow, from raw data processing through to running OSeMOSYS Global simulations.

---

## Overview

The workflow follows these steps:

- Convert raw scenario data to consistent units (PJ)
- Benchmark scenarios against 2040 reference values
- Identify and adjust outlier countries
- Run updated scenarios in OSeMOSYS Global

---

## Requirements

Make sure the following are set up before running:

- Python ≥ 3.9  
- Required libraries:
  - pandas
  - openpyxl
  - pyyaml
- Snakemake installed and working  
- OSeMOSYS Global located at:
external/osemosys_global
- Correct Git branch checked out  

---

## Workflow Steps

### 1. Convert Scenario Files (GWh → PJ)

**Script:**
scripts/convert_scenario_gwh_to_pj.py

**What it does:**
- Reads raw CSVs from:
data/raw
- Converts GWh → PJ using:
1 GWh = 0.0036 PJ
- Keeps identifier columns (e.g. `iso3`)
- Renames columns to reflect PJ units
- Outputs to:
outputs/pj_converted

**Check:**
- Files exist in `outputs/pj_converted`
- Values are in PJ

---

### 2. Compare to 2040 Reference

**Script:**
scripts/compare_scenario_pj_to_2040.py

**What it does:**
- Compares scenario demand to:
data/reference/2040Values.xlsx
- Calculates:
scenario / 2040 reference (%)
- Outputs Excel files to:
outputs/pct_of_2040
- Includes:
- Detailed sheet
- Summary sheet (highlights >5%)

**Check:**
- Open an output file
- Confirm % values look correct

---

### 3. Build Revised Demand Inputs

**Script:**
scripts/build_revised_demand_inputs.py

**What it does:**
- Flags countries where deviation >5%
- Adjusts 2040 demand accordingly
- Projects forward to 2050 using original growth trend
- Generates:
  - `specified_annual_demand.csv`
  - Audit file (updated countries)

**Output location:**
data/generated

**Check:**
- Each scenario folder contains:
  - Revised demand file
  - Audit file

---

### 4. Run OSeMOSYS Global Scenarios

**Script:**
scripts/run_revised_scenarios.py

**What it does:**
- Loops through:
data/generated
- For each scenario:
- Updates config
- Copies revised demand input
- Runs model via Snakemake
- Stores outputs in:
outputs/scenario_runs
- Archives:
- Model outputs
- Logs
- Config files
- Restores original config after completion

**Check:**
- Outputs exist for each scenario-country pair
- Logs show successful runs

---

## Execution

Run from the project root:

```bash
python scripts/convert_scenario_gwh_to_pj.py
python scripts/compare_scenario_pj_to_2040.py
python scripts/build_revised_demand_inputs.py
python scripts/run_revised_scenarios.py