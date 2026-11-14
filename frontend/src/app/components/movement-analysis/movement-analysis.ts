import { CurrencyPipe, DecimalPipe, PercentPipe } from '@angular/common';
import { Component, input } from '@angular/core';
import { Analysis } from '../../services/market-api';

@Component({
  selector: 'app-movement-analysis',
  imports: [CurrencyPipe, DecimalPipe, PercentPipe],
  templateUrl: './movement-analysis.html',
  styleUrl: './movement-analysis.css',
})
export class MovementAnalysis {
  analysis = input.required<Analysis>();
}
