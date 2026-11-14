# Agents AlphaForge

`event_agent` cherche les publications du titre et du marché dans `data/market_events.csv` entre les deux clôtures comparées. Les sources restent liées au résultat, avec l’heure de publication en heure de New York.

`impact_agent` utilise les métriques du scénario fictif. Pour Robert, il calcule la variation de la position en CAD et son écart par rapport au retrait. Pour Amira, il calcule l’exposition directe avant et après l’achat. Pour Mateo, il indique les preuves ESG à obtenir.

Avec `BEDROCK_MODEL_ID`, les deux agents demandent une synthèse à Bedrock sur les résultats calculés et les sources sélectionnées. L’API expose le mode utilisé. Les dates du catalogue sont limitées aux cas de démo. L’ajout d’un événement se fait en enrichissant le CSV en amont du déploiement.
