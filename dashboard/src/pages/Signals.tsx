import { useState, useMemo } from 'react';
import { Search, ExternalLink, ChevronDown, ChevronUp, X } from 'lucide-react';
import { api } from '../api';
import type { Signal } from '../types';
import SeverityBadge from '../components/SeverityBadge';
import PageHeader from '../components/PageHeader';
import ErrorBanner from '../components/ErrorBanner';
import { useFetch } from '../hooks/useFetch';
import { cn, SOURCE_LABELS, formatDateTime } from '../utils';

export default function Signals() {
  const { data, loading, error, lastUpdated, refresh } = useFetch(
    () => api.getSignals({ limit: '500' }),
  );
  const signals = data ?? [];
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Filters
  const [filterSource, setFilterSource] = useState('');
  const [filterCompetitor, setFilterCompetitor] = useState('');
  const [filterSeverity, setFilterSeverity] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [sortKey, setSortKey] = useState<'detected_at' | 'severity' | 'competitor_id'>('detected_at');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const sources = useMemo(() => [...new Set(signals.map((s) => s.source))].sort(), [signals]);
  const competitors = useMemo(() => [...new Set(signals.map((s) => s.competitor_id))].sort(), [signals]);

  const filtered = useMemo(() => {
    let result = signals;
    if (filterSource) result = result.filter((s) => s.source === filterSource);
    if (filterCompetitor) result = result.filter((s) => s.competitor_id === filterCompetitor);
    if (filterSeverity) result = result.filter((s) => s.severity >= Number(filterSeverity));
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (s) =>
          s.title.toLowerCase().includes(q) ||
          s.content.toLowerCase().includes(q) ||
          s.signal_type.toLowerCase().includes(q)
      );
    }
    result.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return result;
  }, [signals, filterSource, filterCompetitor, filterSeverity, searchQuery, sortKey, sortDir]);

  const handleSort = (key: typeof sortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const SortIcon = ({ column }: { column: typeof sortKey }) =>
    sortKey === column ? (
      sortDir === 'asc' ? <ChevronUp size={10} /> : <ChevronDown size={10} />
    ) : null;

  const hasFilters = filterSource || filterCompetitor || filterSeverity || searchQuery;

  const header = (
    <PageHeader
      title="Signals"
      subtitle={data ? `${filtered.length} of ${signals.length} signals shown` : 'Filter and drill into intelligence signals'}
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
      {/* Filters */}
      <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm flex flex-wrap items-center gap-4">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-300" size={14} />
          <input
            type="text"
            placeholder="Search signals..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-slate-50 border border-slate-200 rounded py-2 pl-9 pr-4 text-[10px] font-bold uppercase tracking-wider text-slate-900 focus:outline-none focus:border-[#fee600] transition-colors"
          />
        </div>
        <FilterSelect
          label="Source"
          value={filterSource}
          onChange={setFilterSource}
          options={sources.map((s) => ({ value: s, label: SOURCE_LABELS[s] || s }))}
        />
        <FilterSelect
          label="Competitor"
          value={filterCompetitor}
          onChange={setFilterCompetitor}
          options={competitors.map((c) => ({ value: c, label: c }))}
        />
        <FilterSelect
          label="Min Severity"
          value={filterSeverity}
          onChange={setFilterSeverity}
          options={[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: `>= ${n}` }))}
        />
        {hasFilters && (
          <button
            onClick={() => {
              setFilterSource('');
              setFilterCompetitor('');
              setFilterSeverity('');
              setSearchQuery('');
            }}
            className="text-[9px] font-black uppercase tracking-widest text-slate-400 hover:text-red-500 transition-colors flex items-center gap-1"
          >
            <X size={10} /> Clear
          </button>
        )}
        <div className="text-[9px] font-bold text-slate-400 uppercase tracking-wider ml-auto">
          {filtered.length} / {signals.length} signals
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[10px] border-collapse">
            <thead>
              <tr className="text-slate-400 border-b border-slate-100 bg-slate-50/30">
                <th
                  className="px-6 py-4 font-black uppercase tracking-widest cursor-pointer hover:text-slate-900 transition-colors"
                  onClick={() => handleSort('detected_at')}
                >
                  <span className="flex items-center gap-1">Time <SortIcon column="detected_at" /></span>
                </th>
                <th
                  className="px-6 py-4 font-black uppercase tracking-widest cursor-pointer hover:text-slate-900 transition-colors"
                  onClick={() => handleSort('competitor_id')}
                >
                  <span className="flex items-center gap-1">Competitor <SortIcon column="competitor_id" /></span>
                </th>
                <th className="px-6 py-4 font-black uppercase tracking-widest">Source</th>
                <th className="px-6 py-4 font-black uppercase tracking-widest">Type</th>
                <th className="px-6 py-4 font-black uppercase tracking-widest">Title</th>
                <th
                  className="px-6 py-4 font-black uppercase tracking-widest text-center cursor-pointer hover:text-slate-900 transition-colors"
                  onClick={() => handleSort('severity')}
                >
                  <span className="flex items-center gap-1 justify-center">Sev <SortIcon column="severity" /></span>
                </th>
                <th className="px-6 py-4 font-black uppercase tracking-widest text-center w-10" />
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-6 py-16 text-center text-[10px] font-black uppercase tracking-widest text-slate-300">
                    No signals match your filters
                  </td>
                </tr>
              ) : (
                filtered.map((sig) => (
                  <SignalRow
                    key={sig.id}
                    signal={sig}
                    expanded={expandedId === sig.id}
                    onToggle={() => setExpandedId(expandedId === sig.id ? null : sig.id)}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function SignalRow({
  signal: sig,
  expanded,
  onToggle,
}: {
  signal: Signal;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr
        className={cn(
          'border-b border-slate-50 hover:bg-yellow-50/30 transition-colors cursor-pointer group',
          expanded && 'bg-yellow-50/50'
        )}
        onClick={onToggle}
      >
        <td className="px-6 py-3.5 text-slate-500 font-mono whitespace-nowrap">
          {formatDateTime(sig.detected_at)}
        </td>
        <td className="px-6 py-3.5 font-bold text-slate-900">{sig.competitor_id}</td>
        <td className="px-6 py-3.5">
          <span className="px-2 py-0.5 rounded bg-slate-100 text-[9px] font-black uppercase tracking-widest text-slate-600">
            {SOURCE_LABELS[sig.source] || sig.source}
          </span>
        </td>
        <td className="px-6 py-3.5 text-slate-500">{sig.signal_type}</td>
        <td className="px-6 py-3.5 font-bold text-slate-900 max-w-[400px] truncate">{sig.title}</td>
        <td className="px-6 py-3.5 text-center">
          <SeverityBadge severity={sig.severity} />
        </td>
        <td className="px-6 py-3.5 text-center">
          {expanded ? <ChevronUp size={12} className="text-slate-400" /> : <ChevronDown size={12} className="text-slate-300" />}
        </td>
      </tr>
      {expanded && (
        <tr className="bg-slate-50/50">
          <td colSpan={7} className="px-6 py-5">
            <div className="grid grid-cols-12 gap-6 text-[10px]">
              <div className="col-span-8">
                <div className="text-[9px] font-black uppercase tracking-widest text-slate-400 mb-2">Content</div>
                <p className="text-slate-700 whitespace-pre-wrap leading-relaxed font-medium">
                  {sig.content || '—'}
                </p>
                {sig.change_summary && (
                  <div className="mt-3">
                    <div className="text-[9px] font-black uppercase tracking-widest text-slate-400 mb-1">Change Summary</div>
                    <p className="text-slate-600 font-mono text-[10px]">{sig.change_summary}</p>
                  </div>
                )}
              </div>
              <div className="col-span-4 space-y-3">
                {sig.url && (
                  <div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-slate-400 mb-1">Source URL</div>
                    <a
                      href={sig.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline flex items-center gap-1 font-bold truncate"
                    >
                      <ExternalLink size={10} /> {sig.url}
                    </a>
                  </div>
                )}
                {sig.tags.length > 0 && (
                  <div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-slate-400 mb-1">Tags</div>
                    <div className="flex flex-wrap gap-1">
                      {sig.tags.map((tag, i) => (
                        <span key={i} className="px-1.5 py-0.5 bg-slate-200 rounded text-[9px] font-bold text-slate-600">
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                <div>
                  <div className="text-[9px] font-black uppercase tracking-widest text-slate-400 mb-1">Hash</div>
                  <span className="font-mono text-slate-400">{sig.content_hash.slice(0, 16)}...</span>
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        'bg-slate-50 border border-slate-200 rounded py-2 px-3 text-[10px] font-bold uppercase tracking-wider focus:outline-none focus:border-[#fee600] transition-colors appearance-none cursor-pointer min-w-[120px]',
        value ? 'text-slate-900' : 'text-slate-400'
      )}
    >
      <option value="">{label}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
