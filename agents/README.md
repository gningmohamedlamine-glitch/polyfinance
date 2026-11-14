# Agents AlphaForge

[Django orchestre l’analyse](../backend/markets/pipeline.py) dans un ordre fixe.

1. Python calcule les rendements, compare SPY et QQQ, repère les séances marquantes et lit le catalogue CSV. Si `MARKET_WEB_SEARCH=1`, Python déclenche aussi SEC EDGAR et Nova Web Grounding avant la synthèse, avec ou sans modèle de synthèse configuré.
2. [L’agent marché](event_agent.py) explique les éléments réunis. Les publications du catalogue et les dépôts SEC horodatés figurent dans le dossier. Pour une séance, Nova cherche sur sept jours calendaires centrés sur la date. Pour une période, Nova couvre aussi la plage sélectionnée. Ses résultats restent des pistes dont la date est proposée et dont l’heure reste à vérifier. Une piste datée après la séance est présentée comme un suivi.
3. Django vérifie le schéma, la sélection, les rendements, les indices et la cohérence entre les publications et leur couverture. Seul un dossier valide peut alimenter l’impact ou entrer en cache.
4. [L’agent d’impact](impact_agent.py) reçoit les métriques que Python calcule pour le profil et le scénario. Il en explique les implications et les limites.

Chaque agent de synthèse fait au plus un appel au modèle configuré dans `BEDROCK_MODEL_ID`. Le déploiement de référence utilise `us.amazon.nova-lite-v1:0`. La recherche Web utilise `us.amazon.nova-2-lite-v1:0` et nécessite un profil AWS autorisé. [Le module de synthèse](model_text.py) extrait le texte public. Si Bedrock est indisponible, les chiffres et les preuves déjà collectées accompagnent une synthèse locale.

Le dossier validé peut être réutilisé en mémoire lors d’un changement de profil. Un dossier issu d’une panne de recherche ou de synthèse est recalculé lors de la prochaine demande. Le flux NDJSON expose les actions exécutées et leurs durées. Les CSV sont lus par le pipeline.
