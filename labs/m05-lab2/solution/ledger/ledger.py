"""Load ledger entries and export them as CSV."""

import csv
import json
from pathlib import Path


def load_entries(path: str | Path) -> list[dict]:
    """Read a JSON list of {"date", "amount"} entries."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def total(entries: list[dict]) -> float:
    """Sum the amounts."""
    return round(sum(e["amount"] for e in entries), 2)


def export_csv(entries: list[dict], out: str | Path) -> None:
    """Write entries to a CSV file with a header row."""
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "amount"])
        writer.writeheader()
        writer.writerows(entries)
