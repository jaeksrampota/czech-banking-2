import { FileText, Download } from 'lucide-react';
import { formatDate } from '../../utils';
import type { MysteryShop, Competitor } from '../../types';
import CompanyLogo from './CompanyLogo';
import FavoriteButton from './FavoriteButton';

interface Props {
  shop: MysteryShop;
  spolecnost?: Competitor;
}

export default function MysteryCard({ shop, spolecnost }: Props) {
  return (
    <article className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm hover:border-[#fee600] transition-colors flex flex-col">
      <div className="flex items-start justify-between gap-2 mb-2">
        <h3 className="text-sm font-black text-slate-900 leading-tight flex-1">
          {shop.nazev}
        </h3>
        <FavoriteButton type="mystery" id={shop.id} />
      </div>
      <div className="flex items-center gap-2 text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-3">
        <span>{formatDate(shop.datum)}</span>
        {spolecnost && (
          <>
            <CompanyLogo
              competitorId={spolecnost.id}
              name={spolecnost.name}
              tier={spolecnost.tier}
              size={18}
            />
            <span className="text-slate-700">{spolecnost.name}</span>
          </>
        )}
      </div>
      {shop.popis && (
        <p className="text-xs text-slate-600 font-medium leading-relaxed mb-4 flex-1">
          {shop.popis}
        </p>
      )}
      {shop.pdf_url && (
        <a
          href={shop.pdf_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-slate-700 hover:text-slate-900 border border-slate-200 rounded-md px-3 py-2 hover:bg-slate-50 self-start"
        >
          <FileText size={12} /> <span>PDF zpráva</span> <Download size={11} />
        </a>
      )}
    </article>
  );
}
