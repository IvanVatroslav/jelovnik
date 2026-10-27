#!/usr/bin/env python3
"""
Render a weekly plan JSON into a single self-contained HTML file.

    python scripts/render.py plan.json out.html

Plan JSON schema (all strings UTF-8, prices in EUR):
{
  "week_start": "2026-10-26", "week_end": "2026-11-01",
  "generated": "2026-10-26", "archive_dates": {"lidl": "2026-10-26", ...},
  "notes": ["one-line caveats"],
  "stores": [{"chain": "lidl", "address": "Zadarska 79"},
             {"chain": "konzum", "code": "1260", "label": "Super Konzum Point", "address": "Rudeška 169a"}],   # code+label when a chain appears twice
  # shopping items then reference that store with "store": "konzum:1260" (default: the chain)
  "days": [{"date": "2026-10-26", "label": "Pon", "lunch": "grah i kupus", "dinner": "Pileći file s rižom i brokulom",
            "dinner_recipe": "pileci-file-riza", "leftover": false, "protein_g": 92, "kcal": 820}],
  "shopping": [{"chain": "lidl", "name": "Svježi pileći filet", "pack": "1 kg", "packs": 2,
                "unit_price": 7.49, "total": 14.98, "for": ["Pon", "Uto"], "promo": true}],
  "single_store": {"chain": "plodine", "total": 61.20},
  "recipes": [{"id": "pileci-file-riza", "title": "Pileći file s rižom i brokulom",
               "image_url": "https://www.themealdb.com/images/media/meals/....jpg",   # optional, a real dish photo
               "image_ingredient": "Chicken Breast",                                   # fallback: TheMealDB ingredient name
               "image_keywords": "grilled chicken breast rice broccoli",
               "portions": 2, "protein_g": 78, "kcal": 790, "time_min": 25,
               "ingredients": ["300 g pileći file", "80 g riža (suha)", "200 g brokula", "1 žlica maslinovo ulje"],
               "steps": ["...", "..."]}],
  "totals": {"split": 68.40, "protein_avg_day": 152, "whey_g_day": 30}
}
"""
import html, json, sys, urllib.parse
from pathlib import Path

CHAIN = {
    "lidl":     {"name": "Lidl",     "domain": "lidl.hr",     "color": "#0050aa"},
    "konzum":   {"name": "Konzum",   "domain": "konzum.hr",   "color": "#e30613"},
    "spar":     {"name": "Spar",     "domain": "spar.hr",     "color": "#00843d"},
    "kaufland": {"name": "Kaufland", "domain": "kaufland.hr", "color": "#e10915"},
    "plodine":  {"name": "Plodine",  "domain": "plodine.hr",  "color": "#f39200"},
    "eurospin": {"name": "Eurospin", "domain": "eurospin.hr", "color": "#0a4ea2"},
    "studenac": {"name": "Studenac", "domain": "studenac.hr", "color": "#e2001a"},
    "tommy":    {"name": "Tommy",    "domain": "tommy.hr",    "color": "#d4001a"},
    "ktc":      {"name": "KTC",      "domain": "ktc.hr",      "color": "#1a4d9c"},
}
DAY_HR = {"Mon": "Ponedjeljak", "Tue": "Utorak", "Wed": "Srijeda", "Thu": "Četvrtak",
          "Fri": "Petak", "Sat": "Subota", "Sun": "Nedjelja"}


def e(s):
    return html.escape(str(s if s is not None else ""))


def eur(x):
    try:
        return f"{float(x):.2f} €".replace(".", ",")
    except (TypeError, ValueError):
        return ""


def logo(chain, size=64):
    d = CHAIN.get(chain, {}).get("domain", f"{chain}.hr")
    return f"https://www.google.com/s2/favicons?domain={d}&sz={size}"


def chain_name(chain):
    return CHAIN.get(chain, {}).get("name", chain.capitalize())


def chain_color(chain):
    return CHAIN.get(chain, {}).get("color", "#555")


PALETTE = ["#1f6f5f", "#b4532a", "#5a4f8f", "#a8862b", "#2f6b9a", "#8c3b5e", "#4b7a3a", "#7a5230"]


