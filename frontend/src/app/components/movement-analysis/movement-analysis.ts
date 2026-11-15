import { CurrencyPipe, DecimalPipe, PercentPipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';
import { ReportReveal } from '../../report-reveal';
import { LucideDynamicIcon } from '@lucide/angular';
import { ICONS } from '../../icons';
import { EsgPanel } from '../esg-panel/esg-panel';
import { MarketChange } from '../market-change/market-change';
import { Persona } from '../../personas';
import { Analysis } from '../../services/market-api';

export type TextPart = { text: string; href?: string };

import { InfoTip } from '../info-tip/info-tip';

@Component({
  selector: 'app-movement-analysis',
  imports: [InfoTip, CurrencyPipe, DecimalPipe, PercentPipe, LucideDynamicIcon, EsgPanel, MarketChange, ReportReveal],
  templateUrl: './movement-analysis.html',
  styleUrl: './movement-analysis.css',
})
export class MovementAnalysis {
  analysis = input.required<Analysis>();
  persona = input.required<Persona>();
  readonly icons = ICONS;

  /** Décomposition : mouvement attendu vu la sensibilité au marché (bêta) contre part propre au titre. */
  decomposition = computed(() => {
    const model = this.analysis().dossier?.returns?.market_model;
    if (!model || model.status !== 'ok' || model.expected_return == null || model.residual_pp == null) return null;
    const market = model.expected_return * 100;
    const own = model.residual_pp;
    const total = Math.abs(market) + Math.abs(own) || 1;
    return {
      beta: model.beta ?? null,
      market,
      own,
      marketShare: Math.abs(market) / total,
      ownShare: Math.abs(own) / total,
      ownDominant: Math.abs(own) >= Math.abs(market),
    };
  });

  benchmarks = computed(() => {
    const rows = this.analysis().movement.benchmarks;
    return ['SPY', 'QQQ', 'XLK']
      .filter(symbol => rows[symbol]?.return != null)
      .map(symbol => ({ symbol, label: symbol === 'XLK' ? 'Secteur techno' : rows[symbol].name, ret: rows[symbol].return! }));
  });

  rules = computed(() => {
    const coherence = this.analysis().impact.coherence;
    if (!coherence || coherence.risk.status !== 'ok') return [];
    const vol = coherence.risk.annual_volatility ?? 0;
    const drawdown = coherence.risk.max_drawdown ?? 0;
    return [
      { title: 'Volatilité sur 12 mois', info: 'volatility' as const, value: vol, limit: coherence.limits.annual_volatility,
        breach: vol > coherence.limits.annual_volatility, fill: Math.min(vol / Math.max(coherence.limits.annual_volatility * 2, vol), 1),
        mark: Math.min(coherence.limits.annual_volatility / Math.max(coherence.limits.annual_volatility * 2, vol), 1) },
      { title: 'Pire baisse sur 12 mois', info: 'drawdown' as const, value: drawdown, limit: coherence.limits.max_drawdown,
        breach: drawdown < coherence.limits.max_drawdown, fill: Math.min(Math.abs(drawdown) / Math.max(Math.abs(coherence.limits.max_drawdown) * 2, Math.abs(drawdown)), 1),
        mark: Math.min(Math.abs(coherence.limits.max_drawdown) / Math.max(Math.abs(coherence.limits.max_drawdown) * 2, Math.abs(drawdown)), 1) },
      // Amira : part de technologie du portefeuille fictif après l'achat (énoncé : ne pas miser que sur la tech).
      ...(coherence.sector && coherence.limits.max_sector_weight ? [{
        title: 'Part techno après l’achat', info: 'tech' as const, value: coherence.sector.after, limit: coherence.limits.max_sector_weight,
        breach: coherence.sector.after > coherence.limits.max_sector_weight, fill: coherence.sector.after,
        mark: coherence.limits.max_sector_weight }] : []),
    ];
  });

  /** Même rendement en CAD appliqué à trois tailles de position fictives (aucune recommandation). */
  exposures = computed(() => {
    const cad = this.analysis().movement.cad_return;
    if (cad == null) return [];
    return [10_000, 50_000, 100_000].map(amount => ({ amount, change: amount * cad }));
  });

  /** Métriques non déjà montrées dans les cartes de règles ou les expositions. */
  extraMetrics = computed(() => this.analysis().impact.metrics.filter(metric =>
    !['Volatilité annuelle (12 mois)', 'Variation de la position'].includes(metric.label)
    && !metric.label.startsWith('Rendement 12 mois') && !metric.label.startsWith('Volatilité 12 mois (ESGV')
    && !metric.label.startsWith('Part techno')));

  bullets(text: string) {
    const lines = text.split(/\r?\n/).map(line => line.trim().replace(/^(?:[-*•]|\d+[.)])\s+/, '').replaceAll('**', '')).filter(Boolean);
    // Texte local en un seul paragraphe : une phrase par puce pour rester lisible.
    if (lines.length === 1 && lines[0].length > 220) {
      return lines[0].split(/(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Ý«])/).filter(Boolean);
    }
    return lines;
  }

  bulletLines(text: string): { parts: TextPart[] }[] {
    return this.bullets(text).map(line => ({ parts: this.parseInlineParts(line) }));
  }

  parseInlineParts(line: string): TextPart[] {
    const parts: TextPart[] = [];
    const re = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g;
    let last = 0;
    let match: RegExpExecArray | null;
    while ((match = re.exec(line)) !== null) {
      if (match.index > last) {
        parts.push({ text: line.slice(last, match.index) });
      }
      parts.push({ text: match[1], href: match[2] });
      last = match.index + match[0].length;
    }
    if (last < line.length) {
      parts.push({ text: line.slice(last) });
    }
    return parts.length ? parts : [{ text: line }];
  }
}
