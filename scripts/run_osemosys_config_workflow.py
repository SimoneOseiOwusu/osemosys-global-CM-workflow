#!/usr/bin/env python3
"""
Run OSeMOSYS Global once per generated demand scenario.

This wrapper:
  1. Reads demand scenarios from data/generated/<scenario>/specified_annual_demand.csv
  2. Copies each demand file into OSeMOSYS Global custom data
  3. Runs Snakemake using the existing OSeMOSYS Global config
  4. Archives each scenario's OSeMOSYS results separately

It does NOT rewrite the OSeMOSYS Global config.yaml.
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OG_REPO = REPO_ROOT / "external" / "osemosys_global"
GENERATED_DIR = REPO_ROOT / "data" / "generated"
WORKFLOW_OUT = REPO_ROOT / "outputs" / "osemosys_config_workflow"
SCENARIO_OUT = WORKFLOW_OUT / "scenario_results"
CUSTOM_DEMAND = OG_REPO / "resources" / "data" / "custom" / "specified_annual_demand.csv"


def log(message: str) -> None:
    WORKFLOW_OUT.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
    print(line)
    with (WORKFLOW_OUT / "workflow.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def require_path(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label}: {path}")


def find_snakemake_workdir() -> Path:
    return OG_REPO
 
    for candidate in candidates:
        if (candidate / "Snakefile").exists() or (candidate / "snakefile").exists():
            return candidate

    matches = list(OG_REPO.rglob("Snakefile")) + list(OG_REPO.rglob("snakefile"))
    matches = [p for p in matches if "__pycache__" not in str(p)]
    if not matches:
        raise FileNotFoundError(f"Could not find Snakefile anywhere under {OG_REPO}")
    return matches[0].parent


def discover_scenarios(include_pj: bool, only: str | None) -> list[tuple[str, Path]]:
    require_path(GENERATED_DIR, "generated demand folder")
    scenarios: list[tuple[str, Path]] = []
    for demand_file in sorted(GENERATED_DIR.glob("*/specified_annual_demand.csv")):
        scenario = demand_file.parent.name
        if scenario.startswith(".") or scenario == "__MACOSX":
            continue
        if not include_pj and scenario.endswith("_PJ"):
            continue
        if only and scenario != only:
            continue
        scenarios.append((scenario, demand_file))
    if not scenarios:
        raise FileNotFoundError(
            f"No demand scenarios found in {GENERATED_DIR}. Expected files like "
            "data/generated/<scenario>/specified_annual_demand.csv"
        )
    return scenarios


def quick_csv_check(path: Path) -> tuple[int, list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        rows = sum(1 for _ in reader)
    return rows, header


def copy_demand(scenario: str, demand_file: Path) -> None:
    rows, header = quick_csv_check(demand_file)
    if rows == 0:
        raise ValueError(f"Demand file has no data rows: {demand_file}")
    CUSTOM_DEMAND.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(demand_file, CUSTOM_DEMAND)
    log(f"Scenario {scenario}: copied {demand_file.relative_to(REPO_ROOT)} -> {CUSTOM_DEMAND.relative_to(REPO_ROOT)}")
    log(f"Scenario {scenario}: demand rows={rows}, columns={header}")


def run_snakemake(workdir: Path, cores: int, dry_run: bool, force: bool, extra_args: list[str]) -> None:
    cmd = [
        "snakemake",
        "--cores", str(cores),
        "--rerun-incomplete",
        "--printshellcmds",
        "--show-failed-logs",
    ]
    if dry_run:
        cmd.append("--dry-run")
    if force and not dry_run:
        cmd.append("--forceall")
    cmd.extend(extra_args)

    log(f"Running in {workdir}: {' '.join(cmd)}")
    WORKFLOW_OUT.mkdir(parents=True, exist_ok=True)
    log_path = WORKFLOW_OUT / "snakemake.log"
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n\n" + "=" * 100 + "\n")
        f.write(f"{datetime.now().isoformat(timespec='seconds')} | cwd={workdir}\n")
        f.write(" ".join(cmd) + "\n")
        result = subprocess.run(cmd, cwd=workdir, text=True, stdout=f, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise RuntimeError(f"Snakemake failed with exit code {result.returncode}. See {log_path}")


def archive_results(scenario: str) -> None:
    results_dir = OG_REPO / "results"
    require_path(results_dir, "OSeMOSYS Global results folder")
    dest = SCENARIO_OUT / scenario
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(results_dir, dest / "results", dirs_exist_ok=True)
    log(f"Scenario {scenario}: archived results -> {dest.relative_to(REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="Run Snakemake dry-run for each scenario")
    parser.add_argument("--force", action="store_true", help="Use --forceall for real Snakemake runs")
    parser.add_argument("--list-scenarios", action="store_true", help="List detected demand scenarios and exit")
    parser.add_argument("--demand-scenario", help="Run only one scenario by folder name")
    parser.add_argument("--include-pj", action="store_true", help="Also run folders ending in _PJ. By default these are skipped to avoid duplicate PJ conversion scenarios.")
    parser.add_argument("--snakemake-arg", action="append", default=[], help="Extra argument to pass to Snakemake. Repeat as needed.")
    args = parser.parse_args()

    print(f"Repo root: {REPO_ROOT}")
    require_path(OG_REPO, "OSeMOSYS Global repo")
    workdir = find_snakemake_workdir()
    scenarios = discover_scenarios(include_pj=args.include_pj, only=args.demand_scenario)

    print("Detected demand scenarios:")
    for scenario, demand_file in scenarios:
        print(f"  - {scenario}: {demand_file.relative_to(REPO_ROOT)}")

    if args.list_scenarios:
        return

    log("Starting OSeMOSYS config workflow")
    log(f"Snakemake workdir: {workdir.relative_to(REPO_ROOT)}")
    log(f"Number of demand scenarios: {len(scenarios)}")

    for scenario, demand_file in scenarios:
        log(f"--- Running demand scenario: {scenario} ---")
        copy_demand(scenario, demand_file)
        run_snakemake(workdir, args.cores, args.dry_run, args.force, args.snakemake_arg)
        if not args.dry_run:
            archive_results(scenario)

    log("Workflow complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
