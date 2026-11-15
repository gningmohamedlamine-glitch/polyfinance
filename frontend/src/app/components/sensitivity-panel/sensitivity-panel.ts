import { Component, input } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';
import { ICONS } from '../../icons';
import { Sensitivity } from '../../services/market-api';

/** Mise à l'épreuve : chaque conclusion recalculée avec une autre hypothèse (énoncé : sensibilité). */
@Component({
  selector: 'app-sensitivity-panel',
  imports: [LucideDynamicIcon],
  templateUrl: './sensitivity-panel.html',
  styleUrl: './sensitivity-panel.css',
})
export class SensitivityPanel {
  sensitivity = input.required<Sensitivity>();
  readonly icons = ICONS;
}
