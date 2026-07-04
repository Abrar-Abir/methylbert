# PLAN.md — Reproducing MethylBERT (Jeong et al. 2025) on M2 Pro

Reproduction plan for the open-data experiments from [methylbert.md](methylbert.md), scoped to hardware and access constraints documented in [AGENTS.md](AGENTS.md) and [methylbert_m2pro_report.md](methylbert_m2pro_report.md).

## Scope

**In scope (6 fine-tuning experiments — all training + test data openly available):**

| # | Experiment | Data | Paper figure |
|---|-----------|------|--------------|
| 1 | Simulated read benchmark (complexity × length × coverage) | Synthetic (beta-binomial generator) | Fig. 2 |
| 2 | Pre-training ablation (hg19 vs mm10 vs none) | GSE137880 | Fig. 3B–E |
| 3 | Bulk tumour purity estimation (pseudo-bulks) | GSE137880 | Fig. 4A–E |
| 4 | Low-tumour-fraction (ctDNA-like) purity | GSE137880 | Fig. 5A–B |
| 5 | CRC ctDNA early detection | GSE97693 (train) + GSE149438 (train+test) | Fig. 5C |
| 6 | PDAC ctDNA early detection | GSE63123 (train) + GSE149438 (train+test) | Fig. 5D |

**Deferred:**

- **Exp 7** (prostate-epithelium proportion) — test set `EGAS50000000806` is controlled-access; requires EGA DAC. Skipped entirely per user decision.
- **Exp 8** (5-way leukocyte deconvolution) — needs subset of GSE186458 processed atlas; **deferred until disk is provisioned**. Add back in a later revision of this plan when storage is available.

---

## Phase 0 — Environment setup (M2 Pro) — **DONE 2026-07-04**

**Goal:** working `methylbert` install with MPS acceleration enabled.

**Outcome:**

- Upstream `CompEpigen/methylbert@f82f83b` vendored into `./methylbert/` (plain directory, no inner `.git`). Everything is tracked by the outer workspace repo.
- Outer git repo initialized at `/Users/zer0/code/methylbert/` on branch `main`, tracking `origin` = `https://github.com/Abrar-Abir/methylbert.git` (public). History: pristine upstream import → MPS patches → docs → phase-0 manifest refresh.
- Python 3.11.15 venv at `./.venv/` provisioned via `uv venv --python 3.11`; `./methylbert/` installed editable with pinned deps (torch 2.4.1, transformers 4.44.2, numpy 2.1.1, pysam 0.22.1, methylbert 2.0.2).
- MPS patches applied as a single outer-repo commit (`628e979`, `M2 Pro MPS patches (trainer/cli/utils/config)`):
  - `src/methylbert/trainer.py` — backend-aware device selection (cuda -> mps -> cpu); autocast falls back to `cpu` on MPS; `loss.mean()` gated on `device.type in ("cuda", "mps")`; multi-GPU `torch.cuda.synchronize()` branch removed.
  - `src/methylbert/cli.py` — `--with_mps` flag added and forwarded to `MethylBertFinetuneTrainer`.
  - `src/methylbert/utils.py` — `torch.cuda.manual_seed_all` guarded by `torch.cuda.is_available()`.
  - `src/methylbert/config.py` — `('with_mps', False)` default added.
- Smoke test [scripts/phase0_smoke.py](scripts/phase0_smoke.py) passes: `torch.backends.mps.is_available()` True; `methylbert finetune --help` exposes `--with_mps`; `hanyangii/methylbert_hg19_6l` loads and produces a `(2, 2)` classification-logits tensor on `mps:0` from one forward pass; trainer constructed with `with_cuda=False, with_mps=True` prints `The model is loaded on MPS`.
- Version manifest recorded at [runs/phase0/version_manifest.json](runs/phase0/version_manifest.json); use it as the schema template for every subsequent run.
- Repro seed baseline: `SEED=42`; `torch.use_deterministic_algorithms(False)` (MPS is not bit-exact).

**Reactivation for later phases:**

```bash
cd /Users/zer0/code/methylbert
source .venv/bin/activate
git status  # outer repo; should be clean on main (tracking origin/main)
python scripts/phase0_smoke.py  # sanity check before starting Phase 1+
```

