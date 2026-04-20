# FINeCIM — Product Teardown

Research notes from a logged-in walkthrough of https://www.finecim.cz (April 2026).
Written as a reference for turning `czech-banking-2` into a FINeCIM-equivalent.

**Published by:** Market Vision s.r.o.
**Tagline:** "financial market monitor"
**Positioning:** continuous competitive intelligence for the Czech financial-services market — serves bank/insurance/pension-co employees (users log in with their employer email, e.g. `@rb.cz`).

---

## 1. Information architecture (big picture)

Two-level navigation:

**Left sidebar — domains (market segments):**

| Segment | URL slug |
|---|---|
| Hlavní stránka (Home) | `/cz/` |
| Účty (Accounts) | `/cz/domena/ucty/` |
| Spoření (Savings) | `/cz/domena/spoeni/` (to confirm) |
| Úvěry (Loans) | `/cz/domena/uvery/` |
| Hypotéky (Mortgages) | `/cz/domena/hypoteky/` |
| Investice (Investments) | `/cz/domena/investice/` |
| Bankovní trh (Banking market) | `/cz/domena/bankovni-trh/` |
| FinTech | `/cz/domena/fintech/` |
| Bankopojištění (Bancassurance) | `/cz/domena/bankopojisteni/` |
| Stavební spořitelny (Building societies) | `/cz/domena/stavebni-sporitelny/` |
| Penzijní společnosti (Pension cos.) | `/cz/domena/penzijni-spolecnosti/` |

**Per-segment sub-tabs (product segments):**

Full set (Účty, Spoření, Úvěry, Hypotéky, Investice):
`Novinky | Společnosti | Produkty | Srovnání | Zprávy | Kampaně | Mystery Shopping | Executive Summary`

Reduced set (Bankovní trh, FinTech, Bankopojištění, Stavební spořitelny, Penzijní společnosti):
`Novinky | Společnosti | Zprávy | Kampaně | Mystery Shopping | Executive Summary`
*(no Produkty / Srovnání — these are cross-market or meta segments)*

**Top-right utility bar:**
- Vyhledávání (Search) — `/cz/search/`, full-text + link to "rozšířené vyhledávání"
- Oblíbené (Favorites) — `/cz/favorite/`
- Přečíst později (Read later) — `/cz/read-later/`
- Early warnings — `/cz/visitors/early-warnings` (saved filters + email alerts)
- User menu (name shown, e.g. "Jakub Schrimpel")

---

## 2. Core entities (observed)

### 2.1 Segment (doména)
A macro product family (Účty, Hypotéky, Investice, …). Each segment has its own landing page, news feed, company list, product catalog, and executive summary archive.

### 2.2 Company (Společnost / Subjekt)
URL pattern: `/cz/domena/<segment>/subjekt/<id>` — e.g. `subjekt/11` = Česká spořitelna.

Observed fields on the detail page:
- Name + logo
- `Datum aktualizace` (last profile update)
- Short narrative description (parent group, group structure, subsidiaries)
- Social links: Facebook, Instagram, X, LinkedIn, YouTube, Website
- **Základní informace o společnosti:**
  - Obchodní firma (legal name)
  - Identifikační číslo (IČO)
  - Sídlo (HQ address)
  - Základní kapitál (share capital)
  - Akcionář (shareholder)
  - Představenstvo (board, with roles: předseda / místopředseda / člen)
- Three headline KPIs: number of clients, branches, ATMs
- **PŘÍLOHY** — annual report PDFs, year by year (2010 → 2024 observed)
- Right rail:
  - Související zprávy (related news)
  - Související kampaně (related campaigns)
  - Související Mystery Shopping

### 2.3 Product (Produkt)
Each product appears as a card with:
- Product name (e.g. "OPEN Young", "mKonto")
- Company logo
- `Produktová linie` (product line, e.g. "Běžné účty")
- `Segment` (customer segment: "Fyzické osoby" / "FOP a firmy")
- Short description (1–2 sentences)

