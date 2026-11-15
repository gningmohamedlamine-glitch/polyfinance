# Agents AlphaForge

Deux agents, un seul modèle Bedrock (GPT-6 Astra, via `BEDROCK_MODEL_ID` ; `EVENT_MODEL_ID` et `IMPACT_MODEL_ID` permettent d’en choisir un par agent).

| Agent | Question | Outils qu’il choisit | Ce qu’il décide |
|---|---|---|---|
| **Enquêteur** (`event_agent.py`) | Pourquoi le titre a-t-il bougé ? | `search_catalog`, `search_sec_filings`, `search_web` | Où chercher, quand s’arrêter, quand conclure « cause indéterminée » |
| **Conseiller** (`impact_agent.py`) | Qu’est-ce que ça change pour ce profil ? | `verify_profile_coherence`, `position_value_cad`, `direct_weight`, `esg_screen` (selon le profil) | Quels calculs comptent pour ce profil et quoi signaler en premier |

## Ce que le code garantit (`agent_loop.py`)

- **Faits obligatoires en Python** avant toute décision : rendements, écarts avec SPY, QQQ et XLK, bêta et part propre au titre.
- **Au plus 4 décisions par agent.** Au-delà, l’appel est refusé et l’agent doit conclure.
- **Chaque appel est validé** : séances limitées à la sélection, outils réseau seulement si `MARKET_WEB_SEARCH=1`, outils limités au profil, doublons refusés. Un refus est renvoyé au modèle comme erreur et apparaît dans l’interface (« Refusé par le garde-fou »).
- **La cohérence avec le profil est toujours calculée**, même si le Conseiller l’oublie (source `guard`).
- **Le dossier est vérifié entre les deux agents** (`markets/pipeline.py`, `validate_dossier`).
- **Repli local** : sans modèle ou en cas d’erreur Bedrock, une politique fixe exécute les mêmes outils et un texte est produit en Python.

Les décisions (outil, arguments, justification du modèle, acceptée ou refusée) sont renvoyées dans `dossier.agent_decisions` et `impact.decisions`, et affichées dans « Décisions des agents ».

La recherche web utilise Amazon Nova 2 Lite (`web_search.py`), seul modèle doté de l’outil de recherche intégré `nova_grounding`.

## Recherche web (travail d’Adam)

`search_web` interroge d’abord **Bedrock AgentCore Search**, qui renvoie des articles datés, puis se replie sur Nova Web Grounding.
Les articles sont dédupliqués, regroupés par histoire (`story_key`, `related_count`), filtrés par pertinence et résumés en faits courts.
Variables : `MARKET_WEB_SEARCH=1`, `MARKET_WEB_SEARCH_AGENTCORE=1` (facultatives : `MARKET_WEB_CLUSTER`, `MARKET_WEB_RAW_LEAD_MAX`, `MARKET_WEB_CLUSTER_KEEP`, `MARKET_WEB_RELEVANCE_KEEP`).
