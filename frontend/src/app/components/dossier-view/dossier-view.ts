import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, computed, effect, input, signal } from '@angular/core';
import { ReportReveal } from '../../report-reveal';
import { LucideDynamicIcon } from '@lucide/angular';
import { ICONS } from '../../icons';
import { Analysis, Source } from '../../services/market-api';
import { InfoTip } from '../info-tip/info-tip';
import { MarketChange } from '../market-change/market-change';

type Lead = NonNullable<NonNullable<Analysis['dossier']>['coverage']['web_leads']>[number];
type Bucket = 'results' | 'macro' | 'filing' | 'web';

interface AltSource {
  url: string;
  title: string;
  publisher: string;
}

interface Row {
  url: string;
  title: string;
  publisher: string;
  when: string;
  tip?: string;
  form: string;
  day: string;
  session: string;
  story: string;
  bucket: Bucket;
  also: AltSource[];
}

const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const INTEREST = /revenue|chiffre d.affaires|earnings|bénéfice|\$[\d.,]+\s*billion|taux directeur|federal funds/i;

function frDate(iso?: string, year = true): string {
  if (!iso) return '';
  const [y, month, day] = iso.slice(0, 10).split('-').map(Number);
  if (!y || !month || !day) return iso;
  return year ? `${day} ${MONTHS[month - 1]} ${y}` : `${day} ${MONTHS[month - 1]}`;
}

function clean(text?: string): string {
  return (text ?? '').replace(/\s+/g, ' ').trim();
}

function clip(text: string, max = 88): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

function displayTitle(title: string, fallback: string): string {
  const value = clean(title);
  if (!value || /^(none|article|document|untitled)$/i.test(value)) return fallback;
  return clip(value);
}

function bucketFor(title: string, publisher = '', url = ''): Bucket {
  const text = `${title} ${publisher} ${url}`.toLowerCase();
  if (/8-k|10-q|10-k|424b2|form 10|edgar|dépôt/.test(text) || publisher === 'SEC EDGAR') return 'filing';
  if (/fomc|federal reserve|réserve fédérale|bls\b|taux directeur|fonds fédéraux|cpi\b/.test(text)) return 'macro';
  if (INTEREST.test(text) || /financial results|résultats/.test(text)) return 'results';
  return 'web';
}

function formOf(text: string): string {
  const form = text.match(/\b(8-K|10-Q|10-K|424B2|S-8)\b/i);
  return form ? form[1].toUpperCase() : '';
}

function publisherOf(given: string, url: string, company: string): string {
  const known = given.trim();
  if (/sec edgar|edgar/i.test(known) || /sec\.gov/i.test(url)) return 'SEC EDGAR';
  if (/federal reserve|réserve fédérale|fomc/i.test(`${known} ${url}`)) return 'Federal Reserve';
  if (/bureau of labor|bls\.gov/i.test(`${known} ${url}`)) return 'BLS';
  if (known && !/^(web|other|news)$/i.test(known)) return clip(known, 28);
  try {
    const host = new URL(url).hostname.replace(/^www\./, '');
    const brand = company.split(' ')[0];
    if (brand && host.toLowerCase().includes(brand.toLowerCase())) return brand;
    const stem = host.split('.')[0];
    return stem ? stem.charAt(0).toUpperCase() + stem.slice(1) : 'Web';
  } catch {
    return company.split(' ')[0] || 'Web';
  }
}

/** Publication date on the row. The session date stays in the header, or in a tooltip when it differs. */
function dated(published: string, clock: string | undefined, session?: string): { when: string; tip?: string } {
  const when = clock ? `${frDate(published, false)} · ${clock.slice(0, 5)}` : frDate(published, false);
  const full = clock ? `${frDate(published)}, ${clock.slice(0, 5)} (heure de l’Est)` : frDate(published);
  if (session && session.slice(0, 10) !== published.slice(0, 10)) {
    return { when, tip: `${full} · séance du ${frDate(session)}` };
  }
  return { when, tip: clock ? full : undefined };
}

function publicationRow(source: Source, company: string): Row {
  const bucket = bucketFor(source.title, source.publisher, source.url);
  const [day, clock] = source.time_et.replace(' ', 'T').split('T');
  const dates = dated(day, clock, source.session);
  return {
    url: source.url,
    title: displayTitle(source.title, 'Publication'),
    publisher: publisherOf(source.publisher, source.url, company),
    ...dates,
    form: formOf(`${source.title} ${source.url}`),
    day: day.slice(0, 10),
    session: source.session?.slice(0, 10) ?? '',
    story: '',
    bucket,
    also: [],
  };
}

