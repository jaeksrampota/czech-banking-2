import { useEffect, useMemo, useState } from 'react';
import { Star, X } from 'lucide-react';
import { api } from '../api';
import type {
  Segment, Competitor, MonitorTab,
  Clanek, Signal, Produkt, Kampan, MysteryShop, ExecSummary,
} from '../types';
import PageHeader from '../components/PageHeader';
import ErrorBanner from '../components/ErrorBanner';
import SegmentRail from '../components/finecim/SegmentRail';
import SubNav from '../components/finecim/SubNav';
import FilterBar, { EMPTY_FILTERS, type FilterState } from '../components/finecim/FilterBar';
import NewsCard from '../components/finecim/NewsCard';
import CompanyTile from '../components/finecim/CompanyTile';
import CompanyModal from '../components/finecim/CompanyModal';
import ProductCard from '../components/finecim/ProductCard';
import CampaignCard from '../components/finecim/CampaignCard';
import MysteryCard from '../components/finecim/MysteryCard';
import ExecSummaryArchive from '../components/finecim/ExecSummaryArchive';
import ComparisonWizard from '../components/finecim/ComparisonWizard';
import EmptyState from '../components/finecim/EmptyState';
import ArticleDetail from '../components/finecim/ArticleDetail';
import TagChip from '../components/finecim/TagChip';
import { useFavorites, type FavoriteType } from '../hooks/useFavorites';
import { cn } from '../utils';

