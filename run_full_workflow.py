from pathlib import Path
import shutil
import subprocess
import sys
import yaml
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
OG_REPO = REPO_ROOT / "external" / "osemosys_global"

GENERATED_DIR = REPO_ROOT / "data" / "generated"
OUTPUT_RUNS_DIR = REPO_ROOT / "outputs" / "scenario_runs"

OG_CONFIG = OG_REPO / "config" / "config.yaml"
OG_CUSTOM_DIR = OG_REPO / "resources" / "custom"
OG_DEMAND_FILE = OG_CUSTOM_DIR / "specified_annual_demand.csv"

PREPROCESSING_STEPS = [
    "scripts/convert_scenario_gwh_to_pj.py",
    "scripts/compare_scenario_pj_to_2040.py",
    "scripts/build_revised_demand_inputs.py",
]


def run_cmd(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True)


def run_preprocessing():
    for script in PREPROCESSING_STEPS:
        print(f"Running {script}")
        run_cmd([sys.executable, str(REPO_ROOT / script)], cwd=REPO_ROOT)


def read_yaml(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)


def write_yaml(path, data):
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def run_og_scenario(scenario_name, country_iso, demand_file):
    original_config = read_yaml(OG_CONFIG)

    try:
        config = original_config.copy()
        config["scenario"] = f"{scenario_name}_{country_iso}"
        config["geographic_scope"] = [country_iso]
        config["results_by_country"] = True

        write_yaml(OG_CONFIG, config)

        OG_CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(demand_file, OG_DEMAND_FILE)

        run_cmd(["snakemake", "--cores", "1"], cwd=OG_REPO)

        archive_dir = OUTPUT_RUNS_DIR / scenario_name / country_iso
        archive_dir.mkdir(parents=True, exist_ok=True)

        results_dir = OG_REPO / "results" / config["scenario"]
        if results_dir.exists():
            shutil.copytree(results_dir, archive_dir / "results", dirs_exist_ok=True)

        shutil.copy2(OG_CONFIG, archive_dir / "config.yaml")

    finally:
        write_yaml(OG_CONFIG, original_config)


def run_all_generated_scenarios():
    for scenario_dir in GENERATED_DIR.iterdir():
        if not scenario_dir.is_dir():
            continue

        scenario_name = scenario_dir.name
        demand_file = scenario_dir / "specified_annual_demand.csv"
        audit_file = scenario_dir / "audit.csv"

        if not demand_file.exists():
            print(f"Skipping {scenario_name}: missing specified_annual_demand.csv")
            continue

        if not audit_file.exists():
            print(f"Skipping {scenario_name}: missing audit.csv")
            continue

        audit = pd.read_csv(audit_file)

        for country_iso in audit["iso3"].dropna().unique():
            print(f"Running {scenario_name} for {country_iso}")
            run_og_scenario(scenario_name, country_iso, demand_file)


def main():
    OUTPUT_RUNS_DIR.mkdir(parents=True, exist_ok=True)

    run_preprocessing()
    run_all_generated_scenarios()

    print("Workflow complete.")


if __name__ == "__main__":
    main()