"""Seed the demo database with realistic e-commerce data.

Supports both SQLite (default) and PostgreSQL via --db-url:

    # SQLite (default)
    uv run python scripts/seed_demo_db.py

    # PostgreSQL
    uv run python scripts/seed_demo_db.py --db-url "postgresql://admin:secret@localhost:5432/ecommerce"
"""

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    insert,
)

# Default: create demo.db in the project root (parent of scripts/)
_DEFAULT_DB_PATH = Path(__file__).parent.parent / "demo.db"
_DEFAULT_DB_URL = f"sqlite:///{_DEFAULT_DB_PATH}"

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(100), nullable=False),
    Column("email", String(150), nullable=False),
    Column("country", String(50), nullable=False),
    Column("created_at", DateTime, nullable=False),
    UniqueConstraint("email", name="uq_users_email"),
)

products = Table(
    "products",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(150), nullable=False),
    Column("category", String(50), nullable=False),
    Column("price", Numeric(10, 2), nullable=False),
    Column("stock_quantity", Integer, nullable=False),
    Column("created_at", DateTime, nullable=False),
)

orders = Table(
    "orders",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("status", String(20), nullable=False),
    Column("total_amount", Numeric(10, 2), nullable=False),
    Column("created_at", DateTime, nullable=False),
)

order_items = Table(
    "order_items",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("order_id", Integer, ForeignKey("orders.id"), nullable=False),
    Column("product_id", Integer, ForeignKey("products.id"), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_price", Numeric(10, 2), nullable=False),
)


def random_date(start: datetime, end: datetime) -> datetime:
    delta = end - start
    return start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))


def seed(db_url: str = _DEFAULT_DB_URL) -> None:
    eng = create_engine(db_url, echo=False)
    random.seed(42)
    metadata.drop_all(eng)
    metadata.create_all(eng)

    countries = ["US", "UK", "India", "Germany", "Canada"]
    first_names = [
        "Alice", "Bob", "Carol", "David", "Emma", "Frank", "Grace", "Henry",
        "Isla", "Jack", "Karen", "Liam", "Mia", "Noah", "Olivia", "Paul",
        "Quinn", "Rachel", "Sam", "Tina", "Uma", "Victor", "Wendy", "Xavier",
        "Yara", "Zoe",
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
        "Davis", "Martinez", "Wilson", "Anderson", "Taylor", "Thomas", "Jackson",
        "White", "Harris", "Martin", "Thompson", "Robinson", "Clark",
    ]

    user_rows = []
    emails_used: set[str] = set()
    for i in range(1, 501):
        fn = random.choice(first_names)
        ln = random.choice(last_names)
        base = f"{fn.lower()}.{ln.lower()}"
        email = f"{base}{i}@example.com"
        while email in emails_used:
            email = f"{base}{i}_{random.randint(1, 999)}@example.com"
        emails_used.add(email)
        user_rows.append({
            "name": f"{fn} {ln}",
            "email": email,
            "country": random.choice(countries),
            "created_at": random_date(datetime(2022, 1, 1), datetime(2024, 12, 31)),
        })

    categories = ["Electronics", "Clothing", "Books", "Home", "Sports"]
    product_names = {
        "Electronics": ["Laptop", "Headphones", "Smartwatch", "Tablet", "Keyboard",
                        "Mouse", "Monitor", "Speaker", "Camera", "Phone"],
        "Clothing":    ["T-Shirt", "Jeans", "Jacket", "Dress", "Shorts",
                        "Hoodie", "Sweater", "Coat", "Socks", "Hat"],
        "Books":       ["Python Crash Course", "Clean Code", "The Pragmatic Programmer",
                        "Design Patterns", "Atomic Habits", "Deep Work", "Dune",
                        "1984", "Sapiens", "The Lean Startup"],
        "Home":        ["Lamp", "Pillow", "Blanket", "Towel Set", "Curtains",
                        "Rug", "Candle", "Picture Frame", "Clock", "Vase"],
        "Sports":      ["Yoga Mat", "Dumbbells", "Resistance Bands", "Jump Rope",
                        "Water Bottle", "Running Shoes", "Gym Bag", "Foam Roller",
                        "Knee Brace", "Bicycle Helmet"],
    }

    product_rows = []
    for i in range(100):
        cat = categories[i % len(categories)]
        name_list = product_names[cat]
        product_rows.append({
            "name": f"{name_list[i % len(name_list)]} {i + 1}",
            "category": cat,
            "price": round(random.uniform(5.0, 999.99), 2),
            "stock_quantity": random.randint(0, 500),
            "created_at": random_date(datetime(2022, 1, 1), datetime(2024, 6, 1)),
        })

    start_date = datetime(2023, 1, 1)
    end_date = datetime(2024, 12, 31)
    statuses = ["pending", "shipped", "delivered", "cancelled"]
    order_rows = []
    for _ in range(2000):
        order_rows.append({
            "user_id": random.randint(1, 500),
            "status": random.choice(statuses),
            "total_amount": round(random.uniform(10.0, 2000.0), 2),
            "created_at": random_date(start_date, end_date),
        })

    order_item_rows = []
    for _ in range(5000):
        order_item_rows.append({
            "order_id": random.randint(1, 2000),
            "product_id": random.randint(1, 100),
            "quantity": random.randint(1, 10),
            "unit_price": round(random.uniform(5.0, 999.99), 2),
        })

    with eng.begin() as conn:
        conn.execute(insert(users), user_rows)
        conn.execute(insert(products), product_rows)
        conn.execute(insert(orders), order_rows)
        conn.execute(insert(order_items), order_item_rows)

    # Summary
    with eng.connect() as conn:
        from sqlalchemy import text
        print(f"\nDatabase seeded at: {db_url}\n")
        print(f"{'Table':<15} {'Rows':>6}")
        print("-" * 23)
        for table_name in ["users", "products", "orders", "order_items"]:
            count = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()
            print(f"{table_name:<15} {count:>6}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed the demo database with e-commerce data."
    )
    parser.add_argument(
        "--db-url",
        default=_DEFAULT_DB_URL,
        help=(
            "SQLAlchemy database URL to seed "
            f"(default: sqlite:///{_DEFAULT_DB_PATH})"
        ),
    )
    args = parser.parse_args()
    seed(args.db_url)
