/** Explications courtes affichées au survol des icônes « i ». Un seul endroit pour les textes. */
export const GLOSSARY = {
  variation: 'Rendement du titre entre la clôture de la veille (ou du début de période) et la clôture du dernier jour, en dollars américains, avec des cours ajustés des dividendes et fractionnements.',
  residual: 'Ce qui reste du mouvement une fois retiré l’effet attendu du marché (bêta × variation du Nasdaq-100). Proche de 0 : le marché explique tout. Élevé : une nouvelle propre à l’entreprise est probable.',
  beta: 'Combien le titre amplifie d’habitude le marché, mesuré sur les 252 séances avant la sélection. Un bêta de 2 signifie que, quand le Nasdaq-100 bouge de 1 %, le titre bouge en moyenne de 2 %.',
  expected: 'Le mouvement qu’aurait eu le titre s’il avait seulement suivi le marché : bêta × variation du Nasdaq-100 sur la même période.',
  sources: 'Publications datées venant du catalogue, de SEC EDGAR ou de sites officiels. « Extrait vérifié » : la citation a été retrouvée mot pour mot dans le texte officiel téléchargé.',
  web: 'Articles trouvés par la recherche web, datés et cités par le moteur. Leur contenu n’est pas vérifié. « Corroborée » : plusieurs sites indépendants rapportent la même histoire.',
  volatility: 'Ampleur des variations quotidiennes du prix, annualisée, sur les 12 mois avant la séance. Plus elle est élevée, plus le prix fluctue. Elle est comparée à la limite fictive du profil.',
  drawdown: 'Plus forte chute depuis un sommet sur les 12 mois avant la séance : ce qu’un investisseur aurait pu perdre au pire moment. Elle est comparée à la baisse tolérée par le profil.',
  tech: 'Part du portefeuille fictif d’Amira investie en technologie après l’achat simulé. L’énoncé demande d’éviter de miser exclusivement sur la tech : limite fictive de 50 %.',
  limits: 'Seuils fictifs propres à chaque profil (volatilité, pire baisse, concentration). Ce sont des hypothèses du projet, pas des règles réglementaires ni un conseil.',
  esg: 'Vérification indicative à partir de données publiques : secteur, publications officielles datées (régulateurs) et comparaison avec ESGV. Ce n’est pas une note ESG : sans preuve, l’outil conclut « insuffisant », jamais « conforme ».',
  esgv: 'Vanguard ESG U.S. Stock ETF : un fonds qui exclut certaines entreprises selon des critères environnementaux, sociaux et de gouvernance. Il sert de point de comparaison.',
  sensitivity: 'Chaque conclusion est recalculée avec une autre hypothèse raisonnable (autre indice, autre période). Si la conclusion change, l’outil le signale : elle dépend d’un choix de méthode.',
  controls: 'Vérifications automatiques en code, sans IA, avant l’affichage : limites du profil, aucun conseil d’achat ou de vente, chiffres conformes aux données, sources, aucune donnée future.',
  prudence: 'Si aucune source datée n’explique le mouvement, l’Enquêteur écrit « cause indéterminée » plutôt que d’inventer une explication.',
  tokens: 'Volume de texte lu (entrée) et écrit (sortie) par le modèle, tel que renvoyé par Amazon Bedrock. Aucun coût n’est estimé.',
  decisions: 'Chaque appel d’outil choisi par un agent, avec sa justification. Le code accepte ou refuse chaque appel avant de l’exécuter.',
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;
