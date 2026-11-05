# FINeCIM scraper — design (2026-11-05)

Goal: fill the FINeCIM-shaped tables that already exist in `src/models/schema.sql`
(`segmenty`, `produktove_linie`, `spolecnost_detail`, `produkty`, `clanky`, `kampane`,
`mystery_shopping`, `executive_summary`) from the logged-in FINeCIM site, incrementally
and politely, so the dashboard (`src/api.py` → `dashboard/`) shows real content.

Everything below was verified against the live site on 2026-11-05 from a logged-in
session. Trimmed copies of every page type are in `tests/fixtures/finecim/`.

## 1. The site

* Nette Framework 3 app at `https://www.finecim.cz`, server-rendered HTML, bootstrap
  "Metronic" markup (`kt-*` classes) plus app classes (`ecim-*`). `robots.txt` is
  `Disallow: /` for everyone: the scraper must stay single-threaded, rate-limited and
  use the user's own account only.
* Everything is behind login. Any unauthenticated request to a content URL answers
  HTTP 200 with a redirect chain ending at `/cz/sign/in?backlink=<token>`.
  **Login detection rule:** the final response URL contains `/cz/sign/in`, or the body
  contains `id="kt_login_form"`.
* Login form (`tests/fixtures/finecim/signin.html`): `POST` to the form `action`
  (`/cz/sign/in?backlink=…`, same path as the GET), fields
  `username`, `passwd`, `remember` (`on`), `login` (`Přihlásit`), hidden `_token_`
  (CSRF, changes per page load) and hidden `_do` (`signIn-signInForm-submit`).
  Cookies: `PHPSESSID`, `nette-samesite`, plus a remember cookie when `remember=on`.
  Success = the response (after redirects) is NOT the sign-in page and contains
  `href="/cz/sign/out"`.
* Dates everywhere are `DD.MM.YYYY`. Product parameter dates look like `6. 8. 2026`.
* Media: images `/media/image/default/<id>[?width=&height=]`, PDFs
  `/media/pdf/open?itemId=<id>` (inline) and `/media/pdf/default?itemId=<id>` (download),
  videos `/media/download/default/<id>`. Store absolute URLs; do not download in v1.

### 1.1 Domains (segments) and sub-pages

Ten domains under `/cz/domena/<slug>/`:

| slug | name | products tab | subjects (count) |
|---|---|---|---|
| `ucty` | Účty | yes | 27 |
| `sporeni` | Spoření | yes | 27 |
| `uvery` | Úvěry | yes | 43 |
| `hypoteky` | Hypotéky | yes | 22 |
| `investice` | Investice | yes | 46 |
| `bankovni-trh` | Bankovní trh | no | 66 |
| `fintech` | FinTech | no | 60 |
| `bankopojisteni` | Bankopojištění | yes | 25 |
| `stavebni-sporitelny` | Stavební spořitelny | yes | 10 |
| `penzijni-spolecnosti` | Penzijní společnosti | yes | 0 (empty domain) |

Sub-pages per domain (relative to `/cz/domena/<slug>/`): `subjekty` (companies grid),
`produkty`, `porovnanie-produktov` (comparison wizard, not scraped), `news`, `campaign`,
`mystery-shopping`, `executive-summary`. Domains without a products tab lack
`produkty` and `porovnanie-produktov`.

The full taxonomy (segment ids, product-line ids and names per segment, subject
id→name per segment) is in `config/finecim.yaml`.

### 1.2 List pages

`/cz/domena/<slug>/news`, `/campaign`, `/mystery-shopping`, `/produkty` paginate with
`?step=<12|24|48|96>&page=<n>`; page 1 is `?step=96` (no `page`). Use `step=96`.
Footer shows `Zobrazeno 1 - 12 z 131` (total count) and a `kt-pagination__link--last`
anchor whose `page=` is the last page. Newest items come first.

