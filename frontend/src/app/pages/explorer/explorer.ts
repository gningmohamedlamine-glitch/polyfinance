import { ControlsPanel } from '../../components/controls-panel/controls-panel';
import { SensitivityPanel } from '../../components/sensitivity-panel/sensitivity-panel';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DatePipe } from '@angular/common';
import { Subscription } from 'rxjs';
import { AgentTimeline } from '../../components/agent-timeline/agent-timeline';
import { DossierView } from '../../components/dossier-view/dossier-view';
import { TracesView } from '../../components/traces-view/traces-view';
import { Welcome } from '../../components/welcome/welcome';
import { Logo } from '../../components/logo/logo';
import { MovementAnalysis } from '../../components/movement-analysis/movement-analysis';
import { ChartSelection, ChartStyle, HORIZONS, Horizon, PriceChart } from '../../components/price-chart/price-chart';
import { LucideDynamicIcon } from '@lucide/angular';
import { ICONS } from '../../icons';
import { PERSONAS, personaOf } from '../../personas';
import { AgentProgress, Analysis, MarketApi, Price, Profile, Stock } from '../../services/market-api';

type SelectionMode = 'session' | 'range';

/** Sélection gardée pour l'onglet (idée d'Adam) : un rechargement ne perd ni le profil ni les dates. */
const STORAGE_KEY = 'alphaforge.explorer.v2';
type SavedExplorer = {
  entered: boolean; ticker: string; profile: Profile; mode: 'session' | 'range';
  sessionDate?: string; rangeStart?: string; rangeEnd?: string;
};

