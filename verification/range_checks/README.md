# Range checks on the GHSA labels (exploratory, 2026-10-24)

Two checks that use data and method only, with no human review:

1. **NVD CPE ranges.** NVD is a partly independent source. Does NVD agree that `used_version` is affected?
2. **Ranges with no lower bound.** How many positives depend only on ranges such as `< 4.17.21`? What happens to the results without them?

Inputs are read-only. All numbers come from `range_checks_results.json`, which stores unrounded values.

| File | Content |
|---|---|
| `range_checks.py` | `fetch` gets the CVEs from the NVD API 2.0 into `cache/nvd/` (≤ 5 requests per 30 s, retry with backoff). `analyze` runs offline from the cache. |
| `range_checks_results.json` | All results, unrounded |
| `nvd_disagreements.csv` | Every GHSA/NVD disagreement: one line per unique (package, used_version, advisory), with row and project counts |
| `nvd_advisory_status.csv` | NVD status and matching level for each (advisory, package), plus the version-set comparison |
| `fetch.log`, `analysis.log` | Run logs |
| `cache/nvd/*.json` | Raw NVD responses: 286 CVEs, fetched 2026-10-24 |

How to rerun, from `snapshot_sensitivity/`:

```
$py = '<runtime>\python\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
& $py verification\range_checks\range_checks.py fetch     # only fetches CVEs missing from cache/nvd
& $py verification\range_checks\range_checks.py analyze   # offline, about 1-2 min
```

The library path is set up exactly as in `executed_source.py`: `publication/tools/vendor` and `tools/vendor`, giving numpy 2.5.4, sklearn 1.9.1 and xgboost 3.0.5. Version matching uses node semver 7.8.5 with the same rule as `src/semver_batch.cjs`: commas become spaces, then `validRange` and `satisfies`.

## Common steps

- **Rows.** All 794 positives, plus the 289 hard negatives. A hard negative has label 0, but its package has a reviewed, non-withdrawn GHSA advisory published in (origin, window_end] whose range does not cover `used_version`. This is the same definition as `label_audit/cross_source.py`.
- **Label check.** All 1,083 rows were re-labelled from the in-window advisory entries. Every matched GHSA set equals `matched_ghsa_ids` (0 mismatches).
- **Reproduction.** The main backtest was reproduced **exactly**, with a maximum |Δ| of 0 against `rq_completion/metrics.json`:
  - AP, ROC-AUC and recall@10% for full LR/RF/XGB, drop_libyear ×3, libyear_only_lr and libyear > 1.
  - The package-cluster CIs for full − drop_libyear and full_lr − libyear_only_lr, checked against `intervals.json`.
- **Instance-level libyear statistics** also match thesis Table 5.10:
  - Cohen's d: 0.342 / 0.292 / −0.095 / 0.079
  - pair-level d: 0.255 / 0.296 / 0.066 / 0.467
  - libyear AUC: 0.534 / 0.579 / 0.503 / 0.528

## Check 1: NVD CPE ranges

**Method.** For each matched advisory (positives) or in-window advisory (hard negatives) with a CVE id, the NVD CVE 2.0 record is read. The steps are:

1. **Which entries count.** Only CPE matches with `vulnerable = true` and part `a` are kept, from non-negated nodes.
2. **Matching the product to the npm package.** Names are lower-cased and non-alphanumerics are removed. The levels are:
   - `exact`: the product equals the package name, or scope+name for a scoped package.
   - `affix`: equal after removing a leading "node" and a trailing "js" (for example `next` ↔ `next.js`).
   - **Primary analysis** = `exact` + `affix`.
   - Ambiguous fallbacks, counted only in the "inclusive" analysis:
     - `fallback_name_overlap`: exactly one product whose name contains, or is contained in, the package name (≥ 4 characters). Example: `lodash-es` → `lodash:lodash`.
     - `fallback_single_product`: the CVE lists only one application product. Example: `codecov` → `codecov:nodejs_uploader`.