Card markup (one `div.col-*` child per item inside the listing container):

| entity | listing container | card | fields |
|---|---|---|---|
| news | `#snippet--listingItems` | `.ecim-widget-article` | `h3.ecim-widget-article__title a[href]` (…/news/<id>), `p.ecim-widget-article__date`, `ul.ecim-widget-article__badges li` (`new`/`updated`), `p.ecim-widget-article__body___annotation`, `ul.ecim-widget-article__tags a[href]` (…/tags/detail/<id>, text = tag), `img.ecim-widget-article__img` (company logo, alt = title) |
| campaign | `#snippet--listing` | `.ecim-widget-campaign` | `h3.ecim-widget-campaign__title a[href]` (…/campaign/<id>), `p.ecim-widget-campaign__date` ×2 (`začátek: DD.MM.YYYY`, `aktualizace: DD.MM.YYYY`), `ul.ecim-widget-campaign__badges li`, `p.ecim-widget-campaign__body___annotation`, `ul.ecim-widget-campaign__btns button` (media types: TV, Outdoor, Web, Print, Rádio, Social…), `a.ecim-widget-campaign__main-image img` (creative thumbnail) |
| mystery | `#snippet--listingItems` | `.ecim-widget-general` | `h3.kt-portlet__head-title a[href]` (…/mystery-shopping/<id>), `.kt-portlet__body > p > strong` (date), `p.ecim-widget-mystery__body___annotation` |
| product | `#snippet--listing` | `.ecim-widget-product` | `h3.ecim-widget-product__title a[href]` (…/produkt/<id>), `.ecim-widget-product__category` pairs (`h4` label `Produktová linie:` / `Segment:` → `p` value), `p.ecim-widget-product__body___annotation`, `ul.ecim-widget-product__badges li` |
| company | `#snippet--content .row` | `.ecim-widget-subject` | `a.ecim-widget-subject__link[href]` (…/subjekt/<id>), `span` (name), `img` (logo) |

The segment of any item is the `<slug>` in its own URL (`/cz/domena/<slug>/news/<id>`),
which is also what the site uses on cross-segment links. Numeric ids are global
(a news id is unique across segments).

### 1.3 Detail pages

Common: `#kt_content` holds the page; left column has the main portlet, right column
`div.ecim-widget-basic-links` portlets titled `Související společnosti`,
`Související produkty`, `Související kampaně`, `Související Mystery Shopping`,
`Související zprávy`, `Mohlo by Vás také zajímat`; each item is
`.kt-widget4__item a.kt-widget4__title[href]` (absolute URL). Related company links
are `…/subjekt/<id>` — that is how an item is tied to a company. Favorites/read-later
anchors (`?do=favorite`, `?do=readLater`) must be ignored, never requested.

* **News** `…/news/<id>` (`detail_news.html`): `h3.ecim-widget-article-detail__title`,
  `.ecim-widget-article-detail__info` with `ul.ecim-widget-article-detail__badges li`,
  `.ecim-widget-article-detail__date` (`05.11.2026`), `.ecim-widget-article-detail__news-type span`
  (`produkty a služby, tiskové zprávy` — comma-separated types); body =
  `div.ecim-general-content` (first `p.news-annotation-text` is the perex; the rest is
  rich HTML with `p`, `strong`, `blockquote`, `img`, `a`, source line `Zdroj: …`);
  tags `ul.ecim-widget-article-detail__tags a`; export `?do=exportToPdf` (ignore).
