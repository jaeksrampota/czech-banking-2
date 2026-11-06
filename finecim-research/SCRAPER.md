# FINeCIM scraper: user guide

The scraper copies content from the logged-in FINeCIM site (`https://www.finecim.cz`) into
the local SQLite database (`clanky`, `kampane`, `mystery_shopping`, `produkty`,
`executive_summary`, `spolecnost_detail` and the `finecim_*` helper tables), so the
dashboard shows real data. Design and page formats: `SCRAPER-DESIGN.md` in this folder.

All commands below can be run as `ci-monitor ...` (installed entry point) or
`python -m src.cli ...` from the repository root.

## 1. Credentials

You need your own FINeCIM subscriber account. Credentials are resolved in this order
(first complete username + password pair wins):

1. **Environment variables** `FINECIM_USERNAME` and `FINECIM_PASSWORD`
   (good for CI or a one-off shell session).
2. **An explicit file**: the file named by `FINECIM_ENV_FILE`, then `<repo root>/.env`.
   Copy `.env.example` to `.env` and fill in the two values. `.env` is git-ignored.
3. **`~/.finecim.env`** in your home directory (on Windows `C:\Users\<you>\.finecim.env`).
   This is the recommended place: it lives outside the repository and cannot be
   committed by accident.

Files are plain `KEY=VALUE` lines; `#` starts a comment and values may be quoted:

```
FINECIM_USERNAME=you@example.com
FINECIM_PASSWORD="your password"
```

The tools never print or log the password or cookie values. When nothing is found, the
error lists every place that was searched.

## 2. First run

```bash
python -m src.cli init-db                  # schema, segments, competitors
python -m src.cli finecim login-check      # logs in, saves session cookies
python -m src.cli finecim sync --dry-run   # the plan: no credentials, no network, no writes
python -m src.cli finecim sync --max-pages 1 --max-items 3 --segment ucty   # smoke run
python -m src.cli finecim status           # what is stored, backfill position per segment
python -m src.cli finecim sync             # normal run: new items + the next slice of the backfill
```

`finecim sync` options:

| option | meaning |
|---|---|
| `--entity/-e` | `all` (default) or any of `taxonomy`, `company`, `news`, `campaign`, `mystery`, `product`, `summary`; repeatable. The taxonomy step (segments from config, plus one `/subjekty` page per segment) always runs first; `-e taxonomy` alone runs only that step |
| `--segment/-s` | FINeCIM domain slug (`ucty`, `sporeni`, `uvery`, `hypoteky`, `investice`, `bankovni-trh`, `fintech`, `bankopojisteni`, `stavebni-sporitelny`, `penzijni-spolecnosti`); repeatable, default all |
| `--max-pages N` | page budget: at most N list pages per entity and segment in this run, head scan and backfill together. Head-scan pages on which nothing was fetched are free (see section 3). Default 3 (`DEFAULT_MAX_PAGES` in `src/finecim/sync.py`); unlimited with `--full` unless `--max-pages` is given too |
| `--max-items N` | item budget: at most N detail fetches per entity and segment in this run. Default 120 (`DEFAULT_MAX_ITEMS`) for news, campaigns, mystery shopping and products; unlimited with `--full` unless `--max-items` is given too. Company profiles and executive summaries are capped only when `--max-items` is given (the scheduled job passes 120, see section 4). Minimum 1 |
| `--years YYYY` | executive summaries: refetch every stored month of that year (repeatable) |
| `--full` | no early stop and no default page or item budget: walk every list page (still fetches only new or updated items) and refetch every company profile |
| `--all-companies` | fetch profiles of every company, not only the 19 configured competitors |
| `--dry-run` | validate `--segment` and `--entity` against the config and print the plan (steps x segments, page budget, stored backfill cursors); needs no credentials, makes no request and writes nothing; exit code 0 |

**The first run is bounded.** The whole archive is large (roughly 31,000 news articles
across all domains; at one request every 1.5 s a complete walk takes many hours), so a
plain run never walks it at once. Each run spends at most 3 list pages (96 items each)
and 120 detail fetches per entity and segment. On an empty database, where every page is
new, the first run therefore reads page 1 and the first 24 items of page 2, and the
backfill continues on page 2 next time (with `--max-items 300` it would read pages 1 to 3
and store a backfill cursor of 4).

**The backfill resumes across runs.** Every later run first reads from page 1 to pick up
new items and stops at the first page with nothing new (that page is free). It then
spends the rest of its budgets continuing the backfill at the stored cursor, so the daily
job works through the archive a slice at a time. An interrupted or capped run loses
nothing: the cursor only moves past pages that were read completely (a page cut short by
`--max-items`, or a list page that failed, is read again next time). A detail that fails
is retried on later runs, up to 3 attempts, whether it failed in the head scan or in the
backfill; only after the third failed attempt does the scraper give up on it, with a
warning in the log naming the page or the item ids.
When the backfill reaches the end of the list the cursor is cleared and the segment is
marked `complete`; from then on a run reads page 1, plus further pages only while they
contain new items. To finish a backfill sooner, run with a larger `--max-pages`, or walk
everything in one go with `--full` (best one segment and entity at a time, for example
`finecim sync --full -s ucty -e news`).

