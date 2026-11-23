# Review round 3: extra analyses (exploratory, 2026-10-24, post-fix data)

- Script: `round3_analyses.py` (run from the project root: `PYTHONIOENCODING=utf-8 python verification/round3/round3_analyses.py`, about 75 s). It writes `round3_results.json` with unrounded values.
- Inputs (read-only): `robustness/data/date_12_paired.csv` (the same file `executed_source.py` uses, 29,379 rows), `cache/ghsa/advisories.json`, `publication/experiments/rq_completion/*`, `lockfile_sensitivity/*`, `four_step/seen_unseen_coverage.json`, `verification/advisory_asof/pit_results.json`, `robustness/data/semver_*.csv`.
- Protocol: the same as `rq_completion/executed_source.py`. It uses fixed parameters, an expanding-window backtest, seed 42 and XGBoost 3.0.5 from `publication/tools/vendor`. AP is computed with `score_plan`/`fast_ap`, imported from `executed_source.py`.
- Checks that passed:
  - All 24 main metrics were reproduced: full LR/RF/XGB, drop_libyear ×3, libyear_only_lr and libyear>1, each for 3 origins. AP, AUC and recall@10% match exactly (max |ΔAP| = 0).
  - The package-cluster bootstrap reproduces all 18 matching CIs in `rq_completion/intervals.json` to 1e-12.
- Recall@10% follows the protocol: stable order, top ⌈0.1n⌉. For the tied rule libyear>1, the JSON also holds the tie-aware expected recall (`recall10_expected`), which is the one Table 5.15 uses.
- All results are exploratory. They are test-set intervals only and are not adjusted beyond what is stated.

## F-3 Positives whose matched advisory was public in NVD on or before the origin

A matched advisory counts as "pre-public" when `nvd_published_at <= origin 23:59:59.999Z`. Advisories with no NVD date count as not pre-public (2/6/1/2 such advisories per snapshot).

| Snapshot | Positives | All matched pre-public | Any matched pre-public | Unique advisories pre-public | Mean libyear: all-pre positives / other positives / negatives |
|---|---|---|---|---|---|
| 2020-12-31 | 175 | 18 (10.3%) | 30 (17.1%) | 5 / 54 | 4.97 / 0.62 / 0.71 |
| 2021-12-31 | 268 | 29 (10.8%) | 29 (10.8%) | 9 / 93 | 2.28 / 1.30 / 0.93 |
| 2022-12-31 | 140 | 1 (0.7%) | 1 (0.7%) | 1 / 45 | 0.00 / 0.97 / 1.13 |
| 2023-12-31 | 211 | 0 | 0 | 0 / 65 | – / 1.50 / 1.34 |

**Sensitivity backtest.** The primary variant removes positive rows whose matched advisories were **all** pre-public, from both train and test. This removes 18+29 training rows for the 2022 test and leaves the 2023 test unchanged. Two secondary variants are in the JSON: drop if **any** advisory was pre-public, and relabel to 0 if all were. Values are AP / AUC / recall@10%, main → drop-all.

| Model | 2021-12-31 (test pos 268→239) | 2022-12-31 (140→139) | 2023-12-31 (211→211) |
|---|---|---|---|
| full LR | .116/.758/.280 → .094/.763/.326 | .088/.803/.429 → .097/.820/.424 | .115/.741/.355 → .115/.750/.365 |
| full RF | .068/.669/.194 → .050/.647/.130 | .049/.787/.150 → .053/.804/.216 | .284/.850/.536 → .283/.852/.498 |
| full XGB | .064/.652/.104 → .052/.636/.138 | .050/.778/.314 → .037/.744/.129 | .113/.787/.365 → .105/.794/.284 |
| drop_libyear LR | .102/.762/.250 → .096/.764/.331 | .087/.811/.421 → .097/.816/.424 | .123/.734/.351 → .128/.732/.355 |
| drop_libyear RF | .066/.681/.190 → .058/.656/.167 | .058/.806/.271 → .057/.808/.230 | .284/.844/.498 → .287/.854/.507 |
| drop_libyear XGB | .064/.661/.119 → .046/.634/.109 | .045/.762/.364 → .039/.749/.223 | .109/.778/.294 → .102/.793/.270 |
| libyear-only LR | .056/.579/.157 → .049/.555/.138 | .019/.503/.036 → .019/.505/.036 | .032/.528/.118 → .032/.528/.118 |

