import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';

export interface Stock { ticker: string; name: string }
export interface Price { date: string; close: number; adj_close: number; volume: number }
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
    notable_sessions: {
      concentration: string;
      sessions: { date: string; daily_return: number }[];
    };
    coverage: { sessions_unexplained: string[] };
  };
  event: { text: string; mode: string; mode_reason?: string | null; sources: Source[] };
  impact: {
    text: string;
    mode: string;
    mode_reason?: string | null;
    metrics: { label: string; value: number; unit: string }[];
    assumptions?: string;
    coherence?: Coherence;
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
    return this.http.get<Analysis>('/api/analysis/', { params });
  }
}