@Component({
  selector: 'app-explorer',
  imports: [FormsModule, DatePipe, LucideDynamicIcon, PriceChart, MovementAnalysis, AgentTimeline, DossierView, TracesView, Welcome, Logo, ControlsPanel, SensitivityPanel],
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
  readonly horizons = HORIZONS;
  chartHorizon = signal<Horizon>('1M');
  chartStyle = signal<ChartStyle>('line');

  sourceCount() { return this.result()?.event.sources.length ?? 0; }
  entered = signal(false);
  switcherOpen = signal(false);

  persona() { return personaOf(this.profile); }

  readonly pages = [
    { id: 'analyse', label: 'Configurer l’analyse', icon: this.icons.analyse },
    { id: 'resultat', label: 'Résultat', icon: this.icons.doc },
    { id: 'dossier', label: 'Dossier de preuves', icon: this.icons.dossier },
    { id: 'controles', label: 'Contrôles et sensibilité', icon: this.icons.shield },
    { id: 'traces', label: 'Traces des agents', icon: this.icons.traces },
  ] as const;
  view = signal<(typeof this.pages)[number]['id']>('analyse');

  pageTitle() {
    return this.pages.find(page => page.id === this.view())?.label;
  }

  openPage(id: (typeof this.pages)[number]['id']) {
    this.view.set(id);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  /** Sélection modifiée sans analyse : on invite à cliquer sur « Exécuter l'analyse ». */
  stale = signal(false);
  private autoRun = false;

  newAnalysis() {
    this.view.set('analyse');
    requestAnimationFrame(() => {
      document.getElementById('stock-picker-title')?.focus({ preventScroll: true });
      document.getElementById('stock-picker')?.scrollIntoView({ block: 'start' });
    });
  }

  run() {
    this.view.set('analyse');
    this.analyzeCurrent();
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
    this.persistSelection();
    // Rien ne part tout seul : seul le bouton « Exécuter l'analyse » lance les agents.
    this.stale.set(this.canAnalyze());
  }

  switchProfile(profile: Profile) {
    this.switcherOpen.set(false);
    if (profile === this.profile) return;
    this.selectProfile(profile);
  }

  leave() {
    this.writeSaved({ entered: false });
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
      next: ({ stocks }) => {
        this.stocks.set(stocks);
        const saved = this.readSaved();
        if (saved) {
          this.profile = saved.profile;
          this.entered.set(saved.entered);
        }
        this.load(saved?.ticker ?? 'NVDA', saved ? undefined : '2024-08-29', false, !!saved);
      },
      error: (error) => this.showError(error),
    });
  }

  load(ticker: string, date?: string, run = false, restore = false) {
    // Les scénarios préparent la sélection ; l'analyse attend le bouton.
    this.autoRun = false;
    void run;
    this.historyRequest?.unsubscribe();
    this.cancelAnalysis();
    this.busy.set(false);
    this.error.set('');
    // Le dernier résultat reste affiché jusqu'à la prochaine exécution (signalé comme précédent).
    this.rows.set([]);
    this.rangeStart = '';
    this.rangeEnd = '';
    this.mode.set('session');
    this.ticker = ticker;
    this.historyRequest = this.api.history(ticker).subscribe({
      next: ({ rows }) => {
        this.rows.set(rows);
        const saved = restore ? this.readSaved() : null;
        if (saved?.ticker === ticker && saved.mode === 'range' && saved.rangeStart && saved.rangeEnd) {
          this.mode.set('range');
          this.applyRange(saved.rangeStart, saved.rangeEnd);
          return;
        }
        const preferred = date ?? (saved?.ticker === ticker ? saved.sessionDate : undefined);
        this.applySession(this.pickSessionDate(rows, preferred), true);
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

  /** Bornes affichées dans les calendriers : une séance s'affiche « de la veille à ce jour ». */
  fromDate() {
    if (this.mode() === 'range') return this.rangeStart;
    const rows = this.rows();
    const i = rows.findIndex(row => row.date === this.sessionDate);
    return i > 0 ? rows[i - 1].date : '';
  }

  toDate() {
    return this.mode() === 'range' ? this.rangeEnd : this.sessionDate;
  }

  minDate() { return this.rows()[0]?.date ?? ''; }
  maxDate() { return this.rows().at(-1)?.date ?? ''; }

  /** Ramène une date de calendrier (week-end, férié) à la dernière séance connue. */
  private snapIndex(date: string) {
    const rows = this.rows();
    let index = 0;
    for (let i = 0; i < rows.length; i++) if (rows[i].date <= date) index = i;
    return index;
  }

  onFromChange(value: string) {
    if (!value || !this.rows().length) return;
    const from = this.snapIndex(value);
    let to = this.snapIndex(this.toDate() || this.maxDate());
    if (from >= to) to = Math.min(from + 1, this.rows().length - 1);
    this.setBounds(Math.min(from, to - 1), to);
  }

  onToChange(value: string) {
    if (!value || !this.rows().length) return;
    const to = Math.max(this.snapIndex(value), 1);
    let from = this.snapIndex(this.fromDate() || this.minDate());
    if (from >= to) from = to - 1;
    this.setBounds(from, to);
  }

  /** Une seule séance d'écart = analyse d'une journée ; sinon, une période. */
  private setBounds(from: number, to: number) {
    const rows = this.rows();
    this.error.set('');
    if (to - from === 1) {
      this.mode.set('session');
      this.applySession(rows[to].date, true);
      return;
    }
    this.mode.set('range');
    this.applyRange(rows[from].date, rows[to].date);
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
    const rows = this.rows();
    const from = rows.findIndex(row => row.date === selection.startDate);
    const to = rows.findIndex(row => row.date === selection.endDate);
    if (from < 0 || to <= from) return;
    this.setBounds(from, to);
  }

  selectProfile(profile: Profile) {
    this.profile = profile;
    this.view.set('analyse');
    this.persistSelection();
    // Autre profil : l'analyse attend le bouton, comme toute autre modification.
    // Le résultat dépend du profil : on ne laisse jamais l'analyse de Robert sous le nom d'Amira.
    this.cancelAnalysis();
    this.busy.set(false);
    this.result.set(null);
    this.stale.set(this.canAnalyze());
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
    this.persistSelection();
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
    this.persistSelection();
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
        this.openPage('resultat');
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
    this.busy.set(false);
  }

  /** Libellé de la sélection du résultat affiché, pour signaler qu'il est antérieur. */
  resultLabel() {
    const selection = this.result()?.dossier?.selection;
    if (!selection) return '';
    const end = selection.end_close_date;
    return `${selection.ticker} · ${selection.applied === 'period' ? selection.start_close_date + ' → ' + end : end}`;
  }

  private cancelAnalysis() {
    this.progress.set([]);
    this.analysisRequest?.unsubscribe();
    this.analysisRequest = undefined;
  }

  private showError(error: HttpErrorResponse | Error) {
    this.busy.set(false);
    // Les erreurs du flux (ex. modèle indisponible) arrivent avec leur raison exacte.
    const message = error instanceof HttpErrorResponse ? error.error?.error : error?.message;
    this.error.set(message || 'Le service est indisponible. Réessaie dans un instant.');
  }

  private persistSelection() {
    if (!this.rows().length) return;
    this.writeSaved({
      entered: this.entered(), ticker: this.ticker, profile: this.profile, mode: this.mode(),
      sessionDate: this.sessionDate, rangeStart: this.rangeStart, rangeEnd: this.rangeEnd,
    });
  }

  private writeSaved(patch: Partial<SavedExplorer>) {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ ...this.readSaved(), ...patch }));
    } catch { /* navigation privée */ }
  }

  private readSaved(): SavedExplorer | null {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) as SavedExplorer : null;
    } catch {
      return null;
    }
  }
}
