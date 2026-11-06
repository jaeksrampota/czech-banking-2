# Competitor digest: user guide

The digest is a readable weekly or monthly summary of what the FINeCIM scraper stored
(`clanky`, `kampane` + `kampane_kreativy`, `produkty`, `mystery_shopping`,
`executive_summary` + `executive_summary_polozky`), ordered by competitor tier. It is
the first step towards the automatic strategic reports: the same content is available as
Markdown and HTML files (`ci-monitor digest`), as JSON (`GET /api/digest`) and as the
"Digest" page of the dashboard. Code: `src/digest/` (`build.py` = data, `render.py` =
Markdown/HTML), tests: `tests/test_digest.py`.

All commands can be run as `ci-monitor ...` (installed entry point) or
`python -m src.cli ...` from the repository root.

## 1. Generating a digest

```bash
python -m src.cli digest                                   # weekly, ending today, Markdown
python -m src.cli digest --period monthly --format both    # one month ending today, .md + .html
python -m src.cli digest --period weekly --until 2026-11-06 --segment ucty --segment hypoteky
python -m src.cli digest -p weekly -f html -o C:\reports   # into another directory
```

| option | meaning |
|---|---|
| `--period/-p` | `weekly` (default): the 7 days ending at `--until`; `monthly`: one calendar month ending at `--until` (`2026-11-06` → 7. 10. – 6. 11. 2026). Both ends are inclusive |
| `--until` | last day of the period, `YYYY-MM-DD`; default today |
| `--segment/-s` | segment slug (`ucty`, `sporeni`, `uvery`, `hypoteky`, `investice`, `bankovni-trh`, `fintech`, `bankopojisteni`, `stavebni-sporitelny`, `penzijni-spolecnosti`); repeatable, default all |
| `--format/-f` | `md` (default), `html` or `both` |
| `--output/-o` | output directory, created when missing; default `data/digests/` (git-ignored) |

The command prints the headline counts and the written paths. Files are named
`digest-<period>-<until>.md` / `.html`, with the segment slugs appended when filtered
(`digest-weekly-2026-11-06-ucty+hypoteky.md`). An unknown segment or an invalid date
exits with code 1 and a message.

The digest only reads the database; run `finecim sync` first (see `SCRAPER.md`). It needs
no credentials and makes no request.

## 2. What is in it

Headings and labels are Czech, like the data. Four sections, always in this order:

1. **Čísla za období** – one row per competitor with items in the period: articles,
   campaigns started or updated, product changes, mystery-shopping reports; tier 1 first,
   then tier 2 and 3, each tier by name; FINeCIM items without a company come last as
   "FINeCIM (nepřiřazeno)". Followed by the totals.
2. **Co je nové** – per competitor, in the same order:
   * *Produkty* – `Nový produkt` (first stored in the period, with its parameters),
     `Změna parametrů` (the diff of `produkty.atributy` against the previous stored
     version: changed values `old → new`, added and removed parameters), or
     `Aktualizace` (FINeCIM shows an update date in the period but no parameter change
     could be found, typically because no earlier version is stored yet).
   * *Kampaně* – `Nová kampaň` (started in the period) or `Aktualizovaná kampaň`
     (updated in the period), with media types, campaign type, annotation and the first
     creative (the earliest one) plus the total number of creatives.
   * *Zprávy* – articles of the period grouped by their primary `typ_zpravy`
     (an article with "produkty a služby, tiskové zprávy" is listed under "produkty a
     služby"; articles without a type under "ostatní").
   * *Mystery shopping* – reports dated in the period with the PDF link (`pdf_url`, or
     the first attached PDF).
3. **Executive summary** – the monthly editorial summaries whose month overlaps the
   period (a weekly digest that spans a month end shows both months), per domain, with
   their entries and links.
4. **Bankovní trh a nezařazené zprávy** – market-level news: articles without a
   competitor and every article of the "Bankovní trh" domain (those are not repeated
   under the competitor; the company is shown next to the item instead).

An empty period renders every section with a short note instead of items.

### Which rows fall into a period

| content | date used |
|---|---|
| articles | `clanky.datum` |
| campaigns | `kampane.zacatek` (started) or `kampane.aktualizace` (updated); `pridano_at` when both are empty |
| products | `produkty.aktualizace`, else the date the row was first stored (`pridano_at`); also a product with a newer parameter version stored in the period |
| mystery shopping | `mystery_shopping.datum` |
| executive summary | the summary's month (`rok`, `mesic`) overlaps the period |

**Product versions.** `Database.upsert_produkt()` keeps a history of the parameters in
`produkty_verze` (one row per distinct `atributy`, with the FINeCIM update date and the
time it was stored). The digest diffs the latest version against the last one stored
before the period (or, when there is none, the oldest one). A database filled before
this table existed has one version per product after the next sync, so the first digest
after that shows `Aktualizace` without a diff; the diffs appear from the second change
on. The first digest after a backfill lists every freshly scraped product as new, since
the scraper has no earlier date for them.

**Ordering is pluggable.** `build_digest(db, period, segments, rank_key=...)` sorts
competitors by `rank_key` (default `rank_by_tier`: tier, then name). When the threat
criteria are defined, a scoring function can replace it without touching the renderers.

## 3. API and dashboard

`GET /api/digest?period=weekly|monthly&until=YYYY-MM-DD[&segment=slug]...[&format=json|md|html]`

* `period` defaults to `weekly`, `until` to today, `segment` is repeatable.
* `format=json` (default) returns the digest dict that the renderers use (Czech keys:
  `period`, `souhrn`, `spolecnosti[]` with `pocty`, `produkty`, `kampane`, `zpravy`,
  `mystery_shopping`, then `executive_summary[]` and `trh[]`); `format=md` returns
  `text/markdown`, `format=html` the standalone page.
* Invalid period, date, format or segment answer `400` with the message.
* The route honours `CI_MONITOR_API_KEY` like every other `/api/` route.

The dashboard page **Digest** (sidebar) renders the JSON with the same four sections:
a week/month toggle, the end date, a segment filter and `MD` / `HTML` download buttons
(the API URLs with `format=`). The headline table links to each competitor's block.

## 4. Scheduling

The digest is not scheduled yet. For a weekly report run the command from a scheduler
after the daily `finecim sync` (for example every Monday with `--period weekly`, and on
the first day of the month with `--period monthly`); each run overwrites the file of the
same period and end date in `data/digests/`.
