import { useState, useMemo } from 'react';
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, Tooltip,
  ResponsiveContainer, Cell, LabelList, CartesianGrid,
} from 'recharts';
import { ArrowLeft, Info } from 'lucide-react';
import { api } from '../api';
import type { Competitor } from '../types';
import PageHeader from '../components/PageHeader';
import ErrorBanner from '../components/ErrorBanner';
import { useFetch } from '../hooks/useFetch';
import { cn } from '../utils';

const TIER_COLORS: Record<number, string> = {
  1: '#ef4444',
  2: '#3b82f6',
  3: '#6366f1',
};

const TIER_INFO: Record<number, { label: string; desc: string; badge: string }> = {
  1: { label: 'Tier 1 — Universal Banks', desc: 'Dominant incumbents, foreign-owned', badge: 'border-red-200 text-red-600 bg-red-50' },
  2: { label: 'Tier 2 — Challengers', desc: 'Established mid-market & digital-first', badge: 'border-blue-200 text-blue-600 bg-blue-50' },
  3: { label: 'Tier 3 — Fintechs & Neobanks', desc: 'Disruptors & new entrants', badge: 'border-slate-200 text-slate-600 bg-slate-50' },
};

type MetricKey = 'signal_count' | 'avg_severity' | 'tier';

const METRIC_LABELS: Record<MetricKey, string> = {
  signal_count: 'Signal Count',
  avg_severity: 'Avg Severity',
  tier: 'Market Tier',
};

const METRIC_DOMAINS: Record<MetricKey, [number, number]> = {
  signal_count: [0, 100],
  avg_severity: [0, 5],
  tier: [0, 4],
};

// Stable per-competitor colors
const COMP_COLORS = [
  '#3b82f6', '#10b981', '#ef4444', '#06b6d4', '#6366f1',
  '#eab308', '#f43f5e', '#a855f7', '#22c55e', '#f97316', '#00a19a',
];

