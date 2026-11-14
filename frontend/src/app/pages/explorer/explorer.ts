import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import { MovementAnalysis } from '../../components/movement-analysis/movement-analysis';
import { PriceChart } from '../../components/price-chart/price-chart';
import { Analysis, MarketApi, Price, Profile, Stock } from '../../services/market-api';

@Component({
  selector: 'app-explorer',
  imports: [FormsModule, PriceChart, MovementAnalysis],
  templateUrl: './explorer.html',
  styleUrl: './explorer.css',
})
export class Explorer {
  private api = inject(MarketApi);
  private historyRequest?: Subscription;
  private analysisRequest?: Subscription;
  stocks = signal<Stock[]>([]);
  rows = signal<Price[]>([]);
  result = signal<Analysis | null>(null);
  busy = signal(false);
  error = signal('');
  ticker = 'NVDA';
  date = '';
  startDate = '';
  endDate = '';
  periodMode = signal(false);
  profile: Profile = 'amira';
  position = 10000;
  purchase = 5000;
  portfolio = 100000;
  withdrawal = 9500;

  constructor() {
    this.api.stocks().subscribe({
      next: ({ stocks }) => { this.stocks.set(stocks); this.load('NVDA', '2024-08-29'); },
      error: (error) => this.showError(error),
    });
  }

  load(ticker: string, date?: string) {
    this.historyRequest?.unsubscribe();
    this.analysisRequest?.unsubscribe();
    this.busy.set(false);
    this.error.set('');
    this.result.set(null);
    this.rows.set([]);
    this.date = '';
    this.startDate = '';
    this.endDate = '';
    this.periodMode.set(false);
    this.ticker = ticker;
    this.historyRequest = this.api.history(ticker).subscribe({
      next: ({ rows }) => {
        this.rows.set(rows);
        this.date = date ?? rows.at(-1)?.date ?? '';
        if (this.date) this.analyzeSession(this.date);
      },
      error: (error) => this.showError(error),
    });
  }

  selectableRows() {
    return this.rows().slice(1);
  }

  selectProfile(profile: Profile) {
    this.profile = profile;
    this.runAnalysis();
  }

  analyzeSession(date: string) {
    this.periodMode.set(false);
    this.startDate = '';
    this.endDate = '';
    this.date = date;
    this.runAnalysis();
  }

  analyzeRange(range: { start: string; end: string }) {
    this.periodMode.set(true);
    this.startDate = range.start;
    this.endDate = range.end;
    this.date = range.end;
    this.runAnalysis();
  }

  onStartDateChange(value: string) {
    this.startDate = value;
    this.periodMode.set(true);
    if (this.startDate && this.endDate) this.runAnalysis();
  }

  onEndDateChange(value: string) {
    this.endDate = value;
    this.periodMode.set(true);
    if (this.startDate && this.endDate) this.runAnalysis();
  }

  analyze() {
    this.runAnalysis();
  }

  private runAnalysis() {
    this.analysisRequest?.unsubscribe();
    this.error.set('');
    this.result.set(null);
    this.busy.set(true);
    const params: Record<string, string | number> = {
      ticker: this.ticker,
      profile: this.profile,
      position_cad: this.position,
      purchase_cad: this.purchase,
      portfolio_cad: this.portfolio,
      withdrawal_cad: this.withdrawal,
    };
    if (this.periodMode() && this.startDate && this.endDate) {
      params['start_date'] = this.startDate;
      params['end_date'] = this.endDate;
    } else if (this.date) {
      params['date'] = this.date;
    } else {
      this.busy.set(false);
      return;
    }
    this.analysisRequest = this.api.analyze(params).subscribe({
      next: (result) => { this.result.set(result); this.busy.set(false); },
      error: (error) => this.showError(error),
    });
  }

  loadDemoPeriod() {
    this.load('NVDA', '2024-09-06');
    this.startDate = '2024-08-28';
    this.endDate = '2024-09-06';
    this.periodMode.set(true);
    this.runAnalysis();
  }

  private showError(error: HttpErrorResponse) {
    this.busy.set(false);
    this.error.set(error.error?.error ?? 'Le service est indisponible. Réessaie dans un instant.');
  }
}