import { Component, input } from '@angular/core';
import { PercentPipe } from '@angular/common';
import { LucideDynamicIcon } from '@lucide/angular';
import { ICONS } from '../../icons';
import { Esg } from '../../services/market-api';

/** Vérification ESG (profil de Mateo) : points d'attention et informations manquantes, jamais une note. */
@Component({
  selector: 'app-esg-panel',
  imports: [PercentPipe, LucideDynamicIcon],
  templateUrl: './esg-panel.html',
  styleUrl: './esg-panel.css',
})
export class EsgPanel {
  esg = input.required<Esg>();
  readonly icons = ICONS;
}