3. **Platform filter.** Within the matched product, only entries with `target_sw` ∈ {node.js, nodejs, node, npm, \*, -} are kept. This drops same-named products from other ecosystems.
4. **Version check.**
   - Bounds (`versionStart/EndIncluding/Excluding`) are compared using npm semver ordering. Non-semver bounds are coerced, and those rows are flagged.
   - Version `*` with no bounds means "all versions".
   - An explicit version with no bounds means only that version.
   - Version `-` with no bounds cannot be used.
5. **Verdict.** An advisory is NVD-affected if any of its usable entries covers `used_version`. A row is NVD-affected if any of its usable advisories is.

**How independent NVD is.** Only partly. NVD analysts often build the CPE configuration from the GHSA or vendor advisory, and many npm CVEs are issued by GitHub as the CNA. Agreement is therefore an upper bound on independent confirmation. Disagreement shows that two curated sources differ. It does not show which one is right.

### Coverage

Unit: unique matched (advisory, package) pairs. The two groups overlap, so "all" is 301 pairs.

| | Positives' matched advisories | Hard negatives' in-window advisories |
|---|---|---|
| (advisory, package) pairs | 259 | 66 |
| with a CVE id | 249 (96.1%) | 64 |
| NVD record has configurations | 228 | 57 |
| usable, primary (exact / affix) | 208 (189 / 19) | 52 (51 / 1) |
| usable, fallback (name-overlap / single-product) | 12 (6 / 6) | 4 (3 / 1) |
| no CVE | 10 | 2 |
| NVD has no configurations (Awaiting Analysis / Deferred etc.) | 20 | 7 |
| product matched only for non-Node targets | 4 | 0 |
| matched product, version "-" only | 3 | 0 |
| CVE rejected in NVD | 1 | 0 |
| no product match (several unrelated products) | 1 | 1 |

At row level, 783/794 positives (98.6%) have at least one matched advisory with a CVE. Usable NVD data covers:

| | Primary | Inclusive |
|---|---|---|
| Positives | 712/794 rows (89.7%) | 733 |
| Hard negatives | 257/289 rows (88.9%) | 272 |

Coverage is lowest for 2023 positives (156/211 primary), because many 2024 CVEs have no NVD analysis yet.

### Agreement (primary matching; Wilson 95%)

| Snapshot | Positives NVD-affected (rows) | Hard negatives NVD-not-affected (rows) | Positive unique triples | Hard-negative unique triples |
|---|---|---|---|---|
| 2020-12-31 | 155/163 = 95.1% [90.6, 97.5] | 36/38 = 94.7% [82.7, 98.5] | 77/89 = 86.5% | 15/21 = 71.4% |
| 2021-12-31 | 246/260 = 94.6% [91.2, 96.8] | 120/123 = 97.6% [93.1, 99.2] | 190/199 = 95.5% | 37/40 = 92.5% |
| 2022-12-31 | 109/133 = 82.0% [74.6, 87.6] | 60/61 = 98.4% [91.3, 99.7] | 87/92 = 94.6% | 21/22 = 95.5% |
| 2023-12-31 | 150/156 = 96.2% [91.9, 98.2] | 4/35 = 11.4% [4.5, 26.0] | 66/71 = 93.0% | 3/11 = 27.3% |
| **All** | **660/712 = 92.7% [90.5, 94.4]** | **220/257 = 85.6% [80.8, 89.4]** | **420/451 = 93.1% [90.4, 95.1]** | **76/94 = 80.9% [71.7, 87.5]** |

- **Inclusive matching** gives almost the same totals: positives 680/733 = 92.8% and hard negatives 235/272 = 86.4%.
- **Row-level intervals are too narrow.** The same package/version/advisory appears in many projects, so the Wilson intervals on rows overstate precision. The unique (package, used_version, advisory) triples are the more honest denominator.
- **Advisory-level version sets.** For the 241 primary-usable (advisory, package) pairs, every published non-prerelease npm version was checked against both ranges:
  - 181 (75.1%) give identical affected sets.
  - NVD is strictly broader for 29 and strictly narrower for 30.
  - 1 differs in both directions.
  - The median Jaccard similarity is 1.0.

