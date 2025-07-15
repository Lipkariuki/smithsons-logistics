from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pathlib import Path
import pandas as pd

router = APIRouter()

@router.get("/metadata")
def get_metadata():
    csv_path = Path("data/rate_card.csv")

    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to read CSV: {str(e)}"})

    # Manually fix columns
    df.columns = [
        "LANE DESCRIPTION", "SOURCE", "REGION", "DESTINATION", "TRUCK SIZE", "UNUSED", "RATE (KES)"
    ]

    df["DESTINATION"] = df["DESTINATION"].astype(str).str.strip().str.upper()
    destinations = sorted(df["DESTINATION"].dropna().unique().tolist())

    # Fixed product type list + "OTHER"
    product_types = ["BEER", "SPIRIT", "KEG", "OTHER"]

    return JSONResponse(content={
        "destinations": destinations,
        "product_types": product_types
    })
