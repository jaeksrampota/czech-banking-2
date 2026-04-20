import { cn } from '../../utils';
import type { MonitorTab } from '../../types';

interface Props {
  active: MonitorTab;
  onChange: (tab: MonitorTab) => void;
  maProdukty: boolean;
}

const ALL_TABS: { id: MonitorTab; label: string; needsProducts: boolean }[] = [
  { id: 'novinky',     label: 'Novinky',           needsProducts: false },
  { id: 'spolecnosti', label: 'Společnosti',       needsProducts: false },
  { id: 'produkty',    label: 'Produkty',          needsProducts: true  },
  { id: 'srovnani',    label: 'Srovnání',          needsProducts: true  },
  { id: 'kampane',     label: 'Kampaně',           needsProducts: false },
  { id: 'mystery',     label: 'Mystery Shopping',  needsProducts: false },
  { id: 'executive',   label: 'Executive Summary', needsProducts: false },
];

export default function SubNav({ active, onChange, maProdukty }: Props) {
  const tabs = ALL_TABS.filter((t) => maProdukty || !t.needsProducts);
  return (
    <div className="bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden">
      <div className="flex flex-wrap">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => onChange(tab.id)}
            className={cn(
              'px-5 py-3 text-[10px] font-black uppercase tracking-widest transition-colors border-b-2',
              active === tab.id
                ? 'bg-yellow-50 text-slate-900 border-[#fee600]'
                : 'border-transparent text-slate-400 hover:text-slate-900 hover:bg-slate-50',
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>
    </div>
  );
}