### Disagreements (`nvd_disagreements.csv`)

There are 37 distinct hard-negative rows and 53 positive rows. One more positive disagrees on only one of its two matched advisories. All of them concern a range boundary. None comes from a product mismatch, apart from one `fallback_name_overlap` case.

| Category | Instance rows | Main cases |
|---|---|---|
| Hard negative, **NVD broader**: NVD has no lower bound where GHSA has one | 37 rows (41 row×advisory pairs) | webpack 1.x–4.x vs GHSA-4vvj-4cpr-p986. GHSA `>= 5.0.0-alpha.0, < 5.94.0`; NVD `< 5.94.0`. 31 rows, all in 2023. Also immer 1.x/3.x (3 advisories), async 0.x/1.x, semver 1.1.4 |
| Positive, **NVD narrower at the bottom**: NVD lower bound above `used_version` | 21 | electron 1.8–7.3. GHSA `< 9.4.0` / `< 11.5.0`; NVD starts at 9.0.0 / 10.1.0. Also rollup 0.36–0.53 (NVD `>= 0.59.0`) |
| Positive, NVD lists explicit versions only | 20 | axios `=1.5.1` (GHSA `>= 0.8.1, < 0.28.0`), ajv `=6.12.2`, ejs `=3.1.6`, gh-pages `=3.1.0`, grunt-karma `=4.0.1`, quill |
| Positive, **NVD narrower at the top**: NVD upper bound ≤ `used_version` | 20 | request 2.88.2: GHSA `<= 2.88.2`, NVD `<= 2.88.1`. 15 rows, 2022. Also node-sass 5–6 (NVD `<= 4.14.1`), axios 0.18.1, html-parse-stringify2 (fallback) |

- **Where they fall.** The 2022 positive dip comes from request and axios. The 2023 hard-negative dip comes from one webpack advisory.
- **Libyear of the disagreeing rows.** Mean libyear of the disagreeing hard negatives is 1.70 / 7.55 / 9.60 / 3.01 years, against negatives overall at 0.71–1.34. If NVD's broader ranges were used, older versions would become positives.

### Lower bounds: GHSA vs NVD

Unit: unique positive (advisory, package, used_version), primary NVD. The NVD entries that cover `used_version` were inspected.

| | NVD covering entry has no lower bound | NVD covering entry has a lower bound / exact version | NVD not affected |
|---|---|---|---|
| GHSA unbounded below (342) | 296 (86.5%) | 21 | 25 |
| GHSA bounded (109) | 26 | 77 | 6 |

## Check 2: advisories with no lower bound

**Definitions.**

- **Unbounded below.** A matched advisory is unbounded below for an instance if the comparator set of its GHSA range that covers `used_version` has no `>=`, `>` or exact lower bound above 0.0.0. Examples: `< 4.17.21`, `<= 2.88.2`, `>= 0.0.0, < x`, `> 0.0.0`, `*`. This uses the node semver `Range` parse.
- **Unbounded-only instance.** ALL of the instance's matched advisories are unbounded below.
- **Secondary rule ("effectively unbounded").** This also counts a bounded range whose lower bound is ≤ the package's lowest published version. It flags exactly the same instances, so no separate backtest is reported. 13 bounded (advisory, package) pairs start below 1.0.0, for example url-parse `>= 0.1.0`, path-to-regexp `>= 0.2.0` and axios `>= 0.8.1`. They are listed in the JSON.

| Snapshot | Positives | Unbounded-only | Share | Unique (adv, pkg) unbounded | Top packages among unbounded-only |
|---|---|---|---|---|---|
| 2020-12-31 | 175 | 136 | 77.7% | 42/56 | lodash 49, grunt 15, electron 11, axios 9 |
| 2021-12-31 | 268 | 181 | 67.5% | 67/93 | karma 30, grunt 30, marked 13 |
| 2022-12-31 | 140 | 73 | 52.1% | 35/45 | request 17, postcss 17, electron 10 |
| 2023-12-31 | 211 | 140 | 66.4% | 43/65 | rollup 34, express 25, body-parser 13 |
| All | 794 | 530 | 66.8% | | |

