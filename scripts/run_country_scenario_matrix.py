#!/usr/bin/env python3
"""
Run OSeMOSYS Global for:

    country config x demand scenario

This version supports OSeMOSYS Global layouts where the Snakefile is located at:

    external/osemosys_global/workflow/Snakefile

while the config is located at:

    external/osemosys_global/config/config.yaml

The script runs Snakemake from external/osemosys_global and passes:
    --snakefile workflow/Snakefile

so config/config.yaml is resolved correctly.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

COUNTRY_CONFIG_ROOT = REPO_ROOT / "configs" / "country_configs"
DEMAND_ROOT = REPO_ROOT / "data" / "generated"

OG_REPO = REPO_ROOT / "external" / "osemosys_global"
OG_ROOT_SNAKEFILE = OG_REPO / "Snakefile"
OG_WORKFLOW_SNAKEFILE = OG_REPO / "workflow" / "Snakefile"

OG_CONFIG = OG_REPO / "config" / "config.yaml"
OG_CUSTOM_DEMAND = OG_REPO / "resources" / "data" / "custom" / "specified_annual_demand.csv"
OG_RESULTS = OG_REPO / "results"

WORKFLOW_OUT = REPO_ROOT / "outputs" / "osemosys_config_workflow"
SCENARIO_RESULTS = WORKFLOW_OUT / "scenario_results"
LOG_FILE = WORKFLOW_OUT / "workflow.log"
SNAKEMAKE_LOG = WORKFLOW_OUT / "snakemake.log"


@dataclass(frozen=True)
class CountryConfig:
    country: str
    path: Path


@dataclass(frozen=True)
class DemandScenario:
    name: str
    path: Path


def timestamp() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def log(message: str) -> None:
    WORKFLOW_OUT.mkdir(parents=True, exist_ok=True)
    line = f"[{timestamp()}] {message}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def require_path(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label}: {path}")


def get_snakemake_file_arg() -> list[str]:
    """
    Return extra Snakemake args if the Snakefile is not at repo root.

    Important:
    - cwd must remain OG_REPO, not OG_REPO/workflow.
    - This lets the workflow/Snakefile find config/config.yaml correctly.
    """
    if OG_ROOT_SNAKEFILE.exists():
        return []
    if OG_WORKFLOW_SNAKEFILE.exists():
        return ["--snakefile", str(OG_WORKFLOW_SNAKEFILE.relative_to(OG_REPO))]
    raise FileNotFoundError(
        "Could not find OSeMOSYS Global Snakefile at either:\n"
        f"  {OG_ROOT_SNAKEFILE}\n"
        f"  {OG_WORKFLOW_SNAKEFILE}"
    )


def discover_country_configs(filters: set[str] | None = None) -> list[CountryConfig]:
    require_path(COUNTRY_CONFIG_ROOT, "country config directory")

    configs: list[CountryConfig] = []
    for config_path in sorted(COUNTRY_CONFIG_ROOT.glob("*/config.yaml")):
        country = config_path.parent.name
        if filters and country not in filters:
            continue
        configs.append(CountryConfig(country=country, path=config_path))

    if filters:
        found = {c.country for c in configs}
        missing = sorted(filters - found)
        if missing:
            raise FileNotFoundError(
                "Missing config.yaml for requested countries: "
                + ", ".join(missing)
                + f"\nExpected path: {COUNTRY_CONFIG_ROOT}/<COUNTRY>/config.yaml"
            )

    if not configs:
        raise FileNotFoundError(
            f"No country configs found at {COUNTRY_CONFIG_ROOT}/<COUNTRY>/config.yaml"
        )

    return configs


def discover_demand_scenarios(filters: set[str] | None = None) -> list[DemandScenario]:
    require_path(DEMAND_ROOT, "generated demand directory")

    scenarios: list[DemandScenario] = []
    for demand_path in sorted(DEMAND_ROOT.glob("*/specified_annual_demand.csv")):
        name = demand_path.parent.name
        if filters and name not in filters:
            continue
        scenarios.append(DemandScenario(name=name, path=demand_path))

    if filters:
        found = {s.name for s in scenarios}
        missing = sorted(filters - found)
        if missing:
            raise FileNotFoundError(
                "Missing specified_annual_demand.csv for requested demand scenarios: "
                + ", ".join(missing)
                + f"\nExpected path: {DEMAND_ROOT}/<SCENARIO>/specified_annual_demand.csv"
            )

    if not scenarios:
        raise FileNotFoundError(
            f"No demand files found at {DEMAND_ROOT}/<SCENARIO>/specified_annual_demand.csv"
        )

    return scenarios


def read_csv_shape(path: Path) -> tuple[int, list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            columns = next(reader)
        except StopIteration:
            return 0, []
        rows = sum(1 for _ in reader)
    return rows, columns


def copy_and_clean_demand(src: Path, dst: Path) -> tuple[int, list[str]]:
    """
    Copy demand CSV to OSeMOSYS custom folder and remove empty/Unnamed columns
    caused by Excel exports or trailing commas.

    Required columns:
        CUSTOM_NODE, YEAR, VALUE
    """
    with src.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))

    if not rows:
        raise ValueError(f"Demand file is empty: {src}")

    header = [h.strip() for h in rows[0]]
    keep = [i for i, h in enumerate(header) if h and not h.lower().startswith("unnamed")]
    cleaned_header = [header[i] for i in keep]

    required = {"CUSTOM_NODE", "YEAR", "VALUE"}
    missing = required - set(cleaned_header)
    if missing:
        raise ValueError(
            f"{src} is missing required columns {sorted(missing)}. "
            f"Found columns: {cleaned_header}"
        )

    cleaned_rows = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        padded = row + [""] * max(0, len(header) - len(row))
        cleaned_rows.append([padded[i] for i in keep])

    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(cleaned_header)
        writer.writerows(cleaned_rows)

    return len(cleaned_rows), cleaned_header


def copy_country_config(cfg: CountryConfig) -> None:
    require_path(cfg.path, f"{cfg.country} config")
    OG_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cfg.path, OG_CONFIG)
    log(f"{cfg.country}: copied config {cfg.path.relative_to(REPO_ROOT)} -> {OG_CONFIG.relative_to(REPO_ROOT)}")


def copy_demand(demand: DemandScenario) -> None:
    require_path(demand.path, f"{demand.name} demand file")
    rows, cols = copy_and_clean_demand(demand.path, OG_CUSTOM_DEMAND)
    log(
        f"{demand.name}: copied demand {demand.path.relative_to(REPO_ROOT)} -> "
        f"{OG_CUSTOM_DEMAND.relative_to(REPO_ROOT)}; rows={rows}, columns={cols}"
    )


def run_snakemake(cores: int, dry_run: bool, force: bool, extra_args: list[str]) -> None:
    cmd = [
        "snakemake",
        *get_snakemake_file_arg(),
        "--cores", str(cores),
        "--rerun-incomplete",
        "--printshellcmds",
        "--show-failed-logs",
    ]

    if dry_run:
        cmd.append("--dry-run")

    if force:
        cmd.append("--forceall")

    cmd.extend(extra_args)

    WORKFLOW_OUT.mkdir(parents=True, exist_ok=True)
    log(f"Running in {OG_REPO}: {' '.join(cmd)}")

    with SNAKEMAKE_LOG.open("a", encoding="utf-8") as f:
        f.write("\n" + "=" * 100 + "\n")
        f.write(f"{timestamp()} | cwd={OG_REPO}\n")
        f.write(" ".join(cmd) + "\n")
        f.flush()

        result = subprocess.run(
            cmd,
            cwd=OG_REPO,
            text=True,
            stdout=f,
            stderr=subprocess.STDOUT,
        )

    if result.returncode != 0:
        raise RuntimeError(
            f"Snakemake failed with exit code {result.returncode}. See {SNAKEMAKE_LOG}"
        )


def archive_results(country: str, demand_name: str, overwrite: bool) -> Path:
    dest = SCENARIO_RESULTS / country / demand_name

    if dest.exists():
        if overwrite:
            shutil.rmtree(dest)
        else:
            raise FileExistsError(
                f"Archive already exists: {dest}. Use --overwrite-archive or --resume."
            )

    dest.mkdir(parents=True, exist_ok=True)

    if OG_RESULTS.exists():
        shutil.copytree(OG_RESULTS, dest / "results", dirs_exist_ok=True)
    else:
        log("WARNING: external/osemosys_global/results does not exist after run.")

    inputs = dest / "_inputs_used"
    inputs.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OG_CONFIG, inputs / "config.yaml")
    shutil.copy2(OG_CUSTOM_DEMAND, inputs / "specified_annual_demand.csv")

    return dest


def print_detected(configs: list[CountryConfig], demands: list[DemandScenario]) -> None:
    print("\nDetected country configs:")
    for cfg in configs:
        print(f"  - {cfg.country}: {cfg.path.relative_to(REPO_ROOT)}")

    print("\nDetected demand scenarios:")
    for demand in demands:
        rows, cols = read_csv_shape(demand.path)
        print(f"  - {demand.name}: {demand.path.relative_to(REPO_ROOT)} | rows={rows}, columns={cols}")

    print("\nDetected OSeMOSYS Global layout:")
    if OG_ROOT_SNAKEFILE.exists():
        print("  - Snakefile: external/osemosys_global/Snakefile")
    elif OG_WORKFLOW_SNAKEFILE.exists():
        print("  - Snakefile: external/osemosys_global/workflow/Snakefile")
        print("  - Snakemake will run from external/osemosys_global using --snakefile workflow/Snakefile")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run OSeMOSYS Global for country configs x demand scenarios."
    )

    parser.add_argument("--country", action="append", help="Country code to run. Repeatable.")
    parser.add_argument("--demand-scenario", action="append", help="Demand scenario to run. Repeatable.")
    parser.add_argument("--cores", type=int, default=1, help="Snakemake cores.")
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to Snakemake.")
    parser.add_argument("--force", action="store_true", help="Pass --forceall to Snakemake.")
    parser.add_argument("--list", action="store_true", help="List detected inputs and exit.")
    parser.add_argument("--resume", action="store_true", help="Skip archived country/scenario combinations.")
    parser.add_argument("--overwrite-archive", action="store_true", help="Replace existing archived outputs.")
    parser.add_argument("--clean-between-runs", action="store_true", help="Delete external/osemosys_global/results before each run.")
    parser.add_argument("--snakemake-arg", action="append", default=[], help="Extra Snakemake argument. Repeatable.")

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    require_path(OG_REPO, "OSeMOSYS Global repo")
    get_snakemake_file_arg()
    require_path(OG_CONFIG.parent, "OSeMOSYS Global config directory")

    country_filter = set(args.country) if args.country else None
    demand_filter = set(args.demand_scenario) if args.demand_scenario else None

    configs = discover_country_configs(country_filter)
    demands = discover_demand_scenarios(demand_filter)

    print(f"Repo root: {REPO_ROOT}")
    print_detected(configs, demands)

    if args.list:
        return

    log("Starting country x demand scenario workflow")
    log(f"Snakemake workdir: {OG_REPO.relative_to(REPO_ROOT)}")
    log(f"Number of country configs: {len(configs)}")
    log(f"Number of demand scenarios: {len(demands)}")
    log(f"Total planned runs: {len(configs) * len(demands)}")

    for cfg in configs:
        for demand in demands:
            run_name = f"{cfg.country}/{demand.name}"
            dest = SCENARIO_RESULTS / cfg.country / demand.name

            if args.resume and dest.exists() and not args.overwrite_archive:
                log(f"Skipping existing archived run: {run_name}")
                continue

            log(f"--- Running {run_name} ---")

            if args.clean_between_runs and OG_RESULTS.exists():
                shutil.rmtree(OG_RESULTS)
                log(f"{run_name}: removed previous OSeMOSYS results directory")

            copy_country_config(cfg)
            copy_demand(demand)

            run_snakemake(args.cores, args.dry_run, args.force, args.snakemake_arg)

            if not args.dry_run:
                archived = archive_results(cfg.country, demand.name, args.overwrite_archive)
                log(f"{run_name}: archived results -> {archived.relative_to(REPO_ROOT)}")

    log("Workflow finished successfully!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. If needed, clear Snakemake locks with:")
        print("  rm -rf external/osemosys_global/.snakemake/locks")
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