The session cookies are stored in `data/finecim_cookies.json` (mode 0600 where the OS
supports it). The whole `data/` directory is git-ignored, so the cookies cannot be
committed. The client logs in again automatically when the session expires.

## 3. What the incremental rule does

For news, campaigns, mystery shopping and products, each segment's list is read
newest-first with 96 items per page. On each page the scraper asks the database which ids
it already has, then fetches the detail page only for items that are:

* not stored yet, or
* shown with a newer date than the stored one (the news/mystery date, the campaign
  `aktualizace` date), or
* flagged with the `updated` badge. The one exception is a campaign whose card
  `aktualizace` date is not newer than the stored one: that date is an update date, so
  the stored copy is known to be current. News and mystery cards show only the publish
  date, so a badged news article is always fetched again.

Products have no date on the card, so a product that keeps showing the `updated` badge is
fetched again on every run. When the refetch finds the same update date as stored, it
does not count as new work: the page can still trigger the early stop, so a persistent
badge does not make every run walk deeper into the list.

Items are matched by id alone. An article listed in a domain other than the one in its
own URL (`/cz/domena/<slug>/news/<id>`) is stored once, under the segment of its URL; in
the other domain's list it counts as already known, so it is not fetched again and does
not prevent the early stop.

FINeCIM lists are newest-first, new items are only ever added at the top, and ids only
grow (a newer item has a larger id). The scraper therefore remembers positions by item id
rather than by page number, because page numbers shift whenever new items arrive. Per
entity and segment, `finecim_sync` holds:

* `last_page`, the **backfill cursor**: the next page to read towards the end of the
  archive (empty when the list is complete or no walk has started). The note also records
  `after=<id>`, the last card of the page before the cursor.
* `newest_id`, the **head guard**: an item id meaning "the head scan above this item is
  done; the page that holds it may still have unprocessed items after it" (empty when no
  head work is pending).
* `note`: `backfill`, `complete` or `head` (nothing walked yet), the markers, `retry=N`
  while a backfill page with failed details is being retried, `hretry=N` while a detail
  that failed in the head scan is being retried, then the run counters.

Every run has two budgets per entity and segment: the **page budget** (`--max-pages`,
default 3) and the **item budget** (`--max-items`, default 120 detail fetches); `--full`
lifts both unless they are given explicitly. Head-scan pages on which nothing had to be
fetched (pages that are already known, and the page that ends the head scan) are free, as
is the backfill's check of the page before its cursor; every other list page counts,
including a backfill page on which everything was already known (new items on top push
already processed pages under the page-number cursor, so a small page budget slows the
backfill down a little; it never skips anything). A run
reads at most 60 free pages (`MAX_FREE_PAGES`), so it never makes more than the page
budget plus 60 list requests per entity and segment.

1. **Head scan** from page 1. It fetches what each page needs, in list order. If the item
   budget runs out in the middle of a page, the first card it could not fetch becomes the
   guard and the run ends. If the page budget runs out on a page that still had new items,
   the last card of that page becomes the guard. A guard that is still pending from an
   earlier run and that this run did not get past is kept (the smaller id wins), so an
   older interrupted burst stays protected. The head scan stops early (never with
   `--full`) at the first page that needs nothing and lies wholly below the guard (every
   id on it is smaller than the guard); then the guard is cleared. A guard item that was
   removed from the site is simply passed like any other position. When a cut lands at or
   beyond the backfill cursor, or on a segment that was never walked, the cursor moves to
   the cut instead and no guard is needed, because the backfill covers everything below
   it.
2. **Backfill**, only when the head scan finished within its budgets. It continues at the
   stored cursor without the early stop. It first checks the page before the cursor: if
   items were removed above it and unread cards moved up past the cursor (every id there
   is smaller than `after`), it steps back. A page cut short by the item budget is read
   again next run. A page with a failed detail keeps the cursor where it is and is retried
   on the next run, up to 3 attempts (`MAX_PAGE_ATTEMPTS`); after the third failed attempt
   the cursor moves on and a warning names the page. An empty page (or the pager's last
   page) completes the list.
3. **Failed details in the head scan.** A card whose detail failed is not stored, but the
   head scan has already moved past it. After the run the smallest failed id becomes the
   guard (the smaller of it and a pending guard wins, also when the list was just marked
   `complete`, for example by a `--full` run), so the next head scan cannot stop early
   above that card and fetches it again. This is repeated for up to 3 consecutive runs
   with head failures (`hretry=N` in the note); after the third the guard is no longer
   extended and a warning names the item ids.