Only 22 positives mix an unbounded and a bounded matched advisory.

### Libyear of positives by range type (instance level)

| Snapshot | Mean libyear: negatives | unbounded-only positives | bounded positives | d main | d without unbounded-only (A) | d relabelled (B) | d unbounded-only vs negatives | d pair-level main → A |
|---|---|---|---|---|---|---|---|---|
| 2020-12-31 | 0.71 | 1.23 | 0.95 | 0.342 | 0.186 | 0.176 | 0.389 | 0.255 → 0.018 |
| 2021-12-31 | 0.93 | 1.68 | 0.82 | 0.292 | −0.067 | −0.077 | 0.464 | 0.296 → 0.075 |
| 2022-12-31 | 1.13 | 1.01 | 0.90 | −0.095 | −0.127 | −0.126 | −0.065 | 0.066 → 0.145 |
| 2023-12-31 | 1.34 | 1.90 | 0.72 | 0.079 | −0.295 | −0.299 | 0.268 | 0.467 → 0.006 |

- **libyear AUC without the unbounded-only positives:** 0.481 / 0.509 / 0.493 / 0.447. The main values are 0.534 / 0.579 / 0.503 / 0.528.
- **Unique positive package/version pairs fall** from 81/130/71/94 to 19/40/25/30.

### Sensitivity backtests

The protocol is unchanged: fixed parameters, expanding window, seed 42.

- **Variant A** drops unbounded-only positives from both train and test.
- **Variant B** relabels them 0.

Each cell shows AP / ROC-AUC / recall@10%. Recall uses stable order, as in `executed_source.py`. For the 0/1 rule, the tie-aware expected recall is shown in parentheses.

**Main.** Test positives 268 / 140 / 211; training positives 175 / 443 / 583.

| Model | 2021-12-31 | 2022-12-31 | 2023-12-31 |
|---|---|---|---|
| full_lr | 0.116 / 0.758 / 0.280 | 0.088 / 0.803 / 0.429 | 0.115 / 0.741 / 0.355 |
| full_rf | 0.068 / 0.669 / 0.194 | 0.049 / 0.787 / 0.150 | 0.284 / 0.850 / 0.536 |
| full_xgb | 0.064 / 0.652 / 0.104 | 0.050 / 0.778 / 0.314 | 0.113 / 0.787 / 0.365 |
| drop_libyear_lr | 0.102 / 0.762 / 0.250 | 0.087 / 0.811 / 0.421 | 0.123 / 0.734 / 0.351 |
| drop_libyear_rf | 0.066 / 0.681 / 0.190 | 0.058 / 0.806 / 0.271 | 0.284 / 0.844 / 0.498 |
| drop_libyear_xgb | 0.064 / 0.661 / 0.119 | 0.045 / 0.762 / 0.364 | 0.109 / 0.778 / 0.294 |
| libyear_only_lr | 0.056 / 0.579 / 0.157 | 0.019 / 0.503 / 0.036 | 0.032 / 0.528 / 0.118 |
| libyear > 1 | 0.043 / 0.567 / 0.116 (0.144) | 0.019 / 0.496 / 0.086 (0.098) | 0.031 / 0.530 / 0.128 (0.116) |

**A (drop).** Test positives 87 / 67 / 71; prevalence 1.21% / 0.92% / 0.99%; training positives **39** / 126 / 193.

