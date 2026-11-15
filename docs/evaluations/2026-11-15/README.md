# Vérification Amira, Mateo et recherche web

Mesures du 15 novembre 2026 avec le point d’entrée Django streaming et les services AWS configurés. Chaque ligne est une seule exécution : la latence dépend des services et ne constitue pas un benchmark statistique. Aucun changement frontend.

| Cas | Temps total | Recherche web | Pistes | Extraits vérifiés | Groupes multi-domaines |
|---|---:|---|---:|---:|---:|
| NVDA 17/07/2024 Amira, avant corrections | 32,80 s | found, 19,61 s | 8 | 0 | 0 |
| Même cas, après corrections | 28,15 s | found, 15,01 s | 5 | 0 | 0 |
| MSFT 30/05/2025 Mateo | 37,95 s | found | 7 | 0 | 0 |
| NVDA 29/08/2024 Robert, contrôle catalogue | 8,70 s | not_needed | 0 | 0 | 0 |

La mesure de 15 h 30 communiquée par l’utilisateur (50,7 s, dont 38,9 s de recherche) est un autre passage, pas notre mesure avant correction. Les JSON voisins contiennent les résultats et les limites de chaque passage.

## Recherche : amélioration du filtrage, preuve toujours insuffisante

Avant : huit pistes incluant index EDGAR, formulaires, titres génériques et documents Fed peu spécifiques. Après : cinq articles liés aux puces et restrictions commerciales. Quatre sont datés après le 17 juillet et le cinquième, Bloomberg du 17 juillet, n’a pas d’heure de publication vérifiée. **Aucune de ces cinq pistes n’est admissible pour expliquer la séance.** Aucun extrait n’est vérifié et aucun groupe multi-domaines n’est établi. Les pages de presse retenues ne font pas partie de la récupération automatique réservée aux domaines officiels.

AgentCore reste disponible lorsque Nova échoue ou dépasse son budget ; le résultat déclare alors la recherche partielle. Une première tentative de correction a produit un timeout de recherche et zéro piste en 42,17 s ; la gestion d’attente a été corrigée avant la mesure finale. `found` signifie seulement que des pistes existent.

Suite prioritaire : récupérer le texte et les métadonnées de publication des éditeurs accessibles avec les mêmes protections réseau, rechercher des publications contemporaines lorsque seuls des commentaires ultérieurs ressortent, puis remesurer plusieurs séances. Ne pas convertir une provenance reconnue ou une répétition entre sites en preuve causale.

## Amira

Le cas réel refuse la concentration technologique simulée de 52 %, au-dessus de la limite fictive de 50 %. La tolérance élevée au risque ne supprime pas la diversification. BTC et ETH disposent chacun de 365 rendements quotidiens antérieurs à la date étudiée. Ces références sont transmises au Conseiller ; les positions crypto restent inconnues et la diversification globale non validée. L’interface conserve ses six actions sélectionnables.

## Mateo

Le cas MSFT expose cinq observations d’émissions FY2020–2024 du rapport publié le 29 mai 2025 et une déclaration d’entreprise distincte des controverses. Le catalogue compte maintenant dix publications et dix observations d’émissions pour Apple et Microsoft. Les dates de publication empêchent leur utilisation rétroactive avant disponibilité.

La synthèse reste « insuffisant » : pas de score ESG indépendant ni de composition historique complète d’ESGV. Les données d’émissions d’une entreprise ne prouvent pas le respect de toutes les exclusions de Mateo. La synthèse réelle privilégie ces limites et ne reprend pas les valeurs d’émissions ; elles restent présentes dans le résultat détaillé de l’outil.

## Validation et reproduction

90 tests backend réussis, couvrant notamment le filtrage avant quota, la conservation des pistes lors d’un complément indisponible, les dates, les limites d’Amira et les millésimes ESG de Mateo. Les avertissements de timeout dans les tests sont simulés intentionnellement.

```powershell
python -B scripts/evaluate_analysis.py --ticker NVDA --date 2024-07-17 --profile amira --output rapport-amira.json
python -B scripts/evaluate_analysis.py --ticker MSFT --date 2025-05-30 --profile mateo --output rapport-mateo.json
python -B scripts/evaluate_analysis.py --ticker NVDA --date 2024-08-29 --profile robert --output rapport-catalogue.json
```

Ces commandes chargent `.env` et appellent les services réels. Les JSON enregistrent des résultats d’analyse, sans identifiants AWS.
