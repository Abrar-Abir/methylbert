# AGENTS.md

Agent spec for this repo. Optimize for execution fidelity, not prose.

## Objective

- Reproduce Jeong et al. 2025 MethylBERT fine-tuning experiments on Apple Silicon M2 Pro.
- Canonical paper: Nature Communications 16:788, DOI 10.1038/s41467-025-55920-z.
- Treat 2023 bioRxiv as superseded.

## Local docs

- methylbert.md: paper summary + experiment details.
- methylbert_m2pro_report.md: MPS patch details + benchmark notes.
- PLAN.md: local execution plan (Phase 0 done; Phase 1 next).

## Local repo layout

- Workspace root: `/Users/zer0/code/methylbert/` is the git repo (personal, no upstream remote). History:
  1. `Initial import: methylbert upstream f82f83b + workspace scaffolding` — pristine `CompEpigen/methylbert@f82f83b` vendored under `./methylbert/` alongside docs and scaffolding.
  2. `M2 Pro MPS patches (trainer/cli/utils/config)` — the local patch set as a single commit.
- Vendored upstream: `./methylbert/` is a plain directory (no inner `.git`). Base commit corresponds to `CompEpigen/methylbert@f82f83b`; any upstream refresh is done by re-vendoring files and rebasing/replaying the MPS patch commit on top.
- Python env: `./.venv/` (Python 3.11.15 via `uv venv --python 3.11`, editable install of `./methylbert/`).
  - Activate: `cd /Users/zer0/code/methylbert && source .venv/bin/activate`.
  - No `pip` in venv; use `uv pip install <pkg>` to add deps.
- Scripts: `./scripts/` (currently: `phase0_smoke.py`).
- Run artefacts: `./runs/<phase>/` (currently: `./runs/phase0/version_manifest.json`).
- Dataset/model dirs (`./data/`, `./models/`, `./results/`, `./configs/`) intentionally deferred until Phase 1 lands.

## Runtime constraints

- Hardware target: Apple M2 Pro, 16 GB unified memory.
- Device priority (always): cuda -> mps -> cpu.
- On MPS use torch.autocast(device_type="cpu") (no AMP path on mps).
- For M2 Pro defaults: batch 32-64, workers 4-8, 6-layer model for dev.
- Pretraining on this machine: chr22 only.

## Upstream patch requirements (applied in the `M2 Pro MPS patches` commit)

- `src/methylbert/trainer.py`: backend-aware device selection (cuda -> mps -> cpu); `autocast(device_type=...)` uses `self.device.type`, falling back to `"cpu"` when `device.type == "mps"`; `loss.mean()` gated on `device.type in ("cuda", "mps")`; multi-GPU `torch.cuda.synchronize()` branch removed.
- `src/methylbert/cli.py`: `--with_mps` flag added and forwarded to `MethylBertFinetuneTrainer(with_mps=...)`.
- `src/methylbert/utils.py`: `torch.cuda.manual_seed_all(seed)` guarded by `torch.cuda.is_available()`.
- `src/methylbert/config.py`: `('with_mps', False)` default added so the flag is always exposed on the config object.
- Any new patches must preserve the cuda -> mps -> cpu priority contract and default `with_cuda=False, with_mps=False` at the CLI layer.

## Pinned versions (verified working 2026-07-04)

- torch 2.4.1, transformers 4.44.2, tokenizers 0.19.1, numpy 2.1.1, pandas 2.2.2, scipy 1.14.1, scikit-learn 1.5.1, pysam 0.22.1, biopython 1.84, methylbert 2.0.2. All pinned in `methylbert/pyproject.toml`; do not upgrade without re-running the smoke test.
- Host: macOS 26.5.1 arm64, Python 3.11.15. `torch.backends.mps.is_built()` and `is_available()` both True.

## Smoke test

- `python scripts/phase0_smoke.py` must pass before any Phase >= 1 work. It loads `hanyangii/methylbert_hg19_6l`, runs one forward pass on MPS, and writes `./runs/phase0/version_manifest.json`.
- The pretrained checkpoint only contains the BERT trunk; `dmr_encoder` and `read_classifier` heads are re-initialized on load. The "Some weights ... newly initialized" warning is expected.

## Run manifest schema

Every run must emit a JSON manifest alongside its outputs with at least: `timestamp_utc`, `seed`, `device`, `python`, `platform`, `machine`, `torch`, `numpy`, `methylbert`, `transformers`, `tokenizers`, `pysam`, `methylbert_git_sha`, and any run-specific fields (dataset accession, config path, hyperparameters). Use `scripts/phase0_smoke.py` as the reference implementation.

## Model availability (verified 2026-07-04)

- Public pretrained only; no public fine-tuned checkpoints.
- Preferred dev base model: hanyangii/methylbert_hg19_6l.
- Available hubs: hanyangii/methylbert_hg19_{12l,8l,6l,4l,2l}, hanyangii/methylbert_mm10_4l.

## Experiment index

- E1 simulated benchmark.
- E2 pretraining ablation (hg19 vs mm10 vs none) on GSE137880.
- E3 bulk purity estimation from E2 setup.
- E4 low-fraction (<10%) purity from E2 setup.
- E5 CRC ctDNA detection: GSE97693 + GSE149438.
- E6 PDAC ctDNA detection: GSE63123 + GSE149438.
- E7 prostate-epithelium proportion (atlas-based): train GSE186458, test EGAS50000000806.
- E8 5-way leukocyte deconvolution (atlas-based): GSE186458.
- Total fine-tuned models in paper: 8.

## Dataset access rules

- Open: GSE137880, GSE97693, GSE63123, GSE149438.
- Mixed: GSE186458 (processed data open; raw FASTQ controlled on EGA).
- Controlled: EGAS50000000806 (DAC required).
- Reproducible without controlled access: E1-E6 and E8.
- E7 requires EGA approval for exact test-set replication.

## Storage guardrails

- Do not download full GSE97693 tar (~718 GB); subset to the 341 CRC methylation cells.
- Expect GSE186458 processed atlas download around ~328 GB.
- Remaining required datasets are comparatively small (<20 GB combined).

## Implementation policy

- Keep code backend-agnostic and deterministic where possible.
- Preserve experiment parity with paper configs and figures.
- Track config/version/seed per run.
- Prefer modular, testable changes over monolithic edits.

## Minimal setup

- Already provisioned. Reuse `./.venv/`; activate with `source .venv/bin/activate` from the workspace root.
- Re-provision from scratch (if the venv is lost):
  1. `uv venv --python 3.11 .venv`
  2. `source .venv/bin/activate && uv pip install -e ./methylbert`
  3. `python scripts/phase0_smoke.py`
- The MPS patches live in the outer git history; a fresh checkout of this repo already has them applied under `./methylbert/`. No inner git operations are required.
- Upstream source: https://github.com/CompEpigen/methylbert

## CLI gotchas

- `methylbert --help` at the top level errors: `--help must be one of ['preprocess_finetune', 'finetune', 'deconvolute']`. Use `methylbert <subcommand> --help`.
- CLI defaults are `--with_cuda=False --with_mps=False`, which means CPU. Pass `--with_mps` explicitly on M2 Pro.
- The `MethylBertFinetuneTrainer` config default is `with_cuda=True`; construct with `with_cuda=False, with_mps=True` when invoking the trainer from Python.
- After `set_seed(...)`, `torch.use_deterministic_algorithms(False)` — MPS is not bit-exact and enabling deterministic mode will raise on unsupported ops.