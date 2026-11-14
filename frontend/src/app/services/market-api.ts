import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';

export interface Stock { ticker: string; name: string }
export interface Price { date: string; close: number; adj_close: number; volume: number }
export interface Source { time_et: string; publisher: string; title: string; url: string; summary: string }
export interface Analysis {
  movement: {
    date: string; previous_date: string; usd_return: number; cad_return: number | null;
    benchmarks: Record<string, { name: string; return: number; gap: number }>;
  };
  event: { text: string; mode: string; sources: Source[] };
  impact: { text: string; mode: string; metrics: { label: string; value: number; unit: string }[] };
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
