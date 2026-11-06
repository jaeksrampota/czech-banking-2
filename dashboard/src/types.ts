export interface Signal {
  id: string;
  competitor_id: string;
  source: string;
  signal_type: string;
  title: string;
  content: string;
  url: string;
  detected_at: string;
  published_at: string | null;
  severity: number;
  tags: string[];
  metadata: Record<string, unknown>;
  change_summary: string | null;
  content_hash: string;
}

export interface Competitor {
  id: string;
  name: string;
  parent_group: string | null;
  tier: number;
  ico: string | null;
  config_path: string;
  signal_count: number;
  avg_severity: number;
}

export interface CollectorRun {
  collector_name: string;
  competitor_id: string | null;
  started_at: string;
  finished_at: string | null;
  status: string;
  signals_found: number;
  error_message: string | null;
}

export interface Summary {
  total_signals: {
    total_signals: number;
    avg_severity: number;
    last_signal: string;
    competitors_with_signals: number;
    sources_active: number;
  };
  severity_distribution: { severity: number; count: number }[];
  by_source: { source: string; count: number }[];
  by_competitor: { competitor_id: string; count: number; avg_severity: number }[];
  recent_signals: Signal[];
  timeline: { date: string; count: number }[];
}

// ── FINeCIM-inspirované typy ────────────────────────────────

export interface ProduktovaLinie {
  id: string;
  segment_id: string;
  slug: string;
  nazev: string;
}

export interface Segment {
  id: string;
  slug: string;
  nazev: string;
  poradi: number;
  ma_produkty: number;
  produktove_linie?: ProduktovaLinie[];
  spolecnosti?: Competitor[];
}

export interface Clanek {
  id: string;
  competitor_id: string | null;
  segment_id: string | null;
  produktova_linie_id: string | null;
  nazev: string;
  datum: string;
  typ_zpravy: string | null;
  stav: string;
  perex: string | null;
  telo: string | null;
  tagy: string[];
  zdrojovy_signal_id: string | null;
  url: string | null;
  pridano_at: string;
  typy_zpravy?: string[];
  telo_format?: 'html' | 'text';
  spolecnost_nazev?: string | null;
  logo_url?: string | null;
}

export interface Priloha {
  id: number;
  nazev: string | null;
  url: string;
}

export interface SouvisejiciSpolecnost {
  subject_id: number;
  nazev: string | null;
  url: string | null;
  competitor_id: string | null;
  competitor_name: string | null;
}

export interface ClanekDetail extends Clanek {
  related: Clanek[];
  finecim_url?: string | null;
  souvisejici_spolecnosti?: SouvisejiciSpolecnost[];
  prilohy?: Priloha[];
}

export interface ProduktAtribut {
  section: string | null;
  name: string;
  value: string | null;
}

export interface Produkt {
  id: string;
  competitor_id: string;
  segment_id: string;
  produktova_linie_id: string | null;
  zakaznicky_segment: string | null;
  nazev: string;
  kratky_popis: string | null;
  atributy: ProduktAtribut[] | Record<string, unknown>;
  atributy_mapa?: Record<string, unknown>;
  url: string | null;
  aktivni: number;
  pridano_at: string;
}

export interface Kampan {
  id: string;
  competitor_id: string;
  segment_id: string | null;
  produktova_linie_id: string | null;
  nazev: string;
  zacatek: string | null;
  aktualizace: string | null;
  popis: string | null;
  media_typy: string[];
  typ_kampane: string | null;
  kreativa_url: string | null;
  pridano_at: string;
  kreativy?: Kreativa[];
}

export interface Kreativa {
  id: string;
  kampan_id: string;
  datum: string | null;
  media_typ: string | null;
  popis: string | null;
  media_url: string | null;
  media_druh: 'video' | 'image' | null;
}

export interface MysteryShop {
  id: string;
  competitor_id: string | null;
  segment_id: string | null;
  nazev: string;
  datum: string;
  popis: string | null;
  pdf_url: string | null;
  pridano_at: string;
  prilohy?: Priloha[];
}

export interface ExecSummaryPolozka {
  id: string;
  clanek_id: string | null;
  nazev: string | null;
  text: string | null;
  poradi: number | null;
  clanek_url: string | null;
}

export interface ExecSummary {
  id: string;
  segment_id: string;
  rok: number;
  mesic: number;
  nazev: string | null;
  telo: string | null;
  pdf_url: string | null;
  pridano_at: string;
  polozky?: ExecSummaryPolozka[];
}

export interface Analyza {
  id: string;
  segment_id: string | null;
  nazev: string;
  datum: string;
  typ_analyzy: string | null;
  telo: string | null;
  soubory: string[];
  pridano_at: string;
}

