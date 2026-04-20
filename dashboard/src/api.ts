import type {
  Signal, Competitor, CollectorRun, Summary,
  Segment, Kampan, MysteryShop, ExecSummary, Analyza,
  Produkt, SpolecnostDetail, NovinkyResponse, ClanekDetail,
} from './types';

const BASE = '/api';

async function get<T>(path: string, params?: Record<string, string | undefined>): Promise<T> {
  const url = new URL(path, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v) url.searchParams.set(k, v);
    });
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API chyba: ${res.status}`);
  return res.json();
}

export const api = {
  // Původní endpointy (Overview / Competitors / Status page)
  getSummary: () => get<Summary>(`${BASE}/summary`),

  getSignals: (params?: {
    competitor?: string;
    source?: string;
    severity?: string;
    since?: string;
    limit?: string;
  }) => get<Signal[]>(`${BASE}/signals`, params),

  getCompetitors: () => get<Competitor[]>(`${BASE}/competitors`),

  getStatus: () => get<CollectorRun[]>(`${BASE}/status`),

  // FINeCIM-inspirované endpointy
  getSegmenty: () => get<Segment[]>(`${BASE}/segmenty`),

  getSegment: (slug: string) => get<Segment>(`${BASE}/segment/${slug}`),

  getNovinky: (slug: string, params?: {
    spolecnost?: string;
    produktova_linie?: string;
    typ_zpravy?: string;
    tag?: string;
    od?: string;
    do?: string;
    limit?: string;
  }) => get<NovinkyResponse>(`${BASE}/segment/${slug}/novinky`, params),

  getClanek: (id: string) =>
    get<ClanekDetail>(`${BASE}/clanek/${id}`),

  getSpolecnosti: (slug: string) =>
    get<Competitor[]>(`${BASE}/segment/${slug}/spolecnosti`),

  getProdukty: (slug: string, params?: {
    spolecnost?: string;
    produktova_linie?: string;
    zakaznicky_segment?: string;
  }) => get<Produkt[]>(`${BASE}/segment/${slug}/produkty`, params),

  getKampane: (slug: string, params?: {
    spolecnost?: string;
    media_typ?: string;
    od?: string;
    do?: string;
  }) => get<Kampan[]>(`${BASE}/segment/${slug}/kampane`, params),

  getMysteryShopping: (slug: string, params?: { spolecnost?: string }) =>
    get<MysteryShop[]>(`${BASE}/segment/${slug}/mystery-shopping`, params),

  getExecutiveSummary: (slug: string) =>
    get<ExecSummary[]>(`${BASE}/segment/${slug}/executive-summary`),

  getAnalyzy: (slug: string) =>
    get<Analyza[]>(`${BASE}/segment/${slug}/analyzy`),

  getSpolecnostDetail: (id: string) =>
    get<SpolecnostDetail>(`${BASE}/spolecnost/${id}`),
};
