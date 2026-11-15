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

## Explications et contrôles backend

Chaque synthèse modèle reçoit un `evidence_index` de références exactes. Les marqueurs `[ref:/chemin]` sont retirés de la prose et exposés dans `event.claims` / `impact.claims`, avec les données correspondantes dans `evidence`. Une référence inventée provoque le garde-fou de texte ; une affirmation sans référence est signalée. Les références sont propres à chaque appel d’outil, y compris si le même outil est appelé plusieurs fois. Les textes de repli n’héritent jamais des citations de la réponse remplacée.

Le contrôle numérique par affirmation compare les chiffres avec unité aux **champs de calcul explicitement cités**, avec leur signe et leur arrondi. Il signale les écarts ; il ne valide pas la signification d’une phrase. Les nombres dans les articles restent à interpréter. Le contrôle numérique global historique reste un contrôle partiel, distinct.

Les statuts ont des sens séparés : `source_origin=official` indique le domaine, `page_status=retrieved` la récupération, `excerpt_status=verified` une correspondance textuelle. Aucun de ces statuts ne certifie le résumé ou la causalité. La date du moteur reste `search_reported` ; une métadonnée explicite de publication trouvée dans la page donne `publisher_metadata` et remplace la date proposée. Une date de modification n’est pas une date de publication. Plusieurs domaines ne garantissent pas l’indépendance des articles.

Les sources sans heure publiées le jour même restent des pistes et sont exclues du contexte explicatif. Les heures explicites sont converties en heure de New York. `temporal.py` contient les clôtures anticipées de 2021 à 2026 ; cette table doit être étendue pour d’autres années ([calendrier NYSE](https://www.nyse.com/trade/hours-calendars)). Le classement conserve les dates reçues ; il ne peut pas inventer une nouvelle heure. Une date déclarée par un éditeur n’est pas une authentification indépendante.

## Limites d’exécution et caches

`execution_budget` expose les appels réellement lancés, les tokens rapportés par Bedrock et les limites appliquées. Par défaut : 90 secondes, 20 appels modèle, 50 000 tokens de sortie réservés cumulés, 1 Mo de requêtes UTF-8 cumulées, 40 requêtes externes directes. Le compteur d’entrée est en **octets**, distinct du compteur observé de tokens ; aucun coût monétaire n’est estimé. Les appels internes au service de grounding ne sont pas des requêtes directes comptables par l’application.

Le budget est partagé entre les threads des deux agents et la recherche. Une réservation est faite avant chaque appel modèle ; les essais échoués consomment aussi cette réservation. À l’échéance, le client reçoit une erreur et aucun nouvel appel n’est autorisé. Un appel réseau déjà lancé peut finir sous son délai SDK : il n’est pas tué. Quatre analyses au plus peuvent occuper les workers **par processus** ; une place reste occupée tant que le travail en cours n’est pas terminé. Un déploiement multiprocessus conserve des limites indépendantes par processus, pas un quota AWS global.

Le dossier marché expire après 15 minutes, les soumissions SEC après 15 minutes et les pages officielles après une heure. Les résultats sont copiés pour éviter les mutations entre requêtes. Les échecs de lecture et les dossiers avec recherche incomplète ne sont pas mis en cache. Les paramètres sont documentés dans `.env.example`. Les caches restent locaux au processus.

Le comportement API est compatible avec l’interface existante ; les nouveaux champs de provenance n’ont pas encore de vue dédiée. Les tests sont locaux avec services simulés. Une vérification avec les modèles Bedrock réels reste nécessaire avant déploiement.
