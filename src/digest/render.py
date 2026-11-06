"""Render a digest dict (``build_digest``) as Markdown or as a standalone HTML page.

Both renderers produce the same four sections in the same order with Czech headings.
``write_digest`` saves one file per format into a directory."""

from __future__ import annotations

import html
from collections.abc import Iterable
from pathlib import Path

from src.digest.build import PERIOD_ADJECTIVES, format_date_cz

FORMATS = ("md", "html")
# parameters listed for a new product before "… a dalších N"
MAX_PARAMETERS = 10

SECTION_TITLES = (
    "1. Čísla za období",
    "2. Co je nové",
    "3. Executive summary",
    "4. Bankovní trh a nezařazené zprávy",
)
PRODUCT_KINDS = {"novy": "Nový produkt", "zmena": "Změna parametrů", "aktualizace": "Aktualizace"}
CAMPAIGN_KINDS = {"nova": "Nová kampaň", "aktualizovana": "Aktualizovaná kampaň"}
EMPTY_ALL = "Za toto období nebyly zaznamenány žádné položky."
EMPTY_COMPANIES = "Žádná společnost nemá v období nové položky."
EMPTY_SUMMARIES = "V období nejsou žádné položky executive summary."
EMPTY_MARKET = "Žádné zprávy z trhu."


# ── Czech helpers ────────────────────────────────────────────────


def plural_cz(n: int, one: str, few: str, many: str) -> str:
    """``1 článek``, ``2 články``, ``5 článků``."""
    if n == 1:
        form = one
    elif 2 <= n <= 4:
        form = few
    else:
        form = many
    return f"{n} {form}"


def _datetime_cz(value: str | None) -> str:
    if not value:
        return "—"
    day = format_date_cz(value)
    time = str(value)[11:16]
    return f"{day} {time}" if time else day


def _segments_label(digest: dict) -> str:
    if digest.get("filtr_segmentu"):
        return ", ".join(s["nazev"] for s in digest.get("segmenty", []))
    return "všechny"


def _totals_label(digest: dict) -> str:
    s = digest["souhrn"]
    return " · ".join([
        plural_cz(s["spolecnosti"], "společnost", "společnosti", "společností"),
        plural_cz(s["clanky"], "článek", "články", "článků"),
        plural_cz(s["kampane"], "kampaň", "kampaně", "kampaní"),
        plural_cz(s["produkty"], "produkt", "produkty", "produktů"),
        f"{s['mystery_shopping']} mystery shopping",
        f"{s['executive_summary']} executive summary",
        plural_cz(s["trh"], "zpráva z trhu", "zprávy z trhu", "zpráv z trhu"),
    ])


def _product_context(p: dict) -> str:
    parts = []
    if p.get("segment"):
        parts.append(p["segment"]["nazev"] + (f" / {p['produktova_linie']}" if p.get("produktova_linie") else ""))
    if p.get("zakaznicky_segment"):
        parts.append(p["zakaznicky_segment"])
    return " · ".join(parts)


def _change_text(z: dict) -> tuple[str, str]:
    """(label, description) of one parameter change, without markup."""
    label = z["name"] if not z.get("section") else f"{z['section']}: {z['name']}"
    if z["druh"] == "pridano":
        return label, f"nově {z.get('nova') or '—'}"
    if z["druh"] == "odebrano":
        return label, f"odebráno (dříve {z.get('stara') or '—'})"
    return label, f"{z.get('stara') or '—'} → {z.get('nova') or '—'}"


def _creative_text(k: dict) -> str:
    parts = [format_date_cz(k.get("datum")) if k.get("datum") else None, k.get("media_typ")]
    return " · ".join(x for x in parts if x)


def _first_paragraph(text: str | None) -> str | None:
    if not text:
        return None
    first = text.strip().split("\n", 1)[0].strip()
    return first or None


# ── Markdown ─────────────────────────────────────────────────────


