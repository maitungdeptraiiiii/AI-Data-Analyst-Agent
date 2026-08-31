"""Generate a realistic 10,000-row Superstore Sales dataset."""
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

REGIONS = ["Central", "East", "North", "South", "West"]

CATEGORY_MAP = {
    "Technology": {
        "Phones": ["iPhone 15", "Samsung Galaxy S24", "Google Pixel 8", "OnePlus 12"],
        "Laptops": ["MacBook Pro 16", "Dell XPS 15", "ThinkPad X1 Carbon", "HP Spectre x360"],
        "Accessories": ["Wireless Mouse", "Mechanical Keyboard", "USB-C Hub", "Noise Cancelling Headphones"],
        "Machines": ["Laser Jet Printer", "3D Printer", "Document Scanner"],
        "Copiers": ["Canon High-Yield Copier", "Brother Multifunction Copier"]
    },
    "Office Supplies": {
        "Binders": ["Heavy Duty Binder", "Clear View Binder", "Ring Binder Deluxe"],
        "Storage": ["Filing Cabinet", "Plastic Storage Box", "Desktop Organizer"],
        "Paper": ["Premium Laser Paper", "Recycled Copy Paper", "Glossy Photo Paper"],
        "Appliances": ["Compact Refrigerator", "Coffee Maker", "Microwave Oven", "Water Dispenser"],
        "Art": ["Colored Pencils Set", "Acrylic Paint Kit", "Drawing Markers"],
        "Labels": ["Shipping Labels", "Address Labels", "Barcode Stickers"],
        "Envelopes": ["Kraft Envelopes", "Security Tint Envelopes", "Padded Mailers"]
    },
    "Furniture": {
        "Chairs": ["Executive Ergonomic Chair", "Mesh Task Chair", "Guest Lobby Chair", "Folding Chair"],
        "Tables": ["Conference Table", "Executive Wooden Desk", "Standing Desk", "Coffee Table"],
        "Bookcases": ["Oak 5-Tier Bookcase", "Metal Industrial Bookshelf", "Corner Display Shelf"],
        "Furnishings": ["LED Desk Lamp", "Floor Mat", "Wall Clock", "Framed Whiteboard"]
    }
}

# Base pricing and target profit margin distribution per sub_category
SUB_CAT_PROFILES = {
    "Phones": (300, 1200, 0.15, 0.35),
    "Laptops": (600, 2500, 0.12, 0.30),
    "Accessories": (20, 150, 0.25, 0.50),
    "Machines": (400, 3000, 0.05, 0.25),
    "Copiers": (800, 5000, 0.20, 0.45),
    "Binders": (5, 40, 0.30, 0.60),
    "Storage": (30, 300, 0.15, 0.40),
    "Paper": (10, 80, 0.20, 0.45),
    "Appliances": (100, 800, 0.10, 0.30),
    "Art": (8, 60, 0.25, 0.50),
    "Labels": (5, 30, 0.35, 0.65),
    "Envelopes": (5, 25, 0.30, 0.55),
    "Chairs": (100, 600, 0.08, 0.25),
    "Tables": (200, 1500, -0.15, 0.18),  # Tables occasionally suffer losses
    "Bookcases": (80, 500, 0.05, 0.22),
    "Furnishings": (15, 120, 0.20, 0.45),
}

def generate_row(start_date: datetime, end_date: datetime) -> dict:
    # Random date
    delta_days = (end_date - start_date).days
    order_date = start_date + timedelta(days=random.randint(0, delta_days))
    date_str = order_date.strftime("%Y-%m-%d")

    region = random.choice(REGIONS)
    category = random.choice(list(CATEGORY_MAP.keys()))
    sub_category = random.choice(list(CATEGORY_MAP[category].keys()))
    product_name = random.choice(CATEGORY_MAP[category][sub_category])

    min_price, max_price, min_margin, max_margin = SUB_CAT_PROFILES[sub_category]
    quantity = random.randint(1, 8)
    unit_price = round(random.uniform(min_price, max_price), 2)
    sales = round(unit_price * quantity, 2)
    
    # Discount
    discount = random.choices([0.0, 0.1, 0.15, 0.2, 0.3, 0.4], weights=[0.5, 0.2, 0.1, 0.1, 0.05, 0.05])[0]
    
    # Base profit calculation
    base_margin = random.uniform(min_margin, max_margin)
    # High discount hurts profit margin
    effective_margin = base_margin - (discount * 1.2)
    
    # Regional nuance: Central has slightly lower tech margin, West has higher overall margin
    if region == "Central" and category == "Technology" and discount >= 0.2:
        effective_margin -= 0.15
    elif region == "West":
        effective_margin += 0.04
        
    profit = round(sales * (1 - discount) * effective_margin, 2)
    final_sales = round(sales * (1 - discount), 2)

    return {
        "date": date_str,
        "region": region,
        "category": category,
        "sub_category": sub_category,
        "product_name": product_name,
        "sales": final_sales,
        "profit": profit,
        "quantity": quantity,
        "discount": discount,
    }

def main():
    random.seed(42)
    target_rows = 10000
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2026, 8, 30)

    out_paths = [
        Path("eval/datasets/superstore_10k.csv"),
        Path("eval/datasets/superstore_sales.csv"),  # Also update standard superstore dataset
    ]

    rows = [generate_row(start_date, end_date) for _ in range(target_rows)]

    fieldnames = ["date", "region", "category", "sub_category", "product_name", "sales", "profit", "quantity", "discount"]

    for p in out_paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {len(rows)} rows to {p}")

if __name__ == "__main__":
    main()