export default function Monitor() {
  const [segmenty, setSegmenty] = useState<Segment[]>([]);
  const [segmentsLoading, setSegmentsLoading] = useState(true);
  const [segmentsError, setSegmentsError] = useState<string | null>(null);

  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<MonitorTab>('novinky');
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [onlyFavorites, setOnlyFavorites] = useState(false);
  const [modalCompanyId, setModalCompanyId] = useState<string | null>(null);
  const [openArticleId, setOpenArticleId] = useState<string | null>(null);

  const [data, setData] = useState<any>(null);
  const [dataLoading, setDataLoading] = useState(false);
  const [dataError, setDataError] = useState<string | null>(null);

  const { isFavorite, count: favCount } = useFavorites();

  useEffect(() => {
    api.getSegmenty()
      .then((s) => setSegmenty(s))
      .catch((e) => setSegmentsError(e instanceof Error ? e.message : 'Chyba'))
      .finally(() => setSegmentsLoading(false));
  }, []);

  const currentSegment = useMemo(
    () => segmenty.find((s) => s.slug === selectedSlug) || null,
    [segmenty, selectedSlug],
  );

  const spolecnosti = currentSegment?.spolecnosti || [];
  const produktoveLinie = currentSegment?.produktove_linie || [];

  // Reset když změníme segment
  useEffect(() => {
    setFilters(EMPTY_FILTERS);
    setActiveTag(null);
    setOnlyFavorites(false);
    setOpenArticleId(null);
    if (!currentSegment?.ma_produkty && (activeTab === 'produkty' || activeTab === 'srovnani')) {
      setActiveTab('novinky');
    }
  }, [selectedSlug]);

  // Reset tag/favorites filter když změníme záložku
  useEffect(() => {
    setActiveTag(null);
    setOnlyFavorites(false);
    setOpenArticleId(null);
  }, [activeTab]);

  // Fetch dat pro aktivní záložku
  useEffect(() => {
    setData(null);
    setDataError(null);
    if (!selectedSlug) return;

    setDataLoading(true);

    const params = {
      spolecnost: filters.spolecnost || undefined,
      produktova_linie: filters.produktova_linie || undefined,
      tag: activeTag || undefined,
      od: filters.od || undefined,
      do: filters.do || undefined,
    };

    let promise: Promise<any>;
    switch (activeTab) {
      case 'novinky':
        promise = api.getNovinky(selectedSlug, params);
        break;
      case 'spolecnosti':
        promise = api.getSpolecnosti(selectedSlug);
        break;
      case 'produkty':
        promise = api.getProdukty(selectedSlug, {
          ...params,
          zakaznicky_segment: filters.zakaznicky_segment || undefined,
        });
        break;
      case 'srovnani':
        promise = api.getProdukty(selectedSlug);
        break;
      case 'kampane':
        promise = api.getKampane(selectedSlug, params);
        break;
      case 'mystery':
        promise = api.getMysteryShopping(selectedSlug, params);
        break;
      case 'executive':
        promise = api.getExecutiveSummary(selectedSlug);
        break;
      default:
        promise = Promise.resolve(null);
    }
    promise
      .then(setData)
      .catch((e) => setDataError(e instanceof Error ? e.message : 'Chyba'))
      .finally(() => setDataLoading(false));
  }, [selectedSlug, activeTab, filters, activeTag]);

  const spolecnostById = (id: string | null | undefined) =>
    id ? spolecnosti.find((c) => c.id === id) : undefined;

  const produktovaLinieName = (id: string | null) =>
    id ? produktoveLinie.find((l) => l.id === id)?.nazev : undefined;

  const filterFavs = <T extends { id: string }>(list: T[], type: FavoriteType) =>
    onlyFavorites ? list.filter((i) => isFavorite(type, i.id)) : list;

  // ── Render ─────────────────────────────────────────────────

  if (segmentsLoading) {
    return (
      <div className="max-w-[1500px] mx-auto">
        <PageHeader title="Monitor" subtitle="Načítám segmenty…" />
      </div>
    );
  }

  if (segmentsError) {
    return (
      <div className="max-w-[1500px] mx-auto space-y-4">
        <PageHeader title="Monitor" />
        <ErrorBanner message={segmentsError} />
      </div>
    );
  }

  return (
    <div className="max-w-[1500px] mx-auto">
      <PageHeader
        title="Monitor"
        subtitle={
          currentSegment
            ? `Segment: ${currentSegment.nazev}`
            : 'Přehled napříč segmenty'
        }
        actions={
          <button
            type="button"
            onClick={() => setOnlyFavorites((v) => !v)}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-black uppercase tracking-widest rounded-md border shadow-sm transition-colors',
              onlyFavorites
                ? 'bg-[#fee600] border-[#fee600] text-slate-900'
                : 'bg-white border-slate-200 text-slate-500 hover:bg-slate-50',
            )}
          >
            <Star size={12} fill={onlyFavorites ? 'currentColor' : 'none'} />
            <span>Pouze oblíbené</span>
            <span className={cn(
              'px-1.5 py-0.5 rounded text-[9px] tabular-nums',
              onlyFavorites ? 'bg-slate-900 text-[#fee600]' : 'bg-slate-100 text-slate-500',
            )}>
              {favCount}
            </span>
          </button>
        }
      />

      <div className="grid grid-cols-12 gap-6">
        <aside className="col-span-12 lg:col-span-3 xl:col-span-2">
          <SegmentRail
            segmenty={segmenty}
            selectedSlug={selectedSlug}
            onSelect={setSelectedSlug}
          />
        </aside>

        <section className="col-span-12 lg:col-span-9 xl:col-span-10 space-y-4">
          {selectedSlug === null ? (
            <HlavniStranka
              segmenty={segmenty}
              onOpenSegment={setSelectedSlug}
            />
          ) : openArticleId ? (
            <ArticleDetail
              clanekId={openArticleId}
              spolecnosti={spolecnosti}
              onBack={() => setOpenArticleId(null)}
              onOpenCompany={setModalCompanyId}
              onSelectTag={(t) => { setOpenArticleId(null); setActiveTag(t); }}
              onOpenArticle={setOpenArticleId}
            />
          ) : (
            <>
              <SubNav
                active={activeTab}
                onChange={setActiveTab}
                maProdukty={Boolean(currentSegment?.ma_produkty)}
              />

              {activeTag && (
                <div className="flex items-center gap-2 text-[10px] font-bold text-slate-500 uppercase tracking-wider">
                  <span>Tag:</span>
                  <TagChip tag={activeTag} active />
                  <button
                    type="button"
                    onClick={() => setActiveTag(null)}
                    className="flex items-center gap-1 text-slate-400 hover:text-red-500"
                  >
                    <X size={10} /> zrušit
                  </button>
                </div>
              )}

              {activeTab !== 'mystery' && activeTab !== 'executive' && activeTab !== 'srovnani' && (
                <FilterBar
                  value={filters}
                  onChange={setFilters}
                  spolecnosti={spolecnosti}
                  produktoveLinie={produktoveLinie}
                />
              )}

              {dataError && <ErrorBanner message={dataError} />}

              {dataLoading && !data && (
                <div className="py-16 text-center text-[10px] font-black uppercase tracking-widest text-slate-300">
                  Načítám…
                </div>
              )}

              {data && activeTab === 'novinky' && (
                <NovinkyGrid
                  clanky={filterFavs((data.clanky || []) as Clanek[], 'clanek')}
                  signalyFallback={(data.signaly_fallback || []) as Signal[]}
                  spolecnostById={spolecnostById}
                  onOpenArticle={setOpenArticleId}
                  onSelectTag={setActiveTag}
                  filteringFavorites={onlyFavorites}
                />
              )}

              {data && activeTab === 'spolecnosti' && (
                <SpolecnostiGrid
                  spolecnosti={filterFavs(data as Competitor[], 'spolecnost')}
                  onOpen={setModalCompanyId}
                />
              )}

              {data && activeTab === 'produkty' && (
                <ProduktyGrid
                  produkty={filterFavs(data as Produkt[], 'produkt')}
                  spolecnostById={spolecnostById}
                  produktovaLinieName={produktovaLinieName}
                />
              )}

              {data && activeTab === 'srovnani' && currentSegment && (
                <ComparisonWizard
                  produktoveLinie={produktoveLinie}
                  produkty={data as Produkt[]}
                  spolecnosti={spolecnosti}
                />
              )}

              {data && activeTab === 'kampane' && (
                <KampaneGrid
                  kampane={filterFavs(data as Kampan[], 'kampan')}
                  spolecnostById={spolecnostById}
                />
              )}

              {data && activeTab === 'mystery' && (
                <MysteryGrid
                  shops={filterFavs(data as MysteryShop[], 'mystery')}
                  spolecnostById={spolecnostById}
                />
              )}

              {data && activeTab === 'executive' && (
                <ExecSummaryArchive items={data as ExecSummary[]} />
              )}
            </>
          )}
        </section>
      </div>

      <CompanyModal
        competitorId={modalCompanyId}
        onClose={() => setModalCompanyId(null)}
      />
    </div>
  );
}