def _md(text) -> str:
    """Escape the characters that would change the Markdown structure of inline text."""
    if text is None:
        return ""
    out = str(text)
    for ch in ("\\", "|", "[", "]", "*"):
        out = out.replace(ch, "\\" + ch)
    return " ".join(out.split())


def _md_link(text, url: str | None) -> str:
    return f"[{_md(text)}]({url})" if url else _md(text)


def render_markdown(digest: dict) -> str:
    p = digest["period"]
    lines = [
        f"# {p['nazev']} konkurence: {p['popis']}",
        "",
        f"- Období: {format_date_cz(p['od'])} – {format_date_cz(p['do'])} ({PERIOD_ADJECTIVES[p['typ']]})",
        f"- Segmenty: {_md(_segments_label(digest))}",
        f"- Vygenerováno: {_datetime_cz(digest.get('vygenerovano'))}",
        "",
    ]
    if digest.get("prazdny"):
        lines += [f"_{EMPTY_ALL}_", ""]
    lines += _md_numbers(digest)
    lines += _md_companies(digest)
    lines += _md_summaries(digest)
    lines += _md_market(digest)
    return "\n".join(lines).rstrip() + "\n"


def _md_numbers(digest: dict) -> list[str]:
    lines = [f"## {SECTION_TITLES[0]}", ""]
    companies = digest["spolecnosti"]
    if not companies:
        lines += [f"_{EMPTY_COMPANIES}_", ""]
    else:
        lines += [
            "| Společnost | Tier | Články | Kampaně | Produkty | Mystery shopping |",
            "|---|:-:|--:|--:|--:|--:|",
        ]
        for c in companies:
            n = c["pocty"]
            tier = c["tier"] if c.get("tier") is not None else "—"
            lines.append(
                f"| {_md(c['nazev'])} | {tier} | {n['clanky']} | {n['kampane']} | {n['produkty']} "
                f"| {n['mystery_shopping']} |"
            )
        lines.append("")
    lines += [f"Celkem: {_totals_label(digest)}", ""]
    return lines


def _md_companies(digest: dict) -> list[str]:
    lines = [f"## {SECTION_TITLES[1]}", ""]
    companies = digest["spolecnosti"]
    if not companies:
        return lines + [f"_{EMPTY_COMPANIES}_", ""]
    for c in companies:
        tier = f" (Tier {c['tier']})" if c.get("tier") is not None else ""
        lines += [f"### {_md(c['nazev'])}{tier}", ""]
        if c["produkty"]:
            lines += ["**Produkty**", ""]
            for p in c["produkty"]:
                lines += _md_product(p)
            lines.append("")
        if c["kampane"]:
            lines += ["**Kampaně**", ""]
            for k in c["kampane"]:
                lines += _md_campaign(k)
            lines.append("")
        if c["zpravy"]:
            lines += ["**Zprávy**", ""]
            lines += _md_news_groups(c["zpravy"], with_company=False)
            lines.append("")
        if c["mystery_shopping"]:
            lines += ["**Mystery shopping**", ""]
            for m in c["mystery_shopping"]:
                lines += _md_mystery(m)
            lines.append("")
    return lines


def _md_product(p: dict) -> list[str]:
    head = f"- **{PRODUCT_KINDS.get(p['druh'], p['druh'])}:** {_md_link(p['nazev'], p.get('url'))}"
    context = _product_context(p)
    if context:
        head += f" · {_md(context)}"
    if p["druh"] != "novy" and p.get("aktualizace"):
        head += f" · aktualizace {format_date_cz(p['aktualizace'])}"
    if p["druh"] == "aktualizace":
        head += " · bez zjištěné změny parametrů"
    lines = [head]
    if p.get("kratky_popis"):
        lines.append(f"  - {_md(p['kratky_popis'])}")
    if p["druh"] == "zmena":
        for z in p["zmeny"]:
            label, text = _change_text(z)
            lines.append(f"  - {_md(label)}: {_md(text)}")
    elif p["druh"] == "novy" and p.get("parametry"):
        for a in p["parametry"][:MAX_PARAMETERS]:
            label = a["name"] if not a.get("section") else f"{a['section']}: {a['name']}"
            lines.append(f"  - {_md(label)}: {_md(a.get('value') or '—')}")
        rest = len(p["parametry"]) - MAX_PARAMETERS
        if rest > 0:
            lines.append(f"  - … a {plural_cz(rest, 'další parametr', 'další parametry', 'dalších parametrů')}")
    return lines


