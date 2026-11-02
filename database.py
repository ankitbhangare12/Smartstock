from __future__ import annotations

import math
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


DATABASE_PATH = Path(__file__).with_name("smartstock.db")
TRANSACTION_TYPES = ("Purchase", "Sale", "Usage", "Return", "Damaged")
INBOUND_TYPES = {"Purchase", "Return"}


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                contact_person TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sku TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
                unit_cost REAL NOT NULL DEFAULT 0 CHECK (unit_cost >= 0),
                unit_price REAL NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
                safety_stock INTEGER NOT NULL DEFAULT 0 CHECK (safety_stock >= 0),
                lead_time_days INTEGER NOT NULL DEFAULT 7 CHECK (lead_time_days >= 0),
                supplier_id INTEGER REFERENCES suppliers(id) ON DELETE RESTRICT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
                transaction_type TEXT NOT NULL CHECK (
                    transaction_type IN ('Purchase', 'Sale', 'Usage', 'Return', 'Damaged')
                ),
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                unit_price REAL NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_transactions_product_date
                ON transactions(product_id, created_at);
            """
        )
        has_products = connection.execute("SELECT 1 FROM products LIMIT 1").fetchone()
        if not has_products:
            _seed_sample_data(connection)


def _seed_sample_data(connection: sqlite3.Connection) -> None:
    suppliers = [
        ("Northstar Office Supply", "Maya Chen", "orders@northstar.example", "+1 555 0142", "18 Market Street"),
        ("Clearline Electronics", "Jordan Lee", "sales@clearline.example", "+1 555 0186", "240 Industrial Avenue"),
        ("Greenfield Packaging", "Avery Patel", "hello@greenfield.example", "+1 555 0128", "6 Warehouse Road"),
        ("Summit Workspace", "Riley Morgan", "team@summit.example", "+1 555 0194", "92 Commerce Drive"),
    ]
    connection.executemany(
        "INSERT INTO suppliers (name, contact_person, email, phone, address) VALUES (?, ?, ?, ?, ?)",
        suppliers,
    )
    supplier_ids = {
        row["name"]: row["id"]
        for row in connection.execute("SELECT id, name FROM suppliers").fetchall()
    }

    products = [
        ("A4 Copy Paper", "PAP-1001", "Office Supplies", 42, 4.20, 7.50, 15, 5, "Northstar Office Supply"),
        ("Permanent Markers", "PEN-2044", "Office Supplies", 12, 1.10, 2.40, 10, 8, "Northstar Office Supply"),
        ("Wireless Mouse", "ELC-3102", "Electronics", 76, 11.50, 19.99, 20, 10, "Clearline Electronics"),
        ("USB-C Hub", "ELC-3180", "Electronics", 8, 18.00, 32.00, 12, 12, "Clearline Electronics"),
        ("Shipping Boxes", "PKG-4110", "Packaging", 31, 0.85, 1.65, 8, 6, "Greenfield Packaging"),
        ("Desk Organizer", "DSK-5025", "Workspace", 20, 6.40, 12.00, 10, 7, "Summit Workspace"),
    ]
    starting_quantities = (40, 15, 81, 7, 31, 16)
    connection.executemany(
        """
        INSERT INTO products
            (name, sku, category, quantity, unit_cost, unit_price, safety_stock, lead_time_days, supplier_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                name, sku, category, opening, cost, price, safety, lead, supplier_ids[supplier]
            )
            for (name, sku, category, _final, cost, price, safety, lead, supplier), opening
            in zip(products, starting_quantities)
        ],
    )
    product_ids = {
        row["sku"]: row["id"]
        for row in connection.execute("SELECT id, sku FROM products").fetchall()
    }

    sales = {
        "PAP-1001": (5, 6, 7),
        "PEN-2044": (3, 4, 6),
        "ELC-3102": (8, 10, 12),
        "ELC-3180": (2, 3, 4),
        "PKG-4110": (3, 4, 5),
        "DSK-5025": (1, 2, 3),
    }
    purchases = {
        "PAP-1001": 20,
        "PEN-2044": 10,
        "ELC-3102": 25,
        "ELC-3180": 10,
        "PKG-4110": 12,
        "DSK-5025": 10,
    }
    today = date.today()
    for sku, quantities in sales.items():
        product_id = product_ids[sku]
        price = next(item[5] for item in products if item[1] == sku)
        for offset, quantity in zip((25, 16, 5), quantities):
            connection.execute(
                """
                INSERT INTO transactions (product_id, transaction_type, quantity, unit_price, notes, created_at)
                VALUES (?, 'Sale', ?, ?, 'Sample customer order', ?)
                """,
                (product_id, quantity, price, datetime.combine(today - timedelta(days=offset), datetime.min.time()).isoformat(timespec="seconds")),
            )
        purchase_quantity = purchases[sku]
        connection.execute(
            """
            INSERT INTO transactions (product_id, transaction_type, quantity, unit_price, notes, created_at)
            VALUES (?, 'Purchase', ?, ?, 'Sample replenishment', ?)
            """,
            (
                product_id,
                purchase_quantity,
                next(item[4] for item in products if item[1] == sku),
                datetime.combine(today - timedelta(days=11), datetime.min.time()).isoformat(timespec="seconds"),
            ),
        )
    # Store the demonstration stock levels after applying the seeded movements.
    for product, final_quantity in zip(products, (42, 12, 76, 8, 31, 20)):
        connection.execute(
            "UPDATE products SET quantity = ? WHERE sku = ?",
            (final_quantity, product[1]),
        )


