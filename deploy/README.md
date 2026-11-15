# Pipeline AWS

## Parcours

GitHub Actions (lancement manuel sur `main`) → CI du même commit → image Docker
Angular + Django + CSV → ECR → CloudFormation → ECS Express → vérification HTTPS.
La CI teste les agents et Django, compile Angular, valide les templates CloudFormation,
construit une image et exécute une analyse locale dans ce conteneur.
Le déploiement ne commence que lorsque ces contrôles réussissent.

L'application n'utilise pas de base de données. Les sources téléchargées et données ESG
sont embarquées dans l'image. Il faut les committer avant de lancer le workflow.
Aucune clé AWS ni fichier `.env` n'est embarqué ; GitHub utilise OIDC et les tâches ECS
utilisent leur rôle IAM pour Bedrock et AgentCore.

## 1. Préparer AWS une seule fois

Compte atelier avec ECS Express disponible, réseau public utilisable et accès au modèle
Bedrock choisi ainsi qu'à Nova Web Grounding. Région par défaut : `us-east-1`.
Les règles du compte atelier peuvent empêcher la création d'IAM/OIDC : utiliser alors
le rôle fourni par l'organisateur, ou le script local avec une session AWS autorisée.

Dans AWS CloudShell (remplacer le dépôt par le vôtre) :

```bash
aws cloudformation deploy \
  --region us-east-1 \
  --stack-name alphaforge-github-oidc \
  --template-file deploy/github-oidc.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides GitHubRepo=PROPRIETAIRE/DEPOT Branch=main CreateProvider=true

aws cloudformation describe-stacks \
  --region us-east-1 --stack-name alphaforge-github-oidc \
  --query 'Stacks[0].Outputs[?OutputKey==`RoleArn`].OutputValue | [0]' --output text
```

Cloner le dépôt ou téléverser le template dans CloudShell avant ces commandes.
Si le fournisseur GitHub OIDC existe déjà, utiliser `CreateProvider=false`.
Le template historique de bootstrap accorde **AdministratorAccess au rôle de déploiement**,
pour le compte atelier uniquement ; pour un compte de production, faire fournir un rôle
restreint par l'administrateur. Le rôle d'exécution de l'application n'a pas ces droits.
La confiance OIDC limite le déploiement au dépôt configuré et à `main`.

## 2. Variables GitHub

Settings → Secrets and variables → Actions → Variables :

| Variable | Valeur |
| --- | --- |
| `AWS_DEPLOY_ROLE_ARN` | ARN retourné par la pile OIDC, obligatoire |
| `BEDROCK_MODEL_ID` | ID du modèle ou profil d'inférence autorisé dans le compte, obligatoire |
| `AWS_REGION` | Facultatif, `us-east-1` par défaut ; doit permettre les services et modèles utilisés |
| `STACK_PREFIX` | Facultatif, `alphaforge` par défaut ; conserver ce nom pour mettre à jour le même service |
| `SEC_USER_AGENT` | Nom d'équipe et courriel de contact pour les téléchargements SEC |

Ne pas ajouter de clés AWS permanentes. La politique IAM du service autorise les appels
Bedrock et `bedrock-agentcore:InvokeWebSearch`. Un accès modèle refusé par le compte ne
peut pas être résolu par la seule pipeline.

## 3. Déployer

1. Pousser le code, les workflows et les données sur `main`.
2. Actions → **Déployer AlphaForge sur AWS** → **Run workflow**, branche `main`.
3. Attendre les jobs de validation puis le job de déploiement.
4. L'URL et l'image ECR sont affichées dans le résumé du job.

Le contrôle distant charge l'accueil, vérifie `/api/health/`, puis lance une analyse
NVDA / 29 août 2024 / Mateo. Les deux agents doivent fonctionner via Bedrock ; la recherche
web doit être opérationnelle (zéro résultat est acceptable), l'ESG et les contrôles présents.
Cet essai consomme des appels Bedrock. Une panne web rend le job rouge même si ECS est déployé.
Un échec de ce contrôle ne supprime pas le service et ne restaure pas automatiquement
l'image précédente. Consulter le résumé et les logs CloudWatch pour diagnostiquer.

## Retour à une image précédente

Les images portent un tag unique commit/run/tentative et ECR refuse leur écrasement.
Conserver l'URI d'une image ayant passé les contrôles. Pour revenir à celle-ci :

```bash
aws cloudformation deploy --region us-east-1 \
  --stack-name alphaforge-service --template-file deploy/service.yml \
  --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --parameter-overrides Image=URI_IMAGE_PRECEDENTE BedrockModelId=MODELE_AUTORISE
```

Vérifier ensuite l'accueil et une analyse. Les paramètres existants non fournis sont
conservés lors d'une mise à jour CloudFormation.

## Déploiement local et arrêt

Depuis Bash avec AWS CLI, Docker démarré, Python et curl :

```bash
export AWS_PROFILE=workshop AWS_REGION=us-east-1
export BEDROCK_MODEL_ID=MODELE_AUTORISE
bash deploy/deploy.sh
```

Pour arrêter les ressources de service facturables : supprimer la pile
`alphaforge-service`. ECR est conservé par la politique `Retain` ; supprimer ses images
et le dépôt séparément lorsqu'ils ne sont plus utiles. Ce parcours est destiné à une
démo publique : les routes d'analyse ne disposent actuellement pas d'authentification.

Références : [ECS Express CloudFormation](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ecs-expressgatewayservice.html),
[permission de recherche AgentCore](https://docs.aws.amazon.com/cli/latest/reference/bedrock-agentcore/invoke-web-search.html).