// ── Sub-views ──────────────────────────────────────────────────

function HlavniStranka({
  segmenty, onOpenSegment,
}: {
  segmenty: Segment[];
  onOpenSegment: (slug: string) => void;
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-6 shadow-sm">
      <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-400 mb-4">
        Vyberte segment
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {segmenty.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => onOpenSegment(s.slug)}
            className="bg-slate-50 hover:bg-yellow-50 border border-slate-200 hover:border-[#fee600] rounded-lg p-5 text-left transition-all"
          >
            <div className="text-lg font-black text-slate-900 tracking-tight mb-2">
              {s.nazev}
            </div>
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
              {s.produktove_linie?.length ?? 0} produktových linií &middot;{' '}
              {s.spolecnosti?.length ?? 0} společností
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function NovinkyGrid({
  clanky, signalyFallback, spolecnostById,
  onOpenArticle, onSelectTag, filteringFavorites,
}: {
  clanky: Clanek[];
  signalyFallback: Signal[];
  spolecnostById: (id: string | null | undefined) => Competitor | undefined;
  onOpenArticle: (id: string) => void;
  onSelectTag: (tag: string) => void;
  filteringFavorites: boolean;
}) {
  if (clanky.length === 0 && signalyFallback.length === 0) {
    return (
      <EmptyState
        title={filteringFavorites ? 'Žádné oblíbené novinky' : 'Žádné novinky'}
        description={
          filteringFavorites
            ? 'Přidejte články do oblíbených kliknutím na hvězdičku.'
            : 'Po doplnění článků nebo zapnutí kolektorů se zde budou zobrazovat.'
        }
      />
    );
  }
  if (clanky.length > 0) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {clanky.map((c) => (
          <NewsCard
            key={c.id}
            item={c}
            spolecnost={spolecnostById(c.competitor_id)}
            onOpenArticle={onOpenArticle}
            onSelectTag={onSelectTag}
          />
        ))}
      </div>
    );
  }
  return (
    <>
      <div className="bg-amber-50 border border-amber-200 rounded px-4 py-2 text-[10px] font-bold text-amber-800 uppercase tracking-wider">
        Zatím zobrazujeme raw signály z kolektorů (žádné redakční články).
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {signalyFallback.map((s) => (
          <NewsCard
            key={s.id}
            item={s}
            spolecnost={spolecnostById(s.competitor_id)}
            onSelectTag={onSelectTag}
          />
        ))}
      </div>
    </>
  );
}

