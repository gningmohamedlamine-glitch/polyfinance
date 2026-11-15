import { Profile } from './services/market-api';

export interface Persona {
  id: Profile;
  name: string;
  age: number;
  /** Profession (énoncé du défi). */
  job: string;
  risk: string;
  horizon: string;
  goal: string;
  initial: string;
  /** Mot-clé du profil (énoncé du défi). */
  focus: string;
  /** Contrainte propre au profil. */
  constraint: string;
  /** Limites fictives : copie de PROFILE_LIMITS (agents/impact_agent.py), à garder synchronisée. */
  limits: { volatility: number; drawdown: number; weight: number; sector?: number };
  /** Cas de démo mis en avant. */
  demo?: string;
}

// Profils fictifs de l'énoncé (simulation : aucune donnée personnelle réelle).
export const PERSONAS: Persona[] = [
  { id: 'amira', name: 'Amira', age: 26, job: 'Ingénieure logicielle', risk: 'Risque élevé', horizon: '15 ans et plus',
    goal: 'Croissance à long terme, sans renoncer à la diversification.', initial: 'A',
    focus: 'Croissance', constraint: 'Concentration limitée',
    limits: { volatility: 0.60, drawdown: -0.60, weight: 0.15, sector: 0.50 } },
  { id: 'robert', name: 'Robert', age: 59, job: 'Professionnel de la santé', risk: 'Risque faible à modéré', horizon: '3 à 5 ans',
    goal: 'Préserver son capital à l’approche de la retraite. Attiré par un titre très médiatisé.', initial: 'R',
    focus: 'Préservation', constraint: 'Retrait à financer',
    limits: { volatility: 0.20, drawdown: -0.20, weight: 0.05 },
    demo: 'Cas de démo' },
  { id: 'mateo', name: 'Mateo', age: 41, job: 'Gestionnaire des opérations', risk: 'Risque modéré', horizon: '8 à 12 ans',
    goal: 'Équilibre croissance et stabilité, avec des critères ESG.', initial: 'M',
    focus: 'ESG', constraint: 'Exclusions ESG documentées',
    limits: { volatility: 0.30, drawdown: -0.35, weight: 0.10 } },
];

export const personaOf = (id: Profile) => PERSONAS.find(persona => persona.id === id)!;