* **Campaign** `…/campaign/<id>` (`detail_campaign.html`):
  `h3.ecim-widget-campaign-detail__title`, `.ecim-widget-campaign-detail__dates`
  (`Datum vytvoření: <strong>`, `Datum aktualizace: <strong>`),
  `ul.ecim-widget-campaign-detail__badges li`, `p.ecim-widget-campaign-detail__campaign-type span`
  (`Produktová, Imageová`), annotation `div.campaign-annotation-text p`, key visual
  `div.campaign-annotation-img img`, media buttons
  `ul.ecim-widget-campaing-detail__btns button[data-title][data-load]` (sic: "campaing";
  `data-title` = media type, the count inside the button text is the number of
  creatives, `data-load` = creatives endpoint
  `…/campaign/<id>?type=<n>&link=<url-encoded self>&do=campaignCreatives`).
  Timeline `div.ecim-widget-campaign-timeline #snippet--actualizations
  .ecim-widget-campaign-timeline-event` (`.kt-timeline-v1__item-time` date, text).
* **Campaign creatives** (response of `data-load`, `campaign_creatives.html`): an HTML
  fragment of `div.ecim-widget-campaign-event` blocks: `h3.kt-portlet__head-title`
  (date), `i.copyButton[data-copy]` (`…?creativeId=<id>` → creative id), body
  `div.ecim-general-content` text, media `video source[src]` or `img[src]`.
* **Mystery shopping** `…/mystery-shopping/<id>` (`detail_mystery.html`):
  `h3.ecim-widget-mystery-detail__title`, `.ecim-widget-mystery-detail__info` (date),
  body `div.ecim-general-content` (`p.ms-annotation-text` = perex; `a[href*="/media/pdf/open"]`
  = report PDF), tags `ul.ecim-widget-mystery-detail__tags a`, attachments portlet
  `div.ecim-widget-attachments .kt-widget4__item a.pdf-media-desktop[href]` (text = file name).
* **Product** `…/produkt/<id>` (`detail_product.html`):
  `h3.ecim-widget-product-detail__title`, `.ecim-widget-product-detail__info`
  (`Datum vytvoření: … Datum aktualizace: …`), categories
  `.ecim-widget-product-detail__category` (`Produktová linie:` / `Segment:`),
  `p.product-annotation-text`, parameters accordion (`#accordion .card`: `.card-header`
  text = section name, `.card-body table tr` → `th` name / `td` value). The standalone
  `…/produkty/parameters-new-window/<id>` page (`product_parameters.html`) contains
  the same accordion without page chrome: scrape parameters from there. Also
  `…/produkty/history-new-window/<id>` (not scraped in v1) and
  `…/produkty/download-excel/<id>` (ignore).
* **Company** `…/subjekt/<id>` (`detail_company.html`): `h3.ecim-widget-subject-detail__title`,
  `.ecim-widget-subject-detail__date strong` (last update), `img.ecim-widget-subject-detail__img`,
  body `div.ecim-general-content` paragraphs: free-text description, a paragraph of
  social links (`a[href]` to facebook/x/instagram/linkedin/youtube and the bank's own
  site), then `Základní informace o společnosti:` followed by paragraphs with
  `<strong>Label:</strong> value<br>` pairs — labels `Obchodní firma`, `Identifikační číslo`
  (IČO with spaces: `452 44 782`), `Sídlo`, `Základní kapitál`, `Akcionář`,
  `Představenstvo` (names with roles in parentheses, separated by `<br>` and nbsp runs),
  and a KPI line `4 600 000 klientů … 346 poboček … 1 625 bankomatů`.
  Attachments portlet = annual reports (`a.pdf-media-desktop`, file names like
  `Ceska-sporitelna-vyrocni-zprava-2024`). The right column lists EVERY related item
  (news/campaign/mystery/product) for that company — a large page (2.4 MB for Česká
  spořitelna) — parse only counts and ids from it, never fetch it per sync run except
  for the company profile refresh (weekly).
* **Executive summary** `…/executive-summary` (`list_executive_summary.html`): one
  `div.row` per year, heading `#ecim-summary-list-page-heading-<year>`, months inside
  `#ecim-summary-list-page-content-<year> a.h5[href]` (text = Czech month name
  `leden…prosinec`, href `…/executive-summary/<id>`). Month page
  (`detail_executive_summary.html`): `h1.ecim-summary-page__title` (month name),
  entries `div.ecim-widget-summary` with `h3.ecim-widget-summary__title a[href]` (a news URL),
  `input.es-entry-picker[value]` (entry id), `p.es-annotation-text` (summary text).
  The year is only known from the list page heading.
