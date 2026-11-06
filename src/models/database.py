import hashlib
import json
import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import yaml


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

# Placeholder competitor for FINeCIM items without any related company (subject id 0).
FINECIM_PLACEHOLDER_COMPETITOR = "__finecim__"

# Columns added to pre-existing tables for FINeCIM (ALTER TABLE cannot be made idempotent
# in plain SQL, so initialize() adds them when missing).
_EXTRA_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("segmenty", "finecim_slug", "TEXT"),
    ("produktove_linie", "finecim_id", "INTEGER"),
    ("produkty", "aktualizace", "TEXT"),
    ("executive_summary_polozky", "url", "TEXT"),
    ("executive_summary_polozky", "typ", "TEXT"),
)

# entity name -> (table, id prefix, SQL expression of the stored date)
_FINECIM_ENTITY_TABLES: dict[str, tuple[str, str, str]] = {
    "news": ("clanky", "fc-news-", "datum"),
    "campaign": ("kampane", "fc-campaign-", "aktualizace"),
    "mystery": ("mystery_shopping", "fc-ms-", "datum"),
    "product": ("produkty", "fc-product-", "COALESCE(aktualizace, substr(pridano_at, 1, 10))"),
    "summary": ("executive_summary", "fc-es-", "substr(pridano_at, 1, 10)"),
}
_FINECIM_ENTITY_ALIASES = {
    "clanek": "news", "clanky": "news",
    "kampan": "campaign", "kampane": "campaign",
    "mystery-shopping": "mystery", "mystery_shopping": "mystery", "ms": "mystery",
    "produkt": "product", "produkty": "product",
    "executive-summary": "summary", "executive_summary": "summary", "es": "summary",
    "subjekt": "company", "subject": "company", "spolecnost": "company",
}

_FINECIM_SYNC_FIELDS = ("last_run_at", "last_success_at", "last_page", "newest_id", "note")

_subject_map_cache: dict[str, tuple[float, dict[int, str]]] = {}


def load_subject_competitor_map(config_dir: str | os.PathLike | None = None) -> dict[int, str]:
    """Return FINeCIM subject id -> competitor id from ``finecim.yaml`` (``subject_to_competitor``).

    ``config_dir`` defaults to the repository's ``config`` directory. The result is cached
    per file and refreshed when the file's mtime changes. A missing file yields ``{}``.
    """
    base = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    path = base / "finecim.yaml"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    key = str(path.resolve())
    cached = _subject_map_cache.get(key)
    if cached and cached[0] == mtime:
        return dict(cached[1])
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    mapping = {
        int(k): str(v)
        for k, v in (data.get("subject_to_competitor") or {}).items()
        if v
    }
    _subject_map_cache[key] = (mtime, mapping)
    return dict(mapping)


def _db_value(value):
    """Serialise lists/dicts to JSON text and bools to ints for SQLite."""
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return int(value)
    return value


def _insert_sql(table: str, data: dict, verb: str = "INSERT") -> str:
    names = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    return f"{verb} INTO {table} ({names}) VALUES ({marks})"


