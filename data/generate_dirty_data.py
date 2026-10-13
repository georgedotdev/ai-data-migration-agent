"""
Generate the demo datasets with a known, documented set of data-quality defects.

Every defect is injected on purpose and recorded in data/dirty_data_manifest.json,
so the demo can show exactly what was wrong in the legacy source and prove the
pipeline fixed (or quarantined) it.

Usage:
    python data/generate_dirty_data.py
"""

import csv
import json
import os
import random
from datetime import date, timedelta

SEED = 42
DATA_DIR = os.path.dirname(os.path.abspath(__file__))

FIRST = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "David",
         "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah",
         "Priya", "Arjun", "Ananya", "Rahul", "Sneha", "Vikram", "Meera", "Rohan", "Fatima", "Omar",
         "Wei", "Mei", "Hiroshi", "Yuki", "Carlos", "Sofia", "Luca", "Emma", "Noah", "Olivia"]
LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Martinez",
        "Wilson", "Anderson", "Taylor", "Thomas", "Moore", "Jackson", "Martin", "Lee", "Thompson",
        "Sharma", "Patel", "Iyer", "Nair", "Reddy", "Khan", "Chen", "Wang", "Tanaka", "Rossi", "Silva"]


class Manifest:
    def __init__(self):
        self.defects = {}

    def add(self, kind, row_key, detail):
        self.defects.setdefault(kind, []).append({"row": row_key, "detail": detail})

    def summary(self):
        return {k: {"count": len(v), "examples": v[:3]} for k, v in sorted(self.defects.items())}


def _fmt_date(rng, d, manifest, key):
    """Render a date in one of several legacy formats."""
    style = rng.random()
    if style < 0.45:
        return d.isoformat()
    if style < 0.70:
        manifest.add("mixed_date_format", key, f"{d.month}/{d.day}/{d.year}")
        return f"{d.month}/{d.day}/{d.year}"
    if style < 0.85:
        manifest.add("mixed_date_format", key, d.strftime("%Y/%m/%d"))
        return d.strftime("%Y/%m/%d")
    manifest.add("mixed_date_format", key, d.strftime("%b %d %Y"))
    return d.strftime("%b %d %Y")


def _pad(rng, s, manifest, key, field):
    if rng.random() < 0.12:
        manifest.add("whitespace_padding", key, field)
        return f"  {s} " if rng.random() < 0.5 else f"{s}   "
    return s


