import { useEffect, useState } from 'react';
import { X, ExternalLink, Users, MapPin, Wallet, Building } from 'lucide-react';
import { api } from '../../api';
import { cn, TIER_LABELS, formatDate } from '../../utils';
import type { SpolecnostDetail } from '../../types';
import CompanyLogo from './CompanyLogo';
import FavoriteButton from './FavoriteButton';

interface Props {
  competitorId: string | null;
  onClose: () => void;
}

export default function CompanyModal({ competitorId, onClose }: Props) {
  const [detail, setDetail] = useState<SpolecnostDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!competitorId) {
      setDetail(null);
      return;
    }
    setLoading(true);
    setError(null);
    api.getSpolecnostDetail(competitorId)
      .then(setDetail)
      .catch((e) => setError(e instanceof Error ? e.message : 'Chyba'))
      .finally(() => setLoading(false));
  }, [competitorId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  if (!competitorId) return null;

  const tier = detail ? TIER_LABELS[detail.tier] : null;

  return (
    <div
      className="fixed inset-0 z-[100] bg-slate-900/40 backdrop-blur-sm flex items-start justify-center pt-16 pb-8 px-4 overflow-y-auto"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Profil společnosti"
    >
      <div
        className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[calc(100vh-8rem)] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Hlavička modalu */}
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
          <h2 className="text-[11px] font-black uppercase tracking-[0.2em] text-slate-500">
            Profil společnosti
          </h2>
          <div className="flex items-center gap-2">
            {competitorId && <FavoriteButton type="spolecnost" id={competitorId} size={16} />}
            <button
              type="button"
              onClick={onClose}
              aria-label="Zavřít"
              className="text-slate-400 hover:text-slate-900 transition-colors"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="overflow-y-auto flex-1">
          {loading && !detail && (
            <div className="p-10 text-center text-[10px] font-black uppercase tracking-widest text-slate-300">
              Načítám profil…
            </div>
          )}
          {error && (
            <div className="p-10 text-center text-[10px] font-black uppercase tracking-widest text-red-500">
              Chyba: {error}
            </div>
          )}
          {detail && (
            <div className="p-6 space-y-6">
              {/* Hlava */}
              <div className="flex items-start gap-6">
                <CompanyLogo
                  competitorId={detail.id}
                  name={detail.name}
                  tier={detail.tier}
                  size={80}
                />
                <div className="flex-1">
                  <h3 className="text-2xl font-black text-slate-900 tracking-tight mb-1">
                    {detail.name}
                  </h3>
                  {detail.parent_group && (
                    <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                      {detail.parent_group}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-2 mt-3">
                    {detail.segmenty?.map((s) => (
                      <span
                        key={s.id}
                        className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest bg-yellow-50 text-slate-700 border border-yellow-200"
                      >
                        {s.nazev}
                      </span>
                    ))}
                    <span
                      className={cn(
                        'px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest border',
                        tier?.badge,
                      )}
                    >
                      {tier?.dlouhy || `T${detail.tier}`}
                    </span>
                  </div>
                </div>
              </div>

              {/* Popis */}
              {detail.popis && (
                <p className="text-sm text-slate-600 leading-relaxed">
                  {detail.popis}
                </p>
              )}

              {/* Základní údaje */}
              <section>
                <h4 className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-400 mb-3">
                  Základní informace o společnosti
                </h4>
                <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-2 text-[11px]">
                  <Field label="Obchodní firma" value={detail.name} />
                  <Field label="IČO" value={detail.ico || '—'} mono />
                  <Field label="Sídlo" value={detail.sidlo || '—'} icon={<MapPin size={10} />} />
                  <Field label="Základní kapitál" value={detail.zakladni_kapital || '—'} icon={<Wallet size={10} />} />
                  <Field label="Akcionář" value={detail.akcionar || '—'} icon={<Building size={10} />} />
                  <Field label="Poslední aktualizace" value={formatDate(detail.posledni_aktualizace)} />
                </dl>
              </section>

              {/* Představenstvo */}
              {detail.predstavenstvo && detail.predstavenstvo.length > 0 && (
                <section>
                  <h4 className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-400 mb-3 flex items-center gap-2">
                    <Users size={12} /> Představenstvo
                  </h4>
                  <ul className="space-y-1">
                    {detail.predstavenstvo.map((p, i) => (
                      <li key={i} className="text-[11px] text-slate-700">
                        <span className="font-bold">{p.jmeno}</span>
                        {p.role && (
                          <span className="text-slate-400 font-medium"> — {p.role}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {/* KPI */}
              {(detail.pocet_klientu || detail.pocet_pobocek || detail.pocet_bankomatu) && (
                <div className="grid grid-cols-3 gap-4">
                  <KPI label="Klientů" value={detail.pocet_klientu} />
                  <KPI label="Poboček" value={detail.pocet_pobocek} />
                  <KPI label="Bankomatů" value={detail.pocet_bankomatu} />
                </div>
              )}

              {/* Související obsah */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-4 border-t border-slate-100">
                <RelatedList title="Související zprávy" items={detail.clanky?.map((c) => ({ id: c.id, text: c.nazev, url: c.url }))} />
                <RelatedList title="Související kampaně" items={detail.kampane?.map((k) => ({ id: k.id, text: k.nazev, url: k.kreativa_url }))} />
                <RelatedList title="Mystery Shopping" items={detail.mystery_shopping?.map((m) => ({ id: m.id, text: m.nazev, url: m.pdf_url }))} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, icon, mono }: { label: string; value: string; icon?: React.ReactNode; mono?: boolean }) {
  return (
    <div>
      <dt className="text-[9px] font-black uppercase tracking-widest text-slate-400 mb-0.5 flex items-center gap-1">
        {icon} {label}
      </dt>
      <dd className={cn('text-slate-800 font-medium', mono && 'font-mono')}>{value}</dd>
    </div>
  );
}

function KPI({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="bg-slate-50 rounded p-4 text-center">
      <div className="text-[8px] font-black uppercase tracking-widest text-slate-400 mb-1">
        {label}
      </div>
      <div className="text-lg font-black text-slate-900 tabular-nums">
        {value != null ? value.toLocaleString('cs-CZ') : '—'}
      </div>
    </div>
  );
}

function RelatedList({
  title, items,
}: {
  title: string;
  items?: { id: string; text: string; url?: string | null }[];
}) {
  return (
    <div>
      <h5 className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-400 mb-2">
        {title}
      </h5>
      {!items || items.length === 0 ? (
        <p className="text-[10px] text-slate-300 font-medium">Zatím žádné položky.</p>
      ) : (
        <ul className="space-y-1">
          {items.slice(0, 6).map((it) => (
            <li key={it.id} className="text-[11px] text-slate-700 flex items-start gap-1.5">
              {it.url ? (
                <a href={it.url} target="_blank" rel="noopener noreferrer" className="hover:text-slate-900 flex items-start gap-1.5 font-medium">
                  <ExternalLink size={10} className="mt-0.5 text-slate-300 shrink-0" />
                  <span>{it.text}</span>
                </a>
              ) : (
                <span className="font-medium">{it.text}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
