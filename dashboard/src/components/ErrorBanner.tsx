import { AlertTriangle, RefreshCw } from 'lucide-react';

export default function ErrorBanner({
  message, onRetry,
}: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="border border-red-200 bg-red-50 rounded-lg p-4 flex items-start gap-3"
    >
      <AlertTriangle size={18} className="text-red-600 shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="text-[11px] font-black uppercase tracking-widest text-red-900">
          Could not load data
        </p>
        <p className="text-xs text-red-800 mt-1 font-medium break-words">{message}</p>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-black uppercase tracking-widest bg-white border border-red-300 rounded-md text-red-700 hover:bg-red-100 transition-colors"
        >
          <RefreshCw size={12} /> Retry
        </button>
      )}
    </div>
  );
}
