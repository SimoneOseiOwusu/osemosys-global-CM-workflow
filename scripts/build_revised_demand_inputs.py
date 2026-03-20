
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

# =========================
# User settings
# =========================
REPO_ROOT = Path(__file__).resolve().parents[1]

COMPARISON_DIR = REPO_ROOT / "outputs" / "pct_of_2040"
BASELINE_DEMAND_FILE = REPO_ROOT / "data" / "reference" / "2040Values.xlsx"
GENERATED_DIR = REPO_ROOT / "data" / "generated"

THRESHOLD_PERCENT = 5.0
START_YEAR = 2040
END_YEAR = 2050

# False = use average 2040-2050 CAGR (matches your manual description)
# True  = preserve exact year-by-year growth factors from the baseline workbook
USE_EXACT_YEARLY_PATTERN = False

ISO_COL_CANDIDATES = ["ISO3", "CUSTOM_NODE", "REGION"]
BASELINE_NODE_COL = "CUSTOM_NODE"
BASELINE_YEAR_COL = "YEAR"
BASELINE_VALUE_COL = "VALUE"

PREFERRED_SHEETS = ["over_5pct_summary", "comparison"]


def sanitize_name(name: str) -> str:
    name = re.sub(r"[^\w\s-]", "", str(name)).strip()
    return re.sub(r"[\s/]+", "_", name)


