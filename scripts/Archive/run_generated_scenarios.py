"""
Standalone runner for already-generated demand scenarios.

Use this script when preprocessing has already been completed and data/generated/
contains scenario folders with:
    - specified_annual_demand.csv
    - audit.csv

For the full end-to-end pipeline, use run_full_workflow.py instead.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
OG_REPO = REPO_ROOT / "external" / "osemosys_global"

GENERATED_DIR = REPO_ROOT / "data" / "generated"
OUTPUT_RUNS_DIR = REPO_ROOT / "outputs" / "scenario_runs"
RUN_LOG = REPO_ROOT / "outputs" / "scenario_run_log.csv"

OG_CONFIG = OG_REPO / "config" / "config.yaml"
OG_CUSTOM_DIR = OG_REPO / "resources" / "data" / "custom"
OG_DEMAND_FILE = OG_CUSTOM_DIR / "specified_annual_demand.csv"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalise_filter(values: Iterable[str] | None) -> set[str] | None:
    if not values:
        return None
    out: set[str] = set()
    for value in values:
        for item in str(value).split(","):
            item = item.strip()
            if item:
                out.add(item)
    return out or None


def read_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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
        writer.writerow({field: row.get(field, "") for field in fieldnames})


def run_cmd(cmd: list[str], cwd: Path, log_path: Path) -> None:
    print(" ".join(cmd))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd)


def validate_paths() -> None:
    for path, label in [
        (OG_REPO, "OSeMOSYS Global repository"),
        (OG_CONFIG, "OSeMOSYS Global config.yaml"),
        (GENERATED_DIR, "generated scenario directory"),
    ]:
        if not path.exists():
            raise FileNotFoundError(f"Missing {label}: {path}")


def get_countries(audit_file: Path, only_countries: set[str] | None) -> list[str]:
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

    countries = sorted(str(x).strip().upper() for x in audit["iso3"].dropna().unique())
    if only_countries:
        countries = [c for c in countries if c in only_countries]
    return countries


def run_one(
    scenario_name: str,
    country_iso: str,
    demand_file: Path,
    *,
    cores: int,
    skip_existing: bool,
    dry_run: bool,
) -> None:
    country_iso = country_iso.upper()
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
            }
        )
        return

    print("\n" + "=" * 80)
    print(f"Running scenario={scenario_name} country={country_iso}")
    print("=" * 80)

    start_time = now_iso()
    tic = time.time()
    original_config = read_yaml(OG_CONFIG)
    config = original_config.copy()
    config["scenario"] = config_scenario_name
    config["geographic_scope"] = [country_iso]
    config["results_by_country"] = True

    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(demand_file, archive_dir / "specified_annual_demand.csv")
        write_yaml(archive_dir / "config_used.yaml", config)
        write_yaml(archive_dir / "config_original.yaml", original_config)

        if dry_run:
            append_run_log(
                {
                    "scenario": scenario_name,
                    "country": country_iso,
                    "status": "dry_run",
                    "start_time": start_time,
                    "end_time": now_iso(),
                    "duration_seconds": round(time.time() - tic, 2),
                    "archive_dir": str(archive_dir),
                }
            )
            return

        write_yaml(OG_CONFIG, config)
        OG_CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(demand_file, OG_DEMAND_FILE)

        run_cmd(
            [
                "snakemake",
                "--cores",
                str(cores),
                "--latency-wait",
                "60",
                "--printshellcmds",
                "--show-failed-logs",
            ],
            cwd=OG_REPO,
            log_path=archive_dir / "snakemake.log",
        )

        results_dir = OG_REPO / "results" / config_scenario_name
        if results_dir.exists():
            shutil.copytree(results_dir, results_archive, dirs_exist_ok=True)
        else:
            print(f"Warning: result folder not found: {results_dir}")

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
        raise

    finally:
        write_yaml(OG_CONFIG, original_config)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run generated OSeMOSYS scenarios country by country.")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--only-scenarios", nargs="*")
    parser.add_argument("--only-countries", nargs="*")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validate_paths()
    OUTPUT_RUNS_DIR.mkdir(parents=True, exist_ok=True)

    only_scenarios = normalise_filter(args.only_scenarios)
    only_countries = normalise_filter(args.only_countries)

    scenario_dirs = sorted(d for d in GENERATED_DIR.iterdir() if d.is_dir())
    if only_scenarios:
        scenario_dirs = [d for d in scenario_dirs if d.name in only_scenarios]

    for scenario_dir in scenario_dirs:
        demand_file = scenario_dir / "specified_annual_demand.csv"
        audit_file = scenario_dir / "audit.csv"

        if not demand_file.exists() or not audit_file.exists():
            print(f"Skipping {scenario_dir.name}: missing demand or audit file")
            continue

        countries = get_countries(audit_file, only_countries)
        for country in countries:
            try:
                run_one(
                    scenario_dir.name,
                    country,
                    demand_file,
                    cores=args.cores,
                    skip_existing=args.skip_existing,
                    dry_run=args.dry_run,
                )
            except Exception as exc:
                print(f"Failed {scenario_dir.name}/{country}: {exc}")
                if not args.continue_on_error:
                    raise

    print(f"Done. Run log: {RUN_LOG}")


if __name__ == "__main__":
    main()
