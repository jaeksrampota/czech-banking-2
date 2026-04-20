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
}

export interface ClanekDetail extends Clanek {
  related: Clanek[];
}

export interface Produkt {
  id: string;
  competitor_id: string;
  segment_id: string;
  produktova_linie_id: string | null;
  zakaznicky_segment: string | null;
  nazev: string;
  kratky_popis: string | null;
  atributy: Record<string, unknown>;
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
}

export interface NovinkyResponse {
  clanky: Clanek[];
  signaly_fallback: Signal[];
}

export type Page = 'overview' | 'monitor' | 'competitors' | 'status';

export type MonitorTab =
  | 'novinky'
  | 'spolecnosti'
  | 'produkty'
  | 'srovnani'
  | 'kampane'
  | 'mystery'
  | 'executive';
