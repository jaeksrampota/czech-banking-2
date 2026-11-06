import { useMemo, useState } from 'react';
import {
  Download, ExternalLink, FileText, Megaphone, Newspaper, Package, Search, BookOpen, Globe,
} from 'lucide-react';
import { api, digestDownloadUrl, type DigestParams } from '../api';
import type {
  Digest as DigestData, DigestExecSummary, DigestKampan, DigestMystery, DigestPeriodTyp,
  DigestProdukt, DigestSpolecnost, DigestZpravySkupina,
} from '../types';
import PageHeader from '../components/PageHeader';
import ErrorBanner from '../components/ErrorBanner';
import EmptyState from '../components/finecim/EmptyState';
import CompanyLogo from '../components/finecim/CompanyLogo';
import TagChip from '../components/finecim/TagChip';
import { useFetch } from '../hooks/useFetch';
import { cn, formatDate, MEDIA_TYPE_LABELS, TIER_LABELS } from '../utils';

const MAX_PARAMETERS = 8;

const PRODUCT_KINDS: Record<DigestProdukt['druh'], { label: string; cls: string }> = {
  novy: { label: 'Nový produkt', cls: 'bg-emerald-100 text-emerald-700' },
  zmena: { label: 'Změna parametrů', cls: 'bg-amber-100 text-amber-700' },
  aktualizace: { label: 'Aktualizace', cls: 'bg-blue-100 text-blue-700' },
};

const CAMPAIGN_KINDS: Record<DigestKampan['druh'], { label: string; cls: string }> = {
  nova: { label: 'Nová kampaň', cls: 'bg-emerald-100 text-emerald-700' },
  aktualizovana: { label: 'Aktualizovaná kampaň', cls: 'bg-blue-100 text-blue-700' },
};

function todayIso(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export default function Digest() {
  const [period, setPeriod] = useState<DigestPeriodTyp>('weekly');
  const [until, setUntil] = useState(todayIso());
  const [segment, setSegment] = useState('');

  const segmenty = useFetch(() => api.getSegmenty());
  const params = useMemo<DigestParams>(
    () => ({ period, until: until || undefined, segment: segment || undefined }),
    [period, until, segment],
  );
  const { data, loading, error, lastUpdated, refresh } = useFetch(
    () => api.getDigest(params),
    { deps: [params] },
  );

  const header = (
    <PageHeader
      title="Digest konkurence"
      subtitle={data ? `${data.period.nazev} · ${data.period.popis}` : 'Týdenní a měsíční přehled novinek konkurence'}
      loading={loading}
      lastUpdated={lastUpdated}
      onRefresh={refresh}
      actions={<DownloadLinks params={params} />}
    />
  );

  const controls = (
    <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm flex flex-wrap items-center gap-3">
      <div className="flex rounded-md border border-slate-200 overflow-hidden" role="group" aria-label="Období">
        {(['weekly', 'monthly'] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setPeriod(t)}
            aria-pressed={period === t}
            className={cn(
              'px-4 py-2 text-[10px] font-black uppercase tracking-widest transition-colors',
              period === t ? 'bg-[#fee600] text-slate-900' : 'bg-white text-slate-400 hover:text-slate-900 hover:bg-slate-50',
            )}
          >
            {t === 'weekly' ? 'Týden' : 'Měsíc'}
          </button>
        ))}
      </div>
      <label className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
        do
        <input
          type="date"
          value={until}
          onChange={(e) => setUntil(e.target.value)}
          className="bg-slate-50 border border-slate-200 rounded py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-900 focus:outline-none focus:border-[#fee600] transition-colors"
        />
      </label>
      <select
        value={segment}
        onChange={(e) => setSegment(e.target.value)}
        aria-label="Segment"
        className={cn(
          'bg-slate-50 border border-slate-200 rounded py-2 px-3 text-[10px] font-bold uppercase tracking-wider',
          'focus:outline-none focus:border-[#fee600] transition-colors appearance-none cursor-pointer min-w-[160px]',
          segment ? 'text-slate-900' : 'text-slate-400',
        )}
      >
        <option value="">všechny segmenty</option>
        {(segmenty.data ?? []).map((s) => (
          <option key={s.slug} value={s.slug}>{s.nazev}</option>
        ))}
      </select>
      {data && (
        <div className="ml-auto text-[9px] font-bold text-slate-400 uppercase tracking-wider">
          {formatDate(data.period.od)} – {formatDate(data.period.do)}
        </div>
      )}
    </div>
  );

  if (error) {
    return (
      <div className="max-w-[1400px] mx-auto space-y-4">
        {header}
        {controls}
        <ErrorBanner message={error} onRetry={refresh} />
      </div>
    );
  }

  if (loading && !data) {
    return (
      <div className="max-w-[1400px] mx-auto space-y-4">
        {header}
        {controls}
        <div className="animate-pulse space-y-4">
          <div className="bg-white border border-slate-200 rounded-lg h-24 shadow-sm" />
          <div className="bg-white border border-slate-200 rounded-lg h-[420px] shadow-sm" />
        </div>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="max-w-[1400px] mx-auto space-y-6">
      {header}
      {controls}

      {data.prazdny ? (
        <EmptyState
          title="Za toto období nejsou žádné položky"
          description="Zkuste jiné období nebo segment, případně spusťte ci-monitor finecim sync."
        />
      ) : (
        <>
          <Numbers data={data} />
          <Section number={2} title="Co je nové" icon={Newspaper}>
            {data.spolecnosti.length === 0 ? (
              <p className="text-xs text-slate-400 font-medium">Žádná společnost nemá v období nové položky.</p>
            ) : (
              <div className="space-y-6">
                {data.spolecnosti.map((c) => <CompanyBlock key={c.id} company={c} />)}
              </div>
            )}
          </Section>
          <Section number={3} title="Executive summary" icon={BookOpen}>
            {data.executive_summary.length === 0 ? (
              <p className="text-xs text-slate-400 font-medium">V období nejsou žádné položky executive summary.</p>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {data.executive_summary.map((s) => <SummaryCard key={s.id} summary={s} />)}
              </div>
            )}
          </Section>
          <Section number={4} title="Bankovní trh a nezařazené zprávy" icon={Globe}>
            {data.trh.length === 0 ? (
              <p className="text-xs text-slate-400 font-medium">Žádné zprávy z trhu.</p>
            ) : (
              <NewsGroups groups={data.trh} withCompany />
            )}
          </Section>
        </>
      )}
    </div>
  );
}