**Known gotchas** (also noted in AGENTS.md):

- `methylbert --help` at the top level errors; use `methylbert <subcommand> --help`.
- Loading a pretrained checkpoint re-initializes `dmr_encoder` and `read_classifier` heads — this is expected and fine-tuning trains them.
- Venv has no `pip`; use `uv pip install <pkg>` to add deps.

---

## Phase 1 — Data acquisition & preprocessing

**Goal:** all open datasets downloaded and processed to BAM + methylation calls consistent with the paper's pipeline.

- Datasets to fetch (see [AGENTS.md](AGENTS.md) for accessions, sizes, and access notes):
  - `GSE137880` — DLBCL + non-neoplastic B-cell WGBS (exps 2–4).
  - `GSE97693` — CRC scBS-seq; **subset to the 341 CRC methylation cells** via SRA Run Selector (avoid the ~718 GB full tar).
  - `GSE63123` — PDAC primary-tumour WGBS (exp 6 training).
  - `GSE149438` — plasma targeted BS-seq (exps 5–6 train + test).
- Preprocessing pipeline (matches paper Methods → *Data preparation*):
  - Adapter/quality trim with TrimGalore 0.6.6.
  - Align to hg19 with Bismark 0.22.3 (paired-end where applicable; re-align unmapped reads single-end for the plasma data).
  - Deduplicate with Picard MarkDuplicates.
  - For any array-baseline comparisons, convert BAMs → bedGraph → beta-values via MethylDackel + Methrix (only if reproducing Houseman baseline).
- Track per-sample QC (mapping rate, dedup rate, mean coverage) and store a manifest linking accession → local path → intended experiment.

**Storage budget check:** all four datasets combined fit comfortably under 20 GB after subset filtering — verify against local disk before proceeding.

**Exit criteria:** processed BAM + methylation calls for each dataset, plus a manifest and QC summary.

---

## Phase 2 — DMR calling & region selection

**Goal:** produce the DMR sets each downstream experiment relies on.

- Use DSS with paper parameters: `delta=0.2`, `p<0.05`, `min_CpGs=4`, `min_length=50 bp`, `merge_dist=50 bp`.
- Per-experiment region sets:
  - Exps 2–4 (DLBCL vs B-cell): 50 tumour-hypermethylated + 50 tumour-hypomethylated DMRs, plus a "top 100 by areaStat" set.
  - Exps 5–6 (ctDNA): top 100 DMRs by areaStat between tumour reference and healthy plasma.
- For Exp 1 (simulated), select the 100 CpG islands with the highest CpG count on hg19 — no DMR calling needed.

**Exit criteria:** BED/TSV region files for each experiment, stored alongside their manifest.

---

## Phase 3 — Fine-tuning (experiments 1–6)

**Goal:** train one fine-tuned MethylBERT per experiment on M2 Pro.

- Baseline architecture: 6 encoder layers (`hanyangii/methylbert_hg19_6l`); batch size 32–64; workers 4–8; MPS device with autocast disabled (per patch notes).
- Per-experiment training setup:
  - **Exp 1:** run the read-level simulator (`CompEpigen/methylseq_simulation`, Zenodo `10.5281/zenodo.14025025`) for every combination of α ∈ {0.1, 1, 2, 3} × β=5, read length {150, 500}, coverage grid, plus the CpG-specific pattern variant. Fine-tune one model per condition. This is the largest sweep — schedule accordingly.
  - **Exp 2:** three training runs — pretrained hg19, pretrained mm10, and no pre-training (random init) — on the same DLBCL/B-cell 100-DMR split. Log training + validation curves every 10 steps to reproduce Fig. 3C.
  - **Exp 3:** one fine-tune on DLBCL vs B-cell, top-100 areaStat DMRs (reuse or extend the Exp 2 hg19 model).
  - **Exp 4:** reuse the Exp 3 model; no new fine-tuning required (test-time only).
  - **Exp 5:** fine-tune on CRC scBS-seq (341 cells) + 32 healthy plasma samples.
  - **Exp 6:** fine-tune on 7 PDAC primary-tumour samples + 32 healthy plasma samples.
