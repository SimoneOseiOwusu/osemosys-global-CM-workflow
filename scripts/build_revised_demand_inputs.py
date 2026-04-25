from pathlib import Path
import pandas as pd


# ============================================================
# Paths and settings
# ============================================================

REPO_ROOT = Path(__file__).resolve().parents[1]

COMPARISON_DIR = REPO_ROOT / "outputs" / "pct_of_2040"

BASELINE_FILE = (
    REPO_ROOT
    / "external"
    / "osemosys_global"
    / "resources"
    / "data"
    / "custom"
    / "specified_annual_demand.csv"
)

OUTPUT_DIR = REPO_ROOT / "data" / "generated"

THRESHOLD = 5.0


# ============================================================
# Helper functions
# ============================================================

def clean_name(name):
    return (
        str(name)
        .replace(" ", "_")
        .replace("/", "_")
        .replace("(", "")
        .replace(")", "")
        .replace("%", "pct")
        .replace("__", "_")
    )


def parse_percent(value):
    if pd.isna(value):
        return 0.0

    if isinstance(value, str):
        value = value.replace("%", "").strip()

    return float(value)


def iso_to_node(iso):
    return f"{iso}XX"


def apply_growth(country_df, pct):
    country_df = country_df.copy()

    base_2040 = country_df.loc[country_df["YEAR"] == 2040, "VALUE"]

    if base_2040.empty:
        return country_df

    new_2040 = base_2040.iloc[0] * (1 + pct / 100)

    country_df.loc[country_df["YEAR"] == 2040, "VALUE"] = new_2040

    years_after_2040 = sorted(
        country_df.loc[country_df["YEAR"] > 2040, "YEAR"].unique()
    )

    previous_year = 2040
    previous_value = new_2040

    for year in years_after_2040:
        old_previous = country_df.loc[
            country_df["YEAR"] == previous_year, "VALUE"
        ].iloc[0]

        old_current = country_df.loc[
            country_df["YEAR"] == year, "VALUE"
        ].iloc[0]

        if old_previous == 0:
            growth_rate = 0
        else:
            growth_rate = old_current / old_previous

        new_value = previous_value * growth_rate

        country_df.loc[country_df["YEAR"] == year, "VALUE"] = new_value

        previous_year = year
        previous_value = new_value

    return country_df


# ============================================================
# Main workflow
# ============================================================

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    comparison_files = sorted(COMPARISON_DIR.glob("*.xlsx"))

    if not comparison_files:
        raise FileNotFoundError(
            f"No comparison Excel files found in: {COMPARISON_DIR}"
        )

    comparison_file = comparison_files[0]
    print(f"Using comparison file: {comparison_file}")

    if not BASELINE_FILE.exists():
        raise FileNotFoundError(
            f"Baseline demand file not found: {BASELINE_FILE}"
        )

    comp = pd.read_excel(comparison_file)
    baseline = pd.read_csv(BASELINE_FILE)

    iso_col = None
    for possible_col in ["iso3", "ISO3", "country", "Country"]:
        if possible_col in comp.columns:
            iso_col = possible_col
            break

    if iso_col is None:
        raise ValueError(
            "Could not find an ISO/country column in the comparison file."
        )

    required_baseline_cols = ["CUSTOM_NODE", "YEAR", "VALUE"]

    for col in required_baseline_cols:
        if col not in baseline.columns:
            raise ValueError(
                f"Baseline file is missing required column: {col}"
            )

    scenario_cols = [
        col for col in comp.columns
        if col != iso_col and "2040" in str(col)
    ]

    if not scenario_cols:
        raise ValueError(
            "No scenario columns containing '2040' were found."
        )

    for scenario in scenario_cols:
        scenario_name = str(scenario).replace(" (% of 2040)", "")
        scenario_folder_name = clean_name(scenario_name)

        print(f"\nScenario: {scenario_name}")

        scenario_df = baseline.copy()

        flagged = comp[[iso_col, scenario]].copy()
        flagged["pct"] = flagged[scenario].apply(parse_percent)
        flagged = flagged[flagged["pct"] > THRESHOLD]

        print(f"Flagged countries (> {THRESHOLD}%): {len(flagged)}")

        audit_rows = []

        for _, row in flagged.iterrows():
            iso = row[iso_col]
            node = iso_to_node(iso)
            pct = row["pct"]

            mask = scenario_df["CUSTOM_NODE"] == node
            country_df = scenario_df.loc[mask].copy()

            if country_df.empty:
                print(f"Skipping {iso}: node {node} not found")
                continue

            updated = apply_growth(country_df, pct)

            scenario_df.loc[mask, "VALUE"] = updated["VALUE"].values

            audit_rows.append(
                {
                    "scenario": scenario_name,
                    "iso3": iso,
                    "custom_node": node,
                    "pct_of_2040": pct,
                }
            )

        out_folder = OUTPUT_DIR / scenario_folder_name
        out_folder.mkdir(parents=True, exist_ok=True)

        demand_file = out_folder / "specified_annual_demand.csv"
        audit_file = out_folder / "audit.csv"

        scenario_df.to_csv(demand_file, index=False)
        pd.DataFrame(audit_rows).to_csv(audit_file, index=False)

        print(f"Saved: {demand_file}")
        print(f"Saved: {audit_file}")


if __name__ == "__main__":
    main() 