# agents/ — code de la solution (Kiro)

Idée de découpage (à adapter) :

- `profile_agent.py` : lit le profil (Amira, Mateo, Robert) et ses contraintes
- `data_agent.py` : récupère les données et calcule les indicateurs
- `guardrail_agent.py` : vérifie la cohérence demande / profil (cas Robert)
- `explainer_agent.py` : produit l'explication (sources, hypothèses, limites)
- `main.py` : orchestration

Chaque agent doit avoir un rôle justifiable (voir la diapo 5 de la présentation).
