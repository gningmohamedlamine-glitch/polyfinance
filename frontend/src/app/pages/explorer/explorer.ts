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
    this.ticker = ticker;
    this.historyRequest = this.api.history(ticker).subscribe({
      next: ({ rows }) => {
        this.rows.set(rows);
        this.date = date ?? rows.at(-1)?.date ?? '';
        if (this.date) this.analyze();
      },
      error: (error) => this.showError(error),
    });
  }

  selectProfile(profile: Profile) {
    this.profile = profile;
    if (this.date) this.analyze();
  }

  analyze(date = this.date) {
    this.analysisRequest?.unsubscribe();
    this.date = date;
    this.error.set('');
    this.result.set(null);
    this.busy.set(true);
    this.analysisRequest = this.api.analyze({
      ticker: this.ticker, date, profile: this.profile, position_cad: this.position,
      purchase_cad: this.purchase, portfolio_cad: this.portfolio, withdrawal_cad: this.withdrawal,
    }).subscribe({
      next: (result) => { this.result.set(result); this.busy.set(false); },
      error: (error) => this.showError(error),
    });
  }

  private showError(error: HttpErrorResponse) {
    this.busy.set(false);
    this.error.set(error.error?.error ?? 'Le service est indisponible. Réessaie dans un instant.');
  }
}
