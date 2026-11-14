"""Envoie le dossier data/ dans un bucket S3 (préfixe « data/ »).

Variable d'environnement obligatoire : ALPHAFORGE_BUCKET (nom du bucket).
Identifiants AWS : ceux de l'environnement (rôle, profil, variables AWS_*), jamais dans le code.
Le script n'efface rien dans le bucket ; un fichier de même clé est remplacé.

Usage : python scripts/envoyer_s3.py [--dry-run]
"""
import argparse
import os
import sys
from pathlib import Path

import boto3

REGION = "us-east-1"
PREFIXE = "data/"
RACINE_DATA = Path(__file__).resolve().parent.parent / "data"
IGNORES = {".DS_Store"}
DOSSIERS_IGNORES = {".ipynb_checkpoints", "__pycache__"}


def fichiers_locaux():
    for chemin in sorted(RACINE_DATA.rglob("*")):
        relatif = chemin.relative_to(RACINE_DATA)
        if not chemin.is_file() or chemin.name in IGNORES:
            continue
        if DOSSIERS_IGNORES & set(relatif.parts):
            continue
        yield chemin, PREFIXE + relatif.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="affiche sans envoyer")
    args = parser.parse_args()

    bucket = os.environ.get("ALPHAFORGE_BUCKET", "").strip()
    if not bucket:
        sys.exit("Erreur : la variable d'environnement ALPHAFORGE_BUCKET est absente.")

    s3 = boto3.client("s3", region_name=REGION)
    envoyes = 0
    for chemin, cle in fichiers_locaux():
        if args.dry_run:
            print(f"[dry-run] {chemin} -> s3://{bucket}/{cle}")
        else:
            s3.upload_file(str(chemin), bucket, cle)
            print(f"envoyé : {chemin} -> s3://{bucket}/{cle}")
        envoyes += 1
    print(f"{envoyes} fichier(s) {'à envoyer' if args.dry_run else 'envoyé(s)'} ; rien n'a été supprimé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