| Model | 2021-12-31 | 2022-12-31 | 2023-12-31 |
|---|---|---|---|
| full_lr | 0.035 / 0.737 / 0.264 | 0.088 / 0.824 / 0.672 | 0.135 / 0.841 / 0.451 |
| full_rf | 0.023 / 0.668 / 0.184 | 0.042 / 0.827 / 0.433 | 0.315 / 0.859 / 0.507 |
| full_xgb | 0.022 / 0.676 / 0.218 | 0.036 / 0.835 / 0.582 | 0.286 / 0.853 / 0.535 |
| drop_libyear_lr | 0.031 / 0.737 / 0.253 | 0.116 / 0.835 / 0.672 | 0.125 / 0.843 / 0.507 |
| drop_libyear_rf | 0.025 / 0.690 / 0.264 | 0.049 / 0.827 / 0.433 | 0.319 / 0.871 / 0.577 |
| drop_libyear_xgb | 0.023 / 0.683 / 0.230 | 0.037 / 0.837 / 0.582 | 0.290 / 0.860 / 0.521 |
| libyear_only_lr | 0.012 / 0.509 / 0.057 | 0.010 / 0.493 / 0.030 | 0.011 / 0.553 / 0.028 |
| libyear > 1 | 0.012 / 0.505 / 0.115 (0.104) | 0.009 / 0.469 / 0.075 (0.082) | 0.009 / 0.399 / 0.070 (0.044) |

**B (relabel 0).** Test positives 87 / 67 / 71; prevalence 1.18% / 0.91% / 0.97%.

| Model | 2021-12-31 | 2022-12-31 | 2023-12-31 |
|---|---|---|---|
| full_lr | 0.034 / 0.732 / 0.218 | 0.090 / 0.828 / 0.672 | 0.118 / 0.836 / 0.451 |
| full_rf | 0.023 / 0.649 / 0.310 | 0.040 / 0.835 / 0.299 | 0.306 / 0.826 / 0.451 |
| full_xgb | 0.021 / 0.673 / 0.092 | 0.038 / 0.844 / 0.597 | 0.304 / 0.837 / 0.423 |
| drop_libyear_lr | 0.030 / 0.735 / 0.253 | 0.114 / 0.836 / 0.672 | 0.124 / 0.838 / 0.451 |
| drop_libyear_rf | 0.028 / 0.691 / 0.368 | 0.046 / 0.841 / 0.433 | 0.312 / 0.863 / 0.521 |
| drop_libyear_xgb | 0.021 / 0.674 / 0.161 | 0.045 / 0.848 / 0.597 | 0.303 / 0.831 / 0.394 |
| libyear_only_lr | 0.012 / 0.506 / 0.057 | 0.010 / 0.493 / 0.030 | 0.011 / 0.555 / 0.028 |
| libyear > 1 | 0.012 / 0.503 / 0.115 (0.102) | 0.009 / 0.469 / 0.075 (0.082) | 0.009 / 0.397 / 0.070 (0.043) |

AP is not comparable across variants, because prevalence roughly halves to a third.

### Package-cluster CIs

Each cell shows ΔAP [95% CI] and ΔAUC [95% CI]. The bootstrap uses 1,000 draws, seed 42, and package clusters. At least 999 draws were valid.

