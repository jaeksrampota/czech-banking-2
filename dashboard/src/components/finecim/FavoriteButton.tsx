import { Star } from 'lucide-react';
import { cn } from '../../utils';
import { useFavorites, type FavoriteType } from '../../hooks/useFavorites';

interface Props {
  type: FavoriteType;
  id: string;
  size?: number;
  className?: string;
}

export default function FavoriteButton({ type, id, size = 14, className }: Props) {
  const { isFavorite, toggle } = useFavorites();
  const active = isFavorite(type, id);

  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        toggle(type, id);
      }}
      aria-label={active ? 'Odebrat z oblíbených' : 'Přidat do oblíbených'}
      aria-pressed={active}
      className={cn(
        'p-1 rounded transition-colors',
        active
          ? 'text-[#e6cf00] hover:text-[#cab800]'
          : 'text-slate-300 hover:text-[#e6cf00]',
        className,
      )}
      title={active ? 'Odebrat z oblíbených' : 'Přidat do oblíbených'}
    >
      <Star size={size} fill={active ? 'currentColor' : 'none'} />
    </button>
  );
}