def recipe_image(r):
    """Static photo URL for a recipe: explicit image_url, else TheMealDB ingredient image, else None."""
    if r.get("image_url"):
        return r["image_url"]
    ing = r.get("image_ingredient")
    if ing:
        return "https://www.themealdb.com/images/ingredients/" + urllib.parse.quote(str(ing)) + ".png"
    return None


def food_img(title, keywords, idx=0, cls="", r=None):
    """A photo slot: static image if the plan has one, else coloured placeholder that JS tries to fill."""
    bg = PALETTE[idx % len(PALETTE)]
    u = recipe_image(r) if r else None
    if u:
        return (f'<div class="ph {cls} loaded" style="background:{bg}"><img src="{e(u)}" alt="" loading="lazy">'
                f'<span>{e(title)}</span></div>')
    return (f'<div class="ph {cls}" style="background:{bg}" data-q="{e(keywords)}">'
            f'<span>{e(title)}</span></div>')


def maps_link(store):
    q = f'{chain_name(store["chain"])} {store.get("address","")} Zagreb'
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(q)


def fmt_date(iso):
    y, m, d = iso.split("-")
    return f"{int(d)}.{int(m)}."


def store_key(s):
    return f'{s["chain"]}:{s["code"]}' if s.get("code") else s["chain"]


def item_key(it):
    return it.get("store") or it["chain"]


def store_title(s):
    return s.get("label") or chain_name(s["chain"])


def day_time(d, recipes):
    """Minutes of kitchen time this day: 0 for leftovers/own dish, else the recipes' time_min."""
    mins = 0
    for key, flag in (("dinner_recipe", d.get("leftover")), ("lunch_recipe", d.get("lunch_leftover"))):
        r = recipes.get(d.get(key))
        if r and not flag:
            mins += int(r.get("time_min") or 0)
    return mins


def time_label(mins):
    if not mins:
        return "samo podgrij"
    return f"{mins} min kuhanja"


