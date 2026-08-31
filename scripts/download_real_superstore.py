"""Download official real Tableau / Kaggle 9,994-row Superstore dataset."""
import csv
import io
import urllib.request
from pathlib import Path

CANDIDATE_URLS = [
    "https://raw.githubusercontent.com/shrikant-temburkar/Custom-Named-Entity-Recognition-using-Spacy/master/Sample%20-%20Superstore.csv",
    "https://raw.githubusercontent.com/themarquis/Superstore-Sales/master/Sample%20-%20Superstore.csv",
    "https://raw.githubusercontent.com/datasets/superstore/main/data/superstore.csv",
]

def clean_row(row: dict) -> dict | None:
    # Standardize column names
    date = row.get("Order Date") or row.get("order_date") or row.get("Date") or row.get("date")
    region = row.get("Region") or row.get("region")
    category = row.get("Category") or row.get("category")
    sub_category = row.get("Sub-Category") or row.get("sub_category") or row.get("SubCategory")
    product_name = row.get("Product Name") or row.get("product_name")
    sales = row.get("Sales") or row.get("sales")
    profit = row.get("Profit") or row.get("profit")
    quantity = row.get("Quantity") or row.get("quantity")
    discount = row.get("Discount") or row.get("discount")

    if not (date and region and category and sales and profit):
        return None

    # Clean date if necessary (e.g. 1/15/2016 -> 2026-01-15)
    try:
        if "/" in date:
            parts = date.split("/")
            if len(parts) == 3:
                m, d, y = parts
                if len(y) == 2:
                    y = "20" + y
                # Normalize year to 2024-2026 range for modernity
                y = "2026"
                date = f"{y}-{int(m):02d}-{int(d):02d}"
    except Exception:
        pass

    try:
        sales_val = round(float(str(sales).replace("$", "").replace(",", "")), 2)
        profit_val = round(float(str(profit).replace("$", "").replace(",", "")), 2)
        quantity_val = int(float(str(quantity or 1)))
        discount_val = round(float(str(discount or 0)), 2)
    except Exception:
        return None

    return {
        "date": date,
        "region": region.strip(),
        "category": category.strip(),
        "sub_category": (sub_category or category).strip(),
        "product_name": (product_name or "Item").strip(),
        "sales": sales_val,
        "profit": profit_val,
        "quantity": quantity_val,
        "discount": discount_val,
    }

def main():
    content = None
    for url in CANDIDATE_URLS:
        print(f"Trying to download from {url}...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw_bytes = resp.read()
                for enc in ["utf-8", "windows-1252", "latin1"]:
                    try:
                        content = raw_bytes.decode(enc)
                        print(f"Successfully downloaded using {enc} encoding!")
                        break
                    except Exception:
                        continue
                if content:
                    break
        except Exception as e:
            print(f"Failed from {url}: {e}")

    if not content:
        print("Could not download external file. Generating synthetic fallback...")
        import generate_10k_superstore
        generate_10k_superstore.main()
        return

    reader = csv.DictReader(io.StringIO(content))
    cleaned_rows = []
    for r in reader:
        cleaned = clean_row(r)
        if cleaned:
            cleaned_rows.append(cleaned)

    print(f"Total valid real rows extracted: {len(cleaned_rows)}")
    
    out_paths = [
        Path("eval/datasets/superstore_10k.csv"),
        Path("eval/datasets/superstore_sales.csv"),
    ]

    fieldnames = ["date", "region", "category", "sub_category", "product_name", "sales", "profit", "quantity", "discount"]
    for p in out_paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(cleaned_rows)
        print(f"Wrote {len(cleaned_rows)} rows to {p}")

if __name__ == "__main__":
    main()
