# Agents AlphaForge

`run_event_agent` calcule le dossier `alphaforge.market_dossier.v1` via Bedrock Converse et des outils Python (`compare_market`, `find_notable_sessions`, `search_publications`). Les résultats et la trace d’outils restent exposés à l’API.

`run_impact_agent` reçoit ce dossier, le profil et le scénario fictif. Il exécute les calculs par profil (Robert, Amira, Mateo) puis demande une synthèse Bedrock quand `BEDROCK_MODEL_ID` est configuré.

Avec `BEDROCK_MODEL_ID`, les deux agents peuvent répondre via Bedrock. Sans modèle ou en cas d’erreur, le mode local conserve les chiffres, les sources et la trace des outils exécutés.