def _md_campaign(k: dict) -> list[str]:
    head = f"- **{CAMPAIGN_KINDS.get(k['druh'], k['druh'])}:** {_md_link(k['nazev'], k.get('url'))}"
    if k.get("segment"):
        head += f" ({_md(k['segment']['nazev'])})"
    details = []
    if k.get("zacatek"):
        details.append(f"začátek {format_date_cz(k['zacatek'])}")
    if k.get("aktualizace") and k["druh"] == "aktualizovana":
        details.append(f"aktualizace {format_date_cz(k['aktualizace'])}")
    if k.get("media_typy"):
        details.append("média: " + ", ".join(k["media_typy"]))
    if k.get("typy_kampane"):
        details.append("typ: " + ", ".join(k["typy_kampane"]))
    if details:
        head += " · " + _md(" · ".join(details))
    lines = [head]
    if k.get("popis"):
        lines.append(f"  - {_md(k['popis'])}")
    kreativa = k.get("prvni_kreativa")
    if kreativa:
        text = kreativa.get("popis") or ("Video" if kreativa.get("media_druh") == "video" else "Kreativa")
        parts = [_creative_text(kreativa), _md_link(text, kreativa.get("media_url"))]
        line = "  - První kreativa: " + " · ".join(x for x in parts if x)
        if k.get("pocet_kreativ", 0) > 1:
            line += f" (celkem {plural_cz(k['pocet_kreativ'], 'kreativa', 'kreativy', 'kreativ')})"
        lines.append(line)
    elif k.get("kreativa_url"):
        lines.append(f"  - Klíčový vizuál: {k['kreativa_url']}")
    return lines


def _md_news_item(item: dict, with_company: bool) -> str:
    context = []
    if item.get("segment"):
        context.append(item["segment"]["nazev"])
    if with_company and item.get("spolecnost"):
        context.append(item["spolecnost"]["nazev"])
    line = f"  - {format_date_cz(item.get('datum'))} · {_md_link(item['nazev'], item.get('url'))}"
    if context:
        line += f" ({_md(' · '.join(context))})"
    if item.get("perex"):
        line += f" — {_md(item['perex'])}"
    return line


def _md_news_groups(groups: list[dict], with_company: bool) -> list[str]:
    lines = []
    for g in groups:
        lines.append(f"- {_md(g['typ'])}")
        lines += [_md_news_item(item, with_company) for item in g["polozky"]]
    return lines


def _md_mystery(m: dict) -> list[str]:
    line = f"- {format_date_cz(m.get('datum'))} · {_md_link(m['nazev'], m.get('url'))}"
    if m.get("segment"):
        line += f" ({_md(m['segment']['nazev'])})"
    line += f" · [PDF zpráva]({m['pdf_url']})" if m.get("pdf_url") else " · bez PDF"
    lines = [line]
    first = _first_paragraph(m.get("popis"))
    if first:
        lines.append(f"  - {_md(first)}")
    return lines


