# Package-disjoint evaluation (ISWA plan, advisor item 5)

Status: **exploratory, post hoc**, run 2026-11-10. Design fixed in the script docstring before the run. Nothing in `thesis.md` or the main results changed.

## Files

| File | Content |
|---|---|
| `package_disjoint.py` | Design, fits, metrics, package-cluster bootstrap |
| `package_disjoint_results.json` | `folds` (rows/positives per group), `points` (AP, ROC-AUC, P/R@K per scorer), `intervals` (paired differences) |

Rerun (bundled Python 3.12, offline, ~10 min): `& $py verification\package_disjoint\package_disjoint.py`

## Design

- Same rows, labels, features, fixed parameters and training eligibility as `rq_completion` (library versions asserted equal to its frozen manifest).
- Per test origin, the test snapshot's packages are split into 5 groups by `sha256(package) % 5`. For each group all training rows of those packages are removed, models are refit, and only that group's test rows are scored. The five groups' scores are pooled into one ranking, so **no test row is scored by a model that saw its package**.
- Scorers: disjoint-trained full LR/RF/XGB, the same without libyear, libyear-only LR; libyear score and the prior-advisory rule (no training data, unchanged); main (seen-package) full models on the same rows.
- Metrics and intervals: AP, ROC-AUC, Precision/Recall@K (K = 1/5/10/20 %, four_step tie policy); package-cluster paired bootstrap, 1,000 resamples, seed 42; no multiplicity correction.
- Groups hold 9–106 positives; every training set keeps both classes (94–518 positives).

## Results (instance view)

ROC-AUC, seen → package-disjoint:

| Origin | LR | RF | XGB | Libyear score | Prior-advisory rule |
|---|---|---|---|---|---|
| 2021 | 0.758 → 0.747 | 0.669 → 0.650 | 0.652 → 0.638 | 0.579 | 0.765 |
| 2022 | 0.803 → 0.788 | 0.787 → 0.780 | 0.778 → 0.745 | 0.503 | 0.818 |
| 2023 | 0.741 → 0.733 | 0.850 → 0.834 | 0.787 → 0.717 | 0.528 | 0.682 |

AP, seen → disjoint: LR 0.116 → 0.100, 0.088 → 0.098, 0.115 → 0.108 · RF 0.068 → 0.053, 0.049 → 0.049, 0.284 → 0.268 · XGB 0.064 → 0.054, 0.050 → 0.044, 0.113 → 0.053.

Recall@10 %, disjoint: LR 0.280 / 0.407 / 0.355 · RF 0.142 / 0.300 / 0.521 · XGB 0.104 / 0.286 / 0.156 (rule 0.605 / 0.627 / 0.353).

## Interpretation

- **Little loss from never seeing the package.** All nine disjoint − seen AP intervals include zero (XGB 2023 −0.061 [−0.183, 0.000] is the largest drop). ROC-AUC falls by 0.007–0.019 for LR and RF and by 0.014–0.069 for XGB (largest at 2023; XGB AP 0.113 → 0.053, so the 'little loss' statement holds for LR and RF, not for XGB 2023). The ranking signal is therefore not mainly memorisation of package identity; it transfers to packages absent from training. Even RF's high 2023 AP (0.268) survives, so it is not explained by having seen rollup/express/webpack in training (it still depends on those packages being in the test set, thesis 5.8.5).
- **Models vs libyear, package-disjoint.** 2022 and 2023: disjoint models beat the libyear score on AP for all three algorithms (intervals exclude zero). 2021: no interval excludes zero (LR +0.044 [−0.008, 0.107]; RF and XGB ≈ 0). Against disjoint libyear-only LR, LR 2021 still excludes zero (+0.047 [0.017, 0.103]). So under this stricter test the "models > libyear" result holds in 2022–2023 and for LR in 2021, but is not detectable for RF/XGB in 2021.
- **Prior-advisory rule still higher in 2021–2022** (AP intervals exclude zero for RF/XGB 2021 and XGB 2022; Recall@10 % for all three in 2021). The rule uses public advisory history, not training data, so it is unaffected by the disjoint split.
- **Libyear incremental value unchanged:** 8 of 9 ΔAP intervals include zero; XGB 2023 +0.007 [0.0003, 0.020] narrowly excludes zero (negligible gain).
- Limits: the hash split does not keep related packages (e.g. named in the same advisory) together; pooled ranking across five group models (scores on a common probability scale but from different fits); training sets lose 17–23 % of rows per fold; few positives per group (9–106); test origins reused; no multiplicity correction.