function leadRow(lead: Lead, company: string): Row {
  const raw = [lead.title, ...(lead.facts ?? []), lead.summary ?? '', lead.relevance ?? ''].join(' ');
  const filing = bucketFor(raw, '', lead.url) === 'filing';
  const bucket = filing ? 'filing' : lead.after_session ? 'web' : bucketFor(raw, '', lead.url);
  const dates = dated(lead.published_date, undefined, lead.session);
  return {
    url: lead.url,
    title: displayTitle(lead.title, filing ? (formOf(raw) || 'Dépôt SEC') : 'Piste web'),
    publisher: publisherOf('', lead.url, company),
    ...dates,
    form: formOf(raw),
    day: lead.published_date.slice(0, 10),
    session: lead.session?.slice(0, 10) ?? '',
    story: lead.story_key ?? '',
    bucket,
    also: [],
  };
}

function genericTitle(title: string): boolean {
  return /newsroom|article|document|untitled|piste web|publication$/i.test(title.trim());
}

/** Same announcement, several pages. Filings stay separate: each form is its own document. */
function sameEvent(a: Row, b: Row): boolean {
  if (a.bucket === 'filing' || b.bucket === 'filing') return false;
  if (a.story && a.story === b.story) return true;
  if (!a.day || a.day !== b.day) return false;
  return genericTitle(a.title) || genericTitle(b.title);
}

function gather(rows: Row[]): Row[] {
  const pending = rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => Number(genericTitle(a.row.title)) - Number(genericTitle(b.row.title)) || b.row.title.length - a.row.title.length);
  const used = new Set<number>();
  const out: Row[] = [];
  for (const current of pending) {
    if (used.has(current.index)) continue;
    used.add(current.index);
    const also: AltSource[] = [];
    for (const other of pending) {
      if (used.has(other.index) || !sameEvent(current.row, other.row)) continue;
      used.add(other.index);
      also.push({ url: other.row.url, title: other.row.title, publisher: other.row.publisher });
    }
    out.push({ ...current.row, also });
  }
  return out.sort((a, b) => a.day.localeCompare(b.day) || a.title.localeCompare(b.title));
}

/** Dossier de preuves : tout ce que l'Enquêteur a trouvé, vérifié ou écarté, avec ses limites. */
@Component({
  selector: 'app-dossier-view',
  imports: [InfoTip, DatePipe, DecimalPipe, LucideDynamicIcon, MarketChange, ReportReveal],
  templateUrl: './dossier-view.html',
  styleUrl: './dossier-view.css',
})
export class DossierView {
  analysis = input.required<Analysis>();
  readonly icons = ICONS;
  /** Secondary coverage starts closed. Important groups stay open. */
  private closed = signal(new Set<Bucket>(['web']));

  constructor() {
    effect(() => {
      this.analysis();
      this.closed.set(new Set(['web']));
    });
  }

  isOpen(id: Bucket) {
    return !this.closed().has(id);
  }

