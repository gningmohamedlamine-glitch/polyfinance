import { Component, input } from '@angular/core';

/** Logo ALPHA Déclic : un alpha dont la queue remonte comme une courbe de prix. */
@Component({
  selector: 'app-logo',
  template: `
    <svg viewBox="0 0 48 48" [attr.width]="size()" [attr.height]="size()" role="img" aria-label="ALPHA Déclic">
      <defs>
        <linearGradient id="af-logo-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#3b6ef5" /><stop offset="1" stop-color="#1d3fb8" />
        </linearGradient>
      </defs>
      <rect width="48" height="48" rx="12" fill="url(#af-logo-g)" />
      <path d="M31.5 17C28.5 30 14.5 33 14 24C13.5 16 23.5 14.5 27.5 23L30 29C31 31.5 33 32 34.5 30"
            fill="none" stroke="#fff" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round" />
      <circle cx="37" cy="14" r="3" fill="#7dd3fc" />
    </svg>`,
  styles: `:host { display: inline-flex; flex: none; } svg { display: block; filter: drop-shadow(0 2px 4px rgb(29 63 184 / .25)); }`,
})
export class Logo {
  size = input(36);
}