* **Tags**: `/cz/tags/detail/<id>` lists items for a tag; ~1,390 tags at `/cz/tags/list`.
  Not scraped in v1 (tags are captured on each item).

### 1.4 Volume (2026-11-05)

News pages at step 12: ucty 394, bankovni-trh 949, fintech 238, hypoteky 191,
investice 169, sporeni 168, stavebni-sporitelny 289, uvery 201, bankopojisteni 11 →
roughly 31,000 articles; campaigns ~400 in ucty; mystery shopping 131 in ucty;
products 203 in ucty. A full backfill is hours of polite fetching; the normal run is
incremental and fetches only what is new or updated.

## 2. Package layout (new code)

```
src/finecim/
  __init__.py
  credentials.py   load_credentials() → Credentials(username, password, source)
  client.py        FinecimClient — login, cookie persistence, rate-limited GET, re-login
  parsers.py       pure functions: HTML → dicts (one per page type)
  sync.py          FinecimSync — orchestration (lists → details → DB upserts, early stop)
config/finecim.yaml           taxonomy + subject→competitor mapping (already written)
config/segments.yaml          extended to the 10 domains with finecim ids
src/models/schema.sql         additive tables (section 4)
src/models/database.py        upsert methods (section 4)
src/cli.py                    `finecim` command group (section 6)
tests/fixtures/finecim/*.html trimmed live pages (already copied)
tests/test_finecim_*.py
.env.example
finecim-research/SCRAPER.md   user docs (how to run, credentials, schedule)
```

Dependencies: only what `pyproject.toml` already has (httpx, beautifulsoup4, lxml,
pyyaml, python-dateutil, click, rich). No new runtime dependency.

## 3. Interfaces (contract between the parallel pieces)

### 3.1 `src/finecim/credentials.py`

```python
@dataclass(frozen=True)
class Credentials:
    username: str
    password: str
    source: str   # "env" | path of the file it came from

def load_credentials(env_file: str | os.PathLike | None = None) -> Credentials:
    """Resolution order:
    1. environment variables FINECIM_USERNAME / FINECIM_PASSWORD;
    2. explicit env_file argument or FINECIM_ENV_FILE env var;
    3. <repo root>/.env;
    4. ~/.finecim.env  (Path.home() / ".finecim.env").
    Files are KEY=VALUE lines, '#' comments, optional quotes, UTF-8 (BOM tolerated).
    Raises CredentialsError (subclass of RuntimeError) naming the places searched, never
    echoing any value. Never log or print the password; repr(Credentials) masks it."""
```

### 3.2 `src/finecim/client.py`

```python
BASE_URL = "https://www.finecim.cz"
SIGN_IN_PATH = "/cz/sign/in"

class FinecimAuthError(RuntimeError): ...
class FinecimHTTPError(RuntimeError): ...   # carries .status_code and .url

class FinecimClient:
    def __init__(self, credentials: Credentials | None = None, *,
                 cookie_path: str | os.PathLike | None = "data/finecim_cookies.json",
                 rate_limit_seconds: float = 1.5, timeout: float = 30.0,
                 transport: httpx.BaseTransport | None = None,   # for tests (httpx.MockTransport)
                 user_agent: str | None = None) -> None: ...
    def __enter__(self) -> "FinecimClient": ...          # opens httpx.Client(follow_redirects=True), loads cookies
    def __exit__(self, *exc) -> None: ...                 # saves cookies, closes
    def login(self) -> None:                               # GET sign-in page, parse _token_/_do/action, POST; raise FinecimAuthError on failure
    def is_logged_in(self) -> bool:                        # cheap GET /cz/ and apply the login-detection rule
    def get(self, path_or_url: str, *, params: dict | None = None) -> str:
        """Rate-limited GET returning response text. Resolves relative paths against BASE_URL.
        If the login-detection rule fires, calls login() once and retries; a second failure
        raises FinecimAuthError. Retries transport errors / 5xx up to 3 times with backoff.
        4xx (other than the login redirect) raise FinecimHTTPError."""
    def get_fragment(self, url: str) -> str: ...          # alias of get() for AJAX fragments (campaign creatives)
    @staticmethod
    def looks_like_login_page(final_url: str, html: str) -> bool: ...
    @staticmethod
    def absolute(url: str) -> str: ...                     # join against BASE_URL, keep absolute URLs

def parse_login_form(html: str) -> dict:  # {"action": str, "fields": {"_token_":..., "_do":...}} — module-level, test it on signin.html
```

