import { Inbox } from 'lucide-react';

export default function EmptyState({
  title = 'Zatím žádné položky',
  description,
}: {
  title?: string;
  description?: string;
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-16 shadow-sm flex flex-col items-center justify-center text-center">
      <div className="w-14 h-14 rounded-full bg-slate-50 flex items-center justify-center mb-4">
        <Inbox size={22} className="text-slate-300" />
      </div>
      <p className="text-[11px] font-black uppercase tracking-widest text-slate-500">
        {title}
      </p>
      {description && (
        <p className="text-xs text-slate-400 mt-2 max-w-md font-medium">
          {description}
        </p>
      )}
    </div>
  );
}
