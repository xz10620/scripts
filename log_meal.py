#!/usr/bin/env python3
"""Log meals to a CSV file."""

import csv
import sys
from datetime import datetime
from pathlib import Path

LOG_FILE = Path.home() / "meal_log.csv"


def log_meal(meal: str) -> None:
    now = datetime.now()
    row = [now.strftime("%Y-%m-%d"), now.strftime("%H:%M"), meal]

    write_header = not LOG_FILE.exists()
    with LOG_FILE.open("a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["date", "time", "meal"])
        writer.writerow(row)

    print(f"Logged: {row[0]} {row[1]} — {meal}")
    print(f"Saved to {LOG_FILE}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: log_meal.py <meal description>")
        print('Example: log_meal.py "sandwich and chips"')
        sys.exit(1)

    meal = " ".join(sys.argv[1:])
    log_meal(meal)