def generate_employees(rng):
    m = Manifest()
    departments = {
        "Engineering": ["engineering", "ENGINEERING", "Enginering", "Engineering "],
        "Sales": ["sales", "SALES", "Saless"],
        "Marketing": ["marketing", "Markting", "MARKETING "],
        "Finance": ["finance", "Finanse"],
        "Human Resources": ["human resources", "Human Resource", "HUMAN RESOURCES"],
    }
    regions = ["North", "South", "East", "West"]
    roles = {"Engineering": ["Developer", "DevOps Engineer", "QA Engineer"], "Sales": ["Account Executive"],
             "Marketing": ["Marketing Analyst"], "Finance": ["Accountant", "Financial Analyst"],
             "Human Resources": ["HR Generalist", "Recruiter"]}

    header = [" Employee ID ", "Full Name", "Email Address", "Phone", "Age", "Department",
              "Region", " Annual Salary ", "Join Date", "Is Remote", "Performance Rating", "Status"]
    rows = []
    for i in range(1, 181):
        emp_id = 1000 + i
        key = f"emp {emp_id}"
        first, last = rng.choice(FIRST), rng.choice(LAST)
        dept = rng.choice(list(departments))
        salary = rng.randrange(38, 180) * 1000
        age = rng.randint(21, 63)
        joined = date(2014, 1, 1) + timedelta(days=rng.randint(0, 3900))
        email = f"{first}.{last}{emp_id % 97}@acme-corp.com".lower()
        phone = f"9{rng.randint(100000000, 999999999)}"

        row = {
            "id": str(emp_id),
            "name": _pad(rng, f"{first} {last}", m, key, "Full Name"),
            "email": email,
            "phone": phone,
            "age": str(age),
            "dept": dept,
            "region": rng.choice(regions),
            "salary": f"{salary}",
            "joined": _fmt_date(rng, joined, m, key),
            "remote": rng.choice(["Yes", "No"]),
            "rating": f"{rng.choice([2.5, 3.0, 3.5, 3.8, 4.0, 4.2, 4.5, 5.0])}",
            "status": rng.choice(["Active"] * 6 + ["On Leave", "Terminated"]),
        }

        r = rng.random
        if r() < 0.22:
            row["dept"] = rng.choice(departments[dept])
            m.add("inconsistent_category", key, f"Department '{row['dept']}' (canonical '{dept}')")
        if r() < 0.35:
            row["salary"] = rng.choice([f"${salary:,}", f"{salary:,}", f"USD {salary:,}", f"{salary // 1000}k"])
            m.add("currency_formatting", key, row["salary"])
        if r() < 0.04:
            row["salary"] = rng.choice(["N/A", "TBD", ""])
            m.add("missing_or_sentinel_salary", key, row["salary"] or "<blank>")
        if r() < 0.03:
            row["salary"] = f"-{salary}"
            m.add("negative_salary", key, row["salary"])
        if r() < 0.06:
            row["age"] = rng.choice(["-4", "999", "thirty", "", "0"])
            m.add("invalid_age", key, row["age"] or "<blank>")
        if r() < 0.08:
            row["email"] = rng.choice([f"{first}.{last}@", f"{first} at acme-corp.com", "n/a", ""]).lower()
            m.add("invalid_email", key, row["email"] or "<blank>")
        if r() < 0.25:
            p = row["phone"]
            row["phone"] = rng.choice([f"+91 {p[:5]} {p[5:]}", f"({p[:3]}) {p[3:6]}-{p[6:]}", f"{p[:3]}.{p[3:6]}.{p[6:]}"])
            m.add("phone_formatting", key, row["phone"])
        if r() < 0.3:
            row["remote"] = rng.choice(["Y", "N", "TRUE", "false", "1", "0", "yes", "NO"])
            m.add("inconsistent_boolean", key, row["remote"])
        if r() < 0.06:
            row["rating"] = rng.choice(["", "4.5/5", "9", "N/A"])
            m.add("invalid_rating", key, row["rating"] or "<blank>")
        if r() < 0.08:
            row["status"] = rng.choice(["UNKNOWN", "N/A", "-", "null", "?", "active", "ACTIVE "])
            m.add("status_sentinel_or_case", key, row["status"])
        if r() < 0.02:
            row["joined"] = rng.choice(["00/00/0000", "2031-02-30", "not recorded"])
            m.add("invalid_date", key, row["joined"])
        rows.append(row)

    # Rows that cannot be migrated: no primary key
    for idx in rng.sample(range(len(rows)), 3):
        m.add("missing_primary_key", rows[idx]["name"].strip(), "Employee ID blank")
        rows[idx]["id"] = ""
    # Exact duplicate rows (double-loaded batch)
    for idx in rng.sample(range(len(rows)), 6):
        rows.append(dict(rows[idx]))
        m.add("exact_duplicate_row", f"emp {rows[idx]['id']}", "row appears twice")
    # Same key, different content (re-entered record)
    for idx in rng.sample(range(len(rows) - 6), 4):
        if not rows[idx]["id"]:
            continue
        dup = dict(rows[idx])
        dup["phone"] = f"9{rng.randint(100000000, 999999999)}"
        rows.append(dup)
        m.add("duplicate_primary_key", f"emp {dup['id']}", "same Employee ID, different phone")

    rng.shuffle(rows)
    order = ["id", "name", "email", "phone", "age", "dept", "region", "salary", "joined", "remote", "rating", "status"]
    return header, [[r[k] for k in order] for r in rows], m


