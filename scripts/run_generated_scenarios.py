from pathlib import Path
import shutil
import subprocess
import sys
import yaml


# ============================================================
# Paths
# ============================================================

REPO_ROOT = Path(__file__).resolve().parents[1]

OG_REPO = REPO_ROOT / "external" / "osemosys_global"

GENERATED_DIR = REPO_ROOT / "data" / "generated"
OUTPUT_RUNS_DIR = REPO_ROOT / "outputs" / "scenario_runs"

OG_CONFIG_FILE = OG_REPO / "config" / "config.yaml"

OG_CUSTOM_DEMAND_FILE = (
    OG_REPO
    / "resources"
    / "data"
    / "custom"
    / "specified_annual_demand.csv"
)


# ============================================================
# Helpers
# ============================================================

def read_yaml(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)


def write_yaml(path, data):
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def run_command(command, cwd):
    print(f"\nRunning command in {cwd}:")
    print(" ".join(command))

    subprocess.run(
        command,
        cwd=cwd,
        check=True,
    )


def copy_results(scenario_name, original_config):
    source_results_dir = OG_REPO / "results" / original_config["scenario"]
    target_results_dir = OUTPUT_RUNS_DIR / scenario_name

    target_results_dir.mkdir(parents=True, exist_ok=True)

    if source_results_dir.exists():
        shutil.copytree(
            source_results_dir,
            target_results_dir / "results",
            dirs_exist_ok=True,
        )

    shutil.copy2(
        OG_CONFIG_FILE,
        target_results_dir / "config.yaml",
    )

    shutil.copy2(
        OG_CONFIG_FILE,
        target_results_dir / "config.yaml",
    )


# ============================================================
# Main automation
# ============================================================

def main():
    if not OG_REPO.exists():
        raise FileNotFoundError(f"OSeMOSYS Global repo not found: {OG_REPO}")

    if not OG_CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config file not found: {OG_CONFIG_FILE}")

    if not GENERATED_DIR.exists():
        raise FileNotFoundError(f"Generated scenarios folder not found: {GENERATED_DIR}")

    OUTPUT_RUNS_DIR.mkdir(parents=True, exist_ok=True)

    original_config = read_yaml(OG_CONFIG_FILE)

    scenario_dirs = sorted(
        d for d in GENERATED_DIR.iterdir()
        if d.is_dir()
    )

    if not scenario_dirs:
        raise FileNotFoundError(f"No scenario folders found in {GENERATED_DIR}")

    try:
        for scenario_dir in scenario_dirs:
            scenario_name = scenario_dir.name
            demand_file = scenario_dir / "specified_annual_demand.csv"

            if not demand_file.exists():
                print(f"Skipping {scenario_name}: missing specified_annual_demand.csv")
                continue

            print("\n" + "=" * 80)
            print(f"Running scenario: {scenario_name}")
            print("=" * 80)

            # Copy generated demand file into OSeMOSYS Global
            shutil.copy2(demand_file, OG_CUSTOM_DEMAND_FILE)

            # Update OSeMOSYS config
            config = original_config.copy()
            config["scenario"] = original_config["scenario"]
            config["geographic_scope"] = original_config["geographic_scope"]
            config["results_by_country"] = True

            write_yaml(OG_CONFIG_FILE, config)

            # Run OSeMOSYS Global 
            run_command(
                [
                    "snakemake",
                    "--cores", "1",
                    "--latency-wait", "60",
                    "--printshellcmds",
                    "--show-failed-logs",
                ],
                cwd=OG_REPO,
            )
             

            # Archive results
            copy_results(scenario_name, original_config)

            print(f"Saved outputs to: {OUTPUT_RUNS_DIR / scenario_name}")

    finally:
        # Restore original config
        write_yaml(OG_CONFIG_FILE, original_config)
        print("\nRestored original OSeMOSYS config.")


if __name__ == "__main__":
    main()