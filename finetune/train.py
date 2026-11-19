"""
Fine-tuning QLoRA de Mistral-7B-Instruct-v0.3 sur le dataset Napoléon.
Lance sur une g5.xlarge (A10G 24GB).

Usage:
    python train.py
"""
import os
import json
import torch
from datasets import Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
)
from peft import LoraConfig
from trl import SFTTrainer, SFTConfig

# ── Config ────────────────────────────────────────────────────────────────────
MODEL_ID      = "mistralai/Mistral-7B-Instruct-v0.3"
TRAIN_FILE    = "data/train.jsonl"
VAL_FILE      = "data/val.jsonl"
OUTPUT_DIR    = "output/napoleon-mistral-7b"
HF_REPO       = None   # ex: "votre-pseudo/napoleon-mistral-7b" pour push auto

MAX_SEQ_LEN   = 2048
EPOCHS        = 3
BATCH_SIZE    = 2      # gradient_accumulation_steps compensera
GRAD_ACCUM    = 8      # effective batch = 16
LR            = 2e-4
LORA_R        = 16
LORA_ALPHA    = 32
LORA_DROPOUT  = 0.05

# ── Chargement des données ─────────────────────────────────────────────────────
def load_jsonl(path):
    with open(path) as f:
        return [json.loads(l) for l in f]

train_data = load_jsonl(TRAIN_FILE)
val_data   = load_jsonl(VAL_FILE)
train_ds   = Dataset.from_list(train_data)
val_ds     = Dataset.from_list(val_data)

print(f"Train: {len(train_ds)}  Val: {len(val_ds)}")

# ── Tokenizer ─────────────────────────────────────────────────────────────────
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "right"

# ── Modèle (QLoRA 4-bit) ──────────────────────────────────────────────────────
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)

model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    quantization_config=bnb_config,
    device_map="auto",
    torch_dtype=torch.bfloat16,
)
model.config.use_cache = False

# ── LoRA ──────────────────────────────────────────────────────────────────────
lora_config = LoraConfig(
    r=LORA_R,
    lora_alpha=LORA_ALPHA,
    lora_dropout=LORA_DROPOUT,
    bias="none",
    task_type="CAUSAL_LM",
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
)

# ── Entraînement ──────────────────────────────────────────────────────────────
training_args = SFTConfig(
    output_dir=OUTPUT_DIR,
    num_train_epochs=EPOCHS,
    per_device_train_batch_size=BATCH_SIZE,
    per_device_eval_batch_size=BATCH_SIZE,
    gradient_accumulation_steps=GRAD_ACCUM,
    learning_rate=LR,
    lr_scheduler_type="cosine",
    warmup_ratio=0.05,
    bf16=True,
    logging_steps=10,
    eval_strategy="steps",
    eval_steps=100,
    save_strategy="steps",
    save_steps=100,
    save_total_limit=2,
    load_best_model_at_end=True,
    report_to="none",
    max_seq_length=MAX_SEQ_LEN,
)

trainer = SFTTrainer(
    model=model,
    args=training_args,
    train_dataset=train_ds,
    eval_dataset=val_ds,
    peft_config=lora_config,
    processing_class=tokenizer,
)

trainer.train()
trainer.save_model(OUTPUT_DIR)
print(f"\nModèle sauvegardé dans {OUTPUT_DIR}")

# ── Push HuggingFace (optionnel) ───────────────────────────────────────────────
if HF_REPO:
    print(f"Push vers {HF_REPO}...")
    trainer.model.push_to_hub(HF_REPO)
    tokenizer.push_to_hub(HF_REPO)
    print("Done.")
