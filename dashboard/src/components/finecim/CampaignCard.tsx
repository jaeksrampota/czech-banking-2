import { ExternalLink } from 'lucide-react';
import { formatDate, MEDIA_TYPE_LABELS } from '../../utils';
import type { Kampan, Competitor } from '../../types';
import CompanyLogo from './CompanyLogo';
import FavoriteButton from './FavoriteButton';

interface Props {
  kampan: Kampan;
  spolecnost?: Competitor;
}

export default function CampaignCard({ kampan, spolecnost }: Props) {
  return (
    <article className="bg-white border border-slate-200 rounded-lg shadow-sm hover:border-[#fee600] transition-colors overflow-hidden">
      {kampan.kreativa_url ? (
        <div className="aspect-video bg-slate-100 flex items-center justify-center">
          <img
            src={kampan.kreativa_url}
            alt={kampan.nazev}
            className="w-full h-full object-cover"
            onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
          />
        </div>
      ) : (
        <div className="aspect-video bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center">
          <span className="text-[9px] font-black uppercase tracking-widest text-slate-300">
            Bez náhledu
          </span>
        </div>
      )}
      <div className="p-5">
        <div className="flex items-start justify-between gap-2 mb-2">
          <h3 className="text-sm font-black text-slate-900 leading-tight flex-1">
            {kampan.nazev}
          </h3>
          <div className="flex items-center gap-0.5 shrink-0">
            <FavoriteButton type="kampan" id={kampan.id} />
            {kampan.kreativa_url && (
              <a
                href={kampan.kreativa_url}
                target="_blank"
                rel="noopener noreferrer"
                className="p-1 text-slate-300 hover:text-slate-700"
                aria-label="Otevřít kreativu"
              >
                <ExternalLink size={12} />
              </a>
            )}
          </div>
        </div>
        {spolecnost && (
          <div className="flex items-center gap-2 mb-2">
            <CompanyLogo
              competitorId={spolecnost.id}
              name={spolecnost.name}
              tier={spolecnost.tier}
              size={20}
            />
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
              {spolecnost.name}
            </span>
          </div>
        )}
        <dl className="text-[10px] space-y-1 mb-3">
          {kampan.zacatek && (
            <div className="flex gap-2">
              <dt className="text-slate-400 font-bold">začátek:</dt>
              <dd className="text-slate-700 font-bold">{formatDate(kampan.zacatek)}</dd>
            </div>
          )}
          {kampan.aktualizace && (
            <div className="flex gap-2">
              <dt className="text-slate-400 font-bold">aktualizace:</dt>
              <dd className="text-slate-700 font-bold">{formatDate(kampan.aktualizace)}</dd>
            </div>
          )}
        </dl>
        {kampan.popis && (
          <p className="text-xs text-slate-500 font-medium leading-relaxed line-clamp-3 mb-3">
            {kampan.popis}
          </p>
        )}
        {kampan.media_typy && kampan.media_typy.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {kampan.media_typy.map((m) => (
              <span
                key={m}
                className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest bg-[#fee600]/40 text-slate-900"
              >
                {MEDIA_TYPE_LABELS[m] || m}
              </span>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}