Cookie persistence: JSON list of `{name, value, domain, path, expires}` written with
mode 0600 where the OS supports it; the directory is created; `data/` is gitignored.

### 3.3 `src/finecim/parsers.py` (pure, no I/O)

All functions take `html: str` (plus `url: str` where the id/segment is derived from
the URL) and return plain dicts/lists with ISO dates (`YYYY-MM-DD`) and absolute URLs.
Missing fields are `None`/`[]`, never exceptions, except `ParseError` when the page is
not the expected type (e.g. login page, empty `#kt_content`).

```python
class ParseError(ValueError): ...

def parse_item_url(url: str) -> dict   # {"segment": "ucty", "entity": "news|campaign|mystery-shopping|produkt|subjekt|executive-summary", "id": 43573}
def parse_date_cz(text: str) -> str | None        # "05.11.2026" / "6. 8. 2026" -> "2026-11-05"
def parse_pagination(html: str) -> dict           # {"total": 131, "step": 12, "page": 1, "last_page": 11}

def parse_news_list(html: str, url: str) -> list[dict]
    # each: {"id", "segment", "url", "title", "date", "badges": ["new"], "annotation", "tags": [{"id","name","url"}], "logo_url"}
def parse_campaign_list(html: str, url: str) -> list[dict]
    # each: {"id","segment","url","title","start_date","updated_date","badges","annotation","media_types": ["TV"], "thumbnail_url"}
def parse_mystery_list(html: str, url: str) -> list[dict]
    # each: {"id","segment","url","title","date","annotation"}
def parse_product_list(html: str, url: str) -> list[dict]
    # each: {"id","segment","url","title","product_line","customer_segment","annotation","badges","logo_url"}
def parse_subject_list(html: str, url: str) -> list[dict]
    # each: {"id","segment","url","name","logo_url"}

def parse_news_detail(html: str, url: str) -> dict
    # {"id","segment","url","title","date","badges","news_types": [..], "perex","body_html","body_text",
    #  "tags": [...], "images": [abs urls in body], "source_line", "related_subjects": [{"id","name","url"}],
    #  "related_products": [...], "related_news": [...]}
def parse_campaign_detail(html: str, url: str) -> dict
    # {"id","segment","url","title","created_date","updated_date","badges","campaign_types": [..],
    #  "annotation","key_visual_url","media": [{"type": "TV", "count": 2, "creatives_url": abs}],
    #  "timeline": [{"date","text"}], "related_subjects","related_products","related_campaigns"}
def parse_campaign_creatives(html: str, campaign_url: str) -> list[dict]
    # each: {"creative_id", "date", "text", "media_url", "media_kind": "video|image|None"}
def parse_mystery_detail(html: str, url: str) -> dict
    # {"id","segment","url","title","date","perex","body_html","pdf_url","attachments": [{"name","url"}],
    #  "tags","related_subjects","related_products"}
def parse_product_detail(html: str, url: str) -> dict
    # {"id","segment","url","title","created_date","updated_date","product_line","customer_segment",
    #  "annotation","logo_url","parameters_url","history_url","related_subjects","related_news"}
def parse_product_parameters(html: str) -> list[dict]
    # [{"section": "Aktuální verze", "name": "iOS (verze)", "value": "26.4.51"}, ...]  (ordered)
def parse_subject_detail(html: str, url: str) -> dict
    # {"id","segment","url","name","updated_date","logo_url","description_text","description_html",
    #  "social_links": {"facebook": url, "x": url, "instagram": url, "linkedin": url, "youtube": url, "web": url},
    #  "legal_name","ico" (digits only),"address","share_capital","shareholder",
    #  "board": [{"name","role"}], "clients","branches","atms" (ints or None),
    #  "attachments": [{"name","url"}], "related_counts": {"news": 4075, "campaigns": 200, "mystery": 25, "products": 57},
    #  "related_ids": {"news": [..], "campaigns": [..], "mystery": [..], "products": [..]}}
def parse_executive_summary_list(html: str, url: str) -> list[dict]
    # each: {"id","segment","url","year": 2026, "month": 6, "month_name": "červen"}
def parse_executive_summary_detail(html: str, url: str) -> dict
    # {"id","segment","url","month_name","entries": [{"entry_id", "news_id", "news_url", "title", "text"}]}
```

