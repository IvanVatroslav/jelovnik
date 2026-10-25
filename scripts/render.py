#!/usr/bin/env python3
"""
Render a weekly plan JSON into a single self-contained HTML file.

    python scripts/render.py plan.json out.html

Plan JSON schema (all strings UTF-8, prices in EUR):
{
  "week_start": "2026-10-26", "week_end": "2026-11-01",
  "generated": "2026-10-26", "archive_dates": {"lidl": "2026-10-26", ...},
  "notes": ["one-line caveats"],
  "stores": [{"chain": "lidl", "address": "Zadarska 79", "lat": 45.79, "lon": 15.93}],
  "days": [{"date": "2026-10-26", "label": "Pon", "lunch": "grah i kupus", "dinner": "Pileći file s rižom i brokulom",
            "dinner_recipe": "pileci-file-riza", "leftover": false, "protein_g": 92, "kcal": 820}],
  "shopping": [{"chain": "lidl", "name": "Svježi pileći filet", "pack": "1 kg", "packs": 2,
                "unit_price": 7.49, "total": 14.98, "for": ["Pon", "Uto"], "promo": true}],
  "single_store": {"chain": "plodine", "total": 61.20},
  "recipes": [{"id": "pileci-file-riza", "title": "Pileći file s rižom i brokulom", "image_keywords": "grilled chicken breast rice broccoli",
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


def food_img(title, keywords, idx=0, cls=""):
    """A photo slot: coloured placeholder with the dish name; JS swaps in a Wikimedia Commons photo."""
    bg = PALETTE[idx % len(PALETTE)]
    return (f'<div class="ph {cls}" style="background:{bg}" data-q="{e(keywords)}">'
            f'<span>{e(title)}</span></div>')


def maps_link(store):
    q = f'{chain_name(store["chain"])} {store.get("address","")} Zagreb'
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(q)


def fmt_date(iso):
    y, m, d = iso.split("-")
    return f"{int(d)}.{int(m)}."


def render(plan):
    recipes = {r["id"]: r for r in plan.get("recipes", [])}
    stores = plan.get("stores", [])
    shopping = plan.get("shopping", [])
    by_store = {}
    for it in shopping:
        by_store.setdefault(it["chain"], []).append(it)
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
        c = s["chain"]
        out.append(f'<a class="store" style="--c:{chain_color(c)}" href="{maps_link(s)}" target="_blank" rel="noopener">'
                   f'<img src="{logo(c)}" alt="" onerror="this.style.visibility=\'hidden\'"><div><b>{e(chain_name(c))}</b><small>{e(s.get("address",""))}</small></div>'
                   f'<span class="tot">{eur(subtotals.get(c, 0)) if c in subtotals else ""}</span></a>')
    out.append("</div>")

    # ---------- days ----------
    out.append("<h2>Tjedan</h2><div class=\"days\">")
    for d in plan["days"]:
        r = recipes.get(d.get("dinner_recipe"))
        ridx = list(recipes).index(r["id"]) if r else 0
        img = food_img(r["title"], r["image_keywords"], ridx, "small") if r else ""
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
                   f'<div class="m"><span class="pill">{e(d.get("protein_g","?"))} g prot</span><span class="sub">{e(d.get("kcal",""))} kcal</span></div>'
                   f'</div></div>')
    out.append("</div>")

    # ---------- shopping ----------
    out.append("<h2>Popis za kupnju <span class=\"sub\" style=\"font-weight:400\">(kvačice se pamte na ovom uređaju)</span></h2>")
    order = [s["chain"] for s in stores if s["chain"] in by_store] + [c for c in by_store if c not in [s["chain"] for s in stores]]
    for c in order:
        st = next((s for s in stores if s["chain"] == c), {"chain": c, "address": ""})
        out.append(f'<section class="shop" style="--c:{chain_color(c)}"><header><img src="{logo(c)}" alt="" onerror="this.style.visibility=\'hidden\'"><b>{e(chain_name(c))}</b>'
                   f'<span class="sub">{e(st.get("address",""))}</span><a href="{maps_link(st)}" target="_blank" rel="noopener">karta</a>'
                   f'<span class="st">{eur(subtotals[c])}</span></header><ul>')
        for i, it in enumerate(by_store[c]):
            key = f"{plan['week_start']}:{c}:{i}"
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
        out.append(f'<article class="rc" id="r-{e(r["id"])}">{food_img(r["title"], r["image_keywords"], i)}<div class="b">'
                   f'<h3>{e(r["title"])}</h3><div class="meta">{e(r.get("portions",1))} porcije · {e(r.get("protein_g","?"))} g prot / porcija · '
                   f'{e(r.get("kcal",""))} kcal · {e(r.get("time_min",""))} min</div>'
                   f'<ul>{"".join(f"<li>{e(x)}</li>" for x in r.get("ingredients", []))}</ul>'
                   f'<ol>{"".join(f"<li>{e(x)}</li>" for x in r.get("steps", []))}</ol></div></article>')
    out.append("</div>")

    out.append("""<div class="foot">Cijene iz javnih cjenika (NN 75/2025) preko cijene.dev. Fotografije jela su ilustrativne (Flickr CC).
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


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    Path(sys.argv[2]).write_text(render(plan), encoding="utf-8")
    print(f"wrote {sys.argv[2]}")


if __name__ == "__main__":
    main()
