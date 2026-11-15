import { DecimalPipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';
import { ReportReveal } from '../../report-reveal';
import { ICONS } from '../../icons';
import { Sensitivity, SensitivityChart } from '../../services/market-api';

/** Mise à l'épreuve : chaque conclusion recalculée avec une autre hypothèse (énoncé : sensibilité). */
@Component({
  selector: 'app-sensitivity-panel',
  imports: [DecimalPipe, LucideDynamicIcon, ReportReveal],
  templateUrl: './sensitivity-panel.html',
  styleUrl: './sensitivity-panel.css',
})
export class SensitivityPanel {
  sensitivity = input.required<Sensitivity>();
  readonly icons = ICONS;
  readonly checks = computed(() => this.sensitivity().checks.map(check => ({
    ...check,
    chart: check.chart && this.layoutChart(check.chart),
  })));

  private layoutChart(chart: SensitivityChart) {
    // Both measures share a scale, so the lengths can be compared across the card.
    const values = chart.measures.flatMap(measure => [...measure.values, measure.limit ?? 0]);
    const min = Math.min(0, ...values) * 1.08;
    const max = Math.max(0, ...values) * 1.08;
    const position = (value: number) => (value - min) / (max - min || 1) * 100;
    const zero = position(0);
    return {
      ...chart,
      zero,
      measures: chart.measures.map(measure => ({
        ...measure,
        marker: measure.limit === undefined ? null : position(measure.limit),
        bars: measure.values.map(value => ({
          value,
          start: Math.min(zero, position(value)),
          width: Math.abs(position(value) - zero),
        })),
      })),
    };
  }
}