// ── building blocks ──────────────────────────────────────────

function DownloadLinks({ params }: { params: DigestParams }) {
  const cls = 'flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-black uppercase tracking-widest bg-white border border-slate-200 rounded-md shadow-sm hover:bg-slate-50 transition-colors text-slate-700';
  return (
    <div className="flex items-center gap-2">
      <a href={digestDownloadUrl(params, 'md')} download className={cls} title="Stáhnout jako Markdown">
        <Download size={12} /> MD
      </a>
      <a href={digestDownloadUrl(params, 'html')} target="_blank" rel="noopener noreferrer" className={cls} title="Otevřít jako HTML">
        <FileText size={12} /> HTML
      </a>
    </div>
  );
}

function Section({
  number, title, icon: Icon, children,
}: {
  number: number;
  title: string;
  icon: typeof Newspaper;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4">
      <h3 className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.3em] text-slate-900">
        <span className="w-6 h-6 rounded bg-[#fee600] text-slate-900 flex items-center justify-center text-[10px]">
          {number}
        </span>
        <Icon size={12} className="text-slate-400" aria-hidden="true" />
        {title}
      </h3>
      {children}
    </section>
  );
}

function Numbers({ data }: { data: DigestData }) {
  const s = data.souhrn;
  const kpis = [
    { label: 'Články', value: s.clanky },
    { label: 'Kampaně', value: s.kampane },
    { label: 'Produkty', value: s.produkty },
    { label: 'Mystery shopping', value: s.mystery_shopping },
    { label: 'Executive summary', value: s.executive_summary },
    { label: 'Zprávy z trhu', value: s.trh },
  ];
  return (
    <Section number={1} title="Čísla za období" icon={Search}>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {kpis.map((k) => (
          <div key={k.label} className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm">
            <div className="text-[9px] font-black uppercase tracking-widest text-slate-400">{k.label}</div>
            <div className="text-2xl font-black text-slate-900 tabular-nums mt-1">{k.value}</div>
          </div>
        ))}
      </div>
      {data.spolecnosti.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-[10px] text-left border-collapse">
              <thead>
                <tr className="text-slate-400 border-b border-slate-100 bg-slate-50/30">
                  <th className="px-6 py-3 font-black uppercase tracking-widest">Společnost</th>
                  <th className="px-6 py-3 font-black uppercase tracking-widest">Tier</th>
                  <th className="px-6 py-3 font-black uppercase tracking-widest text-right">Články</th>
                  <th className="px-6 py-3 font-black uppercase tracking-widest text-right">Kampaně</th>
                  <th className="px-6 py-3 font-black uppercase tracking-widest text-right">Produkty</th>
                  <th className="px-6 py-3 font-black uppercase tracking-widest text-right">Mystery shopping</th>
                </tr>
              </thead>
              <tbody>
                {data.spolecnosti.map((c) => (
                  <tr key={c.id} className="border-b border-slate-50 hover:bg-yellow-50/30 transition-colors">
                    <td className="px-6 py-3">
                      <a href={`#digest-${c.id}`} className="flex items-center gap-2 font-bold text-slate-900 hover:underline">
                        <CompanyLogo competitorId={c.id} name={c.nazev} tier={c.tier ?? 3} size={22} />
                        {c.nazev}
                      </a>
                    </td>
                    <td className="px-6 py-3"><TierBadge tier={c.tier} /></td>
                    <td className="px-6 py-3 text-right font-black text-slate-900 tabular-nums">{c.pocty.clanky}</td>
                    <td className="px-6 py-3 text-right font-black text-slate-900 tabular-nums">{c.pocty.kampane}</td>
                    <td className="px-6 py-3 text-right font-black text-slate-900 tabular-nums">{c.pocty.produkty}</td>
                    <td className="px-6 py-3 text-right font-black text-slate-900 tabular-nums">{c.pocty.mystery_shopping}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Section>
  );
}

function TierBadge({ tier }: { tier: number | null }) {
  if (tier == null) return <span className="text-slate-300">—</span>;
  const info = TIER_LABELS[tier];
  return (
    <span className={cn(
      'inline-flex px-2 py-0.5 rounded border text-[9px] font-black uppercase tracking-widest',
      info?.badge ?? 'border-slate-200 text-slate-600 bg-slate-50',
    )} title={info?.dlouhy}>
      {info?.kratky ?? `T${tier}`}
    </span>
  );
}

function KindBadge({ label, cls }: { label: string; cls: string }) {
  return (
    <span className={cn('px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest shrink-0', cls)}>
      {label}
    </span>
  );
}

function Block({ title, icon: Icon, children }: { title: string; icon: typeof Package; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.3em] text-slate-400 mb-3">
        <Icon size={12} aria-hidden="true" /> {title}
      </h4>
      {children}
    </div>
  );
}

function CompanyBlock({ company: c }: { company: DigestSpolecnost }) {
  const n = c.pocty;
  const counts = [
    n.clanky ? `${n.clanky} článků` : null,
    n.kampane ? `${n.kampane} kampaní` : null,
    n.produkty ? `${n.produkty} produktů` : null,
    n.mystery_shopping ? `${n.mystery_shopping} mystery shopping` : null,
  ].filter(Boolean).join(' · ');
  return (
    <article id={`digest-${c.id}`} className="bg-white border border-slate-200 rounded-lg shadow-sm scroll-mt-24">
      <header className="px-6 py-4 border-b border-slate-100 bg-slate-50/50 flex items-center gap-3">
        <CompanyLogo competitorId={c.id} name={c.nazev} tier={c.tier ?? 3} size={32} />
        <h3 className="text-sm font-black text-slate-900">{c.nazev}</h3>
        <TierBadge tier={c.tier} />
        <span className="ml-auto text-[9px] font-bold uppercase tracking-wider text-slate-400">{counts}</span>
      </header>
      <div className="p-6 space-y-6">
        {c.produkty.length > 0 && (
          <Block title="Produkty" icon={Package}>
            <ul className="space-y-3">{c.produkty.map((p) => <ProductRow key={p.id} produkt={p} />)}</ul>
          </Block>
        )}
        {c.kampane.length > 0 && (
          <Block title="Kampaně" icon={Megaphone}>
            <ul className="space-y-3">{c.kampane.map((k) => <CampaignRow key={k.id} kampan={k} />)}</ul>
          </Block>
        )}
        {c.zpravy.length > 0 && (
          <Block title="Zprávy" icon={Newspaper}>
            <NewsGroups groups={c.zpravy} />
          </Block>
        )}
        {c.mystery_shopping.length > 0 && (
          <Block title="Mystery shopping" icon={FileText}>
            <ul className="space-y-3">{c.mystery_shopping.map((m) => <MysteryRow key={m.id} shop={m} />)}</ul>
          </Block>
        )}
      </div>
    </article>
  );
}

function ItemTitle({ nazev, url }: { nazev: string; url: string | null }) {
  if (!url) return <span className="text-sm font-black text-slate-900">{nazev}</span>;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="text-sm font-black text-slate-900 hover:underline inline-flex items-center gap-1">
      {nazev} <ExternalLink size={11} className="text-slate-300" aria-hidden="true" />
    </a>
  );
}

function paramLabel(section: string | null, name: string): string {
  return section ? `${section}: ${name}` : name;
}

function ProductRow({ produkt: p }: { produkt: DigestProdukt }) {
  const kind = PRODUCT_KINDS[p.druh];
  const context = [
    p.segment ? p.segment.nazev + (p.produktova_linie ? ` / ${p.produktova_linie}` : '') : null,
    p.zakaznicky_segment,
  ].filter(Boolean).join(' · ');
  return (
    <li className="border border-slate-100 rounded-md p-4">
      <div className="flex flex-wrap items-center gap-2">
        <KindBadge label={kind.label} cls={kind.cls} />
        <ItemTitle nazev={p.nazev} url={p.url} />
        {context && <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">{context}</span>}
        {p.druh !== 'novy' && p.aktualizace && (
          <span className="text-[10px] font-bold text-slate-400">aktualizace {formatDate(p.aktualizace)}</span>
        )}
      </div>
      {p.kratky_popis && <p className="text-xs text-slate-500 font-medium mt-1.5">{p.kratky_popis}</p>}
      {p.druh === 'zmena' && (
        <ul className="mt-2 text-[11px] space-y-1">
          {p.zmeny.map((z) => (
            <li key={`${z.section ?? ''}|${z.name}`} className="flex flex-wrap gap-1.5">
              <span className="font-bold text-slate-700">{paramLabel(z.section, z.name)}:</span>
              {z.druh === 'pridano' && <span>nově <strong className="text-emerald-700">{z.nova ?? '—'}</strong></span>}
              {z.druh === 'odebrano' && <span>odebráno (dříve <s className="text-slate-400">{z.stara ?? '—'}</s>)</span>}
              {z.druh === 'zmena' && (
                <span><s className="text-slate-400">{z.stara ?? '—'}</s> → <strong className="text-amber-700">{z.nova ?? '—'}</strong></span>
              )}
            </li>
          ))}
        </ul>
      )}
      {p.druh === 'novy' && p.parametry.length > 0 && (
        <dl className="mt-2 text-[10px] grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1">
          {p.parametry.slice(0, MAX_PARAMETERS).map((a) => (
            <div key={`${a.section ?? ''}|${a.name}`} className="flex gap-2 min-w-0">
              <dt className="text-slate-400 font-bold shrink-0">{paramLabel(a.section, a.name)}:</dt>
              <dd className="text-slate-700 font-bold truncate">{a.value ?? '—'}</dd>
            </div>
          ))}
          {p.parametry.length > MAX_PARAMETERS && (
            <div className="text-slate-300 font-bold">+ {p.parametry.length - MAX_PARAMETERS} dalších parametrů</div>
          )}
        </dl>
      )}
      {p.druh === 'aktualizace' && (
        <p className="text-[10px] text-slate-400 font-bold mt-1.5">bez zjištěné změny parametrů</p>
      )}
    </li>
  );
}

function CampaignRow({ kampan: k }: { kampan: DigestKampan }) {
  const kind = CAMPAIGN_KINDS[k.druh];
  const kr = k.prvni_kreativa;
  return (
    <li className="border border-slate-100 rounded-md p-4 flex gap-4">
      {k.kreativa_url && (
        <div className="w-28 shrink-0 aspect-video bg-slate-100 rounded overflow-hidden hidden sm:block">
          <img
            src={k.kreativa_url}
            alt=""
            className="w-full h-full object-cover"
            loading="lazy"
            onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
          />
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <KindBadge label={kind.label} cls={kind.cls} />
          <ItemTitle nazev={k.nazev} url={k.url} />
          {k.segment && <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">{k.segment.nazev}</span>}
        </div>
        <dl className="text-[10px] flex flex-wrap gap-x-4 gap-y-1 mt-1.5">
          {k.zacatek && (
            <div className="flex gap-1.5"><dt className="text-slate-400 font-bold">začátek:</dt><dd className="text-slate-700 font-bold">{formatDate(k.zacatek)}</dd></div>
          )}
          {k.druh === 'aktualizovana' && k.aktualizace && (
            <div className="flex gap-1.5"><dt className="text-slate-400 font-bold">aktualizace:</dt><dd className="text-slate-700 font-bold">{formatDate(k.aktualizace)}</dd></div>
          )}
          {k.typy_kampane.length > 0 && (
            <div className="flex gap-1.5"><dt className="text-slate-400 font-bold">typ:</dt><dd className="text-slate-700 font-bold">{k.typy_kampane.join(', ')}</dd></div>
          )}
        </dl>
        {k.media_typy.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {k.media_typy.map((m) => (
              <span key={m} className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest bg-[#fee600]/40 text-slate-900">
                {MEDIA_TYPE_LABELS[m] || m}
              </span>
            ))}
          </div>
        )}
        {k.popis && <p className="text-xs text-slate-500 font-medium mt-2 line-clamp-3">{k.popis}</p>}
        {kr && (
          <p className="text-[10px] font-bold text-slate-600 mt-2 flex flex-wrap items-center gap-2">
            <span className="text-slate-400 uppercase tracking-wider">První kreativa</span>
            {kr.datum && <span className="text-slate-400">{formatDate(kr.datum)}</span>}
            {kr.media_typ && <span className="uppercase tracking-wider text-slate-400">{MEDIA_TYPE_LABELS[kr.media_typ] || kr.media_typ}</span>}
            {kr.media_url ? (
              <a href={kr.media_url} target="_blank" rel="noopener noreferrer" className="hover:text-slate-900 truncate">
                {kr.popis || (kr.media_druh === 'video' ? 'Video' : 'Kreativa')}
              </a>
            ) : (
              <span className="truncate">{kr.popis}</span>
            )}
            {k.pocet_kreativ > 1 && <span className="text-slate-300">(celkem {k.pocet_kreativ})</span>}
          </p>
        )}
      </div>
    </li>
  );
}

function NewsGroups({ groups, withCompany = false }: { groups: DigestZpravySkupina[]; withCompany?: boolean }) {
  return (
    <div className="space-y-4">
      {groups.map((g) => (
        <div key={g.typ}>
          <div className="text-[9px] font-black uppercase tracking-widest text-slate-500 mb-2 px-1.5 py-0.5 bg-slate-100 rounded inline-block">
            {g.typ}
          </div>
          <ul className="space-y-2">
            {g.polozky.map((item) => (
              <li key={item.id} className="border border-slate-100 rounded-md p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">{formatDate(item.datum)}</span>
                  <ItemTitle nazev={item.nazev} url={item.url} />
                  {item.segment && <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">{item.segment.nazev}</span>}
                  {withCompany && item.spolecnost && (
                    <span className="text-[10px] font-bold text-slate-700 uppercase tracking-wider">{item.spolecnost.nazev}</span>
                  )}
                </div>
                {item.perex && <p className="text-xs text-slate-500 font-medium mt-1 line-clamp-2">{item.perex}</p>}
                {item.tagy.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {item.tagy.slice(0, 4).map((t) => <TagChip key={t} tag={t} />)}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function MysteryRow({ shop: m }: { shop: DigestMystery }) {
  const first = (m.popis ?? '').trim().split('\n')[0];
  return (
    <li className="border border-slate-100 rounded-md p-4 flex flex-wrap items-start gap-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">{formatDate(m.datum)}</span>
          <ItemTitle nazev={m.nazev} url={m.url} />
          {m.segment && <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">{m.segment.nazev}</span>}
        </div>
        {first && <p className="text-xs text-slate-500 font-medium mt-1">{first}</p>}
      </div>
      {m.pdf_url ? (
        <a
          href={m.pdf_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-slate-700 hover:text-slate-900 border border-slate-200 rounded-md px-3 py-2 hover:bg-slate-50 shrink-0"
        >
          <FileText size={12} /> <span>PDF zpráva</span> <Download size={11} />
        </a>
      ) : (
        <span className="text-[9px] font-bold text-slate-300 uppercase tracking-wider shrink-0">bez PDF</span>
      )}
    </li>
  );
}

function SummaryCard({ summary: s }: { summary: DigestExecSummary }) {
  return (
    <article className="bg-white border border-slate-200 rounded-lg shadow-sm">
      <header className="px-5 py-3 border-b border-slate-100 bg-slate-50/50 flex items-center gap-2">
        <BookOpen size={12} className="text-slate-400" aria-hidden="true" />
        <h4 className="text-[10px] font-black uppercase tracking-widest text-slate-900">
          {s.segment?.nazev ?? '—'} · {s.nazev}
        </h4>
        {s.pdf_url && (
          <a href={s.pdf_url} target="_blank" rel="noopener noreferrer" className="ml-auto text-[9px] font-black uppercase tracking-widest text-slate-500 hover:text-slate-900 flex items-center gap-1">
            <FileText size={11} /> PDF
          </a>
        )}
      </header>
      <ul className="p-5 space-y-3">
        {s.polozky.length === 0 && <li className="text-xs text-slate-400 font-medium">bez položek</li>}
        {s.polozky.map((e) => (
          <li key={e.id} className="text-xs">
            <ItemTitle nazev={e.nazev ?? '—'} url={e.url} />
            {e.text && <p className="text-slate-500 font-medium mt-0.5">{e.text}</p>}
          </li>
        ))}
      </ul>
    </article>
  );
}
