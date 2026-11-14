"""Vérifie qu'un modèle Bedrock gère les appels d'outils (Converse + toolConfig).

Variable d'environnement : BEDROCK_MODEL_ID (ID du modèle ou du profil d'inférence).
Région : us-east-1.

Usage :
    python scripts/tester_modele.py            # test d'appel d'outil
    python scripts/tester_modele.py --lister   # profils d'inférence contenant « gpt »
"""
import argparse
import json
import os
import sys

import boto3

REGION = "us-east-1"
MESSAGE = "Quel est l'écart entre NVDA et son marché le 2023-05-25 ?"
OUTIL = "calculer_ecart"

TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": OUTIL,
                "description": "Calcule l'écart de rendement d'un titre par rapport à son marché de référence à une date donnée.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string", "description": "Symbole du titre, ex. NVDA"},
                            "date": {"type": "string", "description": "Date AAAA-MM-JJ"},
                        },
                        "required": ["ticker", "date"],
                    }
                },
            }
        }
    ]
}


def lister() -> int:
    client = boto3.client("bedrock", region_name=REGION)
    trouves = []
    for type_profil in ("SYSTEM_DEFINED", "APPLICATION"):
        jeton = None
        while True:
            params = {"typeEquals": type_profil}
            if jeton:
                params["nextToken"] = jeton
            reponse = client.list_inference_profiles(**params)
            for profil in reponse.get("inferenceProfileSummaries", []):
                identifiant = profil["inferenceProfileId"]
                nom = profil.get("inferenceProfileName", "")
                if "gpt" in identifiant.lower() or "gpt" in nom.lower():
                    trouves.append((identifiant, nom, profil.get("status", "")))
            jeton = reponse.get("nextToken")
            if not jeton:
                break
    if not trouves:
        print("Aucun profil d'inférence contenant « gpt » dans us-east-1.")
        return 1
    for identifiant, nom, statut in trouves:
        print(f"{identifiant}\t{nom}\t{statut}")
    return 0


def tester() -> int:
    modele = os.environ.get("BEDROCK_MODEL_ID", "").strip()
    if not modele:
        sys.exit("Erreur : la variable d'environnement BEDROCK_MODEL_ID est absente "
                 "(voir --lister pour retrouver l'ID).")
    client = boto3.client("bedrock-runtime", region_name=REGION)
    try:
        reponse = client.converse(
            modelId=modele,
            messages=[{"role": "user", "content": [{"text": MESSAGE}]}],
            toolConfig=TOOL_CONFIG,
        )
    except Exception as erreur:  # affichage de l'erreur brute pour le diagnostic
        print(f"ERREUR lors de l'appel converse() : {erreur}")
        return 1

    contenu = reponse.get("output", {}).get("message", {}).get("content", [])
    appels = [bloc["toolUse"] for bloc in contenu if "toolUse" in bloc]
    if any(appel.get("name") == OUTIL for appel in appels):
        print("OK")
        return 0
    print("Pas de toolUse pour calculer_ecart. Réponse brute :")
    print(json.dumps(reponse, indent=2, ensure_ascii=False, default=str))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lister", action="store_true",
                        help="liste les profils d'inférence contenant « gpt »")
    args = parser.parse_args()
    return lister() if args.lister else tester()


if __name__ == "__main__":
    sys.exit(main())
