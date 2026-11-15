import { CurrencyPipe, DatePipe, DecimalPipe, NgTemplateOutlet, PercentPipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';
import { ReportReveal } from '../../report-reveal';
import { LucideDynamicIcon } from '@lucide/angular';
import { ICONS } from '../../icons';
import { EsgPanel } from '../esg-panel/esg-panel';
import { InfoTip } from '../info-tip/info-tip';
import { MarketChange } from '../market-change/market-change';
import { Persona } from '../../personas';
import { Analysis } from '../../services/market-api';

export type TextPart = { text: string; kind?: 'link' | 'code' | 'strong' | 'em'; href?: string };

@Component({
  selector: 'app-movement-analysis',
  imports: [InfoTip, CurrencyPipe, DatePipe, DecimalPipe, NgTemplateOutlet, PercentPipe, LucideDynamicIcon, EsgPanel, MarketChange, ReportReveal],
  templateUrl: './movement-analysis.html',
  styleUrl: './movement-analysis.css',
})
export class MovementAnalysis {
  analysis = input.required<Analysis>();
  view = input<'result' | 'details'>('result');
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
    const spark = this.compareSpark(this.analysis().movement.path ?? [], rows['QQQ']?.path ?? []);
    return ['SPY', 'QQQ', 'XLK']
      .filter(symbol => rows[symbol]?.return != null)
      .map(symbol => ({
        symbol,
        label: symbol === 'XLK' ? 'Secteur techno' : rows[symbol].name,
        ret: rows[symbol].return!,
        spark: symbol === 'QQQ' ? spark : null,
      }));
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

  /** Deux fenêtres distinctes : la sélection (simulation) et les 12 mois avant sa fin (risque, ESG). */
  windows = computed(() => {
    const selection = this.analysis().dossier?.selection;
    if (!selection) return null;
    const risk = this.analysis().impact.coherence?.risk;
    return {
      selection: { start: selection.start_close_date, end: selection.end_close_date },
      risk: risk?.status === 'ok' && risk.start_date && risk.end_date ? { start: risk.start_date, end: risk.end_date } : null,
    };
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
    const lines = text.split(/\r?\n/).map(line => line.trim().replace(/^(?:[-*•]|\d+[.)])\s+/, '')).filter(Boolean);
    // Texte local en un seul paragraphe : une phrase par puce pour rester lisible.
    if (lines.length === 1 && lines[0].length > 220) {
      return lines[0].split(/(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Ý«])/).filter(Boolean);
    }
    return lines;
  }

  bulletLines(text: string): { parts: TextPart[] }[] {
    return this.bullets(text)
      .map(line => this.readable(line))
      .filter(line => line.length > 0)
      .map(line => ({ parts: this.parseInlineParts(line) }));
  }

  /** Le modèle cite parfois des champs ou des outils. On les dit en français, ou on les retire. */
  readable(text: string): string {
    const phrases: Record<string, string> = {
      'source_origin=official': 'source officielle',
      'source_origin=other': 'autre source',
      'excerpt_status=verified': 'extrait vérifié',
      'excerpt_status=no_excerpt': 'sans extrait vérifié',
      'excerpt_status=mismatch': 'extrait non retrouvé',
      'excerpt_status=source_missing': 'source introuvable',
      'excerpt_status=not_checked': 'extrait non vérifié',
      'temporal_status=before_close': 'avant la clôture',
      'temporal_status=after_close': 'après la clôture',
      'temporal_status=date_only_prior': 'date antérieure',
      'temporal_status=same_day_time_unknown': 'heure inconnue',
      'temporal_status=unknown_timezone': 'fuseau inconnu',
      'temporal_status=invalid_timestamp': 'horodatage invalide',
      'temporal_status=missing_date': 'date manquante',
      'page_status=retrieved': 'page consultée',
      'page_status=unavailable': 'page indisponible',
      'page_status=not_checked': 'page non consultée',
      'eligible_for_explanation=true': 'peut expliquer le mouvement',
      'eligible_for_explanation=false': 'ne peut pas expliquer le mouvement',
    };
    let out = text.replace(/`([^`\n]+)`/g, ' $1 ');
    out = out.replace(/\b([a-z][a-z0-9_]*)\s*=\s*([A-Za-z0-9_]+)/g, (full, key: string, value: string) => {
      return phrases[`${key}=${value}`] ?? '';
    });
    out = out
      .replace(/\b(profile_calculations|verify_profile_coherence|position_value_cad|direct_weight|esg_screen|search_catalog|search_web|search_sec_filings)\b/g, ' ')
      .replace(/\b[a-z]+(?:_[a-z0-9]+)+\b/g, ' ')
      .replace(/\(\s*\)/g, '')
      .replace(/\s+([,.;:])/g, '$1')
      .replace(/([:;])\s*([,.;])/g, '$2')
      .replace(/(\s*,){2,}/g, ',')
      .replace(/\s{2,}/g, ' ')
      .replace(/^[,;:\s]+|[,;:\s]+$/g, '')
      .trim();
    if (!out) return '';
    return out.charAt(0).toUpperCase() + out.slice(1);
  }

  /** Deux tracés sur la même échelle : le titre et le Nasdaq-100. */
  private compareSpark(stock: number[], market: number[]) {
    if (stock.length < 2 || market.length !== stock.length) return null;
    const all = [...stock, ...market];
    const min = Math.min(...all);
    const max = Math.max(...all);
    const span = max - min || 1;
    const w = 112;
    const h = 36;
    const line = (values: number[]) => values.map((value, index) => {
      const x = (index / (values.length - 1)) * w;
      const y = h - 2 - ((value - min) / span) * (h - 4);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return { w, h, stock: line(stock), market: line(market) };
  }

  /** Inline marks the model writes: `code`, **bold**, *italic*, and [label](https://…). */
  parseInlineParts(line: string): TextPart[] {
    const parts: TextPart[] = [];
    const re = /(`([^`\n]+)`)|(\*\*([^*\n]+)\*\*)|(\*([^*\n]+)\*)|(\[([^\]]+)\]\((https?:\/\/[^)\s]+)\))/g;
    let last = 0;
    let match: RegExpExecArray | null;
    while ((match = re.exec(line)) !== null) {
      if (match.index > last) {
        parts.push({ text: line.slice(last, match.index) });
      }
      if (match[2] != null) parts.push({ text: match[2], kind: 'code' });
      else if (match[4] != null) parts.push({ text: match[4], kind: 'strong' });
      else if (match[6] != null) parts.push({ text: match[6], kind: 'em' });
      else if (match[8] != null) parts.push({ text: match[8], kind: 'link', href: match[9] });
      last = match.index + match[0].length;
    }
    if (last < line.length) {
      parts.push({ text: line.slice(last) });
    }
    return parts.length ? parts : [{ text: line }];
  }
}
