import { useEffect, useState } from 'react';
import { ArrowLeft, ExternalLink, Share2 } from 'lucide-react';
import { api } from '../../api';
import { formatDate, cn } from '../../utils';
import type { ClanekDetail, Competitor, Clanek } from '../../types';
import CompanyLogo from './CompanyLogo';
import FavoriteButton from './FavoriteButton';
import TagChip from './TagChip';

interface Props {
  clanekId: string;
  spolecnosti: Competitor[];
  onBack: () => void;
  onOpenCompany: (id: string) => void;
  onSelectTag: (tag: string) => void;
  onOpenArticle: (id: string) => void;
}

export default function ArticleDetail({
  clanekId, spolecnosti, onBack, onOpenCompany, onSelectTag, onOpenArticle,
}: Props) {
  const [data, setData] = useState<ClanekDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api.getClanek(clanekId)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Chyba'))
      .finally(() => setLoading(false));
  }, [clanekId]);

  const spol = data?.competitor_id
    ? spolecnosti.find((c) => c.id === data.competitor_id)
    : undefined;

  return (
    <div className="space-y-4">
      <button
        type="button"
        onClick={onBack}
        className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-slate-400 hover:text-slate-900 transition-colors"
      >
        <ArrowLeft size={14} /> Zpět na novinky
      </button>

      {loading && !data && (
        <div className="bg-white border border-slate-200 rounded-lg p-12 text-center text-[10px] font-black uppercase tracking-widest text-slate-300 shadow-sm">
          Načítám článek…
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-red-700 text-sm">
          {error}
        </div>
      )}

      {data && (
        <div className="grid grid-cols-12 gap-6">
          <article className="col-span-12 lg:col-span-8 bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden">
            {/* Header */}
            <div className="p-6 border-b border-slate-100">
              <div className="flex items-center gap-4 mb-4">
                {spol && (
                  <button
                    type="button"
                    onClick={() => onOpenCompany(spol.id)}
                    className="shrink-0"
                    aria-label={`Otevřít profil ${spol.name}`}
                  >
                    <CompanyLogo
                      competitorId={spol.id}
                      name={spol.name}
                      tier={spol.tier}
                      size={48}
                    />
                  </button>
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    {data.stav && (
                      <span className={cn(
                        'px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest',
                        data.stav === 'updated'
                          ? 'bg-amber-100 text-amber-700'
                          : 'bg-emerald-100 text-emerald-700',
                      )}>
                        {data.stav === 'updated' ? 'aktualizováno' : 'nové'}
                      </span>
                    )}
                    <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
                      {formatDate(data.datum)}
                    </span>
                    {data.typ_zpravy && (
                      <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
                        | Typ zprávy: <span className="text-slate-900">{data.typ_zpravy}</span>
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <FavoriteButton type="clanek" id={data.id} size={18} />
                  {data.url && (
                    <a
                      href={data.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label="Otevřít zdroj"
                      className="p-1 rounded text-slate-300 hover:text-slate-700"
                    >
                      <ExternalLink size={16} />
                    </a>
                  )}
                  <button
                    type="button"
                    onClick={() => navigator.clipboard?.writeText(window.location.href + '#' + data.id)}
                    className="p-1 rounded text-slate-300 hover:text-slate-700"
                    aria-label="Zkopírovat odkaz"
                    title="Zkopírovat odkaz"
                  >
                    <Share2 size={16} />
                  </button>
                </div>
              </div>

              <h1 className="text-2xl font-black text-slate-900 tracking-tight leading-tight">
                {data.nazev}
              </h1>

              {spol && (
                <button
                  type="button"
                  onClick={() => onOpenCompany(spol.id)}
                  className="mt-2 text-[11px] font-bold text-slate-500 uppercase tracking-wider hover:text-slate-900"
                >
                  {spol.name}
                </button>
              )}
            </div>

            {/* Perex */}
            {data.perex && (
              <div className="px-6 pt-5">
                <p className="text-sm text-slate-700 font-medium leading-relaxed border-l-4 border-[#fee600] pl-4">
                  {data.perex}
                </p>
              </div>
            )}

            {/* Body */}
            {data.telo && data.telo !== data.perex && (
              <div className="px-6 py-5 text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">
                {data.telo}
              </div>
            )}

            {/* Tagy */}
            {data.tagy && data.tagy.length > 0 && (
              <div className="px-6 py-4 border-t border-slate-100">
                <div className="text-[9px] font-black uppercase tracking-widest text-slate-400 mb-2">
                  Tagy
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {data.tagy.map((t) => (
                    <TagChip key={t} tag={t} onClick={onSelectTag} />
                  ))}
                </div>
              </div>
            )}
          </article>

          {/* Pravý sloupec — související */}
          <aside className="col-span-12 lg:col-span-4 space-y-4">
            <div className="bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden">
              <div className="px-5 py-3 border-b border-slate-100 bg-slate-50/50">
                <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-700">
                  Mohlo by Vás také zajímat
                </h3>
              </div>
              <ul className="divide-y divide-slate-50">
                {data.related.length === 0 ? (
                  <li className="px-5 py-4 text-[10px] font-bold text-slate-300 uppercase tracking-widest">
                    Žádné další články
                  </li>
                ) : (
                  data.related.map((r) => (
                    <RelatedRow
                      key={r.id}
                      clanek={r}
                      spolecnost={spolecnosti.find((c) => c.id === r.competitor_id)}
                      onOpen={onOpenArticle}
                    />
                  ))
                )}
              </ul>
            </div>

            {spol && (
              <div className="bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden">
                <div className="px-5 py-3 border-b border-slate-100 bg-slate-50/50">
                  <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-700">
                    Související společnost
                  </h3>
                </div>
                <button
                  type="button"
                  onClick={() => onOpenCompany(spol.id)}
                  className="w-full px-5 py-3 flex items-center gap-3 hover:bg-slate-50 transition-colors text-left"
                >
                  <CompanyLogo
                    competitorId={spol.id}
                    name={spol.name}
                    tier={spol.tier}
                    size={32}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-black text-slate-900">{spol.name}</div>
                    {spol.parent_group && (
                      <div className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">
                        {spol.parent_group}
                      </div>
                    )}
                  </div>
                </button>
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

function RelatedRow({
  clanek, spolecnost, onOpen,
}: {
  clanek: Clanek;
  spolecnost?: Competitor;
  onOpen: (id: string) => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onOpen(clanek.id)}
        className="w-full px-5 py-3 flex items-start gap-3 hover:bg-yellow-50/30 transition-colors text-left"
      >
        {spolecnost && (
          <CompanyLogo
            competitorId={spolecnost.id}
            name={spolecnost.name}
            tier={spolecnost.tier}
            size={24}
            className="shrink-0 mt-0.5"
          />
        )}
        <div className="flex-1 min-w-0">
          <div className="text-xs font-bold text-slate-900 leading-snug line-clamp-2">
            {clanek.nazev}
          </div>
          <div className="text-[9px] font-bold text-slate-400 uppercase tracking-wider mt-0.5">
            {formatDate(clanek.datum)}
          </div>
        </div>
      </button>
    </li>
  );
}
