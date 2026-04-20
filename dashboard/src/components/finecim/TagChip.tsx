import { cn } from '../../utils';

interface Props {
  tag: string;
  active?: boolean;
  onClick?: (tag: string) => void;
}

export default function TagChip({ tag, active, onClick }: Props) {
  const clickable = Boolean(onClick);
  const base = 'inline-flex items-center px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest transition-colors';
  const cls = active
    ? 'bg-[#fee600] text-slate-900 border border-[#fee600]'
    : 'bg-slate-100 text-slate-600 border border-slate-200 hover:bg-yellow-50 hover:border-[#fee600]';
  if (!clickable) {
    return <span className={cn(base, cls)}>{tag}</span>;
  }
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick!(tag);
      }}
      className={cn(base, cls, 'cursor-pointer')}
      title={`Filtrovat podle tagu „${tag}"`}
    >
      {tag}
    </button>
  );
}
