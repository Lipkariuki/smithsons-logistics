import pandas as pd
from pathlib import Path


def _derive_product_hint(description: str) -> str:
    text = (description or "").upper()
    if "KEG" in text:
        return "KEG"
    if "BEER" in text:
        return "BEER"
    if "SPIRIT" in text:
        return "SPIRIT"
    return "OTHER"


def get_rate(destination: str, truck_size: str, product_type: str = "OTHER") -> float:
    csv_path = Path("data/rate_card.csv")

    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        raise Exception(f"Failed to read rate card CSV: {e}")

    # Fix column names manually due to odd structure
    df.columns = [
        "LANE DESCRIPTION",
        "SOURCE",
        "REGION",
        "DESTINATION",
        "TRUCK SIZE",
        "UNUSED",
        "RATE (KES)",
    ]

    required_columns = {"DESTINATION", "TRUCK SIZE", "RATE (KES)", "LANE DESCRIPTION"}
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"❌ Missing columns in CSV: {', '.join(missing)}")

    df_clean = df.copy()
    df_clean["DESTINATION"] = df_clean["DESTINATION"].astype(str).str.strip().str.upper()
    df_clean["TRUCK SIZE"] = df_clean["TRUCK SIZE"].astype(str).str.strip().str.upper()
    df_clean["PRODUCT_HINT"] = df_clean["LANE DESCRIPTION"].astype(str).apply(_derive_product_hint)
    df_clean["RATE (KES)"] = (
        df_clean["RATE (KES)"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .astype(float)
    )

    destination = destination.strip().upper()
    truck_size = truck_size.strip().upper()
    product = (product_type or "OTHER").strip().upper()

    match = df_clean[
        (df_clean["DESTINATION"] == destination)
        & (df_clean["TRUCK SIZE"] == truck_size)
        & (df_clean["PRODUCT_HINT"] == product)
    ]

    if match.empty and product != "OTHER":
        # fallback to lanes without explicit product marker (some CSV rows omit type)
        match = df_clean[
            (df_clean["DESTINATION"] == destination)
            & (df_clean["TRUCK SIZE"] == truck_size)
            & (df_clean["PRODUCT_HINT"] == "OTHER")
        ]

    if match.empty:
        raise ValueError("❌ Rate not found for this combination")

    rate = match["RATE (KES)"].iloc[0]
    return float(rate)

def get_dropdown_options() -> dict:
    csv_path = Path("data/rate_card.csv")

    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        raise Exception(f"Failed to read rate card CSV: {e}")

    df.columns = [
        "LANE DESCRIPTION", "SOURCE", "REGION", "DESTINATION", "TRUCK SIZE", "UNUSED", "RATE (KES)"
    ]

    df["DESTINATION"] = df["DESTINATION"].astype(str).str.strip().str.upper()
    destinations = sorted(df["DESTINATION"].dropna().unique().tolist())

    # ✅ Product type dropdown with fixed options + 'OTHER'
    product_types = ["BEER", "SPIRIT", "KEG", "OTHER"]

    return {
        "destinations": destinations,
        "product_types": product_types
    }
