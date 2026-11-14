"""Point d'entrée de la solution AlphaForge AI (squelette).

Test rapide de l'accès à Amazon Bedrock depuis us-east-1.
"""
import boto3


def check_bedrock() -> None:
    client = boto3.client("bedrock", region_name="us-east-1")
    models = client.list_foundation_models()["modelSummaries"]
    print(f"Bedrock OK : {len(models)} modèles visibles")


if __name__ == "__main__":
    check_bedrock()
