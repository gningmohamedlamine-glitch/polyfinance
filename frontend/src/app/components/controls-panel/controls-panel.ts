import { Component, computed, input } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';
import { ReportReveal } from '../../report-reveal';
import { ICONS } from '../../icons';
import { Controls } from '../../services/market-api';

/** Panneau du Contrôleur : les vérifications automatiques, visibles par l'utilisateur. */
@Component({
  selector: 'app-controls-panel',
  imports: [LucideDynamicIcon, ReportReveal],
  templateUrl: './controls-panel.html',
  styleUrl: './controls-panel.css',
})
export class ControlsPanel {
  controls = input.required<Controls>();
  readonly icons = ICONS;
  readonly statusIcon = { ok: ICONS.check, warn: ICONS.alert, fail: ICONS.cross, info: ICONS.info };
  readonly statusLabel = { ok: 'Respecté', warn: 'À signaler', fail: 'Enfreint', info: 'Information' };
  readonly verdictLabel = { ok: 'Tous les contrôles sont respectés', warn: 'Contrôles respectés, points signalés', fail: 'Au moins une règle est enfreinte' };
  counts = computed(() => {
    const list = this.controls().controls;
    return { ok: list.filter(c => c.status === 'ok').length, total: list.filter(c => c.status !== 'info').length };
  });
}