def _md_summaries(digest: dict) -> list[str]:
    lines = [f"## {SECTION_TITLES[2]}", ""]
    summaries = digest["executive_summary"]
    if not summaries:
        return lines + [f"_{EMPTY_SUMMARIES}_", ""]
    for s in summaries:
        segment = s["segment"]["nazev"] if s.get("segment") else "—"
        lines += [f"### {_md(segment)} · {_md(s['nazev'])}", ""]
        if not s["polozky"]:
            lines.append("- _bez položek_")
        for e in s["polozky"]:
            text = f"- **{_md(e.get('nazev') or '—')}**"
            if e.get("text"):
                text += f" — {_md(e['text'])}"
            if e.get("url"):
                text += f" ([odkaz]({e['url']}))"
            lines.append(text)
        if s.get("pdf_url"):
            lines.append(f"- [PDF]({s['pdf_url']})")
        lines.append("")
    return lines


def _md_market(digest: dict) -> list[str]:
    lines = [f"## {SECTION_TITLES[3]}", ""]
    if not digest["trh"]:
        return lines + [f"_{EMPTY_MARKET}_", ""]
    lines += _md_news_groups(digest["trh"], with_company=True)
    lines.append("")
    return lines


# ── HTML ─────────────────────────────────────────────────────────

_CSS = """
body{margin:0;background:#f4f4f5;color:#1e293b;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;line-height:1.5}
main{max-width:960px;margin:0 auto;padding:32px 28px 48px;background:#fff}
h1{font-size:1.6rem;margin:0 0 4px;letter-spacing:-.01em}
.meta{color:#64748b;font-size:.85rem;margin:0 0 24px}
h2{font-size:1.15rem;margin:36px 0 12px;padding-bottom:4px;border-bottom:2px solid #fee600}
h3{font-size:1rem;margin:24px 0 8px}
h4{font-size:.72rem;text-transform:uppercase;letter-spacing:.12em;color:#64748b;margin:14px 0 6px}
table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{padding:6px 8px;border-bottom:1px solid #e2e8f0;text-align:left;vertical-align:top}
th{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:#64748b}
.n{text-align:right;font-variant-numeric:tabular-nums}
.tier{display:inline-block;padding:0 6px;border-radius:4px;font-size:.72rem;font-weight:700;border:1px solid #e2e8f0;color:#475569}
.tier-1{color:#dc2626;border-color:#fecaca;background:#fef2f2}
.tier-2{color:#2563eb;border-color:#bfdbfe;background:#eff6ff}
ul{margin:4px 0 8px;padding-left:20px}
li{margin:3px 0}
li ul{margin:2px 0 4px}
.muted{color:#64748b;font-size:.85rem}
.kind{font-weight:700}
.kind-novy,.kind-nova{color:#047857}
.kind-zmena{color:#b45309}
.kind-aktualizace,.kind-aktualizovana{color:#2563eb}
.old{color:#94a3b8;text-decoration:line-through}
.empty{color:#94a3b8;font-style:italic}
.totals{font-size:.85rem;color:#475569;margin-top:8px}
.chip{display:inline-block;padding:0 6px;border-radius:4px;background:#fff7cc;font-size:.72rem;font-weight:700;margin-right:4px}
a{color:#1d4ed8;text-decoration:none}
a:hover{text-decoration:underline}
@media print{body{background:#fff}main{padding:0}h2{break-after:avoid}}
"""


def _h(text) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def _h_link(text, url: str | None) -> str:
    if not url:
        return _h(text)
    return f'<a href="{_h(url)}" target="_blank" rel="noopener noreferrer">{_h(text)}</a>'


def _h_tier(tier) -> str:
    if tier is None:
        return '<span class="tier">—</span>'
    return f'<span class="tier tier-{_h(tier)}">Tier {_h(tier)}</span>'


