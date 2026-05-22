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

# The comparison workbook stores percentage columns as ratios, e.g. 0.06 = 6%.
THRESHOLD_RATIO = 0.05
THRESHOLD_PERCENT = THRESHOLD_RATIO * 100
AUDIT_COLUMNS = ["scenario", "iso3", "custom_node", "pct_of_2040"]

# If multiple comparison workbooks exist, choose the one that matches your original
# manual workflow. Change this if you want region_constrained, region_unconstrained, etc.
PREFERRED_COMPARISON_KEYWORD = "country_constrained"
SUMMARY_SHEET = "over_5pct_summary"


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
        .strip("_")
    )


def parse_ratio(value):
    """
    Return a ratio, where 0.05 means 5%.

    Handles Excel percentage values that are read as decimals, strings such as
    '5%', and accidental percent-point values such as 5.
    """
    if pd.isna(value):
        return 0.0

    if isinstance(value, str):
        cleaned = value.replace("%", "").strip()
        if cleaned == "":
            return 0.0
        numeric = float(cleaned)
        return numeric / 100 if "%" in value else numeric

    numeric = float(value)

    # Defensive fallback: if a value larger than 1 appears in a percentage column,
    # treat it as percent points rather than a ratio.
    if numeric > 1:
        return numeric / 100

    return numeric


def iso_to_node(iso):
    return f"{str(iso).strip().upper()}XX"


def apply_growth(country_df, pct_percent):
    """
    Increase 2040 demand by pct_percent, then preserve the baseline growth ratios
    for all years after 2040.
    """
    country_df = country_df.copy()

    base_2040 = country_df.loc[country_df["YEAR"] == 2040, "VALUE"]

    if base_2040.empty:
        return country_df

    new_2040 = base_2040.iloc[0] * (1 + pct_percent / 100)
    country_df.loc[country_df["YEAR"] == 2040, "VALUE"] = new_2040

    years_after_2040 = sorted(country_df.loc[country_df["YEAR"] > 2040, "YEAR"].unique())

    previous_year = 2040
    previous_value = new_2040

    for year in years_after_2040:
        old_previous = country_df.loc[country_df["YEAR"] == previous_year, "VALUE"].iloc[0]
        old_current = country_df.loc[country_df["YEAR"] == year, "VALUE"].iloc[0]

        growth_rate = 0 if old_previous == 0 else old_current / old_previous
        new_value = previous_value * growth_rate

        country_df.loc[country_df["YEAR"] == year, "VALUE"] = new_value

        previous_year = year
        previous_value = new_value

    return country_df


def choose_comparison_file() -> Path:
    comparison_files = sorted(COMPARISON_DIR.glob("*.xlsx"))

    if not comparison_files:
        raise FileNotFoundError(f"No comparison Excel files found in: {COMPARISON_DIR}")

    preferred = [p for p in comparison_files if PREFERRED_COMPARISON_KEYWORD in p.name]
    return preferred[0] if preferred else comparison_files[0]


def load_percentage_summary(comparison_file: Path) -> pd.DataFrame:
    """
    Load the percentage-only sheet. This avoids treating PJ value columns as
    percentage columns.
    """
    try:
        comp = pd.read_excel(comparison_file, sheet_name=SUMMARY_SHEET)
    except ValueError:
        # Fallback for older workbooks: read the first sheet but only keep columns
        # that explicitly end with '(% of 2040)'.
        comp = pd.read_excel(comparison_file)

    return comp


def find_iso_column(comp: pd.DataFrame) -> str:
    for possible_col in ["iso3", "ISO3", "country", "Country"]:
        if possible_col in comp.columns:
            return possible_col

    raise ValueError("Could not find an ISO/country column in the comparison file.")


def find_scenario_percent_columns(comp: pd.DataFrame, iso_col: str) -> list[str]:
    scenario_cols = [
        col for col in comp.columns
        if col != iso_col and str(col).endswith("(% of 2040)")
    ]

    if not scenario_cols:
        raise ValueError(
            "No scenario percentage columns ending with '(% of 2040)' were found. "
            f"Check sheet '{SUMMARY_SHEET}' in the comparison workbook."
        )

    return scenario_cols


def validate_baseline(baseline: pd.DataFrame) -> None:
    for col in ["CUSTOM_NODE", "YEAR", "VALUE"]:
        if col not in baseline.columns:
            raise ValueError(f"Baseline file is missing required column: {col}")


# ============================================================
# Main workflow
# ============================================================

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    comparison_file = choose_comparison_file()
    print(f"Using comparison file: {comparison_file}")
    print(f"Using comparison sheet: {SUMMARY_SHEET}")

    if not BASELINE_FILE.exists():
        raise FileNotFoundError(f"Baseline demand file not found: {BASELINE_FILE}")

    comp = load_percentage_summary(comparison_file)
    baseline = pd.read_csv(BASELINE_FILE)

    iso_col = find_iso_column(comp)
    validate_baseline(baseline)
    scenario_cols = find_scenario_percent_columns(comp, iso_col)

    for scenario in scenario_cols:
        scenario_name = str(scenario).replace(" (% of 2040)", "")
        scenario_folder_name = clean_name(scenario_name)

        print(f"\nScenario: {scenario_name}")

        scenario_df = baseline.copy()

        flagged = comp[[iso_col, scenario]].copy()
        flagged[iso_col] = flagged[iso_col].astype(str).str.strip().str.upper()
        flagged["ratio"] = flagged[scenario].apply(parse_ratio)
        flagged = flagged[flagged["ratio"] > THRESHOLD_RATIO]

        print(f"Flagged countries (> {THRESHOLD_PERCENT:.1f}%): {len(flagged)}")

        audit_rows = []

        for _, row in flagged.iterrows():
            iso = row[iso_col]
            node = iso_to_node(iso)
            pct_percent = row["ratio"] * 100

            mask = scenario_df["CUSTOM_NODE"] == node
            country_df = scenario_df.loc[mask].copy()

            if country_df.empty:
                print(f"Skipping {iso}: node {node} not found")
                continue

            updated = apply_growth(country_df, pct_percent)
            scenario_df.loc[mask, "VALUE"] = updated["VALUE"].values

            audit_rows.append(
                {
                    "scenario": scenario_name,
                    "iso3": iso,
                    "custom_node": node,
                    "pct_of_2040": pct_percent,
                }
            )

        out_folder = OUTPUT_DIR / scenario_folder_name
        out_folder.mkdir(parents=True, exist_ok=True)

        demand_file = out_folder / "specified_annual_demand.csv"
        audit_file = out_folder / "audit.csv"

        scenario_df.to_csv(demand_file, index=False)

        # Always write headers, even when there are zero flagged countries.
        # This prevents pandas.errors.EmptyDataError in the runner.
        pd.DataFrame(audit_rows, columns=AUDIT_COLUMNS).to_csv(audit_file, index=False)

        print(f"Saved: {demand_file}")
        print(f"Saved: {audit_file}")


if __name__ == "__main__":
    main()