Why nothing is lost: every item is either above the guard (a head scan always starts at
page 1 and does not stop early before it is below the guard), on the guard's page (that
page never triggers the early stop, so its remaining cards are fetched when it is seen),
or below the head cut (reached by the backfill cursor); a card whose detail failed stays
above a guard (head scan) or under the cursor (backfill) until it is stored or its 3
attempts are used up. New items only enter at the top,
so nothing moves from "below" to "above" a position that was already processed.
`finecim status` and `--dry-run` show a pending guard as "head unfinished (guard id N)".
The randomized replay in `tests/test_finecim_resume_property.py` checks this property
against a simulated list.

The end of the list is the page named by the pager's last-page link (or computed from the
item total); when a page has neither, the walk continues until an empty page. An empty
domain (`penzijni-spolecnosti` has no content yet) costs one list request per entity and
ends as `complete` without errors. Segments without a products tab (`bankovni-trh`,
`fintech`) are skipped for products.

Each campaign detail also loads its creatives (one request per media type) and each
product loads its parameter table (one request). The related companies of every item are
stored in `finecim_vazby`; a related company that is not on any `/subjekty` page yet gets
a minimal `finecim_subjekty` row (name and link from the item page). An item's competitor
is the first related company that maps to a configured competitor; only when none maps
does a campaign or product fall back to the first related company (an auto-created
`fc_<id>` competitor) or, without any related company, the placeholder `__finecim__`.

Company profiles are large pages: they are fetched only for the companies mapped to
configured competitors (`config/finecim.yaml`, `subject_to_competitor`; every company with
`--all-companies`) and only when no profile is stored yet or that company's last profile
fetch is older than 7 days (a weekly refresh; `--full` refetches all of them). The fetch
time is kept per company in `finecim_sync` (entity `company-profile`, segment id = the
FINeCIM subject id).

Executive summaries: the per-segment month list is read and every month not stored yet is
fetched. The current and the previous calendar month are fetched again on every run,
because FINeCIM fills them in during the month. `finecim sync --years 2025` (or
`sync_summaries(years=...)`) refetches every stored month of the given years. The summary title is the month name and year from the
list page (for example `červen 2026`).

A page that fails (HTTP error, unexpected markup) is counted in the `Errors` column and
the run continues with the next item; a failed login stops the run. `finecim status`
shows per entity and segment when the last run and the last error-free run happened and
the backfill position (`next page N`, `complete` or `not started`, plus `head unfinished
(guard id N)` while a head guard is pending), plus how many company profiles have been
fetched and the oldest and newest fetch time.

## 4. Schedule

`python -m src.cli schedule` adds a `finecim_sync` job (default `daily`, at 04:15 UTC; named schedules and cron
expressions are evaluated in UTC)
when the credentials resolve. The job is a bounded run with the default budgets passed
explicitly (3 list pages and 120 detail fetches per entity and segment): new items first,
then the next slice of the backfill. Because the item budget is passed explicitly, a
scheduled run also caps company profiles and executive summaries at 120 per segment
(a plain `finecim sync` leaves those uncapped). The archive fills in
over the following days without any single run taking hours. Without credentials the scheduler logs that FINeCIM is
disabled and runs the other collectors as before. Settings live in `config/settings.yaml`:

```yaml
finecim:
  rate_limit_seconds: 1.5                 # minimum gap between two requests
  cookie_path: "data/finecim_cookies.json"
  schedule: "daily"                       # hourly | daily | weekly | cron expression | off
```

## 5. Politeness settings

* Strictly one request at a time, at least `rate_limit_seconds` (1.5 s) apart.
* Transport errors and HTTP 5xx are retried up to 3 times with exponential backoff. On
  HTTP 429 and 503 the server's `Retry-After` header is honoured (delta-seconds or an
  HTTP date), capped at 120 s per wait.
* Every run is bounded per entity and segment by the page budget (default 3 list pages),
  the item budget (default 120 detail fetches) and at most 60 free list pages.
* The client refuses to request `?do=favorite`, `?do=readLater`, `?do=exportToPdf`,
  `?do=askFerda`, `/cz/sign/out` and the Early-warnings pages.
* Media (images, PDFs, videos) are stored as URLs; nothing is downloaded or mirrored.
* Prefer the bounded daily run (which also advances the backfill) over repeated `--full`
  runs.

## 6. Legal note

FINeCIM is a paid subscription service and its `robots.txt` disallows all crawling. Use
the scraper only with your own account, within your subscription terms, for your own
internal competitive-intelligence tooling. Keep the scraper single-threaded and
rate-limited, do not redistribute the content, and do not mirror media files. Credentials
and cookie values must never be printed, logged or committed: `.env`, `~/.finecim.env`
and the `data/` directory stay out of git.
