# Analytics methodology

Every metric is also served at `/api/metrics` and shown in the UI. Type: **measured** (read from data), **calculated** (arithmetic on measured data), **estimated** (depends on an assumption).

| Metric | Formula | Type |
|---|---|---|
| Defect rate | defective / units produced x 100 (volume weighted; none if units = 0) | calculated |
| Target attainment | units / target x 100 | calculated |
| Output efficiency | units / (ideal rate x period hours) x 100 | calculated |
| Unplanned downtime % | unplanned minutes / period minutes x 100 | measured |
| MTBF / MTTR | run hours / unplanned events; mean unplanned event minutes (needs >= 3 events) | calculated |
| Energy cost | kWh x tariff | calculated |
| kWh per good unit | sum kWh / sum good units | calculated |

## Profit-leakage model (no double counting)
The four production categories are **disjoint by construction**: each unit of cost is counted once.

| Category | Observed cost | Why it does not overlap |
|---|---|---|
| Downtime impact | (unplanned min/60 x ideal units/h) x contribution margin/unit x 70% unrecoverable | uses **margin**, never revenue; output lost to stops |
| Quality cost | defective x (std material + std conversion) x (1 - 10% salvage) | **input cost** of scrap, not a lost sale |
| Excess energy | max(0, kWh - baseline kWh/unit x units x 1.05) x tariff | only energy above a per-machine+product median |
| Material waste | max(0, material cost - units x std material x 1.01) | only consumption beyond standard; defect material is in Quality |
| Inventory carrying | qty x unit cost x 18% / 365 per snapshot day | line level only |

Three tiers are always shown separately: **observed cost**, **estimated avoidable cost** (portion above explicit benchmarks: downtime 5% of time, defects 2%, 60% of excess energy, 50% of excess material, stock above 45 days of cover) and **potential future savings** (avoidable x 50% realization). The whole estimated loss is never presented as recoverable profit. All assumptions are `FPI_*` settings; benchmarks are illustrative and should be replaced with company targets.

Arithmetic: record-level figures are computed vectorised in float64 for speed; every published aggregate is rounded half-up with `Decimal` (`finance.money`). `finance.record_losses` is a Decimal reference implementation and a test asserts both agree to 0.01.

## Root cause
Correlations (Pearson across machine-days, also within-machine, n >= 30, flagged against a 2/sqrt(n) noise level), group indices, first-half vs second-half trend comparison, downtime reason matrix, and outliers (modified z-score using median/MAD, |z| > 3.5, per machine). Everything is labelled as association, not causation, and insufficient data returns a stated limitation.

## Recommendations
Deterministic rules on the latest 30 days: unusually high unplanned downtime per machine (>= max(6%, 1.5 x fleet median)), elevated defect rate per line and shift (>= 3% and >= 1.4 x factory), energy per unit >= 10% above baseline (last 14 days), inventory below reorder point and slow-moving stock, shift output-efficiency gap >= 5 points. Each stores evidence, triggering metric, threshold, severity, confidence, calculation method and timestamps. Upserted by (rule, entity) so user status/notes persist.

## Savings verification
Cost-rate difference between a baseline and a post-intervention period times post volume. **Verified** requires all of: baseline >= 28 days and >= 80% coverage; post >= 14 days and coverage; periods ordered with no overlap; daily volume within +/-30%; Welch |t| >= 2 on daily cost rates; >= 5% improvement; documented assumptions; values computed from loaded data. Manual values can never exceed *estimated*. Even *verified* is labelled "against baseline", not proof of causation.
