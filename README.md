# Replication package: temporal evaluation of ML for anticipating vulnerability disclosures in npm dependencies

This package accompanies the article

> Keawpitak, W., & Kantavat, P. *How Reliable Is Machine Learning for Anticipating Vulnerability Disclosures in Software Dependencies? A Temporal Evaluation Against Libyear and Package-History Baselines.* Manuscript prepared for submission to *Intelligent Systems with Applications*.

It contains the dataset, the fixed source data, the code that produced every number in the article and its Supplementary Material, the per-instance predictions and results, and manifests with hashes and library versions. All analyses are exploratory and retrospective (see Section 7 of the article).

## Contents

The folder layout is the one in which the analyses were executed, so the scripts run without changes.

| Path | Content |
|---|---|
| `data/cohort/projects.json` | Sampling frame: 250 GitHub projects with popularity stratum |
| `data/processed/paired.csv` (`.parquet`) | **Main dataset**: 29,379 direct-dependency instances (238 projects × 4 year-end snapshots, 2020–2023) with the nine features, labels, matched advisory IDs and snapshot commit SHAs |
| `data/processed/all_available.csv`, `instance_audit.csv` | All projects available per snapshot; every instance with its inclusion/exclusion reason |
| `cache/snapshots/<origin>/` | Snapshot of each project's root `package.json` at each reference date (commit SHA, commit date, file SHA-256 and the dependency fields; see *Changes made for publication*) |
| `cache/npm/` | npm release histories (version → publication time) as retrieved in October 2026 |
| `cache/ghsa/` | GitHub Security Advisories (npm) as retrieved, with pagination evidence |
| `config/experiment.json`, `publication/protocol/` | Configurations fixed before the runs (reference dates, horizon, features, model parameters, seed) |
| `src/` | Pipeline code: snapshot collection and dataset construction (`pipeline.py`, `semver_batch.cjs`), main evaluation (`publication_completion.py`), sensitivity analyses (`four_step_*.py`, `robustness_analysis.py`, `semver_variants.cjs`, `publication_lockfile_sensitivity.py`), audits and validators |
| `tests/` | Boundary tests for SemVer handling and time windows |
| `results/` | Outputs of the first pipeline run (temporal metrics, associations, predictions) |
| `publication/experiments/rq_completion/` | **Main results** (Table 4, Table 5, Sections 4–5): metrics, bootstrap intervals, drop-column and native importances, per-instance predictions per origin (`<origin>/predictions_wide.csv`), executed source and frozen manifest |
| `publication/experiments/four_step/` | Review budgets (Fig. 3, S6), calibration and thresholds (S9), training-label and weighting sensitivities, seen/unseen coverage |
| `publication/experiments/lockfile_sensitivity/` | Lockfile versions (Table S21) |
| `publication/audits/` | Cache chronology, dependence structure, lockfile inventory, sampling provenance |
| `robustness/` | Cohort, latest-version, window and exact-version variants (Table S20): data, results, manifests |
| `verification/` | Independent re-computations and checks: `topk/` (prior-advisory rule and Top-K, Fig. 3, S6), `exposure/` (prior-advisory rule, popularity and advisory history as covariates), `package_disjoint/` (Section 5.3), `range_checks/` (NVD comparison and open-ended ranges, Section 5.2, S10), `advisory_asof/` (point-in-time training labels, Table S24), `round3/` (NVD pre-publication, high/critical only, seeds), `label_audit/` (cross-source label checks), `checks.py`, `round1_analyses.py`, `round2_numbers.py` and `results/` |
| `manifests/` | Environment, collection status of every project × snapshot, dataset and run metadata, SHA-256 of sources and executed code (`manifests/code/`) |
| `replicability/data/` | Earlier dataset from which the sampling frame was frozen (provenance only; not used for any reported number) |
| `DATA_DICTIONARY.md` | Column definitions of the datasets, prediction files and main result files |
| `MANIFEST.json` | SHA-256 and size of every file in this package |

Two caches are stored as zip archives to keep the file count small; unzip them in place before rerunning the analyses that use them:

