from pathlib import Path
import pandas as pd

# Conversion factor
GWH_TO_PJ = 0.0036

# Assumes this script is saved in: repo_root/scripts/convert_scenario_gwh_to_pj.py
REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = REPO_ROOT / "data" / "raw"
OUTPUT_DIR = REPO_ROOT / "outputs" / "pj_converted"

# Keep this list static. Just replace the CSV files with updated versions when needed.
FILES_TO_PROCESS = [
    "AggregatedDemand_combined_node_locations_for_energy_conversion_region_unconstrained.csv",
    "AggregatedDemand_combined_node_locations_for_energy_conversion_country_constrained.csv",
    "AggregatedDemand_combined_node_locations_for_energy_conversion_country_unconstrained.csv",
    "AggregatedDemand_combined_node_locations_for_energy_conversion_region_constrained.csv",
]

# Columns that should never be converted
EXCLUDED_COLUMNS = {"iso3"}


def convert_series_gwh_to_pj(series: pd.Series) -> pd.Series:
    """
    Convert a column to numeric where possible, handling commas like '1,213.6',
    then convert GWh to PJ.
    If the column is not numeric, return it unchanged.
    """
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    )

    numeric = pd.to_numeric(cleaned, errors="coerce")

    # If nothing in the column is numeric, leave it unchanged
    if numeric.notna().sum() == 0:
        return series

    return numeric * GWH_TO_PJ


def rename_columns_to_pj(columns):
    """
    If a column name contains 'GWh' or 'gwh', rename it to 'PJ'/'pj'.
    Otherwise keep the original name.
    """
    renamed = []
    for col in columns:
        new_col = col.replace("GWh", "PJ").replace("gwh", "pj")
        renamed.append(new_col)
    return renamed


def convert_file(input_path: Path, output_path: Path) -> None:
    df = pd.read_csv(input_path)

    for col in df.columns:
        if col in EXCLUDED_COLUMNS:
            continue
        df[col] = convert_series_gwh_to_pj(df[col])

    df.columns = rename_columns_to_pj(df.columns)
    df.to_csv(output_path, index=False)
    print(f"Created: {output_path}")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    processed = 0

    for filename in FILES_TO_PROCESS:
        input_path = INPUT_DIR / filename

        if not input_path.exists():
            print(f"Missing file, skipped: {input_path}")
            continue

        output_filename = f"{input_path.stem}_PJ.csv"
        output_path = OUTPUT_DIR / output_filename

        convert_file(input_path, output_path)
        processed += 1

    if processed == 0:
        print("No files were processed. Check that your CSVs are in data/raw/ with the exact filenames above.")
    else:
        print(f"\nDone. Converted {processed} file(s) from GWh to PJ.")


if __name__ == "__main__":
    main()