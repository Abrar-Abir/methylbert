# MethylBERT on M2 Pro — Feasibility Report

## Model Overview

MethylBERT is a BERT-based transformer (~110M params, 12 encoder layers, hidden size 768) for read-level DNA methylation classification. A 6-layer variant also exists and performs comparably.

---

## Feasibility by Task

### 1. Inference from Pretrained Model — ✅ Fully Feasible

- Pretrained weights available via `pip install methylbert` (PyPI) and GitHub
- Falls back to CPU automatically when no CUDA device detected (`with_cuda=False`)
- Paper reports <5 min per ctDNA sample on one V100 — expect ~10–30 min on M2 Pro CPU
- **No code changes needed to run inference on M2 Pro (CPU mode)**

### 2. Fine-tuning a Pretrained Model — ✅ Feasible (with patches for MPS acceleration)

- Paper fine-tunes 600–1000 steps, batch size 600, on 4× V100s
- On M2 Pro CPU: feasible but slow (hours for a full fine-tune)
- With MPS patches (see below): significantly faster using Apple's GPU via Metal backend
- Recommended: use the **6-layer variant** and reduce batch size to 32–64

### 3. Pre-training from Scratch — ⚠️ Impractical at Full Scale

- Paper pre-trained for 120k steps, batch size 256, on the full hg19 genome (~3B bases)
- Would take **weeks to months** on M2 Pro even with MPS
- **Feasible as a proof-of-concept** on a single chromosome (e.g., chr22, the smallest)
- Not recommended unless the goal is purely experimental

---

## Current MPS / Apple Silicon Support

**Status: None.** The codebase assumes CUDA or CPU only.

| File | Line(s) | Issue |
|------|---------|-------|
| `src/methylbert/trainer.py` | 75 | Device hardcoded: `"cuda:0"` or `"cpu"` |
| `src/methylbert/trainer.py` | 70 | AMP only enabled when CUDA available |
| `src/methylbert/trainer.py` | 206, 285, 417, 508, 713 | `torch.autocast(device_type="cuda"/"cpu")` — no `"mps"` |
| `src/methylbert/trainer.py` | 297, 424, 527 | `if "cuda" in self.device.type` — skipped on MPS |
| `src/methylbert/trainer.py` | 427 | `torch.cuda.synchronize()` — CUDA-only |
| `src/methylbert/utils.py` | 25 | `torch.cuda.manual_seed_all()` — no-op on MPS (harmless) |
| `src/methylbert/cli.py` | 70 | `--with_cuda` flag has no MPS equivalent |

---

## Required Patches for MPS Acceleration

### trainer.py — Device Selection (line 69–75)

```python
# BEFORE
self._config.amp = torch.cuda.is_available() and self._config.with_cuda
self.device = torch.device("cuda:0" if self._config.with_cuda else "cpu")

# AFTER
if self._config.with_cuda and torch.cuda.is_available():
    self.device = torch.device("cuda:0")
    self._config.amp = True
elif torch.backends.mps.is_available():
    self.device = torch.device("mps")
    self._config.amp = False  # AMP on MPS is limited; keep off for stability
else:
    self.device = torch.device("cpu")
    self._config.amp = False
```

### trainer.py — Autocast (lines 206, 285, 417, 508, 713)

```python
# BEFORE
with torch.autocast(device_type="cuda" if self._config.with_cuda else "cpu", enabled=self._config.amp):

# AFTER
device_type = self.device.type if self.device.type != "mps" else "cpu"
with torch.autocast(device_type=device_type, enabled=self._config.amp):
```

### trainer.py — CUDA-specific loss.mean() (lines 297, 424, 527)

```python
# BEFORE
if "cuda" in self.device.type:
    loss = loss.mean()

# AFTER
if self.device.type in ("cuda", "mps"):
    loss = loss.mean()
```

### cli.py — Add MPS flag (line 70)

```python
# ADD alongside --with_cuda
parser.add_argument("--with_mps", default=False, action="store_true",
                    help="training with MPS (Apple Silicon GPU)")
```

---

## Practical Setup for M2 Pro

```bash
# Install
pip install methylbert

# Check MPS is available
python -c "import torch; print(torch.backends.mps.is_available())"

# Fine-tune (CPU mode, no patches needed)
methylbert finetune \
    --pretrained_model <path> \
    --train_data <bam> \
    --batch_size 32 \
    --n_encoder_layers 6 \
    --num_workers 4

# Pre-training experiment (single chromosome, CPU mode)
methylbert pretrain \
    --genome chr22.fa \
    --batch_size 32 \
    --n_encoder_layers 6
```

### Recommended Settings for M2 Pro

| Parameter | Server (paper) | M2 Pro |
|-----------|---------------|--------|
| Encoder layers | 12 | 6 |
| Batch size | 256–600 | 32–64 |
| num_workers | 20–40 | 4–8 |
| Device | 4× V100 (32GB) | MPS or CPU |
| Fine-tune time (est.) | ~minutes | ~hours |
| Pre-train (full hg19) | feasible | impractical |
| Pre-train (single chr) | overkill | feasible (~days) |

---

## Summary

| Task | M2 Pro Feasibility | Patches Needed |
|------|-------------------|----------------|
| Inference | ✅ Works today (CPU) | None |
| Fine-tuning | ✅ Works (CPU); faster with MPS | 4 small patches for MPS |
| Pre-training (toy) | ⚠️ Feasible (single chr) | Same MPS patches |
| Pre-training (full) | ❌ Impractical | — |

The most impactful path is applying the MPS patches (~10 lines changed) and running fine-tuning with the 6-layer model at reduced batch size. This gives GPU-accelerated training on M2 Pro without needing a CUDA environment.
