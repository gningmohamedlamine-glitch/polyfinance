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

`search_web` lance **Bedrock AgentCore Search** et **Nova Web Grounding** en parallèle. AgentCore exécute jusqu’à trois requêtes à la fois. Si des résultats déjà classés couvrent les séances clés, le mode rapide peut terminer sans attendre Nova au-delà de 10 secondes. Les recherches avec une couverture plus faible attendent le résultat de Nova jusqu’au délai réseau de 40 secondes.

En mode rapide, le regroupement et la pertinence partagent un appel au modèle, avec un classement séparé si sa réponse est incomplète. L’application vérifie jusqu’à cinq articles de sites officiels, en parallèle entre domaines, et compare les citations au texte récupéré. La recherche approfondie garde les deux appels spécialisés et vérifie toutes les pistes officielles retenues.

Le flux présente les rendements et les limites du profil avant les synthèses. Quand le catalogue contient des extraits vérifiés pour toutes les séances clés, les deux agents peuvent écrire à partir du même dossier validé. L’interface adapte automatiquement la recherche à la couverture disponible. Pour comparer les résultats ou diagnostiquer la couverture, le paramètre API `search=deep` force la recherche web et donne à Nova son délai réseau complet.
Variables : `MARKET_WEB_SEARCH=1`, `MARKET_WEB_SEARCH_AGENTCORE=1` (facultatives : `MARKET_WEB_CLUSTER`, `MARKET_WEB_RAW_LEAD_MAX`, `MARKET_WEB_CLUSTER_KEEP`, `MARKET_WEB_RELEVANCE_KEEP`).
