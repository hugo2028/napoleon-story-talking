"""Télécharge les bases RAG de l'application depuis la Release GitHub du dépôt.

Les bases ne sont pas versionnées dans Git (trop lourdes pour Git LFS en accès public) :
elles sont publiées une fois pour toutes comme fichiers d'une Release, que GitHub sert sans quota.

Usage :
    python scripts/download_data.py           # télécharge ce qui manque ou est corrompu
    python scripts/download_data.py --force   # retélécharge tout

Seule la bibliothèque standard est utilisée.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

RELEASE_URL = "https://github.com/hugo2028/napoleon-story-talking/releases/download/data-v2"
DEST = Path(__file__).resolve().parent.parent / "data" / "rag"

# nom du fichier → (taille en octets, empreinte SHA-256)
FILES = {
    "napoleon_clean.sqlite": (
        246_747_136, "b38be0b05c34b3cd3f963807499572e0018eca543f40156f7b42bea561c14622"),
    "napoleon_memoirs.sqlite": (
        39_256_064, "a1f8ba7ee127ebf2a5e6440ffcf95c1575b139d465f997f2bb08839fda3fcf18"),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def is_valid(path: Path, size: int, digest: str) -> bool:
    return path.is_file() and path.stat().st_size == size and sha256(path) == digest


def download(name: str, size: int, digest: str) -> None:
    target = DEST / name
    partial = target.with_name(name + ".part")
    url = f"{RELEASE_URL}/{name}"
    print(f"Téléchargement de {name} ({size / 1e6:.0f} Mo)…")
    with urllib.request.urlopen(url) as resp, partial.open("wb") as out:
        done = 0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            print(f"\r  {done / 1e6:6.0f} / {size / 1e6:.0f} Mo", end="", flush=True)
    print()
    if not is_valid(partial, size, digest):
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"{name} : taille ou empreinte SHA-256 inattendue, fichier rejeté.")
    partial.replace(target)
    print(f"  {name} vérifié.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="retélécharger même si le fichier est valide")
    args = parser.parse_args()

    DEST.mkdir(parents=True, exist_ok=True)
    for name, (size, digest) in FILES.items():
        if not args.force and is_valid(DEST / name, size, digest):
            print(f"{name} : déjà présent et valide.")
            continue
        try:
            download(name, size, digest)
        except Exception as exc:  # réseau, HTTP, empreinte
            print(f"\nÉchec pour {name} : {exc}", file=sys.stderr)
            return 1
    print("Bases prêtes dans data/rag/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