export interface SpolecnostDetail extends Competitor {
  popis: string | null;
  zakladni_kapital: string | null;
  sidlo: string | null;
  akcionar: string | null;
  pocet_klientu: number | null;
  pocet_pobocek: number | null;
  pocet_bankomatu: number | null;
  socialni_site: Record<string, string>;
  predstavenstvo: { jmeno: string; role: string }[];
  posledni_aktualizace: string | null;
  segmenty: { id: string; slug: string; nazev: string }[];
  clanky: Clanek[];
  kampane: Kampan[];
  mystery_shopping: MysteryShop[];
  produkty: Produkt[];
  prilohy?: Priloha[];
  finecim_subject_id?: number | null;
  finecim_url?: string | null;
}

export interface NovinkyResponse {
  clanky: Clanek[];
  signaly_fallback: Signal[];
}

export type Page = 'overview' | 'monitor' | 'competitors' | 'digest' | 'status';

export type MonitorTab =
  | 'novinky'
  | 'spolecnosti'
  | 'produkty'
  | 'srovnani'
  | 'kampane'
  | 'mystery'
  | 'executive';

// ── Digest (GET /api/digest; src/digest/build.py) ───────────

export type DigestPeriodTyp = 'weekly' | 'monthly';

export interface DigestPeriod {
  typ: DigestPeriodTyp;
  od: string;
  do: string;
  nazev: string;
  popis: string;
}

export interface DigestSegmentRef {
  id: string;
  slug: string;
  nazev: string;
}

export interface DigestSpolecnostRef {
  id: string;
  nazev: string;
  tier: number | null;
}

export interface DigestZmena {
  section: string | null;
  name: string;
  stara: string | null;
  nova: string | null;
  druh: 'zmena' | 'pridano' | 'odebrano';
}

export interface DigestParametr {
  section: string | null;
  name: string;
  value: string | null;
}

export interface DigestProdukt {
  id: string;
  nazev: string;
  url: string | null;
  druh: 'novy' | 'zmena' | 'aktualizace';
  segment: DigestSegmentRef | null;
  produktova_linie: string | null;
  zakaznicky_segment: string | null;
  kratky_popis: string | null;
  aktualizace: string | null;
  pridano: string | null;
  zmeny: DigestZmena[];
  parametry: DigestParametr[];
}

export interface DigestKreativa {
  id: string;
  datum: string | null;
  media_typ: string | null;
  popis: string | null;
  media_url: string | null;
  media_druh: 'video' | 'image' | null;
}

export interface DigestKampan {
  id: string;
  nazev: string;
  url: string | null;
  druh: 'nova' | 'aktualizovana';
  segment: DigestSegmentRef | null;
  zacatek: string | null;
  aktualizace: string | null;
  popis: string | null;
  media_typy: string[];
  typy_kampane: string[];
  kreativa_url: string | null;
  prvni_kreativa: DigestKreativa | null;
  pocet_kreativ: number;
}

export interface DigestZprava {
  id: string;
  nazev: string;
  datum: string | null;
  url: string | null;
  perex: string | null;
  typy_zpravy: string[];
  tagy: string[];
  stav: string | null;
  segment: DigestSegmentRef | null;
  spolecnost: DigestSpolecnostRef | null;
}

export interface DigestZpravySkupina {
  typ: string;
  polozky: DigestZprava[];
}

export interface DigestMystery {
  id: string;
  nazev: string;
  datum: string | null;
  popis: string | null;
  pdf_url: string | null;
  url: string | null;
  segment: DigestSegmentRef | null;
}

export interface DigestPocty {
  clanky: number;
  kampane: number;
  produkty: number;
  mystery_shopping: number;
}

export interface DigestSpolecnost {
  id: string;
  nazev: string;
  tier: number | null;
  parent_group: string | null;
  pocty: DigestPocty;
  produkty: DigestProdukt[];
  kampane: DigestKampan[];
  zpravy: DigestZpravySkupina[];
  mystery_shopping: DigestMystery[];
}

export interface DigestExecSummaryPolozka {
  id: string;
  nazev: string | null;
  text: string | null;
  url: string | null;
  typ: string | null;
  clanek_id: string | null;
}

export interface DigestExecSummary {
  id: string;
  rok: number;
  mesic: number;
  nazev: string;
  pdf_url: string | null;
  segment: DigestSegmentRef | null;
  polozky: DigestExecSummaryPolozka[];
}

export interface Digest {
  period: DigestPeriod;
  segmenty: DigestSegmentRef[];
  filtr_segmentu: string[];
  vygenerovano: string;
  prazdny: boolean;
  souhrn: DigestPocty & { spolecnosti: number; executive_summary: number; trh: number };
  spolecnosti: DigestSpolecnost[];
  executive_summary: DigestExecSummary[];
  trh: DigestZpravySkupina[];
}
