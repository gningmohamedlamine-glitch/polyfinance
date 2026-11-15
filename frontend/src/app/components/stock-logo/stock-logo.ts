import { Component, computed, input } from '@angular/core';

const LOGO_TICKERS = new Set(['NVDA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']);

@Component({
  selector: 'app-stock-logo',
  host: {
    'aria-hidden': 'true',
    '[class.compact]': 'compact()',
    '[class.wordmark]': 'ticker() === "GOOGL" || ticker() === "AMZN"',
  },
  template: `
    @if (src(); as logo) {
      <img [src]="logo" alt="" />
    } @else {
      <span>{{ ticker() }}</span>
    }
  `,
  styles: `
    :host { display: inline-grid; place-items: center; flex: none; width: 48px; height: 44px;
      border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
    img { display: block; width: 27px; height: 27px; object-fit: contain; }
    :host(.wordmark) { width: 86px; }
    :host(.wordmark) img { width: 68px; }
    :host(.compact) { height: 30px; width: 32px; border: 0; border-radius: 6px; }
    :host(.compact) img { width: 22px; height: 22px; }
    :host(.compact.wordmark) { width: 72px; }
    :host(.compact.wordmark) img { width: 64px; }
    span { color: var(--muted); font: 600 .64rem var(--mono); }
  `,
})
export class StockLogo {
  ticker = input.required<string>();
  compact = input(false);
  src = computed(() => {
    const ticker = this.ticker();
    return LOGO_TICKERS.has(ticker) ? `stock-logos/${ticker.toLowerCase()}.svg` : null;
  });
}
