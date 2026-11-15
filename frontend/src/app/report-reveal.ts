import { afterNextRender, DestroyRef, Directive, ElementRef, inject } from '@angular/core';

@Directive({
  selector: '[reportReveal]',
  host: { class: 'report-reveal' },
})
export class ReportReveal {
  constructor() {
    const element = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;
    const destroyRef = inject(DestroyRef);

    afterNextRender(() => {
      if (!window.IntersectionObserver) {
        element.classList.add('is-revealed');
        return;
      }

      // Reveal each card once, so scrolling back to it keeps it readable.
      const observer = new IntersectionObserver(([entry]) => {
        if (!entry?.isIntersecting) return;
        element.classList.add('is-revealed');
        observer.disconnect();
      }, { rootMargin: '-76px 0px 0px' });
      observer.observe(element);
      destroyRef.onDestroy(() => observer.disconnect());
    });
  }
}
