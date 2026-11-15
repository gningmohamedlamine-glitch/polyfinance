import { Profile } from './services/market-api';

export interface Persona {
  id: Profile;
  name: string;
  age: number;
  risk: string;
  horizon: string;
  goal: string;
  initial: string;
}

// Profils fictifs de l'énoncé (simulation : aucune donnée personnelle réelle).
export const PERSONAS: Persona[] = [
  { id: 'amira', name: 'Amira', age: 26, risk: 'Risque élevé', horizon: '15 ans et plus',
    goal: 'Croissance à long terme, sans renoncer à la diversification.', initial: 'A' },
  { id: 'robert', name: 'Robert', age: 59, risk: 'Risque faible à modéré', horizon: '3 à 5 ans',
    goal: 'Préserver son capital à l’approche de la retraite.', initial: 'R' },
  { id: 'mateo', name: 'Mateo', age: 41, risk: 'Risque modéré', horizon: '8 à 12 ans',
    goal: 'Équilibre croissance et stabilité, avec des critères ESG.', initial: 'M' },
];

export const personaOf = (id: Profile) => PERSONAS.find(persona => persona.id === id)!;
