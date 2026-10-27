#!/usr/bin/env python3
"""
Validate a plan.json against the real price snapshot. Exit 1 with a list of problems if anything is off.

    python3 -I scripts/validate.py plan.json data/

Checks, per shopping item:
  - the store exists in the plan's "stores" and in data/stores.csv
  - the product name matches a real row of that store in prices.csv.gz (exact, case/whitespace-insensitive)
  - unit_price equals that row's price (or its special_price when "promo" is true), tolerance 0.01
  - "promo" is allowed only when the row has a special_price lower than price
  - packs is an integer >= 1 and total == packs * unit_price (tolerance 0.02)
  - no frozen potato products
Plus: every day references existing recipes, every recipe is used, week dates are 7 consecutive days.
"""
import csv, gzip, json, re, sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

FROZEN_POTATO = re.compile(r"(wedges|pomfrit|pommes|rösti|rosti|kroket|pekarski krumpir|krumpir.*smrz|smrz.*krumpir|hash brown)", re.I)


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def num(x):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    data = Path(sys.argv[2])
    problems = []

    # --- index the snapshot: (chain, store_code) -> normalized name -> list of rows
    idx = defaultdict(lambda: defaultdict(list))
    with gzip.open(data / "prices.csv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            idx[(r["chain"], r["store_code"])][norm(r["name"])].append(r)
    known_stores = {(r["chain"], r["store_code"]) for r in csv.DictReader(open(data / "stores.csv", encoding="utf-8"))}

    # --- stores in plan
    plan_stores = {}
    for s in plan.get("stores", []):
        key = f'{s["chain"]}:{s["code"]}' if s.get("code") else s["chain"]
        plan_stores[key] = s
        if s.get("code") and (s["chain"], s["code"]) not in known_stores:
            problems.append(f'store {key} is not in data/stores.csv')
    # chain-only keys resolve to the single store of that chain in the snapshot
    def resolve(key):
        if ":" in key:
            c, code = key.split(":", 1)
            return (c, code)
        cands = [k for k in idx if k[0] == key]
        return cands[0] if len(cands) == 1 else None

    # --- shopping items
    for i, it in enumerate(plan.get("shopping", [])):
        tag = f'shopping[{i}] "{it.get("name")}"'
        key = it.get("store") or it.get("chain")
        if key not in plan_stores and resolve(key) is None:
            problems.append(f"{tag}: store {key} not declared in plan.stores")
            continue
        sk = resolve(key)
        if sk is None or sk not in idx:
            problems.append(f"{tag}: no price rows for store {key}")
            continue
        rows = idx[sk].get(norm(it.get("name")))
        if not rows:
            # help the fixer: suggest close names
            words = [w for w in norm(it.get("name")).split() if len(w) > 3][:2]
            sugg = [n for n in idx[sk] if all(w in n for w in words)][:5]
            problems.append(f"{tag}: not found in {key} price list. Similar: {sugg}")
            continue
        if FROZEN_POTATO.search(it.get("name", "")) or FROZEN_POTATO.search(it.get("pack", "")):
            problems.append(f"{tag}: frozen potato product is not allowed")
        up = num(it.get("unit_price"))
        packs = it.get("packs", 1)
        total = num(it.get("total"))
        if not isinstance(packs, int) or packs < 1:
            problems.append(f"{tag}: packs must be an integer >= 1 (got {packs!r})")
        prices = [num(r["price"]) for r in rows]
        specials = [num(r["special_price"]) for r in rows if r.get("special_price")]
        promo = bool(it.get("promo"))
        if promo:
            if not specials:
                problems.append(f"{tag}: marked promo but the price list has no special_price for it")
            elif up is None or all(abs(up - s) > 0.01 for s in specials):
                problems.append(f"{tag}: promo unit_price {up} != special_price {specials}")
        else:
            if up is None or all(abs(up - p) > 0.01 for p in prices):
                problems.append(f"{tag}: unit_price {up} != list price {sorted(set(prices))}")
        if up is not None and total is not None and isinstance(packs, int) and abs(total - up * packs) > 0.02:
            problems.append(f"{tag}: total {total} != {packs} x {up}")

    # --- days & recipes
    recipes = {r["id"] for r in plan.get("recipes", [])}
    used = set()
    days = plan.get("days", [])
    if len(days) != 7:
        problems.append(f"days: expected 7, got {len(days)}")
    try:
        d0 = date.fromisoformat(plan["week_start"])
        for k, d in enumerate(days):
            if date.fromisoformat(d["date"]) != d0 + timedelta(days=k):
                problems.append(f'days[{k}]: date {d["date"]} is not week_start + {k}')
        if d0.weekday() != 0:
            problems.append(f"week_start {plan['week_start']} is not a Monday")
    except Exception as ex:  # noqa
        problems.append(f"dates: {ex}")
    for k, d in enumerate(days):
        for fld in ("dinner_recipe", "lunch_recipe"):
            rid = d.get(fld)
            if rid:
                used.add(rid)
                if rid not in recipes:
                    problems.append(f"days[{k}].{fld}: unknown recipe id {rid}")
        if d.get("label") in ("Mon", "Tue", "Wed", "Thu", "Fri") and d.get("lunch") not in ("grah i kupus", "vani"):
            problems.append(f'days[{k}]: weekday lunch must be "grah i kupus" or "vani", got {d.get("lunch")!r}')
    for rid in recipes - used:
        problems.append(f"recipe {rid} is never used")
    for r in plan.get("recipes", []):
        if not r.get("time_min"):
            problems.append(f'recipe {r["id"]}: time_min missing')

    if problems:
        print("INVALID PLAN, fix these before rendering:")
        for p in problems:
            print(" -", p)
        sys.exit(1)
    print(f"OK: {len(plan.get('shopping', []))} items verified against the price list, {len(recipes)} recipes.")


if __name__ == "__main__":
    main()
