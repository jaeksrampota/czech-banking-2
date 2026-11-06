-- ── Původní tabulky (beze změny) ────────────────────────────────

CREATE TABLE IF NOT EXISTS competitors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_group TEXT,
    tier INTEGER NOT NULL,
    ico TEXT,
    config_path TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    competitor_id TEXT NOT NULL REFERENCES competitors(id),
    source TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    url TEXT,
    detected_at TEXT NOT NULL,
    published_at TEXT,
    severity INTEGER DEFAULT 1,
    tags TEXT,
    metadata TEXT,
    change_summary TEXT,
    content_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signals_competitor ON signals(competitor_id);
CREATE INDEX IF NOT EXISTS idx_signals_source ON signals(source);
CREATE INDEX IF NOT EXISTS idx_signals_detected ON signals(detected_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_hash ON signals(content_hash);
CREATE INDEX IF NOT EXISTS idx_signals_severity ON signals(severity);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id TEXT NOT NULL REFERENCES competitors(id),
    source TEXT NOT NULL,
    snapshot_key TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    UNIQUE(competitor_id, source, snapshot_key, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_lookup
    ON snapshots(competitor_id, source, snapshot_key);

CREATE TABLE IF NOT EXISTS collector_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collector_name TEXT NOT NULL,
    competitor_id TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    signals_found INTEGER DEFAULT 0,
    error_message TEXT
);

-- ── FINeCIM-inspirovaná struktura (nové tabulky, additivně) ─────

-- Segmenty trhu (Účty, Hypotéky, Investice, …)
CREATE TABLE IF NOT EXISTS segmenty (
    id TEXT PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    nazev TEXT NOT NULL,
    poradi INTEGER NOT NULL DEFAULT 0,
    ma_produkty INTEGER NOT NULL DEFAULT 1
);

-- Produktové linie v rámci segmentu (Běžné účty, Hypotéky, …)
CREATE TABLE IF NOT EXISTS produktove_linie (
    id TEXT PRIMARY KEY,
    segment_id TEXT NOT NULL REFERENCES segmenty(id),
    slug TEXT NOT NULL,
    nazev TEXT NOT NULL,
    UNIQUE(segment_id, slug)
);

-- Vazba společnost ↔ segment (M:N)
CREATE TABLE IF NOT EXISTS spolecnosti_segmenty (
    competitor_id TEXT NOT NULL REFERENCES competitors(id),
    segment_id TEXT NOT NULL REFERENCES segmenty(id),
    PRIMARY KEY (competitor_id, segment_id)
);

-- Rozšířený profil společnosti (bez ALTER TABLE — join přes competitor_id)
CREATE TABLE IF NOT EXISTS spolecnost_detail (
    competitor_id TEXT PRIMARY KEY REFERENCES competitors(id),
    popis TEXT,
    zakladni_kapital TEXT,
    sidlo TEXT,
    akcionar TEXT,
    pocet_klientu INTEGER,
    pocet_pobocek INTEGER,
    pocet_bankomatu INTEGER,
    socialni_site TEXT,
    predstavenstvo TEXT,
    posledni_aktualizace TEXT
);

-- Produkty (katalog produktů banky)
CREATE TABLE IF NOT EXISTS produkty (
    id TEXT PRIMARY KEY,
    competitor_id TEXT NOT NULL REFERENCES competitors(id),
    segment_id TEXT NOT NULL REFERENCES segmenty(id),
    produktova_linie_id TEXT REFERENCES produktove_linie(id),
    zakaznicky_segment TEXT,
    nazev TEXT NOT NULL,
    kratky_popis TEXT,
    atributy TEXT,
    url TEXT,
    aktivni INTEGER DEFAULT 1,
    pridano_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_produkty_company ON produkty(competitor_id);
CREATE INDEX IF NOT EXISTS idx_produkty_segment ON produkty(segment_id);
CREATE INDEX IF NOT EXISTS idx_produkty_linie ON produkty(produktova_linie_id);

-- Články / Zprávy (redakční obsah; volitelně navázaný na signal)
CREATE TABLE IF NOT EXISTS clanky (
    id TEXT PRIMARY KEY,
    competitor_id TEXT REFERENCES competitors(id),
    segment_id TEXT REFERENCES segmenty(id),
    produktova_linie_id TEXT REFERENCES produktove_linie(id),
    nazev TEXT NOT NULL,
    datum TEXT NOT NULL,
    typ_zpravy TEXT,
    stav TEXT DEFAULT 'new',
    perex TEXT,
    telo TEXT,
    tagy TEXT,
    zdrojovy_signal_id TEXT REFERENCES signals(id),
    url TEXT,
    pridano_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clanky_segment ON clanky(segment_id);
CREATE INDEX IF NOT EXISTS idx_clanky_company ON clanky(competitor_id);
CREATE INDEX IF NOT EXISTS idx_clanky_datum ON clanky(datum);
CREATE UNIQUE INDEX IF NOT EXISTS idx_clanky_signal ON clanky(zdrojovy_signal_id);

-- Kampaně (reklama / marketing)
CREATE TABLE IF NOT EXISTS kampane (
    id TEXT PRIMARY KEY,
    competitor_id TEXT NOT NULL REFERENCES competitors(id),
    segment_id TEXT REFERENCES segmenty(id),
    produktova_linie_id TEXT REFERENCES produktove_linie(id),
    nazev TEXT NOT NULL,
    zacatek TEXT,
    aktualizace TEXT,
    popis TEXT,
    media_typy TEXT,
    typ_kampane TEXT,
    kreativa_url TEXT,
    pridano_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kampane_segment ON kampane(segment_id);
CREATE INDEX IF NOT EXISTS idx_kampane_company ON kampane(competitor_id);

-- Mystery Shopping (terénní testování produktů konkurence)
CREATE TABLE IF NOT EXISTS mystery_shopping (
    id TEXT PRIMARY KEY,
    competitor_id TEXT REFERENCES competitors(id),
    segment_id TEXT REFERENCES segmenty(id),
    nazev TEXT NOT NULL,
    datum TEXT NOT NULL,
    popis TEXT,
    pdf_url TEXT,
    pridano_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mystery_segment ON mystery_shopping(segment_id);

-- Executive Summary (měsíční, na segment)
CREATE TABLE IF NOT EXISTS executive_summary (
    id TEXT PRIMARY KEY,
    segment_id TEXT NOT NULL REFERENCES segmenty(id),
    rok INTEGER NOT NULL,
    mesic INTEGER NOT NULL,
    nazev TEXT,
    telo TEXT,
    pdf_url TEXT,
    pridano_at TEXT NOT NULL,
    UNIQUE(segment_id, rok, mesic)
);

-- Analýzy (ad-hoc i periodické reporty)
CREATE TABLE IF NOT EXISTS analyzy (
    id TEXT PRIMARY KEY,
    segment_id TEXT REFERENCES segmenty(id),
    nazev TEXT NOT NULL,
    datum TEXT NOT NULL,
    typ_analyzy TEXT,
    telo TEXT,
    soubory TEXT,
    pridano_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_analyzy_segment ON analyzy(segment_id);

-- ── FINeCIM scraper (additivně; viz finecim-research/SCRAPER-DESIGN.md §4) ──
-- Sloupce segmenty.finecim_slug, produktove_linie.finecim_id a produkty.aktualizace
-- přidává idempotentně Database.initialize() (ALTER TABLE nelze podmínit v čistém SQL).

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

-- Každá související společnost položky
CREATE TABLE IF NOT EXISTS finecim_vazby (
    entity_type TEXT NOT NULL,                       -- clanek | kampan | mystery | produkt
    entity_id TEXT NOT NULL,
    subject_id INTEGER NOT NULL,
    PRIMARY KEY (entity_type, entity_id, subject_id)
);

CREATE INDEX IF NOT EXISTS idx_finecim_vazby_subject ON finecim_vazby(subject_id);

-- PDF / soubory připojené k položce nebo společnosti
CREATE TABLE IF NOT EXISTS finecim_prilohy (
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

CREATE INDEX IF NOT EXISTS idx_kampane_kreativy_kampan ON kampane_kreativy(kampan_id);

CREATE TABLE IF NOT EXISTS executive_summary_polozky (
    id TEXT PRIMARY KEY,                             -- fc-es-entry-<entryId>
    summary_id TEXT NOT NULL REFERENCES executive_summary(id),
    clanek_id TEXT,                                  -- fc-news-<id> (nemusí být ještě stažen)
    nazev TEXT,
    text TEXT,
    poradi INTEGER,
    url TEXT,                                        -- odkaz položky (zpráva, kampaň, mystery, produkt)
    typ TEXT                                         -- news | campaign | mystery-shopping | produkt | NULL
);

CREATE INDEX IF NOT EXISTS idx_es_polozky_summary ON executive_summary_polozky(summary_id);

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
