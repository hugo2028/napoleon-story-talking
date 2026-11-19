"""
Fusionne tous les JSONL d'entraînement en train.jsonl / val.jsonl
Supprime le champ _meta non standard.
"""
import json
import random
from pathlib import Path

SOURCES = [
    "napoleon-corpus/datasets/sft/training/memoires_1_training.jsonl",
    "napoleon-corpus/datasets/sft/training/memoires_2_training.jsonl",
    "napoleon-corpus/datasets/sft/training/memoires_3_training.jsonl",
    "napoleon-corpus/datasets/sft/training/memoires_4_training.jsonl",
    "napoleon-corpus/datasets/sft/training/memoires_5_training.jsonl",
    "napoleon-corpus/datasets/sft/training/lettres_amour_imperiales_training.jsonl",
    "napoleon-corpus/datasets/sft/training/anachronic_training.jsonl",
]

VAL_RATIO = 0.05  # 5% validation (~183 exemples)
SEED = 42

out_dir = Path("finetune/data")
out_dir.mkdir(parents=True, exist_ok=True)

examples = []
for path in SOURCES:
    with open(path) as f:
        for line in f:
            obj = json.loads(line)
            # Garder uniquement le champ messages
            examples.append({"messages": obj["messages"]})

random.seed(SEED)
random.shuffle(examples)

split = int(len(examples) * VAL_RATIO)
val_set = examples[:split]
train_set = examples[split:]

def write_jsonl(path, data):
    with open(path, "w") as f:
        for ex in data:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

write_jsonl(out_dir / "train.jsonl", train_set)
write_jsonl(out_dir / "val.jsonl", val_set)

print(f"Train : {len(train_set)} exemples → finetune/data/train.jsonl")
print(f"Val   : {len(val_set)} exemples → finetune/data/val.jsonl")
