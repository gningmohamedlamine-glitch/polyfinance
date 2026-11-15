import { Component, computed, input } from '@angular/core';
import { LucideDynamicIcon, LucideInfo } from '@lucide/angular';
import { GLOSSARY, GlossaryKey } from './glossary';

let nextId = 0;

/** Petite icône « i » : explication au survol ou au focus clavier (accessible au lecteur d'écran). */
@Component({
  selector: 'app-info',
  imports: [LucideDynamicIcon],
  template: `
    <span class="tip" [class.left]="align() === 'left'" [class.right]="align() === 'right'">
      <button type="button" class="trigger" [attr.aria-label]="'Explication : ' + label()" [attr.aria-describedby]="id">
        <svg [lucideIcon]="icon" aria-hidden="true"></svg>
      </button>
      <span class="bubble" role="tooltip" [id]="id">{{ text() }}</span>
    </span>`,
  styles: `
    :host { display: inline-flex; vertical-align: middle; margin-left: 4px; }
    .tip { position: relative; display: inline-flex; }
    .trigger { display: inline-grid; place-items: center; width: 16px; height: 16px; padding: 0; border: 0;
      border-radius: 50%; background: transparent; color: var(--muted); cursor: help; }
    .trigger svg { width: 14px; height: 14px; }
    .trigger:hover, .trigger:focus-visible { color: var(--accent); outline: none; }
    .trigger:focus-visible { box-shadow: 0 0 0 2px var(--accent-soft); }
    .bubble { position: absolute; z-index: 50; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%);
      width: max-content; max-width: 280px; padding: 9px 12px; border-radius: 10px; background: #101828; color: #fff;
      font-size: .78rem; font-weight: 400; line-height: 1.45; letter-spacing: normal; text-transform: none;
      text-align: left; white-space: normal; box-shadow: 0 8px 24px rgb(16 24 40 / .2);
      opacity: 0; visibility: hidden; pointer-events: none; transition: opacity .12s ease; }
    .bubble::after { content: ''; position: absolute; top: 100%; left: 50%; transform: translateX(-50%);
      border: 6px solid transparent; border-top-color: #101828; }
    .left .bubble { left: -8px; transform: none; } .left .bubble::after { left: 16px; }
    .right .bubble { left: auto; right: -8px; transform: none; } .right .bubble::after { left: auto; right: 10px; }
    .tip:hover .bubble, .tip:focus-within .bubble { opacity: 1; visibility: visible; }
  `,
})
export class InfoTip {
  term = input.required<GlossaryKey>();
  label = input('ce terme');
  /** Décale la bulle quand l'icône est près d'un bord. */
  align = input<'center' | 'left' | 'right'>('center');
  readonly icon = LucideInfo.icon;
  readonly id = `info-tip-${nextId++}`;
  text = computed(() => GLOSSARY[this.term()]);
}
