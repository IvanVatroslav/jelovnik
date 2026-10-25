# jelovnik

Weekly grocery price snapshot for a configurable set of nearby stores, built on the public Croatian retail price lists (NN 75/2025) via the free [cijene.dev](https://cijene.dev) daily archives. The output feeds a separate meal-planning step.

## What it does

A GitHub Action runs `scripts/filter.py` every Monday morning (Lidl promotions start Mondays, most other chains Wednesday or Thursday). Chains missing from the day's archive fall back to the previous day. It downloads the day's archive from `api.cijene.dev/v0/archive/<date>.zip`, keeps the nearest store per chain within `radius_km` of the configured point, and commits:

- `data/stores.csv` the stores used
- `data/prices.csv.gz` every product + price in those stores
- `data/protein_picks.csv` cheapest product per tracked staple per store, with protein per euro
- `data/meta.json` archive date and counts
- `data/build.log` the run's output

## Config

- Stores: `store_codes` in `config.json` (`chain:code`). Alternatively leave it out and set `HOME_LAT` / `HOME_LON` repository secrets; the script then picks the nearest store per chain within `radius_km`.
- `config.json`: `radius_km`, `stores_per_chain`, `chains`, and `extra_store_codes` / `exclude_store_codes` as `chain:code` (codes from `data/stores.csv` or upstream [stores.csv](https://github.com/senko/cijene-api/blob/main/enrichment/stores.csv)).
- `scripts/staples.csv`: tracked items. Columns: `item, group, protein_g_100g, kcal_100g, include_regex, exclude_regex`. Regexes match case-insensitively against `name + brand`. No commas inside regexes.

Run locally: `python scripts/filter.py` (Python 3.10+, stdlib only).

## Notes

- Only chains geocoded upstream are covered (Konzum, Lidl, Spar, Kaufland, Plodine, Tommy, Eurospin, Studenac, KTC, NTL, Trgocentar), some partially. Add missing stores by code via `extra_store_codes`.
- Lidl sometimes publishes no Sunday prices; the Saturday archive is used on purpose.
- Prices are public data; upstream `enrichment/stores.csv` is CC BY-NC-SA. Personal, non-commercial use.