Product line taxonomy seen in filters / Early-warning setup:
`Americké hypotéky, Běžné účty, Cestovní pojištění – dlouhodobé, Cestovní pojištění – krátkodobé, Debetní karty, Hypotéky, Investiční fondy, Investiční platformy, Konsolidace, Kontokorenty, Kreditní karty, Mikropůjčky, Mobilní aplikace, Nákup na splátky, Penzijní spoření, Pojištění pravidelných plateb, Pojištění schopnosti splácet k hypotékám…`

Segments: `Fyzické osoby` (individuals), `FOP a firmy` (self-employed + companies).

### 2.4 News / Zpráva
URL pattern: `/cz/domena/<segment>/news/<id>` — e.g. `news/42452`.

Fields:
- Title
- Status badge: `new` / `updated`
- Date (DD.MM.YYYY)
- `Typ zprávy` (report type) — e.g. "produkty a služby"
- Lead paragraph
- Body (rich): can embed **Google Play** and **App Store** "What's new" excerpts with source attribution (`Zdroj: Google Play, DD. měsíc YYYY`)
- **GALERIE** — screenshot gallery from the actual product (in-app screens)
- Tags (e.g. `mobilní bankovnictví`, `Market Vision`, author name like `Kučera Petr`)
- Actions: star (save to favorites), envelope (share / read-later?), **Exportuj** button
- Right rail: Mohlo by Vás také zajímat (related articles), Související společnosti, Související produkty

### 2.5 Campaign (Kampaň)
URL pattern: `/cz/domena/<segment>/campaign` list.

Card fields:
- Campaign creative thumbnail
- Company logo
- Campaign title
- `začátek` (start date)
- `aktualizace` (update date — when the campaign was re-tagged/refreshed)
- Short description
- **Media-type badges:** `TV`, `Outdoor`, `Web` (observed — likely also Print, Social, Radio)

List filters: od/do, segment, společnost, produktová linie, **media typ**, **typ kampaně**.

### 2.6 Mystery Shopping
Top banner: the content is produced "by Market Vision agency exclusively for FINeCIM users."

Card fields:
- Title (what was tested — e.g. "Online sjednání bankovního účtu u mBank")
- Date
- Narrative description (1 paragraph — how it went, pain points, verdict)
- PDF attachment (linked from description: "více se dozvíte v přiloženém PDF souboru")

These are field trips: a Market Vision tester opens an account / applies for a card / uses a feature at a competitor and writes up the journey. This is the highest-value, most-differentiating content on FINeCIM — it cannot be scraped, it's human research.

Observed titles span: online account opening, card sign-up, AI chatbot tests, referral-bonus flows, in-app surveys, etc.

### 2.7 Executive Summary
URL: `/cz/domena/<segment>/executive-summary`.

Archive layout: accordion by year (2020 → 2025), each year expands to a month grid (leden … prosinec). Each month opens a monthly executive digest for that segment.

### 2.8 Analýza / Report (Zprávy standalone)
Listed on home-page rightbar and segment rightbar. Example titles seen:
- "Přehled aktualizací mobilních aplikací za rok 2026" (annual mobile-app update log)
- "Analýza sociálních sítí — březen 2026" (social-media monthly, "data presented via Power BI dashboards")
- "Přehled změn úrokových lístků za rok 2025" (rate-sheet change log, per segment)
- "Online distribuce produktů na tuzemském bankovním trhu" (digital distribution analysis)
- "Žebříček podílových fondů na Finparádě za měsíc…" (mutual-fund league table)

So there's a recurring editorial calendar: weekly summaries, monthly social-media analyses, quarterly rate-sheet roundups, yearly overviews.

### 2.9 Srovnání (Comparison wizard)
URL: `/cz/domena/<segment>/porovnanie-produktov`.