- Pre-public positives are concentrated in the 2020 and 2021 snapshots and have much higher libyear than other positives. In 2020, positives that were not pre-public have a lower mean libyear than negatives (0.62 vs 0.71). Some of libyear's weak association in early snapshots may therefore reflect advisories that were already known.
- In the drop-all variant the best algorithm per origin by AP stays LR/LR/RF. libyear-only stays near chance (AUC 0.51–0.56). Removing libyear still changes AP very little.
- In the "drop any" variant, libyear-only LR for the 2021 test falls to AUC 0.445 (below chance). That baseline's 2021 result depends on a handful of pre-public 2020 positives. Absolute AP for 2021 drops for every model, partly because the test positives change.

## F-22 Severity

Positive instances by the maximum severity of their matched advisories ("medium" is GHSA's term for moderate):

| Snapshot | Positives | low | medium | high | critical | Prevalence: main → high/critical |
|---|---|---|---|---|---|---|
| 2020 | 175 | 0 | 63 (36.0%) | 92 (52.6%) | 20 (11.4%) | 2.37% → 1.52% |
| 2021 | 268 | 0 | 97 (36.2%) | 132 (49.3%) | 39 (14.6%) | 3.63% → 2.32% |
| 2022 | 140 | 0 | 55 (39.3%) | 54 (38.6%) | 31 (22.1%) | 1.91% → 1.16% |
| 2023 | 211 | 19 (9.0%) | 81 (38.4%) | 109 (51.7%) | 2 (0.9%) | 2.89% → 1.52% |

**Outcome sensitivity.** The label is 1 only if a matched advisory is high or critical, and models are refitted on that label. Values are AP / AUC / recall@10%.

| Model | 2021 (pos 171) | 2022 (pos 85) | 2023 (pos 111) |
|---|---|---|---|
| full LR | .093/.742/.345 | .054/.749/.400 | .036/.618/.117 |
| full RF | .083/.667/.135 | .054/.774/.424 | .189/.861/.577 |
| full XGB | .058/.665/.216 | .051/.764/.412 | .122/.834/.495 |
| drop_libyear LR | .070/.753/.363 | .058/.736/.400 | .036/.622/.117 |
| drop_libyear RF | .092/.701/.205 | .061/.762/.447 | .195/.872/.541 |
| drop_libyear XGB | .055/.665/.216 | .040/.739/.412 | .110/.832/.495 |
| libyear-only LR | .038/.517/.129 | .013/.508/.035 | .020/.600/.153 |
| libyear > 1 (rule; expected recall) | .024/.515/.110 | .011/.482/.089 | .020/.597/.153 |

- The full models stay above the libyear baselines in every origin. libyear-only stays weak (AUC 0.51–0.60).
- The ranking changes:
  - LR leads on AP only in 2021. In 2022 LR and RF tie (.0541 vs .0541). RF leads in 2023.
  - LR falls sharply in 2023 (AUC .741 → .618).
  - drop_libyear RF has a higher AP than full RF in all three origins.
- Positives are few (85–171), so these numbers are less stable than the main run.

## F-19 Multiplicity

The bootstrap draws 1,000 package clusters (seed 42, the same draws as `executed_source.intervals`). The two-sided bootstrap p-value is p = 2·min((#≤0+1)/(n+1), (#≥0+1)/(n+1)), floored at 0.002. Holm's correction is applied within each family of nine contrasts.

| Family (9 contrasts) | CI excludes 0 | Holm-adjusted p < .05 | Contrasts that do not survive Holm |
|---|---|---|---|
| ΔAP full − libyear_only_lr | 7 | 7 | RF 2021 (+.012 [−.012, .081], p_holm .50), XGB 2021 (+.007 [−.015, .044], p_holm .50) |
| ΔAUC full − libyear_only_lr | 8 | 6 | RF 2021 (+.090 [.012, .170], p .028 → .060), LR 2023 (+.213 [.038, .418], p .020 → .060), XGB 2021 (CI includes 0) |
| ΔAP full − drop_libyear | 0 | 0 | all nine (smallest p_holm .63, RF 2022) |
| ΔAP full − libyear_only (same algorithm; the Table 5.16 comparison) | 9 | 9 | none (largest p_holm .022, XGB 2021) |

- With libyear-only of the same algorithm as comparator (the thesis's "9/9"), all nine AP contrasts survive Holm.
- Against the single libyear-only LR baseline, RF and XGB in 2021 do not differ clearly on AP.
- The "no added value from libyear" contrasts show no difference after adjustment.
- With 1,000 draws the smallest attainable p is 0.002, so the Holm values are coarse.

## F-11 Lockfile subset: recorded − inferred (paired package-cluster bootstrap, 1,000 draws, seed 42)

Both arms use the same rows; labels may differ between them. The point values match Table 5.20.

| Origin (pos inf/rec) | Model | ΔAUC [95% CI] | ΔAP [95% CI] |
|---|---|---|---|
| 2021 (120/135) | LR | −.003 [−.022, .021] | −.005 [−.029, .017] |
| | RF | +.031 [−.011, .067] | +.010 [−.012, .022] |
| | XGB | +.022 [−.022, .068] | +.008 [−.012, .018] |
| | libyear-only LR | +.046 [−.005, .105] | +.010 [.001, .021] |
| 2022 (65/65) | LR | −.027 [−.069, .006] | −.027 [−.062, .000] |
| | RF | +.008 [−.019, .033] | +.003 [−.013, .038] |
| | XGB | +.019 [−.012, .059] | +.005 [−.008, .021] |
| | libyear-only LR | +.031 [−.029, .081] | +.000 [−.001, .003] |
| 2023 (102/103) | LR | +.074 [−.011, .165] | +.029 [−.019, .083] |
| | RF | +.010 [−.009, .033] | +.015 [−.033, .066] |
| | XGB | −.007 [−.033, .022] | −.025 [−.073, .005] |
| | libyear-only LR | +.074 [.007, .159] | +.005 [−.002, .012] |

- All 18 full-model differences (3 origins × 3 models × 2 metrics) have CIs that include 0.
- For libyear-only LR, only AUC in 2023 and AP in 2021 exclude 0, both narrowly. The other four libyear-only CIs include 0.
- These CIs cover test-set uncertainty only; each arm's model was fitted separately. In 2021 the labels also differ (120 vs 135 positives).
- The existing within-arm intervals (full − without_libyear, full − libyear_only, for each arm) are copied to `round3_results.json` under `F11_lockfile.existing_within_arm_intervals`.
- The evidence supports "no clear change, with a possible small rise for libyear-only" better than "libyear is likely attenuated".

## F-14 Versions-behind under semver ordering

- **Not available.** `src/semver_variants.cjs` changes only the rule that picks the latest version (`latest_rule`). The counting loop is shared by every variant: it walks releases after `used_version_date` in date order and advances the reference only on a semver increase (2026-10-24 fix).
- The `semver_12_clamped`, `semver_12_signed` and `semver_6_clamped` datasets have major/minor/patch columns identical to `date_12_paired` (0 of 29,379 rows differ). Only latest_version (747 rows) and libyear differ.
- Instance-level d under the main definition reproduces Table 5.11:

  | | 2020 | 2021 | 2022 | 2023 |
  |---|---|---|---|---|
  | major | .011 | .133 | .308 | .013 |
  | minor | .034 | −.062 | .044 | .809 |
  | patch | .093 | .272 | .319 | 1.251 |
  | package_age | .877 | .797 | .877 | .550 |

- The review's example (node-fetch 2.6.7, 2023 snapshot, major = 3) is pre-fix. With current data it has major 1 / minor 2 / patch 12, latest 2.7.0, libyear 1.6.
- **Cost of a true semver-ordered count:**
  - What it would take: one new counting function, for example over the sorted versions in (used, highest-semver latest]. It can be computed in Python or Node from `cache/npm` for 29,379 rows with no new downloads. Compute time is under a minute; with code, tests and review it is about 1–2 hours.
  - What it would trigger: if it fed the models rather than only Table 5.11, it would also need a backtest refit (minutes) and new tables. That makes it a new feature definition and should be disclosed as one.

## F-23 Seeds (RF; seeds 0–9 plus seed 42; same data and parameters)

| Origin | RF AP mean ± SD [min, max] (seed 42, rank of 11) | RF AUC mean ± SD (seed 42) | RF recall@10% mean ± SD [min, max] (seed 42, rank) |
|---|---|---|---|
| 2021 | .0808 ± .0137 [.0613, .1009] (.0684, 9th) | .6690 ± .0082 (.6689) | .169 ± .014 [.146, .201] (.194, 2nd) |
| 2022 | .0491 ± .0022 [.0459, .0519] (.0488, 7th) | .7857 ± .0045 (.7873) | .227 ± .042 [.157, .329] (.150, 11th = lowest) |
| 2023 | .2938 ± .0080 [.2845, .3135] (.2835, 11th = lowest) | .8490 ± .0026 (.8498) | .518 ± .025 [.469, .555] (.536, 3rd) |

- SD is ddof = 0, as in `checks.py` and Table 5.25; ddof = 1 is in the JSON.
- XGBoost gives identical results for every seed (subsample = colsample = 1), so its SD is 0. Table 5.25 matches after rounding.
- Seed 42 sits low for RF:
  - AP in 2023 is below all ten other seeds.
  - recall@10% in 2022 (15.0% in Table 5.15) is below all ten; the seed mean is 22.7%.
- The main-table RF values are single draws and slightly pessimistic. They do not change the algorithm ranking against LR.

## F-20 Point-in-time training labels (PIT − main; from `pit_results.json`, 4-dp source)

| Origin | Model | AP main → PIT (Δ) | AUC main → PIT (Δ) |
|---|---|---|---|
| 2022 | LR | .0879 → .1148 (+.0269) | .8034 → .8210 (+.0176) |
| 2022 | RF | .0488 → .0561 (+.0073) | .7873 → .8085 (+.0212) |
| 2022 | XGB | .0503 → .0412 (−.0091) | .7782 → .7662 (−.0120) |
| 2023 | LR | .1148 → .1154 (+.0006) | .7410 → .7561 (+.0151) |
| 2023 | RF | .2835 → .3149 (+.0314) | .8498 → .8517 (+.0019) |
| 2023 | XGB | .1133 → .1065 (−.0068) | .7869 → .7762 (−.0107) |

- Max |ΔAP| = 0.031 (RF 2023) and max |ΔAUC| = 0.021 (RF 2022). The text of 5.8.6 mentions only AUC; AP moves by up to about 0.03 in both directions.
- The 2021 origin cannot be checked, because the advisory database history starts in February 2022.

## F-24 No-history subset (test rows whose package had no positive in training)

| Origin | Rows (share of test) | Positives | Packages | Packages seen in training (as negatives only) | Rows seen | Positives in seen packages |
|---|---|---|---|---|---|---|
| 2021 | 7,178 (97.4%) | 199 | 2,868 | 2,632 (91.8%) | 96.6% | 195 |
| 2022 | 6,912 (94.3%) | 86 | 2,761 | 2,613 (94.6%) | 97.7% | 85 |
| 2023 | 6,768 (92.7%) | 147 | 2,763 | 2,577 (93.3%) | 97.1% | 145 |

- The unseen remainder (236/148/186 packages, 4/1/2 positives) matches `four_step/seen_unseen_coverage.json`.
- The 97–98% figure in 5.6.1 is a **row** share (96.6–97.7%). At the **package** level it is 92–95%.
- Either way, nearly all no-history positives (195/199, 85/86, 145/147) belong to packages the models saw in training as negatives.
