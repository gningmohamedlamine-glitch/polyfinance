import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

export interface Stock { ticker: string; name: string }
export interface Price { date: string; open: number; high: number; low: number; close: number; adj_close: number; volume: number }
export interface Source {
  session?: string;
  time_et: string;
  publisher: string;
  title: string;
  url: string;
  summary: string;
  excerpt?: string;
  excerpt_status?: 'verified' | 'mismatch' | 'source_missing' | 'no_excerpt';
}
export interface MarketModel {
  status: string;
  reference: string;
  beta?: number;
  expected_return?: number;
  residual?: number;
  residual_pp?: number;
}
export interface AgentDecision {
  agent: 'event' | 'impact' | 'governance';
  tool: string;
  arguments: Record<string, unknown>;
  accepted: boolean;
  reason?: string | null;
  refusal?: string;
  output?: unknown;
}
export interface Usage { input_tokens: number; output_tokens: number; model_calls: number; model?: string | null }
export interface Coherence {
  coherent: boolean | null;
  conflicts: string[];
  limits: { annual_volatility: number; max_drawdown: number; max_weight: number; horizon_years: number; max_sector_weight?: number };
  sector?: { sector: string | null; is_tech: boolean; before: number; after: number; assumption: string } | null;
  risk: { status: string; annual_volatility?: number; max_drawdown?: number };
  notice: string;
}
export interface ToolTrace {
  agent: string;
  name: string;
  source: string;
  status: string;
  arguments: Record<string, unknown>;
  error?: string;
}
export interface AgentProgress {
  kind: 'progress';
  agent: 'event' | 'impact' | 'governance';
  action: string;
  status: 'running' | 'done' | 'unavailable';
  count?: number | null;
  mode?: string | null;
  duration_ms?: number | null;
  reason?: string | null;
}

export interface AnalysisPreview {
  kind: 'preview';
  movement: Analysis['movement'];
  coherence: Coherence;
}

export interface EvidencePreview {
  kind: 'evidence';
  publications: Source[];
  web_leads: NonNullable<NonNullable<Analysis['dossier']>['coverage']['web_leads']>;
}

type AnalysisMessage = AgentProgress | AnalysisPreview | EvidencePreview | { kind: 'result'; analysis: Analysis } | { kind: 'error'; message: string };

export interface Analysis {
  movement: {
    date: string;
    previous_date: string;
    usd_return: number;
    cad_return: number | null;
    benchmarks: Record<string, { name: string; return: number | null; gap: number | null; gap_pp?: number | null; status?: string }>;
  };
  dossier?: {
    selection: {
      ticker?: string;
      name?: string;
      start_adj_close?: number;
      end_adj_close?: number;
      requested: string;
      applied: string;
      start_close_date: string;
      end_close_date: string;
      bounds?: { start_date: string; end_date: string };
    };
    benchmarks: Record<string, { name?: string; kind?: string; return?: number | null; gap_pp: number | null; status: string }>;
    returns?: { market_model?: MarketModel | null };
    agent_decisions?: AgentDecision[];
    limits?: Record<string, string | number>;
    usage?: Usage;
    notable_sessions: {
      concentration: string;
      sessions: { date: string; daily_return: number }[];
    };
    coverage: {
      sessions_unexplained: string[];
      web_search?: string;
      web_search_reason?: string;
      nova_grounding?: string;
      web_leads?: {
        url: string;
        title: string;
        published_date: string;
        summary: string;
        session?: string;
        after_session?: boolean;
        source_type?: string;
        corroboration?: number;
        source_origin?: 'official' | 'other';
        page_status?: 'retrieved' | 'unavailable' | 'not_checked';
        excerpt_status?: string;
        original_excerpt?: string;
        domains?: string[];
        verification?: 'corroborated' | 'single_source';
        relevance?: string;
        story_key?: string;
        related_count?: number;
        facts?: string[];
      }[];
    };
  };
  event: { text: string; mode: string; mode_reason?: string | null; sources: Source[] };
  impact: {
    text: string;
    mode: string;
    mode_reason?: string | null;
    metrics: { label: string; value: number; unit: string }[];
    assumptions?: string;
    coherence?: Coherence;
    decisions?: AgentDecision[];
    usage?: Usage;
    esg?: Esg | null;
    scenario?: Partial<Record<'position_cad' | 'purchase_cad' | 'portfolio_cad' | 'withdrawal_cad', number>>;
  };
  trace?: ToolTrace[];
  controls?: Controls;
  sensitivity?: Sensitivity;
}
export type Profile = 'amira' | 'robert' | 'mateo';

export interface SensitivityChart {
  unit: 'pts' | '%';
  scenarios: { label: string; detail?: string; verdict: string }[];
  measures: { label: string; values: number[]; limit?: number }[];
}
export interface SensitivityCheck {
  id: string;
  question: string;
  base: string;
  alternative: string;
  holds: boolean;
  chart?: SensitivityChart;
}
export interface Sensitivity { checks: SensitivityCheck[]; robust: boolean; summary: string }
export interface Control { id: string; label: string; status: 'ok' | 'warn' | 'fail' | 'info'; detail: string }
export interface Controls { verdict: 'ok' | 'warn' | 'fail'; controls: Control[]; notice: string }

export interface EsgSnapshot {
  symbol: string; return_12m: number | null; annual_volatility: number; max_drawdown: number;
  start_date: string; end_date: string;
}
export interface Esg {
  ticker: string;
  sector: string | null;
  sector_flag: string | null;
  membership: { status: 'ok' | 'unavailable'; member?: boolean; as_of?: string | null };
  comparison: { stock: EsgSnapshot | null; reference: EsgSnapshot | null };
  controversies: { title: string; url?: string; published_date?: string; kind: string; topic?: string | null; summary?: string }[];
  web_status: string;
  attention: string[];
  missing: string[];
  conclusion: 'points_attention' | 'insuffisant';
  notice: string;
}

@Injectable({ providedIn: 'root' })
export class MarketApi {
  private http = inject(HttpClient);

  stocks() {
    return this.http.get<{ stocks: Stock[]; profiles: Record<Profile, string> }>('/api/stocks/');
  }

  history(ticker: string) {
    return this.http.get<{ ticker: string; rows: Price[] }>(`/api/stocks/${ticker}/`);
  }

  analyze(params: Record<string, string | number>) {
    return new Observable<AgentProgress | AnalysisPreview | EvidencePreview | Analysis>(subscriber => {
      const controller = new AbortController();
      const query = new URLSearchParams({ stream: '1' });
      Object.entries(params).forEach(([key, value]) => query.set(key, String(value)));

      void (async () => {
        try {
          const response = await fetch('/api/analysis/?' + query, { signal: controller.signal });
          if (!response.ok) {
            const body = await response.json();
            throw new Error(body.error);
          }
          if (!response.body) throw new Error('Flux d’analyse indisponible.');
          const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
          let buffer = '';
          while (!subscriber.closed) {
            const { value, done } = await reader.read();
            if (done) throw new Error('La connexion a été interrompue pendant l’analyse.');
            buffer += value;
            const lines = buffer.split('\n');
            buffer = lines.pop() ?? '';
            for (const line of lines) {
              if (!line) continue;
              const message: AnalysisMessage = JSON.parse(line);
              if (message.kind === 'error') throw new Error(message.message);
              if (message.kind === 'result') {
                subscriber.next(message.analysis);
                subscriber.complete();
                return;
              }
              subscriber.next(message);
            }
          }
        } catch (error) {
          if (!subscriber.closed) subscriber.error(error);
        }
      })();
      return () => controller.abort();
    });
  }
}