export default function Competitors() {
  const { data, loading, error, lastUpdated, refresh } = useFetch(
    () => api.getCompetitors(),
  );
  const competitors = data ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [xAxis, setXAxis] = useState<MetricKey>('signal_count');
  const [yAxis, setYAxis] = useState<MetricKey>('avg_severity');
  const [selectedTiers, setSelectedTiers] = useState<number[]>([1, 2, 3]);

  const enriched = useMemo(
    () =>
      competitors
        .filter((c) => selectedTiers.includes(c.tier))
        .map((c, i) => ({ ...c, color: COMP_COLORS[i % COMP_COLORS.length] })),
    [competitors, selectedTiers]
  );

  const selected = useMemo(() => enriched.find((c) => c.id === selectedId), [enriched, selectedId]);

  // Auto-scale domains
  const xDomain = useMemo<[number, number]>(() => {
    if (enriched.length === 0) return METRIC_DOMAINS[xAxis];
    const vals = enriched.map((c) => c[xAxis] as number);
    return [0, Math.ceil(Math.max(...vals) * 1.2) || METRIC_DOMAINS[xAxis][1]];
  }, [enriched, xAxis]);

  const yDomain = useMemo<[number, number]>(() => {
    if (enriched.length === 0) return METRIC_DOMAINS[yAxis];
    const vals = enriched.map((c) => c[yAxis] as number);
    return [0, Math.ceil(Math.max(...vals) * 1.2) || METRIC_DOMAINS[yAxis][1]];
  }, [enriched, yAxis]);

  const toggleTier = (t: number) =>
    setSelectedTiers((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));

  const header = (
    <PageHeader
      title="Competitors"
      subtitle="Tier-level positioning and per-competitor drill-down"
      loading={loading}
      lastUpdated={lastUpdated}
      onRefresh={refresh}
    />
  );

  if (error) {
    return (
      <div className="max-w-[1400px] mx-auto space-y-4">
        {header}
        <ErrorBanner message={error} onRetry={refresh} />
      </div>
    );
  }

  if (loading && !data) {
    return (
      <div className="max-w-[1400px] mx-auto space-y-4 animate-pulse">
        {header}
        <div className="bg-white border border-slate-200 rounded-lg h-[600px] shadow-sm" />
      </div>
    );
  }

  return (
    <div className="max-w-[1400px] mx-auto space-y-4">
      {header}
      <div className="grid grid-cols-12 gap-6">
      {/* Sidebar controls */}
      <div className="col-span-12 lg:col-span-3 space-y-6">
        {/* Tier slicer */}
        <div className="bg-white border border-slate-200 rounded-lg p-6 shadow-sm space-y-4">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">Market Tier</label>
          <div className="flex flex-wrap gap-2">
            {[1, 2, 3].map((t) => (
              <button
                key={t}
                onClick={() => toggleTier(t)}
                className={cn(
                  'px-3 py-1.5 rounded text-[10px] font-black border transition-all',
                  selectedTiers.includes(t)
                    ? 'bg-slate-800 text-white border-slate-800'
                    : 'bg-white text-slate-400 border-slate-200 hover:border-slate-400'
                )}
              >
                T{t}
              </button>
            ))}
          </div>
        </div>

        {/* Axis selectors */}
        <AxisSelector label="X-Axis Metric" value={xAxis} onChange={setXAxis} activeColor="bg-[#fee600] border-[#fee600] text-black" />
        <AxisSelector label="Y-Axis Metric" value={yAxis} onChange={setYAxis} activeColor="bg-slate-800 border-slate-800 text-white" />

        {/* Tier legend */}
        <div className="space-y-3">
          {([1, 2, 3] as const).map((t) => {
            const info = TIER_INFO[t];
            const count = enriched.filter((c) => c.tier === t).length;
            return (
              <div key={t} className="bg-white border border-slate-200 rounded-lg p-4 flex items-center justify-between shadow-sm hover:border-[#fee600] transition-all">
                <div className="flex items-center gap-3">
                  <div className={cn('w-8 h-8 rounded flex items-center justify-center font-black text-[10px] border', info.badge)}>
                    T{t}
                  </div>
                  <div>
                    <div className="text-[10px] font-black text-slate-900 uppercase tracking-tight">{info.label}</div>
                    <div className="text-[9px] font-bold text-slate-400">{info.desc}</div>
                  </div>
                </div>
                <div className="text-[10px] font-black text-slate-900">{count}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Chart + detail */}
      <div className="col-span-12 lg:col-span-9 space-y-6">
        {/* Scatter chart */}
        <div className="bg-white border border-slate-200 rounded-lg p-8 shadow-sm">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-400">Competitive Landscape</h2>
            <div className="flex gap-4">
              {[1, 2, 3].map((t) => (
                <div key={t} className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full" style={{ backgroundColor: TIER_COLORS[t] }} />
                  <span className="text-[9px] font-bold uppercase text-slate-400">T{t}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="h-[480px]">
            {enriched.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 20, right: 20, bottom: 60, left: 60 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis
                    type="number"
                    dataKey={xAxis}
                    domain={xDomain}
                    tick={{ fontSize: 9, fontWeight: 700, fill: '#94a3b8' }}
                    axisLine={{ stroke: '#e2e8f0' }}
                    tickLine={{ stroke: '#e2e8f0' }}
                    label={{ value: METRIC_LABELS[xAxis], position: 'bottom', offset: 40, fontSize: 9, fontWeight: 900, fill: '#64748b' }}
                  />
                  <YAxis
                    type="number"
                    dataKey={yAxis}
                    domain={yDomain}
                    tick={{ fontSize: 9, fontWeight: 700, fill: '#94a3b8' }}
                    axisLine={{ stroke: '#e2e8f0' }}
                    tickLine={{ stroke: '#e2e8f0' }}
                    label={{ value: METRIC_LABELS[yAxis], angle: -90, position: 'left', offset: 40, fontSize: 9, fontWeight: 900, fill: '#64748b' }}
                  />
                  <ZAxis range={[400, 400]} />
                  <Tooltip
                    cursor={{ strokeDasharray: '3 3', stroke: '#e2e8f0' }}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const d = payload[0].payload as Competitor & { color: string };
                      return (
                        <div className="bg-white border border-slate-200 p-4 rounded shadow-2xl">
                          <div className="text-slate-900 font-black text-xs uppercase tracking-tight mb-2 border-b border-slate-100 pb-2">{d.name}</div>
                          <div className="space-y-1 text-[10px] font-bold">
                            <div className="flex justify-between gap-8"><span className="text-slate-400">Signals</span><span className="text-slate-900">{d.signal_count}</span></div>
                            <div className="flex justify-between gap-8"><span className="text-slate-400">Avg Severity</span><span className="text-slate-900">{d.avg_severity}</span></div>
                            <div className="flex justify-between gap-8"><span className="text-slate-400">Tier</span><span className="text-slate-900">{d.tier}</span></div>
                          </div>
                        </div>
                      );
                    }}
                  />
                  <Scatter data={enriched} onClick={(d: any) => setSelectedId(d.id)} className="cursor-pointer">
                    {enriched.map((entry, i) => (
                      <Cell
                        key={i}
                        fill={TIER_COLORS[entry.tier] || '#94a3b8'}
                        fillOpacity={0.8}
                        stroke={entry.id === selectedId ? '#000' : '#fff'}
                        strokeWidth={entry.id === selectedId ? 3 : 2}
                      />
                    ))}
                    <LabelList
                      dataKey="name"
                      content={(props: any) => {
                        const { x, y, value } = props;
                        if (!x || !y) return null;
                        return (
                          <text x={x} y={y + 16} textAnchor="middle" className="text-[9px] font-black text-slate-900 pointer-events-none uppercase tracking-tighter">
                            {(value as string).split(' ')[0]}
                          </text>
                        );
                      }}
                    />
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center h-full text-[10px] font-black uppercase tracking-widest text-slate-300">
                No competitors match selected tiers
              </div>
            )}
          </div>
        </div>

        {/* Selected competitor detail */}
        <div className="bg-white border border-slate-200 rounded-lg p-8 shadow-sm min-h-[200px] flex items-center justify-center">
          {selected ? (
            <div className="w-full">
              <button onClick={() => setSelectedId(null)} className="text-slate-400 hover:text-slate-900 transition-colors flex items-center gap-2 text-[10px] font-black uppercase tracking-widest mb-6">
                <ArrowLeft size={14} /> Back
              </button>
              <div className="flex items-start gap-8">
                <div className="w-16 h-16 rounded-full flex items-center justify-center border-4 shadow-inner shrink-0" style={{ borderColor: TIER_COLORS[selected.tier], backgroundColor: `${TIER_COLORS[selected.tier]}10` }}>
                  <span className="text-slate-900 font-black text-xl">{selected.name[0]}</span>
                </div>
                <div className="flex-1">
                  <h3 className="text-2xl font-black text-slate-900 tracking-tight">{selected.name}</h3>
                  <p className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.2em] mb-4">{TIER_INFO[selected.tier]?.label}</p>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                    <StatBox label="Signals" value={selected.signal_count} />
                    <StatBox label="Avg Severity" value={selected.avg_severity?.toFixed(1) || '—'} />
                    <StatBox label="Tier" value={`T${selected.tier}`} />
                    <StatBox label="ICO" value={selected.ico || '—'} />
                    {selected.parent_group && <StatBox label="Parent" value={selected.parent_group} />}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="text-slate-300 flex flex-col items-center gap-4">
              <div className="w-20 h-20 rounded-full border-4 border-dashed border-slate-100 flex items-center justify-center">
                <Info size={32} className="text-slate-100" />
              </div>
              <p className="text-[10px] font-black uppercase tracking-[0.2em]">Select a competitor for details</p>
            </div>
          )}
        </div>

        {/* Competitor table */}
        <div className="bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-100 bg-slate-50/50">
            <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-900">All Competitors</h3>
          </div>
          <table className="w-full text-[10px] text-left border-collapse">
            <thead>
              <tr className="text-slate-400 border-b border-slate-100 bg-slate-50/30">
                <th className="px-6 py-3 font-black uppercase tracking-widest">Name</th>
                <th className="px-6 py-3 font-black uppercase tracking-widest">Parent</th>
                <th className="px-6 py-3 font-black uppercase tracking-widest text-center">Tier</th>
                <th className="px-6 py-3 font-black uppercase tracking-widest text-center">ICO</th>
                <th className="px-6 py-3 font-black uppercase tracking-widest text-right">Signals</th>
                <th className="px-6 py-3 font-black uppercase tracking-widest text-right">Avg Sev</th>
              </tr>
            </thead>
            <tbody>
              {enriched.map((c) => (
                <tr
                  key={c.id}
                  className={cn('border-b border-slate-50 hover:bg-yellow-50/30 transition-colors cursor-pointer', selectedId === c.id && 'bg-yellow-50/50')}
                  onClick={() => setSelectedId(c.id)}
                >
                  <td className="px-6 py-3 font-black text-slate-900">{c.name}</td>
                  <td className="px-6 py-3 text-slate-500">{c.parent_group || '—'}</td>
                  <td className="px-6 py-3 text-center">
                    <span className={cn('px-2 py-0.5 rounded text-[9px] font-black border uppercase', TIER_INFO[c.tier]?.badge)}>T{c.tier}</span>
                  </td>
                  <td className="px-6 py-3 text-center font-mono text-slate-500">{c.ico || '—'}</td>
                  <td className="px-6 py-3 text-right font-black text-slate-900">{c.signal_count}</td>
                  <td className="px-6 py-3 text-right font-mono text-slate-900">{c.avg_severity?.toFixed(1) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      </div>
    </div>
  );
}

function AxisSelector({
  label,
  value,
  onChange,
  activeColor,
}: {
  label: string;
  value: MetricKey;
  onChange: (v: MetricKey) => void;
  activeColor: string;
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-6 shadow-sm space-y-3">
      <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">{label}</label>
      <div className="grid grid-cols-1 gap-1">
        {(Object.entries(METRIC_LABELS) as [MetricKey, string][]).map(([key, lbl]) => (
          <button
            key={key}
            onClick={() => onChange(key)}
            className={cn(
              'w-full text-left px-3 py-2 rounded text-[10px] font-bold uppercase tracking-wider transition-all border',
              value === key
                ? `${activeColor} shadow-sm`
                : 'bg-white border-transparent text-slate-500 hover:bg-slate-50 hover:text-slate-900'
            )}
          >
            {lbl}
          </button>
        ))}
      </div>
    </div>
  );
}

function StatBox({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-slate-50 rounded p-3">
      <div className="text-[8px] font-black uppercase tracking-widest text-slate-400 mb-1">{label}</div>
      <div className="text-sm font-black text-slate-900">{value}</div>
    </div>
  );
}
