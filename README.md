# AlphaForge AI — Datathon PolyFinances 2026

Solution agentique auto-explicative d'aide à la décision d'investissement (simulation uniquement, aucun conseil financier).

## Structure

| Dossier | Outil | Contenu |
| --- | --- | --- |
| `agents/` | **Kiro** | Code de la solution : agents (Strands), outils, déploiement AgentCore, interface |
| `notebooks/` | **JupyterLab** (SageMaker Unified Studio) | Exploration, nettoyage et validation des données |
| `data/` | — | Jeu de départ AlphaForge (voir `data/README_starter.md`) |

## Région AWS

`us-east-1` uniquement.

## Reproduction
```bash
pip install -r requirements.txt
```

### Variables d'environnement
| Variable | Rôle | Exemple |
| --- | --- | --- |
| `SEC_USER_AGENT` | User-Agent exigé par la SEC pour le téléchargement des communiqués | `export SEC_USER_AGENT="Equipe AlphaForge prenom.nom@exemple.com"` |
| `ALPHAFORGE_BUCKET` | Bucket S3 (`us-east-1`) où envoyer `data/` ; lu aussi par les outils quand il est défini | `export ALPHAFORGE_BUCKET=nom-du-bucket` |
| `BEDROCK_MODEL_ID` | ID du modèle ou du profil d'inférence Bedrock utilisé par les agents | `export BEDROCK_MODEL_ID=<id trouvé avec --lister>` |

Les identifiants AWS viennent de l'environnement (rôle, profil ou variables `AWS_*`), jamais du code.

### Ordre des scripts
1. `notebooks/01_exploration.ipynb`, dernière cellule : télécharge les FNB sectoriels dans `data/sector_etfs_daily.csv`.
2. `python scripts/telecharger_annonces.py` : communiqués SEC dans `data/annonces/` (fichiers déjà présents non réécrits).
3. `python scripts/envoyer_s3.py` (`--dry-run` pour simuler) : envoie `data/` vers `s3://$ALPHAFORGE_BUCKET/data/`, sans rien supprimer.
4. `python scripts/tester_modele.py --lister` : retrouve l'ID du modèle (profils contenant « gpt »).
5. `python scripts/tester_modele.py` : vérifie que le modèle appelle l'outil `calculer_ecart` (affiche `OK`).
6. `python -m pytest -q agents/test_tools.py` : tests des outils.

À compléter : lancement des agents, sources et limites des données (voir `data/sources_metadata.csv`).
