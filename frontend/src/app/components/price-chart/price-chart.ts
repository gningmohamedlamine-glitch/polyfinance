import {
  Component,
  computed,
  ElementRef,
  effect,
  HostListener,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { Price } from '../../services/market-api';

export type ChartSelection =
  | { kind: 'session'; date: string }
  | { kind: 'range'; startDate: string; endDate: string };

const DRAG_THRESHOLD = 8;
const VIEW_WIDTH = 720;

type ChartPoint = Price & {
  x: number; y: number; openY: number; highY: number; lowY: number;
};

@Component({
  selector: 'app-price-chart',
  imports: [DecimalPipe],
  templateUrl: './price-chart.html',
  styleUrl: './price-chart.css',
})
export class PriceChart {
  rows = input.required<Price[]>();
  rangeMode = input(false);
  chartStyle = signal<'line' | 'candles'>('line');
  horizons = ["1J", "5J", "1M", "6M", "YTD", "1A", "5A", "Max"] as const;
  horizon = signal<(typeof this.horizons)[number]>("1M");
  firstBound = signal<string | null>(null);
  selection = input.required<ChartSelection>();
  selectionChange = output<ChartSelection>();

  svg = viewChild<ElementRef<SVGSVGElement>>('chartSvg');

  private dragOriginX = 0;
  private dragOriginDate = '';
  private pointerActive = false;
  private exceededThreshold = false;
  dragPreview = signal<{ startDate: string; endDate: string } | null>(null);

  private resetBound = effect(() => {
    this.rows();
    this.rangeMode();
    this.firstBound.set(null);
  });

  private windowSlice = computed(() => {
    const rows = this.rows();
    const sel = this.selection();
    const anchor = sel.kind === 'range' ? sel.endDate : sel.date;
    const selected = rows.findIndex(row => row.date === anchor);
    const horizon = this.horizon();
    const counts = { '1J': 2, '5J': 6, '1M': 22, '6M': 127, '1A': 253, '5A': 1261 };
    const count = horizon === 'YTD' || horizon === 'Max' ? rows.length : counts[horizon];
    let end = horizon === 'Max' || selected < 0 ? rows.length - 1
      : Math.min(rows.length - 1, selected + (horizon === '1M' ? 8 : 0));
    const yearStart = rows.findIndex(row => row.date.startsWith(rows[end]?.date.slice(0, 4) ?? ''));
    let start = horizon === 'YTD' ? Math.max(0, yearStart) : Math.max(0, end - count + 1);
    if (this.rangeMode() && sel.kind === 'range') {
      const startIndex = rows.findIndex(row => row.date === sel.startDate);
      const endIndex = rows.findIndex(row => row.date === sel.endDate);
      if (startIndex >= 0 && endIndex >= 0) {
        const lo = Math.min(startIndex, endIndex);
        const hi = Math.max(startIndex, endIndex);
        start = Math.min(start, lo);
        end = Math.max(end, hi);
      }
    }
    return rows.slice(start, end + 1);
  });

  setHorizon(horizon: (typeof this.horizons)[number]) {
    this.firstBound.set(null);
    this.horizon.set(horizon);
  }

  points = computed(() => {
    const rows = this.windowSlice();
    if (!rows.length) return [] as ChartPoint[];
    // Apply the same adjustment factor to each OHLC value.
    const prices = rows.map(row => {
      const adjustment = row.adj_close / row.close;
      return { ...row, open: row.open * adjustment, high: row.high * adjustment,
        low: row.low * adjustment, close: row.adj_close };
    });
    const showCandles = this.chartStyle() === 'candles';
    const low = Math.min(...prices.map(row => showCandles ? row.low : row.close));
    const high = Math.max(...prices.map(row => showCandles ? row.high : row.close));
    const range = Math.max(high - low, 0.01);
    const toY = (price: number) => 206 - ((price - low) * 169) / range;
    return prices.map((row, index) => ({
      ...row,
      x: 18 + (index * 684) / Math.max(1, rows.length - 1),
      y: toY(row.close),
      openY: toY(row.open),
      highY: toY(row.high),
      lowY: toY(row.low),
    }));
  });

  candleWidth = computed(() => Math.min(12, 684 / Math.max(1, this.points().length) * 0.65));

  line = computed(() => this.points().map(point => `${point.x},${point.y}`).join(' '));

  displayRange = computed(() => {
    const preview = this.dragPreview();
    if (preview) return preview;
    if (this.rangeMode() && this.firstBound()) return null;
    const sel = this.selection();
    if (sel.kind === 'range') {
      return { startDate: sel.startDate, endDate: sel.endDate };
    }
    return null;
  });

  sessionMarker = computed(() => {
    if (this.dragPreview()) return null;
    if (this.rangeMode() && this.firstBound()) return this.firstBound();
    const sel = this.selection();
    return sel.kind === 'session' ? sel.date : null;
  });

  rangeOverlay = computed(() => {
    const range = this.displayRange();
    if (!range) return null;
    const pts = this.points();
    const start = pts.find(point => point.date === range.startDate);
    const end = pts.find(point => point.date === range.endDate);
    if (!pts.length || range.endDate < pts[0].date || range.startDate > pts.at(-1)!.date) return null;
    const raw1 = start?.x ?? pts[0].x;
    const raw2 = end?.x ?? pts.at(-1)!.x;
    return {
      x1: Math.min(raw1, raw2),
      x2: Math.max(raw1, raw2),
      startDate: range.startDate,
      endDate: range.endDate,
    };
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
      this.firstBound.set(null);
      const date = this.dateAtX(this.clientToSvgX(event.clientX));
      const [startDate, endDate] = this.sortDates(this.dragOriginDate, date);
      this.selectionChange.emit(this.rangeOrSession(startDate, endDate));
      return;
    }
    const date = this.dateAtX(this.clientToSvgX(event.clientX));
    if (this.rangeMode()) {
      const first = this.firstBound();
      if (first && this.points().some(point => point.date === first)) {
        this.firstBound.set(null);
        this.selectionChange.emit(this.rangeOrSession(...this.sortDates(first, date)));
      } else {
        this.firstBound.set(date);
      }
      return;
    }
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
    this.firstBound.set(null);
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