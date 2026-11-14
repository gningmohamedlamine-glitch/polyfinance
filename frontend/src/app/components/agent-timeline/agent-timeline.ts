import { Component, computed, input, signal } from '@angular/core';
import {
  LucideCalendarRange, LucideChartNoAxesCombined, LucideFileSearch, LucideUserRound,
  LucideCircleCheck, LucideSearch, LucideGlobe, LucideCalculator, LucideDatabase,
  LucideTrendingDown, LucideScale, LucideCheck, LucideCircleAlert, LucideDynamicIcon, LucideLoaderCircle,
} from '@lucide/angular';
import { AgentProgress } from '../../services/market-api';

type PipelineState = 'waiting' | 'running' | 'done' | 'interrupted';

@Component({
  selector: 'app-agent-timeline',
  imports: [LucideDynamicIcon],
  templateUrl: './agent-timeline.html',
  styleUrl: './agent-timeline.css',
})
export class AgentTimeline {
  steps = input.required<AgentProgress[]>();
  busy = input.required<boolean>();
  selectionLabel = input.required<string>();
  profileLabel = input.required<string>();
  hasResult = input.required<boolean>();
  icons = {
    selection: LucideCalendarRange.icon, event: LucideChartNoAxesCombined.icon, dossier: LucideFileSearch.icon,
    impact: LucideUserRound.icon, output: LucideCircleCheck.icon, check: LucideCheck.icon,
    warning: LucideCircleAlert.icon, tool: LucideCalculator.icon, spinner: LucideLoaderCircle.icon,
  };

  toolIcons: Partial<Record<string, typeof LucideCalculator.icon>> = {
    compare_market: LucideChartNoAxesCombined.icon,
    find_notable_sessions: LucideCalendarRange.icon,
    search_publications: LucideSearch.icon,
    sec_edgar: LucideFileSearch.icon,
    web_search: LucideGlobe.icon,
    cached_dossier: LucideDatabase.icon,
    max_drawdown_cad: LucideTrendingDown.icon,
    direct_weight: LucideScale.icon,
  };

  labels: Partial<Record<string, string>> = {
    compare_market: 'Comparer le titre à SPY et QQQ',
    find_notable_sessions: 'Repérer les séances marquantes',
    search_publications: 'Rechercher les publications',
    sec_edgar: 'Consulter les dépôts SEC EDGAR',
    web_search: 'Chercher des pistes sur le web',
    cached_dossier: 'Réutiliser le dossier de cette période',
    validate_dossier: 'Vérifier le dossier avant sa transmission',
    synthesize: 'Rédiger la synthèse',
    calculate_profile_impact: 'Calculer l’impact pour ton profil',
    position_value_cad: 'Calculer la variation en CAD',
    max_drawdown_cad: 'Mesurer la baisse maximale',
    direct_weight: 'Comparer le poids avant et après l’achat',
    exclusion_evidence: 'Vérifier les preuves liées aux exclusions',
  };

  readonly nodes = [
    { id: 'selection', label: 'Sélection' },
    { id: 'event', label: 'Marché' },
    { id: 'dossier', label: 'Dossier' },
    { id: 'impact', label: 'Impact' },
    { id: 'output', label: 'Résultat' },
  ] as const;

  readonly expanded = signal<(typeof this.nodes)[number]['id'] | null>(null);
  readonly market = computed(() => this.stage('event'));
  readonly impact = computed(() => this.stage('impact'));

  readonly nodeStates = computed<Record<(typeof this.nodes)[number]['id'], PipelineState>>(() => ({
    selection: 'done',
    event: this.state(this.market()),
    dossier: this.market()?.status === 'done' ? 'done' : 'waiting',
    impact: this.state(this.impact()),
    output: this.hasResult() ? 'done' : 'waiting',
  }));

  readonly activity = computed(() => {
    if (this.hasResult()) return 'Analyse terminée';
    if (!this.busy()) return 'Analyse interrompue';

    const agent = this.impact()?.status === 'running' ? 'impact' : 'event';
    const runningTool = this.actions(agent).find(step => step.status === 'running');
    if (runningTool) return this.labels[runningTool.action] ?? runningTool.action;
    if (this.impact()?.status === 'running') return 'Agent d’impact en cours';
    if (this.market()?.status === 'running') return 'Agent marché en cours';
    return 'Analyse en cours';
  });

  readonly stateLabels: Record<PipelineState, string> = {
    waiting: 'En attente',
    running: 'En cours',
    done: 'Terminé',
    interrupted: 'Interrompu',
  };

  toggle(id: (typeof this.nodes)[number]['id']) {
    this.expanded.update(current => current === id ? null : id);
  }

  private state(step?: AgentProgress): PipelineState {
    if (step?.status === 'done') return 'done';
    if (step?.status === 'running') return this.busy() ? 'running' : 'interrupted';
    return 'waiting';
  }

  stageStatus(step?: AgentProgress) {
    if (step?.status === 'done') {
      const mode = step.mode === 'bedrock' ? 'Bedrock' : 'Calcul local';
      const duration = step.duration_ms == null
        ? ''
        : step.duration_ms < 1000
          ? ` · ${step.duration_ms} ms`
          : ` · ${(step.duration_ms / 1000).toLocaleString('fr-CA', { maximumFractionDigits: 1 })} s`;
      return `Terminé · ${mode}${duration}`;
    }
    if (step?.status === 'running') return this.busy() ? 'En cours' : 'Interrompu';
    return this.busy() ? 'En attente' : 'Non exécuté';
  }

  toolStatus(step: AgentProgress) {
    if (step.status === 'unavailable') {
      switch (step.reason) {
        case 'timeout': return 'Délai dépassé';
        case 'not_executed': return 'Recherche non exécutée';
        case 'invalid_response': return 'Réponse inexploitable';
        default: return 'Indisponible';
      }
    }
    if (step.status === 'running') return this.busy() ? 'En cours' : 'Interrompu';
    if (step.count != null) return step.count === 1 ? '1 résultat' : step.count + ' résultats';
    return 'Terminé';
  }

  stage(id: AgentProgress['agent']) {
    return this.steps().find(step => step.agent === id && step.action === 'stage');
  }

  actions(id: AgentProgress['agent']) {
    return this.steps().filter(step => step.agent === id && step.action !== 'stage');
  }
}
