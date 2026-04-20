import { X } from 'lucide-react';
import { cn } from '../../utils';
import type { Competitor, ProduktovaLinie } from '../../types';

export interface FilterState {
  od: string;
  do: string;
  zakaznicky_segment: string;
  spolecnost: string;
  produktova_linie: string;
}

export const EMPTY_FILTERS: FilterState = {
  od: '',
  do: '',
  zakaznicky_segment: '',
  spolecnost: '',
  produktova_linie: '',
};

interface Props {
  value: FilterState;
  onChange: (next: FilterState) => void;
  spolecnosti: Competitor[];
  produktoveLinie: ProduktovaLinie[];
  extraFilters?: React.ReactNode;
}

export default function FilterBar({
  value, onChange, spolecnosti, produktoveLinie, extraFilters,
}: Props) {
  const set = <K extends keyof FilterState>(k: K, v: FilterState[K]) =>
    onChange({ ...value, [k]: v });

  const hasFilters = Object.values(value).some((v) => v);

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm flex flex-wrap items-center gap-3">
      <DateInput placeholder="od" value={value.od} onChange={(v) => set('od', v)} />
      <span className="text-slate-300">…</span>
      <DateInput placeholder="do" value={value.do} onChange={(v) => set('do', v)} />

      <Select
        placeholder="segment"
        value={value.zakaznicky_segment}
        onChange={(v) => set('zakaznicky_segment', v)}
        options={[
          { value: 'Fyzické osoby', label: 'Fyzické osoby' },
          { value: 'FOP a firmy',   label: 'FOP a firmy' },
        ]}
      />

      <Select
        placeholder="společnost"
        value={value.spolecnost}
        onChange={(v) => set('spolecnost', v)}
        options={spolecnosti.map((c) => ({ value: c.id, label: c.name }))}
      />

      <Select
        placeholder="produktová linie"
        value={value.produktova_linie}
        onChange={(v) => set('produktova_linie', v)}
        options={produktoveLinie.map((l) => ({ value: l.id, label: l.nazev }))}
      />

      {extraFilters}

      {hasFilters && (
        <button
          type="button"
          onClick={() => onChange(EMPTY_FILTERS)}
          className="text-[9px] font-black uppercase tracking-widest text-slate-400 hover:text-red-500 transition-colors flex items-center gap-1 ml-auto"
        >
          <X size={10} /> Reset
        </button>
      )}
    </div>
  );
}

function DateInput({
  placeholder, value, onChange,
}: {
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <input
      type="date"
      placeholder={placeholder}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={placeholder}
      className={cn(
        'bg-slate-50 border border-slate-200 rounded py-2 px-3 text-[10px] font-bold uppercase tracking-wider',
        'focus:outline-none focus:border-[#fee600] transition-colors min-w-[130px]',
        value ? 'text-slate-900' : 'text-slate-400',
      )}
    />
  );
}

function Select({
  placeholder, value, onChange, options,
}: {
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={placeholder}
      className={cn(
        'bg-slate-50 border border-slate-200 rounded py-2 px-3 text-[10px] font-bold uppercase tracking-wider',
        'focus:outline-none focus:border-[#fee600] transition-colors appearance-none cursor-pointer min-w-[140px]',
        value ? 'text-slate-900' : 'text-slate-400',
      )}
    >
      <option value="">{placeholder}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}
