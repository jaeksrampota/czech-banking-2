import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  PieChart, Pie, Cell, AreaChart, Area,
} from 'recharts';
import { Radio, Building2, Activity, TrendingUp, ExternalLink } from 'lucide-react';
import { api } from '../api';
import SeverityBadge from '../components/SeverityBadge';
import PageHeader from '../components/PageHeader';
import ErrorBanner from '../components/ErrorBanner';
import { useFetch } from '../hooks/useFetch';
import { SOURCE_LABELS, timeAgo } from '../utils';

const PIE_COLORS = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#b91c1c'];
const AUTO_REFRESH_MS = 60_000;

export default function Overview() {
  const { data, loading, error, lastUpdated, refresh } = useFetch(
    () => api.getSummary(),
    { refreshInterval: AUTO_REFRESH_MS },
  );

  const header = (
    <PageHeader
      title="Overview"
      subtitle="Signal volume and recent intelligence"
      loading={loading}
      lastUpdated={lastUpdated}
      onRefresh={refresh}
    />
  );

  if (error) {
    return (
      <div className="space-y-6 max-w-[1400px] mx-auto">
        {header}
        <ErrorBanner message={error} onRetry={refresh} />
      </div>
    );
  }
  if (loading && !data) {
    return (
      <div className="space-y-6 max-w-[1400px] mx-auto">
        {header}
        <LoadingSkeleton />
      </div>
    );
  }
  if (!data) {
    return (
      <div className="space-y-6 max-w-[1400px] mx-auto">
        {header}
        <EmptyState text="No data available. Run collectors first." />
      </div>
    );
  }

  const stats = data.total_signals;

  return (
    <div className="space-y-6 max-w-[1400px] mx-auto">
      {header}
      {/* KPI Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          label="Total Signals"
          value={stats.total_signals}
          icon={<Radio size={16} />}
          accent="text-[#e6cf00]"
        />
        <KPICard
          label="Avg Severity"
          value={stats.avg_severity?.toFixed(1) || '—'}
          icon={<TrendingUp size={16} />}
          accent="text-red-500"
        />
        <KPICard
          label="Sources Active"
          value={stats.sources_active}
          icon={<Activity size={16} />}
          accent="text-emerald-500"
        />
        <KPICard
          label="Competitors"
          value={stats.competitors_with_signals}
          icon={<Building2 size={16} />}
          accent="text-blue-500"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-12 gap-6">
        {/* Signal Timeline */}
        <div className="col-span-12 lg:col-span-8 bg-white border border-slate-200 rounded-lg p-6 shadow-sm">
          <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-400 mb-6">
            Signal Volume — Last 30 Days
          </h3>
          <div className="h-[240px]">
            {data.timeline.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.timeline} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
                  <defs>
                    <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#fee600" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#fee600" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 9, fontWeight: 700, fill: '#94a3b8' }}
                    tickFormatter={(d: string) => d.slice(5)}
                    axisLine={{ stroke: '#e2e8f0' }}
                  />
                  <YAxis
                    tick={{ fontSize: 9, fontWeight: 700, fill: '#94a3b8' }}
                    axisLine={{ stroke: '#e2e8f0' }}
                    allowDecimals={false}
                  />
                  <Tooltip
                    contentStyle={{ fontSize: 10, fontWeight: 700, borderRadius: 6, border: '1px solid #e2e8f0' }}
                    labelFormatter={(d) => `Date: ${d}`}
                  />
                  <Area
                    type="monotone"
                    dataKey="count"
                    stroke="#e6cf00"
                    strokeWidth={2}
                    fill="url(#areaGrad)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState text="No timeline data yet" />
            )}
          </div>
        </div>

        {/* Severity Distribution */}
        <div className="col-span-12 lg:col-span-4 bg-white border border-slate-200 rounded-lg p-6 shadow-sm">
          <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-400 mb-6">
            Severity Distribution
          </h3>
          <div className="h-[180px]">
            {data.severity_distribution.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={data.severity_distribution}
                    dataKey="count"
                    nameKey="severity"
                    cx="50%"
                    cy="50%"
                    innerRadius={45}
                    outerRadius={75}
                    strokeWidth={2}
                    stroke="#fff"
                  >
                    {data.severity_distribution.map((entry, i) => (
                      <Cell key={i} fill={PIE_COLORS[entry.severity - 1] || PIE_COLORS[0]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ fontSize: 10, fontWeight: 700, borderRadius: 6, border: '1px solid #e2e8f0' }}
                    formatter={(value, name) => [`${value} signals`, `Severity ${name}`]}
                  />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState text="No severity data" />
            )}
          </div>
          {/* Legend */}
          <div className="flex flex-wrap gap-3 mt-2 justify-center">
            {data.severity_distribution.map((d) => (
              <div key={d.severity} className="flex items-center gap-1.5">
                <div
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: PIE_COLORS[d.severity - 1] }}
                />
                <span className="text-[9px] font-bold text-slate-500">
                  S{d.severity}: {d.count}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Bottom Row */}
      <div className="grid grid-cols-12 gap-6">
        {/* By Source */}
        <div className="col-span-12 lg:col-span-5 bg-white border border-slate-200 rounded-lg p-6 shadow-sm">
          <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-400 mb-6">
            Signals by Source
          </h3>
          <div className="h-[220px]">
            {data.by_source.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={data.by_source.map((s) => ({ ...s, label: SOURCE_LABELS[s.source] || s.source }))}
                  layout="vertical"
                  margin={{ top: 0, right: 10, bottom: 0, left: 10 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 9, fontWeight: 700, fill: '#94a3b8' }} axisLine={{ stroke: '#e2e8f0' }} />
                  <YAxis
                    dataKey="label"
                    type="category"
                    tick={{ fontSize: 10, fontWeight: 900, fill: '#334155' }}
                    axisLine={false}
                    tickLine={false}
                    width={60}
                  />
                  <Tooltip contentStyle={{ fontSize: 10, fontWeight: 700, borderRadius: 6, border: '1px solid #e2e8f0' }} />
                  <Bar dataKey="count" fill="#fee600" radius={[0, 4, 4, 0]} barSize={20} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState text="No source data" />
            )}
          </div>
        </div>

        {/* Recent Signals */}
        <div className="col-span-12 lg:col-span-7 bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden">
          <div className="px-6 py-5 border-b border-slate-100 bg-slate-50/50">
            <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-900">
              Latest Intelligence
            </h3>
          </div>
          <div className="divide-y divide-slate-50 max-h-[320px] overflow-y-auto">
            {data.recent_signals.length > 0 ? (
              data.recent_signals.map((sig) => (
                <div key={sig.id} className="px-6 py-3.5 hover:bg-yellow-50/30 transition-colors group">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <SeverityBadge severity={sig.severity} />
                        <span className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">
                          {SOURCE_LABELS[sig.source] || sig.source}
                        </span>
                        <span className="text-[9px] font-bold text-slate-300">
                          {sig.competitor_id}
                        </span>
                      </div>
                      <p className="text-xs font-bold text-slate-900 truncate leading-snug">
                        {sig.title}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-[9px] font-bold text-slate-400">
                        {timeAgo(sig.detected_at)}
                      </span>
                      {sig.url && (
                        <a
                          href={sig.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-slate-300 hover:text-slate-600 opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                          <ExternalLink size={12} />
                        </a>
                      )}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="px-6 py-12">
                <EmptyState text="No signals collected yet" />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function KPICard({
  label,
  value,
  icon,
  accent,
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  accent: string;
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[9px] font-black uppercase tracking-widest text-slate-400">
          {label}
        </span>
        <span className={accent}>{icon}</span>
      </div>
      <div className="text-2xl font-black text-slate-900 tracking-tight">{value}</div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-6 max-w-[1400px] mx-auto animate-pulse">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="bg-white border border-slate-200 rounded-lg p-5 h-24 shadow-sm" />
        ))}
      </div>
      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-8 bg-white border border-slate-200 rounded-lg h-[300px] shadow-sm" />
        <div className="col-span-4 bg-white border border-slate-200 rounded-lg h-[300px] shadow-sm" />
      </div>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex items-center justify-center h-full text-[10px] font-black uppercase tracking-widest text-slate-300">
      {text}
    </div>
  );
}
