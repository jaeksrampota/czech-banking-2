import { useState, useMemo } from 'react';
import { cn } from '../../utils';
import type { ProduktovaLinie, Produkt, Competitor } from '../../types';

interface Props {
  produktoveLinie: ProduktovaLinie[];
  produkty: Produkt[];
  spolecnosti: Competitor[];
}

type Step = 1 | 2 | 3 | 4;

const STEPS: { idx: Step; label: string }[] = [
  { idx: 1, label: 'Výběr produktové linie' },
  { idx: 2, label: 'Výběr konkrétních produktů' },
  { idx: 3, label: 'Výběr parametrů pro porovnání' },
  { idx: 4, label: 'Výstup — tabulka' },
];

export default function ComparisonWizard({
  produktoveLinie, produkty, spolecnosti,
}: Props) {
  const [step, setStep] = useState<Step>(1);
  const [linieId, setLinieId] = useState<string>('');
  const [zakaznickyS, setZakaznickyS] = useState<string>('');
  const [spolecnostId, setSpolecnostId] = useState<string>('');
  const [vybraneProdukty, setVybraneProdukty] = useState<Set<string>>(new Set());
  const [atributy, setAtributy] = useState<Set<string>>(new Set());

  const filteredProducts = useMemo(() => {
    return produkty.filter((p) => {
      if (linieId && p.produktova_linie_id !== linieId) return false;
      if (zakaznickyS && p.zakaznicky_segment !== zakaznickyS) return false;
      if (spolecnostId && p.competitor_id !== spolecnostId) return false;
      return true;
    });
  }, [produkty, linieId, zakaznickyS, spolecnostId]);

  const productsByCompany = useMemo(() => {
    const map = new Map<string, Produkt[]>();
    for (const p of filteredProducts) {
      const arr = map.get(p.competitor_id) ?? [];
      arr.push(p);
      map.set(p.competitor_id, arr);
    }
    return [...map.entries()];
  }, [filteredProducts]);

  const allAttributes = useMemo(() => {
    const set = new Set<string>();
    for (const p of produkty.filter((p) => vybraneProdukty.has(p.id))) {
      Object.keys(p.atributy || {}).forEach((k) => set.add(k));
    }
    return [...set];
  }, [produkty, vybraneProdukty]);

  const vybranePole = produkty.filter((p) => vybraneProdukty.has(p.id));

  const toggleProduct = (id: string) => {
    const next = new Set(vybraneProdukty);
    if (next.has(id)) next.delete(id); else next.add(id);
    setVybraneProdukty(next);
  };

  const toggleAttr = (key: string) => {
    const next = new Set(atributy);
    if (next.has(key)) next.delete(key); else next.add(key);
    setAtributy(next);
  };

  return (
    <div className="bg-white border border-slate-200 rounded-lg shadow-sm">
      {/* Stepper */}
      <ol className="flex border-b border-slate-100">
        {STEPS.map(({ idx, label }) => {
          const done = step > idx;
          const active = step === idx;
          return (
            <li key={idx} className={cn(
              'flex-1 px-5 py-4 border-b-2',
              active ? 'border-[#fee600]' : done ? 'border-emerald-300' : 'border-transparent',
            )}>
              <div className={cn(
                'flex items-center gap-2 text-[10px] font-black uppercase tracking-widest',
                active ? 'text-slate-900' : done ? 'text-emerald-700' : 'text-slate-300',
              )}>
                <span>{idx}</span>
                <span>{label}</span>
              </div>
            </li>
          );
        })}
      </ol>

      <div className="p-6">
        {step === 1 && (
          <div className="space-y-4">
            <h3 className="text-[10px] font-black uppercase tracking-widest text-slate-400">
              Filtr produktů
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <LabeledSelect
                label="produktová linie"
                value={linieId}
                onChange={setLinieId}
                options={produktoveLinie.map((l) => ({ value: l.id, label: l.nazev }))}
              />
              <LabeledSelect
                label="zákaznický segment"
                value={zakaznickyS}
                onChange={setZakaznickyS}
                options={[
                  { value: 'Fyzické osoby', label: 'Fyzické osoby' },
                  { value: 'FOP a firmy', label: 'FOP a firmy' },
                ]}
              />
              <LabeledSelect
                label="společnost"
                value={spolecnostId}
                onChange={setSpolecnostId}
                options={spolecnosti.map((c) => ({ value: c.id, label: c.name }))}
              />
            </div>
            <div className="pt-4 border-t border-slate-100 flex justify-end">
              <PrimaryButton disabled={!linieId} onClick={() => setStep(2)}>
                Pokračovat
              </PrimaryButton>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <h3 className="text-[10px] font-black uppercase tracking-widest text-slate-400">
              Vyberte parametry produktů ke srovnání
            </h3>
            {productsByCompany.length === 0 ? (
              <p className="text-xs text-slate-400 font-medium">
                Pro zvolené filtry nejsou k dispozici žádné produkty.
              </p>
            ) : (
              <div className="space-y-4">
                {productsByCompany.map(([cid, prods]) => {
                  const spol = spolecnosti.find((s) => s.id === cid);
                  return (
                    <div key={cid}>
                      <div className="text-[11px] font-black uppercase tracking-wider text-slate-900 mb-2">
                        {spol?.name || cid}
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 pl-4">
                        {prods.map((p) => (
                          <label key={p.id} className="flex items-start gap-2 text-[11px] cursor-pointer">
                            <input
                              type="checkbox"
                              checked={vybraneProdukty.has(p.id)}
                              onChange={() => toggleProduct(p.id)}
                              className="mt-0.5"
                            />
                            <span className="text-slate-700 font-medium">{p.nazev}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            <div className="pt-4 border-t border-slate-100 flex justify-between">
              <SecondaryButton onClick={() => setStep(1)}>Zpět</SecondaryButton>
              <PrimaryButton disabled={vybraneProdukty.size === 0} onClick={() => setStep(3)}>
                Pokračovat
              </PrimaryButton>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <h3 className="text-[10px] font-black uppercase tracking-widest text-slate-400">
              Zvolte, které atributy chcete v tabulce
            </h3>
            {allAttributes.length === 0 ? (
              <p className="text-xs text-slate-400 font-medium">
                Vybrané produkty nemají vyplněné atributy. Po doplnění dat se zde
                objeví seznam parametrů ke srovnání.
              </p>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                {allAttributes.map((k) => (
                  <label key={k} className="flex items-center gap-2 text-[11px] cursor-pointer">
                    <input
                      type="checkbox"
                      checked={atributy.has(k)}
                      onChange={() => toggleAttr(k)}
                    />
                    <span className="text-slate-700 font-medium">{k}</span>
                  </label>
                ))}
              </div>
            )}
            <div className="pt-4 border-t border-slate-100 flex justify-between">
              <SecondaryButton onClick={() => setStep(2)}>Zpět</SecondaryButton>
              <PrimaryButton onClick={() => setStep(4)}>Zobrazit tabulku</PrimaryButton>
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-4">
            <h3 className="text-[10px] font-black uppercase tracking-widest text-slate-400">
              Výstup
            </h3>
            {vybranePole.length === 0 ? (
              <p className="text-xs text-slate-400 font-medium">Nic k zobrazení.</p>
            ) : (
              <div className="overflow-x-auto border border-slate-200 rounded">
                <table className="w-full text-[11px] text-left">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="px-4 py-2 font-black uppercase tracking-widest text-slate-500">Atribut</th>
                      {vybranePole.map((p) => (
                        <th key={p.id} className="px-4 py-2 font-black text-slate-800">
                          {p.nazev}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-t border-slate-100">
                      <td className="px-4 py-2 font-bold text-slate-500">Společnost</td>
                      {vybranePole.map((p) => (
                        <td key={p.id} className="px-4 py-2 text-slate-700">
                          {spolecnosti.find((s) => s.id === p.competitor_id)?.name || p.competitor_id}
                        </td>
                      ))}
                    </tr>
                    {[...atributy].map((key) => (
                      <tr key={key} className="border-t border-slate-100">
                        <td className="px-4 py-2 font-bold text-slate-500">{key}</td>
                        {vybranePole.map((p) => (
                          <td key={p.id} className="px-4 py-2 text-slate-700">
                            {String((p.atributy as any)?.[key] ?? '—')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="pt-4 border-t border-slate-100 flex justify-between">
              <SecondaryButton onClick={() => setStep(3)}>Zpět</SecondaryButton>
              <SecondaryButton onClick={() => { setStep(1); setVybraneProdukty(new Set()); setAtributy(new Set()); }}>
                Nové srovnání
              </SecondaryButton>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function LabeledSelect({
  label, value, onChange, options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="block">
      <span className="text-[9px] font-black uppercase tracking-widest text-slate-400">
        {label}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          'w-full mt-1 bg-slate-50 border border-slate-200 rounded py-2 px-3 text-[11px] font-bold',
          'focus:outline-none focus:border-[#fee600] appearance-none cursor-pointer',
          value ? 'text-slate-900' : 'text-slate-400',
        )}
      >
        <option value="">— vyberte —</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}

function PrimaryButton({ children, onClick, disabled }: { children: React.ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'px-5 py-2 rounded text-[10px] font-black uppercase tracking-widest transition-colors',
        disabled
          ? 'bg-slate-100 text-slate-300 cursor-not-allowed'
          : 'bg-[#fee600] text-slate-900 hover:bg-[#f2dc00]',
      )}
    >
      {children}
    </button>
  );
}

function SecondaryButton({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="px-5 py-2 rounded text-[10px] font-black uppercase tracking-widest text-slate-700 border border-slate-200 hover:bg-slate-50 transition-colors"
    >
      {children}
    </button>
  );
}