def generate_orders(rng):
    m = Manifest()
    catalog = {
        "Electronics": [("Smartphone", 499.0), ("Laptop", 1099.0), ("Headphones", 89.99), ("Smartwatch", 199.0)],
        "Home": [("Blender", 49.5), ("Air Fryer", 129.0), ("Desk Lamp", 24.99)],
        "Books": [("Science Fiction", 14.99), ("Biography", 19.5), ("Cookbook", 29.0)],
        "Sports": [("Tennis Racket", 119.0), ("Basketball", 29.99), ("Yoga Mat", 34.0)],
    }
    cat_variants = {"Electronics": ["electronics", "ELECTRONICS", "Electronic"], "Home": ["home", "HOME "],
                    "Books": ["books", "Book"], "Sports": ["sports", "Sport", "SPORTS"]}
    payment_variants = {"Credit Card": ["credit card", "CREDIT CARD", "Credit  Card"], "PayPal": ["paypal", "Pay Pal", "PAYPAL"],
                        "UPI": ["upi", "Upi"], "Cash on Delivery": ["cash on delivery", "COD "]}
    statuses = ["Delivered"] * 5 + ["Shipped"] * 3 + ["Processing", "Cancelled", "Returned"]

    header = ["Order ID", " Customer Name", "Customer Email", "Order Date", "Product", "Category ",
              "Quantity", "Unit Price", "Discount", "Payment Method", "Order Status", "Total Amount"]
    rows = []
    for i in range(1, 241):
        oid = f"ORD-{50000 + i}"
        key = oid
        first, last = rng.choice(FIRST), rng.choice(LAST)
        cat = rng.choice(list(catalog))
        product, price = rng.choice(catalog[cat])
        qty = rng.randint(1, 5)
        disc = rng.choice([0, 0, 0, 5, 10, 15])
        total = round(qty * price * (1 - disc / 100), 2)
        d = date(2025, 1, 1) + timedelta(days=rng.randint(0, 270))
        pay = rng.choice(list(payment_variants))
        row = {
            "id": oid, "name": _pad(rng, f"{first} {last}", m, key, "Customer Name"),
            "email": f"{first}.{last}@mail.com".lower(), "date": _fmt_date(rng, d, m, key),
            "product": product, "cat": cat, "qty": str(qty), "price": f"{price:.2f}",
            "disc": f"{disc}%", "pay": pay, "status": rng.choice(statuses), "total": f"{total:.2f}",
        }
        r = rng.random
        if r() < 0.2:
            row["cat"] = rng.choice(cat_variants[cat])
            m.add("inconsistent_category", key, f"Category '{row['cat']}' (canonical '{cat}')")
        if r() < 0.2:
            row["pay"] = rng.choice(payment_variants[pay])
            m.add("inconsistent_category", key, f"Payment '{row['pay']}' (canonical '{pay}')")
        if r() < 0.3:
            row["price"] = rng.choice([f"${price:,.2f}", f"Rs. {price:,.2f}", f"{price:,.2f} USD"])
            m.add("currency_formatting", key, row["price"])
        if r() < 0.04:
            row["price"] = rng.choice(["abc", "four hundred", "", "N/A"])
            m.add("unparseable_price", key, row["price"] or "<blank>")
        if r() < 0.05:
            row["qty"] = rng.choice(["", "-2", "0", "two"])
            m.add("invalid_quantity", key, row["qty"] or "<blank>")
        if r() < 0.15:
            row["disc"] = rng.choice([f"{disc / 100:.2f}", f"{disc} %", ""])
            m.add("percentage_formatting", key, row["disc"] or "<blank>")
        if r() < 0.06:
            row["email"] = rng.choice([f"{first}@", "unknown", "", f"{first}.{last}mail.com"]).lower()
            m.add("invalid_email", key, row["email"] or "<blank>")
        if r() < 0.06:
            row["status"] = rng.choice(["UNKNOWN", "N/A", "pending?", "delivered", "SHIPPED"])
            m.add("status_sentinel_or_case", key, row["status"])
        if r() < 0.04:
            row["total"] = ""
            m.add("missing_total", key, "<blank>")
        rows.append(row)

    for idx in rng.sample(range(len(rows)), 2):
        m.add("missing_primary_key", rows[idx]["name"].strip(), "Order ID blank")
        rows[idx]["id"] = ""
    for idx in rng.sample(range(len(rows)), 5):
        rows.append(dict(rows[idx]))
        m.add("exact_duplicate_row", rows[idx]["id"] or "<no id>", "row appears twice")
    for idx in rng.sample(range(len(rows) - 5), 3):
        if not rows[idx]["id"]:
            continue
        dup = dict(rows[idx])
        dup["status"] = "Returned"
        rows.append(dup)
        m.add("duplicate_primary_key", dup["id"], "same Order ID, different status")

    rng.shuffle(rows)
    order = ["id", "name", "email", "date", "product", "cat", "qty", "price", "disc", "pay", "status", "total"]
    return header, [[r[k] for k in order] for r in rows], m


def _write(name, header, rows):
    path = os.path.join(DATA_DIR, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


def main():
    rng = random.Random(SEED)
    manifest = {"seed": SEED, "datasets": {}}
    for table, fname, gen in [("dirty_employees", "dirty_employees.csv", generate_employees),
                              ("dirty_orders", "dirty_orders.csv", generate_orders)]:
        header, rows, m = gen(rng)
        _write(fname, header, rows)
        manifest["datasets"][table] = {"file": fname, "rows": len(rows), "defects": m.summary()}
        print(f"Wrote {fname}: {len(rows)} rows, {sum(len(v) for v in m.defects.values())} injected defects")
    with open(os.path.join(DATA_DIR, "dirty_data_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


if __name__ == "__main__":
    main()
