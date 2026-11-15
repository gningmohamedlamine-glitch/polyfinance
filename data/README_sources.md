# Sources et vérification

## Données ajoutées

Le catalogue market_events.csv contient les 32 décisions ordinaires FOMC de 2022 à 2025
(31 nouvelles entrées et celle de septembre 2024 déjà présente). Les textes proviennent
des archives de la Réserve fédérale, conservés dans data/sources. L'import exige le titre
du communiqué et la mention explicite de publication à 14 h heure de l'Est.
Chaque extrait est recherché littéralement dans le texte téléchargé.

Actualisation depuis la racine :

    python scripts/import_fomc.py --years 2022 2023 2024 2025

L'import ne nécessite pas de clé API, ignore les URL déjà présentes et préserve les
autres entrées. Il ne transforme pas une annonce antérieure en événement d'une autre séance.
Les nouvelles publications ESG concernent Google (27 juin 2025), Apple (16 avril 2025)
et l'accord FTC–Amazon (25 septembre 2025). Les publications ESG datées sans heure sont
utilisées à partir du lendemain, pendant la fenêtre glissante de 365 jours.

## Recherche web

- Les requêtes ciblent d'abord les relations investisseurs, la SEC, la Fed et le BLS.
- Les résultats AgentCore sans date sont écartés ; la date de séance n'est plus substituée.
- Le regroupement par modèle ne peut ajouter ni URL ni date absentes des résultats reçus.
- Les pages officielles sur liste de domaines exacte sont téléchargées avec un délai
  maximal de 4 secondes par page, une limite de 2 Mo, sans redirection automatique.
- Un court extrait original fourni par la recherche est comparé au texte de la page.
  « Extrait retrouvé » signifie uniquement une concordance textuelle. Le résumé traduit,
  la date et la pertinence causale ne sont pas ainsi certifiés.
- Une origine officielle est distincte d'une citation vérifiée. Un accès bloqué reste
  explicitement indisponible. La presse peut rester une piste complémentaire non vérifiée.
- Plusieurs domaines constituent un indice de corroboration, pas une garantie
  d'indépendance éditoriale ni de véracité.

## Limites

Les appels Bedrock restent nécessaires pour la recherche dynamique ; les tests utilisent
des doubles de ces services. Les scores ESG commerciaux, les séries complètes d'émissions
et la composition historique d'ESGV ne sont pas ajoutés par cet import.
Les déclarations environnementales des entreprises ne sont pas des controverses en soi.
Les sources déjà présentes dans le catalogue sans extrait téléchargé restent non vérifiées.
