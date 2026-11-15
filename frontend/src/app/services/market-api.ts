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
  residual_pp?: number;
}
export interface AgentDecision {
  agent: 'event' | 'impact';
  tool: string;
  arguments: Record<string, unknown>;
  accepted: boolean;
  reason?: string | null;
  refusal?: string;
}
export interface Coherence {
  coherent: boolean;
  conflicts: string[];
  limits: { annual_volatility: number; max_drawdown: number; max_weight: number; horizon_years: number };
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
  agent: 'event' | 'impact';
  action: string;
  status: 'running' | 'done' | 'unavailable';
  count?: number | null;
  mode?: string | null;
  duration_ms?: number | null;
  reason?: string | null;
}

type AnalysisMessage = AgentProgress | { kind: 'result'; analysis: Analysis } | { kind: 'error'; message: string };

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
      requested: string;
      applied: string;
      start_close_date: string;
      end_close_date: string;
      bounds?: { start_date: string; end_date: string };
    };
    benchmarks: Record<string, { name?: string; kind?: string; return?: number | null; gap_pp: number | null; status: string }>;
    returns?: { market_model?: MarketModel | null };
    agent_decisions?: AgentDecision[];
    notable_sessions: {
      concentration: string;
      sessions: { date: string; daily_return: number }[];
    };
    coverage: {
      sessions_unexplained: string[];
      web_search?: string;
      web_search_reason?: string;
      web_leads?: {
        url: string;
        title: string;
        published_date: string;
        summary: string;
        session?: string;
        after_session?: boolean;
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
    scenario?: Partial<Record<'position_cad' | 'purchase_cad' | 'portfolio_cad' | 'withdrawal_cad', number>>;
  };
  trace?: ToolTrace[];
}
export type Profile = 'amira' | 'robert' | 'mateo';

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
    return new Observable<AgentProgress | Analysis>(subscriber => {
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