  onToggle(id: Bucket, event: Event) {
    const open = (event.target as HTMLDetailsElement).open;
    this.closed.update(current => {
      const next = new Set(current);
      if (open) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  sources = computed(() => this.analysis().event.sources);
  leads = computed(() => this.analysis().dossier?.coverage.web_leads ?? []);
  verified = computed(() => this.sources().filter(s => s.excerpt_status === 'verified').length);
  corroborated = computed(() => this.leads().filter(l => (l.corroboration ?? 1) >= 2).length);
  unexplained = computed(() => this.analysis().dossier?.coverage.sessions_unexplained ?? []);
  readonly betaMissing = 'bêta indisponible : il faut un an d’historique avant le début de la sélection';
  /** Only the big sessions. A long period is mostly quiet days, and listing them is not a finding. */
  notableGaps = computed(() => {
    const missing = new Set(this.unexplained());
    return (this.analysis().dossier?.notable_sessions?.sessions ?? []).filter(session => missing.has(session.date));
  });
  groups = computed(() => {
    const company = this.selection()?.name ?? this.selection()?.ticker ?? '';
    const rows = gather([
      ...this.sources().map(source => publicationRow(source, company)),
      ...this.leads().map(lead => leadRow(lead, company)),
    ]);
    const specs: { id: Bucket; title: string; hint: string; icon: 'analyse' | 'sec' | 'doc' | 'web' }[] = [
      { id: 'results', title: 'Annonces financières', hint: 'Résultats, chiffre d’affaires, prévisions', icon: 'analyse' },
      { id: 'macro', title: 'Contexte de marché', hint: 'Décisions officielles, contexte macroéconomique', icon: 'sec' },
      { id: 'filing', title: 'Dépôts SEC', hint: 'Dépôts officiels', icon: 'doc' },
      { id: 'web', title: 'Autres sources', hint: 'Couverture médiatique et autres pistes web', icon: 'web' },
    ];
    return specs
      .map(spec => {
        const mine = rows.filter(row => row.bucket === spec.id);
        const sessions = [...new Set(mine.map(row => row.session).filter(Boolean))];
        const hint = sessions.length === 1 ? `${spec.hint} · séance du ${frDate(sessions[0], false)}` : spec.hint;
        return { ...spec, hint, rows: mine };
      })
      .filter(group => group.rows.length);
  });
  resultCount = computed(() => this.groups().reduce((sum, group) => sum + group.rows.length, 0));
  decisions = computed(() => (this.analysis().dossier?.agent_decisions ?? []));
  limits = computed(() => {
    const limits = this.analysis().dossier?.limits ?? {};
    const labels: Record<string, string> = {
      causality: 'Causalité', direction: 'Sens du mouvement', excerpts: 'Extraits', figures_source: 'Origine des chiffres',
      verified_events_source: 'Sources consultées', max_tool_calls: 'Appels d’outils maximum',
    };
    return Object.entries(limits).map(([key, value]) => ({
      label: labels[key] ?? key,
      value: key === 'figures_source' && value === 'python' ? 'Calculés en Python, jamais par le modèle' : String(value),
    }));
  });
  /** Mouvement surtout expliqué par l'effet attendu du marché (bêta × indice). */
  marketDriven = computed(() => {
    const m = this.analysis().dossier?.returns?.market_model;
    return !!m && m.status === 'ok' && Math.abs(m.expected_return ?? 0) > Math.abs(m.residual ?? 0);
  });
  /** A quiet note. A complete search does not need a banner. */
  searchNote = computed(() => {
    const coverage = this.analysis().dossier?.coverage;
    const reason = coverage?.web_search_reason;
    if (coverage?.nova_grounding === 'budget_elapsed') {
      return { summary: 'Recherche partielle — Nova n’a pas répondu dans le délai prévu.', detail: 'Les sources déjà obtenues sont affichées. Une piste web reste une piste, pas une preuve.' };
    }
    if (coverage?.nova_grounding && ['busy', 'timeout', 'unavailable', 'not_executed', 'invalid_response'].includes(coverage.nova_grounding)) {
      return { summary: 'Recherche partielle — Nova n’a renvoyé aucun résultat exploitable.', detail: 'Les sources déjà obtenues sont affichées. Une piste web reste une piste, pas une preuve.' };
    }
    switch (coverage?.web_search) {
      case 'disabled': return { summary: 'Recherche web désactivée.', detail: 'MARKET_WEB_SEARCH n’est pas activé. Seul le catalogue vérifié est consulté.' };
      case 'unavailable': return { summary: 'Recherche web indisponible.', detail: reason || 'Le service n’a pas répondu. Les autres sources disponibles sont affichées.' };
      case 'no_dated_sources': return { summary: 'Aucun article daté.', detail: 'La recherche a tourné, sans article daté dans la fenêtre.' };
      case 'no_relevant_sources': return { summary: 'Aucun article retenu.', detail: 'Des articles ont été trouvés, aucun n’est retenu pour ce mouvement.' };
      default: return null;
    }
  });
  status = computed(() => {
    if (!this.sources().length && !this.leads().length) {
      return this.marketDriven()
        ? { label: 'Mouvement surtout porté par le marché', tone: 'neutral' }
        : { label: 'Cause indéterminée', tone: 'neutral' };
    }
    if (this.verified()) return { label: 'Extraits vérifiés', tone: 'ok' };
    return { label: 'Sources datées', tone: 'neutral' };
  });
  model = computed(() => this.analysis().dossier?.returns?.market_model);
  selection = computed(() => this.analysis().dossier?.selection);

  toolLabel(tool: string) {
    return ({ search_catalog: 'Chercher dans le catalogue vérifié', search_sec_filings: 'Chercher les dépôts 8-K sur SEC EDGAR',
              search_web: 'Chercher des pistes sur le web' } as Record<string, string>)[tool] ?? tool;
  }

}