Body HTML sanitising: keep `p, br, strong, b, em, i, u, a, ul, ol, li, blockquote,
h1-h6, table, thead, tbody, tr, th, td, img`; drop `style`/`class`/`id`/`on*`
attributes; make `href`/`src` absolute; collapse whitespace. `body_text` is the text
with paragraphs separated by blank lines.

### 3.4 `src/models/database.py` additions (section 4 has the DDL)

```python
# taxonomy
def upsert_finecim_subject(self, subject_id: int, name: str, competitor_id: str | None, url: str | None, segment_ids: list[str]) -> None
def get_finecim_subject(self, subject_id: int) -> dict | None
def ensure_competitor_for_subject(self, subject_id: int, name: str) -> str   # returns competitor_id; creates "fc_<id>" (tier 3) when unmapped
# entities (all idempotent upserts keyed by the finecim id; set pridano_at only on insert)
def upsert_clanek(self, row: dict) -> bool                  # returns True if inserted
def upsert_kampan(self, row: dict) -> bool
def replace_kampan_kreativy(self, kampan_id: str, rows: list[dict]) -> int
def upsert_mystery(self, row: dict) -> bool
def upsert_produkt(self, row: dict) -> bool
def upsert_executive_summary(self, row: dict, polozky: list[dict]) -> bool
def upsert_spolecnost_detail(self, competitor_id: str, row: dict) -> None
def replace_prilohy(self, entity_type: str, entity_id: str, rows: list[dict]) -> int
def replace_vazby(self, entity_type: str, entity_id: str, subject_ids: list[int]) -> int
# incremental sync helpers
def known_finecim_ids(self, entity: str, ids: list[int]) -> dict[int, str | None]   # id -> stored updated/aktualizace date (or None)
def get_finecim_sync(self, entity: str, segment_id: str) -> dict | None
def set_finecim_sync(self, entity: str, segment_id: str, **fields) -> None
```

Row dict keys mirror the table columns (section 4). Entity ids are strings:
`fc-news-<id>`, `fc-campaign-<id>`, `fc-ms-<id>`, `fc-product-<id>`, `fc-es-<id>`.

### 3.5 `src/finecim/sync.py`

