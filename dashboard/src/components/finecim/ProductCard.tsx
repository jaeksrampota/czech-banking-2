import { ExternalLink } from 'lucide-react';
import type { Produkt, Competitor } from '../../types';
import CompanyLogo from './CompanyLogo';
import FavoriteButton from './FavoriteButton';

interface Props {
  produkt: Produkt;
  spolecnost?: Competitor;
  produktovaLinieNazev?: string;
}

export default function ProductCard({ produkt, spolecnost, produktovaLinieNazev }: Props) {
  return (
    <article className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm hover:border-[#fee600] transition-colors flex flex-col">
      <div className="flex items-start justify-between mb-3 gap-2">
        <div className="flex items-start gap-2 min-w-0">
          {spolecnost && (
            <CompanyLogo
              competitorId={spolecnost.id}
              name={spolecnost.name}
              tier={spolecnost.tier}
              size={28}
              className="shrink-0 mt-0.5"
            />
          )}
          <h3 className="text-sm font-black text-slate-900 leading-tight">
            {produkt.nazev}
          </h3>
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          <FavoriteButton type="produkt" id={produkt.id} />
          {produkt.url && (
            <a
              href={produkt.url}
              target="_blank"
              rel="noopener noreferrer"
              className="p-1 text-slate-300 hover:text-slate-700"
              aria-label="Otevřít produktovou stránku"
            >
              <ExternalLink size={12} />
            </a>
          )}
        </div>
      </div>
      <dl className="text-[10px] space-y-1 mb-3">
        {produktovaLinieNazev && (
          <div className="flex gap-2">
            <dt className="text-slate-400 font-bold">Produktová linie:</dt>
            <dd className="text-slate-700 font-bold">{produktovaLinieNazev}</dd>
          </div>
        )}
        {produkt.zakaznicky_segment && (
          <div className="flex gap-2">
            <dt className="text-slate-400 font-bold">Segment:</dt>
            <dd className="text-slate-700 font-bold">{produkt.zakaznicky_segment}</dd>
          </div>
        )}
        {spolecnost && (
          <div className="flex gap-2">
            <dt className="text-slate-400 font-bold">Společnost:</dt>
            <dd className="text-slate-700 font-bold">{spolecnost.name}</dd>
          </div>
        )}
      </dl>
      {produkt.kratky_popis && (
        <p className="text-xs text-slate-500 font-medium leading-relaxed line-clamp-3">
          {produkt.kratky_popis}
        </p>
      )}
    </article>
  );
}
