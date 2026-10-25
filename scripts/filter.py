#!/usr/bin/env python3
"""
Weekly price snapshot for the stores near home.

1. Picks the nearest stores (per chain) from cijene-api's geocoded store list.
2. Downloads the newest daily archive from api.cijene.dev (free, no key).
3. Keeps only prices for those stores, joins product names and writes:
     data/stores.csv          the stores that were used
     data/prices.csv.gz       every product + price in those stores
     data/protein_picks.csv   cheapest match per staple per store, with protein per euro
     data/meta.json           archive date, row counts
"""
import csv, gzip, io, json, math, re, sys, zipfile, urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
UA = {"User-Agent": "jelovnik-weekly/1.0 (+github)"}

# Anything matching this (name + brand + category) is never food we'd cook with.
GLOBAL_EXCLUDE = re.compile(
    r"hrana za (ma[čc]k|ps|pse|ljubim)|za ma[čc]ke|za pse|kitekat|whiskas|felix|pedigree|petties|"
    r"kapsul|kaps\.|deterd|omek[šs]iva|[šs]ampon|regenerator|sapun|gel za|dezodor|pasta za zube|"
    r"salvet|ubrus|toalet|vre[ćc]ic|vrecic|folij|[šs]tapi[ćc]i za u[šs]i|stapici za usi|vata|"
    r"sjeme|sjemen|gnojiv|zemlja za|svije[ćc]|mirisn|osvje[žz]iva[čc]|"
    r"[čc]a[šs]a |[čc]a[šs]e |tanjur|pribor|posud|zdjel|kruhoreznic|"
    r"kreker|[čc]ips|grickal|flips|smoki|pločic|plocic|keks|napolitank|bombon|žvak|zvak|"
    r"tramezzini|sendvi[čc]|pizza|burek|"
    r"igra[čc]k|dje[čc]j|baby|bebe|pelen|"
    r"\bbio\b.*ulje za|ulje za masa|ulje za tijelo|"
    r"friskies|temeljac|ka[šs]ic|dekorac|naljepnic|usk\.|uskr[šs]|[žz]lic|ko[šs]aric|presa za|"
    r"nektar|\bsok\b|pi[ćc]e |gazir|juha|sladoled|bananko|\bpire\b|bra[šs]no|za pos\.|cest[ae]|"
    r"panir|punjen|dumpling|kruh s|heljdin|ljuska",
    re.I,
)

# Plausibility floor: a "match" priced below this many €/kg is a mis-match or a non-food item.
MIN_PPK_BY_GROUP = {
    "meso": 3.0, "riba": 3.0, "jaja": 2.5, "mliječno": 0.6, "dodaci": 8.0,
    "biljno": 1.0, "ugljikohidrati": 0.3, "povrće": 0.3, "voće": 0.5, "masti": 1.5, "ostalo": 0.1,
}
TOP_N_PER_STORE = 3


def fetch(url, binary=False, timeout=600):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if binary else r.read().decode("utf-8")


def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def home_coords():
    import os
    lat, lon = os.environ.get("HOME_LAT"), os.environ.get("HOME_LON")
    if lat and lon:
        return {"lat": float(lat), "lon": float(lon)}
    if CFG.get("home"):
        return CFG["home"]
    sys.exit("Set store_codes in config.json, or HOME_LAT/HOME_LON env vars")


def pick_stores():
    rows = list(csv.DictReader(io.StringIO(fetch(CFG["enrichment_stores_url"]))))
    if CFG.get("store_codes"):
        # explicit list, no coordinates needed
        chosen = []
        for r in rows:
            key = f'{r["chain_code"]}:{r["code"]}'
            if key in CFG["store_codes"]:
                chosen.append({
                    "chain": r["chain_code"], "store_code": r["code"], "type": r["type"],
                    "address": r["address"], "city": r["city"],
                    "distance_km": "", "lat": r["lat"], "lon": r["lon"],
                })
        return chosen
    home = home_coords()
    per_chain = defaultdict(list)
    for r in rows:
        if r["chain_code"] not in CFG["chains"]:
            continue
        try:
            d = haversine(home["lat"], home["lon"], float(r["lat"]), float(r["lon"]))
        except ValueError:
            continue
        key = f'{r["chain_code"]}:{r["code"]}'
        if key in CFG.get("exclude_store_codes", []):
            continue
        if d <= CFG["radius_km"] or key in CFG.get("extra_store_codes", []):
            per_chain[r["chain_code"]].append((d, r))
    chosen = []
    for chain, lst in per_chain.items():
        lst.sort(key=lambda x: x[0])
        keep = lst[: CFG["stores_per_chain"]]
        keep += [x for x in lst[CFG["stores_per_chain"]:] if f'{chain}:{x[1]["code"]}' in CFG.get("extra_store_codes", [])]
        for d, r in keep:
            chosen.append({
                "chain": chain, "store_code": r["code"], "type": r["type"],
                "address": r["address"], "city": r["city"], "distance_km": round(d, 2),
                "lat": r["lat"], "lon": r["lon"],
            })
    chosen.sort(key=lambda x: x["distance_km"])
    return chosen


