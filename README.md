# Revised Demand Scenario Workflow

This guide explains how to run the revised demand scenario workflow, from raw data processing through to running OSeMOSYS Global simulations.

## Overview

The workflow follows these steps:

1. Convert raw scenario data to consistent units (PJ)
2. Benchmark scenarios against 2040 reference values
3. Build revised demand trajectories through 2050
4. Sense-check generated demand inputs
5. Run country-level OSeMOSYS Global optimisation scenarios

The workflow uses additive demand logic:

```text
revised demand = reference demand + scenario demand
```

For each scenario:
- 2022–2039:
  - baseline demand remains unchanged
- 2040:
  - scenario demand is added to reference demand
- 2041–2050:
  - demand grows forward from revised 2040 demand using the script’s post-2040 growth logic

---

## Requirements

Make sure the following are set up before running.

### Python

- Python ≥ 3.9

### Required libraries

- pandas
- openpyxl
- pyyaml

### Other requirements

- Snakemake installed and working
- OSeMOSYS Global cloned to:

```text
external/osemosys_global
```

- Correct OSeMOSYS Global branch checked out
- Country configuration files created under:

```text
configs/country_configs/
```

---

## OSeMOSYS Global Setup

Clone the required branch:

```bash
git clone --branch Issue-253 https://github.com/OSeMOSYS/osemosys_global.git external/osemosys_global
```

---

# Workflow Steps

## 1. Convert Scenario Files (GWh → PJ)

### Script

```text
scripts/convert_scenario_gwh_to_pj.py
```

### What it does

- Reads raw CSVs from:

```text
data/raw
```

- Converts GWh → PJ using:

```text
1 GWh = 0.0036 PJ
```

- Keeps identifier columns (e.g. ISO3)
- Renames columns to reflect PJ units

### Outputs

```text
outputs/pj_converted
```

### Run

```bash
python scripts/convert_scenario_gwh_to_pj.py
```

### Checks

- Files exist in `outputs/pj_converted`
- Values are in PJ 

---

## 2. Compare Scenario Demand to 2040 Reference Values

### Script

```text
scripts/compare_scenario_pj_to_2040.py
```

### What it does

- Compares scenario demand to:

```text
data/reference/2040Values.xlsx
```

- Calculates:

```text
scenario demand / reference 2040 demand
```

### Outputs

```text
outputs/pct_of_2040
```

Outputs include:
- detailed comparison sheets
- summary sheets

### Run

```bash
python scripts/compare_scenario_pj_to_2040.py
```

### Checks

- Open an output workbook
- Confirm percentage values look correct
- Confirm country demand magnitudes are plausible

---

## 3. Build Revised Demand Inputs

### Script

```text
scripts/build_revised_demand_inputs.py
```

### What it does

Creates revised OSeMOSYS demand trajectories using additive demand logic:

```text
revised demand = reference demand + scenario demand
```

Logic used:
- 2022–2039:
  - keep baseline demand unchanged
- 2040:
  - add scenario demand to baseline 2040 demand
- 2041–2050:
  - project forward from revised 2040 demand using the post-2040 growth logic in the script

The script generates:
- revised `specified_annual_demand.csv`
- scenario audit files

### Outputs

```text
data/generated
```

### Run

```bash
python scripts/build_revised_demand_inputs.py \
  --baseline-file data/baseline/specified_annual_demand.csv \
  --comparison-file outputs/pct_of_2040/AggregatedDemand_combined_node_locations_for_energy_conversion_country_unconstrained_pct_of_2040.xlsx \
  --clear-output
```

### Checks

Each scenario folder should contain:
- `specified_annual_demand.csv`
- `audit.csv`

Verify:
- demand extends through 2050
- no collapse after 2040
- smooth growth trajectories
- High > Mid > Low demand scenarios

---

## 4. Sense-Check Generated Demand Inputs

### Script

```text
scripts/check_generated_demand.py
```

### What it does

Checks generated demand trajectories before optimisation.

Outputs include:
- country summaries
- node summaries
- warning tables

### Outputs

```text
outputs/demand_sense_checks
```

### Run

```bash
python scripts/check_generated_demand.py --country ZAF
```

### Checks

Confirm:
- trajectories extend to 2050
- no major warnings
- smooth growth after 2040
- plausible demand magnitudes

---

## 5. Run OSeMOSYS Global Scenarios

### Script

```text
scripts/run_country_scenario_matrix.py
```

### What it does

This script loops through:
- country configuration files
- generated demand scenarios

For each run it:
- updates the OSeMOSYS Global config
- copies the revised demand input
- runs the Snakemake workflow
- archives outputs

### Outputs

```text
outputs/osemosys_config_workflow/scenario_results
```

Archives include:
- model outputs
- logs
- configuration snapshots

---

## Example Runs

### Single-country test

```bash
python scripts/run_country_scenario_matrix.py \
  --country ZAF \
  --demand-scenario Bau_2040_Low_Min_Threshold \
  --demand-scenario Bau_2040_High_Min_Threshold \
  --cores 2 \
  --force \
  --clean-between-runs \
  --overwrite-archive
```

### Multi-country run

```bash
python scripts/run_country_scenario_matrix.py \
  --country AGO \
  --country KEN \
  --country ZAF \
  --cores 4 \
  --force \
  --clean-between-runs \
  --overwrite-archive
```

### Full scenario matrix

```bash
python scripts/run_country_scenario_matrix.py \
  --cores 4 \
  --force \
  --clean-between-runs \
  --overwrite-archive
```

---

## Outputs

Scenario results are saved to:

```text
outputs/osemosys_config_workflow/scenario_results/<COUNTRY>/<SCENARIO>/
```

Important output files include:

```text
results/data/TotalCapacityAnnual.csv
results/data/ProductionByTechnologyAnnual.csv
results/data/AnnualEmissions.csv
results/data/TotalDiscountedCost.csv
```

---

## Recommended Execution Order

Run from the project root:

```bash
python scripts/convert_scenario_gwh_to_pj.py

python scripts/compare_scenario_pj_to_2040.py

python scripts/build_revised_demand_inputs.py \
  --baseline-file data/baseline/specified_annual_demand.csv \
  --comparison-file outputs/pct_of_2040/AggregatedDemand_combined_node_locations_for_energy_conversion_country_unconstrained_pct_of_2040.xlsx \
  --clear-output

python scripts/check_generated_demand.py --country ZAF

python scripts/run_country_scenario_matrix.py \
  --country ZAF \
  --demand-scenario Bau_2040_Low_Min_Threshold \
  --cores 2 \
  --force \
  --clean-between-runs \
  --overwrite-archive
```

 
 
