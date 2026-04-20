import { cn, TIER_LABELS } from '../../utils';
import type { Competitor } from '../../types';
import CompanyLogo from './CompanyLogo';
import FavoriteButton from './FavoriteButton';

interface Props {
  spolecnost: Competitor;
  onClick: (id: string) => void;
}

export default function CompanyTile({ spolecnost, onClick }: Props) {
  const tier = TIER_LABELS[spolecnost.tier];
  return (
    <div className="bg-white border border-slate-200 rounded-lg shadow-sm hover:border-[#fee600] hover:shadow-md transition-all relative">
      <div className="absolute top-2 right-2 z-10">
        <FavoriteButton type="spolecnost" id={spolecnost.id} />
      </div>
      <button
        type="button"
        onClick={() => onClick(spolecnost.id)}
        className="w-full p-5 flex flex-col items-center gap-3 text-center"
      >
        <CompanyLogo
          competitorId={spolecnost.id}
          name={spolecnost.name}
          tier={spolecnost.tier}
          size={56}
        />
        <div className="flex-1 min-h-0">
          <div className="text-[11px] font-black text-slate-900 uppercase tracking-tight leading-tight">
            {spolecnost.name}
          </div>
          {spolecnost.parent_group && (
            <div className="text-[9px] font-bold text-slate-400 uppercase tracking-wider mt-1">
              {spolecnost.parent_group}
            </div>
          )}
        </div>
        <span
          className={cn(
            'px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-widest border',
            tier?.badge,
          )}
        >
          {tier?.kratky || `T${spolecnost.tier}`}
        </span>
      </button>
    </div>
  );
}