| Difference | Variant | 2021-12-31 | 2022-12-31 | 2023-12-31 |
|---|---|---|---|---|
| full_lr − drop_libyear_lr | Main | +0.013 [−0.022, +0.064]; −0.005 [−0.017, +0.004] | +0.001 [−0.018, +0.014]; −0.007 [−0.019, −0.001] | −0.008 [−0.076, +0.002]; +0.007 [−0.002, +0.017] |
| | A | +0.004 [−0.020, +0.026]; −0.000 [−0.016, +0.019] | −0.028 [−0.119, +0.001]; −0.010 [−0.049, +0.005] | +0.010 [−0.012, +0.057]; −0.003 [−0.016, +0.005] |
| | B | +0.003 [−0.019, +0.024]; −0.003 [−0.024, +0.018] | −0.024 [−0.111, −0.000]; −0.008 [−0.042, +0.005] | −0.006 [−0.027, +0.001]; −0.003 [−0.011, +0.004] |
| full_rf − drop_libyear_rf | Main | +0.002 [−0.028, +0.046]; −0.013 [−0.028, +0.003] | −0.009 [−0.029, +0.000]; −0.019 [−0.037, +0.001] | −0.001 [−0.026, +0.021]; +0.005 [−0.004, +0.017] |
| | A | −0.003 [−0.010, +0.003]; −0.022 [−0.046, −0.002] | −0.007 [−0.048, +0.002]; −0.000 [−0.036, +0.031] | −0.004 [−0.020, +0.009]; −0.011 [−0.049, +0.016] |
| | B | −0.005 [−0.015, −0.001]; −0.042 [−0.065, −0.019] | −0.007 [−0.045, +0.002]; −0.005 [−0.038, +0.043] | −0.006 [−0.018, +0.003]; −0.037 [−0.085, −0.002] |
| full_xgb − drop_libyear_xgb | Main | +0.000 [−0.011, +0.029]; −0.009 [−0.026, +0.009] | +0.005 [−0.007, +0.030]; +0.017 [−0.026, +0.048] | +0.004 [−0.007, +0.014]; +0.009 [−0.005, +0.020] |
| | A | −0.000 [−0.004, +0.005]; −0.007 [−0.032, +0.020] | −0.001 [−0.006, +0.001]; −0.003 [−0.014, +0.005] | −0.004 [−0.017, +0.010]; −0.007 [−0.025, +0.007] |
| | B | −0.001 [−0.007, +0.002]; −0.000 [−0.033, +0.027] | −0.007 [−0.029, +0.002]; −0.004 [−0.039, +0.059] | +0.001 [−0.001, +0.002]; +0.006 [−0.001, +0.017] |
| full_lr − libyear_only_lr | Main | +0.059 [+0.022, +0.125]; +0.179 [+0.108, +0.241] | +0.069 [+0.015, +0.187]; +0.300 [+0.142, +0.391] | +0.083 [+0.011, +0.225]; +0.213 [+0.038, +0.418] |
| | A | +0.023 [+0.004, +0.088]; +0.228 [+0.117, +0.361] | +0.078 [+0.001, +0.275]; +0.331 [−0.013, +0.454] | +0.124 [+0.005, +0.435]; +0.287 [+0.135, +0.409] |
| | B | +0.022 [+0.003, +0.087]; +0.226 [+0.109, +0.369] | +0.080 [+0.001, +0.276]; +0.335 [−0.018, +0.454] | +0.107 [+0.005, +0.389]; +0.281 [+0.120, +0.410] |
| full_rf − libyear_only_lr | Main | +0.012 [−0.012, +0.081]; +0.090 [+0.012, +0.170] | +0.030 [+0.013, +0.060]; +0.284 [+0.194, +0.342] | +0.252 [+0.031, +0.501]; +0.322 [+0.192, +0.439] |
| | A | +0.011 [−0.001, +0.039]; +0.159 [+0.044, +0.298] | +0.031 [+0.001, +0.154]; +0.334 [+0.092, +0.417] | +0.304 [+0.005, +0.651]; +0.306 [+0.176, +0.423] |
| | B | +0.011 [−0.001, +0.045]; +0.143 [+0.010, +0.295] | +0.029 [+0.002, +0.113]; +0.342 [+0.122, +0.431] | +0.295 [+0.004, +0.648]; +0.271 [+0.147, +0.405] |
| full_xgb − libyear_only_lr | Main | +0.007 [−0.015, +0.043]; +0.073 [−0.020, +0.163] | +0.031 [+0.009, +0.084]; +0.275 [+0.167, +0.344] | +0.081 [+0.017, +0.218]; +0.259 [+0.151, +0.373] |
| | A | +0.010 [−0.002, +0.031]; +0.167 [+0.070, +0.280] | +0.026 [+0.001, +0.075]; +0.342 [+0.061, +0.492] | +0.275 [+0.007, +0.619]; +0.299 [+0.201, +0.372] |
| | B | +0.009 [−0.001, +0.026]; +0.168 [+0.078, +0.283] | +0.028 [+0.002, +0.081]; +0.351 [+0.123, +0.511] | +0.293 [+0.005, +0.648]; +0.282 [+0.189, +0.360] |

