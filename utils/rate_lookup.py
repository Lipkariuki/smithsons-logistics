# utils/rate_lookup.py

import pandas as pd
import os

RATE_CARD_PATH = os.path.join(os.path.dirname(__file__), "../data/rate_card.csv")

def get_rate(destination: str, truck_size: str, product_type: str) -> float:
    try:
        df = pd.read_csv(RATE_CARD_PATH)

        row = df[
            (df["destination"].str.strip().str.lower() == destination.strip().lower()) &
            (df["size"].str.strip().str.lower() == truck_size.strip().lower()) &
            (df["product_type"].str.strip().str.lower() == product_type.strip().lower())
        ]

        if row.empty:
            raise ValueError("Rate not found")

        return float(row.iloc[0]["rate"])
    except Exception as e:
        print("Rate lookup failed:", e)
        return 0.0
