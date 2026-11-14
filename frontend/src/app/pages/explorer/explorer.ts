import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import { MovementAnalysis } from '../../components/movement-analysis/movement-analysis';
import { ChartSelection, PriceChart } from '../../components/price-chart/price-chart';
import { Analysis, MarketApi, Price, Profile, Stock } from '../../services/market-api';

type SelectionMode = 'session' | 'range';

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
  notice = signal('');
  selection = signal<ChartSelection>({ kind: 'session', date: '' });
  mode = signal<SelectionMode>('session');
  ticker = 'NVDA';
  sessionDate = '';
  rangeStart = '';
  rangeEnd = '';
  profile: Profile = 'amira';
  position = 10000;
  purchase = 5000;
  portfolio = 100000;
  withdrawal = 9500;

  rangeInvalid = computed(() => {
    const rows = this.rows();
    if (!rows.length || this.rangeStart === '' || this.rangeEnd === '') return false;
    const start = rows.findIndex(row => row.date === this.rangeStart);
    const end = rows.findIndex(row => row.date === this.rangeEnd);
    return start >= 0 && end >= 0 && start > end;
  });

  canAnalyze = computed(() => {
    if (this.busy() || !this.rows().length || this.rangeInvalid()) return false;
    if (this.mode() === 'session') {
      const rows = this.rows();
      return !!this.sessionDate && this.sessionDate !== rows[0]?.date;
    }
    return !!this.rangeStart && !!this.rangeEnd;
  });

  constructor() {
    this.api.stocks().subscribe({
      next: ({ stocks }) => { this.stocks.set(stocks); this.load('NVDA', '2024-08-29'); },
      error: (error) => this.showError(error),
    });
  }

  load(ticker: string, date?: string) {
    this.historyRequest?.unsubscribe();
    this.cancelAnalysis();
    this.error.set('');
    this.notice.set('');
    this.result.set(null);
    this.rows.set([]);
    this.mode.set('session');
    this.ticker = ticker;
    this.historyRequest = this.api.history(ticker).subscribe({
      next: ({ rows }) => {
        this.rows.set(rows);
        const session = this.pickSessionDate(rows, date);
        this.applySession(session, true);
      },
      error: (error) => this.showError(error),
    });
  }

  setMode(mode: SelectionMode) {
    if (this.mode() === mode) return;
    this.mode.set(mode);
    this.error.set('');
    this.notice.set('');
    if (mode === 'session') {
      const date = this.pickSessionDate(this.rows(), this.sessionDate || this.rangeEnd || undefined);
      this.applySession(date, true);
      return;
    }
    const rows = this.rows();
    if (!rows.length) return;
    this.rangeStart = this.rangeStart || rows[0].date;
    this.rangeEnd = this.rangeEnd || this.sessionDate || rows.at(-1)!.date;
    this.applyRange(this.rangeStart, this.rangeEnd);
  }

  onSessionDateChange(date: string) {
    this.applySession(date, true);
  }

  onRangeStartChange(date: string) {
    this.rangeStart = date;
    this.applyRange(this.rangeStart, this.rangeEnd);
  }

  onRangeEndChange(date: string) {
    this.rangeEnd = date;
    this.applyRange(this.rangeStart, this.rangeEnd);
  }

  onChartSelection(selection: ChartSelection) {
    if (selection.kind === 'session') {
      this.mode.set('session');
      this.applySession(selection.date, true);
      return;
    }
    this.mode.set('range');
    this.applyRange(selection.startDate, selection.endDate);
  }

  selectProfile(profile: Profile) {
    this.profile = profile;
    if (this.mode() === 'session' && this.canAnalyze()) this.analyzeCurrent();
  }

  submitAnalysis() {
    this.analyzeCurrent();
  }

  private applySession(date: string, run = false) {
    this.sessionDate = date;
    this.selection.set({ kind: 'session', date });
    this.clearPendingAnalysis();
    if (!run) return;
    if (date === this.rows()[0]?.date) {
      this.error.set('Sélectionne une séance avec une clôture précédente.');
      return;
    }
    this.error.set('');
    this.notice.set('');
    this.analyzeCurrent();
  }

  private applyRange(startDate: string, endDate: string) {
    const rows = this.rows();
    const start = rows.findIndex(row => row.date === startDate);
    const end = rows.findIndex(row => row.date === endDate);
    if (start < 0 || end < 0) return;
    const [lo, hi] = start <= end ? [startDate, endDate] : [endDate, startDate];
    this.rangeStart = lo;
    this.rangeEnd = hi;
    this.clearPendingAnalysis();
    if (lo === hi) {
      this.mode.set('session');
      this.applySession(lo, true);
      return;
    }
    this.selection.set({ kind: 'range', startDate: lo, endDate: hi });
    this.error.set('');
    this.result.set(null);
    if (start > end) {
      this.notice.set('');
      this.error.set('La date de début doit précéder ou égaler la date de fin.');
      return;
    }
    this.notice.set(
      'Une période compare la clôture de la première séance à celle de la dernière. ' +
      'Pour inclure le mouvement du 29 août 2024, commence à la clôture du 28 août 2024. ' +
      'L’analyse de période sera branchée à l’intégration API.',
    );
    // Brancher ici quand Django accepte start_date / end_date sur GET /api/analysis/ :
    // this.analyzePeriod(lo, hi);
  }

  private analyzeCurrent() {
    if (!this.canAnalyze()) return;
    if (this.mode() === 'range') {
      if (this.rangeStart === this.rangeEnd) {
        this.applySession(this.rangeStart, true);
        return;
      }
      this.applyRange(this.rangeStart, this.rangeEnd);
      return;
    }
    this.cancelAnalysis();
    this.notice.set('');
    this.busy.set(true);
    this.analysisRequest = this.api.analyze(this.scenarioParams(this.sessionDate)).subscribe({
      next: (result) => { this.result.set(result); this.busy.set(false); },
      error: (error) => this.showError(error),
    });
  }

  private analyzePeriod(startDate: string, endDate: string) {
    this.cancelAnalysis();
    this.notice.set('');
    this.busy.set(true);
    this.analysisRequest = this.api.analyzePeriod({
      ...this.scenarioParams(),
      start_date: startDate,
      end_date: endDate,
    }).subscribe({
      next: (result) => { this.result.set(result); this.busy.set(false); },
      error: (error) => this.showError(error),
    });
  }

  private scenarioParams(date?: string) {
    return {
      ticker: this.ticker,
      date: date ?? this.sessionDate,
      profile: this.profile,
      position_cad: this.position,
      purchase_cad: this.purchase,
      portfolio_cad: this.portfolio,
      withdrawal_cad: this.withdrawal,
    };
  }

  private pickSessionDate(rows: Price[], preferred?: string) {
    if (!rows.length) return '';
    if (preferred && preferred !== rows[0].date && rows.some(row => row.date === preferred)) {
      return preferred;
    }
    return rows.length > 1 ? rows.at(-1)!.date : '';
  }

  private clearPendingAnalysis() {
    this.cancelAnalysis();
    this.result.set(null);
    this.busy.set(false);
  }

  private cancelAnalysis() {
    this.analysisRequest?.unsubscribe();
    this.analysisRequest = undefined;
  }

  private showError(error: HttpErrorResponse) {
    this.busy.set(false);
    this.error.set(error.error?.error ?? 'Le service est indisponible. Réessaie dans un instant.');
  }
}