class Database:
    # Config dir used to look up the FINeCIM subject -> competitor mapping; None = repo config.
    finecim_config_dir: str | os.PathLike | None = None

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def initialize(self):
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        self.conn.executescript(schema)
        self._ensure_extra_columns()
        self.conn.commit()
        logger.info("Database initialized at %s", self.db_path)

    def _table_columns(self, table: str) -> list[str]:
        return [r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})").fetchall()]

    def has_table(self, table: str) -> bool:
        """True when ``table`` exists (a database created before a schema addition may lack it)."""
        return bool(self._table_columns(table))

    def _ensure_extra_columns(self) -> None:
        for table, column, decl in _EXTRA_COLUMNS:
            if column not in self._table_columns(table):
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def close(self):
        self.conn.close()

    # ── Competitors ──────────────────────────────────────────────

    def seed_competitors(self, config_dir: str):
        competitors_dir = Path(config_dir) / "competitors"
        if not competitors_dir.exists():
            logger.warning("No competitors directory at %s", competitors_dir)
            return
        count = 0
        for f in sorted(competitors_dir.glob("*.yaml")):
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            ico = data.get("sources", {}).get("ares_ico")
            self.conn.execute(
                """INSERT INTO competitors (id, name, parent_group, tier, ico, config_path)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     name=excluded.name,
                     parent_group=excluded.parent_group,
                     tier=excluded.tier,
                     ico=excluded.ico,
                     config_path=excluded.config_path""",
                (data["id"], data["name"], data.get("parent_group"),
                 data["tier"], ico, str(f)),
            )
            # M:N vazba na segmenty
            segmenty = data.get("segmenty") or []
            self.conn.execute(
                "DELETE FROM spolecnosti_segmenty WHERE competitor_id = ?",
                (data["id"],),
            )
            for seg_slug in segmenty:
                self.conn.execute(
                    """INSERT OR IGNORE INTO spolecnosti_segmenty (competitor_id, segment_id)
                       SELECT ?, id FROM segmenty WHERE slug = ?""",
                    (data["id"], seg_slug),
                )
            count += 1
        self.conn.commit()
        logger.info("Seeded %d competitors", count)

    # ── Segmenty ─────────────────────────────────────────────────

    def seed_segments(self, config_dir: str):
        """Seed segmenty + produktove_linie from segments.yaml (idempotent).

        Product lines are matched within their segment by id (``<segment>__<slug>``), then by
        ``finecim_id``, then by name, so re-seeding never duplicates a line."""
        segments_path = Path(config_dir) / "segments.yaml"
        if not segments_path.exists():
            logger.warning("No segments.yaml at %s", segments_path)
            return
        data = yaml.safe_load(segments_path.read_text(encoding="utf-8")) or {}
        has_finecim_slug = "finecim_slug" in self._table_columns("segmenty")
        has_finecim_id = "finecim_id" in self._table_columns("produktove_linie")
        count_seg = 0
        count_lin = 0
        for seg in data.get("segmenty") or []:
            seg_id = seg["id"]
            params = (seg_id, seg.get("slug", seg_id), seg["nazev"],
                      seg.get("poradi", 0), 1 if seg.get("ma_produkty", True) else 0)
            if has_finecim_slug:
                self.conn.execute(
                    """INSERT INTO segmenty (id, slug, nazev, poradi, ma_produkty, finecim_slug)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                         slug=excluded.slug,
                         nazev=excluded.nazev,
                         poradi=excluded.poradi,
                         ma_produkty=excluded.ma_produkty,
                         finecim_slug=excluded.finecim_slug""",
                    (*params, seg.get("finecim_slug")),
                )
            else:
                self.conn.execute(
                    """INSERT INTO segmenty (id, slug, nazev, poradi, ma_produkty)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                         slug=excluded.slug,
                         nazev=excluded.nazev,
                         poradi=excluded.poradi,
                         ma_produkty=excluded.ma_produkty""",
                    params,
                )
            count_seg += 1
            for linie in seg.get("produktove_linie") or []:
                linie_id = f"{seg_id}__{linie['slug']}"
                finecim_id = linie.get("finecim_id") if has_finecim_id else None
                existing = self._find_produktova_linie(seg_id, linie_id, finecim_id, linie["nazev"])
                if existing and has_finecim_id:
                    self.conn.execute(
                        """UPDATE produktove_linie
                           SET nazev = ?, finecim_id = COALESCE(?, finecim_id)
                           WHERE id = ?""",
                        (linie["nazev"], finecim_id, existing),
                    )
                elif existing:
                    self.conn.execute(
                        "UPDATE produktove_linie SET nazev = ? WHERE id = ?",
                        (linie["nazev"], existing),
                    )
                elif has_finecim_id:
                    self.conn.execute(
                        """INSERT INTO produktove_linie (id, segment_id, slug, nazev, finecim_id)
                           VALUES (?, ?, ?, ?, ?)""",
                        (linie_id, seg_id, linie["slug"], linie["nazev"], finecim_id),
                    )
                else:
                    self.conn.execute(
                        """INSERT INTO produktove_linie (id, segment_id, slug, nazev)
                           VALUES (?, ?, ?, ?)""",
                        (linie_id, seg_id, linie["slug"], linie["nazev"]),
                    )
                count_lin += 1
        self.conn.commit()
        logger.info("Seeded %d segmenty, %d produktove_linie", count_seg, count_lin)

    def _find_produktova_linie(
        self, segment_id: str, linie_id: str, finecim_id: int | None, nazev: str,
    ) -> str | None:
        """Existing product line in a segment: by id, then by finecim_id, then by name."""
        row = self.conn.execute(
            "SELECT id FROM produktove_linie WHERE id = ? AND segment_id = ?",
            (linie_id, segment_id),
        ).fetchone()
        if row:
            return row["id"]
        return self.resolve_produktova_linie(segment_id, finecim_id=finecim_id, nazev=nazev)

    def resolve_produktova_linie(
        self, segment_id: str, finecim_id: int | None = None, nazev: str | None = None,
    ) -> str | None:
        """Return the produktove_linie id in a segment matching a FINeCIM product-line id or
        a name (case-insensitive, surrounding whitespace ignored), else None."""
        if finecim_id is not None and "finecim_id" in self._table_columns("produktove_linie"):
            row = self.conn.execute(
                "SELECT id FROM produktove_linie WHERE segment_id = ? AND finecim_id = ?",
                (segment_id, int(finecim_id)),
            ).fetchone()
            if row:
                return row["id"]
        if nazev:
            wanted = nazev.strip().casefold()
            rows = self.conn.execute(
                "SELECT id, nazev FROM produktove_linie WHERE segment_id = ? ORDER BY id",
                (segment_id,),
            ).fetchall()
            for r in rows:
                if (r["nazev"] or "").strip().casefold() == wanted:
                    return r["id"]
        return None

    def get_segmenty(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM segmenty ORDER BY poradi, nazev"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_segment(self, slug: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM segmenty WHERE slug = ?", (slug,)
        ).fetchone()
        return dict(row) if row else None

    def get_produktove_linie(self, segment_id: str | None = None) -> list[dict]:
        if segment_id:
            rows = self.conn.execute(
                "SELECT * FROM produktove_linie WHERE segment_id = ? ORDER BY nazev",
                (segment_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM produktove_linie ORDER BY segment_id, nazev"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_companies_in_segment(self, segment_id: str) -> list[dict]:
        rows = self.conn.execute(
            """SELECT c.*
               FROM competitors c
               JOIN spolecnosti_segmenty ss ON ss.competitor_id = c.id
               WHERE ss.segment_id = ?
               ORDER BY c.tier, c.name""",
            (segment_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_company_detail(self, competitor_id: str) -> dict | None:
        row = self.conn.execute(
            """SELECT c.*,
                      d.popis, d.zakladni_kapital, d.sidlo, d.akcionar,
                      d.pocet_klientu, d.pocet_pobocek, d.pocet_bankomatu,
                      d.socialni_site, d.predstavenstvo, d.posledni_aktualizace
               FROM competitors c
               LEFT JOIN spolecnost_detail d ON d.competitor_id = c.id
               WHERE c.id = ?""",
            (competitor_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        seg_rows = self.conn.execute(
            """SELECT s.id, s.slug, s.nazev
               FROM segmenty s
               JOIN spolecnosti_segmenty ss ON ss.segment_id = s.id
               WHERE ss.competitor_id = ?
               ORDER BY s.poradi""",
            (competitor_id,),
        ).fetchall()
        result["segmenty"] = [dict(r) for r in seg_rows]
        return result

    # ── FINeCIM-inspirované gettery ──────────────────────────────

    def get_clanky(
        self,
        segment_id: str | None = None,
        competitor_id: str | None = None,
        produktova_linie_id: str | None = None,
        typ_zpravy: str | None = None,
        tag: str | None = None,
        od: str | None = None,
        do: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        query = "SELECT * FROM clanky WHERE 1=1"
        params: list = []
        if segment_id:
            query += " AND segment_id = ?"
            params.append(segment_id)
        if competitor_id:
            query += " AND competitor_id = ?"
            params.append(competitor_id)
        if produktova_linie_id:
            query += " AND produktova_linie_id = ?"
            params.append(produktova_linie_id)
        if typ_zpravy:
            query += " AND typ_zpravy = ?"
            params.append(typ_zpravy)
        if tag:
            # tagy je JSON array stored as TEXT; LIKE matching na uvozovkách
            query += " AND tagy LIKE ?"
            params.append(f'%"{tag}"%')
        if od:
            query += " AND datum >= ?"
            params.append(od)
        if do:
            query += " AND datum <= ?"
            params.append(do)
        query += " ORDER BY datum DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_clanek(self, clanek_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM clanky WHERE id = ?", (clanek_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_related_clanky(
        self, clanek_id: str, segment_id: str | None, limit: int = 6,
    ) -> list[dict]:
        if segment_id:
            rows = self.conn.execute(
                """SELECT * FROM clanky
                   WHERE segment_id = ? AND id != ?
                   ORDER BY datum DESC LIMIT ?""",
                (segment_id, clanek_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM clanky WHERE id != ? ORDER BY datum DESC LIMIT ?",
                (clanek_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_produkty(
        self,
        segment_id: str | None = None,
        competitor_id: str | None = None,
        produktova_linie_id: str | None = None,
        zakaznicky_segment: str | None = None,
    ) -> list[dict]:
        query = "SELECT * FROM produkty WHERE aktivni = 1"
        params: list = []
        if segment_id:
            query += " AND segment_id = ?"
            params.append(segment_id)
        if competitor_id:
            query += " AND competitor_id = ?"
            params.append(competitor_id)
        if produktova_linie_id:
            query += " AND produktova_linie_id = ?"
            params.append(produktova_linie_id)
        if zakaznicky_segment:
            query += " AND zakaznicky_segment = ?"
            params.append(zakaznicky_segment)
        query += " ORDER BY nazev"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_kampane(
        self,
        segment_id: str | None = None,
        competitor_id: str | None = None,
        media_typ: str | None = None,
        od: str | None = None,
        do: str | None = None,
    ) -> list[dict]:
        query = "SELECT * FROM kampane WHERE 1=1"
        params: list = []
        if segment_id:
            query += " AND segment_id = ?"
            params.append(segment_id)
        if competitor_id:
            query += " AND competitor_id = ?"
            params.append(competitor_id)
        if media_typ:
            query += " AND media_typy LIKE ?"
            params.append(f'%"{media_typ}"%')
        if od:
            query += " AND zacatek >= ?"
            params.append(od)
        if do:
            query += " AND zacatek <= ?"
            params.append(do)
        query += " ORDER BY COALESCE(aktualizace, zacatek) DESC"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_mystery_shopping(
        self,
        segment_id: str | None = None,
        competitor_id: str | None = None,
    ) -> list[dict]:
        query = "SELECT * FROM mystery_shopping WHERE 1=1"
        params: list = []
        if segment_id:
            query += " AND segment_id = ?"
            params.append(segment_id)
        if competitor_id:
            query += " AND competitor_id = ?"
            params.append(competitor_id)
        query += " ORDER BY datum DESC"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_executive_summary(self, segment_id: str | None = None) -> list[dict]:
        if segment_id:
            rows = self.conn.execute(
                "SELECT * FROM executive_summary WHERE segment_id = ? ORDER BY rok DESC, mesic DESC",
                (segment_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM executive_summary ORDER BY rok DESC, mesic DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_analyzy(self, segment_id: str | None = None) -> list[dict]:
        if segment_id:
            rows = self.conn.execute(
                "SELECT * FROM analyzy WHERE segment_id = ? ORDER BY datum DESC",
                (segment_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM analyzy ORDER BY datum DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def insert_clanek_from_signal(self, signal_row: dict, segment_id: str | None = None) -> bool:
        """Vytvoří článek z existujícího signálu. Idempotentní (unique index na zdrojovy_signal_id)."""
        import uuid
        tagy = signal_row.get("tags") or "[]"
        cursor = self.conn.execute(
            """INSERT OR IGNORE INTO clanky
               (id, competitor_id, segment_id, nazev, datum, typ_zpravy,
                stav, perex, telo, tagy, zdrojovy_signal_id, url, pridano_at)
               VALUES (?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), signal_row["competitor_id"], segment_id,
             signal_row["title"], signal_row["detected_at"][:10],
             signal_row.get("signal_type", "news"),
             (signal_row.get("content") or "")[:500],
             signal_row.get("content", ""),
             tagy, signal_row["id"], signal_row.get("url"),
             datetime.utcnow().isoformat()),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_competitors(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM competitors ORDER BY tier, name"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_competitor(self, competitor_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM competitors WHERE id = ?", (competitor_id,)
        ).fetchone()
        return dict(row) if row else None

    # ── FINeCIM: taxonomie ───────────────────────────────────────

    def upsert_finecim_subject(
        self, subject_id: int, name: str, competitor_id: str | None, url: str | None,
        segment_ids: list[str], *, logo_url: str | None = None, aktualizace: str | None = None,
    ) -> None:
        """Insert/update a FINeCIM subject and add its segment memberships.

        Existing memberships are kept and unknown segment ids are skipped. None never erases
        a stored competitor_id/url/logo_url/aktualizace; an empty name keeps the stored one."""
        with self.conn:
            self.conn.execute(
                """INSERT INTO finecim_subjekty
                   (subject_id, nazev, competitor_id, url, logo_url, aktualizace, pridano_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(subject_id) DO UPDATE SET
                     nazev = CASE WHEN excluded.nazev != '' THEN excluded.nazev ELSE nazev END,
                     competitor_id = COALESCE(excluded.competitor_id, competitor_id),
                     url = COALESCE(excluded.url, url),
                     logo_url = COALESCE(excluded.logo_url, logo_url),
                     aktualizace = COALESCE(excluded.aktualizace, aktualizace)""",
                (int(subject_id), name or "", competitor_id, url, logo_url, aktualizace,
                 _utc_now_iso()),
            )
            for seg_id in segment_ids or []:
                self.conn.execute(
                    """INSERT OR IGNORE INTO finecim_subjekty_segmenty (subject_id, segment_id)
                       SELECT ?, id FROM segmenty WHERE id = ?""",
                    (int(subject_id), seg_id),
                )

    def get_finecim_subject(self, subject_id: int) -> dict | None:
        """Subject row plus ``segment_ids`` (sorted list of its segments)."""
        row = self.conn.execute(
            "SELECT * FROM finecim_subjekty WHERE subject_id = ?", (int(subject_id),)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        seg_rows = self.conn.execute(
            """SELECT segment_id FROM finecim_subjekty_segmenty
               WHERE subject_id = ? ORDER BY segment_id""",
            (int(subject_id),),
        ).fetchall()
        result["segment_ids"] = [r["segment_id"] for r in seg_rows]
        return result

    def ensure_competitor_for_subject(self, subject_id: int, name: str) -> str:
        """Return the competitor id for a FINeCIM subject, creating the competitor if needed.

        Subject 0 maps to the placeholder ``__finecim__``. Otherwise the mapping in
        ``finecim.yaml`` (``subject_to_competitor``, read from ``self.finecim_config_dir`` or
        the repo config dir) wins, then a competitor already stored on the subject row, then
        an auto-created ``fc_<id>`` competitor (tier 3). A mapped competitor that is not
        seeded yet gets a tier-3 stub that ``seed_competitors`` later overwrites."""
        subject_id = int(subject_id)
        if subject_id == 0:
            competitor_id = FINECIM_PLACEHOLDER_COMPETITOR
        else:
            competitor_id = load_subject_competitor_map(self.finecim_config_dir).get(subject_id)
            if competitor_id is None:
                row = self.conn.execute(
                    "SELECT competitor_id FROM finecim_subjekty WHERE subject_id = ?", (subject_id,)
                ).fetchone()
                competitor_id = (row["competitor_id"] if row else None) or f"fc_{subject_id}"
            elif not self.conn.execute(
                "SELECT 1 FROM competitors WHERE id = ?", (competitor_id,)
            ).fetchone():
                logger.warning(
                    "Competitor %s (FINeCIM subject %d) is not seeded; creating a stub",
                    competitor_id, subject_id,
                )
        with self.conn:
            self.conn.execute(
                """INSERT OR IGNORE INTO competitors (id, name, parent_group, tier, ico, config_path)
                   VALUES (?, ?, NULL, 3, NULL, NULL)""",
                (competitor_id, (name or "").strip() or f"FINeCIM subjekt {subject_id}"),
            )
            if subject_id != 0:
                self.conn.execute(
                    """UPDATE finecim_subjekty SET competitor_id = ?
                       WHERE subject_id = ? AND competitor_id IS NULL""",
                    (competitor_id, subject_id),
                )
        return competitor_id

    # ── FINeCIM: entity upserts ──────────────────────────────────

    def _upsert_row(self, table: str, row: dict, key: str = "id") -> bool:
        """Insert or update one row keyed by ``key`` (call inside a transaction).

        Only keys that are columns of ``table`` are used (lists/dicts become JSON). On update
        only the provided columns change and ``pridano_at`` is never touched; on insert
        ``pridano_at`` defaults to now. Returns True on insert."""
        columns = self._table_columns(table)
        data = {k: _db_value(v) for k, v in row.items() if k in columns}
        if data.get(key) is None:
            raise ValueError(f"{table}: row is missing '{key}'")
        exists = self.conn.execute(
            f"SELECT 1 FROM {table} WHERE {key} = ?", (data[key],)
        ).fetchone()
        if exists:
            updates = {k: v for k, v in data.items() if k not in (key, "pridano_at")}
            if updates:
                assignments = ", ".join(f"{k} = ?" for k in updates)
                self.conn.execute(
                    f"UPDATE {table} SET {assignments} WHERE {key} = ?",
                    (*updates.values(), data[key]),
                )
            return False
        if "pridano_at" in columns and not data.get("pridano_at"):
            data["pridano_at"] = _utc_now_iso()
        self.conn.execute(_insert_sql(table, data), tuple(data.values()))
        return True

    def upsert_clanek(self, row: dict) -> bool:
        with self.conn:
            return self._upsert_row("clanky", row)

    def upsert_kampan(self, row: dict) -> bool:
        with self.conn:
            return self._upsert_row("kampane", row)

    def replace_kampan_kreativy(self, kampan_id: str, rows: list[dict]) -> int:
        """Replace all creatives of a campaign; returns the number of rows written."""
        columns = self._table_columns("kampane_kreativy")
        count = 0
        with self.conn:
            self.conn.execute("DELETE FROM kampane_kreativy WHERE kampan_id = ?", (kampan_id,))
            for r in rows or []:
                data = {k: _db_value(v) for k, v in r.items() if k in columns}
                if not data.get("id"):
                    raise ValueError("kampane_kreativy: row is missing 'id'")
                data["kampan_id"] = kampan_id
                self.conn.execute(
                    _insert_sql("kampane_kreativy", data, "INSERT OR REPLACE"), tuple(data.values())
                )
                count += 1
        return count

    def upsert_mystery(self, row: dict) -> bool:
        with self.conn:
            return self._upsert_row("mystery_shopping", row)

    def upsert_produkt(self, row: dict) -> bool:
        """Upsert a product; when ``row`` carries ``atributy`` and they differ from the last
        stored version, a new row is added to ``produkty_verze`` (the digest diffs them)."""
        with self.conn:
            inserted = self._upsert_row("produkty", row)
            if "atributy" in row:
                self._record_produkt_verze(row["id"], row.get("atributy"), row.get("aktualizace"))
            return inserted

    @staticmethod
    def produkt_atributy_hash(atributy) -> str:
        """Stable hash of product parameters (order of keys and whitespace do not matter)."""
        canonical = json.dumps(atributy or [], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(canonical.encode("utf-8")).hexdigest()

    def _record_produkt_verze(self, produkt_id: str, atributy, aktualizace: str | None) -> bool:
        """Append a version of the product parameters unless the latest one is identical
        (call inside a transaction). Returns True when a version was written."""
        if not self._table_columns("produkty_verze"):
            return False
        content_hash = self.produkt_atributy_hash(atributy)
        latest = self.conn.execute(
            "SELECT content_hash FROM produkty_verze WHERE produkt_id = ? ORDER BY id DESC LIMIT 1",
            (produkt_id,),
        ).fetchone()
        if latest and latest["content_hash"] == content_hash:
            return False
        self.conn.execute(
            """INSERT INTO produkty_verze (produkt_id, atributy, content_hash, aktualizace, zachyceno_at)
               VALUES (?, ?, ?, ?, ?)""",
            (produkt_id, _db_value(atributy if atributy is not None else []), content_hash,
             aktualizace, _utc_now_iso()),
        )
        return True

    def get_produkt_verze(self, produkt_id: str) -> list[dict]:
        """Stored parameter versions of a product, oldest first, ``atributy`` parsed from JSON.
        An empty list when none is stored (or the table does not exist yet)."""
        if not self._table_columns("produkty_verze"):
            return []
        rows = self.conn.execute(
            "SELECT * FROM produkty_verze WHERE produkt_id = ? ORDER BY id", (produkt_id,)
        ).fetchall()
        result = []
        for r in rows:
            entry = dict(r)
            try:
                entry["atributy"] = json.loads(entry["atributy"]) if entry.get("atributy") else []
            except (json.JSONDecodeError, TypeError):
                entry["atributy"] = []
            result.append(entry)
        return result

    def upsert_executive_summary(self, row: dict, polozky: list[dict]) -> bool:
        """Upsert a monthly summary and replace its entries (``executive_summary_polozky``).

        A stored summary for the same (segment_id, rok, mesic) under another id is treated
        as the same record and re-keyed to ``row["id"]``. Entries without ``id`` but with
        ``entry_id`` get ``fc-es-entry-<entry_id>``; ``poradi`` defaults to list order. Entries
        may carry ``url`` (link of the item) and ``typ`` (``news`` / ``campaign`` /
        ``mystery-shopping`` / ``produkt``).

        Month pages are shared across domains, so an existing summary keeps its ``segment_id``
        on update (the first segment wins); the other columns are updated."""
        summary_id = row.get("id")
        if not summary_id:
            raise ValueError("executive_summary: row is missing 'id'")
        columns = self._table_columns("executive_summary_polozky")
        with self.conn:
            if row.get("segment_id") and row.get("rok") is not None and row.get("mesic") is not None:
                other = self.conn.execute(
                    """SELECT id FROM executive_summary
                       WHERE segment_id = ? AND rok = ? AND mesic = ? AND id != ?""",
                    (row["segment_id"], row["rok"], row["mesic"], summary_id),
                ).fetchone()
                own = self.conn.execute(
                    "SELECT 1 FROM executive_summary WHERE id = ?", (summary_id,)
                ).fetchone()
                if other and not own:
                    self.conn.execute(
                        "DELETE FROM executive_summary_polozky WHERE summary_id = ?", (other["id"],)
                    )
                    self.conn.execute(
                        "UPDATE executive_summary SET id = ? WHERE id = ?", (summary_id, other["id"])
                    )
            stored = self.conn.execute(
                "SELECT 1 FROM executive_summary WHERE id = ?", (summary_id,)
            ).fetchone()
            if stored:
                row = {k: v for k, v in row.items() if k != "segment_id"}
            inserted = self._upsert_row("executive_summary", row)
            self.conn.execute(
                "DELETE FROM executive_summary_polozky WHERE summary_id = ?", (summary_id,)
            )
            for index, p in enumerate(polozky or []):
                data = {k: _db_value(v) for k, v in p.items() if k in columns}
                if not data.get("id") and p.get("entry_id") is not None:
                    data["id"] = f"fc-es-entry-{p['entry_id']}"
                if not data.get("id"):
                    raise ValueError("executive_summary_polozky: row is missing 'id'")
                data["summary_id"] = summary_id
                if data.get("poradi") is None:
                    data["poradi"] = index
                self.conn.execute(
                    _insert_sql("executive_summary_polozky", data, "INSERT OR REPLACE"),
                    tuple(data.values()),
                )
        return inserted

    def upsert_spolecnost_detail(self, competitor_id: str, row: dict) -> None:
        """Upsert the company profile; a row key ``ico`` fills ``competitors.ico`` when empty."""
        data = dict(row)
        data["competitor_id"] = competitor_id
        ico = data.pop("ico", None)
        with self.conn:
            self._upsert_row("spolecnost_detail", data, key="competitor_id")
            if ico:
                self.conn.execute(
                    "UPDATE competitors SET ico = ? WHERE id = ? AND (ico IS NULL OR ico = '')",
                    (str(ico), competitor_id),
                )

    def replace_prilohy(self, entity_type: str, entity_id: str, rows: list[dict]) -> int:
        """Replace attachments of an item; rows carry ``url`` and ``nazev`` (or ``name``).
        Rows without a url and duplicate urls are skipped. Returns rows written."""
        count = 0
        with self.conn:
            self.conn.execute(
                "DELETE FROM finecim_prilohy WHERE entity_type = ? AND entity_id = ?",
                (entity_type, entity_id),
            )
            for r in rows or []:
                if not r.get("url"):
                    continue
                cur = self.conn.execute(
                    """INSERT OR IGNORE INTO finecim_prilohy (entity_type, entity_id, nazev, url)
                       VALUES (?, ?, ?, ?)""",
                    (entity_type, entity_id, r.get("nazev", r.get("name")), r["url"]),
                )
                count += cur.rowcount
        return count

    def replace_vazby(self, entity_type: str, entity_id: str, subject_ids: list[int]) -> int:
        """Replace the related-company links of an item; returns distinct links written."""
        unique_ids = list(dict.fromkeys(int(s) for s in subject_ids or []))
        with self.conn:
            self.conn.execute(
                "DELETE FROM finecim_vazby WHERE entity_type = ? AND entity_id = ?",
                (entity_type, entity_id),
            )
            self.conn.executemany(
                "INSERT INTO finecim_vazby (entity_type, entity_id, subject_id) VALUES (?, ?, ?)",
                [(entity_type, entity_id, sid) for sid in unique_ids],
            )
        return len(unique_ids)

    # ── FINeCIM: incremental sync helpers ────────────────────────

    def known_finecim_ids(self, entity: str, ids: list[int]) -> dict[int, str | None]:
        """Map each already-stored FINeCIM id to its stored date; unknown ids are absent.

        Dates: news/mystery ``datum``, campaign ``aktualizace``, product ``aktualizace`` (else
        the insert date), summary the insert date, company ``finecim_subjekty.aktualizace``.
        Entity names follow ``sync.ENTITIES``; Czech table-style aliases are accepted too."""
        name = _FINECIM_ENTITY_ALIASES.get(entity, entity)
        if name != "company" and name not in _FINECIM_ENTITY_TABLES:
            raise ValueError(f"Unknown FINeCIM entity: {entity!r}")
        wanted = list(dict.fromkeys(int(i) for i in ids or []))
        result: dict[int, str | None] = {}
        for start in range(0, len(wanted), 500):
            chunk = wanted[start:start + 500]
            marks = ", ".join("?" for _ in chunk)
            if name == "company":
                rows = self.conn.execute(
                    f"""SELECT subject_id AS k, aktualizace AS d FROM finecim_subjekty
                        WHERE subject_id IN ({marks})""",
                    chunk,
                ).fetchall()
                result.update({int(r["k"]): r["d"] for r in rows})
                continue
            table, prefix, date_expr = _FINECIM_ENTITY_TABLES[name]
            rows = self.conn.execute(
                f"SELECT id AS k, {date_expr} AS d FROM {table} WHERE id IN ({marks})",
                [f"{prefix}{i}" for i in chunk],
            ).fetchall()
            result.update({int(r["k"][len(prefix):]): r["d"] for r in rows})
        return result

    def get_finecim_sync(self, entity: str, segment_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM finecim_sync WHERE entity = ? AND segment_id = ?",
            (entity, segment_id),
        ).fetchone()
        return dict(row) if row else None

    def set_finecim_sync(self, entity: str, segment_id: str, **fields) -> None:
        """Upsert sync state; only the given fields change. Allowed fields: last_run_at,
        last_success_at, last_page, newest_id, note (unknown names raise ValueError)."""
        unknown = set(fields) - set(_FINECIM_SYNC_FIELDS)
        if unknown:
            raise ValueError(f"Unknown finecim_sync fields: {sorted(unknown)}")
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO finecim_sync (entity, segment_id) VALUES (?, ?)",
                (entity, segment_id),
            )
            if fields:
                assignments = ", ".join(f"{k} = ?" for k in fields)
                self.conn.execute(
                    f"UPDATE finecim_sync SET {assignments} WHERE entity = ? AND segment_id = ?",
                    (*fields.values(), entity, segment_id),
                )

    # ── Signals ──────────────────────────────────────────────────

    def insert_signal(self, signal_dict: dict) -> bool:
        cursor = self.conn.execute(
            """INSERT OR IGNORE INTO signals
               (id, competitor_id, source, signal_type, title, content, url,
                detected_at, published_at, severity, tags, metadata,
                change_summary, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (signal_dict["id"], signal_dict["competitor_id"],
             signal_dict["source"], signal_dict["signal_type"],
             signal_dict["title"], signal_dict["content"],
             signal_dict["url"], signal_dict["detected_at"],
             signal_dict.get("published_at"),
             signal_dict["severity"],
             signal_dict["tags"], signal_dict["metadata"],
             signal_dict.get("change_summary"),
             signal_dict["content_hash"]),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_signals(
        self,
        competitor_id: str | None = None,
        source: str | None = None,
        min_severity: int | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        query = "SELECT * FROM signals WHERE 1=1"
        params: list = []
        if competitor_id:
            query += " AND competitor_id = ?"
            params.append(competitor_id)
        if source:
            query += " AND source = ?"
            params.append(source)
        if min_severity:
            query += " AND severity >= ?"
            params.append(min_severity)
        if since:
            query += " AND detected_at >= ?"
            params.append(since)
        query += " ORDER BY detected_at DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ── Snapshots ────────────────────────────────────────────────

    def get_latest_snapshot(
        self, competitor_id: str, source: str, snapshot_key: str
    ) -> dict | None:
        row = self.conn.execute(
            """SELECT * FROM snapshots
               WHERE competitor_id = ? AND source = ? AND snapshot_key = ?
               ORDER BY captured_at DESC, id DESC LIMIT 1""",
            (competitor_id, source, snapshot_key),
        ).fetchone()
        return dict(row) if row else None

    def get_previous_snapshot(
        self, competitor_id: str, source: str, snapshot_key: str
    ) -> dict | None:
        row = self.conn.execute(
            """SELECT * FROM snapshots
               WHERE competitor_id = ? AND source = ? AND snapshot_key = ?
               ORDER BY captured_at DESC, id DESC LIMIT 1 OFFSET 1""",
            (competitor_id, source, snapshot_key),
        ).fetchone()
        return dict(row) if row else None

    def insert_snapshot(
        self, competitor_id: str, source: str, snapshot_key: str,
        content: str, content_hash: str,
    ) -> bool:
        try:
            self.conn.execute(
                """INSERT INTO snapshots
                   (competitor_id, source, snapshot_key, content, content_hash, captured_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (competitor_id, source, snapshot_key, content, content_hash,
                 _utc_now_iso()),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    # ── Collector Runs ───────────────────────────────────────────

    def start_collector_run(
        self, collector_name: str, competitor_id: str | None = None
    ) -> int:
        cursor = self.conn.execute(
            """INSERT INTO collector_runs
               (collector_name, competitor_id, started_at, status)
               VALUES (?, ?, ?, 'running')""",
            (collector_name, competitor_id, _utc_now_iso()),
        )
        self.conn.commit()
        return cursor.lastrowid

    def finish_collector_run(
        self, run_id: int, status: str,
        signals_found: int = 0, error_message: str | None = None,
    ):
        self.conn.execute(
            """UPDATE collector_runs
               SET finished_at = ?, status = ?, signals_found = ?, error_message = ?
               WHERE id = ?""",
            (_utc_now_iso(), status, signals_found,
             error_message, run_id),
        )
        self.conn.commit()

    def get_collector_status(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT collector_name, competitor_id, started_at, finished_at,
                      status, signals_found, error_message
               FROM collector_runs
               ORDER BY started_at DESC
               LIMIT 50"""
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Aggregates (used by the API summary endpoint) ───────────

    def get_competitor_signal_stats(self, competitor_id: str) -> dict:
        row = self.conn.execute(
            """SELECT COUNT(*) AS cnt, ROUND(AVG(severity), 1) AS avg_sev
               FROM signals WHERE competitor_id = ?""",
            (competitor_id,),
        ).fetchone()
        if row is None:
            return {"signal_count": 0, "avg_severity": 0}
        return {"signal_count": row["cnt"] or 0, "avg_severity": row["avg_sev"] or 0}

    def get_signals_overview(self) -> dict:
        stats = self.conn.execute(
            """SELECT
                    COUNT(*) AS total_signals,
                    ROUND(AVG(severity), 1) AS avg_severity,
                    MAX(detected_at) AS last_signal,
                    COUNT(DISTINCT competitor_id) AS competitors_with_signals,
                    COUNT(DISTINCT source) AS sources_active
               FROM signals"""
        ).fetchone()
        severity_dist = self.conn.execute(
            "SELECT severity, COUNT(*) AS count FROM signals GROUP BY severity ORDER BY severity"
        ).fetchall()
        by_source = self.conn.execute(
            "SELECT source, COUNT(*) AS count FROM signals GROUP BY source ORDER BY count DESC"
        ).fetchall()
        by_competitor = self.conn.execute(
            """SELECT competitor_id, COUNT(*) AS count, ROUND(AVG(severity), 1) AS avg_severity
               FROM signals GROUP BY competitor_id ORDER BY count DESC LIMIT 10"""
        ).fetchall()
        timeline = self.conn.execute(
            """SELECT DATE(detected_at) AS date, COUNT(*) AS count
               FROM signals
               WHERE detected_at >= DATE('now', '-30 days')
               GROUP BY DATE(detected_at)
               ORDER BY date"""
        ).fetchall()
        return {
            "total_signals": dict(stats) if stats else {},
            "severity_distribution": [dict(r) for r in severity_dist],
            "by_source": [dict(r) for r in by_source],
            "by_competitor": [dict(r) for r in by_competitor],
            "timeline": [dict(r) for r in timeline],
        }