```python
ENTITIES = ("company", "news", "campaign", "mystery", "product", "summary")

@dataclass
class SyncStats: fetched: int = 0; inserted: int = 0; updated: int = 0; skipped: int = 0; errors: int = 0; pages: int = 0

class FinecimSync:
    def __init__(self, client: FinecimClient, db: Database, config_dir: str | os.PathLike, *,
                 logger: logging.Logger | None = None) -> None: ...
    def sync_taxonomy(self) -> None            # segments + product lines from config/segments.yaml + config/finecim.yaml, subjects per segment from /subjekty
    def sync_companies(self, segments: list[str] | None = None, *, all_companies: bool = False) -> SyncStats
    def sync_news(self, segments=None, *, max_pages: int | None = None, full: bool = False) -> SyncStats
    def sync_campaigns(self, segments=None, *, max_pages=None, full=False) -> SyncStats
    def sync_mystery(self, segments=None, *, max_pages=None, full=False) -> SyncStats
    def sync_products(self, segments=None, *, max_pages=None, full=False) -> SyncStats
    def sync_summaries(self, segments=None, *, years: list[int] | None = None) -> SyncStats
    def sync_all(self, entities=ENTITIES, segments=None, *, max_pages=None, full=False) -> dict[str, SyncStats]
```

Incremental rule for list-driven entities: walk pages newest-first with `step=96`;
for each page collect ids; ask `known_finecim_ids`; fetch the detail of every id that
is unknown, or carries the `updated` badge / has a newer `aktualizace` date than
stored; after a page where nothing needed fetching, stop (unless `full`). `max_pages`
caps pages per segment. Each detail fetch is wrapped so one bad page increments
`errors` and continues. Campaign details also fetch each `media[].creatives_url`.
Product details also fetch `parameters_url`. Company sync fetches the profile only for
subjects mapped to a configured competitor unless `all_companies`. Summaries: list
page per segment, then every month page not yet stored (or all when `years` given).

## 4. Schema additions (additive; `init-db` must stay idempotent)

```sql
CREATE TABLE IF NOT EXISTS finecim_subjekty (
    subject_id INTEGER PRIMARY KEY,
    nazev TEXT NOT NULL,
    competitor_id TEXT REFERENCES competitors(id),
    url TEXT,
    logo_url TEXT,
    aktualizace TEXT,
    pridano_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS finecim_subjekty_segmenty (
    subject_id INTEGER NOT NULL REFERENCES finecim_subjekty(subject_id),
    segment_id TEXT NOT NULL REFERENCES segmenty(id),
    PRIMARY KEY (subject_id, segment_id)
);
CREATE TABLE IF NOT EXISTS finecim_vazby (          -- every related company of an item
    entity_type TEXT NOT NULL,                       -- clanek | kampan | mystery | produkt
    entity_id TEXT NOT NULL,
    subject_id INTEGER NOT NULL,
    PRIMARY KEY (entity_type, entity_id, subject_id)
);
CREATE TABLE IF NOT EXISTS finecim_prilohy (        -- PDFs / files attached to an item or company
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,                       -- spolecnost | mystery | clanek
    entity_id TEXT NOT NULL,
    nazev TEXT,
    url TEXT NOT NULL,
    UNIQUE(entity_type, entity_id, url)
);
CREATE TABLE IF NOT EXISTS kampane_kreativy (
    id TEXT PRIMARY KEY,                             -- fc-creative-<creativeId>
    kampan_id TEXT NOT NULL REFERENCES kampane(id),
    datum TEXT,
    media_typ TEXT,
    popis TEXT,
    media_url TEXT,
    media_druh TEXT                                  -- video | image | NULL
);
CREATE TABLE IF NOT EXISTS executive_summary_polozky (
    id TEXT PRIMARY KEY,                             -- fc-es-entry-<entryId>
    summary_id TEXT NOT NULL REFERENCES executive_summary(id),
    clanek_id TEXT,                                  -- fc-news-<id> (may not be scraped yet)
    nazev TEXT,
    text TEXT,
    poradi INTEGER
);
CREATE TABLE IF NOT EXISTS finecim_sync (
    entity TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    last_run_at TEXT,
    last_success_at TEXT,
    last_page INTEGER,
    newest_id INTEGER,
    note TEXT,
    PRIMARY KEY (entity, segment_id)
);
```

