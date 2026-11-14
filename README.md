# AlphaForge AI — Datathon PolyFinances 2026

Clique sur une séance pour comprendre le mouvement, puis change le profil pour voir l’impact sur un scénario fictif.

| Dossier | Contenu |
| --- | --- |
| `frontend/` | Angular CLI. Page d’exploration, composants graphique et résultats, service HTTP. |
| `backend/` | Projet Django `config`, application `markets`, routes et service de données. |
| `agents/` | Recherche de publications et analyse de l’impact, avec synthèses Bedrock. |
| `data/` | CSV d’origine et catalogue de publications. Le serveur lit les CSV et construit les séries en mémoire. |
| `notebooks/` | Exploration dans JupyterLab. |
| `deploy/` | Conteneur déployé via ECR, CloudFormation et ECS Express Mode. |

## Lancement local

Depuis la racine, avec Python 3.12+ et Node 24, dans deux terminaux. Sur Windows, remplacer `.venv/bin/python` par `.venv\Scripts\python.exe` et utiliser `npm.cmd` si PowerShell bloque les scripts npm.

```bash
python -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python backend/manage.py runserver
```

```bash
cd frontend
npm ci
npm start
```

Ouvrir `http://localhost:4200`. Les deux boutons de démo sélectionnent NVIDIA après la publication du 8-K et NVIDIA le jour de la publication de l’IPC américain. La vue compare les clôtures ajustées sur la même fenêtre avec SPY et QQQ. Le calcul CAD utilise le taux disponible à chaque date. Les points du graphique sont des séances quotidiennes. Les publications apportent un contexte plausible et les chiffres mesurent les écarts observés.

Le mode local fonctionne avec le catalogue seul. Pour utiliser un profil créé avec `aws login`, installer aussi `botocore[crt]` dans le venv. Pour essayer Bedrock, configurer une session AWS valide et les variables `AWS_PROFILE` (si un profil est utilisé), `AWS_REGION=us-east-1` et `BEDROCK_MODEL_ID` avant de lancer Django.

## Déploiement AWS

Le compte de l’atelier doit autoriser CloudFormation, ECR, ECS Express Mode et les opérations IAM nécessaires à la création et à l’utilisation des rôles du service. Le modèle Bedrock ou profil d’inférence doit être invocable depuis `us-east-1`. Le modèle choisi et les permissions du compte se vérifient avec les identifiants temporaires de l’atelier.

- **Depuis GitHub Actions** — Configurer le fournisseur OIDC GitHub et un rôle de déploiement AWS avec une condition de confiance ciblant ce dépôt et la branche autorisée. Définir ensuite les variables du dépôt `AWS_DEPLOY_ROLE_ARN` et `BEDROCK_MODEL_ID`, puis lancer **Déployer AlphaForge sur AWS**. [Guide officiel OIDC](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws).
- **Depuis un poste authentifié** — Ouvrir un shell Bash avec AWS CLI, Docker, Python et curl. Configurer `AWS_PROFILE=workshop` et `BEDROCK_MODEL_ID`, puis lancer `bash deploy/deploy.sh`. L’AWS CLI peut utiliser la session temporaire stockée dans le profil local.

Le script construit une image unique et vérifie localement son démarrage en lecture seule. Il la pousse ensuite sur ECR, met à jour ECS et vérifie le frontend, la route de santé et l’appel réel des deux agents Bedrock. Le conteneur ne demande aucune base de données. L’adresse générée par ECS est accessible publiquement lorsque le compte fournit les sous-réseaux publics nécessaires. Les modèles peuvent donc être appelés pendant la démo via cette adresse.

Pour arrêter le déploiement d’essai, supprimer la pile `alphaforge-service`. La pile `alphaforge-registry` conserve le dépôt d’images lors de sa suppression. Les ressources AWS sont facturables selon les conditions du compte atelier.
