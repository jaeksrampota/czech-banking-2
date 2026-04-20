import { useMemo } from 'react';
import { CheckCircle2, XCircle, Clock } from 'lucide-react';
import { api } from '../api';
import PageHeader from '../components/PageHeader';
import ErrorBanner from '../components/ErrorBanner';
import { useFetch } from '../hooks/useFetch';
import { cn, SOURCE_LABELS, formatDateTime } from '../utils';

export default function Status() {
  const { data, loading, error, lastUpdated, refresh } = useFetch(
    () => api.getStatus(),
  );
  const runs = data ?? [];

  // Per-collector summary
  const collectorStats = useMemo(() => {
    const map = new Map<string, { total: number; success: number; failed: number; signals: number; lastRun: string }>();
    for (const r of runs) {
      const name = r.collector_name;
      if (!map.has(name)) map.set(name, { total: 0, success: 0, failed: 0, signals: 0, lastRun: '' });
      const s = map.get(name)!;
      s.total++;
      if (r.status === 'success') s.success++;
      else if (r.status === 'failed') s.failed++;
      s.signals += r.signals_found || 0;
      if (!s.lastRun || r.started_at > s.lastRun) s.lastRun = r.started_at;
    }
    return [...map.entries()].map(([name, stats]) => ({ name, ...stats }));
  }, [runs]);

  const header = (
    <PageHeader
      title="Stav kolektorů"
      subtitle="Zdraví jednotlivých kolektorů a historie běhů"
      loading={loading}
      lastUpdated={lastUpdated}
      onRefresh={refresh}
    />
  );

  if (error) {
    return (
      <div className="max-w-[1400px] mx-auto space-y-6">
        {header}
        <ErrorBanner message={error} onRetry={refresh} />
      </div>
    );
  }

  return (
    <div className="max-w-[1400px] mx-auto space-y-6">
      {header}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {collectorStats.length > 0 ? (
          collectorStats.map((c) => {
            const rate = c.total > 0 ? Math.round((c.success / c.total) * 100) : 0;
            const healthy = rate >= 80;
            return (
              <div key={c.name} className="bg-white border border-slate-200 rounded-lg p-6 shadow-sm">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className={cn(
                      'w-10 h-10 rounded flex items-center justify-center',
                      healthy ? 'bg-emerald-50' : 'bg-red-50'
                    )}>
                      {healthy
                        ? <CheckCircle2 size={18} className="text-emerald-500" />
                        : <XCircle size={18} className="text-red-500" />}
                    </div>
                    <div>
                      <div className="text-xs font-black text-slate-900 uppercase tracking-tight">
                        {SOURCE_LABELS[c.name] || c.name}
                      </div>
                      <div className="text-[9px] font-bold text-slate-400">{c.name}</div>
                    </div>
                  </div>
                  <div className={cn(
                    'text-lg font-black',
                    healthy ? 'text-emerald-600' : 'text-red-600'
                  )}>
                    {rate}%
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-3 text-center">
                  <div>
                    <div className="text-[8px] font-black uppercase tracking-widest text-slate-400">Běhů</div>
                    <div className="text-sm font-black text-slate-900">{c.total}</div>
                  </div>
                  <div>
                    <div className="text-[8px] font-black uppercase tracking-widest text-slate-400">Signálů</div>
                    <div className="text-sm font-black text-slate-900">{c.signals}</div>
                  </div>
                  <div>
                    <div className="text-[8px] font-black uppercase tracking-widest text-slate-400">Chyb</div>
                    <div className="text-sm font-black text-red-600">{c.failed}</div>
                  </div>
                </div>
                <div className="mt-3 pt-3 border-t border-slate-100 flex items-center gap-1.5 text-[9px] font-bold text-slate-400">
                  <Clock size={10} /> Poslední běh: {formatDateTime(c.lastRun)}
                </div>
              </div>
            );
          })
        ) : (
          <div className="col-span-3 bg-white border border-slate-200 rounded-lg p-12 shadow-sm text-center">
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-300">
              Zatím žádné běhy — spusťte nejdřív <code className="font-mono bg-slate-100 px-1.5 py-0.5 rounded text-slate-500">ci-monitor collect</code>
            </div>
          </div>
        )}
      </div>

      {/* Run history table */}
      <div className="bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 bg-slate-50/50 flex items-center justify-between">
          <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-900">Historie běhů</h3>
          <span className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">{runs.length} běhů</span>
        </div>
        <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
          <table className="w-full text-[10px] text-left border-collapse">
            <thead className="sticky top-0 bg-white z-10">
              <tr className="text-slate-400 border-b border-slate-100">
                <th className="px-6 py-3 font-black uppercase tracking-widest">Kolektor</th>
                <th className="px-6 py-3 font-black uppercase tracking-widest">Společnost</th>
                <th className="px-6 py-3 font-black uppercase tracking-widest">Začátek</th>
                <th className="px-6 py-3 font-black uppercase tracking-widest">Konec</th>
                <th className="px-6 py-3 font-black uppercase tracking-widest text-center">Stav</th>
                <th className="px-6 py-3 font-black uppercase tracking-widest text-right">Signálů</th>
                <th className="px-6 py-3 font-black uppercase tracking-widest">Chyba</th>
              </tr>
            </thead>
            <tbody>
              {runs.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center text-[10px] font-black uppercase tracking-widest text-slate-300">
                    Žádné záznamy
                  </td>
                </tr>
              ) : (
                runs.map((run, i) => (
                  <tr key={i} className="border-b border-slate-50 hover:bg-slate-50/50 transition-colors">
                    <td className="px-6 py-3 font-bold text-slate-900">
                      {SOURCE_LABELS[run.collector_name] || run.collector_name}
                    </td>
                    <td className="px-6 py-3 text-slate-600">{run.competitor_id || 'vše'}</td>
                    <td className="px-6 py-3 font-mono text-slate-500 whitespace-nowrap">{formatDateTime(run.started_at)}</td>
                    <td className="px-6 py-3 font-mono text-slate-500 whitespace-nowrap">{formatDateTime(run.finished_at)}</td>
                    <td className="px-6 py-3 text-center">
                      <span className={cn(
                        'inline-flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest',
                        run.status === 'success'
                          ? 'bg-emerald-50 text-emerald-700'
                          : run.status === 'failed'
                          ? 'bg-red-50 text-red-700'
                          : 'bg-amber-50 text-amber-700'
                      )}>
                        {run.status === 'success' && <CheckCircle2 size={10} />}
                        {run.status === 'failed' && <XCircle size={10} />}
                        {run.status}
                      </span>
                    </td>
                    <td className="px-6 py-3 text-right font-black text-slate-900">{run.signals_found}</td>
                    <td className="px-6 py-3 text-red-500 max-w-[200px] truncate" title={run.error_message || ''}>
                      {run.error_message || ''}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
