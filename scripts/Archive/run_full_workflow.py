"""
Run the full demand-scenario workflow and execute OSeMOSYS Global one country at a time.

This script is intended to replace the earlier manual process where config.yaml was
edited for each country/scenario run.

Key features
------------
1. Runs preprocessing scripts in order.
2. Reads generated scenario folders from data/generated/.
3. Uses each scenario's audit.csv to identify countries to run.
4. Applies country assumption overlays from config/country_assumptions/<ISO3>.yaml.
5. Updates OSeMOSYS Global config.yaml one country at a time.
6. Copies the generated specified_annual_demand.csv into OSeMOSYS Global.
7. Runs Snakemake.
8. Archives each country/scenario result separately.
9. Supports skip/resume, filters, dry-run mode, and run logging.

Example usage
-------------
Run the full workflow:
    python scripts/run_full_workflow.py

Resume without rerunning completed outputs:
    python scripts/run_full_workflow.py --skip-existing

Test one scenario and one country:
    python scripts/run_full_workflow.py --only-scenarios my_scenario --only-countries ZAF --skip-preprocessing

Run with 4 Snakemake cores:
    python scripts/run_full_workflow.py --cores 4
"""

from __future__ import annotations

import argparse
import copy
import csv
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
import yaml


# ============================================================
# Paths
# ============================================================

REPO_ROOT = Path(__file__).resolve().parents[1]
OG_REPO = REPO_ROOT / "external" / "osemosys_global"

GENERATED_DIR = REPO_ROOT / "data" / "generated"
OUTPUT_RUNS_DIR = REPO_ROOT / "outputs" / "scenario_runs"
RUN_LOG = REPO_ROOT / "outputs" / "scenario_run_log.csv"

# Country-specific assumptions are saved here, for example:
#   config/country_assumptions/ZAF.yaml
# Each overlay should contain the fields you normally edit manually, such as:
#   geographic_scope, no_invest_technologies, emission_limit, results_by_country
COUNTRY_ASSUMPTIONS_DIR = REPO_ROOT / "config" / "country_assumptions"

OG_CONFIG = OG_REPO / "config" / "config.yaml"

# Use the same custom demand path as run_generated_scenarios.py.
# This fixes the earlier mismatch with resources/custom/.
OG_CUSTOM_DIR = OG_REPO / "resources" / "data" / "custom"
OG_DEMAND_FILE = OG_CUSTOM_DIR / "specified_annual_demand.csv"

PREPROCESSING_STEPS = [
    "scripts/convert_scenario_gwh_to_pj.py",
    "scripts/compare_scenario_pj_to_2040.py",
    "scripts/build_revised_demand_inputs.py",
]


# ============================================================
# Utilities
# ============================================================

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalise_filter(values: Iterable[str] | None) -> set[str] | None:
    if not values:
        return None
    result: set[str] = set()
    for value in values:
        for item in str(value).split(","):
            item = item.strip()
            if item:
                result.add(item)
    return result or None


def read_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def write_yaml(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def append_run_log(row: dict) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "scenario",
        "country",
        "status",
        "start_time",
        "end_time",
        "duration_seconds",
        "archive_dir",
        "error",
    ]
    file_exists = RUN_LOG.exists()
    with open(RUN_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow({name: row.get(name, "") for name in fieldnames})


def run_cmd(cmd: list[str], cwd: Path, log_path: Path | None = None) -> None:
    """Run a command, optionally teeing stdout/stderr to a log file."""
    print(" ".join(cmd))
    if log_path is None:
        subprocess.run(cmd, cwd=cwd, check=True)
        return

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log_file:
        process = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, cmd)


def run_preprocessing() -> None:
    for script in PREPROCESSING_STEPS:
        script_path = REPO_ROOT / script
        if not script_path.exists():
            raise FileNotFoundError(f"Preprocessing script not found: {script_path}")
        print(f"\nRunning preprocessing step: {script}")
        run_cmd([sys.executable, str(script_path)], cwd=REPO_ROOT)


def validate_paths() -> None:
    required_paths = [
        (OG_REPO, "OSeMOSYS Global repository"),
        (OG_CONFIG, "OSeMOSYS Global config.yaml"),
        (GENERATED_DIR, "generated scenarios directory"),
    ]
    for path, description in required_paths:
        if not path.exists():
            raise FileNotFoundError(f"Missing {description}: {path}")


# ============================================================
# Scenario execution
# ============================================================