def render(plan):
    recipes = {r["id"]: r for r in plan.get("recipes", [])}
    stores = plan.get("stores", [])
    shopping = plan.get("shopping", [])
    by_store = {}
    for it in shopping:
        by_store.setdefault(item_key(it), []).append(it)
    subtotals = {c: sum(float(i.get("total", 0)) for i in items) for c, items in by_store.items()}
    grand = sum(subtotals.values())
    totals = plan.get("totals", {})
    single = plan.get("single_store") or {}

    # ---------- header ----------
    out = [f"""<!doctype html><html lang="hr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jelovnik {fmt_date(plan["week_start"])} – {fmt_date(plan["week_end"])}</title>
<style>
:root{{--bg:#f6f3ee;--card:#fff;--ink:#1d1d1b;--mute:#6b6760;--line:#e6e1d8;--acc:#1f6f5f;--acc2:#d9534f}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
.wrap{{max-width:1100px;margin:0 auto;padding:20px 16px 60px}}
h1{{font-size:28px;margin:0 0 4px}}h2{{font-size:20px;margin:36px 0 12px;display:flex;align-items:center;gap:10px}}
.sub{{color:var(--mute);font-size:14px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}}
.kpi b{{display:block;font-size:22px}}.kpi span{{font-size:12px;color:var(--mute);text-transform:uppercase;letter-spacing:.04em}}
.notes{{background:#fff8e6;border:1px solid #f1dfae;border-radius:10px;padding:10px 14px;font-size:14px}}
.notes li{{margin:2px 0}}
.stores{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}}
.store{{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--c);border-radius:12px;padding:12px;display:flex;gap:10px;align-items:center;text-decoration:none;color:inherit}}
.store img{{width:36px;height:36px;border-radius:8px;background:#fff;object-fit:contain}}
.store b{{display:block}}.store small{{color:var(--mute)}}
.store .tot{{margin-left:auto;font-weight:700;white-space:nowrap}}
.days{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}}
.day{{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;display:flex;flex-direction:column}}
.ph{{position:relative;width:100%;height:170px;overflow:hidden;display:flex;align-items:flex-end;padding:10px 12px;color:#fff;font-weight:700;font-size:15px;text-shadow:0 1px 3px rgba(0,0,0,.5)}}
.ph.small{{height:130px;font-size:14px}}.ph img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
.ph span{{position:relative;z-index:1}}.ph.loaded span{{display:none}}
.day .b{{padding:10px 12px 12px;flex:1;display:flex;flex-direction:column;gap:4px}}
.day .d{{font-size:12px;color:var(--mute);text-transform:uppercase;letter-spacing:.05em}}
.day .l{{font-size:13px;color:var(--mute)}}.day .l::before{{content:"Ručak · "}}
.day .n{{font-weight:600}}.day .n::before{{content:"Večera · ";font-weight:400;color:var(--mute)}}
.day .m{{margin-top:auto;padding-top:6px;font-size:13px;display:flex;gap:10px}}
.pill{{display:inline-block;background:#e8f3f0;color:var(--acc);border-radius:999px;padding:1px 8px;font-size:12px;font-weight:600}}
.pill.left{{background:#efeae2;color:#7a6a4f}}.pill.promo{{background:#fdecec;color:var(--acc2)}}
.shop{{background:var(--card);border:1px solid var(--line);border-radius:14px;margin-bottom:14px;overflow:hidden}}
.shop header{{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--line);border-left:5px solid var(--c)}}
.shop header img{{width:28px;height:28px;border-radius:6px}}.shop header b{{font-size:17px}}
.shop header a{{margin-left:auto;font-size:13px;color:var(--acc)}}
.shop header .st{{font-weight:700;margin-left:12px;white-space:nowrap}}
.shop ul{{list-style:none;margin:0;padding:4px 0}}
.shop li{{display:grid;grid-template-columns:28px 1fr auto;gap:8px;padding:8px 14px;border-bottom:1px dashed var(--line);align-items:center}}
.shop li:last-child{{border:0}}.shop li input{{width:20px;height:20px;accent-color:var(--acc)}}
.shop li.done .t{{text-decoration:line-through;color:var(--mute)}}
.shop li .t small{{display:block;color:var(--mute);font-size:12px}}
.shop li .p{{text-align:right;white-space:nowrap}}.shop li .p small{{display:block;color:var(--mute);font-size:12px}}
.grand{{display:flex;justify-content:space-between;align-items:baseline;background:var(--ink);color:#fff;border-radius:12px;padding:12px 16px;font-size:18px}}
.grand small{{color:#cfc9bf;font-size:13px}}
.recipes{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}}
.rc{{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;scroll-margin-top:12px}}
.rc .b{{padding:12px 14px 14px}}.rc h3{{margin:0 0 4px;font-size:18px}}
.rc .meta{{font-size:13px;color:var(--mute);margin-bottom:8px}}
.rc ul{{margin:6px 0 10px;padding-left:18px;font-size:14px}}.rc ol{{margin:0;padding-left:18px;font-size:14px}}
.rc li{{margin:2px 0}}
.foot{{margin-top:40px;font-size:12px;color:var(--mute)}}
a{{color:var(--acc)}}
@media print{{.ph{{height:90px}}.shop li input{{display:none}}}}
</style></head><body><div class="wrap">
<h1>Jelovnik {fmt_date(plan["week_start"])} – {fmt_date(plan["week_end"])}</h1>
<div class="sub">Cijene: {", ".join(f"{chain_name(c)} {fmt_date(d)}" for c, d in sorted(plan.get("archive_dates", {}).items()))}
 · generirano {fmt_date(plan.get("generated", plan["week_start"]))}</div>
<div class="kpis">
 <div class="kpi"><b>{eur(grand)}</b><span>ukupno, {len(by_store)} trgovine</span></div>
 <div class="kpi"><b>{e(totals.get("protein_avg_day","–"))} g</b><span>proteina / dan (prosjek)</span></div>
 <div class="kpi"><b>{len(recipes)}</b><span>recepata</span></div>
 <div class="kpi"><b>{eur(single.get("total")) if single else "–"}</b><span>sve u jednoj: {e(chain_name(single.get("chain",""))) if single else "–"}</span></div>
</div>"""]
    if plan.get("notes"):
        out.append('<div class="notes"><ul style="margin:0;padding-left:18px">' +
                   "".join(f"<li>{e(n)}</li>" for n in plan["notes"]) + "</ul></div>")

    # ---------- stores ----------
    out.append("<h2>Trgovine</h2><div class=\"stores\">")
    for s in stores:
        c, k = s["chain"], store_key(s)
        out.append(f'<a class="store" style="--c:{chain_color(c)}" href="{maps_link(s)}" target="_blank" rel="noopener">'
                   f'<img src="{logo(c)}" alt="" onerror="this.style.visibility=\'hidden\'"><div><b>{e(store_title(s))}</b><small>{e(s.get("address",""))}</small></div>'
                   f'<span class="tot">{eur(subtotals.get(k, 0)) if k in subtotals else ""}</span></a>')
    out.append("</div>")

    # ---------- days ----------
    out.append("<h2>Tjedan</h2><div class=\"days\">")
    for d in plan["days"]:
        r = recipes.get(d.get("dinner_recipe"))
        ridx = list(recipes).index(r["id"]) if r else 0
        img = food_img(r["title"], r.get("image_keywords", ""), ridx, "small", r) if r else ""
        label = DAY_HR.get(d.get("label"), d.get("label", ""))
        pills = ""
        if d.get("leftover"):
            pills += '<span class="pill left">ostatak</span>'
        href = f'#r-{e(r["id"])}' if r else "#"
        lr = recipes.get(d.get("lunch_recipe"))
        lunch_html = (f'<a href="#r-{e(lr["id"])}" style="color:inherit">{e(d.get("lunch",""))}</a>' if lr else e(d.get("lunch", "")))
        out.append(f'<div class="day">{f"<a href={chr(34)}{href}{chr(34)}>{img}</a>" if r else ""}'
                   f'<div class="b"><div class="d">{e(label)} {fmt_date(d["date"])}</div>'
                   f'<div class="l">{lunch_html}</div>'
                   f'<div class="n"><a href="{href}" style="color:inherit;text-decoration:none">{e(d.get("dinner",""))}</a> {pills}</div>'
                   f'<div class="m"><span class="pill">{e(d.get("protein_g","?"))} g prot</span><span class="sub">{e(d.get("kcal",""))} kcal</span><span class="sub">⏱ {time_label(day_time(d, recipes))}</span></div>'
                   f'</div></div>')
    out.append("</div>")

    # ---------- shopping ----------
    out.append("<h2>Popis za kupnju <span class=\"sub\" style=\"font-weight:400\">(kvačice se pamte na ovom uređaju)</span></h2>")
    order = [store_key(s) for s in stores if store_key(s) in by_store] + [k for k in by_store if k not in [store_key(s) for s in stores]]
    for k in order:
        st = next((s for s in stores if store_key(s) == k), {"chain": k.split(":")[0], "address": ""})
        c = st["chain"]
        out.append(f'<section class="shop" style="--c:{chain_color(c)}"><header><img src="{logo(c)}" alt="" onerror="this.style.visibility=\'hidden\'"><b>{e(store_title(st))}</b>'
                   f'<span class="sub">{e(st.get("address",""))}</span><a href="{maps_link(st)}" target="_blank" rel="noopener">karta</a>'
                   f'<span class="st">{eur(subtotals[k])}</span></header><ul>')
        for i, it in enumerate(by_store[k]):
            key = f"{plan['week_start']}:{k}:{i}"
            promo = ' <span class="pill promo">akcija</span>' if it.get("promo") else ""
            fr = ", ".join(it.get("for", [])) if it.get("for") else ""
            out.append(f'<li data-k="{e(key)}"><input type="checkbox"><div class="t">{e(it["name"])}{promo}'
                       f'<small>{e(it.get("pack",""))} × {e(it.get("packs",1))}{" · " + e(fr) if fr else ""}</small></div>'
                       f'<div class="p">{eur(it.get("total"))}<small>{eur(it.get("unit_price"))}/kom</small></div></li>')
        out.append("</ul></section>")
    out.append(f'<div class="grand"><span>Ukupno</span><span>{eur(grand)}'
               + (f' <small>· sve u {e(chain_name(single["chain"]))}: {eur(single["total"])}</small>' if single else "")
               + "</span></div>")

    # ---------- recipes ----------
    out.append("<h2>Recepti</h2><div class=\"recipes\">")
    for i, r in enumerate(plan.get("recipes", [])):
        out.append(f'<article class="rc" id="r-{e(r["id"])}">{food_img(r["title"], r.get("image_keywords", ""), i, "", r)}<div class="b">'
                   f'<h3>{e(r["title"])}</h3><div class="meta">{e(r.get("portions",1))} porcije · {e(r.get("protein_g","?"))} g prot / porcija · '
                   f'{e(r.get("kcal",""))} kcal · {e(r.get("time_min",""))} min</div>'
                   f'<ul>{"".join(f"<li>{e(x)}</li>" for x in r.get("ingredients", []))}</ul>'
                   f'<ol>{"".join(f"<li>{e(x)}</li>" for x in r.get("steps", []))}</ol></div></article>')
    out.append("</div>")

    out.append("""<div class="foot">Cijene iz javnih cjenika (NN 75/2025) preko cijene.dev. Fotografije jela su ilustrativne (TheMealDB).
Logotipi su zaštitni znakovi trgovaca.</div></div>
<script>
try{var K="jelovnik-"+location.pathname;var S=JSON.parse(localStorage.getItem(K)||"{}");
document.querySelectorAll(".shop li").forEach(function(li){var k=li.dataset.k,cb=li.querySelector("input");
if(S[k]){cb.checked=true;li.classList.add("done")}
cb.addEventListener("change",function(){li.classList.toggle("done",cb.checked);S[k]=cb.checked;try{localStorage.setItem(K,JSON.stringify(S))}catch(e){}})})}catch(e){}
(function(){var cache={};
function commons(q){return fetch("https://commons.wikimedia.org/w/api.php?action=query&format=json&origin=*&generator=search&gsrnamespace=6&gsrlimit=5&gsrsearch="+encodeURIComponent("filetype:bitmap "+q+" food")+"&prop=imageinfo&iiprop=url|mime&iiurlwidth=800")
 .then(function(r){return r.json()}).then(function(j){var p=j.query&&j.query.pages;if(!p)return null;
 var arr=Object.values(p).filter(function(x){var ii=x.imageinfo&&x.imageinfo[0];return ii&&/jpeg|png|webp/.test(ii.mime)&&!/[.]svg$/i.test(ii.url)}).sort(function(a,b){return a.index-b.index});
 return arr.length?arr[0].imageinfo[0].thumburl:null})}
function openverse(q){return fetch("https://api.openverse.org/v1/images/?q="+encodeURIComponent(q)+"&page_size=5&license_type=all&category=photograph")
 .then(function(r){return r.json()}).then(function(j){var r=j.results&&j.results[0];return r?r.url:null})}
function lookup(q){if(!cache[q])cache[q]=commons(q).catch(function(){return null}).then(function(u){return u||openverse(q).catch(function(){return null})});return cache[q]}
document.querySelectorAll(".ph[data-q]").forEach(function(ph){var q=ph.dataset.q;if(!q)return;
 lookup(q).then(function(u){if(!u)return;var im=new Image();im.referrerPolicy="no-referrer";im.onload=function(){ph.appendChild(im);ph.classList.add("loaded")};im.src=u})});})();
</script></body></html>""")
    return "".join(out)




