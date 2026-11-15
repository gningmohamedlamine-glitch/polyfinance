import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import { AgentTimeline } from '../../components/agent-timeline/agent-timeline';
import { DossierView } from '../../components/dossier-view/dossier-view';
import { TracesView } from '../../components/traces-view/traces-view';
import { MovementAnalysis } from '../../components/movement-analysis/movement-analysis';
import { ChartSelection, PriceChart } from '../../components/price-chart/price-chart';
import { LucideDynamicIcon } from '@lucide/angular';
import { ICONS } from '../../icons';
import { PERSONAS, personaOf } from '../../personas';
import { AgentProgress, Analysis, MarketApi, Price, Profile, Stock } from '../../services/market-api';

type SelectionMode = 'session' | 'range';

@Component({
  selector: 'app-explorer',
  imports: [FormsModule, LucideDynamicIcon, PriceChart, MovementAnalysis, AgentTimeline, DossierView, TracesView],
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
  progress = signal<AgentProgress[]>([]);
  error = signal('');
  selection = signal<ChartSelection>({ kind: 'session', date: '' });
  mode = signal<SelectionMode>('session');
  ticker = 'NVDA';
  sessionDate = '';
  rangeStart = '';
  rangeEnd = '';
  profile: Profile = 'amira';
  readonly personas = PERSONAS;
  readonly icons = ICONS;
  entered = signal(false);
  switcherOpen = signal(false);

  persona() { return personaOf(this.profile); }

  /** Trois vues : l'analyse (actes 1 à 3), le dossier de preuves et les traces des agents. */
  view = signal<'analyse' | 'dossier' | 'traces'>('analyse');
  readonly pages = [
    { id: 'analyse' as const, label: 'Analyse' },
    { id: 'dossier' as const, label: 'Dossier de preuves' },
    { id: 'traces' as const, label: 'Traces des agents' },
  ];
  readonly sections = [
    { id: 'acte1', label: 'La séance' },
    { id: 'acte2', label: 'Ce qui s’est passé' },
    { id: 'acte3', label: 'Pour toi' },
    { id: 'decisions', label: 'Décisions des agents' },
  ];
  activeSection = signal('acte1');

  openPage(id: 'analyse' | 'dossier' | 'traces') {
    this.view.set(id);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  /** Sélection modifiée sans analyse : on invite à cliquer sur « Exécuter l'analyse ». */
  stale = signal(false);
  private autoRun = false;

  /** Le menu de gauche fait défiler la page vers chaque acte (aucune page fictive). */
  goTo(id: string) {
    this.activeSection.set(id);
    const scroll = () => {
      const element = document.getElementById(id);
      if (element instanceof HTMLDetailsElement) element.open = true;
      element?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    if (this.view() !== 'analyse') {
      this.view.set('analyse');
      setTimeout(scroll, 50);
    } else {
      scroll();
    }
  }

  /** Nouvelle analyse : retour à la sélection de la séance. */
  newAnalysis() {
    this.goTo('acte1');
  }

  /** Bouton « Exécuter l'analyse » : relance les deux agents sur la sélection courante. */
  run() {
    this.analyzeCurrent();
  }

  available(id: string) {
    const result = this.result();
    if (id === 'acte1') return true;
    if (!result) return false;
    if (id === 'decisions') return !!(result.dossier?.agent_decisions?.length || result.impact.decisions?.length);
    if (id === 'traces') return !!result.trace?.length;
    return true;
  }

  aiMode() {
    const result = this.result();
    if (!result) return null;
    return result.event.mode === 'bedrock' || result.impact.mode === 'bedrock' ? 'GPT-6 Astra (Bedrock)' : 'Calcul local';
  }

  /** Simulation de connexion : aucun mot de passe, seul le profil fictif change. */
  enter(profile: Profile) {
    this.profile = profile;
    this.entered.set(true);
    this.analyzeCurrent();
  }

  switchProfile(profile: Profile) {
    this.switcherOpen.set(false);
    if (profile === this.profile) return;
    this.selectProfile(profile);
  }

  leave() {
    this.switcherOpen.set(false);
    this.clearPendingAnalysis();
    this.entered.set(false);
    this.view.set('analyse');
  }

  rangeInvalid() {
    const rows = this.rows();
    if (!rows.length || this.rangeStart === '' || this.rangeEnd === '') return false;
    const start = rows.findIndex(row => row.date === this.rangeStart);
    const end = rows.findIndex(row => row.date === this.rangeEnd);
    return start >= 0 && end >= 0 && start > end;
  }

  canAnalyze() {
    if (!this.rows().length) return false;
    if (this.mode() === 'session') {
      const rows = this.rows();
      return !!this.sessionDate && this.sessionDate !== rows[0]?.date;
    }
    return !!this.rangeStart && !!this.rangeEnd && !this.rangeInvalid();
  }

  constructor() {
    this.api.stocks().subscribe({
      next: ({ stocks }) => { this.stocks.set(stocks); this.load('NVDA', '2024-08-29'); },
      error: (error) => this.showError(error),
    });
  }

  load(ticker: string, date?: string, run = false) {
    this.autoRun = run;
    this.historyRequest?.unsubscribe();
    this.cancelAnalysis();
    this.error.set('');
    this.result.set(null);
    this.rows.set([]);
    this.rangeStart = '';
    this.rangeEnd = '';
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

  stockName() {
    return this.stocks().find(stock => stock.ticker === this.ticker)?.name ?? this.ticker;
  }

  setMode(mode: SelectionMode) {
    if (this.mode() === mode) return;
    this.mode.set(mode);
    this.error.set('');
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
    // Même séance, autre profil : on relance si une analyse est affichée (seul l'impact change).
    if (this.result() || this.busy()) this.analyzeCurrent();
    else this.stale.set(this.canAnalyze());
  }

  /** Les scénarios de démo lancent l'analyse ; un clic de sélection attend le bouton. */
  private maybeRun() {
    if (this.autoRun) {
      this.autoRun = false;
      this.analyzeCurrent();
    } else {
      this.stale.set(this.canAnalyze());
    }
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
    this.maybeRun();
  }

  private applyRange(startDate: string, endDate: string) {
    const rows = this.rows();
    const start = rows.findIndex(row => row.date === startDate);
    const end = rows.findIndex(row => row.date === endDate);
    if (start < 0 || end < 0) return;
    const [lo, hi] = start <= end ? [startDate, endDate] : [endDate, startDate];
    this.rangeStart = startDate;
    this.rangeEnd = endDate;
    this.clearPendingAnalysis();
    if (lo === hi) {
      this.mode.set('session');
      this.applySession(lo, true);
      return;
    }
    if (start > end) {
      this.error.set('La date de début doit précéder ou égaler la date de fin.');
      return;
    }
    this.selection.set({ kind: 'range', startDate: lo, endDate: hi });
    this.maybeRun();
  }

  analyzeCurrent() {
    if (!this.entered() || !this.canAnalyze()) return;
    if (this.mode() === 'range') {
      if (this.rangeStart === this.rangeEnd) {
        this.applySession(this.rangeStart, true);
        return;
      }
      this.requestAnalysis({ start_date: this.rangeStart, end_date: this.rangeEnd });
      return;
    }
    this.requestAnalysis({ date: this.sessionDate });
  }

  private requestAnalysis(selection: Record<string, string>) {
    this.clearPendingAnalysis();
    this.stale.set(false);
    this.error.set('');
    this.busy.set(true);
    this.analysisRequest = this.api.analyze({
      ...selection,
      ticker: this.ticker,
      profile: this.profile,
    }).subscribe({
      next: (message) => {
        if ('kind' in message) {
          this.progress.update(steps => {
            const index = steps.findIndex(step => step.agent === message.agent && step.action === message.action);
            return index < 0 ? [...steps, message] : steps.map((step, i) => i === index ? message : step);
          });
          return;
        }
        this.result.set(message);
        this.busy.set(false);
      },
      error: (error: Error) => {
        this.busy.set(false);
        this.error.set(error.message || 'Le service est indisponible.');
      },
    });
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
    this.progress.set([]);
    this.analysisRequest?.unsubscribe();
    this.analysisRequest = undefined;
  }

  private showError(error: HttpErrorResponse) {
    this.busy.set(false);
    this.error.set(error.error?.error ?? 'Le service est indisponible. Réessaie dans un instant.');
  }
}