def load_country_assumptions(country_iso: str) -> dict:
    """Load country-specific config edits.

    Example file:
        config/country_assumptions/ZAF.yaml

    The file should include only country assumptions, not demand-scenario data.
    Typical keys are:
        geographic_scope
        no_invest_technologies
        emission_limit
        results_by_country
    """
    country_iso = country_iso.strip().upper()
    country_file = COUNTRY_ASSUMPTIONS_DIR / f"{country_iso}.yaml"

    if not country_file.exists():
        raise FileNotFoundError(
            "Missing country assumptions file:\n"
            f"  {country_file}\n\n"
            "Create it with the config fields you normally edit manually. "
            "For example, for South Africa create config/country_assumptions/ZAF.yaml."
        )

    data = read_yaml(country_file)
    if not isinstance(data, dict):
        raise ValueError(f"Country assumptions file must be a YAML mapping: {country_file}")
    return data


def build_config_for_run(
    *,
    original_config: dict,
    scenario_name: str,
    country_iso: str,
) -> dict:
    """Combine base config + country assumptions + demand scenario run label."""
    country_iso = country_iso.strip().upper()
    config_scenario_name = f"{scenario_name}_{country_iso}"

    # Deep copy avoids accidental changes to nested lists/dicts in original_config.
    config = copy.deepcopy(original_config)

    # Apply the country overlay. Top-level replacement is intentional:
    # if ZAF.yaml contains emission_limit, it replaces the base emission_limit list.
    country_assumptions = load_country_assumptions(country_iso)
    config.update(country_assumptions)

    # These two values are controlled by the workflow for each run.
    config["scenario"] = config_scenario_name
    config["geographic_scope"] = [country_iso]
    config["results_by_country"] = True

    return config


def archive_inputs(
    archive_dir: Path,
    demand_file: Path,
    config: dict,
    original_config: dict,
) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(demand_file, archive_dir / "specified_annual_demand.csv")
    write_yaml(archive_dir / "config_used.yaml", config)
    write_yaml(archive_dir / "config_original.yaml", original_config)


def archive_results(config_scenario_name: str, archive_dir: Path) -> None:
    results_dir = OG_REPO / "results" / config_scenario_name
    if results_dir.exists():
        shutil.copytree(results_dir, archive_dir / "results", dirs_exist_ok=True)
    else:
        print(f"Warning: expected results folder not found: {results_dir}")


def run_og_scenario(
    scenario_name: str,
    country_iso: str,
    demand_file: Path,
    *,
    cores: int,
    skip_existing: bool,
    dry_run: bool,
    extra_snakemake_args: list[str] | None = None,
) -> None:
    country_iso = str(country_iso).strip().upper()
    config_scenario_name = f"{scenario_name}_{country_iso}"
    archive_dir = OUTPUT_RUNS_DIR / scenario_name / country_iso
    results_archive = archive_dir / "results"

    if skip_existing and results_archive.exists() and any(results_archive.iterdir()):
        print(f"Skipping existing run: {scenario_name}/{country_iso}")
        append_run_log(
            {
                "scenario": scenario_name,
                "country": country_iso,
                "status": "skipped_existing",
                "start_time": now_iso(),
                "end_time": now_iso(),
                "duration_seconds": 0,
                "archive_dir": str(archive_dir),
                "error": "",
            }
        )
        return

    print("\n" + "=" * 80)
    print(f"Running scenario={scenario_name} country={country_iso}")
    print("=" * 80)

    start_time = now_iso()
    tic = time.time()
    original_config = read_yaml(OG_CONFIG)

    config = build_config_for_run(
        original_config=original_config,
        scenario_name=scenario_name,
        country_iso=country_iso,
    )

    try:
        archive_inputs(archive_dir, demand_file, config, original_config)

        if dry_run:
            print(f"Dry run only. Would write config and run {config_scenario_name}.")
            append_run_log(
                {
                    "scenario": scenario_name,
                    "country": country_iso,
                    "status": "dry_run",
                    "start_time": start_time,
                    "end_time": now_iso(),
                    "duration_seconds": round(time.time() - tic, 2),
                    "archive_dir": str(archive_dir),
                    "error": "",
                }
            )
            return

        write_yaml(OG_CONFIG, config)

        OG_CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(demand_file, OG_DEMAND_FILE)

        snakemake_cmd = [
            "snakemake",
            "--cores",
            str(cores),
            "--latency-wait",
            "60",
            "--printshellcmds",
            "--show-failed-logs",
        ]
        if extra_snakemake_args:
            snakemake_cmd.extend(extra_snakemake_args)

        run_cmd(snakemake_cmd, cwd=OG_REPO, log_path=archive_dir / "snakemake.log")
        archive_results(config_scenario_name, archive_dir)

        append_run_log(
            {
                "scenario": scenario_name,
                "country": country_iso,
                "status": "success",
                "start_time": start_time,
                "end_time": now_iso(),
                "duration_seconds": round(time.time() - tic, 2),
                "archive_dir": str(archive_dir),
                "error": "",
            }
        )
        print(f"Saved outputs to: {archive_dir}")

    except Exception as exc:
        append_run_log(
            {
                "scenario": scenario_name,
                "country": country_iso,
                "status": "failed",
                "start_time": start_time,
                "end_time": now_iso(),
                "duration_seconds": round(time.time() - tic, 2),
                "archive_dir": str(archive_dir),
                "error": repr(exc),
            }
        )
        print(f"Failed: {scenario_name}/{country_iso}: {exc}")
        raise

    finally:
        # Always restore the user's original config after each country run.
        write_yaml(OG_CONFIG, original_config)


