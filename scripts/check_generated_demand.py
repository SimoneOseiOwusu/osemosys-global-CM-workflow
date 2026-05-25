#!/usr/bin/env python3
"""
Sense-check generated OSeMOSYS demand inputs before running the optimisation.

Reads:
    data/generated/<SCENARIO>/specified_annual_demand.csv

Outputs:
    outputs/demand_sense_checks/demand_by_country_scenario_year.csv
    outputs/demand_sense_checks/demand_summary_by_country_scenario.csv
    outputs/demand_sense_checks/demand_summary_by_node_scenario.csv
    outputs/demand_sense_checks/demand_warnings.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMAND_ROOT = REPO_ROOT / "data" / "generated"
OUT_DIR = REPO_ROOT / "outputs" / "demand_sense_checks"


def parse_args():
    parser = argparse.ArgumentParser(description="Sense-check generated demand inputs.")
    parser.add_argument("--country", action="append", help="Country ISO3 prefix to check. Repeatable.")
    parser.add_argument("--scenario", action="append", help="Demand scenario folder to check. Repeatable.")
    parser.add_argument("--warning-growth-threshold", type=float, default=0.25,
                        help="Warn if year-on-year growth exceeds this fraction. Default 0.25 = 25 percent.")
    parser.add_argument("--warning-drop-threshold", type=float, default=-0.25,
                        help="Warn if year-on-year growth is below this fraction. Default -0.25 = -25 percent.")
    return parser.parse_args()


def find_demand_files(selected_scenarios):
    files = sorted(DEMAND_ROOT.glob("*/specified_annual_demand.csv"))
    if selected_scenarios:
        files = [p for p in files if p.parent.name in selected_scenarios]
    if not files:
        raise FileNotFoundError("No matching specified_annual_demand.csv files found in data/generated/")
    return files


def read_demand(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
    required = {"CUSTOM_NODE", "YEAR", "VALUE"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path} missing required columns: {sorted(missing)}")
    df["SCENARIO"] = path.parent.name
    df["COUNTRY"] = df["CUSTOM_NODE"].astype(str).str[:3]
    df["YEAR"] = pd.to_numeric(df["YEAR"], errors="coerce").astype("Int64")
    df["VALUE"] = pd.to_numeric(df["VALUE"], errors="coerce")
    return df


def build_warnings(country_year: pd.DataFrame, growth_high: float, growth_low: float) -> pd.DataFrame:
    warnings = []
    for (country, scenario), group in country_year.groupby(["COUNTRY", "SCENARIO"]):
        g = group.sort_values("YEAR").copy()

        if g["VALUE"].isna().any():
            warnings.append({
                "COUNTRY": country,
                "SCENARIO": scenario,
                "YEAR": "",
                "WARNING": "Missing or non-numeric demand value",
                "VALUE": "",
                "YOY_GROWTH": "",
            })

        for _, row in g[g["VALUE"] < 0].iterrows():
            warnings.append({
                "COUNTRY": country,
                "SCENARIO": scenario,
                "YEAR": int(row["YEAR"]),
                "WARNING": "Negative demand",
                "VALUE": row["VALUE"],
                "YOY_GROWTH": "",
            })

        g["YOY_GROWTH"] = g["VALUE"].pct_change()
        unusual = g[(g["YOY_GROWTH"] > growth_high) | (g["YOY_GROWTH"] < growth_low)]
        for _, row in unusual.iterrows():
            warnings.append({
                "COUNTRY": country,
                "SCENARIO": scenario,
                "YEAR": int(row["YEAR"]),
                "WARNING": "Large year-on-year demand change",
                "VALUE": row["VALUE"],
                "YOY_GROWTH": row["YOY_GROWTH"],
            })

        if g["VALUE"].nunique(dropna=True) <= 1:
            warnings.append({
                "COUNTRY": country,
                "SCENARIO": scenario,
                "YEAR": "",
                "WARNING": "Demand is constant across all years",
                "VALUE": "",
                "YOY_GROWTH": "",
            })

    return pd.DataFrame(warnings)


def main():
    args = parse_args()
    countries = set(args.country) if args.country else None
    scenarios = set(args.scenario) if args.scenario else None

    demand = pd.concat([read_demand(p) for p in find_demand_files(scenarios)], ignore_index=True)

    if countries:
        demand = demand[demand["COUNTRY"].isin(countries)].copy()

    if demand.empty:
        raise ValueError("No demand rows remain after filtering. Check country/scenario names.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    country_year = (
        demand
        .groupby(["COUNTRY", "SCENARIO", "YEAR"], as_index=False)["VALUE"]
        .sum()
        .sort_values(["COUNTRY", "SCENARIO", "YEAR"])
    )

    country_summary = (
        country_year
        .groupby(["COUNTRY", "SCENARIO"])
        .agg(
            first_year=("YEAR", "min"),
            last_year=("YEAR", "max"),
            first_value=("VALUE", "first"),
            last_value=("VALUE", "last"),
            min_value=("VALUE", "min"),
            max_value=("VALUE", "max"),
            total_value=("VALUE", "sum"),
        )
        .reset_index()
    )
    country_summary["change_first_to_last"] = country_summary["last_value"] - country_summary["first_value"]
    country_summary["pct_change_first_to_last"] = country_summary["change_first_to_last"] / country_summary["first_value"]

    node_summary = (
        demand
        .groupby(["COUNTRY", "CUSTOM_NODE", "SCENARIO"])
        .agg(
            first_year=("YEAR", "min"),
            last_year=("YEAR", "max"),
            first_value=("VALUE", "first"),
            last_value=("VALUE", "last"),
            min_value=("VALUE", "min"),
            max_value=("VALUE", "max"),
            total_value=("VALUE", "sum"),
        )
        .reset_index()
    )

    warnings = build_warnings(country_year, args.warning_growth_threshold, args.warning_drop_threshold)

    country_year.to_csv(OUT_DIR / "demand_by_country_scenario_year.csv", index=False)
    country_summary.to_csv(OUT_DIR / "demand_summary_by_country_scenario.csv", index=False)
    node_summary.to_csv(OUT_DIR / "demand_summary_by_node_scenario.csv", index=False)
    warnings.to_csv(OUT_DIR / "demand_warnings.csv", index=False)

    print(f"Wrote: {OUT_DIR / 'demand_by_country_scenario_year.csv'}")
    print(f"Wrote: {OUT_DIR / 'demand_summary_by_country_scenario.csv'}")
    print(f"Wrote: {OUT_DIR / 'demand_summary_by_node_scenario.csv'}")
    print(f"Wrote: {OUT_DIR / 'demand_warnings.csv'}")

    print("\nCountry/scenario summary:")
    print(country_summary.to_string(index=False))

    if not warnings.empty:
        print("\nWARNINGS:")
        print(warnings.to_string(index=False))
    else:
        print("\nNo major demand warnings found.")


if __name__ == "__main__":
    main()
