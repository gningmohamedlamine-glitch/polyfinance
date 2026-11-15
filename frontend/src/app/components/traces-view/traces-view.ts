import { DecimalPipe, JsonPipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';
import { AgentProgress, Analysis } from '../../services/market-api';

const STEP_FOR_TOOL: Record<string, string> = {
  search_catalog: 'search_publications', search_sec_filings: 'sec_edgar', search_web: 'web_search',
};
const LABELS: Record<string, string> = {
  compare_market: 'Comparer au marché et calculer le bêta', find_notable_sessions: 'Repérer les séances marquantes',
  search_publications: 'Chercher dans le catalogue', search_catalog: 'Chercher dans le catalogue',
  sec_edgar: 'Chercher sur SEC EDGAR', search_sec_filings: 'Chercher sur SEC EDGAR',
  web_search: 'Chercher sur le web (Nova)', search_web: 'Chercher sur le web (Nova)',
  investigate: 'Raisonnement de l’Enquêteur', advise: 'Raisonnement du Conseiller', synthesize: 'Rédiger la synthèse',
  validate_dossier: 'Vérifier le dossier', cached_dossier: 'Réutiliser le dossier',
  verify_profile_coherence: 'Vérifier la cohérence du profil', profile_coherence: 'Vérifier la cohérence du profil',
  position_value_cad: 'Chiffrer la position en CAD', direct_weight: 'Mesurer le poids', exclusion_evidence: 'Vérifier les preuves ESG',
  calculate_profile_impact: 'Calculer l’impact du profil',
};

/** Traces des agents : durées mesurées, appels au modèle, entrées et sorties de chaque outil. */
@Component({
  selector: 'app-traces-view',
  imports: [DecimalPipe, JsonPipe],
  templateUrl: './traces-view.html',
  styleUrl: './traces-view.css',
})
export class TracesView {
  analysis = input.required<Analysis>();
  steps = input.required<AgentProgress[]>();

  label = (name: string) => LABELS[name] ?? name;

  total = computed(() => this.steps().filter(s => s.action === 'stage').reduce((sum, s) => sum + (s.duration_ms ?? 0), 0));
  usage = computed(() => {
    const parts = [this.analysis().dossier?.usage, this.analysis().impact.usage].filter(Boolean);
    return {
      calls: parts.reduce((n, u) => n + (u!.model_calls ?? 0), 0),
      input: parts.reduce((n, u) => n + (u!.input_tokens ?? 0), 0),
      output: parts.reduce((n, u) => n + (u!.output_tokens ?? 0), 0),
      model: parts.find(u => u!.model)?.model ?? null,
    };
  });
  bedrock = computed(() => this.analysis().event.mode === 'bedrock' || this.analysis().impact.mode === 'bedrock');

  /** Étapes mesurées (hors étapes globales), pour la barre de répartition du temps. */
  timed = computed(() => {
    const rows = this.steps().filter(s => s.action !== 'stage' && s.status !== 'running' && (s.duration_ms ?? 0) > 0);
    const sum = rows.reduce((n, s) => n + (s.duration_ms ?? 0), 0) || 1;
    return rows.map((s, i) => ({ ...s, share: (s.duration_ms ?? 0) / sum, hue: i % 6 }));
  });

  journal = computed(() => {
    const decisions = [...(this.analysis().dossier?.agent_decisions ?? []), ...(this.analysis().impact.decisions ?? [])];
    return decisions.map(d => ({
      ...d,
      duration: this.steps().find(s => s.agent === d.agent && s.action === (STEP_FOR_TOOL[d.tool] ?? d.tool))?.duration_ms ?? null,
    }));
  });
}
