# Sources ESG
Le catalogue esg_publications.csv contient dix publications publiques consultées le 15 novembre 2026. Les URL, éditeurs et dates figurent dans chaque ligne. Les résumés français sont des paraphrases manuelles. Les textes complets ne sont pas archivés et aucun extrait n’est présenté comme vérifié automatiquement. `evidence_type` distingue les déclarations d’entreprise, les actions réglementaires et les allégations. Les rapports d’entreprise sont exposés dans `disclosures`, pas automatiquement dans `controversies`.

Le lecteur retient les publications des 365 jours précédant la clôture analysée. Sans heure de publication, une source devient utilisable le lendemain. Les faits reflètent ce qui était annoncé à la date citée. Une poursuite reste une allégation, un accord conserve son statut et un rapport d’entreprise reste déclaratif. Le catalogue est partiel et ne suit pas automatiquement les évolutions des affaires.

Cas reproductibles avec Mateo
- NVDA le 9 mai 2022
- MSFT le 6 juin 2023
- TSLA le 29 septembre 2023
- GOOGL le 3 juillet 2024
- AAPL le 24 octobre 2024
- AMZN le 20 décembre 2024

Aucun abonnement API n’est nécessaire. Les sources sont consultables publiquement sur leurs sites officiels, sous leurs conditions respectives. Un catalogue vide à une date ne permet pas de conclure à la conformité ESG.

## Émissions

`esg_emissions.csv` contient cinq observations Apple (exercices 2020–2024), empreinte carbone brute sans compensation, en tonnes CO2e. Source : [rapport environnemental Apple 2025, page 82](https://www.apple.com/environment/pdf/Apple_Environmental_Progress_Report_2025.pdf), [publié le 16 avril 2025](https://www.apple.com/newsroom/2025/04/apple-surpasses-60-percent-reduction-in-global-greenhouse-gas-emissions/). Les valeurs sont arrondies par l’émetteur ; les périmètres historiques évoluent, notamment dès 2022. Ne pas traiter cette série comme une comparaison à périmètre constant ni comme une notation ESG.

Le fichier contient également cinq observations Microsoft (exercices 2020–2024), soit dix observations pour deux sociétés au total. Source : [Microsoft 2025 Environmental Data Fact Sheet, page 3, tableau 1A](https://cdn-dynmedia-1.microsoft.com/is/content/microsoftcorp/microsoft/msc/documents/presentations/CSR/2025-Microsoft-Environmental-Data-Fact-Sheet-PDF.pdf), [publié le 29 mai 2025](https://blogs.microsoft.com/on-the-issues/2025/05/29/environmental-sustainability-report/). Inventaire GHGP scopes 1+2+3, scope 2 market-based, arrondi au millier de tonnes CO2e. Les historiques sont retraités dans ce millésime. Les totaux du tableau 1B utilisant des critères de gestion ne sont pas mélangés à cette série. Cas reproductible : MSFT, 30 mai 2025, Mateo.

Chaque ligne conserve la période, la date de publication, le périmètre, la méthode, l’unité et la source. Ces valeurs du millésime 2025 ne sont utilisables qu’après leur publication, même pour les exercices plus anciens. Le lecteur retient le dernier millésime connu pour chaque période/périmètre/méthode. Les quatre autres sociétés restent sans série structurée : leurs rapports ne sont pas remplacés par des estimations. Les chiffres sont des données déclaratives, pas une validation indépendante des exclusions de Mateo. `coverage` expose les quantités et les lacunes ; des émissions disponibles ne suffisent pas à conclure à la conformité ESG.

## Historique ESGV

Le lecteur accepte `esgv_holdings.csv` avec les colonnes `ticker,as_of,published_date,url,snapshot_complete`. Les deux dates sont obligatoires ; la source doit être officielle. Une composition sans date de publication n’est jamais rétrospectivement disponible. Une liste partielle permet de constater la présence d’un titre, jamais son absence. Un relevé de plus de 120 jours est marqué `stale`, sans déduire une exclusion actuelle. L’appartenance au portefeuille n’est pas une certification ESG.

La [fiche Vanguard consultée](https://institutional.vanguard.com/assets/corp/fund_communications/pdf_publish/us-products/fact-sheet/F4393.pdf) présente une composition partielle datée mais ne fournit pas de date précise de première publication. Elle n’a donc pas été importée comme preuve historique. La composition historique complète d’ESGV et les notes propriétaires restent indisponibles ; le backend l’indique explicitement.
