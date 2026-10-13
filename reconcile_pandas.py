"""Version 1: reconcile Finland's real-time electricity balance in pandas.

For every 3-minute slot:  difference = (production - net exports) - consumption
Run:  python reconcile_pandas.py --start 2026-10-06T00:00:00Z --end 2026-10-10T00:00:00Z
"""
import os
import sys
import time

import pandas as pd

from fingrid_api import DATASETS, fetch_all_datasets, parse_period

TOLERANCE = 0.5   # allowed difference, as % of production
FILL_GAPS = False  # Off: filled values breached tolerance in 4 of 9 reconcilable
                   # cases, against about 1% for original readings (1 to 10 Oct 2026)
SLOT = pd.Timedelta(minutes=3)
BORDERS = ["north_swed", "cent_swed", "estonia", "norway"]  # positive = export


class Tee:
    """Write everything printed to both the terminal and a file."""

    def __init__(self, filename):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.file = open(os.path.join(script_dir, filename), "w")
        self.stdout = sys.stdout

    def write(self, text):
        self.stdout.write(text)
        self.file.write(text)

    def flush(self):
        self.stdout.flush()
        self.file.flush()


def normalise_intervals(df, fill_gaps=FILL_GAPS):
    """Give every reading its own 3-minute slot.

    Some real-time records claim to last 6 minutes. Analysis showed their end
    time is wrong, so each record keeps only its first slot ('endtime_fixed').
    If fill_gaps is True and the next slot has no reading of its own, the value
    is carried into it ('filled_from_previous').
    """
    df = df.sort_values("startTime").reset_index(drop=True).copy()
    long = (df["endTime"] - df["startTime"]) > SLOT

    df["endTime"] = df["startTime"] + SLOT
    df["value_status"] = "original"
    df.loc[long, "value_status"] = "endtime_fixed"

    if fill_gaps:
        own_starts = set(df["startTime"])
        fills = []
        for _, r in df[long].iterrows():
            next_slot = r["startTime"] + SLOT
            if next_slot not in own_starts:
                fills.append({"startTime": next_slot,
                              "endTime": next_slot + SLOT,
                              "value": r["value"],
                              "value_status": "filled_from_previous"})
        if fills:
            df = pd.concat([df, pd.DataFrame(fills)], ignore_index=True)

    df = df.sort_values("startTime").reset_index(drop=True)
    return df[["startTime", "endTime", "value", "value_status"]]


def to_15min(df):
    """Average 3-minute values into 15-minute blocks (average power, MW),
    and count how many readings each average is based on (at most 5)."""
    out = df.set_index("startTime")["value"].resample("15min").agg(["mean", "count"])
    out = out.rename(columns={"mean": "value", "count": "reading_count"})
    out["endTime"] = out.index + pd.Timedelta(minutes=15)
    return out.reset_index()[["startTime", "endTime", "value", "reading_count"]]


def build_table(frames, interval, start, end):
    """Join datasets onto the full grid of slots that SHOULD exist."""
    selected = {n: m["df"] for n, m in frames.items() if m["interval"] == interval}

    grid = pd.date_range(start=start, end=end, freq=f"{interval}min", inclusive="left")
    table = pd.DataFrame({"startTime": grid,
                          "endTime": grid + pd.Timedelta(minutes=interval)})

    for name, df in selected.items():
        check = df[["startTime", "endTime"]].merge(
            table[["startTime", "endTime"]], on=["startTime", "endTime"],
            how="left", indicator=True)
        off_grid = (check["_merge"] == "left_only").sum()
        if off_grid:
            print(f"  WARNING: {off_grid} {name} rows don't fit the {interval}-minute grid")

        value_cols = [c for c in df.columns if c not in ("startTime", "endTime")]
        table = table.merge(df[["startTime", "endTime"] + value_cols],
                            on=["startTime", "endTime"], how="left",
                            validate="one_to_one")
    return table


