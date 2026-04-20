import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const SEVERITY_COLORS: Record<number, { bg: string; text: string; dot: string; label: string }> = {
  1: { bg: 'bg-emerald-50', text: 'text-emerald-700', dot: 'bg-emerald-500', label: 'Nízká' },
  2: { bg: 'bg-blue-50', text: 'text-blue-700', dot: 'bg-blue-500', label: 'Info' },
  3: { bg: 'bg-amber-50', text: 'text-amber-700', dot: 'bg-amber-500', label: 'Střední' },
  4: { bg: 'bg-red-50', text: 'text-red-700', dot: 'bg-red-500', label: 'Vysoká' },
  5: { bg: 'bg-red-100', text: 'text-red-900', dot: 'bg-red-700', label: 'Kritická' },
};

export const SOURCE_LABELS: Record<string, string> = {
  ares: 'ARES',
  job_postings: 'Nábor',
  news: 'Zprávy',
  google_news: 'Google News',
};

export const TIER_LABELS: Record<number, { kratky: string; dlouhy: string; popis: string; badge: string }> = {
  1: {
    kratky: 'T1',
    dlouhy: 'Tier 1 — Univerzální banky',
    popis: 'Dominantní hráči, převážně zahraničně vlastněni',
    badge: 'border-red-200 text-red-600 bg-red-50',
  },
  2: {
    kratky: 'T2',
    dlouhy: 'Tier 2 — Vyzyvatelé',
    popis: 'Střední a digitální banky',
    badge: 'border-blue-200 text-blue-600 bg-blue-50',
  },
  3: {
    kratky: 'T3',
    dlouhy: 'Tier 3 — Fintech a specialisté',
    popis: 'Nová generace a úzce zaměření hráči',
    badge: 'border-slate-200 text-slate-600 bg-slate-50',
  },
};

export const MEDIA_TYPE_LABELS: Record<string, string> = {
  TV: 'TV',
  Outdoor: 'Outdoor',
  Web: 'Web',
  Social: 'Sociální sítě',
  Radio: 'Rádio',
  Print: 'Tisk',
};

export const CZECH_MONTHS = [
  'leden', 'únor', 'březen', 'duben', 'květen', 'červen',
  'červenec', 'srpen', 'září', 'říjen', 'listopad', 'prosinec',
];

export function formatDate(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('cs-CZ', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('cs-CZ', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  });
}

export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'právě teď';
  if (mins < 60) return `před ${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `před ${hours} h`;
  const days = Math.floor(hours / 24);
  return `před ${days} d`;
}
