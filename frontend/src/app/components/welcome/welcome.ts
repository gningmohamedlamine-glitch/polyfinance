import { Component, output } from '@angular/core';
import { PercentPipe } from '@angular/common';
import { LucideDynamicIcon } from '@lucide/angular';
import { ICONS } from '../../icons';
import { Logo } from '../logo/logo';
import { PERSONAS } from '../../personas';
import { Profile } from '../../services/market-api';

/** Écran d'accueil : choix d'un profil fictif de l'énoncé. */
@Component({
  selector: 'app-welcome',
  imports: [PercentPipe, LucideDynamicIcon, Logo],
  templateUrl: './welcome.html',
  styleUrl: './welcome.css',
})
export class Welcome {
  readonly personas = PERSONAS;
  readonly icons = ICONS;
  /** Échelle des jauges : 60 % de volatilité = barre pleine. */
  readonly scale = 0.6;
  enter = output<Profile>();
}
