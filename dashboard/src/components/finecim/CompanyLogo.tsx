import { useState } from 'react';
import { cn, TIER_LABELS } from '../../utils';

interface Props {
  competitorId: string;
  name: string;
  tier: number;
  size?: number;
  className?: string;
}

/**
 * Logo společnosti s fallbackem na iniciálu.
 * Pokud v `/logos/<id>.svg` nebo `/logos/<id>.png` leží obrázek, použije se.
 * Jinak se renderuje kolečko s iniciálou obarvené podle tieru.
 */
export default function CompanyLogo({
  competitorId, name, tier, size = 40, className,
}: Props) {
  const [err, setErr] = useState(false);
  const sizePx = `${size}px`;

  if (!err) {
    return (
      <img
        src={`/logos/${competitorId}.svg`}
        alt={name}
        width={size}
        height={size}
        loading="lazy"
        onError={() => setErr(true)}
        className={cn('rounded-full object-contain bg-white border border-slate-200 p-1', className)}
        style={{ width: sizePx, height: sizePx }}
      />
    );
  }

  const tierInfo = TIER_LABELS[tier];
  const initial = name.trim().charAt(0).toUpperCase();
  return (
    <div
      className={cn(
        'rounded-full flex items-center justify-center border-2 font-black',
        tierInfo?.badge || 'bg-slate-50 text-slate-500 border-slate-200',
        className,
      )}
      style={{ width: sizePx, height: sizePx, fontSize: `${size * 0.4}px` }}
      role="img"
      aria-label={name}
    >
      {initial}
    </div>
  );
}