# ---------------------------------------------------------------------------
# Email mode: Gmail-safe HTML (inline styles, tables, no JS/CSS vars/grid).
# ---------------------------------------------------------------------------
import urllib.request

_IMG_CACHE = {}


def commons_photo(keywords, width=600):
    """Resolve a Wikimedia Commons photo URL for the keywords at render time. None on failure."""
    q = str(keywords).strip()
    if not q:
        return None
    if q in _IMG_CACHE:
        return _IMG_CACHE[q]
    url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=search"
           "&gsrnamespace=6&gsrlimit=6&gsrsearch=" + urllib.parse.quote(f"filetype:bitmap {q} food")
           + f"&prop=imageinfo&iiprop=url|mime&iiurlwidth={width}")
    out = None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "jelovnik-weekly/1.0 (personal meal planner)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            pages = json.loads(r.read().decode("utf-8")).get("query", {}).get("pages", {})
        cands = []
        for pg in pages.values():
            ii = (pg.get("imageinfo") or [{}])[0]
            if ii.get("thumburl") and ii.get("mime", "").split("/")[-1] in ("jpeg", "png", "webp"):
                cands.append((pg.get("index", 99), ii["thumburl"]))
        if cands:
            out = sorted(cands)[0][1]
    except Exception:
        out = None
    _IMG_CACHE[q] = out
    return out