def render_html(digest: dict) -> str:
    p = digest["period"]
    title = f"{p['nazev']} konkurence: {p['popis']}"
    out = [
        "<!doctype html>",
        '<html lang="cs">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_h(title)}</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        "<main>",
        f"<h1>{_h(title)}</h1>",
        '<p class="meta">'
        f"Období: {_h(format_date_cz(p['od']))} – {_h(format_date_cz(p['do']))} ({_h(PERIOD_ADJECTIVES[p['typ']])})"
        f" · Segmenty: {_h(_segments_label(digest))}"
        f" · Vygenerováno: {_h(_datetime_cz(digest.get('vygenerovano')))}"
        "</p>",
    ]
    if digest.get("prazdny"):
        out.append(f'<p class="empty">{_h(EMPTY_ALL)}</p>')
    out += _html_numbers(digest)
    out += _html_companies(digest)
    out += _html_summaries(digest)
    out += _html_market(digest)
    out += ["</main>", "</body>", "</html>"]
    return "\n".join(out) + "\n"


def _html_numbers(digest: dict) -> list[str]:
    out = [f"<section><h2>{_h(SECTION_TITLES[0])}</h2>"]
    companies = digest["spolecnosti"]
    if not companies:
        out.append(f'<p class="empty">{_h(EMPTY_COMPANIES)}</p>')
    else:
        out += [
            "<table>",
            "<thead><tr><th>Společnost</th><th>Tier</th>"
            '<th class="n">Články</th><th class="n">Kampaně</th><th class="n">Produkty</th>'
            '<th class="n">Mystery shopping</th></tr></thead>',
            "<tbody>",
        ]
        for c in companies:
            n = c["pocty"]
            out.append(
                f'<tr><td><a href="#spolecnost-{_h(c["id"])}">{_h(c["nazev"])}</a></td>'
                f"<td>{_h_tier(c.get('tier'))}</td>"
                f'<td class="n">{n["clanky"]}</td><td class="n">{n["kampane"]}</td>'
                f'<td class="n">{n["produkty"]}</td><td class="n">{n["mystery_shopping"]}</td></tr>'
            )
        out += ["</tbody>", "</table>"]
    out += [f'<p class="totals">Celkem: {_h(_totals_label(digest))}</p>', "</section>"]
    return out


def _html_companies(digest: dict) -> list[str]:
    out = [f"<section><h2>{_h(SECTION_TITLES[1])}</h2>"]
    companies = digest["spolecnosti"]
    if not companies:
        return out + [f'<p class="empty">{_h(EMPTY_COMPANIES)}</p>', "</section>"]
    for c in companies:
        out.append(f'<h3 id="spolecnost-{_h(c["id"])}">{_h(c["nazev"])} {_h_tier(c.get("tier"))}</h3>')
        if c["produkty"]:
            out.append("<h4>Produkty</h4><ul>")
            out += [_html_product(p) for p in c["produkty"]]
            out.append("</ul>")
        if c["kampane"]:
            out.append("<h4>Kampaně</h4><ul>")
            out += [_html_campaign(k) for k in c["kampane"]]
            out.append("</ul>")
        if c["zpravy"]:
            out.append("<h4>Zprávy</h4>")
            out += _html_news_groups(c["zpravy"], with_company=False)
        if c["mystery_shopping"]:
            out.append("<h4>Mystery shopping</h4><ul>")
            out += [_html_mystery(m) for m in c["mystery_shopping"]]
            out.append("</ul>")
    out.append("</section>")
    return out


