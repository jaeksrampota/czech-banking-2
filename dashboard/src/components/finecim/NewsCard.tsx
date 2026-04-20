import { ExternalLink } from 'lucide-react';
import { timeAgo, cn } from '../../utils';
import type { Clanek, Signal, Competitor } from '../../types';
import CompanyLogo from './CompanyLogo';
import FavoriteButton from './FavoriteButton';
import TagChip from './TagChip';

interface Props {
  item: Clanek | Signal;
  spolecnost?: Competitor;
  onOpenArticle?: (id: string) => void;
  onSelectTag?: (tag: string) => void;
}

function isClanek(x: Clanek | Signal): x is Clanek {
  return 'nazev' in x;
}

export default function NewsCard({
  item, spolecnost, onOpenArticle, onSelectTag,
}: Props) {
  const title = isClanek(item) ? item.nazev : item.title;
  const perex = isClanek(item) ? (item.perex || '') : item.content;
  const date = isClanek(item) ? item.datum : item.detected_at;
  const url = item.url;
  const typ = isClanek(item) ? item.typ_zpravy : item.signal_type;
  const tags = isClanek(item) ? item.tagy : item.tags;
  const isArticle = isClanek(item);
  const id = item.id;

  const clickable = isArticle && onOpenArticle;

  const body = (
    <>
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          {spolecnost && (
            <CompanyLogo
              competitorId={spolecnost.id}
              name={spolecnost.name}
              tier={spolecnost.tier}
              size={28}
            />
          )}
          <div className="flex flex-col min-w-0">
            <span className="text-[9px] font-bold text-slate-300 uppercase tracking-wider">
              {timeAgo(date)}
            </span>
            {spolecnost && (
              <span className="text-[9px] font-bold text-slate-700 uppercase tracking-wider truncate">
                {spolecnost.name}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          {isArticle && item.stav && (
            <span className={cn(
              'px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest mr-1',
              item.stav === 'updated'
                ? 'bg-amber-100 text-amber-700'
                : 'bg-emerald-100 text-emerald-700',
            )}>
              {item.stav === 'updated' ? 'aktualizováno' : 'nové'}
            </span>
          )}
          {isArticle && <FavoriteButton type="clanek" id={id} />}
          {url && (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="p-1 text-slate-300 hover:text-slate-700"
              aria-label="Otevřít zdroj"
            >
              <ExternalLink size={12} />
            </a>
          )}
        </div>
      </div>
      <h3 className="text-sm font-black text-slate-900 leading-snug mb-2 text-left">
        {title}
      </h3>
      {perex && (
        <p className="text-xs text-slate-500 font-medium leading-relaxed line-clamp-3 text-left">
          {perex}
        </p>
      )}
      {((tags && tags.length > 0) || typ) && (
        <div className="mt-3 pt-3 border-t border-slate-100 flex flex-wrap items-center gap-1.5">
          {typ && (
            <span className="px-1.5 py-0.5 bg-slate-100 rounded text-[9px] font-bold text-slate-500 uppercase tracking-wider">
              {typ}
            </span>
          )}
          {tags && tags.slice(0, 5).map((t) => (
            <TagChip key={t} tag={t} onClick={onSelectTag} />
          ))}
        </div>
      )}
    </>
  );

  if (clickable) {
    return (
      <article className="bg-white border border-slate-200 rounded-lg shadow-sm hover:border-[#fee600] transition-colors overflow-hidden">
        <button
          type="button"
          onClick={() => onOpenArticle!(id)}
          className="w-full p-5 text-left block"
        >
          {body}
        </button>
      </article>
    );
  }

  return (
    <article className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm hover:border-[#fee600] transition-colors">
      {body}
    </article>
  );
}
