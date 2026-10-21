"""Generate the deterministic sample dataset in data/ (same seed, same files)."""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data"
START, DAYS = date(2026, 6, 3), 120  # ends 2026-09-30

SUPPLIERS = [("SUP-FN", "Frío Norte"), ("SUP-CA", "Clima Andino"), ("SUP-BR", "Brisa Pacífico")]
PRODUCTS = [
    ("MS-12K-INV", "Minisplit 12,000 BTU inverter", "minisplit", "SUP-FN", 7400),
    ("MS-18K-INV", "Minisplit 18,000 BTU inverter", "minisplit", "SUP-FN", 9800),
    ("MS-24K-INV", "Minisplit 24,000 BTU inverter", "minisplit", "SUP-CA", 12900),
    ("MS-12K-STD", "Minisplit 12,000 BTU standard", "minisplit", "SUP-CA", 5600),
    ("PT-10K", "Portable air conditioner 10,000 BTU", "portable", "SUP-BR", 4300),
    ("PT-14K", "Portable air conditioner 14,000 BTU", "portable", "SUP-BR", 5900),
    ("WN-12K", "Window unit 12,000 BTU", "window", "SUP-CA", 4800),
    ("FAN-TWR", "Tower fan", "fan", "SUP-BR", 900),
]
STORES = [
    ("CDMX-POL", "Polanco", "Ciudad de México", "centro"),
    ("GDL-CEN", "Guadalajara Centro", "Guadalajara", "occidente"),
    ("MTY-VAL", "Valle Oriente", "Monterrey", "norte"),
]
HEAT = {"CDMX-POL": 0.6, "GDL-CEN": 0.9, "MTY-VAL": 1.6}
BASE = {"MS-12K-INV": 3.2, "MS-18K-INV": 1.8, "MS-24K-INV": 0.9, "MS-12K-STD": 2.1,
        "PT-10K": 1.5, "PT-14K": 0.8, "WN-12K": 0.7, "FAN-TWR": 4.0}
MARKUP = 1.42


def main() -> None:
    rng = random.Random(20260930)
    OUT.mkdir(exist_ok=True)
    write("suppliers.csv", ["supplier_id", "name"], SUPPLIERS)
    write("products.csv", ["sku", "name", "category", "supplier_id", "unit_cost"], PRODUCTS)
    write("stores.csv", ["store_id", "name", "city", "region"], STORES)

    sales, inventory = [], []
    for store_id, *_ in STORES:
        for sku, _name, _cat, _sup, cost in PRODUCTS:
            on_hand = rng.randint(25, 60)
            price = round(cost * MARKUP, -1)
            for d in range(DAYS):
                day = START + timedelta(days=d)
                season = 1.3 - 0.9 * d / DAYS  # summer peak fading into autumn
                weekend = 1.35 if day.weekday() >= 5 else 1.0
                demand = BASE[sku] * HEAT[store_id] * season * weekend
                units = min(on_hand, max(0, round(rng.gauss(demand, demand * 0.45))))
                on_hand -= units
                if d % 21 == 20 and on_hand < 30:  # replenishment every 3 weeks
                    on_hand += rng.randint(20, 40)
                if units:
                    promo = 0.9 if day.weekday() == 6 else 1.0
                    sales.append((day.isoformat(), store_id, sku, units, round(price * promo, 2)))
                inventory.append((day.isoformat(), store_id, sku, on_hand))
    write("sales.csv", ["date", "store_id", "sku", "units", "unit_price"], sales)
    write("inventory.csv", ["date", "store_id", "sku", "on_hand"], inventory)
    print(f"{len(sales)} sales rows, {len(inventory)} inventory rows")


def write(name: str, header: list[str], rows: list[tuple]) -> None:
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


if __name__ == "__main__":
    main()
