import { Component, computed, input, output } from '@angular/core';
import { Price } from '../../services/market-api';

@Component({
  selector: 'app-price-chart',
  templateUrl: './price-chart.html',
  styleUrl: './price-chart.css',
})
export class PriceChart {
  rows = input.required<Price[]>();
  selected = input.required<string>();
  selectDate = output<string>();

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
}