def find_latest_comparison_file(directory: Path) -> Path:
    candidates = []
    for ext in ("*.xlsx", "*.xls", "*.csv"):
        candidates.extend(directory.glob(ext))
    if not candidates:
        raise FileNotFoundError(f"No comparison file found in: {directory}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def detect_iso_column(df: pd.DataFrame) -> str:
    for col in ISO_COL_CANDIDATES:
        if col in df.columns:
            return col
    raise KeyError(f"Could not find ISO column. Tried: {ISO_COL_CANDIDATES}")


def read_comparison_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        xls = pd.ExcelFile(path)
        sheet_to_use = next((s for s in PREFERRED_SHEETS if s in xls.sheet_names), xls.sheet_names[0])
        df = pd.read_excel(path, sheet_name=sheet_to_use)

    iso_col = detect_iso_column(df)
    keep_cols = [iso_col] + [c for c in df.columns if c != iso_col and "% of 2040" in str(c)]
    if len(keep_cols) <= 1:
        raise ValueError("No scenario columns containing '% of 2040' were found in the comparison table.")
    return df[keep_cols].copy()


def parse_series_to_percent_points(series: pd.Series) -> pd.Series:
    explicit_percent = series.astype(str).str.contains("%", regex=False, na=False)

    def _parse_value(x):
        if pd.isna(x):
            return pd.NA
        if isinstance(x, str):
            x = x.strip()
            if x == "":
                return pd.NA
            x = x.replace(",", "")
            if x.endswith("%"):
                x = x[:-1].strip()
            return float(x)
        return float(x)

    parsed = series.map(_parse_value)
    numeric_without_percent = parsed[~explicit_percent & parsed.notna()]
    if not numeric_without_percent.empty and numeric_without_percent.abs().max() <= 2:
        parsed.loc[~explicit_percent & parsed.notna()] = parsed.loc[~explicit_percent & parsed.notna()] * 100
    return parsed.astype("Float64")


def read_reference_workbook(path: Path) -> pd.DataFrame:
    """
    Reads data/reference/2040Values.xlsx in its current wide layout:
    - first sheet
    - row 2 holds ISO3 codes across columns
    - column A holds years
    Returns long-form rows: CUSTOM_NODE, YEAR, VALUE
    """
    raw = pd.read_excel(path, sheet_name=0, header=None)

    iso_headers = raw.iloc[1, 1:].tolist()
    year_labels = pd.to_numeric(raw.iloc[2:, 0], errors="coerce")
    values = raw.iloc[2:, 1:].copy()

    values.columns = iso_headers
    values.insert(0, BASELINE_YEAR_COL, year_labels.values)

    long_df = values.melt(
        id_vars=[BASELINE_YEAR_COL],
        var_name=BASELINE_NODE_COL,
        value_name=BASELINE_VALUE_COL,
    )

    long_df = long_df.dropna(subset=[BASELINE_NODE_COL, BASELINE_YEAR_COL])
    long_df[BASELINE_NODE_COL] = long_df[BASELINE_NODE_COL].astype(str).str.strip().str.upper()
    long_df[BASELINE_YEAR_COL] = pd.to_numeric(long_df[BASELINE_YEAR_COL], errors="coerce").astype("Int64")
    long_df[BASELINE_VALUE_COL] = pd.to_numeric(long_df[BASELINE_VALUE_COL], errors="coerce")

    long_df = long_df.dropna(subset=[BASELINE_YEAR_COL])
    long_df = long_df.sort_values([BASELINE_NODE_COL, BASELINE_YEAR_COL]).reset_index(drop=True)
    return long_df


def compute_growth_factor(base_2040: float, base_2050: float) -> float:
    if pd.isna(base_2040) or pd.isna(base_2050):
        return 1.0
    if base_2040 > 0 and base_2050 > 0:
        return (base_2050 / base_2040) ** (1 / (END_YEAR - START_YEAR))
    return 1.0


def apply_revised_cagr(df_country: pd.DataFrame, pct_increase: float) -> tuple[pd.DataFrame, dict]:
    df_country = df_country.copy().sort_values(BASELINE_YEAR_COL)

    base_2040 = float(df_country.loc[df_country[BASELINE_YEAR_COL] == START_YEAR, BASELINE_VALUE_COL].iloc[0])
    base_2050 = float(df_country.loc[df_country[BASELINE_YEAR_COL] == END_YEAR, BASELINE_VALUE_COL].iloc[0])

    new_2040 = base_2040 * (1 + pct_increase / 100.0)
    growth_factor = compute_growth_factor(base_2040, base_2050)

    for year in range(START_YEAR, END_YEAR + 1):
        df_country.loc[df_country[BASELINE_YEAR_COL] == year, BASELINE_VALUE_COL] = (
            new_2040 * (growth_factor ** (year - START_YEAR))
        )

    return df_country, {
        "method": "cagr",
        "base_2040": base_2040,
        "base_2050": base_2050,
        "pct_increase": pct_increase,
        "new_2040": new_2040,
        "growth_factor": growth_factor,
        "new_2050": new_2040 * (growth_factor ** (END_YEAR - START_YEAR)),
    }


def apply_revised_yearly_pattern(df_country: pd.DataFrame, pct_increase: float) -> tuple[pd.DataFrame, dict]:
    df_country = df_country.copy().sort_values(BASELINE_YEAR_COL)

    year_to_base = dict(zip(df_country[BASELINE_YEAR_COL], df_country[BASELINE_VALUE_COL]))

    base_2040 = float(year_to_base[START_YEAR])
    base_2050 = float(year_to_base[END_YEAR])
    new_values = {START_YEAR: base_2040 * (1 + pct_increase / 100.0)}

    for year in range(START_YEAR + 1, END_YEAR + 1):
        prev_base = year_to_base.get(year - 1)
        curr_base = year_to_base.get(year)
        if pd.notna(prev_base) and pd.notna(curr_base) and prev_base not in (0, None):
            annual_factor = float(curr_base) / float(prev_base)
        else:
            annual_factor = 1.0
        new_values[year] = new_values[year - 1] * annual_factor

    for year, value in new_values.items():
        df_country.loc[df_country[BASELINE_YEAR_COL] == year, BASELINE_VALUE_COL] = value

    return df_country, {
        "method": "yearly_pattern",
        "base_2040": base_2040,
        "base_2050": base_2050,
        "pct_increase": pct_increase,
        "new_2040": new_values[START_YEAR],
        "new_2050": new_values[END_YEAR],
    }


def scenario_name_from_column(col: str) -> str:
    return str(col).replace(" (% of 2040)", "").strip()


def main():
    comparison_file = find_latest_comparison_file(COMPARISON_DIR)
    print(f"Using comparison file: {comparison_file}")

    comparison_df = read_comparison_table(comparison_file)
    iso_col = detect_iso_column(comparison_df)
    baseline_df = read_reference_workbook(BASELINE_DEMAND_FILE)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    scenario_cols = [c for c in comparison_df.columns if c != iso_col]
    audit_rows = []

    for scenario_col in scenario_cols:
        scenario_name = scenario_name_from_column(scenario_col)
        scenario_folder = GENERATED_DIR / sanitize_name(scenario_name)
        scenario_folder.mkdir(parents=True, exist_ok=True)

        scenario_output_df = baseline_df.copy()
        pct_series = parse_series_to_percent_points(comparison_df[scenario_col])

        flagged = comparison_df.loc[pct_series > THRESHOLD_PERCENT, [iso_col]].copy()
        flagged["pct_increase"] = pct_series[pct_series > THRESHOLD_PERCENT].values

        print(f"\nScenario: {scenario_name}")
        print(f"Flagged countries (> {THRESHOLD_PERCENT}%): {len(flagged)}")

        for _, row in flagged.iterrows():
            iso3 = str(row[iso_col]).strip().upper()
            pct_increase = float(row["pct_increase"])

            country_mask = (
                (scenario_output_df[BASELINE_NODE_COL] == iso3) &
                (scenario_output_df[BASELINE_YEAR_COL] >= START_YEAR) &
                (scenario_output_df[BASELINE_YEAR_COL] <= END_YEAR)
            )
            country_df = scenario_output_df.loc[country_mask].copy()

            if country_df.empty:
                print(f"  - Skipping {iso3}: not found in baseline workbook")
                audit_rows.append({
                    "scenario": scenario_name, "iso3": iso3,
                    "pct_increase": pct_increase, "status": "missing_in_baseline"
                })
                continue

            needed_years = set(range(START_YEAR, END_YEAR + 1))
            present_years = set(country_df[BASELINE_YEAR_COL].astype(int).tolist())
            if not needed_years.issubset(present_years):
                print(f"  - Skipping {iso3}: missing one or more years between {START_YEAR} and {END_YEAR}")
                audit_rows.append({
                    "scenario": scenario_name, "iso3": iso3,
                    "pct_increase": pct_increase, "status": "missing_years"
                })
                continue

            if USE_EXACT_YEARLY_PATTERN:
                updated_country_df, audit = apply_revised_yearly_pattern(country_df, pct_increase)
            else:
                updated_country_df, audit = apply_revised_cagr(country_df, pct_increase)

            for _, updated_row in updated_country_df.iterrows():
                mask = (
                    (scenario_output_df[BASELINE_NODE_COL] == iso3) &
                    (scenario_output_df[BASELINE_YEAR_COL] == updated_row[BASELINE_YEAR_COL])
                )
                scenario_output_df.loc[mask, BASELINE_VALUE_COL] = updated_row[BASELINE_VALUE_COL]

            audit_rows.append({
                "scenario": scenario_name,
                "iso3": iso3,
                "pct_increase": pct_increase,
                "status": "updated",
                **audit,
            })

        output_file = scenario_folder / "specified_annual_demand.csv"
        scenario_output_df.to_csv(output_file, index=False)
        print(f"Saved: {output_file}")

    audit_df = pd.DataFrame(audit_rows)
    audit_file = GENERATED_DIR / "revised_demand_audit.csv"
    audit_df.to_csv(audit_file, index=False)
    print(f"\nSaved audit log: {audit_file}")


if __name__ == "__main__":
    main()
  