import { CurrencyPipe, DecimalPipe, PercentPipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';
import { ICONS } from '../../icons';

@Component({
  selector: 'app-market-change',
  imports: [CurrencyPipe, DecimalPipe, PercentPipe, LucideDynamicIcon],
  host: { '[attr.data-direction]': 'direction()' },
  template: `
    @if (showIcon() && direction() !== 'flat') {
      <svg class="ico" [lucideIcon]="direction() === 'up' ? icons.up : icons.down" aria-hidden="true"></svg>
    }
    <span class="num">{{ direction() === 'up' ? '+' : '' }}@switch (unit()) {
      @case ('pts') { {{ value() | number:digits() }}&nbsp;pts }
      @case ('CAD') { {{ value() | currency:'CAD':'symbol-narrow':digits() }} }
      @default { {{ value() | percent:digits() }} }
    }</span>
  `,
  styles: `
    :host { display: inline-flex; align-items: baseline; gap: .28em; white-space: nowrap; }
    :host([data-direction="up"]) { color: var(--ok); }
    :host([data-direction="down"]) { color: var(--danger); }
    .ico { align-self: center; width: .86em; height: .86em; }
  `,
})
export class MarketChange {
  value = input.required<number>();
  unit = input<'%' | 'pts' | 'CAD'>('%');
  digits = input('1.2-2');
  showIcon = input(false);
  readonly icons = ICONS;
  direction = computed(() => this.value() > 0 ? 'up' : this.value() < 0 ? 'down' : 'flat');
}
