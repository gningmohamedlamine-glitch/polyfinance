import { Component, computed, input, output, signal } from '@angular/core';
import { Price } from '../../services/market-api';

@Component({
  selector: 'app-price-chart',
  templateUrl: './price-chart.html',
  styleUrl: './price-chart.css',
})
export class PriceChart {
  rows = input.required<Price[]>();
  selected = input.required<string>();
  rangeStart = input<string>('');
  rangeEnd = input<string>('');
  selectDate = output<string>();
  selectRange = output<{ start: string; end: string }>();

  private anchor = signal<string | null>(null);
  dragging = signal(false);
  hoverDate = signal<string | null>(null);

  points = computed(() => {
    const rows = this.rows();
    const selection = rows.findIndex(row => row.date === this.selected());
    const end = Math.min(rows.length, (selection < 0 ? rows.length : selection + 17));
    const window = rows.slice(Math.max(0, end - 48), end);
    if (!window.length) return [];
    const values = window.map(row => row.adj_close);
    const low = Math.min(...values);
    const range = Math.max(Math.max(...values) - low, 0.01);
    return window.map((row, index) => ({
      ...row, x: 18 + index * 684 / Math.max(1, window.length - 1),
      y: 206 - (row.adj_close - low) * 169 / range,
      canSelect: row.date !== rows[0].date,
    }));
  });

  line = computed(() => this.points().map(point => `${point.x},${point.y}`).join(' '));

  rangeDates = computed(() => {
    const start = this.rangeStart();
    const end = this.rangeEnd();
    if (!start || !end) return new Set<string>();
    const rows = this.rows().map(row => row.date);
    const a = rows.indexOf(start);
    const b = rows.indexOf(end);
    if (a < 0 || b < 0) return new Set<string>();
    const lo = Math.min(a, b);
    const hi = Math.max(a, b);
    return new Set(rows.slice(lo, hi + 1));
  });

  inRange(date: string): boolean {
    return this.rangeDates().has(date);
  }

  onPointerDown(date: string) {
    if (!this.points().find(point => point.date === date)?.canSelect) return;
    this.anchor.set(date);
    this.dragging.set(true);
    this.hoverDate.set(date);
  }

  onPointerEnter(date: string) {
    if (!this.dragging()) return;
    this.hoverDate.set(date);
  }

  cancelDrag() {
    this.anchor.set(null);
    this.dragging.set(false);
    this.hoverDate.set(null);
  }

  onPointerUp(date: string) {
    if (!this.dragging()) {
      this.selectDate.emit(date);
      return;
    }
    const start = this.anchor();
    this.dragging.set(false);
    this.anchor.set(null);
    this.hoverDate.set(null);
    if (!start || start === date) {
      this.selectDate.emit(date);
      return;
    }
    const rows = this.rows().map(row => row.date);
    const a = rows.indexOf(start);
    const b = rows.indexOf(date);
    const lo = Math.min(a, b);
    const hi = Math.max(a, b);
    this.selectRange.emit({ start: rows[lo], end: rows[hi] });
  }
}