def _html_product(p: dict) -> str:
    kind = PRODUCT_KINDS.get(p["druh"], p["druh"])
    parts = [f'<span class="kind kind-{_h(p["druh"])}">{_h(kind)}:</span> {_h_link(p["nazev"], p.get("url"))}']
    context = _product_context(p)
    if context:
        parts.append(f'<span class="muted">{_h(context)}</span>')
    if p["druh"] != "novy" and p.get("aktualizace"):
        parts.append(f'<span class="muted">aktualizace {_h(format_date_cz(p["aktualizace"]))}</span>')
    if p["druh"] == "aktualizace":
        parts.append('<span class="muted">bez zjištěné změny parametrů</span>')
    out = [" · ".join(parts)]
    sub = []
    if p.get("kratky_popis"):
        sub.append(f"<li>{_h(p['kratky_popis'])}</li>")
    if p["druh"] == "zmena":
        for z in p["zmeny"]:
            label, _ = _change_text(z)
            if z["druh"] == "pridano":
                detail = f"nově <strong>{_h(z.get('nova') or '—')}</strong>"
            elif z["druh"] == "odebrano":
                detail = f'odebráno (dříve <span class="old">{_h(z.get("stara") or "—")}</span>)'
            else:
                detail = f'<span class="old">{_h(z.get("stara") or "—")}</span> → <strong>{_h(z.get("nova") or "—")}</strong>'
            sub.append(f"<li>{_h(label)}: {detail}</li>")
    elif p["druh"] == "novy" and p.get("parametry"):
        for a in p["parametry"][:MAX_PARAMETERS]:
            label = a["name"] if not a.get("section") else f"{a['section']}: {a['name']}"
            sub.append(f"<li>{_h(label)}: {_h(a.get('value') or '—')}</li>")
        rest = len(p["parametry"]) - MAX_PARAMETERS
        if rest > 0:
            sub.append(f'<li class="muted">… a {_h(plural_cz(rest, "další parametr", "další parametry", "dalších parametrů"))}</li>')
    if sub:
        out.append("<ul>" + "".join(sub) + "</ul>")
    return "<li>" + "".join(out) + "</li>"


def _html_campaign(k: dict) -> str:
    kind = CAMPAIGN_KINDS.get(k["druh"], k["druh"])
    head = f'<span class="kind kind-{_h(k["druh"])}">{_h(kind)}:</span> {_h_link(k["nazev"], k.get("url"))}'
    if k.get("segment"):
        head += f' <span class="muted">({_h(k["segment"]["nazev"])})</span>'
    details = []
    if k.get("zacatek"):
        details.append(f"začátek {format_date_cz(k['zacatek'])}")
    if k.get("aktualizace") and k["druh"] == "aktualizovana":
        details.append(f"aktualizace {format_date_cz(k['aktualizace'])}")
    if k.get("typy_kampane"):
        details.append("typ: " + ", ".join(k["typy_kampane"]))
    if details:
        head += f' · <span class="muted">{_h(" · ".join(details))}</span>'
    if k.get("media_typy"):
        head += " " + "".join(f'<span class="chip">{_h(m)}</span>' for m in k["media_typy"])
    sub = []
    if k.get("popis"):
        sub.append(f"<li>{_h(k['popis'])}</li>")
    kreativa = k.get("prvni_kreativa")
    if kreativa:
        text = kreativa.get("popis") or ("Video" if kreativa.get("media_druh") == "video" else "Kreativa")
        parts = [_h(_creative_text(kreativa)), _h_link(text, kreativa.get("media_url"))]
        line = "První kreativa: " + " · ".join(x for x in parts if x)
        if k.get("pocet_kreativ", 0) > 1:
            line += f' <span class="muted">(celkem {_h(plural_cz(k["pocet_kreativ"], "kreativa", "kreativy", "kreativ"))})</span>'
        sub.append(f"<li>{line}</li>")
    elif k.get("kreativa_url"):
        sub.append(f"<li>{_h_link('Klíčový vizuál', k['kreativa_url'])}</li>")
    body = head + ("<ul>" + "".join(sub) + "</ul>" if sub else "")
    return f"<li>{body}</li>"


def _html_news_item(item: dict, with_company: bool) -> str:
    context = []
    if item.get("segment"):
        context.append(item["segment"]["nazev"])
    if with_company and item.get("spolecnost"):
        context.append(item["spolecnost"]["nazev"])
    line = f'<span class="muted">{_h(format_date_cz(item.get("datum")))}</span> · {_h_link(item["nazev"], item.get("url"))}'
    if context:
        line += f' <span class="muted">({_h(" · ".join(context))})</span>'
    if item.get("perex"):
        line += f' — <span class="muted">{_h(item["perex"])}</span>'
    return f"<li>{line}</li>"