Column mapping into the existing tables:

* `clanky`: id `fc-news-<id>`, competitor_id = primary related subject's competitor (or
  NULL), segment_id, produktova_linie_id NULL, nazev, datum, typ_zpravy (joined types),
  stav (badge or `new`), perex, telo (sanitised HTML), tagy (JSON list of names),
  zdrojovy_signal_id NULL, url, pridano_at.
* `kampane`: id `fc-campaign-<id>`, competitor_id (required: primary subject, else the
  auto-created `fc_<subject>` competitor; if there is no related subject at all use
  `__finecim__`, a placeholder competitor created by `ensure_competitor_for_subject(0, "FINeCIM (nepřiřazeno)")`),
  segment_id, nazev, zacatek, aktualizace, popis (annotation), media_typy (JSON list),
  typ_kampane (joined), kreativa_url (key visual), pridano_at.
* `mystery_shopping`: id `fc-ms-<id>`, competitor_id (nullable), segment_id, nazev, datum,
  popis (perex + body text), pdf_url, pridano_at.
* `produkty`: id `fc-product-<id>`, competitor_id (required, as for kampane), segment_id,
  produktova_linie_id (resolved by name within the segment via `produktove_linie.nazev`,
  else NULL), zakaznicky_segment, nazev, kratky_popis, atributy (JSON list of
  `{section,name,value}`), url, aktivni 1, pridano_at.
* `executive_summary`: id `fc-es-<id>`, segment_id, rok, mesic, nazev (`<month name> <year>`),
  telo (markdown: one `- [title](news_url): text` line per entry), pdf_url NULL.
* `spolecnost_detail`: popis (description_text), zakladni_kapital, sidlo, akcionar,
  pocet_klientu, pocet_pobocek, pocet_bankomatu, socialni_site (JSON), predstavenstvo (JSON),
  posledni_aktualizace. `competitors.ico` is filled from the profile when empty.

## 5. Config

`config/finecim.yaml` (written) holds `segments` (slug → finecim name, has_products,
product_lines id→name), `subjects` (id → name, per-segment membership) and
`subject_to_competitor` (the 19 configured competitors). `config/segments.yaml` must be
extended to all ten domains, keeping existing ids/slugs for `ucty`, `hypoteky`,
`investice` and their product-line slugs, adding `finecim_slug` on segments and
`finecim_id` on product lines, and adding the missing product lines with slugs derived
from the Czech name (ASCII, underscores).

## 6. CLI

`ci-monitor finecim …` (Click group in `src/cli.py`):

* `finecim login-check` — load credentials, log in, print the account state (never
  the password), persist cookies.
* `finecim sync [--entity all|company|news|campaign|mystery|product|summary]…
  [--segment SLUG]… [--max-pages N] [--full] [--all-companies] [--dry-run]` — runs the
  sync, prints a Rich table of `SyncStats` per entity.
* `finecim status` — rows of `finecim_sync` plus counts per table.

`schedule` gains a daily `finecim sync` job when credentials resolve, otherwise logs
that FINeCIM is disabled. Settings: `config/settings.yaml` gets
`finecim: {rate_limit_seconds: 1.5, cookie_path: data/finecim_cookies.json, schedule: daily}`.

## 7. Politeness and safety

* One request at a time, ≥1.5 s apart (configurable), exponential backoff on 5xx.
* Never request `?do=favorite`, `?do=readLater`, `?do=exportToPdf`, `/cz/sign/out`,
  the AI assistant endpoints (`?do=askFerda`), or the Early-warnings pages.
* Never print or log credentials or cookie values. `.env`, `~/.finecim.env` and
  `data/` stay out of git.
* Content is for the subscriber's internal tooling; the scraper stores URLs to media
  rather than mirroring files in v1.
