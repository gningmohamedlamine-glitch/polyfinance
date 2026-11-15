import { CurrencyPipe, DecimalPipe, PercentPipe } from '@angular/common';
import { Component, input, output } from '@angular/core';
import { Analysis } from '../../services/market-api';

export type TextPart = { text: string; href?: string };

@Component({
  selector: 'app-movement-analysis',
  imports: [CurrencyPipe, DecimalPipe, PercentPipe],
  templateUrl: './movement-analysis.html',
  styleUrl: './movement-analysis.css',
})
export class MovementAnalysis {
  analysis = input.required<Analysis>();
  retry = output<void>();

  bullets(text: string) {
    return text.split(/\r?\n/).map(line => line.trim().replace(/^(?:[-*•]|\d+[.)])\s+/, '').replaceAll('**', '')).filter(Boolean);
  }

  bulletLines(text: string): { parts: TextPart[] }[] {
    return this.bullets(text).map(line => ({ parts: this.parseInlineParts(line) }));
  }

  parseInlineParts(line: string): TextPart[] {
    const parts: TextPart[] = [];
    const re = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g;
    let last = 0;
    let match: RegExpExecArray | null;
    while ((match = re.exec(line)) !== null) {
      if (match.index > last) {
        parts.push({ text: line.slice(last, match.index) });
      }
      parts.push({ text: match[1], href: match[2] });
      last = match.index + match[0].length;
    }
    if (last < line.length) {
      parts.push({ text: line.slice(last) });
    }
    return parts.length ? parts : [{ text: line }];
  }

  oneLine(text?: string, max = 140) {
    const line = text?.replace(/\s+/g, ' ').trim();
    if (!line) return '';
    return line.length > max ? `${line.slice(0, max - 1)}…` : line;
  }

  leadLine(lead: { relevance?: string; summary: string; facts?: string[] }) {
    if (lead.facts?.length) {
      return this.oneLine(lead.facts.join(' · '));
    }
    return this.oneLine(lead.relevance?.trim() || lead.summary);
  }
}