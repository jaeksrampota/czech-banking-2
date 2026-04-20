import { RefreshCw } from 'lucide-react';
import { cn } from '../utils';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  lastUpdated?: Date | null;
  loading?: boolean;
  onRefresh?: () => void;
  actions?: React.ReactNode;
}

export default function PageHeader({
  title, subtitle, lastUpdated, loading, onRefresh, actions,
}: PageHeaderProps) {
  return (
    <div className="flex items-end justify-between gap-4 mb-6">
      <div>
        <h2 className="text-slate-900 font-black text-2xl leading-tight tracking-tight">{title}</h2>
        {subtitle && (
          <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mt-1">
            {subtitle}
          </p>
        )}
      </div>
      <div className="flex items-center gap-3">
        {actions}
        {lastUpdated && (
          <span
            className="text-[9px] font-bold text-slate-400 uppercase tracking-wider tabular-nums"
            title={lastUpdated.toLocaleString('cs-CZ')}
          >
            Updated {formatAgo(lastUpdated)}
          </span>
        )}
        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            aria-label="Refresh data"
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-black uppercase tracking-widest',
              'bg-white border border-slate-200 rounded-md shadow-sm transition-colors',
              'hover:bg-slate-50 disabled:opacity-60 disabled:cursor-not-allowed',
            )}
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </button>
        )}
      </div>
    </div>
  );
}

function formatAgo(d: Date): string {
  const diff = Date.now() - d.getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 5) return 'just now';
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  return `${hours}h ago`;
}