- For every run: fix seed, log hyperparameters, save best checkpoint by validation loss, and store training curves.

**Exit criteria:** one saved checkpoint + training log per experiment (Exp 1 = many; Exps 2–6 = one each; Exp 4 reuses Exp 3).

---

## Phase 4 — Evaluation & inference

**Goal:** run each experiment's evaluation and derive the metrics reported in the paper.

- **Exp 1:** classification accuracy per (complexity, length, coverage) cell. Compare against paper's HMM/CancerDetector/DISMIR baselines only if resources allow; otherwise report MethylBERT curves alone and note baseline omission.
- **Exp 2:** confusion matrices + P(cell type = Tumour | read) distributions for pretrained-hg19, pretrained-mm10, no-pretrain models on held-out reads.
- **Exp 3:**
  - Generate 20 in-silico pseudo-bulks from held-out DLBCL + B-cell reads with controlled tumour ratios spanning 0–100%.
  - Estimate tumour purity via the MLE + Bayesian inversion pipeline; report with and without skewness adjustment.
  - Compute Fisher information per DMR-quality tier (very high / high / medium / low areaStat).
  - Reconstruct cell-type-specific methylation levels per DMR.
- **Exp 4:** generate 10 pseudo-bulks with tumour fraction <10%; report median absolute error and Spearman correlation.
- **Exps 5–6:** run inference on held-out plasma samples (14 healthy + 40 CRC; remaining healthy + 44 stage-clarified PDAC); report per-stage tumour cell fraction distributions and Mann-Whitney vs healthy.
- Every evaluation must emit: raw predictions, aggregated metric table, and the plot(s) corresponding to the paper figure.

**Exit criteria:** metric tables + figures for Fig. 2, Fig. 3B–E, Fig. 4A–E, Fig. 5A–D.

---

## Phase 5 — Comparison against published results

**Goal:** quantify how closely the M2 Pro reproduction matches the paper.

- For each experiment, produce a side-by-side table: paper metric vs. reproduced metric, with tolerance thresholds decided per experiment (tighter for deterministic sims, looser for stochastic ctDNA runs).
- Flag any experiment whose reproduced result falls outside tolerance; open an investigation issue with logs and seeds attached.
- Record all deviations from the paper (batch size, layer count, device, sample subsets, any dataset substitutions) in a single reproduction report.

**Exit criteria:** reproduction report with per-experiment pass/fail and documented deviations.

---

## Cross-cutting concerns

- **Determinism:** fix seeds (`torch`, `numpy`, `random`, `methylbert.utils.set_seed`); document that MPS is not bit-exact — expect small numeric drift vs CUDA.
- **Configuration:** every run driven by a config file (hyperparameters, dataset paths, seed, git SHA of the patched fork). Configs stored with results.
- **Version pinning:** freeze `torch`, `methylbert`, `bismark`, `trim_galore`, `picard`, `dss` versions; capture in the manifest per run.
- **Compute budget:** Exp 1's sweep is the dominant cost — parallelize per-condition runs sequentially and consider reducing coverage grid density if wall time becomes untenable. Exps 5–6 are the next largest (largest training sets).
- **Reruns:** each phase's outputs are idempotent inputs to the next; a failed experiment can be re-run without redoing data prep.
- **Layout:** repo layout for `data/`, `models/`, `results/`, `configs/` is intentionally left open — decide when Phase 1 lands.

---

## Open questions (revisit before starting)

- **Repository layout for artefacts** — first-pass convention now in use: `./data/<accession>/`, `./models/<experiment>/`, `./results/<experiment>/`, `./configs/<experiment>.yaml`, `./runs/<phase-or-experiment>/`. Ratify or adjust when Phase 1 lands.
- **Exp 8** (leukocyte deconvolution) — add back once disk is provisioned; needs a scoped GSE186458 download plan.
- **Baseline reproduction** — whether to reproduce competing baselines (CancerDetector, DISMIR, Houseman) or cite paper values only. Decision affects Phase 4 scope.
- **Exp 1 simulation sweep** — whether to trim the α × length × coverage grid for time.