F = "font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
MUTE = "color:#6b6760;"


def _photo_cell(title, keywords, idx, height, r=None):
    u = recipe_image(r) if r else None
    bg = PALETTE[idx % len(PALETTE)]
    if u:
        return (f'<img src="{e(u)}" width="100%" height="{height}" alt="{e(title)}" '
                f'style="display:block;width:100%;height:{height}px;object-fit:cover;border-radius:12px 12px 0 0;background:{bg}">')
    return (f'<div style="height:{height}px;background:{bg};border-radius:12px 12px 0 0;color:#fff;{F}font-weight:700;'
            f'font-size:15px;padding:0 12px;line-height:{height}px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">{e(title)}</div>')


def render_email(plan):
    recipes = {r["id"]: r for r in plan.get("recipes", [])}
    rid_index = {rid: i for i, rid in enumerate(recipes)}
    stores = plan.get("stores", [])
    by_store = {}
    for it in plan.get("shopping", []):
        by_store.setdefault(item_key(it), []).append(it)
    subtotals = {c: sum(float(i.get("total", 0)) for i in items) for c, items in by_store.items()}
    grand = sum(subtotals.values())
    totals = plan.get("totals", {})
    single = plan.get("single_store") or {}

    card = "background:#ffffff;border:1px solid #e6e1d8;border-radius:12px;"
    h2 = f'style="{F}font-size:20px;margin:28px 0 10px;color:#1d1d1b"'
    o = [f'<div style="background:#f6f3ee;padding:16px 10px"><div style="max-width:680px;margin:0 auto;{F}color:#1d1d1b;font-size:15px;line-height:1.45">',
         f'<h1 style="{F}font-size:26px;margin:0 0 2px">Jelovnik {fmt_date(plan["week_start"])} – {fmt_date(plan["week_end"])}</h1>',
         f'<div style="{MUTE}font-size:13px;margin-bottom:14px">Cijene: '
         + ", ".join(f"{chain_name(c)} {fmt_date(d)}" for c, d in sorted(plan.get("archive_dates", {}).items())) + "</div>"]

    # KPIs
    kp = [(eur(grand), f"ukupno, {len(by_store)} trgovine"), (f'{totals.get("protein_avg_day","–")} g', "proteina / dan"),
          (str(len(recipes)), "recepata"), (eur(single.get("total")) if single else "–", f'sve u {chain_name(single.get("chain",""))}' if single else "")]
    o.append('<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>')
    for i, (v, l) in enumerate(kp):
        o.append(f'<td width="25%" style="padding:{"0 4px 0 0" if i == 0 else "0 0 0 4px" if i == 3 else "0 4px"}">'
                 f'<div style="{card}padding:10px 12px"><div style="font-size:20px;font-weight:700">{e(v)}</div>'
                 f'<div style="{MUTE}font-size:11px;text-transform:uppercase;letter-spacing:.04em">{e(l)}</div></div></td>')
    o.append("</tr></table>")
    if plan.get("notes"):
        o.append('<div style="background:#fff8e6;border:1px solid #f1dfae;border-radius:10px;padding:8px 12px;font-size:13px;margin-top:10px">'
                 + "<br>".join("• " + e(n) for n in plan["notes"]) + "</div>")

    # stores
    o.append(f"<h2 {h2}>Trgovine</h2>")
    for s in stores:
        c, k = s["chain"], store_key(s)
        o.append(f'<a href="{maps_link(s)}" style="text-decoration:none;color:#1d1d1b"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
                 f'style="{card}border-left:5px solid {chain_color(c)};margin-bottom:6px"><tr>'
                 f'<td width="44" style="padding:8px 4px 8px 10px"><img src="{logo(c)}" width="28" height="28" alt="" style="display:block;border-radius:6px"></td>'
                 f'<td style="padding:8px 0"><b>{e(store_title(s))}</b><br><span style="{MUTE}font-size:13px">{e(s.get("address",""))}</span></td>'
                 f'<td align="right" style="padding:8px 12px;font-weight:700;white-space:nowrap">{eur(subtotals[k]) if k in subtotals else ""}</td></tr></table></a>')

    # week: 2 columns of day cards
    o.append(f"<h2 {h2}>Tjedan</h2>")
    days = plan["days"]
    o.append('<table role="presentation" width="100%" cellspacing="0" cellpadding="0">')
    for row in range(0, len(days), 2):
        o.append("<tr>")
        for col in range(2):
            if row + col >= len(days):
                o.append("<td width='50%'></td>")
                continue
            d = days[row + col]
            r = recipes.get(d.get("dinner_recipe"))
            lr = recipes.get(d.get("lunch_recipe"))
            pad = "0 4px 8px 0" if col == 0 else "0 0 8px 4px"
            lunch = e(d.get("lunch", ""))
            if lr:
                lunch = f'<a href="#r-{e(lr["id"])}" style="color:#1d1d1b">{lunch}</a>'
            dinner = e(d.get("dinner", ""))
            if r:
                dinner = f'<a href="#r-{e(r["id"])}" style="color:#1d1d1b;text-decoration:none;font-weight:600">{dinner}</a>'
            left = ' <span style="background:#efeae2;color:#7a6a4f;border-radius:999px;padding:1px 7px;font-size:11px;font-weight:600">ostatak</span>' if d.get("leftover") else ""
            photo = _photo_cell(r["title"], r.get("image_keywords", ""), rid_index[r["id"]], 120, r) if r else ""
            o.append(f'<td width="50%" valign="top" style="padding:{pad}"><div style="{card}overflow:hidden">{photo}'
                     f'<div style="padding:8px 10px 10px">'
                     f'<div style="{MUTE}font-size:11px;text-transform:uppercase;letter-spacing:.05em">{e(DAY_HR.get(d.get("label"), d.get("label","")))} {fmt_date(d["date"])}</div>'
                     f'<div style="{MUTE}font-size:13px">Ručak · {lunch}</div>'
                     f'<div><span style="{MUTE}">Večera · </span>{dinner}{left}</div>'
                     f'<div style="margin-top:6px;font-size:12px"><span style="background:#e8f3f0;color:#1f6f5f;border-radius:999px;padding:1px 7px;font-weight:600">{e(d.get("protein_g","?"))} g prot</span>'
                     f' <span style="{MUTE}">{e(d.get("kcal",""))} kcal</span>'
                     f'<br><span style="{MUTE}">⏱ {time_label(day_time(d, recipes))}</span></div></div></div></td>')
        o.append("</tr>")
    o.append("</table>")

    # shopping
    o.append(f"<h2 {h2}>Popis za kupnju</h2>")
    order = [store_key(s) for s in stores if store_key(s) in by_store] + [k for k in by_store if k not in [store_key(s) for s in stores]]
    for k in order:
        st = next((s for s in stores if store_key(s) == k), {"chain": k.split(":")[0], "address": ""})
        c = st["chain"]
        o.append(f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="{card}margin-bottom:10px;border-collapse:separate">'
                 f'<tr><td colspan="3" style="padding:8px 12px;border-bottom:1px solid #e6e1d8;border-left:5px solid {chain_color(c)};border-radius:12px 12px 0 0">'
                 f'<img src="{logo(c)}" width="22" height="22" alt="" style="vertical-align:middle;border-radius:5px;margin-right:6px"><b style="font-size:16px;vertical-align:middle">{e(store_title(st))}</b>'
                 f' <span style="{MUTE}font-size:13px;vertical-align:middle">{e(st.get("address",""))}</span>'
                 f' <a href="{maps_link(st)}" style="font-size:12px;color:#1f6f5f;vertical-align:middle">karta</a>'
                 f'<span style="float:right;font-weight:700">{eur(subtotals[k])}</span></td></tr>')
        for it in by_store[k]:
            promo = ' <span style="background:#fdecec;color:#d9534f;border-radius:999px;padding:0 6px;font-size:11px;font-weight:600">akcija</span>' if it.get("promo") else ""
            fr = (" · " + ", ".join(it["for"])) if it.get("for") else ""
            o.append(f'<tr><td width="18" style="padding:7px 0 7px 12px;border-bottom:1px dashed #e6e1d8;vertical-align:top">☐</td>'
                     f'<td style="padding:7px 8px;border-bottom:1px dashed #e6e1d8">{e(it["name"])}{promo}<br>'
                     f'<span style="{MUTE}font-size:12px">{e(it.get("pack",""))} × {e(it.get("packs",1))}{e(fr)}</span></td>'
                     f'<td align="right" style="padding:7px 12px;border-bottom:1px dashed #e6e1d8;white-space:nowrap;vertical-align:top">{eur(it.get("total"))}<br>'
                     f'<span style="{MUTE}font-size:12px">{eur(it.get("unit_price"))}/kom</span></td></tr>')
        o.append("</table>")
    o.append(f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#1d1d1b;color:#fff;border-radius:12px"><tr>'
             f'<td style="padding:10px 14px;font-size:17px">Ukupno</td><td align="right" style="padding:10px 14px;font-size:17px;color:#fff">{eur(grand)}'
             + (f' <span style="color:#cfc9bf;font-size:12px">· sve u {e(chain_name(single["chain"]))}: {eur(single["total"])}</span>' if single else "") + "</td></tr></table>")

    # recipes
    o.append(f"<h2 {h2}>Recepti</h2>")
    for i, r in enumerate(plan.get("recipes", [])):
        o.append(f'<a name="r-{e(r["id"])}"></a><div id="r-{e(r["id"])}" style="{card}overflow:hidden;margin-bottom:12px">'
                 + _photo_cell(r["title"], r.get("image_keywords", ""), i, 160, r)
                 + f'<div style="padding:10px 14px 12px"><div style="font-size:18px;font-weight:700">{e(r["title"])}</div>'
                 f'<div style="{MUTE}font-size:13px;margin-bottom:6px">{e(r.get("portions",1))} porcije · {e(r.get("protein_g","?"))} g prot / porcija · {e(r.get("kcal",""))} kcal · {e(r.get("time_min",""))} min</div>'
                 f'<ul style="margin:4px 0 8px;padding-left:18px;font-size:14px">{"".join(f"<li>{e(x)}</li>" for x in r.get("ingredients", []))}</ul>'
                 f'<ol style="margin:0;padding-left:18px;font-size:14px">{"".join(f"<li style=margin-bottom:2px>{e(x)}</li>" for x in r.get("steps", []))}</ol></div></div>')

    o.append(f'<div style="{MUTE}font-size:11px;margin-top:24px">Cijene iz javnih cjenika (NN 75/2025) preko cijene.dev. Fotografije jela su ilustrativne (TheMealDB). '
             f'Logotipi su zaštitni znakovi trgovaca.</div></div></div>')
    return "".join(o)


def main():
    """render.py plan.json out.html [--email out_email.html] [--data DATA_DIR  (validates first, refuses on mismatch)]"""
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if "--data" in sys.argv:
        # refuse to render anything that doesn't match the real price list
        import subprocess
        data_dir = sys.argv[sys.argv.index("--data") + 1]
        rc = subprocess.call([sys.executable, "-I", str(Path(__file__).with_name("validate.py")), sys.argv[1], data_dir])
        if rc != 0:
            sys.exit("render refused: plan.json failed validation")
    Path(sys.argv[2]).write_text(render(plan), encoding="utf-8")
    print(f"wrote {sys.argv[2]}")
    if "--email" in sys.argv:
        out = sys.argv[sys.argv.index("--email") + 1]
        Path(out).write_text(render_email(plan), encoding="utf-8")
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