def reconcile(table, suffix=""):
    """Add the balance calculation. Missing inputs give a blank difference."""
    prod, cons = f"production{suffix}", f"consumption{suffix}"
    borders = [f"{b}{suffix}" for b in BORDERS]
    table["net_exports"] = table[borders].sum(axis=1, min_count=len(borders))
    table["reconciled"] = table[prod] - table["net_exports"]
    table["difference"] = table["reconciled"] - table[cons]
    table["difference_percent"] = table["difference"].abs() / table[prod] * 100
    return table


def print_summary(table, title, suffix=""):
    prod, cons = f"production{suffix}", f"consumption{suffix}"
    readings = [f"{n}{suffix}" for n in ["production", "consumption"] + BORDERS]
    breaches = table["difference_percent"] > TOLERANCE

    print(f"\nSummary of {title}:")
    print("  Total slots:                              ", len(table))
    print("  Rows with missing values:                 ", table.isnull().any(axis=1).sum())
    print("  Slots with no reading in any dataset:     ", table[readings].isna().all(axis=1).sum())
    print("  Production missing:                       ", table[prod].isna().sum())
    print("  Consumption missing:                      ", table[cons].isna().sum())
    print("  Production and consumption both missing:  ",
          (table[prod].isna() & table[cons].isna()).sum())
    print("  Max absolute difference (MW):             ", round(table["difference"].abs().max(), 2))
    print(f"  Slots exceeding tolerance ({TOLERANCE}%):        ", breaches.sum())

    if "window_complete" in table.columns:
        by_window = table.groupby("window_complete").agg(
            windows=("difference", "size"),
            breaches=("difference_percent", lambda s: (s > TOLERANCE).sum()),
            max_abs_difference=("difference", lambda s: round(s.abs().max(), 2)))
        print("\n  Breaches by window completeness (complete = all six datasets have 5 readings):")
        print(by_window.to_string())

    status_col = f"production_status{suffix}" if suffix else "production_status"
    if status_col in table.columns:
        by_status = table.groupby(status_col).agg(
            slots=("difference", "size"),
            complete=("difference", "count"),
            breaches=("difference_percent", lambda s: (s > TOLERANCE).sum()))
        print("\n  Breaches by production status:")
        print(by_status.to_string())


def main():
    start, end = parse_period("Reconcile Fingrid's real-time energy balance in pandas.")
    sys.stdout = sys.stderr = Tee("output.txt")
    started = time.time()

    raw = fetch_all_datasets(start, end)

    frames = {}
    for ds in DATASETS:
        name, interval = ds["name"], ds["interval"]
        df = raw[name].drop(columns=["datasetId"])

        if interval == 3:
            df = normalise_intervals(df)
            dupes = df[df.duplicated("startTime", keep=False)]
            if not dupes.empty:
                print(f"  WARNING: {len(dupes)} rows involved in overlapping slots in {name}")
                df = df.drop_duplicates("startTime", keep="first")
            print(f"  {name}: {len(df)} records after normalising intervals")
            frames[f"{name}_15min"] = {
                "interval": 15,
                "df": to_15min(df).rename(columns={"value": f"{name}_15min",
                                                   "reading_count": f"{name}_15min_readings"})}

        frames[name] = {
            "interval": interval,
            "df": df.rename(columns={"value": name, "value_status": f"{name}_status"})}

    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    df_3min = reconcile(build_table(frames, 3, t0, t1))
    df_15min = reconcile(build_table(frames, 15, t0, t1), suffix="_15min")

    # A 15-minute average is only comparable across datasets when every dataset
    # has all 5 readings; otherwise the averages cover different moments.
    reading_cols = [f"{n}_15min_readings" for n in ["production", "consumption"] + BORDERS]
    df_15min["min_readings"] = df_15min[reading_cols].fillna(0).min(axis=1).astype(int)
    df_15min["window_complete"] = df_15min["min_readings"] == 5

    print_summary(df_3min, "3-minute data")
    print_summary(df_15min, "15-minute data", suffix="_15min")

    minutes, seconds = divmod(time.time() - started, 60)
    print(f"\nScript completed in {int(minutes)} minutes and {seconds:.2f} seconds.")


if __name__ == "__main__":
    main()