4-step wizard:
1. **Výběr produktové linie** — filters: produktová linie, segmenty, společnosti.
2. **Výběr konkrétních produktů** — checkbox list grouped by company (each bank's products shown as checkboxes; "Označit vše / Odznačit vše" toggle).
3. **Výběr parametrů pro porovnání** — choose which attributes to compare.
4. **Výstup - tabulka** — side-by-side comparison table.

So every product has a structured attribute schema that makes table-based comparison possible.

---

## 3. Companies covered (Účty list, non-exhaustive)

~24 entities on the Účty → Společnosti grid, including:

**Czech universals:** Česká spořitelna, ČSOB, Komerční banka, Raiffeisenbank, UniCredit Bank, MONETA Money Bank, Fio banka, Air Bank, mBank.
**Challengers / regional / digital:** Banka CREDITAS (+ Divize Max), Partners Banka, Trinity Bank, J&T BANKA, ERB bank, Citibank, Oberbank, Artesa spořitelní družstvo, Volksbank Raiffeisenbank Nordoberpfalz, ČSOB Poštovní spořitelna.
**Fintech / foreign:** Revolut.
**Meta entries:** ČNB (regulator), ČBA (bankers' association), Bankovní trh (aggregate), Market Vision – bankovní trh (editorial), Zahraniční trhy (foreign markets).

Early-warning company picker confirms a much wider list across all segments, including: Akcenta, AKRO investiční společnost, Alipay, Allianz penzijní společnost, Amundi investiční společnost, Apple Pay, AvaFin, Avant, BNP Paribas (+ Cardif Pojišťovna), Broker Consulting, bunq, Česká spořitelna – penzijní společnost, ClearBank, Cofidis, Conseq Investment Management, Direct Fondee, …

**Implication:** FINeCIM tracks ~50+ institutions across banking, fintech, pensions, insurance, investment, payments.

---

## 4. Filtering model (cross-cutting)

Filter bar on every list page:
- `od` / `do` — date range
- `segment` — Fyzické osoby / FOP a firmy
- `společnost` — company multi-select
- `produktová linie` — product-line multi-select
- On Kampaně: adds `media typ` + `typ kampaně`
- On Zprávy: adds `typ zprávy`
- Reset / Filtruj buttons

Home feed also has tab filters above the list: `vše | kampaně | zprávy | produkt | mystery shopping | executive summary`.

---

## 5. Early warnings (personalization)

Per-user saved filters with email cadence control.

**Filter builder fields:**
- od/do, Vyberte oblast (segment)
- Produktová linie (checkboxes of all product lines)
- Segment (Fyzické osoby / FOP a firmy)
- Produkty (dependent on product-line selection)
- Společnosti (checkbox list of every tracked entity)
- `typ obsahu` (content type): zprávy / kampaně / produkt / mystery shopping
- Název filtru (filter name)
- Frequency: "nezasílat" (don't send) + other cadences (daily/weekly presumed)
- "Uložit filtr a nastavit zasílání"

---

## 6. What FINeCIM does vs. what `czech-banking-2` currently does

| Capability | FINeCIM | czech-banking-2 today |
|---|---|---|
| Segment taxonomy (Účty/Hypotéky/…) | 11 domains, curated | Single flat signal list |
| Company coverage | ~50+ across banking/fintech/insurance/pension/investment/payments | 11 banks |
| Product catalog (named products + attributes) | Yes, with product lines | No |
| Structured side-by-side product comparison (Srovnání) | 4-step wizard → attribute table | No |
| News feed with editorial tagging | Yes (typ zprávy, product line, tags, author) | Yes (RSS scrape, auto tags) |
| Ad-campaign monitoring (TV/Outdoor/Web) | Yes — creatives, start/update dates, media type | No |
| Mystery Shopping reports | Yes — human field tests, PDF writeups | No |
| Executive Summaries (monthly, per segment) | Yes — archive from 2020 | No |
| Recurring analyses (rate sheets, social-media, app-update logs) | Yes | No |
| Gallery of in-app screenshots per news item | Yes | No |
| Company profile with IČO/board/capital/branches/ATMs + annual reports | Yes | Partial (ARES collector captures registry fields) |
| Saved searches + email alerts | Yes (Early warnings) | No |
| Favorites / Read-later per user | Yes | No |
| Full-text search + advanced search | Yes | Partial (DB query, no FTS) |
| Multi-tenant users (e.g. Raiffeisenbank seats) | Yes (logged-in users from banks) | No auth |
| Export (per article + XLSX bulk) | Per-item Exportuj button | XLSX bulk |

---

## 7. Proposed mapping to current data model

Current: single `signals` table. FINeCIM pattern is richer — treat a signal as one of several typed entities:

```
Segment          (id, name, slug)
Company          (id, name, parent_group, tier, ico, description, capital,
                  hq_address, shareholder, clients, branches, atms,
                  social_links, last_updated)
CompanyOfficer   (company_id, name, role)   -- board + supervisory
ProductLine      (id, segment_id, name)     -- e.g. Běžné účty
Product          (id, company_id, product_line_id, customer_segment,
                  name, short_description, attributes_json)
Article          (id, company_id, segment_id, product_ids[],
                  title, date, report_type, tags[], body_md, source,
                  gallery_image_urls[], play_store_excerpt, app_store_excerpt)
Campaign         (id, company_id, segment_id, title, start_date, updated_date,
                  description, media_types[], campaign_type, creative_url)
MysteryShop      (id, company_id, segment_id, title, date, description,
                  pdf_url, tester, outcome)
ExecSummary      (id, segment_id, year, month, body, attachment_url)
Analysis         (id, segment_id, title, date, analysis_type, body, files[])
SavedFilter      (id, user_id, name, filter_json, cadence)
UserFavorite     (user_id, entity_type, entity_id)
UserReadLater    (user_id, entity_type, entity_id, marked_at)
```

Current `Signal` generalizes across these types. Two paths:

**A.** Keep `signals` as the fact table, add `entity_type` + per-type detail tables for rich display.
**B.** Migrate to typed tables and drop the generic Signal model.

Recommend **A** for now — preserves collector output while layering the editorial taxonomy on top.

---

## 8. Gaps that matter most (and are realistic to build)

Ordered by ROI:

1. **Segment/domain model + per-segment landing pages** — structural, low-risk.
2. **Product catalog + product-line taxonomy** — unlocks comparison later.
3. **Ad-campaign collector** — new collector scraping Google Search Ads / SpotX / TV monitoring RSS / bank YouTube channels; cards with media-type badges.
4. **Saved searches + email alerts (Early warnings-lite)** — persist filters, send digests.
5. **Executive summaries** — auto-generate monthly markdown per segment from collected signals.
6. **Favorites / Read-later** — small UX wins.
7. **In-app screenshot gallery on articles** — needs a playwright-driven screenshot collector per app URL.
8. **Srovnání (product comparison table)** — needs the Product attribute schema; hardest item.
9. **Mystery Shopping** — fundamentally human work; system role is only to store & surface PDFs and tag them.

Not worth chasing without resources: the human mystery-shopping + editorial analysis content. That's a services moat, not a software one.

---

## 9. Screenshots

Saved to the browser-tool default screenshot dir (not under this repo). Referenced IDs from this session: `ss_0411n0foi` (home), `ss_1350ntedy` (Účty/Společnosti grid), `ss_5565wsnxa` (ČS profile), `ss_0874clrk2` (Účty/Produkty), `ss_75799o2f3` (Srovnání step 1), `ss_4472ncrso` (Srovnání step 2), `ss_5914l96x9` (Účty/Zprávy), `ss_78097301l` (Účty/Kampaně), `ss_917095dyf` (Účty/Mystery Shopping), `ss_0657ikwdc` (Exec Summary archive), `ss_4857sil4z` (Hypotéky), `ss_9458duvgz` (Bankovní trh), `ss_2478wsydz` (FinTech), `ss_52473gl02` (Early warnings landing), `ss_61153wqdr` (filter builder top), `ss_00893hqbn` (filter builder bottom), `ss_58194c7oi` (search), `ss_8664tn95k` (article detail top), `ss_2920zit0u` (article detail body + gallery).

---

## 10. Open questions (decide before coding)

1. **Scope v1:** mirror all 11 segments, or start with 3 (Účty, Hypotéky, Investice)?
2. **Companies:** expand from 11 → ~50 now, or incrementally?
3. **Campaign data source:** scraping Youtube/ad galleries is scrappy — do we have access to a real ad-intelligence feed, or do we start with a manual table?
4. **Multi-user auth:** needed for favorites + early warnings. Add Flask-Login + SQLite `users` table, or punt and keep single-user local?
5. **Czech/English UX:** keep Czech labels like FINeCIM does? (Yes, domain terms are Czech-specific.)
6. **Legal:** FINeCIM is a commercial product with terms of service — we're building our own tool, not redistributing theirs. Screenshot references are for internal planning only.