def iter_generated_scenarios(
    *,
    only_scenarios: set[str] | None,
) -> list[Path]:
    scenario_dirs = sorted(d for d in GENERATED_DIR.iterdir() if d.is_dir())
    if only_scenarios:
        scenario_dirs = [d for d in scenario_dirs if d.name in only_scenarios]
    return scenario_dirs


def get_countries_from_audit(audit_file: Path, only_countries: set[str] | None) -> list[str]:
    try:
        audit = pd.read_csv(audit_file)
    except pd.errors.EmptyDataError:
        print(f"Skipping {audit_file.parent.name}: audit.csv is empty")
        return []

    if audit.empty:
        print(f"Skipping {audit_file.parent.name}: audit.csv has no flagged countries")
        return []

    if "iso3" not in audit.columns:
        print(f"Skipping {audit_file.parent.name}: audit.csv is missing required column 'iso3'")
        return []

    countries = [str(x).strip().upper() for x in audit["iso3"].dropna().unique()]
    countries = sorted(c for c in countries if c)

    if only_countries:
        countries = [c for c in countries if c in only_countries]

    return countries


def run_all_generated_scenarios(
    *,
    cores: int,
    skip_existing: bool,
    dry_run: bool,
    only_scenarios: set[str] | None,
    only_countries: set[str] | None,
    continue_on_error: bool,
    extra_snakemake_args: list[str] | None,
) -> None:
    scenario_dirs = iter_generated_scenarios(only_scenarios=only_scenarios)

    if not scenario_dirs:
        raise FileNotFoundError(
            f"No generated scenario folders found in {GENERATED_DIR}"
            + (f" matching {sorted(only_scenarios)}" if only_scenarios else "")
        )

    for scenario_dir in scenario_dirs:
        scenario_name = scenario_dir.name
        demand_file = scenario_dir / "specified_annual_demand.csv"
        audit_file = scenario_dir / "audit.csv"

        if not demand_file.exists():
            print(f"Skipping {scenario_name}: missing specified_annual_demand.csv")
            continue

        if not audit_file.exists():
            print(f"Skipping {scenario_name}: missing audit.csv")
            continue

        countries = get_countries_from_audit(audit_file, only_countries)
        if not countries:
            print(f"Skipping {scenario_name}: no countries to run after filtering")
            continue

        print(f"\nScenario {scenario_name}: {len(countries)} country run(s)")

        for country_iso in countries:
            try:
                run_og_scenario(
                    scenario_name,
                    country_iso,
                    demand_file,
                    cores=cores,
                    skip_existing=skip_existing,
                    dry_run=dry_run,
                    extra_snakemake_args=extra_snakemake_args,
                )
            except Exception:
                if continue_on_error:
                    print("Continuing after failed run because --continue-on-error was set.")
                    continue
                raise


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full OSeMOSYS scenario workflow.")
    parser.add_argument("--skip-preprocessing", action="store_true", help="Do not rerun preprocessing scripts.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip country/scenario runs with archived results already present.")
    parser.add_argument("--dry-run", action="store_true", help="Prepare archive inputs and log intended runs without executing Snakemake.")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue to the next run if one country/scenario fails.")
    parser.add_argument("--cores", type=int, default=1, help="Number of Snakemake cores to use.")
    parser.add_argument("--only-scenarios", nargs="*", help="Scenario folder names to run. Accepts space- or comma-separated values.")
    parser.add_argument("--only-countries", nargs="*", help="ISO3 country codes to run. Accepts space- or comma-separated values.")
    parser.add_argument(
        "--snakemake-arg",
        action="append",
        default=None,
        help="Extra argument to pass to Snakemake. Repeat this option for multiple args.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    OUTPUT_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    validate_paths()

    only_scenarios = normalise_filter(args.only_scenarios)
    only_countries = normalise_filter(args.only_countries)

    if not args.skip_preprocessing:
        run_preprocessing()

    run_all_generated_scenarios(
        cores=args.cores,
        skip_existing=args.skip_existing,
        dry_run=args.dry_run,
        only_scenarios=only_scenarios,
        only_countries=only_countries,
        continue_on_error=args.continue_on_error,
        extra_snakemake_args=args.snakemake_arg,
    )

    print("\nWorkflow complete.")
    print(f"Run log: {RUN_LOG}")


if __name__ == "__main__":
    main()
