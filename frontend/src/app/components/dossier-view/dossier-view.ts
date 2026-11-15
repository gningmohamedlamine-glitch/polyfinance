import { DecimalPipe, PercentPipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';
import { Analysis } from '../../services/market-api';

/** Dossier de preuves : tout ce que l'Enquêteur a trouvé, vérifié ou écarté, avec ses limites. */
@Component({
  selector: 'app-dossier-view',
  imports: [DecimalPipe, PercentPipe],
  templateUrl: './dossier-view.html',
  styleUrl: './dossier-view.css',
})
export class DossierView {
  analysis = input.required<Analysis>();

  sources = computed(() => this.analysis().event.sources);
  leads = computed(() => this.analysis().dossier?.coverage.web_leads ?? []);
  verified = computed(() => this.sources().filter(s => s.excerpt_status === 'verified').length);
  unexplained = computed(() => this.analysis().dossier?.coverage.sessions_unexplained ?? []);
  decisions = computed(() => (this.analysis().dossier?.agent_decisions ?? []));
  limits = computed(() => {
    const limits = this.analysis().dossier?.limits ?? {};
    const labels: Record<string, string> = {
      causality: 'Causalité', direction: 'Sens du mouvement', excerpts: 'Extraits', figures_source: 'Origine des chiffres',
      verified_events_source: 'Sources consultées', max_tool_calls: 'Appels d’outils maximum',
    };
    return Object.entries(limits).map(([key, value]) => ({
      label: labels[key] ?? key,
      value: key === 'figures_source' && value === 'python' ? 'Calculés en Python, jamais par le modèle' : String(value),
    }));
  });
  status = computed(() => {
    if (!this.sources().length && !this.leads().length) return { label: 'Cause indéterminée', tone: 'neutral' };
    if (this.verified()) return { label: 'Extraits vérifiés', tone: 'ok' };
    return { label: 'Sources datées, extraits à vérifier', tone: 'warn' };
  });
  model = computed(() => this.analysis().dossier?.returns?.market_model);
  selection = computed(() => this.analysis().dossier?.selection);

  toolLabel(tool: string) {
    return ({ search_catalog: 'Chercher dans le catalogue vérifié', search_sec_filings: 'Chercher les dépôts 8-K sur SEC EDGAR',
              search_web: 'Chercher des pistes sur le web' } as Record<string, string>)[tool] ?? tool;
  }

  statusLabel(status?: string) {
    switch (status) {
      case 'verified': return '✓ Extrait vérifié dans la source';
      case 'mismatch': return '✕ Extrait introuvable dans la source';
      case 'source_missing': return 'Source non téléchargée : extrait non vérifié';
      default: return 'Publication datée, sans extrait';
    }
  }
}
