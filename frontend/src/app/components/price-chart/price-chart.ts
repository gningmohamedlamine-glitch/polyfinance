import {
  Component,
  computed,
  ElementRef,
  HostListener,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { Price } from '../../services/market-api';

export type ChartSelection =
  | { kind: 'session'; date: string }
  | { kind: 'range'; startDate: string; endDate: string };

const DRAG_THRESHOLD = 8;
const VIEW_WIDTH = 720;

type ChartPoint = Price & { x: number; y: number; globalIndex: number };

@Component({
  selector: 'app-price-chart',
  templateUrl: './price-chart.html',
  styleUrl: './price-chart.css',
})
export class PriceChart {
  rows = input.required<Price[]>();
  selection = input.required<ChartSelection>();
  selectionChange = output<ChartSelection>();

  svg = viewChild<ElementRef<SVGSVGElement>>('chartSvg');

  private dragOriginX = 0;
  private dragOriginDate = '';
  private pointerActive = false;
  private exceededThreshold = false;
  dragPreview = signal<{ startDate: string; endDate: string } | null>(null);

  private windowSlice = computed(() => {
    const rows = this.rows();
    if (!rows.length) return { start: 0, end: 0, window: [] as Price[] };
    const sel = this.selection();
    let start = 0;
    let end = rows.length - 1;
    if (sel.kind === 'session') {
      const index = rows.findIndex(row => row.date === sel.date);
      end = index < 0 ? rows.length - 1 : Math.min(rows.length - 1, index + 17);
      start = Math.max(0, end - 47);
    } else {
      const from = rows.findIndex(row => row.date === sel.startDate);
      const to = rows.findIndex(row => row.date === sel.endDate);
      if (from < 0 || to < 0) {
        start = Math.max(0, rows.length - 48);
        end = rows.length - 1;
      } else {
        const lo = Math.min(from, to);
        const hi = Math.max(from, to);
        const span = hi - lo + 1;
        if (span >= 48) {
          start = lo;
          end = hi;
        } else {
          const pad = Math.floor((48 - span) / 2);
          start = Math.max(0, lo - pad);
          end = Math.min(rows.length - 1, start + 47);
          start = Math.min(start, lo);
          end = Math.max(end, hi);
        }
      }
    }
    return { start, end, window: rows.slice(start, end + 1) };
  });

  points = computed(() => {
    const rows = this.rows();
    const { start, window } = this.windowSlice();
    if (!window.length) return [] as ChartPoint[];
    const values = window.map(row => row.adj_close);
    const low = Math.min(...values);
    const range = Math.max(Math.max(...values) - low, 0.01);
    return window.map((row, index) => ({
      ...row,
      x: 18 + (index * 684) / Math.max(1, window.length - 1),
      y: 206 - ((row.adj_close - low) * 169) / range,
      globalIndex: start + index,
    }));
  });

  line = computed(() => this.points().map(point => `${point.x},${point.y}`).join(' '));

  displayRange = computed(() => {
    const preview = this.dragPreview();
    if (preview) return preview;
    const sel = this.selection();
    if (sel.kind === 'range') {
      return { startDate: sel.startDate, endDate: sel.endDate };
    }
    return null;
  });

  sessionMarker = computed(() => {
    if (this.dragPreview()) return null;
    const sel = this.selection();
    return sel.kind === 'session' ? sel.date : null;
  });

  rangeOverlay = computed(() => {
    const range = this.displayRange();
    if (!range) return null;
    const pts = this.points();
    const start = pts.find(point => point.date === range.startDate);
    const end = pts.find(point => point.date === range.endDate);
    if (!start || !end) return null;
    const x1 = Math.min(start.x, end.x);
    const x2 = Math.max(start.x, end.x);
    return { x1, x2, startDate: range.startDate, endDate: range.endDate };
  });

  caption = computed(() => {
    const overlay = this.rangeOverlay();
    if (overlay) {
      return {
        left: overlay.startDate,
        center: overlay.startDate === overlay.endDate ? overlay.startDate : `${overlay.startDate} → ${overlay.endDate}`,
        right: overlay.endDate,
      };
    }
    const marker = this.sessionMarker();
    const pts = this.points();
    if (!pts.length) return { left: '', center: '', right: '' };
    return {
      left: pts[0].date,
      center: marker ?? pts.at(-1)!.date,
      right: pts.at(-1)!.date,
    };
  });

  onPointerDown(event: PointerEvent) {
    if (event.button !== 0 || !this.points().length) return;
    const svg = this.svg()?.nativeElement;
    if (!svg) return;
    svg.setPointerCapture(event.pointerId);
    this.pointerActive = true;
    this.exceededThreshold = false;
    this.dragOriginX = this.clientToSvgX(event.clientX);
    this.dragOriginDate = this.dateAtX(this.dragOriginX);
    this.dragPreview.set(null);
  }

  onPointerMove(event: PointerEvent) {
    if (!this.pointerActive) return;
    const x = this.clientToSvgX(event.clientX);
  if (!this.exceededThreshold && Math.abs(x - this.dragOriginX) >= DRAG_THRESHOLD) {
      this.exceededThreshold = true;
    }
    if (this.exceededThreshold) {
      const current = this.dateAtX(x);
      const [startDate, endDate] = this.sortDates(this.dragOriginDate, current);
      this.dragPreview.set({ startDate, endDate });
    }
  }

  onPointerUp(event: PointerEvent) {
    if (!this.pointerActive) return;
    const svg = this.svg()?.nativeElement;
    svg?.releasePointerCapture(event.pointerId);
    this.pointerActive = false;
    const preview = this.dragPreview();
    this.dragPreview.set(null);
    if (this.exceededThreshold && preview) {
      this.selectionChange.emit(this.rangeOrSession(preview.startDate, preview.endDate));
      return;
    }
    const date = this.dateAtX(this.clientToSvgX(event.clientX));
    if (date !== this.rows()[0]?.date) {
      this.selectionChange.emit({ kind: 'session', date });
    }
  }

  onPointerCancel() {
    this.pointerActive = false;
    this.exceededThreshold = false;
    this.dragPreview.set(null);
  }

  @HostListener('document:keydown.escape')
  onEscape() {
    if (!this.dragPreview()) return;
    this.onPointerCancel();
  }

  private clientToSvgX(clientX: number) {
    const svg = this.svg()?.nativeElement;
    if (!svg) return 0;
    const rect = svg.getBoundingClientRect();
    if (!rect.width) return 0;
    return ((clientX - rect.left) / rect.width) * VIEW_WIDTH;
  }

  private dateAtX(x: number) {
    const pts = this.points();
    if (!pts.length) return '';
    let best = pts[0];
    let distance = Math.abs(pts[0].x - x);
    for (const point of pts.slice(1)) {
      const next = Math.abs(point.x - x);
      if (next < distance) {
        best = point;
        distance = next;
      }
    }
    return best.date;
  }

  private sortDates(a: string, b: string) {
    const rows = this.rows();
    const ai = rows.findIndex(row => row.date === a);
    const bi = rows.findIndex(row => row.date === b);
    if (ai <= bi) return [a, b] as const;
    return [b, a] as const;
  }

  private rangeOrSession(startDate: string, endDate: string): ChartSelection {
    if (startDate === endDate) return { kind: 'session', date: startDate };
    return { kind: 'range', startDate, endDate };
  }
}