def list_archives():
    """Archives newest first, today or earlier."""
    lst = json.loads(fetch(CFG["archive_list_url"]))["archives"]
    today = date.today().isoformat()
    lst = [a for a in lst if a["date"] <= today] or lst
    lst.sort(key=lambda a: a["date"], reverse=True)
    return lst


def process_archive(zf, wanted, chains, archive_date):
    """Extract rows for the wanted stores of the given chains from one archive."""
    names = set(zf.namelist())
    out_rows, by_chain_count, chain_date = [], defaultdict(int), {}
    for chain in chains:
        if f"{chain}/prices.csv" not in names:
            continue
        codes = {sc for (c, sc) in wanted if c == chain}
        prods = {}
        with zf.open(f"{chain}/products.csv") as f:
            for p in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")):
                prods[p["product_id"]] = p
        with zf.open(f"{chain}/prices.csv") as f:
            for pr in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")):
                if pr["store_id"] not in codes:
                    continue
                p = prods.get(pr["product_id"])
                if not p:
                    continue
                price = num(pr["price"])
                special = num(pr.get("special_price"))
                eff = special if (special and price and special < price) else price
                if eff is None:
                    continue
                kg = to_kg(p["unit"], p["quantity"], p["name"])
                unit_price = num(pr.get("unit_price"))
                ppk = round(eff / kg, 2) if kg else (unit_price if unit_price else None)
                st = wanted[(chain, pr["store_id"])]
                out_rows.append({
                    "chain": chain, "store_code": pr["store_id"], "store_address": st["address"],
                    "distance_km": st["distance_km"], "archive_date": archive_date, "barcode": p["barcode"],
                    "product_id": p["product_id"], "name": p["name"], "brand": p.get("brand", ""),
                    "category": p.get("category", ""), "unit": p.get("unit", ""), "quantity": p.get("quantity", ""),
                    "price": price, "special_price": special or "", "eff_price": eff,
                    "price_per_kg": ppk if ppk is not None else "",
                    "available": pr.get("available", ""),
                })
                by_chain_count[chain] += 1
        if by_chain_count[chain]:
            chain_date[chain] = archive_date
        else:
            with zf.open(f"{chain}/stores.csv") as f:
                ids = [s["store_id"] for s in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))]
            print(f"note: {chain} {sorted(codes)} not in archive {archive_date}; its store_ids start: {ids[:12]}")
    return out_rows, by_chain_count, chain_date


def num(s):
    if s is None:
        return None
    s = str(s).strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        m = re.search(r"\d+(?:\.\d+)?", s)
        return float(m.group()) if m else None


def to_kg(unit, qty, name):
    """Return the item's mass/volume in kg or l; None when it isn't resolvable."""
    u = (unit or "").strip().lower()
    q = num(qty)
    if q is None:
        # try to read "500 g" / "1 kg" / "1l" out of the name
        m = re.search(r"(\d+(?:[.,]\d+)?)\s?(kg|g|l|ml|dl)\b", name.lower())
        if not m:
            return None
        q, u = num(m.group(1)), m.group(2)
    if u in ("kg", "l"):
        return q
    if u in ("g", "ml"):
        return q / 1000.0
    if u == "dl":
        return q / 10.0
    if u in ("kom", "pc", "pcs", "kom.") and re.search(r"\bjaj", name.lower()):
        return q * 0.06  # ~60 g per egg
    return None


