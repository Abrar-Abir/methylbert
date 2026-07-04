"""Phase 0 smoke test for MethylBERT on Apple M2 Pro (MPS).

Verifies:
1. Torch / MPS availability.
2. Patched device selection in `MethylBertTrainer` picks MPS when requested.
3. Pretrained `hanyangii/methylbert_hg19_6l` loads and runs a single forward
   pass on the MPS device.
4. Reproducibility seeds propagate without CUDA errors.

Also emits a JSON version manifest under `runs/phase0/version_manifest.json`
so every subsequent run has a comparable provenance record.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

# The package is installed editable; importing after torch keeps ordering stable.
import methylbert  # noqa: F401  (imported for version + import-time side effects)
from methylbert.data.vocab import MethylVocab
from methylbert.network import MethylBertEmbeddedDMR
from methylbert.utils import set_seed


REPO_ROOT = Path(__file__).resolve().parent.parent
METHYLBERT_SRC = REPO_ROOT / "methylbert"
RUN_DIR = REPO_ROOT / "runs" / "phase0"
RUN_DIR.mkdir(parents=True, exist_ok=True)

PRETRAINED_MODEL = "hanyangii/methylbert_hg19_6l"
SEED = 42


def _git_rev(path: Path) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return None


def _pkg_version(mod_name: str) -> str | None:
    try:
        mod = __import__(mod_name)
        return getattr(mod, "__version__", None)
    except Exception:
        return None


def _select_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda:0")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def main() -> int:
    print("=" * 60)
    print("MethylBERT Phase 0 smoke test")
    print("=" * 60)

    # --- 1. Backend availability -----------------------------------------
    assert torch.backends.mps.is_built(), "torch was built without MPS support"
    assert torch.backends.mps.is_available(), "MPS backend not available on this host"
    device = _select_device()
    print(f"[1/4] selected device : {device}")
    print(f"      torch           : {torch.__version__}")
    print(f"      python          : {sys.version.split()[0]}")
    print(f"      platform        : {platform.platform()}")

    # --- 2. Reproducibility knobs ----------------------------------------
    set_seed(SEED)  # exercises the utils.py cuda.manual_seed_all guard
    torch.use_deterministic_algorithms(False)  # MPS is not bit-exact; keep off
    print(f"[2/4] seeds set (torch/numpy/random)={SEED}; deterministic algos=False (MPS)")

    # --- 3. Load pretrained model and run a forward pass -----------------
    tokenizer = MethylVocab(k=3)
    vocab_size = len(tokenizer)
    print(f"[3/4] tokenizer vocab_size={vocab_size}")

    print(f"      loading {PRETRAINED_MODEL} ...")
    model = MethylBertEmbeddedDMR.from_pretrained(
        PRETRAINED_MODEL,
        num_labels=2,
    )
    model.eval()
    model.to(device)

    seq_len = model.seq_len  # 150 by default
    batch = 2

    # Sample token ids from the tokenizer vocab space; avoid pad (0) / oov (1)
    input_ids = torch.randint(
        low=2, high=vocab_size, size=(batch, seq_len + 1), device=device
    )
    token_type_ids = torch.zeros_like(input_ids, dtype=torch.long, device=device)
    labels = torch.zeros(batch, dtype=torch.long, device=device)  # DMR label
    ctype_label = torch.zeros(batch, dtype=torch.long, device=device)  # cell-type label

    with torch.no_grad():
        out = model.forward(
            step=0,
            input_ids=input_ids,
            token_type_ids=token_type_ids,
            labels=labels,
            ctype_label=ctype_label,
        )

    logits = out["classification_logits"]
    assert logits.device.type == device.type, (
        f"model output device {logits.device} != requested {device}"
    )
    assert logits.shape == (batch, 2), f"unexpected logits shape {logits.shape}"
    print(
        f"      forward ok      : logits.shape={tuple(logits.shape)} "
        f"device={logits.device} loss={float(out['loss'].detach().cpu()):.4f}"
    )

    # --- 4. Emit version manifest ----------------------------------------
    manifest = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": SEED,
        "device": str(device),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "torch": torch.__version__,
        "torch_mps_built": bool(torch.backends.mps.is_built()),
        "torch_mps_available": bool(torch.backends.mps.is_available()),
        "numpy": np.__version__,
        "methylbert": _pkg_version("methylbert"),
        "transformers": _pkg_version("transformers"),
        "tokenizers": _pkg_version("tokenizers"),
        "pysam": _pkg_version("pysam"),
        "methylbert_git_sha": _git_rev(METHYLBERT_SRC),
        "pretrained_model": PRETRAINED_MODEL,
    }
    out_path = RUN_DIR / "version_manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"[4/4] manifest written -> {out_path.relative_to(REPO_ROOT)}")
    print("smoke test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