## Interpretation (exploratory; associations only)

- **NVD mostly agrees with GHSA, but the check is not fully independent.**
  - Where usable NVD data exists, NVD also marks about 93% of positives as affected (unique triples 93.1% [90.4, 95.1]).
  - It also marks about 86% of hard negatives as not affected (unique triples 80.9%).
  - Every disagreement concerns a range boundary, mostly the **lower** bound, and each comes from a few advisories: webpack 2023, request, electron, rollup, axios.
  - NVD often copies GHSA or vendor data, so this supports the ranges only partly. It does not show which source is correct where they differ.
  - The thesis statement that range content "was not checked independently" can now be narrowed to "checked against NVD for about 90% of rows, with the agreement above."
- **Most positives rest on ranges with no lower bound.**
  - Two-thirds of positives (530/794; 52–78% per snapshot) are matched only by ranges like `< x`.
  - NVD gives the same no-lower-bound shape for 86.5% of these triples. So this is mainly how both databases record vulnerabilities (affected "since the beginning"), not a GHSA-only artefact.
  - Still, an unbounded range assigns every older version to the positive class by construction. Some of those versions may predate the vulnerable code.
- **The small positive libyear association is carried by the unbounded-range positives.**
  - Without them, instance-level d falls to 0.19 / −0.07 / −0.13 / −0.29. Pair-level d falls to 0.02 / 0.08 / 0.14 / 0.01. Libyear AUC is 0.45–0.51.
  - The thesis reports a positive association in 2021, and at pair level in every year, mostly 2021 and 2023. That association is therefore not robust to how ranges are written.
  - The reverse reading is just as mechanical. Bounded ranges by design cover only newer release lines, so dropping unbounded ranges selects positives with low libyear. Neither labeling is the "true" one. The libyear–disclosure relation depends on this label-construction choice and should be reported as fragile.
- **"Models > libyear rules" survives both variants.**
  - Full models reach ROC-AUC 0.65–0.86, against 0.49–0.56 for libyear-only LR and 0.40–0.51 for libyear > 1.
  - Most full − libyear_only_lr ΔAP and ΔAUC intervals exclude 0. The exceptions are the same kind as in the main run:
    - ΔAP for RF/XGB in 2021, whose lower bounds are −0.001 / −0.002.
    - ΔAUC for LR in 2022, whose lower bound is about −0.015.
  - With the unbounded positives removed, the libyear > 1 rule ranks **below** chance in 2023 (AUC 0.40).
- **"Libyear adds no detectable value" survives.**
  - All full − drop_libyear ΔAP intervals include 0 or lie below it.
  - Three intervals now exclude 0 on the negative side, meaning libyear makes results worse:
    - B 2021 RF, ΔAP −0.005 [−0.015, −0.001]
    - B 2022 LR, ΔAP −0.024 [−0.111, −0.000]
    - several RF ΔAUC
  - No interval favours including libyear.
- **The algorithm ranking is not stable either.**
  - In A/B, LR still has the highest AP in 2021–2022. In 2023, RF and XGB are close (0.315 / 0.286 in A), while in the main run XGB was 0.113.
  - These variants have few events: 39 training positives for the 2021 test origin (EPV ≈ 4.3) and only 67–87 test positives. All differences are uncertain.
- **Overlap with other explanations.**
  - **NVD published before origin (round 3, F-3).** That group contains 18 / 29 / 1 / 0 positives per snapshot. Of these, 18 / 9 / 1 / 0 are also unbounded-only.
  - **Size.** The unbounded-only group is far larger: 530 against 48 positives. It is mostly a different set of rows.
  - **Concentration.** It is concentrated in a few large positive packages: lodash, grunt, karma, rollup and express.
  - This check does not separate range shape from package identity.
