# Revised OSeMOSYS scenario workflow scripts v2

These scripts preserve your existing workflow but harden the country-by-country OSeMOSYS execution for 14 countries and 10+ scenarios.

## What changed in v2

- Fixed empty `audit.csv` handling. Scenarios with zero flagged countries are now skipped safely.
- Fixed `build_revised_demand_inputs.py` so it reads the `over_5pct_summary` sheet and only processes real `(% of 2040)` columns.
- Prevented PJ value columns such as `Reference 2040 (PJ)` from being treated as scenario percentage columns.
- Kept the OSeMOSYS custom demand path as:

```text
external/osemosys_global/resources/data/custom/specified_annual_demand.csv
```

## Recommended test command

```bash
python scripts/run_full_workflow.py --skip-existing --only-countries ZAF --dry-run
```

## Recommended production command

```bash
python scripts/run_full_workflow.py --skip-existing --cores 1 --continue-on-error
```

## Skip preprocessing after the generated demand files are correct

```bash
python scripts/run_full_workflow.py --skip-preprocessing --skip-existing --cores 1 --continue-on-error
```

## Expected outputs

```text
outputs/scenario_runs/<scenario_name>/<ISO3>/
    specified_annual_demand.csv
    config_used.yaml
    config_original.yaml
    snakemake.log
    results/
```

The batch log is saved to:

```text
outputs/scenario_run_log.csv
```