| Archive | Unzip to | Used by |
|---|---|---|
| `verification/exposure/cache.zip` | `verification/exposure/cache/` (npm daily downloads; GHSA advisories published before 2021) | `exposure/`, `topk/`, `package_disjoint/` |
| `verification/advisory_asof/db_2022-12-31.zip`, `db_2023-12-31.zip` | `verification/advisory_asof/db_<date>/` (`advisories/github-reviewed` of [github/advisory-database](https://github.com/github/advisory-database) at commits `fc303372d4da618bfa0ce361eaed92d4eb978941` (2022-12-31T21:31:30Z) and `308f9cac9cc06441474024e0bdf71c1cc6149811` (2023-12-31T21:31:36Z)) | `advisory_asof/pit_labels.py` |

## Environment

The results were produced on Windows 11 with Python 3.12.14, numpy 2.5.4, pandas 3.0.1, scikit-learn 1.9.1, scipy 1.18.1, XGBoost 3.0.5, duckdb 1.5.6, and npm `semver` 7.8.5 on Node.js 24 (`manifests/environment.json`, `publication/experiments/rq_completion/frozen_manifest.json`). Create an environment with these versions:

```text
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt        # Windows: .venv\Scripts\python
```

The scripts first look for vendored libraries in `tools/vendor` and `publication/tools/vendor` (not included) and otherwise use the installed ones. Run every command from the package root.

## Rerunning the analyses

The analyses run in four stages (Supplementary Section S11).

**Stages 3 and 4 run offline from the stored data.** Each script overwrites its own output files, so run it in a copy of the package and compare the new outputs with the published ones. `publication_completion.py` resumes from the `complete.json` marker of each origin; delete `publication/experiments/rq_completion/<origin>/complete.json` to refit:

```text
python src/publication_completion.py run                    # main backtest: metrics, intervals, importances, predictions
python verification/round3/round3_analyses.py               # reproduces the 24 main metrics; NVD pre-publication; high/critical only; seeds
python verification/topk/topk_prior_advisory.py             # prior-advisory rule and Top-K (needs exposure/cache)
python verification/exposure/exposure_analysis.py           # popularity and advisory history as covariates (needs exposure/cache)
python verification/package_disjoint/package_disjoint.py    # package-disjoint evaluation, ~10 min (needs exposure/cache)
python verification/advisory_asof/pit_labels.py             # point-in-time training labels (needs db_<date>/)
python verification/range_checks/range_checks.py analyze    # NVD comparison (uses range_checks/cache/nvd)
python src/four_step_fit.py && python src/four_step_evaluate.py   # budgets, calibration, training-label sensitivities

python compare_outputs.py <published package folder> <rerun folder>   # numeric comparison of all JSON outputs
```

`src/four_step_fit.py` and `src/four_step_evaluate.py` refuse to overwrite a frozen run; move `publication/experiments/four_step/fit_manifest.json` and `evaluation_manifest.json` out of the copy first.

`src/validate_publication_completion.py`, `src/validate_four_step.py`, `src/validate_robustness.py` and `src/validate_lockfile_sensitivity.py` recheck the stored predictions and result arithmetic with the standard library only; they also check the recorded file hashes, so run them on the unmodified package (a rerun rewrites prediction files whose floating-point values can differ in the last digit).

**Tested reruns.** In a new Python 3.12 environment installed from PyPI with `requirements.txt` (Windows 11, November 2026), the offline scripts listed above reproduced every number in their JSON outputs within 1e-9 (`compare_outputs.py`); per-instance predictions agreed within 1e-12.

**Stages 1 and 2 need the network** (GitHub, the npm Registry and the GitHub REST API) and Node.js with `semver` 7.8.5:

```text
python src/pipeline.py init | collect | build | evaluate | report    # or: all
```

`collect` makes bare partial clones of each project's default branch (`cache/git/`, not included) and reads `package.json` at the last commit on or before each reference date; cached snapshots are reused. Because GitHub, npm and GHSA change over time, a fresh collection may differ slightly from the stored one, which is why the fixed source data are included. The lockfile analysis (`src/publication_lockfile_sensitivity.py`) also needs `cache/git/`. The scripts that call Node.js (`src/pipeline.py`, `src/robustness_analysis.py`, `src/four_step_dataset_audit.py`, `verification/range_checks/range_checks.py`) take the runtime from the constant `RUNTIME` near the top of each file (`<home>/.cache/codex-runtimes/codex-primary-runtime/dependencies`, holding `node/bin/node.exe` and `node/node_modules/semver`); point it to your own Node.js installation. The network stages of the checks are `verification/exposure/fetch_exposure.py`, `verification/range_checks/range_checks.py fetch` (NVD API 2.0) and the database checkouts for `advisory_asof/` (sparse checkout of `advisories/github-reviewed` at the commits above).

## Changes made for publication

The package was exported from the working folder by an allowlist (`tools/build_replication_package.py` in the authors' project). Compared with the executed state:

- **package.json snapshots** keep only `name`, `version`, `dependencies` and `devDependencies`, the only fields the pipeline reads; other fields, which include personal data of third-party maintainers (author and contributor e-mail addresses), were removed. `package_json_sha256` still identifies the original file, which can be retrieved from the project at `commit_sha`. Hashes of the snapshot files recorded in `manifests/` therefore refer to the unreduced files.
- **Host-specific paths** in metadata, logs and READMEs were rewritten: paths inside the executed folder are now relative to the package root (so that scripts that re-hash their recorded inputs work when run from the root), and other prefixes became `<exam>`, `<project>` (the authors' working folders), `<runtime>` and `<home>`. Code files are byte-identical to the executed versions.
- **`replicability/data/`** holds four files of the earlier dataset from which the 250-project sampling frame was frozen; they are recorded as protected inputs and read by `src/audit_sampling_provenance.py`.
- **Not included:** bare Git clones (`cache/git/`, large and re-creatable), vendored library binaries, the authors' internal code-review notes, working documents in Thai, and scripts of an earlier export that are not used for the article.

## Licences

- Code (`src/`, `tests/`, `verification/**/*.py`, `*.cjs`, `compare_outputs.py`): MIT License (`LICENSE`).
- Data and results created by the authors (datasets, features, labels, predictions, metrics, manifests): Creative Commons Attribution 4.0 International (`LICENSE-DATA.md`).
- Third-party data keep their original terms: GitHub Advisory Database content (`cache/ghsa/`, the advisory archives) is CC BY 4.0 (GitHub); npm Registry metadata (`cache/npm/`, npm download counts) is subject to the npm terms; `package.json` dependency fields belong to the respective projects and their licences; NVD data (`verification/range_checks/cache/`) are public-domain U.S. government data. See `LICENSE-DATA.md`.

## Citation

Please cite the article and this package (`CITATION.cff`). The project list includes the top 100 most-starred JavaScript repositories from EvanLi/Github-Ranking (version of 3 June 2026, commit 47b6c1e).
