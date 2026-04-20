import { useState, useMemo } from 'react';
import { ChevronDown, ChevronRight, FileText } from 'lucide-react';
import { CZECH_MONTHS } from '../../utils';
import type { ExecSummary } from '../../types';
import EmptyState from './EmptyState';

interface Props {
  items: ExecSummary[];
}

export default function ExecSummaryArchive({ items }: Props) {
  const byYear = useMemo(() => {
    const map = new Map<number, ExecSummary[]>();
    for (const it of items) {
      const arr = map.get(it.rok) ?? [];
      arr.push(it);
      map.set(it.rok, arr);
    }
    return [...map.entries()].sort((a, b) => b[0] - a[0]);
  }, [items]);

  const [expandedYear, setExpandedYear] = useState<number | null>(
    byYear.length > 0 ? byYear[0][0] : null,
  );

  if (items.length === 0) {
    return (
      <EmptyState
        title="Zatím žádné executive summary"
        description="Měsíční přehledy po segmentech se zde budou zobrazovat, jakmile je doplníte."
      />
    );
  }

  return (
    <div className="space-y-3">
      {byYear.map(([year, months]) => {
        const open = expandedYear === year;
        return (
          <div key={year} className="bg-white border border-slate-200 rounded-lg shadow-sm">
            <button
              type="button"
              onClick={() => setExpandedYear(open ? null : year)}
              className="w-full px-6 py-4 flex items-center gap-3 text-left"
            >
              {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              <span className="text-lg font-black text-slate-900 tracking-tight">{year}</span>
              <span className="ml-auto text-[9px] font-bold uppercase tracking-widest text-slate-400">
                {months.length} přehledů
              </span>
            </button>
            {open && (
              <div className="border-t border-slate-100 p-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                {months
                  .sort((a, b) => a.mesic - b.mesic)
                  .map((m) => (
                    <a
                      key={m.id}
                      href={m.pdf_url ?? '#'}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-4 py-3 border border-slate-200 rounded hover:border-[#fee600] hover:bg-slate-50 transition-colors flex items-center justify-between"
                    >
                      <span className="text-[11px] font-bold text-slate-700 capitalize">
                        {CZECH_MONTHS[m.mesic - 1]}
                      </span>
                      {m.pdf_url && <FileText size={11} className="text-slate-300" />}
                    </a>
                  ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
