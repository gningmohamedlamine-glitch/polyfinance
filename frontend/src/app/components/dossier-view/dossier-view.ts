import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';
import { ReportReveal } from '../../report-reveal';
import { LucideDynamicIcon } from '@lucide/angular';
import { ICONS } from '../../icons';
import { Analysis } from '../../services/market-api';
import { MarketChange } from '../market-change/market-change';

/** Dossier de preuves : tout ce que l'Enquêteur a trouvé, vérifié ou écarté, avec ses limites. */
import { InfoTip } from '../info-tip/info-tip';

@Component({
  selector: 'app-dossier-view',
  imports: [InfoTip, DatePipe, DecimalPipe, LucideDynamicIcon, MarketChange, ReportReveal],
  templateUrl: './dossier-view.html',
  styleUrl: './dossier-view.css',
})
export class DossierView {
  analysis = input.required<Analysis>();
  readonly icons = ICONS;

  sources = computed(() => this.analysis().event.sources);
  leads = computed(() => this.analysis().dossier?.coverage.web_leads ?? []);
  verified = computed(() => this.sources().filter(s => s.excerpt_status === 'verified').length);
  corroborated = computed(() => this.leads().filter(l => (l.corroboration ?? 1) >= 2).length);
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
  /** Mouvement surtout expliqué par l'effet attendu du marché (bêta × indice). */
  marketDriven = computed(() => {
    const m = this.analysis().dossier?.returns?.market_model;
    return !!m && m.status === 'ok' && Math.abs(m.expected_return ?? 0) > Math.abs(m.residual ?? 0);
  });
  /** Ce qui s'est passé avec la recherche web, dit en clair. */
  webStatus = computed(() => {
    const coverage = this.analysis().dossier?.coverage;
    const reason = coverage?.web_search_reason;
    if (coverage?.nova_grounding === 'budget_elapsed') return 'Les résultats de recherche disponibles sont affichés. Nova n’a pas répondu dans le délai prévu.';
    if (coverage?.nova_grounding && ['busy', 'timeout', 'unavailable', 'not_executed', 'invalid_response'].includes(coverage.nova_grounding)) {
      return 'Recherche partielle : Nova n’a renvoyé aucun résultat exploitable. Les autres sources disponibles sont affichées.';
    }
    switch (coverage?.web_search) {
      case 'disabled': return 'Recherche web désactivée (MARKET_WEB_SEARCH ≠ 1).';
      case 'not_requested': return 'Recherche web non lancée par l’Enquêteur.';
      case 'unavailable': return `Recherche web indisponible${reason ? ' (' + reason + ')' : ''}.`;
      case 'no_dated_sources': return 'Recherche web lancée : aucun article daté dans la fenêtre.';
      case 'no_relevant_sources': return 'Recherche web lancée : articles trouvés, aucun pertinent pour ce mouvement.';
      case 'not_needed': return 'Le catalogue vérifié couvre les séances clés de la sélection.';
      default: return coverage?.web_search ? `Recherche web : ${coverage.web_search}.` : '';
    }
  });
  status = computed(() => {
    if (!this.sources().length && !this.leads().length) {
      return this.marketDriven()
        ? { label: 'Mouvement surtout porté par le marché', tone: 'neutral' }
        : { label: 'Cause indéterminée', tone: 'neutral' };
    }
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
      case 'verified': return 'Extrait vérifié dans la source';
      case 'mismatch': return 'Extrait introuvable dans la source';
      case 'source_missing': return 'Source non téléchargée : extrait non vérifié';
      default: return 'Publication datée, sans extrait';
    }
  }
}