def read_frame(query: str, parameters: tuple[Any, ...] = ()) -> pd.DataFrame:
    with get_connection() as connection:
        return pd.read_sql_query(query, connection, params=parameters)


def get_products() -> pd.DataFrame:
    return read_frame(
        """
        SELECT p.*, s.name AS supplier_name
        FROM products p
        LEFT JOIN suppliers s ON s.id = p.supplier_id
        ORDER BY p.name COLLATE NOCASE
        """
    )


def get_suppliers() -> pd.DataFrame:
    return read_frame(
        """
        SELECT s.*, COUNT(p.id) AS product_count
        FROM suppliers s
        LEFT JOIN products p ON p.supplier_id = s.id
        GROUP BY s.id
        ORDER BY s.name COLLATE NOCASE
        """
    )


def get_transactions(limit: int | None = None) -> pd.DataFrame:
    query = """
        SELECT t.id, t.product_id, p.name AS product_name, p.sku, t.transaction_type,
               t.quantity, t.unit_price, t.notes, t.created_at
        FROM transactions t
        JOIN products p ON p.id = t.product_id
        ORDER BY t.created_at DESC, t.id DESC
    """
    if limit is not None:
        query += " LIMIT ?"
        return read_frame(query, (limit,))
    return read_frame(query)


def record_transaction(
    product_id: int,
    transaction_type: str,
    quantity: int,
    unit_price: float,
    notes: str = "",
    transaction_date: date | None = None,
) -> None:
    if transaction_type not in TRANSACTION_TYPES:
        raise ValueError("Choose a valid transaction type.")
    if isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or not math.isfinite(quantity) or int(quantity) != quantity or quantity <= 0:
        raise ValueError("Quantity must be a positive whole number.")
    if not math.isfinite(unit_price) or unit_price < 0:
        raise ValueError("Unit price cannot be negative.")
    timestamp = datetime.combine(transaction_date or date.today(), datetime.now().time()).isoformat(timespec="seconds")
    with get_connection() as connection:
        if transaction_type in INBOUND_TYPES:
            cursor = connection.execute(
                "UPDATE products SET quantity = quantity + ? WHERE id = ?",
                (quantity, product_id),
            )
        else:
            cursor = connection.execute(
                "UPDATE products SET quantity = quantity - ? WHERE id = ? AND quantity >= ?",
                (quantity, product_id, quantity),
            )
        if cursor.rowcount == 0:
            exists = connection.execute("SELECT 1 FROM products WHERE id = ?", (product_id,)).fetchone()
            if not exists:
                raise ValueError("The selected product no longer exists.")
            raise ValueError("This transaction would reduce available stock below zero.")
        connection.execute(
            """
            INSERT INTO transactions (product_id, transaction_type, quantity, unit_price, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (product_id, transaction_type, quantity, unit_price, notes.strip(), timestamp),
        )


def save_product(values: dict[str, Any], product_id: int | None = None) -> None:
    _validate_product(values)
    fields = (
        values["name"].strip(),
        values["sku"].strip().upper(),
        values["category"].strip(),
        int(values["quantity"]),
        float(values["unit_cost"]),
        float(values["unit_price"]),
        int(values["safety_stock"]),
        int(values["lead_time_days"]),
        values["supplier_id"],
    )
    with get_connection() as connection:
        if product_id is None:
            connection.execute(
                """
                INSERT INTO products
                    (name, sku, category, quantity, unit_cost, unit_price, safety_stock, lead_time_days, supplier_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                fields,
            )
        else:
            connection.execute(
                """
                UPDATE products
                SET name = ?, sku = ?, category = ?, quantity = ?, unit_cost = ?, unit_price = ?,
                    safety_stock = ?, lead_time_days = ?, supplier_id = ?
                WHERE id = ?
                """,
                (*fields, product_id),
            )


def _validate_product(values: dict[str, Any]) -> None:
    for field in ("name", "sku", "category"):
        if not str(values.get(field, "")).strip():
            raise ValueError(f"{field.replace('_', ' ').capitalize()} is required.")
    for field in ("quantity", "safety_stock", "lead_time_days"):
        value = values.get(field)
        try:
            valid = (
                not isinstance(value, bool)
                and math.isfinite(value)
                and int(value) == value
                and int(value) >= 0
            )
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            raise ValueError(f"{field.replace('_', ' ').capitalize()} must be a non-negative whole number.")
    for field in ("unit_cost", "unit_price"):
        try:
            valid = math.isfinite(float(values.get(field, 0))) and float(values.get(field, 0)) >= 0
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            raise ValueError(f"{field.replace('_', ' ').capitalize()} cannot be negative.")


def delete_product(product_id: int) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM products WHERE id = ?", (product_id,))


def save_supplier(values: dict[str, str], supplier_id: int | None = None) -> None:
    if not values.get("name", "").strip():
        raise ValueError("Supplier name is required.")
    email = values.get("email", "").strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid supplier email address.")
    fields = tuple(values.get(key, "").strip() for key in ("name", "contact_person", "email", "phone", "address"))
    with get_connection() as connection:
        if supplier_id is None:
            connection.execute(
                "INSERT INTO suppliers (name, contact_person, email, phone, address) VALUES (?, ?, ?, ?, ?)",
                fields,
            )
        else:
            connection.execute(
                """
                UPDATE suppliers SET name = ?, contact_person = ?, email = ?, phone = ?, address = ?
                WHERE id = ?
                """,
                (*fields, supplier_id),
            )


def delete_supplier(supplier_id: int) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
