"""FINeCIM sync orchestration: list pages -> detail pages -> database upserts.

See finecim-research/SCRAPER-DESIGN.md (sections 3.5 and 4). The incremental rule for the
list-driven entities (news, campaign, mystery, product):

* walk the list pages of a segment newest-first with ``step=96``;
* per page, ask the database which ids are already stored (``known_finecim_ids``);
* fetch the detail of every id that is unknown, or whose card shows a newer date than
  the stored one, or that carries the ``updated`` badge. The one exception to the badge:
  campaign cards show their update date (``aktualizace``), so a badged campaign whose
  card update date is not newer than the stored one is current and is skipped. News and
  mystery cards show the publish date, which says nothing about updates, so a badged
  news/mystery card is always refetched. A card is matched by its id alone, so an item
  listed in another domain than its own URL slug is "known" there too.

Resume model per (entity, segment). FINeCIM lists are newest-first, new items are only
ever inserted at the top and ids are monotonic (a newer item has a larger id), so a
position in the list can be named by an item id, which does not shift when new items
arrive. The finecim_sync row holds:

* ``last_page`` = the backfill cursor: the next page to read towards the end of the
  archive (NULL when the list is complete or no walk has started); the note carries
  ``after=ID``, the last card of the page before the cursor, so a run can tell whether
  removed items moved unread cards up past the cursor (it then steps back);
* ``newest_id`` = the head guard: an item id meaning "the head scan above this item is
  done; the page that holds it may still have unprocessed items after it" (NULL when no
  head work is pending). A head scan may stop early only on a page with nothing to fetch
  that lies wholly below the guard (every id < guard), so it can never stop above
  unprocessed items left by an earlier, interrupted head scan, and a guard item that has
  vanished from the list is passed like any other position;
* ``note`` = ``backfill`` | ``complete`` | ``head`` (no walk yet), the markers above,
  ``retry=N`` (failed attempts at the cursor page) and ``hretry=N`` (consecutive runs whose
  head scan had failed details), then the run counters.

A run has a page budget (``max_pages``; DEFAULT_MAX_PAGES, unlimited with ``full``) and an
item budget (``max_items`` detail fetches per entity and segment; DEFAULT_MAX_ITEMS,
unlimited with ``full``). Head-scan pages on which no detail was fetched (fully known
pages, the early-stop page) and the backfill's check of the page before the cursor are
free; every other list page counts (also a fully known backfill page). A run that has a page budget reads at most
MAX_FREE_PAGES free pages (a runaway stop; when the head scan hits it, the cursor takes
over from the next page), so it makes at most budget + MAX_FREE_PAGES list requests.

* The head scan reads from page 1. It fetches the cards that need it in list order; when
  the item budget runs out mid-page it records the first card not fetched as the guard
  and ends the run. It early-stops (never with ``full``) on a page with nothing to fetch
  below the guard, clearing the guard. When the page budget runs out on a page that had
  work, the last card of that page becomes the guard. An existing guard that the run did
  not get past is kept (the smaller id wins), so an older interrupted burst stays
  protected. When the cut lies at or beyond the backfill cursor, or the segment was never
  walked, the cursor is moved to the cut instead (the backfill then covers everything
  below it) and no guard is needed.
* The backfill runs only when the head finished without exhausting the budgets. From the
  cursor it reads page after page without the early stop; an empty page (or the pager's
  last page) completes the list. A page cut short by the item budget is read again next
  run. A page with a failed detail is read again next run, up to MAX_PAGE_ATTEMPTS
  attempts; after that the cursor moves on and a warning names the page.
* A detail that fails during the head scan is not stored, but the scan has moved past it.
  After the run the smallest failed id becomes the guard (the smaller of it and a pending
  guard wins; also on a list that was just completed), so the next head scan cannot stop
  early above that card and fetches it again. Up to MAX_PAGE_ATTEMPTS consecutive runs
  with head failures do this; after that a warning names the cards.

Why nothing is lost: every item is either above the guard (processed by a head scan:
head scans always start at page 1 and do not early-stop before they are below the
guard), on the guard's page (that page holds an id >= the guard, so it never triggers the
early stop and its remaining cards are processed when it is seen), or below the head cut
(reached by the backfill cursor), and a card whose detail failed is kept above a guard
(head scan) or under the cursor (backfill) until it is stored or its attempts run out.
Items only enter at the top, so nothing moves from
"below" to "above" an already processed position; a removed item moves the cards after it
up, which the id checks (the guard comparison, ``after=`` at the cursor) detect.

Every detail is processed inside its own try/except: one bad page increments
``SyncStats.errors`` and the run continues. A failed login (FinecimAuthError) aborts the
run, since every further request would fail the same way; the position reached so far is
recorded first.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from src.finecim import parsers
from src.finecim.client import FinecimAuthError, FinecimClient
from src.finecim.credentials import Credentials
from src.models.database import Database

__all__ = [
    "DEFAULT_MAX_ITEMS",
    "DEFAULT_MAX_PAGES",
    "ENTITIES",
    "LIST_STEP",
    "MAX_FREE_PAGES",
    "MAX_PAGE_ATTEMPTS",
    "PROFILE_REFRESH_DAYS",
    "PROFILE_SYNC_ENTITY",
    "SYNC_TARGETS",
    "FinecimSync",
    "ResumeState",
    "SyncStats",
    "backfill_position",
    "client_from_settings",
    "item_budget",
    "load_finecim_settings",
    "page_budget",
    "resume_state",
]

ENTITIES = ("company", "news", "campaign", "mystery", "product", "summary")
#: Everything ``sync_all`` accepts: the taxonomy step (always run first) plus ENTITIES.
SYNC_TARGETS = ("taxonomy", *ENTITIES)

LIST_STEP = 96
#: List pages per entity and segment of a plain run (head scan + backfill together). Only
#: pages on which at least one detail was fetched count.
DEFAULT_MAX_PAGES = 3
#: Detail fetches per entity and segment of a plain run (list entities).
DEFAULT_MAX_ITEMS = 120
#: List pages without any detail fetch that one run may read per entity and segment.
MAX_FREE_PAGES = 60
#: Attempts at a backfill page with failed details before the cursor moves on anyway.
MAX_PAGE_ATTEMPTS = 3
#: A company profile (a large page) is refetched when its last fetch is older than this.
PROFILE_REFRESH_DAYS = 7
#: finecim_sync entity holding the last profile fetch per subject (segment_id = subject id).
PROFILE_SYNC_ENTITY = "company-profile"

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# entity -> (list path below /cz/domena/<slug>/, list parser, entity_type for finecim_vazby)
_LIST_ENTITIES: dict[str, tuple[str, Callable[[str, str], list[dict]], str]] = {
    "news": ("news", parsers.parse_news_list, "clanek"),
    "campaign": ("campaign", parsers.parse_campaign_list, "kampan"),
    "mystery": ("mystery-shopping", parsers.parse_mystery_list, "mystery"),
    "product": ("produkty", parsers.parse_product_list, "produkt"),
}

# Which card field holds the date comparable with the stored date (known_finecim_ids).
_CARD_DATE_FIELD = {"news": "date", "campaign": "updated_date", "mystery": "date", "product": None}
# Entities whose card date is an update date: a card date that is not newer than the
# stored one proves the stored copy is current even when the ``updated`` badge is shown.
_DATE_PROVES_CURRENT = frozenset({"campaign"})

_UPDATED_BADGES = ("updated", "aktualizováno", "aktualizovano", "aktualizace")


@dataclass
class SyncStats:
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    pages: int = 0

    def add(self, other: SyncStats) -> None:
        for key, value in asdict(other).items():
            setattr(self, key, getattr(self, key) + value)

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_finecim_settings(config_dir: str | os.PathLike) -> dict:
    """The ``finecim`` section of settings.yaml with defaults filled in."""
    settings = _read_yaml(Path(config_dir) / "settings.yaml")
    section = settings.get("finecim") or {}
    return {
        "rate_limit_seconds": float(section.get("rate_limit_seconds", 1.5)),
        "cookie_path": section.get("cookie_path", "data/finecim_cookies.json"),
        "schedule": section.get("schedule", "daily"),
    }


def client_from_settings(config_dir: str | os.PathLike,
                         credentials: Credentials | None = None) -> FinecimClient:
    """A FinecimClient configured from settings.yaml (relative cookie paths resolve
    against the project root)."""
    cfg = load_finecim_settings(config_dir)
    cookie_path = cfg["cookie_path"]
    if cookie_path and not os.path.isabs(cookie_path):
        cookie_path = str(PROJECT_ROOT / cookie_path)
    return FinecimClient(
        credentials,
        cookie_path=cookie_path or None,
        rate_limit_seconds=cfg["rate_limit_seconds"],
    )


def page_budget(max_pages: int | None, full: bool) -> int | None:
    """List pages per entity and segment for one run (None = unlimited). Only pages on
    which at least one detail was fetched count against it."""
    if max_pages:
        return int(max_pages)
    return None if full else DEFAULT_MAX_PAGES


def item_budget(max_items: int | None, full: bool) -> int | None:
    """Detail fetches per entity and segment for one list-entity run (None = unlimited)."""
    if max_items is not None:
        return int(max_items)
    return None if full else DEFAULT_MAX_ITEMS


def backfill_position(state: dict | None) -> tuple[int | None, bool]:
    """``(cursor, complete)`` from a finecim_sync row of a list entity.

    ``cursor`` is the next backfill page (``last_page`` when the note starts with
    ``backfill``); ``complete`` is True once the whole list has been walked. Rows without
    either marker (never run, or written by an older version) give ``(None, False)``."""
    if not state:
        return None, False
    note = (state.get("note") or "").strip().lower()
    if note.startswith("complete"):
        return None, True
    if note.startswith("backfill") and state.get("last_page"):
        return int(state["last_page"]), False
    return None, False


_AFTER_RE = re.compile(r"\bafter=(\d+)\b")
_RETRY_RE = re.compile(r"\bretry=(\d+)\b")
_HRETRY_RE = re.compile(r"\bhretry=(\d+)\b")


@dataclass
class ResumeState:
    """Where a list entity's walk of one segment stands (see the module docstring).

    ``cursor`` next backfill page (``finecim_sync.last_page``), ``complete`` the whole list
    was walked, ``guard`` head guard item id (``finecim_sync.newest_id``), ``after`` id of
    the last card of the page before the cursor (``after=`` in the note), ``retry`` failed
    attempts at the cursor page (``retry=`` in the note), ``head_retry`` consecutive runs
    whose head scan had failed details (``hretry=`` in the note)."""

    cursor: int | None = None
    complete: bool = False
    guard: int | None = None
    after: int | None = None
    retry: int = 0
    head_retry: int = 0

    @property
    def started(self) -> bool:
        return self.complete or self.cursor is not None

    @property
    def position(self) -> str:
        if self.complete:
            return "complete"
        return "backfill" if self.cursor is not None else "head"

    def set_cursor(self, page: int, after: int | None) -> None:
        if page != self.cursor:
            self.retry = 0
        self.cursor, self.complete, self.after = int(page), False, after

    def finish(self) -> None:
        """The whole list has been walked: nothing pending."""
        self.cursor, self.complete, self.guard, self.after, self.retry = None, True, None, None, 0
        self.head_retry = 0

    def note_prefix(self) -> str:
        parts = [self.position]
        if self.cursor is not None and self.after is not None:
            parts.append(f"after={int(self.after)}")
        if self.cursor is not None and self.retry:
            parts.append(f"retry={int(self.retry)}")
        if self.guard is not None and self.head_retry:
            parts.append(f"hretry={int(self.head_retry)}")
        return "; ".join(parts) + "; "


def resume_state(state: dict | None) -> ResumeState:
    """A ResumeState from a finecim_sync row of a list entity (empty for None)."""
    if not state:
        return ResumeState()
    cursor, complete = backfill_position(state)
    note = state.get("note") or ""
    after = retry = None
    if cursor is not None:
        after = _AFTER_RE.search(note)
        retry = _RETRY_RE.search(note)
    guard = state.get("newest_id")
    head_retry = _HRETRY_RE.search(note) if guard is not None else None
    return ResumeState(
        cursor=cursor,
        complete=complete,
        guard=int(guard) if guard is not None else None,
        after=int(after.group(1)) if after else None,
        retry=int(retry.group(1)) if retry else 0,
        head_retry=int(head_retry.group(1)) if head_retry else 0,
    )


@dataclass
class _PageResult:
    ok: bool = True
    ids: list[int] = field(default_factory=list)
    work: int = 0            # cards that needed a fetch (the early-stop signal)
    fetched: int = 0         # detail fetches attempted on this page (charges the page budget)
    failed: int = 0          # detail fetches that raised
    cut_id: int | None = None  # first card not fetched because the item budget ran out
    at_end: bool = False     # empty page, or the last page of the list


@dataclass
class _SegmentRun:
    stats: SyncStats
    max_items: int | None
    fetched_here: int = 0
    # where the walk is (for recording the position when the login fails mid-run)
    pos_page: int = 1
    pos_item: int | None = None
    # head-scan details that raised in this run (made resumable through the guard)
    in_head: bool = True
    head_failed: list[int] = field(default_factory=list)


def _has_updated_badge(badges: Iterable[str] | None) -> bool:
    return any((b or "").strip().lower() in _UPDATED_BADGES for b in badges or [])


def _first_pdf_attachment(attachments: list[dict] | None) -> str | None:
    """URL of the first attachment that is a PDF (by its URL or name), else None."""
    for a in attachments or []:
        url = a.get("url") or ""
        name = (a.get("name") or "").lower()
        if url and ("/media/pdf/" in url or url.lower().split("?")[0].endswith(".pdf") or name.endswith(".pdf")):
            return url
    return None


def needs_fetch(item: dict, known: bool, stored_date: str | None, card_date_field: str | None,
                date_proves_current: bool = False) -> bool:
    """The incremental rule for one list card (see module docstring)."""
    if not known:
        return True
    card_date = item.get(card_date_field) if card_date_field else None
    if card_date and (stored_date is None or card_date > stored_date[:10]):
        return True
    if _has_updated_badge(item.get("badges")):
        # Only an update date (campaigns) that is not newer than the stored one proves the
        # stored copy is current; a publish date (news, mystery) says nothing about updates.
        return not (date_proves_current and card_date and stored_date)
    return False


class FinecimSync:
    def __init__(self, client: FinecimClient | None, db: Database | None,
                 config_dir: str | os.PathLike, *, logger: logging.Logger | None = None) -> None:
        """``client`` and ``db`` may be None for a plan-only instance (``plan``, dry runs)."""
        self.client = client
        self.db = db
        self.config_dir = Path(config_dir)
        self.log = logger or logging.getLogger(__name__)
        if db is not None and getattr(db, "finecim_config_dir", None) is None:
            db.finecim_config_dir = str(self.config_dir)
        #: Today's date (UTC); replaceable in tests. Decides which summary months are "recent".
        self.today: Callable[[], date] = lambda: datetime.now(UTC).date()
        # /subjekty results of the current sync_all run (slug -> subjects); None outside it.
        self._subject_cache: dict[str, list[dict]] | None = None

        self.finecim_cfg = _read_yaml(self.config_dir / "finecim.yaml")
        segments_cfg = _read_yaml(self.config_dir / "segments.yaml")
        # FINeCIM slug -> segmenty.id
        self.slug_to_segment: dict[str, str] = {}
        for seg in segments_cfg.get("segmenty") or []:
            slug = seg.get("finecim_slug")
            if slug:
                self.slug_to_segment[str(slug)] = str(seg["id"])
        fc_segments = self.finecim_cfg.get("segments") or {}
        for slug in fc_segments:
            self.slug_to_segment.setdefault(str(slug), str(slug))
        self.segment_slugs: list[str] = [str(s) for s in fc_segments] or list(self.slug_to_segment)
        self.has_products = {
            str(slug): bool((cfg or {}).get("has_products", True)) for slug, cfg in fc_segments.items()
        }
        self.subject_map: dict[int, str] = {
            int(k): str(v) for k, v in (self.finecim_cfg.get("subject_to_competitor") or {}).items() if v
        }

    # ── helpers ──────────────────────────────────────────────────

    def _resolve_segments(self, segments: Iterable[str] | None) -> list[str]:
        """Segment arguments (FINeCIM slugs or segmenty ids) -> FINeCIM slugs."""
        if not segments:
            return list(self.segment_slugs)
        by_id = {v: k for k, v in self.slug_to_segment.items()}
        out = []
        for seg in segments:
            slug = seg if seg in self.slug_to_segment else by_id.get(seg)
            if slug is None:
                raise ValueError(f"Unknown FINeCIM segment: {seg!r} (known: {', '.join(self.segment_slugs)})")
            if slug not in out:
                out.append(slug)
        return out

    @staticmethod
    def _resolve_entities(entities: Iterable[str]) -> list[str]:
        wanted = list(entities)
        unknown = [e for e in wanted if e not in SYNC_TARGETS]
        if unknown:
            raise ValueError(f"Unknown FINeCIM entities: {unknown} (known: {', '.join(SYNC_TARGETS)})")
        return wanted

    def _segment_id(self, slug: str | None, fallback_slug: str) -> str:
        if slug and slug in self.slug_to_segment:
            return self.slug_to_segment[slug]
        return self.slug_to_segment[fallback_slug]

    def _slug_for_segment(self, segment_id: str) -> str:
        """FINeCIM slug of a segmenty id (the id itself when no slug is configured)."""
        for slug, seg_id in self.slug_to_segment.items():
            if seg_id == segment_id:
                return slug
        return segment_id

    @staticmethod
    def _list_url(slug: str, path: str) -> str:
        return f"/cz/domena/{slug}/{path}"

    def _get_list_page(self, slug: str, path: str, page: int) -> tuple[str, str]:
        params: dict[str, Any] = {"step": LIST_STEP}
        if page > 1:
            params["page"] = page
        url = FinecimClient.absolute(self._list_url(slug, path))
        return self.client.get(url, params=params), url

    def _subject_ids(self, related: list[dict] | None) -> list[int]:
        return list(dict.fromkeys(int(r["id"]) for r in related or [] if r.get("id") is not None))

    def _mapped_competitor(self, related: list[dict] | None) -> str | None:
        """Competitor of the first related subject that is mapped to a configured
        competitor (``subject_to_competitor``); None when no related subject is mapped."""
        for rel in related or []:
            sid = rel.get("id")
            if sid is not None and int(sid) in self.subject_map:
                return self.db.ensure_competitor_for_subject(int(sid), rel.get("name") or "")
        return None

    def _required_competitor(self, related: list[dict] | None) -> str:
        """Mapped competitor, else the first related subject's (auto-created) competitor,
        else the placeholder competitor."""
        mapped = self._mapped_competitor(related)
        if mapped:
            return mapped
        for rel in related or []:
            if rel.get("id") is not None:
                return self.db.ensure_competitor_for_subject(int(rel["id"]), rel.get("name") or "")
        return self.db.ensure_competitor_for_subject(0, "FINeCIM (nepřiřazeno)")

    def _ensure_subjects(self, related: list[dict] | None) -> None:
        """A minimal finecim_subjekty row (name and url from the related widget) for every
        related subject id that has none yet, so joins over finecim_vazby keep it."""
        for rel in related or []:
            sid = rel.get("id")
            if sid is None or self.db.get_finecim_subject(int(sid)) is not None:
                continue
            competitor = None
            if int(sid) in self.subject_map:
                competitor = self.db.ensure_competitor_for_subject(int(sid), rel.get("name") or "")
            self.db.upsert_finecim_subject(
                int(sid), rel.get("name") or f"FINeCIM subjekt {sid}", competitor, rel.get("url"), [],
            )

    def _ensured(self, related: list[dict] | None) -> list[dict] | None:
        self._ensure_subjects(related)
        return related

    def _link_subjects(self, entity_type: str, entity_id: str, related: list[dict] | None) -> None:
        self._ensure_subjects(related)
        self.db.replace_vazby(entity_type, entity_id, self._subject_ids(related))

    def _record_segment(self, entity: str, segment_id: str, stats: SyncStats, *,
                        newest_id: int | None = None, failed: bool = False,
                        resume: ResumeState | None = None) -> None:
        """Write the finecim_sync row. For list entities ``resume`` gives ``last_page`` (the
        cursor), ``newest_id`` (the head guard, also when it is cleared) and the start of
        the note (position and markers, see ResumeState.note_prefix); the run counters
        follow. Other entities pass ``newest_id`` (the newest id seen) when known."""
        now = _now_iso()
        counters = (f"fetched={stats.fetched} inserted={stats.inserted} updated={stats.updated} "
                    f"skipped={stats.skipped} errors={stats.errors} pages={stats.pages}")
        fields: dict[str, Any] = {"last_run_at": now}
        if resume is not None:
            fields["last_page"] = resume.cursor
            fields["newest_id"] = resume.guard
            fields["note"] = resume.note_prefix() + counters
        else:
            fields["note"] = counters
            if newest_id is not None:
                fields["newest_id"] = newest_id
        if not failed and stats.errors == 0:
            fields["last_success_at"] = now
        try:
            self.db.set_finecim_sync(entity, segment_id, **fields)
        except Exception:  # bookkeeping must never abort the run
            self.log.exception("Could not record finecim_sync for %s/%s", entity, segment_id)

    def _stored_date(self, entity: str, finecim_id: int) -> str | None:
        return self.db.known_finecim_ids(entity, [finecim_id]).get(finecim_id)

    def _count_result(self, stats: SyncStats, inserted: bool) -> None:
        stats.fetched += 1
        if inserted:
            stats.inserted += 1
        else:
            stats.updated += 1

    # ── plan (dry run) ───────────────────────────────────────────

    def plan(self, entities: Iterable[str] = ENTITIES, segments=None, *, max_pages: int | None = None,
             full: bool = False, max_items: int | None = None) -> list[dict]:
        """What ``sync_all`` would do, without network or writes: one row per step and
        segment with ``entity``, ``segment`` (slug), ``segment_id``, ``budget`` (list pages,
        None = unlimited; list entities only), ``items`` (detail fetches, None = unlimited;
        list entities only), ``cursor``, ``complete``, ``guard`` (pending head guard id) and
        ``skip`` (a reason or None). The taxonomy step always comes first. Raises
        ValueError for unknown entities or segments."""
        wanted = self._resolve_entities(entities)
        slugs = self._resolve_segments(segments)
        rows = []
        for entity in SYNC_TARGETS:
            if entity != "taxonomy" and entity not in wanted:
                continue
            for slug in slugs:
                segment_id = self.slug_to_segment[slug]
                row: dict[str, Any] = {"entity": entity, "segment": slug, "segment_id": segment_id,
                                       "budget": None, "items": None, "cursor": None, "complete": False,
                                       "guard": None, "skip": None}
                if entity in _LIST_ENTITIES:
                    row["budget"] = page_budget(max_pages, full)
                    row["items"] = item_budget(max_items, full)
                    if entity == "product" and not self.has_products.get(slug, True):
                        row["skip"] = "no products tab"
                    state = None
                    if self.db is not None:
                        try:
                            state = self.db.get_finecim_sync(entity, segment_id)
                        except Exception:  # no schema yet
                            state = None
                    resume = resume_state(state)
                    row["cursor"], row["complete"], row["guard"] = resume.cursor, resume.complete, resume.guard
                rows.append(row)
        return rows

    # ── taxonomy / companies ─────────────────────────────────────

    def seed_taxonomy(self) -> None:
        """Offline part of the taxonomy: segments + product lines from segments.yaml and the
        subject seed from finecim.yaml (no network)."""
        self.db.seed_segments(str(self.config_dir))
        for slug, subjects in (self.finecim_cfg.get("subjects") or {}).items():
            if slug not in self.slug_to_segment:
                continue
            segment_id = self.slug_to_segment[slug]
            for sid, name in (subjects or {}).items():
                sid = int(sid)
                competitor = (
                    self.db.ensure_competitor_for_subject(sid, name or "") if sid in self.subject_map else None
                )
                self.db.upsert_finecim_subject(sid, name or "", competitor, None, [segment_id])

    def sync_taxonomy(self, segments: list[str] | None = None) -> SyncStats:
        """Segments + product lines from config, then the subjects of every segment from
        its /subjekty page (one request per segment)."""
        self.seed_taxonomy()
        total = SyncStats()
        for slug in self._resolve_segments(segments):
            segment_id = self.slug_to_segment[slug]
            stats = SyncStats()
            try:
                self._sync_subject_list(slug, stats)
            except FinecimAuthError:
                self._record_segment("taxonomy", segment_id, stats, failed=True)
                raise
            except Exception:
                stats.errors += 1
                self.log.exception("FINeCIM subject list failed for %s", slug)
            self._record_segment("taxonomy", segment_id, stats)
            total.add(stats)
        return total

    def _sync_subject_list(self, slug: str, stats: SyncStats) -> list[dict]:
        segment_id = self.slug_to_segment[slug]
        url = FinecimClient.absolute(self._list_url(slug, "subjekty"))
        html = self.client.get(url)
        stats.pages += 1
        subjects = parsers.parse_subject_list(html, url)
        for subj in subjects:
            sid = subj.get("id")
            if sid is None:
                continue
            existed = self.db.get_finecim_subject(sid) is not None
            competitor = (
                self.db.ensure_competitor_for_subject(sid, subj.get("name") or "")
                if sid in self.subject_map else None
            )
            self.db.upsert_finecim_subject(
                sid, subj.get("name") or "", competitor, subj.get("url"), [segment_id],
                logo_url=subj.get("logo_url"),
            )
            if not existed:
                stats.inserted += 1
        if self._subject_cache is not None:
            self._subject_cache[slug] = subjects
        return subjects

    def _profile_competitor(self, sid: int) -> str | None:
        """Competitor id a subject's profile would be stored under (without creating one)."""
        if sid in self.subject_map:
            return self.subject_map[sid]
        row = self.db.get_finecim_subject(sid)
        return (row or {}).get("competitor_id") or f"fc_{sid}"

    def _has_profile(self, competitor_id: str | None) -> bool:
        if not competitor_id:
            return False
        return self.db.conn.execute(
            "SELECT 1 FROM spolecnost_detail WHERE competitor_id = ?", (competitor_id,)
        ).fetchone() is not None

    def profile_fetched_at(self, sid: int) -> str | None:
        """When the profile of subject ``sid`` was last fetched successfully (ISO, UTC).

        Kept in finecim_sync (entity PROFILE_SYNC_ENTITY, segment_id = subject id): neither
        spolecnost_detail.posledni_aktualizace nor finecim_subjekty.aktualizace records the
        fetch (both hold the site's own update date) and pridano_at is the insert time."""
        state = self.db.get_finecim_sync(PROFILE_SYNC_ENTITY, str(int(sid)))
        return (state or {}).get("last_success_at")

    def _profile_refresh_due(self, sid: int, full: bool) -> bool:
        if full or not self._has_profile(self._profile_competitor(sid)):
            return True
        fetched = self.profile_fetched_at(sid)
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=PROFILE_REFRESH_DAYS)
        return not fetched or fetched < cutoff.isoformat(timespec="seconds")

    def sync_companies(self, segments: list[str] | None = None, *, all_companies: bool = False,
                       full: bool = False, max_items: int | None = None) -> SyncStats:
        """Subjects from each segment's /subjekty page, then company profiles for subjects
        mapped to a configured competitor (every subject with ``all_companies``).

        A profile is fetched when none is stored yet, when that subject's last profile fetch
        (see ``profile_fetched_at``) is older than PROFILE_REFRESH_DAYS, or always with
        ``full``. Inside ``sync_all`` the /subjekty pages read by the taxonomy step are reused."""
        total = SyncStats()
        done: set[int] = set()
        for slug in self._resolve_segments(segments):
            segment_id = self.slug_to_segment[slug]
            stats = SyncStats()
            subjects = (self._subject_cache or {}).get(slug)
            if subjects is None:
                try:
                    subjects = self._sync_subject_list(slug, stats)
                except FinecimAuthError:
                    raise
                except Exception as exc:
                    stats.errors += 1
                    self.log.warning("FINeCIM subject list failed for %s: %s", slug, exc)
                    self._record_segment("company", segment_id, stats, failed=True)
                    total.add(stats)
                    continue
            fetched_here = 0
            for subj in subjects:
                sid = subj.get("id")
                if sid is None or sid in done:
                    continue
                if not all_companies and sid not in self.subject_map:
                    stats.skipped += 1
                    continue
                if not self._profile_refresh_due(sid, full):
                    stats.skipped += 1
                    continue
                if max_items is not None and fetched_here >= max_items:
                    stats.skipped += 1
                    continue
                done.add(sid)
                fetched_here += 1
                existed = self._has_profile(self._profile_competitor(sid))
                try:
                    self._sync_company_profile(subj, segment_id, slug)
                    self._count_result(stats, inserted=not existed)
                except FinecimAuthError:
                    raise
                except Exception as exc:
                    stats.errors += 1
                    self.log.warning("FINeCIM company profile %s failed: %s", sid, exc)
                    self._record_profile_fetch(sid, None, ok=False)
            self._record_segment("company", segment_id, stats)
            total.add(stats)
        return total

    def _record_profile_fetch(self, sid: int, competitor_id: str | None, *, ok: bool) -> None:
        now = _now_iso()
        fields: dict[str, Any] = {"last_run_at": now}
        if ok:
            fields["last_success_at"] = now
            fields["note"] = f"profile of {competitor_id}"
        try:
            self.db.set_finecim_sync(PROFILE_SYNC_ENTITY, str(int(sid)), **fields)
        except Exception:  # bookkeeping must never abort the run
            self.log.exception("Could not record the profile fetch of subject %s", sid)

    def _sync_company_profile(self, subj: dict, segment_id: str, slug: str | None = None) -> None:
        sid = int(subj["id"])
        slug = slug or self._slug_for_segment(segment_id)
        url = subj.get("url") or FinecimClient.absolute(f"/cz/domena/{slug}/subjekt/{sid}")
        html = self.client.get(url)
        d = parsers.parse_subject_detail(html, url)
        name = d.get("name") or subj.get("name") or ""
        competitor_id = self.db.ensure_competitor_for_subject(sid, name)
        self.db.upsert_finecim_subject(
            sid, subj.get("name") or name, competitor_id, subj.get("url") or d.get("url"), [segment_id],
            logo_url=d.get("logo_url") or subj.get("logo_url"), aktualizace=d.get("updated_date"),
        )
        self.db.upsert_spolecnost_detail(competitor_id, {
            "popis": d.get("description_text"),
            "zakladni_kapital": d.get("share_capital"),
            "sidlo": d.get("address"),
            "akcionar": d.get("shareholder"),
            "pocet_klientu": d.get("clients"),
            "pocet_pobocek": d.get("branches"),
            "pocet_bankomatu": d.get("atms"),
            "socialni_site": d.get("social_links") or {},
            "predstavenstvo": d.get("board") or [],
            "posledni_aktualizace": d.get("updated_date"),
            "ico": d.get("ico"),
        })
        self.db.replace_prilohy(
            "spolecnost", competitor_id,
            [{"nazev": a.get("name"), "url": a.get("url")} for a in d.get("attachments") or []],
        )
        self._record_profile_fetch(sid, competitor_id, ok=True)

    # ── list-driven entities ─────────────────────────────────────

    def _scan_page(self, entity: str, slug: str, page: int, run: _SegmentRun, seen: set[int],
                   process: Callable[[dict, str], bool]) -> _PageResult:
        """Read one list page and fetch, in list order, the cards that need it, until the
        item budget runs out (``cut_id``). FinecimAuthError propagates."""
        path, list_parser, _ = _LIST_ENTITIES[entity]
        date_field = _CARD_DATE_FIELD[entity]
        date_proves_current = entity in _DATE_PROVES_CURRENT
        stats = run.stats
        run.pos_page, run.pos_item = page, None
        try:
            html, url = self._get_list_page(slug, path, page)
            items = list_parser(html, url)
            pagination = parsers.parse_pagination(html)
        except FinecimAuthError:
            raise
        except Exception as exc:
            stats.errors += 1
            self.log.warning("FINeCIM %s list %s page %d failed: %s", entity, slug, page, exc)
            return _PageResult(ok=False)
        stats.pages += 1
        ids = [it["id"] for it in items if it.get("id") is not None]
        # Trust the last page only when the footer states it (the "last" anchor or the
        # total); otherwise keep reading until an empty page.
        last_known = "kt-pagination__link--last" in html or pagination.get("total") is not None
        result = _PageResult(
            ids=ids,
            at_end=not items or (last_known and page >= (pagination.get("last_page") or page)),
        )
        # Known is by id alone: a card listed here whose URL slug is another segment is
        # stored under that slug and still counts as known (no refetch, early stop holds).
        known = self.db.known_finecim_ids(entity, ids) if ids else {}
        for item in items:
            item_id = item.get("id")
            if item_id is None:
                continue
            if item_id in seen:
                stats.skipped += 1
                continue
            if not needs_fetch(item, item_id in known, known.get(item_id), date_field,
                               date_proves_current):
                stats.skipped += 1
                continue
            if run.max_items is not None and run.fetched_here >= run.max_items:
                result.cut_id = item_id
                break
            result.work += 1
            result.fetched += 1
            run.fetched_here += 1
            seen.add(item_id)
            run.pos_item = item_id
            stored_before = known.get(item_id)
            try:
                inserted = process(item, slug)
                self._count_result(stats, inserted)
            except FinecimAuthError:
                raise
            except Exception as exc:
                stats.errors += 1
                result.failed += 1
                if run.in_head:
                    run.head_failed.append(item_id)
                self.log.warning("FINeCIM %s %s failed: %s", entity, item.get("url"), exc)
                continue
            if (date_field is None and stored_before is not None
                    and self._stored_date(entity, item_id) == stored_before):
                # No card date (products): a refetch triggered only by a persistent
                # 'updated' badge that found the same update date does not count as
                # new work, so the early stop still applies.
                result.work -= 1
        run.pos_item = None
        return result

    def _sync_list_entity(self, entity: str, segments: list[str] | None, *, max_pages: int | None,
                          full: bool, max_items: int | None,
                          process: Callable[[dict, str], bool]) -> SyncStats:
        budget = page_budget(max_pages, full)
        items_budget = item_budget(max_items, full)
        total = SyncStats()
        # ids handled in this run: an item listed in several segments (or on several pages)
        # is fetched at most once per run.
        seen: set[int] = set()
        for slug in self._resolve_segments(segments):
            if entity == "product" and not self.has_products.get(slug, True):
                continue
            segment_id = self.slug_to_segment[slug]
            run = _SegmentRun(stats=SyncStats(), max_items=items_budget)
            state = resume_state(self.db.get_finecim_sync(entity, segment_id))
            try:
                failed = self._walk_segment(entity, slug, run, seen, process, budget, full, state)
            except FinecimAuthError:
                self._keep_head_failures(entity, slug, run, state)
                self._record_segment(entity, segment_id, run.stats, failed=True, resume=state)
                raise
            self._keep_head_failures(entity, slug, run, state)
            self._record_segment(entity, segment_id, run.stats, failed=failed, resume=state)
            total.add(run.stats)
        return total

    def _keep_head_failures(self, entity: str, slug: str, run: _SegmentRun,
                            state: ResumeState) -> None:
        """Make the details that failed during the head scan resumable.

        A failed card is not stored, but the head scan has moved past it, and the next
        plain run would early-stop above it. So the smallest failed id becomes the guard
        (the smaller of it and any pending guard wins; this also holds after the list was
        marked complete): the next head scan cannot early-stop before it has seen that
        card's page again, where the card is still unknown and is fetched. Up to
        MAX_PAGE_ATTEMPTS consecutive runs with head failures keep it (``hretry=N``); after
        that the guard is not extended and a warning names the cards."""
        if not run.head_failed:
            state.head_retry = 0
            return
        attempts = state.head_retry + 1
        if attempts >= MAX_PAGE_ATTEMPTS:
            self.log.warning("FINeCIM %s %s: details %s still failed after %d runs; the head "
                             "scan no longer returns to them", entity, slug,
                             sorted(run.head_failed, reverse=True), attempts)
            state.head_retry = 0
            return
        mark = min(run.head_failed)
        state.guard = mark if state.guard is None else min(state.guard, mark)
        state.head_retry = attempts

    @staticmethod
    def _head_cut(state: ResumeState, page: int, cut_id: int | None, prev_ids: list[int] | None) -> None:
        """The head scan stops before its early stop: everything above ``cut_id`` on
        ``page`` (above the whole page when ``cut_id`` is None) has been processed in this
        run; ``prev_ids`` are the ids of page ``page - 1`` (read in this run).

        A segment that was never walked, or whose cursor is at or before ``page``, gets
        the cursor ``page`` (the backfill covers everything from there; no guard needed).
        Otherwise the guard records the cut; an older guard this run did not get past has
        the smaller id and is kept."""
        prev_last = min(prev_ids) if prev_ids else None
        if page <= 1 and cut_id is None:
            return  # nothing was read: the stored state still holds
        if not state.started or (state.cursor is not None and state.cursor <= page):
            state.set_cursor(page, prev_last)
            state.guard = None
            return
        mark = cut_id if cut_id is not None else prev_last
        if mark is not None:
            state.guard = mark if state.guard is None else min(state.guard, mark)

    def _walk_segment(self, entity: str, slug: str, run: _SegmentRun, seen: set[int],
                      process: Callable[[dict, str], bool], budget: int | None, full: bool,
                      state: ResumeState) -> bool:
        """Head scan, then backfill from the cursor (see the module docstring). ``state``
        is updated in place, also when the login fails mid-run (FinecimAuthError is
        re-raised after the position reached is recorded in it). Returns True when a list
        page failed."""
        used = 0   # pages charged to the page budget
        free = 0   # free pages (capped by MAX_FREE_PAGES)
        read: dict[int, list[int]] = {}  # ids of the head pages read in this run
        guard = state.guard
        page = 1

        def out_of_pages() -> bool:
            return budget is not None and used >= budget

        def out_of_free_pages() -> bool:  # only a run with a page budget has the cap
            return budget is not None and free >= MAX_FREE_PAGES

        # -- head scan --
        try:
            while True:
                res = self._scan_page(entity, slug, page, run, seen, process)
                if not res.ok:
                    self._head_cut(state, page, None, read.get(page - 1))
                    return True
                read[page] = res.ids
                if res.cut_id is not None:  # item budget spent: read this page again next run
                    self._head_cut(state, page, res.cut_id, read.get(page - 1))
                    return False
                if res.at_end:
                    state.finish()
                    return False
                if res.fetched:
                    used += 1
                else:
                    free += 1
                below_guard = guard is None or (bool(res.ids) and max(res.ids) < guard)
                if not full and res.work == 0 and below_guard:
                    break  # early stop
                if out_of_pages():
                    self._head_cut(state, page + 1, None, res.ids)
                    return False
                if out_of_free_pages():
                    # Runaway stop: every page so far is processed, so the cursor can take
                    # over from the next page (no guard needed below it).
                    self.log.warning("FINeCIM %s %s: %d list pages without anything to fetch; "
                                     "the backfill continues from page %d", entity, slug, free, page + 1)
                    state.set_cursor(page + 1, min(res.ids) if res.ids else None)
                    state.guard = None
                    return False
                page += 1
        except FinecimAuthError:
            self._head_cut(state, run.pos_page, run.pos_item, read.get(run.pos_page - 1))
            raise

        # -- early stop on ``page``: the head is done --
        run.in_head = False
        state.guard = None
        if state.complete:
            return False
        anchored = False
        if state.cursor is None or state.cursor <= page + 1:
            state.set_cursor(page + 1, min(read[page]) if read[page] else None)
            anchored = True

        # -- backfill --
        # Unless the head has just read the page before the cursor, start one page earlier
        # and check that it still reaches ``after`` (removed items move cards up).
        anchored = anchored or state.after is None or state.cursor <= 1
        p = state.cursor if anchored else state.cursor - 1
        while state.cursor is not None and not out_of_pages() and not out_of_free_pages():
            if not anchored and p <= page:
                # stepped back into the pages this head scan has just covered
                anchored = True
                state.set_cursor(page + 1, min(read[page]) if read[page] else None)
                p = state.cursor
                continue
            res = self._scan_page(entity, slug, p, run, seen, process)
            if not res.ok:
                return True
            # every backfill page counts; only a check page (before the cursor) that
            # needed no fetch is free
            if res.fetched or anchored:
                used += 1
            else:
                free += 1
            if res.cut_id is not None:
                return False  # item budget spent: the cursor stays, the page is read again
            if not anchored:
                if p > 1 and (not res.ids or max(res.ids) < state.after):
                    p -= 1  # cards moved up past the cursor: step back
                    continue
                anchored = True
            if not res.ids:
                state.finish()
                return False
            if res.failed:
                attempts = state.retry + 1
                if attempts < MAX_PAGE_ATTEMPTS:
                    if p != state.cursor:
                        state.set_cursor(p, state.after)
                    state.retry = attempts
                    return False
                self.log.warning("FINeCIM %s %s: list page %d still has failed details after %d "
                                 "attempts; the backfill moves on", entity, slug, p, attempts)
            if res.at_end:
                state.finish()
                return False
            state.set_cursor(p + 1, min(res.ids))
            p += 1
        return False

    def sync_news(self, segments=None, *, max_pages: int | None = None, full: bool = False,
                  max_items: int | None = None) -> SyncStats:
        return self._sync_list_entity("news", segments, max_pages=max_pages, full=full,
                                      max_items=max_items, process=self._process_news)

    def sync_campaigns(self, segments=None, *, max_pages=None, full=False, max_items=None) -> SyncStats:
        return self._sync_list_entity("campaign", segments, max_pages=max_pages, full=full,
                                      max_items=max_items, process=self._process_campaign)

    def sync_mystery(self, segments=None, *, max_pages=None, full=False, max_items=None) -> SyncStats:
        return self._sync_list_entity("mystery", segments, max_pages=max_pages, full=full,
                                      max_items=max_items, process=self._process_mystery)

    def sync_products(self, segments=None, *, max_pages=None, full=False, max_items=None) -> SyncStats:
        return self._sync_list_entity("product", segments, max_pages=max_pages, full=full,
                                      max_items=max_items, process=self._process_product)

    # ── per-item processing (fetch everything first, then write) ──

    def _process_news(self, item: dict, slug: str) -> bool:
        html = self.client.get(item["url"])
        d = parsers.parse_news_detail(html, item["url"])
        datum = d.get("date") or item.get("date")
        if not datum:
            raise parsers.ParseError(f"news {item['id']} has no date")
        entity_id = f"fc-news-{d.get('id') or item['id']}"
        related = d.get("related_subjects")
        self._ensure_subjects(related)
        row = {
            "id": entity_id,
            "competitor_id": self._mapped_competitor(related),
            "segment_id": self._segment_id(d.get("segment") or item.get("segment"), slug),
            "produktova_linie_id": None,
            "nazev": d.get("title") or item.get("title") or entity_id,
            "datum": datum,
            "typ_zpravy": ", ".join(d.get("news_types") or []) or None,
            "stav": (d.get("badges") or item.get("badges") or ["new"])[0],
            "perex": d.get("perex") or item.get("annotation"),
            "telo": d.get("body_html"),
            "tagy": [t["name"] for t in (d.get("tags") or item.get("tags") or []) if t.get("name")],
            "zdrojovy_signal_id": None,
            "url": d.get("url") or item["url"],
        }
        inserted = self.db.upsert_clanek(row)
        self._link_subjects("clanek", entity_id, related)
        return inserted

    def _process_campaign(self, item: dict, slug: str) -> bool:
        html = self.client.get(item["url"])
        d = parsers.parse_campaign_detail(html, item["url"])
        campaign_id = d.get("id") or item["id"]
        entity_id = f"fc-campaign-{campaign_id}"
        creatives: dict[str, dict] = {}
        for media in d.get("media") or []:
            if not media.get("creatives_url"):
                continue
            fragment = self.client.get_fragment(media["creatives_url"])
            for index, c in enumerate(parsers.parse_campaign_creatives(fragment, d.get("url") or item["url"])):
                cid = (f"fc-creative-{c['creative_id']}" if c.get("creative_id") is not None
                       else f"fc-creative-{campaign_id}-{media.get('type')}-{index}")
                creatives.setdefault(cid, {
                    "id": cid,
                    "datum": c.get("date"),
                    "media_typ": media.get("type"),
                    "popis": c.get("text"),
                    "media_url": c.get("media_url"),
                    "media_druh": c.get("media_kind"),
                })
        media_types = [m["type"] for m in d.get("media") or [] if m.get("type")] or item.get("media_types") or []
        row = {
            "id": entity_id,
            "competitor_id": self._required_competitor(self._ensured(d.get("related_subjects"))),
            "segment_id": self._segment_id(d.get("segment") or item.get("segment"), slug),
            "nazev": d.get("title") or item.get("title") or entity_id,
            "zacatek": d.get("created_date") or item.get("start_date"),
            "aktualizace": d.get("updated_date") or item.get("updated_date"),
            "popis": d.get("annotation") or item.get("annotation"),
            "media_typy": list(dict.fromkeys(media_types)),
            "typ_kampane": ", ".join(d.get("campaign_types") or []) or None,
            "kreativa_url": d.get("key_visual_url") or item.get("thumbnail_url"),
        }
        inserted = self.db.upsert_kampan(row)
        self.db.replace_kampan_kreativy(entity_id, list(creatives.values()))
        self._link_subjects("kampan", entity_id, d.get("related_subjects"))
        return inserted

    def _process_mystery(self, item: dict, slug: str) -> bool:
        html = self.client.get(item["url"])
        d = parsers.parse_mystery_detail(html, item["url"])
        datum = d.get("date") or item.get("date")
        if not datum:
            raise parsers.ParseError(f"mystery shopping {item['id']} has no date")
        entity_id = f"fc-ms-{d.get('id') or item['id']}"
        popis = "\n\n".join(p for p in (d.get("perex"), d.get("body_text")) if p) or item.get("annotation")
        row = {
            "id": entity_id,
            "competitor_id": self._mapped_competitor(self._ensured(d.get("related_subjects"))),
            "segment_id": self._segment_id(d.get("segment") or item.get("segment"), slug),
            "nazev": d.get("title") or item.get("title") or entity_id,
            "datum": datum,
            "popis": popis,
            "pdf_url": d.get("pdf_url") or _first_pdf_attachment(d.get("attachments")),
        }
        inserted = self.db.upsert_mystery(row)
        self.db.replace_prilohy(
            "mystery", entity_id,
            [{"nazev": a.get("name"), "url": a.get("url")} for a in d.get("attachments") or []],
        )
        self._link_subjects("mystery", entity_id, d.get("related_subjects"))
        return inserted

    def _process_product(self, item: dict, slug: str) -> bool:
        html = self.client.get(item["url"])
        d = parsers.parse_product_detail(html, item["url"])
        parameters: list[dict] = []
        if d.get("parameters_url"):
            parameters = parsers.parse_product_parameters(self.client.get(d["parameters_url"]))
        entity_id = f"fc-product-{d.get('id') or item['id']}"
        segment_id = self._segment_id(d.get("segment") or item.get("segment"), slug)
        line_name = d.get("product_line") or item.get("product_line")
        row = {
            "id": entity_id,
            "competitor_id": self._required_competitor(self._ensured(d.get("related_subjects"))),
            "segment_id": segment_id,
            "produktova_linie_id": (
                self.db.resolve_produktova_linie(segment_id, nazev=line_name) if line_name else None
            ),
            "zakaznicky_segment": d.get("customer_segment") or item.get("customer_segment"),
            "nazev": d.get("title") or item.get("title") or entity_id,
            "kratky_popis": d.get("annotation") or item.get("annotation"),
            "atributy": [
                {"section": p.get("section"), "name": p.get("name"), "value": p.get("value")}
                for p in parameters
            ],
            "url": d.get("url") or item["url"],
            "aktivni": 1,
            "aktualizace": d.get("updated_date"),
        }
        inserted = self.db.upsert_produkt(row)
        self._link_subjects("produkt", entity_id, d.get("related_subjects"))
        return inserted

    # ── executive summaries ──────────────────────────────────────

    def sync_summaries(self, segments=None, *, years: list[int] | None = None,
                       max_items: int | None = None) -> SyncStats:
        """List page per segment, then every month page not stored yet, plus the months of
        the current and the previous calendar month (they fill in during the month) and
        (with ``years``) every stored month of those years again."""
        total = SyncStats()
        wanted_years = {int(y) for y in years} if years else None
        recent = self.recent_summary_months()
        for slug in self._resolve_segments(segments):
            segment_id = self.slug_to_segment[slug]
            stats = SyncStats()
            url = FinecimClient.absolute(self._list_url(slug, "executive-summary"))
            try:
                months = parsers.parse_executive_summary_list(self.client.get(url), url)
            except FinecimAuthError:
                raise
            except Exception as exc:
                stats.errors += 1
                self.log.warning("FINeCIM executive-summary list %s failed: %s", slug, exc)
                self._record_segment("summary", segment_id, stats, failed=True)
                total.add(stats)
                continue
            stats.pages += 1
            ids = [m["id"] for m in months if m.get("id") is not None]
            known = self.db.known_finecim_ids("summary", ids) if ids else {}
            fetched_here = 0
            for month in months:
                if month.get("id") is None:
                    continue
                refetch = (
                    (month.get("year"), month.get("month")) in recent
                    or (wanted_years is not None and month.get("year") in wanted_years)
                )
                if month["id"] in known and not refetch:
                    stats.skipped += 1
                    continue
                if max_items is not None and fetched_here >= max_items:
                    stats.skipped += 1
                    continue
                fetched_here += 1
                try:
                    inserted = self._process_summary(month, slug)
                    self._count_result(stats, inserted)
                except FinecimAuthError:
                    self._record_segment("summary", segment_id, stats,
                                         newest_id=max(ids) if ids else None, failed=True)
                    raise
                except Exception as exc:
                    stats.errors += 1
                    self.log.warning("FINeCIM executive summary %s failed: %s", month.get("url"), exc)
            self._record_segment("summary", segment_id, stats, newest_id=max(ids) if ids else None)
            total.add(stats)
        return total

    def recent_summary_months(self) -> set[tuple[int, int]]:
        """(year, month) of the current and the previous calendar month."""
        today = self.today()
        previous = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        return {(today.year, today.month), previous}

    def _process_summary(self, month: dict, slug: str) -> bool:
        if month.get("year") is None or month.get("month") is None:
            raise parsers.ParseError(f"executive summary {month.get('id')} has no year/month")
        html = self.client.get(month["url"])
        d = parsers.parse_executive_summary_detail(html, month["url"])
        summary_id = f"fc-es-{d.get('id') or month['id']}"
        # nazev comes from the list page, like mesic and rok (the year is only known there)
        month_name = month.get("month_name") or d.get("month_name") or str(month["month"])
        entries = d.get("entries") or []
        lines = []
        polozky = []
        for index, e in enumerate(entries):
            title = e.get("title") or ""
            text = e.get("text") or ""
            lines.append(f"- [{title}]({e['news_url']}): {text}" if e.get("news_url") else f"- {title}: {text}")
            entry_id = (f"fc-es-entry-{e['entry_id']}" if e.get("entry_id") is not None
                        else f"fc-es-entry-{d.get('id') or month['id']}-{index}")
            polozky.append({
                "id": entry_id,
                "clanek_id": f"fc-news-{e['news_id']}" if e.get("news_id") is not None else None,
                "nazev": e.get("title"),
                "text": e.get("text"),
                "poradi": index,
            })
        row = {
            "id": summary_id,
            "segment_id": self._segment_id(d.get("segment") or month.get("segment"), slug),
            "rok": int(month["year"]),
            "mesic": int(month["month"]),
            "nazev": f"{month_name} {month['year']}",
            "telo": "\n".join(lines) or None,
            "pdf_url": None,
        }
        return self.db.upsert_executive_summary(row, polozky)

    # ── everything ───────────────────────────────────────────────

    def sync_all(self, entities: Iterable[str] = ENTITIES, segments=None, *, max_pages=None,
                 full: bool = False, all_companies: bool = False,
                 max_items: int | None = None, years: list[int] | None = None) -> dict[str, SyncStats]:
        """The taxonomy first (offline seed + one /subjekty page per segment), then each
        requested entity in ENTITIES order. ``entities`` may also name ``taxonomy`` alone,
        which runs only that step. The result has a ``taxonomy`` entry plus one per entity.
        ``max_pages`` None means DEFAULT_MAX_PAGES per entity and segment and ``max_items``
        None means DEFAULT_MAX_ITEMS detail fetches per list entity and segment (both
        unlimited with ``full``; companies and summaries are not capped by default); see
        the module docstring for the head guard / backfill cursor model. ``years`` is
        passed to sync_summaries (refetch every stored month of those years)."""
        wanted = self._resolve_entities(entities)
        slugs = self._resolve_segments(segments)
        results: dict[str, SyncStats] = {}
        self._subject_cache = {}
        try:
            self.log.info("FINeCIM sync: taxonomy (%d segments)", len(slugs))
            results["taxonomy"] = self.sync_taxonomy(slugs)
            for entity in ENTITIES:
                if entity not in wanted:
                    continue
                self.log.info("FINeCIM sync: %s (%d segments)", entity, len(slugs))
                if entity == "company":
                    results[entity] = self.sync_companies(slugs, all_companies=all_companies, full=full,
                                                          max_items=max_items)
                elif entity == "summary":
                    results[entity] = self.sync_summaries(slugs, years=years, max_items=max_items)
                else:
                    method = {
                        "news": self.sync_news,
                        "campaign": self.sync_campaigns,
                        "mystery": self.sync_mystery,
                        "product": self.sync_products,
                    }[entity]
                    results[entity] = method(slugs, max_pages=max_pages, full=full, max_items=max_items)
                self.log.info("FINeCIM sync %s: %s", entity, results[entity].as_dict())
        finally:
            self._subject_cache = None
        return results
