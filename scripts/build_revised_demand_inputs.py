from pathlib import Path
import pandas as pd
import re

# =========================
# PATHS
# =========================
REPO_ROOT = Path(__file__).resolve().parents[1]

COMPARISON_DIR = REPO_ROOT / "outputs" / "pct_of_2040"
REFERENCE_FILE = REPO_ROOT / "data" / "reference" / "2040Values.xlsx"
OUTPUT_DIR = REPO_ROOT / "data" / "generated"

THRESHOLD = 5.0
START_YEAR = 2040
END_YEAR = 2050


# =========================
# HELPERS
# =========================
def iso_to_node(iso):
    """Convert ISO3 → OSeMOSYS node (AGO → AGOXX)."""
    if pd.isna(iso):
        return iso
    return str(iso).strip() + "XX"


def clean_name(name):
    """Make safe folder names."""
    name = re.sub(r"[^\w\s-]", "", str(name))
    return re.sub(r"\s+", "_", name.strip())


def find_comparison_file():
    files = []
    for ext in ["*.xlsx", "*.csv"]:
        for f in COMPARISON_DIR.glob(ext):
            if not f.name.startswith("~$"):
                files.append(f)

    if not files:
        raise FileNotFoundError("No comparison file found")

    return max(files, key=lambda x: x.stat().st_mtime)


def parse_percent(val):
    """Convert % values into float."""
    if pd.isna(val):
        return None

    if isinstance(val, str):
        val = val.replace("%", "").strip()
        return float(val)

    # if Excel stored as decimal
    if val <= 2:
        return val * 100

    return float(val)


# =========================
# LOAD REFERENCE DEMAND
# =========================
def load_reference():
    df = pd.read_excel(REFERENCE_FILE, header=None)

    years = df.iloc[2:, 0]
    iso_codes = df.iloc[1, 1:]
    values = df.iloc[2:, 1:]

    long_df = pd.DataFrame(values.values, columns=iso_codes)
    long_df.insert(0, "YEAR", years.values)

    long_df = long_df.melt(id_vars="YEAR", var_name="ISO3", value_name="VALUE")

    # convert to node format
    long_df["CUSTOM_NODE"] = long_df["ISO3"].apply(iso_to_node)

    return long_df[["CUSTOM_NODE", "YEAR", "VALUE"]]


# =========================
# APPLY GROWTH
# =========================
def apply_growth(df_country, pct):
    df_country = df_country.sort_values("YEAR").copy()

    base_2040 = df_country.loc[df_country["YEAR"] == 2040, "VALUE"].values[0]
    base_2050 = df_country.loc[df_country["YEAR"] == 2050, "VALUE"].values[0]

    new_2040 = base_2040 * (1 + pct / 100)

    if base_2040 > 0:
        growth = (base_2050 / base_2040) ** (1 / (2050 - 2040))
    else:
        growth = 1.0

    for y in range(2040, 2050 + 1):
        df_country.loc[df_country["YEAR"] == y, "VALUE"] = new_2040 * (growth ** (y - 2040))

    return df_country


# =========================
# MAIN
# =========================
def main():

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    comparison_file = find_comparison_file()
    print(f"Using comparison file: {comparison_file}")

    # Load comparison
    if comparison_file.suffix == ".csv":
        comp = pd.read_csv(comparison_file)
    else:
        comp = pd.read_excel(comparison_file)

    iso_col = "ISO3"

    scenario_cols = [c for c in comp.columns if "% of 2040" in str(c)]

    baseline = load_reference()

    for scenario in scenario_cols:

        scenario_name = scenario.replace(" (% of 2040)", "")
        print(f"\nScenario: {scenario_name}")

        scenario_df = baseline.copy()

        flagged = comp[[iso_col, scenario]].copy()
        flagged["pct"] = flagged[scenario].apply(parse_percent)

        flagged = flagged[flagged["pct"] > THRESHOLD]

        print(f"Flagged countries (> {THRESHOLD}%): {len(flagged)}")

        for _, row in flagged.iterrows():

            iso = row[iso_col]
            node = iso_to_node(iso)
            pct = row["pct"]

            mask = scenario_df["CUSTOM_NODE"] == node
            country_df = scenario_df.loc[mask].copy()

            if country_df.empty:
                print(f"Skipping {iso}")
                continue

            updated = apply_growth(country_df, pct)

            scenario_df.loc[mask, "VALUE"] = updated["VALUE"].values

        out_folder = OUTPUT_DIR / clean_name(scenario_name)
        out_folder.mkdir(parents=True, exist_ok=True)

        out_file = out_folder / "specified_annual_demand.csv"
        scenario_df.to_csv(out_file, index=False)

        print(f"Saved: {out_file}")


if __name__ == "__main__":
    main() 