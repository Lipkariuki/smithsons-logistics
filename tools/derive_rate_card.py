"""
Derive an updated rate card CSV from recent payment spreadsheets (XLS/XLSX/CSV).

Usage examples:
  python backend/tools/derive_rate_card.py --inputs backend/data/payments \
    --output backend/data/rate_card.updated.csv --agg median

Inputs can be a mix of .xls/.xlsx/.csv files, or a directory containing them.

Output format matches what the backend expects (7 columns), and the backend
renames columns internally, so the header values are advisory:
  ["LANE DESCRIPTION","SOURCE","REGION","DESTINATION","TRUCK SIZE","UNUSED","RATE (KES)"]

Assumptions:
  - We aggregate to one rate per (DESTINATION, TRUCK SIZE) using median by default.
  - DESTINATION and TRUCK SIZE are normalized to uppercase; sizes are mapped via helpers.
  - SOURCE set to "NBO" and REGION blank, unless provided via --source/--region.

If openpyxl is not installed and you supply .xlsx/.xls, install it:
  pip install openpyxl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List, Dict, Tuple

import pandas as pd


def _iter_input_files(paths: List[str]) -> List[Path]:
    files: List[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for ext in ("*.xlsx", "*.xls", "*.csv"):
                files.extend(sorted(path.rglob(ext)))
        elif path.is_file():
            files.append(path)
        else:
            print(f"[WARN] Missing path: {path}")
    return files


def _read_table(path: Path) -> pd.DataFrame:
    try:
        if path.suffix.lower() in (".xlsx", ".xls"):
            # Requires openpyxl/xlrd depending on file type
            return pd.read_excel(path)
        return pd.read_csv(path)
    except Exception as e:
        raise RuntimeError(f"Failed to read {path}: {e}")


def _find_col(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    cols = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        key = cand.lower().strip()
        if key in cols:
            return cols[key]
    # try contains matches
    for c in df.columns:
        lc = c.lower()
        for cand in candidates:
            if cand.lower() in lc:
                return c
    return None


def normalize_destination(value: str | float | int | None) -> str:
    if value is None:
        return ""
    s = str(value).strip().upper()
    # Common cleanups
    s = s.replace("  ", " ")
    return s


def normalize_size(raw: str | float | int | None) -> str:
    if raw is None:
        return ""
    s = str(raw).strip().upper().replace(" ", "")
    # Map common synonyms
    synonyms = {
        "PICKUP": "P/UP",
        "P-UP": "P/UP",
        "P/U": "P/UP",
        "P/UP": "P/UP",
        "P/U.P": "P/UP",
        "P/UP." : "P/UP",
        "VAN": "VAN",
    }
    if s in synonyms:
        return synonyms[s]
    # Extract tonnage like 14T, 7.5T, 30T from various patterns
    num = ""
    dot_seen = False
    for ch in s:
        if ch.isdigit():
            num += ch
        elif ch == "." and not dot_seen:
            num += ch
            dot_seen = True
    if num:
        # Normalize to X or X.Y with trailing T
        if num.endswith("."):
            num = num[:-1]
        if num:
            return f"{num}T"
    return s


def to_number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    # Remove thousands separators & currency
    s = s.replace(",", "")
    for pref in ("KES", "KSH", "KSH.", "KSHS", "KSHS."):
        if s.upper().startswith(pref):
            s = s[len(pref):].strip()
    try:
        return float(s)
    except ValueError:
        return None


def build_rate_card(
    dataframes: List[pd.DataFrame],
    default_source: str = "NBO",
    default_region: str = "",
    agg: str = "median",
) -> pd.DataFrame:
    rows: List[dict] = []
    # Column candidates
    dest_cols = ["destination", "dest", "town", "to"]
    # Do NOT include plain 'truck' (it's often the plate number)
    size_cols = ["size", "truck size", "truck_size", "tonnage", "capacity"]
    lane_cols = ["lane description", "route description", "lane", "route"]
    cost_cols = ["cost"]
    amt_cols = ["amount", "paid", "payment", "rate", "price", "charge"]

    for df in dataframes:
        dcol = _find_col(df, dest_cols)
        scol = _find_col(df, size_cols)
        lcol = _find_col(df, lane_cols)
        ccol = _find_col(df, cost_cols)
        acol = _find_col(df, amt_cols)
        if not acol:
            print(f"[WARN] Skipping a sheet missing amount column: amount={acol}")
            continue
        for _, r in df.iterrows():
            # destination
            dest = normalize_destination(r.get(dcol)) if dcol else ""
            # size
            size = normalize_size(r.get(scol)) if scol else ""
            # Fallback: parse from lane/route description like
            #   "F24 -NBO - NANYUKI - Beer - 14T DIST" or
            #   "F24 -NBO - UMOJA EB - Keg - 14T Offloading"
            if (not dest or not size) and lcol:
                lane = str(r.get(lcol) or "").strip()
                if lane:
                    parts = [p.strip() for p in lane.split("-") if str(p).strip()]
                    # Expected sequence: CODE, SOURCE, DEST, PRODUCT, SIZE [rest]
                    if len(parts) >= 5:
                        if not dest:
                            dest = normalize_destination(parts[2])
                        if not size:
                            size = normalize_size(parts[4])
                    else:
                        # Try last token as size and third token as destination where possible
                        if not dest and len(parts) >= 3:
                            dest = normalize_destination(parts[2])
                        if not size and parts:
                            size = normalize_size(parts[-1])
            # Filter: include only DIST rows, exclude OFFL / Offloading
            lane_text = str(r.get(lcol) or "") if lcol else ""
            lane_low = lane_text.lower()
            cost_text = str(r.get(ccol) or "") if ccol else ""
            cost_low = cost_text.lower()
            is_offload = ("offl" in lane_low) or ("offload" in lane_low) or ("offl" in cost_low) or ("offload" in cost_low)
            is_dist = ("dist" in lane_low) or ("dist" in cost_low)
            if is_offload or not is_dist:
                continue

            amt = to_number(r.get(acol))
            if dest and size and amt is not None and amt > 0:
                rows.append({"DESTINATION": dest, "TRUCK SIZE": size, "AMOUNT": amt})

    if not rows:
        raise SystemExit("No usable rows found in provided files.")

    tmp = pd.DataFrame(rows)
    if agg == "median":
        grouped = tmp.groupby(["DESTINATION", "TRUCK SIZE"], as_index=False)["AMOUNT"].median()
    elif agg == "mean":
        grouped = tmp.groupby(["DESTINATION", "TRUCK SIZE"], as_index=False)["AMOUNT"].mean()
    elif agg == "latest":
        # Without proper dates, latest == last occurrence order; median is safer
        grouped = tmp.groupby(["DESTINATION", "TRUCK SIZE"], as_index=False)["AMOUNT"].last()
    else:
        raise SystemExit(f"Unsupported agg: {agg}")

    # Compose output with 7 columns
    out = pd.DataFrame({
        "LANE DESCRIPTION": [f"AUTO - {d} - {s}" for d, s in zip(grouped["DESTINATION"], grouped["TRUCK SIZE"])],
        "SOURCE": default_source,
        "REGION": default_region,
        "DESTINATION": grouped["DESTINATION"],
        "TRUCK SIZE": grouped["TRUCK SIZE"],
        "UNUSED": "",
        "RATE (KES)": grouped["AMOUNT"].round(2),
    })
    return out


def canonicalize_rate_card(df: pd.DataFrame) -> pd.DataFrame:
    expected = [
        "LANE DESCRIPTION", "SOURCE", "REGION", "DESTINATION", "TRUCK SIZE", "UNUSED", "RATE (KES)"
    ]
    # fit to 7 columns
    if len(df.columns) >= 7:
        df = df.iloc[:, :7].copy()
        df.columns = expected
    else:
        # pad columns
        new_df = df.copy()
        while len(new_df.columns) < 7:
            new_df[f"UNUSED_{len(new_df.columns)}"] = ""
        new_df = new_df.iloc[:, :7]
        new_df.columns = expected
        df = new_df

    df["DESTINATION"] = df["DESTINATION"].astype(str).str.strip().str.upper()
    df["TRUCK SIZE"] = df["TRUCK SIZE"].astype(str).str.strip().str.upper()
    df["RATE (KES)"] = (
        df["RATE (KES)"].astype(str).str.replace(",", "", regex=False).str.strip().replace("", "0").astype(float)
    )
    return df


def merge_with_baseline(baseline_csv: Path, updates_df: pd.DataFrame) -> pd.DataFrame:
    base_raw = pd.read_csv(baseline_csv)
    base = canonicalize_rate_card(base_raw)
    updates = canonicalize_rate_card(updates_df.copy())

    upd_map: Dict[Tuple[str, str], float] = {}
    for _, r in updates.iterrows():
        k = (str(r["DESTINATION"]).upper(), str(r["TRUCK SIZE"]).upper())
        upd_map[k] = float(r["RATE (KES)"])

    new_rates: List[float] = []
    for _, r in base.iterrows():
        k = (r["DESTINATION"], r["TRUCK SIZE"])
        new_rates.append(upd_map.get(k, r["RATE (KES)"]))
    base["RATE (KES)"] = pd.Series(new_rates).round(2)
    return base


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Derive rate card CSV from payment spreadsheets")
    p.add_argument("--inputs", nargs="+", required=True, help="Files or directories of XLS/XLSX/CSV")
    p.add_argument("--output", required=True, help="Output CSV path")
    p.add_argument("--merge-with", default=None, help="Baseline CSV to merge against (retain rows not present in inputs)")
    p.add_argument("--agg", default="median", choices=["median", "mean", "latest"], help="Aggregation method")
    p.add_argument("--source", default="NBO", help="Default SOURCE column value")
    p.add_argument("--region", default="", help="Default REGION column value")
    args = p.parse_args(argv)

    files = _iter_input_files(args.inputs)
    if not files:
        print("No input files found.")
        return 2
    dfs = []
    for f in files:
        try:
            dfs.append(_read_table(f))
            print(f"Loaded: {f}")
        except Exception as e:
            print(e)

    out_df = build_rate_card(dfs, default_source=args.source, default_region=args.region, agg=args.agg)
    if args.merge_with:
        out_df = merge_with_baseline(Path(args.merge_with), out_df)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False)
    print(f"✅ Wrote updated rate card: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
