import { Wallet, Home, TrendingUp, Globe } from 'lucide-react';
import { cn } from '../../utils';
import type { Segment } from '../../types';

const SEGMENT_ICONS: Record<string, typeof Wallet> = {
  ucty: Wallet,
  hypoteky: Home,
  investice: TrendingUp,
};

interface Props {
  segmenty: Segment[];
  selectedSlug: string | null;
  onSelect: (slug: string | null) => void;
}

export default function SegmentRail({ segmenty, selectedSlug, onSelect }: Props) {
  return (
    <nav
      aria-label="Segmenty"
      className="bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden"
    >
      <button
        type="button"
        onClick={() => onSelect(null)}
        className={cn(
          'w-full flex items-center gap-3 px-4 py-3 text-[10px] font-black uppercase tracking-widest transition-colors border-l-2',
          selectedSlug === null
            ? 'bg-yellow-50 text-slate-900 border-[#fee600]'
            : 'border-transparent text-slate-400 hover:text-slate-900 hover:bg-slate-50',
        )}
      >
        <Globe size={14} />
        <span>Hlavní stránka</span>
      </button>
      <div className="border-t border-slate-100" />
      {segmenty.map((s) => {
        const Icon = SEGMENT_ICONS[s.slug] || Wallet;
        const active = selectedSlug === s.slug;
        return (
          <button
            key={s.id}
            type="button"
            onClick={() => onSelect(s.slug)}
            className={cn(
              'w-full flex items-center gap-3 px-4 py-3 text-[10px] font-black uppercase tracking-widest transition-colors border-l-2',
              active
                ? 'bg-yellow-50 text-slate-900 border-[#fee600]'
                : 'border-transparent text-slate-400 hover:text-slate-900 hover:bg-slate-50',
            )}
          >
            <Icon size={14} className={active ? 'text-[#e6cf00]' : ''} />
            <span>{s.nazev}</span>
          </button>
        );
      })}
    </nav>
  );
}
