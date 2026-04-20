export interface Signal {
  id: string;
  competitor_id: string;
  source: string;
  signal_type: string;
  title: string;
  content: string;
  url: string;
  detected_at: string;
  published_at: string | null;
  severity: number;
  tags: string[];
  metadata: Record<string, unknown>;
  change_summary: string | null;
  content_hash: string;
}

export interface Competitor {
  id: string;
  name: string;
  parent_group: string | null;
  tier: number;
  ico: string | null;
  config_path: string;
  signal_count: number;
  avg_severity: number;
}

export interface CollectorRun {
  collector_name: string;
  competitor_id: string | null;
  started_at: string;
  finished_at: string | null;
  status: string;
  signals_found: number;
  error_message: string | null;
}

export interface Summary {
  total_signals: {
    total_signals: number;
    avg_severity: number;
    last_signal: string;
    competitors_with_signals: number;
    sources_active: number;
  };
  severity_distribution: { severity: number; count: number }[];
  by_source: { source: string; count: number }[];
  by_competitor: { competitor_id: string; count: number; avg_severity: number }[];
  recent_signals: Signal[];
  timeline: { date: string; count: number }[];
}

export type Page = 'overview' | 'signals' | 'competitors' | 'status';