function SpolecnostiGrid({
  spolecnosti, onOpen,
}: {
  spolecnosti: Competitor[];
  onOpen: (id: string) => void;
}) {
  if (spolecnosti.length === 0) {
    return <EmptyState title="Žádné společnosti v tomto segmentu" />;
  }
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
      {spolecnosti.map((c) => (
        <CompanyTile key={c.id} spolecnost={c} onClick={onOpen} />
      ))}
    </div>
  );
}

function ProduktyGrid({
  produkty, spolecnostById, produktovaLinieName,
}: {
  produkty: Produkt[];
  spolecnostById: (id: string | null | undefined) => Competitor | undefined;
  produktovaLinieName: (id: string | null) => string | undefined;
}) {
  if (produkty.length === 0) {
    return (
      <EmptyState
        title="Žádné produkty"
        description="Produkty tohoto segmentu zatím nejsou v databázi. Po doplnění se zde zobrazí karty s klíčovými parametry."
      />
    );
  }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {produkty.map((p) => (
        <ProductCard
          key={p.id}
          produkt={p}
          spolecnost={spolecnostById(p.competitor_id)}
          produktovaLinieNazev={produktovaLinieName(p.produktova_linie_id)}
        />
      ))}
    </div>
  );
}

function KampaneGrid({
  kampane, spolecnostById,
}: {
  kampane: Kampan[];
  spolecnostById: (id: string | null | undefined) => Competitor | undefined;
}) {
  if (kampane.length === 0) {
    return (
      <EmptyState
        title="Žádné kampaně"
        description="Marketingové kampaně (TV / Outdoor / Web) se zde zobrazí po doplnění dat."
      />
    );
  }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {kampane.map((k) => (
        <CampaignCard key={k.id} kampan={k} spolecnost={spolecnostById(k.competitor_id)} />
      ))}
    </div>
  );
}

function MysteryGrid({
  shops, spolecnostById,
}: {
  shops: MysteryShop[];
  spolecnostById: (id: string | null | undefined) => Competitor | undefined;
}) {
  if (shops.length === 0) {
    return (
      <EmptyState
        title="Žádná Mystery Shopping data"
        description="Terénní testy produktů konkurence — závěrečné zprávy v PDF se zde zobrazí po doplnění."
      />
    );
  }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {shops.map((m) => (
        <MysteryCard
          key={m.id}
          shop={m}
          spolecnost={spolecnostById(m.competitor_id)}
        />
      ))}
    </div>
  );
}
