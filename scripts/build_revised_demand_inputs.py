#!/usr/bin/env python3
"""
Build revised OSeMOSYS specified_annual_demand.csv files using ADDITIVE demand logic
and explicit post-2040 growth.

Corrected logic
---------------
Scenario values are treated as additional demand, not total demand:

    revised_2040 = baseline_2040 + scenario_additional_2040

Then for years after 2040:

    revised_year = revised_2040 * (1 + post_target_growth_rate) ** years_after_2040

Default post-target growth rate is 2%.

This avoids the issue where 2041-2050 reverted to old/static baseline values.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_BASELINE = REPO_ROOT / "data" / "baseline" / "specified_annual_demand.csv"
DEFAULT_COMPARISON_DIR = REPO_ROOT / "outputs" / "pct_of_2040"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "generated"

TARGET_YEAR_DEFAULT = 2040
DEFAULT_POST_TARGET_GROWTH_RATE = 0.02
COMPARISON_SHEET = "comparison"


def clean_scenario_name(name: str) -> str:
    return (
        str(name)
        .strip()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace("(", "")
        .replace(")", "")
        .replace("%", "pct")
        .replace("-", "_")
        .replace("__", "_")
        .strip("_")
    )


def iso_to_custom_node(iso3: str) -> str:
    return f"{str(iso3).strip().upper()}XX"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build revised demand inputs using baseline + scenario demand + post-2040 growth."
    )
    parser.add_argument(
        "--baseline-file",
        type=Path,
        default=DEFAULT_BASELINE,
        help="Clean baseline specified_annual_demand.csv. Default: data/baseline/specified_annual_demand.csv",
    )
    parser.add_argument(
        "--comparison-file",
        type=Path,
        default=None,
        help="Specific comparison workbook to use. If omitted, script picks one from outputs/pct_of_2040.",
    )
    parser.add_argument(
        "--comparison-dir",
        type=Path,
        default=DEFAULT_COMPARISON_DIR,
        help="Folder containing comparison Excel files. Default: outputs/pct_of_2040",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output folder. Default: data/generated",
    )
    parser.add_argument(
        "--target-year",
        type=int,
        default=TARGET_YEAR_DEFAULT,
        help="Year to revise. Default: 2040",
    )
    parser.add_argument(
        "--post-target-growth-rate",
        type=float,
        default=DEFAULT_POST_TARGET_GROWTH_RATE,
        help="Annual growth rate after target year. Default: 0.02 = 2 percent.",
    )
    parser.add_argument(
        "--preferred-keyword",
        default="country_unconstrained",
        help="Keyword used to choose comparison workbook if multiple exist. Default: country_unconstrained",
    )
    parser.add_argument(
        "--clear-output",
        action="store_true",
        help="Delete existing data/generated before writing new scenario folders.",
    )
    parser.add_argument(
        "--include-reference",
        action="store_true",
        help="Also generate Reference_2040_PJ if Reference 2040 (PJ) exists. Usually leave this off.",
    )
    parser.add_argument(
        "--countries",
        nargs="*",
        default=None,
        help="Optional ISO3 countries to update. Example: --countries ZAF KEN AGO",
    )
    return parser.parse_args()


def choose_comparison_file(args: argparse.Namespace) -> Path:
    if args.comparison_file:
        if not args.comparison_file.exists():
            raise FileNotFoundError(f"Comparison file not found: {args.comparison_file}")
        return args.comparison_file

    files = sorted(args.comparison_dir.glob("*.xlsx"))
    if not files:
        raise FileNotFoundError(f"No .xlsx files found in {args.comparison_dir}")

    preferred = [p for p in files if args.preferred_keyword in p.name]
    return preferred[0] if preferred else files[0]


def load_baseline(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Baseline demand file not found: {path}\n\n"
            "Create it first, for example:\n"
            "  mkdir -p data/baseline\n"
            "  cp external/osemosys_global/resources/data/custom/specified_annual_demand.csv "
            "data/baseline/specified_annual_demand.csv\n\n"
            "Use a clean reference baseline file, not a scenario output."
        )

    df = pd.read_csv(path)
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")].copy()

    required = {"CUSTOM_NODE", "YEAR", "VALUE"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Baseline file missing required columns: {sorted(missing)}")

    df["CUSTOM_NODE"] = df["CUSTOM_NODE"].astype(str).str.strip().str.upper()
    df["YEAR"] = pd.to_numeric(df["YEAR"], errors="raise").astype(int)
    df["VALUE"] = pd.to_numeric(df["VALUE"], errors="raise")

    return df


def load_comparison(path: Path) -> pd.DataFrame:
    try:
        df = pd.read_excel(path, sheet_name=COMPARISON_SHEET)
    except ValueError:
        df = pd.read_excel(path, sheet_name=0)

    df.columns = [str(c).strip() for c in df.columns]

    iso_col = None
    for candidate in ["ISO3", "iso3", "Iso3", "Country", "country"]:
        if candidate in df.columns:
            iso_col = candidate
            break

    if iso_col is None:
        raise ValueError(f"Could not find ISO3/country column in {path}")

    df = df.rename(columns={iso_col: "ISO3"})
    df["ISO3"] = df["ISO3"].astype(str).str.strip().str.upper()

    return df


def scenario_columns(comp: pd.DataFrame, include_reference: bool) -> list[str]:
    cols = [c for c in comp.columns if str(c).endswith(" (PJ)")]

    if not include_reference:
        cols = [c for c in cols if c != "Reference 2040 (PJ)"]

    cols = [c for c in cols if c != "2022 Baseline (PJ)"]

    if not cols:
        raise ValueError("No scenario columns ending in ' (PJ)' found in comparison workbook.")

    return cols


def scenario_name_from_pj_col(col: str) -> str:
    return str(col).removesuffix(" (PJ)").strip()


def get_ratio_value(row: pd.Series, scenario_name: str):
    ratio_col = f"{scenario_name} (% of 2040)"
    if ratio_col not in row.index:
        return None

    value = row[ratio_col]
    if pd.isna(value):
        return None

    if isinstance(value, str):
        txt = value.strip().replace("%", "")
        if not txt:
            return None
        val = float(txt)
        return val / 100 if "%" in value else val

    return float(value)


def apply_additional_demand_with_growth(
    scenario_df: pd.DataFrame,
    custom_node: str,
    target_year: int,
    additional_value: float,
    post_target_growth_rate: float,
):
    """
    Keep pre-target years unchanged.
    Add scenario value to target year.
    For years after target year, grow from revised target year using fixed growth rate.
    """
    mask = scenario_df["CUSTOM_NODE"] == custom_node
    node_df = scenario_df.loc[mask].sort_values("YEAR").copy()

    if node_df.empty:
        return None, None, {}, "node_not_found"

    if target_year not in set(node_df["YEAR"]):
        return None, None, {}, "target_year_not_found"

    baseline_target = float(node_df.loc[node_df["YEAR"] == target_year, "VALUE"].iloc[0])
    revised_target = baseline_target + float(additional_value)

    scenario_df.loc[mask & (scenario_df["YEAR"] == target_year), "VALUE"] = revised_target

    years_after = sorted(node_df.loc[node_df["YEAR"] > target_year, "YEAR"].unique())
    revised_after = {}

    for year in years_after:
        n = int(year) - int(target_year)
        new_value = revised_target * ((1.0 + post_target_growth_rate) ** n)
        scenario_df.loc[mask & (scenario_df["YEAR"] == year), "VALUE"] = new_value
        revised_after[int(year)] = float(new_value)

    return baseline_target, revised_target, revised_after, "updated"


def main() -> None:
    args = parse_args()

    comparison_file = choose_comparison_file(args)
    baseline = load_baseline(args.baseline_file)
    comp = load_comparison(comparison_file)

    country_filter = {c.upper() for c in args.countries} if args.countries else None

    if args.clear_output and args.output_dir.exists():
        shutil.rmtree(args.output_dir)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    pj_cols = scenario_columns(comp, include_reference=args.include_reference)

    print(f"Using baseline: {args.baseline_file}")
    print(f"Using comparison workbook: {comparison_file}")
    print(f"Target year: {args.target_year}")
    print("Mode: ADD scenario PJ value to baseline target-year demand")
    print(f"Post-target growth rate: {args.post_target_growth_rate:.4f}")
    print(f"Scenarios found: {len(pj_cols)}")

    all_audit = []

    for pj_col in pj_cols:
        scenario_name = scenario_name_from_pj_col(pj_col)
        scenario_folder = clean_scenario_name(scenario_name)

        scenario_df = baseline.copy()
        audit_rows = []

        print(f"\nBuilding scenario: {scenario_name}")

        for _, row in comp.iterrows():
            iso3 = str(row["ISO3"]).strip().upper()
            if country_filter and iso3 not in country_filter:
                continue

            if pd.isna(row[pj_col]):
                continue

            custom_node = iso_to_custom_node(iso3)
            additional_demand = float(row[pj_col])
            ratio = get_ratio_value(row, scenario_name)

            baseline_target, revised_target, revised_after, status = apply_additional_demand_with_growth(
                scenario_df=scenario_df,
                custom_node=custom_node,
                target_year=args.target_year,
                additional_value=additional_demand,
                post_target_growth_rate=args.post_target_growth_rate,
            )

            audit = {
                "scenario": scenario_name,
                "iso3": iso3,
                "custom_node": custom_node,
                "target_year": args.target_year,
                "status": status,
                "baseline_target_value": baseline_target if baseline_target is not None else "",
                "additional_scenario_demand": additional_demand,
                "revised_target_value": revised_target if revised_target is not None else "",
                "post_target_growth_rate": args.post_target_growth_rate,
                "revised_2050_value": revised_after.get(2050, "") if revised_after else "",
                "ratio_of_reference_2040_from_workbook": ratio if ratio is not None else "",
                "pct_increase_vs_baseline_target": (
                    additional_demand / baseline_target if baseline_target not in [None, 0] else ""
                ),
            }

            audit_rows.append(audit)
            all_audit.append(audit)

        out_dir = args.output_dir / scenario_folder
        out_dir.mkdir(parents=True, exist_ok=True)

        demand_out = out_dir / "specified_annual_demand.csv"
        audit_out = out_dir / "audit.csv"

        scenario_df.to_csv(demand_out, index=False)
        pd.DataFrame(audit_rows).to_csv(audit_out, index=False)

        print(f"Updated countries: {sum(1 for r in audit_rows if r['status'] == 'updated')}")
        print(f"Saved demand: {demand_out}")
        print(f"Saved audit:  {audit_out}")

    all_audit_path = args.output_dir / "_demand_generation_audit_all.csv"
    pd.DataFrame(all_audit).to_csv(all_audit_path, index=False)

    print(f"\nSaved combined audit: {all_audit_path}")
    print("\nNext sense check:")
    print("  python scripts/check_generated_demand.py --country ZAF")
    print("  grep ZAF data/generated/Bau_2040_Low_Min_Threshold/specified_annual_demand.csv")


if __name__ == "__main__":
    main()