def main():
    stores = pick_stores()
    if not stores:
        sys.exit("No stores found near home; check config.json")
    wanted = {(s["chain"], s["store_code"]): s for s in stores}
    print(f"Using {len(stores)} stores:")
    for s in stores:
        print(f'  {str(s["distance_km"]):>5} km  {s["chain"]:9} {s["store_code"]:7} {s["address"]}')

    archives = list_archives()
    arch = archives[0]
    print(f'Downloading archive {arch["date"]} ({arch["size"]/1e6:.0f} MB) ...')
    zf = zipfile.ZipFile(io.BytesIO(fetch(arch["url"], binary=True)))
    chains_wanted = [c for c in CFG["chains"] if any(ch == c for (ch, _) in wanted)]
    out_rows, by_chain_count, chain_date = process_archive(zf, wanted, chains_wanted, arch["date"])

    # Chains missing from today's archive (e.g. Lidl on Sundays): fall back to the previous day.
    missing = [c for c in chains_wanted if by_chain_count.get(c, 0) == 0]
    if missing and len(archives) > 1:
        prev = archives[1]
        print(f'Chains missing in {arch["date"]}: {missing}. Falling back to {prev["date"]} ...')
        zf2 = zipfile.ZipFile(io.BytesIO(fetch(prev["url"], binary=True)))
        rows2, cnt2, date2 = process_archive(zf2, wanted, missing, prev["date"])
        out_rows += rows2
        by_chain_count.update({k: v for k, v in cnt2.items() if v})
        chain_date.update(date2)
    still_missing = [c for c in chains_wanted if by_chain_count.get(c, 0) == 0]
    if still_missing:
        print(f"WARNING no prices for {still_missing} in the last two archives (store code wrong or chain not crawled)")

    cols = list(out_rows[0].keys())
    with gzip.open(DATA / "prices.csv.gz", "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out_rows)
    with open(DATA / "stores.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(stores[0].keys()))
        w.writeheader()
        w.writerows(stores)

    # --- staple picks: cheapest product per staple per store ------------------
    staples = list(csv.DictReader(open(ROOT / "scripts" / "staples.csv", encoding="utf-8")))
    picks = []
    for s in staples:
        inc = re.compile(s["include_regex"], re.I)
        exc = re.compile(s["exclude_regex"], re.I) if s["exclude_regex"].strip() else None
        cands = defaultdict(list)
        min_ppk = MIN_PPK_BY_GROUP.get(s["group"], 0.0)
        for r in out_rows:
            nm = f'{r["name"]} {r["brand"]}'
            full = f'{nm} {r["category"]}'
            if not inc.search(nm) or (exc and exc.search(nm)) or GLOBAL_EXCLUDE.search(full):
                continue
            if str(r["available"]) == "0":
                continue
            if r["price_per_kg"] == "" or r["price_per_kg"] < min_ppk:
                continue
            cands[(r["chain"], r["store_code"])].append((r["price_per_kg"], r))
        prot = num(s["protein_g_100g"]) or 0
        for (chain, code), lst in sorted(cands.items()):
            lst.sort(key=lambda x: x[0])
            seen = set()
            kept = []
            for metric, r in lst:
                if r["name"] in seen:
                    continue
                seen.add(r["name"]); kept.append((metric, r))
                if len(kept) >= TOP_N_PER_STORE:
                    break
            for rank, (metric, r) in enumerate(kept, 1):
                ppk = r["price_per_kg"]
                picks.append({"rank": rank, **{
                "item": s["item"], "group": s["group"], "chain": chain, "store_code": code, "archive_date": r["archive_date"],
                "store_address": r["store_address"], "name": r["name"], "brand": r["brand"],
                "quantity": r["quantity"], "unit": r["unit"], "price": r["price"],
                "special_price": r["special_price"], "eff_price": r["eff_price"],
                "price_per_kg": ppk, "protein_g_100g": prot, "kcal_100g": s["kcal_100g"],
                "protein_g_per_eur": round(prot * 10 / ppk, 1) if (ppk and prot) else "",
                "barcode": r["barcode"],
            }})
    with open(DATA / "protein_picks.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(picks[0].keys()))
        w.writeheader()
        w.writerows(picks)

    meta = {
        "archive_date": arch["date"], "chain_archive_date": chain_date, "generated": date.today().isoformat(),
        "stores": len(stores), "rows": len(out_rows), "rows_by_chain": dict(by_chain_count),
        "staples_matched": len({p["item"] for p in picks}), "staples_total": len(staples),
    }
    (DATA / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(meta, indent=2, ensure_ascii=False))
    missing = sorted({s["item"] for s in staples} - {p["item"] for p in picks})
    if missing:
        print("Staples with no match:", ", ".join(missing))


if __name__ == "__main__":
    main()