def _html_news_groups(groups: list[dict], with_company: bool) -> list[str]:
    out = ["<ul>"]
    for g in groups:
        out.append(f"<li><strong>{_h(g['typ'])}</strong><ul>")
        out += [_html_news_item(item, with_company) for item in g["polozky"]]
        out.append("</ul></li>")
    out.append("</ul>")
    return out


def _html_mystery(m: dict) -> str:
    line = f'<span class="muted">{_h(format_date_cz(m.get("datum")))}</span> · {_h_link(m["nazev"], m.get("url"))}'
    if m.get("segment"):
        line += f' <span class="muted">({_h(m["segment"]["nazev"])})</span>'
    line += " · " + (_h_link("PDF zpráva", m["pdf_url"]) if m.get("pdf_url") else '<span class="muted">bez PDF</span>')
    first = _first_paragraph(m.get("popis"))
    if first:
        line += f"<ul><li>{_h(first)}</li></ul>"
    return f"<li>{line}</li>"


def _html_summaries(digest: dict) -> list[str]:
    out = [f"<section><h2>{_h(SECTION_TITLES[2])}</h2>"]
    summaries = digest["executive_summary"]
    if not summaries:
        return out + [f'<p class="empty">{_h(EMPTY_SUMMARIES)}</p>', "</section>"]
    for s in summaries:
        segment = s["segment"]["nazev"] if s.get("segment") else "—"
        out.append(f"<h3>{_h(segment)} · {_h(s['nazev'])}</h3><ul>")
        if not s["polozky"]:
            out.append('<li class="empty">bez položek</li>')
        for e in s["polozky"]:
            text = f"<strong>{_h(e.get('nazev') or '—')}</strong>"
            if e.get("text"):
                text += f" — {_h(e['text'])}"
            if e.get("url"):
                text += f" ({_h_link('odkaz', e['url'])})"
            out.append(f"<li>{text}</li>")
        if s.get("pdf_url"):
            out.append(f"<li>{_h_link('PDF', s['pdf_url'])}</li>")
        out.append("</ul>")
    out.append("</section>")
    return out


def _html_market(digest: dict) -> list[str]:
    out = [f"<section><h2>{_h(SECTION_TITLES[3])}</h2>"]
    if not digest["trh"]:
        return out + [f'<p class="empty">{_h(EMPTY_MARKET)}</p>', "</section>"]
    out += _html_news_groups(digest["trh"], with_company=True)
    out.append("</section>")
    return out


# ── files ────────────────────────────────────────────────────────

RENDERERS = {"md": render_markdown, "html": render_html}


def digest_filename(digest: dict, ext: str) -> str:
    """``digest-weekly-2026-11-06.md``; with a segment filter ``digest-weekly-2026-11-06-ucty+hypoteky.md``."""
    period = digest["period"]
    slugs = digest.get("filtr_segmentu") or []
    suffix = "-" + "+".join(slugs) if slugs else ""
    return f"digest-{period['typ']}-{period['do']}{suffix}.{ext}"


def write_digest(digest: dict, output_dir: str | Path, formats: Iterable[str] = ("md",)) -> list[Path]:
    """Write the digest in each format (``md``, ``html``; ``both`` = the two) into
    ``output_dir`` (created when missing). Returns the written paths in that order."""
    wanted: list[str] = []
    for fmt in formats:
        for one in (FORMATS if fmt == "both" else (fmt,)):
            if one not in RENDERERS:
                raise ValueError(f"Neznámý formát: {fmt!r} (podporováno: md, html, both)")
            if one not in wanted:
                wanted.append(one)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for fmt in wanted:
        path = out_dir / digest_filename(digest, fmt)
        path.write_text(RENDERERS[fmt](digest), encoding="utf-8")
        paths.append(path)
    return paths


__all__ = [
    "digest_filename",
    "plural_cz",
    "render_html",
    "render_markdown",
    "write_digest",
]
