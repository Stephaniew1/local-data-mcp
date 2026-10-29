"""Create a deterministic sample store database to serve."""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE customers (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    email   TEXT NOT NULL UNIQUE,
    city    TEXT NOT NULL,
    joined  TEXT NOT NULL            -- ISO date
);

CREATE TABLE products (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    category  TEXT NOT NULL,
    price     REAL NOT NULL,
    stock     INTEGER NOT NULL
);

CREATE TABLE orders (
    id           INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    order_date   TEXT NOT NULL,       -- ISO date
    status       TEXT NOT NULL CHECK (status IN ('pending', 'shipped', 'delivered', 'cancelled'))
);

CREATE TABLE order_items (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id),
    product_id  INTEGER NOT NULL REFERENCES products(id),
    quantity    INTEGER NOT NULL,
    unit_price  REAL NOT NULL
);

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_items_order ON order_items(order_id);
"""

PRODUCTS = [
    ("Mechanical Keyboard", "Electronics", 89.99),
    ("Wireless Mouse", "Electronics", 29.99),
    ("USB-C Hub", "Electronics", 45.00),
    ("27in Monitor", "Electronics", 279.00),
    ("Noise-Cancelling Headphones", "Electronics", 199.00),
    ("Standing Desk", "Furniture", 499.00),
    ("Ergonomic Chair", "Furniture", 349.00),
    ("Desk Lamp", "Furniture", 39.50),
    ("Bookshelf", "Furniture", 129.00),
    ("Notebook (A5)", "Stationery", 7.99),
    ("Fountain Pen", "Stationery", 34.00),
    ("Sticky Notes 12-pack", "Stationery", 11.49),
    ("Pour-Over Coffee Set", "Kitchen", 54.00),
    ("Insulated Mug", "Kitchen", 24.95),
    ("Electric Kettle", "Kitchen", 69.00),
]

FIRST = ["Amina", "Brian", "Chen", "Diego", "Esther", "Farah", "George", "Hana", "Ivan", "Joy",
         "Kofi", "Lena", "Mateo", "Nia", "Omar", "Priya", "Quinn", "Rosa", "Sam", "Tariq"]
LAST = ["Otieno", "Smith", "Wang", "Garcia", "Mwangi", "Khan", "Brown", "Sato", "Petrov", "Njeri"]
CITIES = ["Nairobi", "Mombasa", "Kisumu", "London", "Berlin", "Toronto", "Lagos", "Tokyo"]
STATUSES = ["delivered"] * 6 + ["shipped"] * 2 + ["pending", "cancelled"]


def seed(path: str | Path, *, customers: int = 40, orders: int = 300, overwrite: bool = False) -> Path:
    path = Path(path).expanduser().resolve()
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"{path} already exists (pass overwrite=True / --force to replace it)")
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)

    rng = random.Random(42)
    start = date(2025, 1, 1)

    conn = sqlite3.connect(path)
    with conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO products (name, category, price, stock) VALUES (?, ?, ?, ?)",
            [(n, c, p, rng.choice([0, 3, 12, 25, 60, 150])) for n, c, p in PRODUCTS],
        )
        for i in range(1, customers + 1):
            first, last = rng.choice(FIRST), rng.choice(LAST)
            conn.execute(
                "INSERT INTO customers (name, email, city, joined) VALUES (?, ?, ?, ?)",
                (
                    f"{first} {last}",
                    f"{first.lower()}.{last.lower()}{i}@example.com",
                    rng.choice(CITIES),
                    (start + timedelta(days=rng.randint(0, 200))).isoformat(),
                ),
            )
        for _ in range(orders):
            cur = conn.execute(
                "INSERT INTO orders (customer_id, order_date, status) VALUES (?, ?, ?)",
                (
                    rng.randint(1, customers),
                    (start + timedelta(days=rng.randint(0, 600))).isoformat(),
                    rng.choice(STATUSES),
                ),
            )
            for product_id in rng.sample(range(1, len(PRODUCTS) + 1), rng.randint(1, 4)):
                conn.execute(
                    "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
                    (cur.lastrowid, product_id, rng.randint(1, 3), PRODUCTS[product_id - 1][2]),
                )
    conn.close()
    return path
