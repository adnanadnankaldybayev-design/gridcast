# GridCast Benchmark Card

Generated from `gridcast analyze` on a live run: anchors stride=6, GBM refit every 2 anchors, min history 30d, common anchor set per unit.
Git SHA and timestamps live in the sibling JSON (`latest_benchmark.json`).

## Models

### Seasonal-naive (168h week-ago)
- purpose: zero-parameter baseline and regularizer; publication-aware via fallback ladder
- strong: robust, no fitting, unbeatable on very short stable series
- weak: no weather/calendar awareness; needs lag >> publication lag (GB: 4 weeks back)
- cadence limits: any

### Ridge (linear, weather+calendar+lags)
- purpose: honest linear floor between naive and GBM
- strong: Australia's thermal-linear response; cheap, deterministic
- weak: misses nonlinear ramps/holidays; GB stale-lag structure fails it
- cadence limits: any

### LightGBM (trees, weather+calendar+publication-safe lags)
- purpose: production champion
- strong: best or near-best on every unit; handles NaN lag gaps natively
- weak: cold-snap overshoot via HDD; needs periodic refits
- cadence limits: any

### Chronos-Bolt-mini (zero-shot foundation)
- purpose: evidence for H2: pretrained series model as an out-of-box competitor
- strong: GB 30-min with 21d arrears; anomalous days (cold snaps, holidays)
- weak: fine cadences + long AR horizons: 192-576 step continuation degrades badly
- cadence limits: >=30 min; long horizons very cautiously

### Ensemble (inverse-MAE over last 14 anchors, past-only)
- purpose: variance reduction and graceful model compromise
- strong: never trains on the evaluation window; robust to one bad member
- weak: weights lag regime changes by ~2 weeks (rolling window)
- cadence limits: any (composed of its members)

## Accuracy by unit (primary metric on common anchors)

### GB/GB (champion: ensemble-inv-mae-14, n_anchors≈22)
                 model  mape_pct   mae_mw
   ensemble-inv-mae-14    7.3649 1563.405
      lightgbm-weather    8.2958 1757.272
chronos-bolt-zero-shot    8.9825 1910.146
   seasonal-naive-168h    9.4883 1977.788
         ridge-weather   11.5394 2569.172

### IE/ALL (champion: lightgbm-weather, n_anchors≈30)
                 model  mape_pct  mae_mw
      lightgbm-weather    3.4561 160.781
   seasonal-naive-168h    3.7574 175.319
   ensemble-inv-mae-14    3.7646 174.091
         ridge-weather    3.8716 180.262
chronos-bolt-zero-shot   14.2621 640.404

### AU/NSW1 (champion: ensemble-inv-mae-14, n_anchors≈30)
                 model  smape_pct   mae_mw
   ensemble-inv-mae-14     6.7734  496.872
      lightgbm-weather     6.8468  498.765
         ridge-weather     6.8741  509.106
   seasonal-naive-168h     7.1630  526.208
chronos-bolt-zero-shot    20.6278 1573.607

### AU/QLD1 (champion: lightgbm-weather, n_anchors≈30)
                 model  smape_pct   mae_mw
      lightgbm-weather     3.9134  214.199
   ensemble-inv-mae-14     4.8345  269.608
         ridge-weather     5.0158  280.400
   seasonal-naive-168h     5.6224  300.703
chronos-bolt-zero-shot    22.8662 1339.662

### AU/SA1 (champion: lightgbm-weather, n_anchors≈30)
                 model  smape_pct  mae_mw
      lightgbm-weather    13.9701 147.064
   ensemble-inv-mae-14    15.1953 164.505
         ridge-weather    16.8629 176.665
   seasonal-naive-168h    17.1778 185.641
chronos-bolt-zero-shot    34.1018 408.119

### AU/TAS1 (champion: ensemble-inv-mae-14, n_anchors≈30)
                 model  smape_pct  mae_mw
   ensemble-inv-mae-14     6.2028  68.055
         ridge-weather     6.2689  69.030
      lightgbm-weather     6.3875  69.537
   seasonal-naive-168h     7.8144  85.902
chronos-bolt-zero-shot    14.6319 159.992

### AU/VIC1 (champion: ridge-weather, n_anchors≈30)
                 model  smape_pct   mae_mw
         ridge-weather     7.4355  399.894
   ensemble-inv-mae-14     8.0670  428.133
      lightgbm-weather     8.3437  432.584
   seasonal-naive-168h    10.0933  545.424
chronos-bolt-zero-shot    21.8652 1203.934

### AU/NEM_TOTAL (champion: ridge-weather, n_anchors≈30)
                 model  smape_pct   mae_mw
         ridge-weather     4.6347  971.617
   ensemble-inv-mae-14     4.9141 1024.009
   seasonal-naive-168h     4.9486 1045.110
      lightgbm-weather     4.9835 1028.755
chronos-bolt-zero-shot    20.9186 4533.125

## Ensemble vs best single (delta primary metric, negative = ensemble better)

- GB/GB: ensemble 7.365 vs lightgbm-weather 8.296 (delta -0.931)
- IE/ALL: ensemble 3.765 vs lightgbm-weather 3.456 (delta 0.308)
- AU/NSW1: ensemble 6.773 vs lightgbm-weather 6.847 (delta -0.073)
- AU/QLD1: ensemble 4.835 vs lightgbm-weather 3.913 (delta 0.921)
- AU/SA1: ensemble 15.195 vs lightgbm-weather 13.97 (delta 1.225)
- AU/TAS1: ensemble 6.203 vs ridge-weather 6.269 (delta -0.066)
- AU/VIC1: ensemble 8.067 vs ridge-weather 7.436 (delta 0.631)
- AU/NEM_TOTAL: ensemble 4.914 vs ridge-weather 4.635 (delta 0.279)

## Diebold-Mariano (two-sided, HAC Newey-West)

| pair | mean loss diff | DM | p | verdict |
|---|---|---|---|---|
| GB/GB: lightgbm-weather__vs__seasonal-naive-168h | -220.51588 | -1.9988 | 0.045634 | significant |
| GB/GB: lightgbm-weather__vs__ridge-weather | -811.899988 | -5.4022 | 0.0 | significant |
| GB/GB: lightgbm-weather__vs__chronos-bolt-zero-shot | -152.873138 | -1.2868 | 0.198168 | NOT significant |
| GB/GB: ensemble-inv-mae-14__vs__lightgbm-weather | -193.86782 | -2.8768 | 0.004017 | significant |
| IE/ALL: lightgbm-weather__vs__seasonal-naive-168h | -14.537991 | -2.1632 | 0.030529 | significant |
| IE/ALL: lightgbm-weather__vs__ridge-weather | -19.480597 | -2.8255 | 0.004721 | significant |
| IE/ALL: lightgbm-weather__vs__chronos-bolt-zero-shot | -479.622545 | -25.2172 | 0.0 | significant |
| IE/ALL: ensemble-inv-mae-14__vs__lightgbm-weather | 13.309936 | 2.4208 | 0.015485 | significant |
| AU/NSW1: lightgbm-weather__vs__seasonal-naive-168h | -27.443424 | -1.5837 | 0.113265 | NOT significant |
| AU/NSW1: lightgbm-weather__vs__ridge-weather | -10.341414 | -0.7079 | 0.479017 | NOT significant |
| AU/NSW1: lightgbm-weather__vs__chronos-bolt-zero-shot | -1074.842184 | -27.0119 | 0.0 | significant |
| AU/NSW1: ensemble-inv-mae-14__vs__lightgbm-weather | -1.893184 | -0.1744 | 0.861589 | NOT significant |
| AU/QLD1: lightgbm-weather__vs__seasonal-naive-168h | -86.504745 | -8.3883 | 0.0 | significant |
| AU/QLD1: lightgbm-weather__vs__ridge-weather | -66.201277 | -9.0752 | 0.0 | significant |
| AU/QLD1: lightgbm-weather__vs__chronos-bolt-zero-shot | -1125.463146 | -33.7048 | 0.0 | significant |
| AU/QLD1: ensemble-inv-mae-14__vs__lightgbm-weather | 55.409623 | 7.978 | 0.0 | significant |
| AU/SA1: lightgbm-weather__vs__seasonal-naive-168h | -38.577198 | -6.1365 | 0.0 | significant |
| AU/SA1: lightgbm-weather__vs__ridge-weather | -29.600893 | -6.3428 | 0.0 | significant |
| AU/SA1: lightgbm-weather__vs__chronos-bolt-zero-shot | -261.054726 | -21.2435 | 0.0 | significant |
| AU/SA1: ensemble-inv-mae-14__vs__lightgbm-weather | 17.441106 | 5.3501 | 0.0 | significant |
| AU/TAS1: lightgbm-weather__vs__seasonal-naive-168h | -16.364747 | -7.3303 | 0.0 | significant |
| AU/TAS1: lightgbm-weather__vs__ridge-weather | 0.506862 | 0.263 | 0.792523 | NOT significant |
| AU/TAS1: lightgbm-weather__vs__chronos-bolt-zero-shot | -90.455348 | -24.8726 | 0.0 | significant |
| AU/TAS1: ensemble-inv-mae-14__vs__ridge-weather | -0.974867 | -0.7314 | 0.46454 | NOT significant |
| AU/VIC1: lightgbm-weather__vs__seasonal-naive-168h | -112.839433 | -7.1895 | 0.0 | significant |
| AU/VIC1: lightgbm-weather__vs__ridge-weather | 32.690612 | 2.6631 | 0.007742 | significant |
| AU/VIC1: lightgbm-weather__vs__chronos-bolt-zero-shot | -771.349918 | -26.6763 | 0.0 | significant |
| AU/VIC1: ensemble-inv-mae-14__vs__ridge-weather | 28.238873 | 3.2317 | 0.00123 | significant |
| AU/NEM_TOTAL: lightgbm-weather__vs__seasonal-naive-168h | -16.355055 | -0.5292 | 0.596674 | NOT significant |
| AU/NEM_TOTAL: lightgbm-weather__vs__ridge-weather | 57.137716 | 2.1015 | 0.035597 | significant |
| AU/NEM_TOTAL: lightgbm-weather__vs__chronos-bolt-zero-shot | -3504.370074 | -32.7298 | 0.0 | significant |
| AU/NEM_TOTAL: ensemble-inv-mae-14__vs__ridge-weather | 52.392274 | 2.1998 | 0.027819 | significant |

Reading: mean_loss_diff > 0 => the first model named has HIGHER loss (worse). Pairs with NOT significant differences are honest non-conclusions, not ties to hide.

## Conformal intervals (rolling split-conformal, calib 14 anchors)

- GB/GB/ensemble-inv-mae-14 nominal 80%: PICP 0.844, mean width 5728.8 MW, gap 0.0437
- GB/GB/ensemble-inv-mae-14 nominal 90%: PICP 0.935, mean width 7888.5 MW, gap 0.0345
- GB/GB/ensemble-inv-mae-14 nominal 95%: PICP 0.982, mean width 9837.8 MW, gap 0.0316
- GB/GB/lightgbm-weather nominal 80%: PICP 0.908, mean width 6910.1 MW, gap 0.1077
- GB/GB/lightgbm-weather nominal 90%: PICP 0.966, mean width 8836.3 MW, gap 0.0663
- GB/GB/lightgbm-weather nominal 95%: PICP 0.99, mean width 10581.4 MW, gap 0.0396
- IE/ALL/ensemble-inv-mae-14 nominal 80%: PICP 0.854, mean width 623.8 MW, gap 0.0538
- IE/ALL/ensemble-inv-mae-14 nominal 90%: PICP 0.918, mean width 795.3 MW, gap 0.0183
- IE/ALL/ensemble-inv-mae-14 nominal 95%: PICP 0.954, mean width 921.5 MW, gap 0.0037
- IE/ALL/lightgbm-weather nominal 80%: PICP 0.848, mean width 601.7 MW, gap 0.0482
- IE/ALL/lightgbm-weather nominal 90%: PICP 0.93, mean width 811.1 MW, gap 0.03
- IE/ALL/lightgbm-weather nominal 95%: PICP 0.969, mean width 971.3 MW, gap 0.0186
- AU/NSW1/ensemble-inv-mae-14 nominal 80%: PICP 0.817, mean width 1616.2 MW, gap 0.0168
- AU/NSW1/ensemble-inv-mae-14 nominal 90%: PICP 0.905, mean width 2184.3 MW, gap 0.0051
- AU/NSW1/ensemble-inv-mae-14 nominal 95%: PICP 0.946, mean width 2684.9 MW, gap -0.0041
- AU/NSW1/lightgbm-weather nominal 80%: PICP 0.802, mean width 1588.9 MW, gap 0.0023
- AU/NSW1/lightgbm-weather nominal 90%: PICP 0.901, mean width 2184.0 MW, gap 0.0006
- AU/NSW1/lightgbm-weather nominal 95%: PICP 0.944, mean width 2820.3 MW, gap -0.0057
- AU/QLD1/ensemble-inv-mae-14 nominal 80%: PICP 0.852, mean width 980.3 MW, gap 0.052
- AU/QLD1/ensemble-inv-mae-14 nominal 90%: PICP 0.921, mean width 1346.6 MW, gap 0.0206
- AU/QLD1/ensemble-inv-mae-14 nominal 95%: PICP 0.955, mean width 1794.8 MW, gap 0.0047
- AU/QLD1/lightgbm-weather nominal 80%: PICP 0.839, mean width 747.9 MW, gap 0.0395
- AU/QLD1/lightgbm-weather nominal 90%: PICP 0.921, mean width 1136.9 MW, gap 0.0211
- AU/QLD1/lightgbm-weather nominal 95%: PICP 0.959, mean width 1540.2 MW, gap 0.0088
- AU/SA1/ensemble-inv-mae-14 nominal 80%: PICP 0.812, mean width 548.4 MW, gap 0.0118
- AU/SA1/ensemble-inv-mae-14 nominal 90%: PICP 0.894, mean width 749.2 MW, gap -0.0064
- AU/SA1/ensemble-inv-mae-14 nominal 95%: PICP 0.938, mean width 1002.0 MW, gap -0.0117
- AU/SA1/lightgbm-weather nominal 80%: PICP 0.798, mean width 453.0 MW, gap -0.0019
- AU/SA1/lightgbm-weather nominal 90%: PICP 0.89, mean width 669.9 MW, gap -0.01
- AU/SA1/lightgbm-weather nominal 95%: PICP 0.939, mean width 901.7 MW, gap -0.0109
- AU/TAS1/ensemble-inv-mae-14 nominal 80%: PICP 0.797, mean width 218.2 MW, gap -0.0032
- AU/TAS1/ensemble-inv-mae-14 nominal 90%: PICP 0.892, mean width 287.2 MW, gap -0.0084
- AU/TAS1/ensemble-inv-mae-14 nominal 95%: PICP 0.946, mean width 349.1 MW, gap -0.0039
- AU/TAS1/lightgbm-weather nominal 80%: PICP 0.815, mean width 231.3 MW, gap 0.015
- AU/TAS1/lightgbm-weather nominal 90%: PICP 0.904, mean width 296.7 MW, gap 0.0039
- AU/TAS1/lightgbm-weather nominal 95%: PICP 0.944, mean width 356.2 MW, gap -0.0057
- AU/VIC1/ensemble-inv-mae-14 nominal 80%: PICP 0.813, mean width 1406.3 MW, gap 0.0126
- AU/VIC1/ensemble-inv-mae-14 nominal 90%: PICP 0.901, mean width 1829.2 MW, gap 0.001
- AU/VIC1/ensemble-inv-mae-14 nominal 95%: PICP 0.946, mean width 2267.6 MW, gap -0.0044
- AU/VIC1/lightgbm-weather nominal 80%: PICP 0.784, mean width 1407.0 MW, gap -0.0163
- AU/VIC1/lightgbm-weather nominal 90%: PICP 0.888, mean width 1891.2 MW, gap -0.0116
- AU/VIC1/lightgbm-weather nominal 95%: PICP 0.936, mean width 2302.8 MW, gap -0.0141
- AU/NEM_TOTAL/ensemble-inv-mae-14 nominal 80%: PICP 0.831, mean width 3474.9 MW, gap 0.0311
- AU/NEM_TOTAL/ensemble-inv-mae-14 nominal 90%: PICP 0.918, mean width 4740.3 MW, gap 0.0185
- AU/NEM_TOTAL/ensemble-inv-mae-14 nominal 95%: PICP 0.966, mean width 5980.9 MW, gap 0.0156
- AU/NEM_TOTAL/lightgbm-weather nominal 80%: PICP 0.803, mean width 3239.4 MW, gap 0.0026
- AU/NEM_TOTAL/lightgbm-weather nominal 90%: PICP 0.898, mean width 4422.5 MW, gap -0.0017
- AU/NEM_TOTAL/lightgbm-weather nominal 95%: PICP 0.945, mean width 5481.9 MW, gap -0.0049

### Undercovered slices (PICP below nominal minus 0.05)

- AU/QLD1/ensemble-inv-mae-14 bank_holiday/h0-24 @80%: PICP 0.666 (n=287)
- AU/QLD1/ensemble-inv-mae-14 bank_holiday/h0-24 @90%: PICP 0.801 (n=287)
- AU/QLD1/ensemble-inv-mae-14 bank_holiday/h0-24 @95%: PICP 0.878 (n=287)
- AU/QLD1/lightgbm-weather bank_holiday/h0-24 @80%: PICP 0.746 (n=287)
- AU/SA1/ensemble-inv-mae-14 bank_holiday/h24-48 @80%: PICP 0.636 (n=258)
- AU/SA1/ensemble-inv-mae-14 bank_holiday/h24-48 @90%: PICP 0.698 (n=258)
- AU/SA1/ensemble-inv-mae-14 bank_holiday/h24-48 @95%: PICP 0.775 (n=258)
- AU/SA1/ensemble-inv-mae-14 cold_10pct/h24-48 @80%: PICP 0.691 (n=576)
- AU/SA1/ensemble-inv-mae-14 cold_10pct/h24-48 @90%: PICP 0.807 (n=576)
- AU/SA1/ensemble-inv-mae-14 cold_10pct/h24-48 @95%: PICP 0.866 (n=576)
- AU/SA1/lightgbm-weather bank_holiday/h24-48 @80%: PICP 0.671 (n=258)
- AU/SA1/lightgbm-weather bank_holiday/h24-48 @90%: PICP 0.806 (n=258)
- AU/SA1/lightgbm-weather bank_holiday/h24-48 @95%: PICP 0.891 (n=258)
- AU/SA1/lightgbm-weather cold_10pct/h24-48 @80%: PICP 0.705 (n=576)
- AU/SA1/lightgbm-weather cold_10pct/h24-48 @90%: PICP 0.795 (n=576)
- AU/SA1/lightgbm-weather cold_10pct/h24-48 @95%: PICP 0.885 (n=576)
- AU/TAS1/ensemble-inv-mae-14 weekday/h24-48 @80%: PICP 0.747 (n=5784)
- AU/TAS1/ensemble-inv-mae-14 cold_10pct/h0-24 @80%: PICP 0.463 (n=574)
- AU/TAS1/ensemble-inv-mae-14 cold_10pct/h0-24 @90%: PICP 0.646 (n=574)
- AU/TAS1/ensemble-inv-mae-14 cold_10pct/h0-24 @95%: PICP 0.794 (n=574)
- AU/TAS1/ensemble-inv-mae-14 cold_10pct/h24-48 @80%: PICP 0.448 (n=840)
- AU/TAS1/ensemble-inv-mae-14 cold_10pct/h24-48 @90%: PICP 0.657 (n=840)
- AU/TAS1/ensemble-inv-mae-14 cold_10pct/h24-48 @95%: PICP 0.787 (n=840)
- AU/TAS1/lightgbm-weather weekday/h24-48 @90%: PICP 0.843 (n=5784)
- AU/TAS1/lightgbm-weather weekday/h24-48 @95%: PICP 0.883 (n=5784)
- AU/TAS1/lightgbm-weather cold_10pct/h0-24 @80%: PICP 0.587 (n=574)
- AU/TAS1/lightgbm-weather cold_10pct/h0-24 @90%: PICP 0.779 (n=574)
- AU/TAS1/lightgbm-weather cold_10pct/h24-48 @80%: PICP 0.413 (n=840)
- AU/TAS1/lightgbm-weather cold_10pct/h24-48 @90%: PICP 0.577 (n=840)
- AU/TAS1/lightgbm-weather cold_10pct/h24-48 @95%: PICP 0.71 (n=840)
- AU/VIC1/ensemble-inv-mae-14 bank_holiday/h24-48 @80%: PICP 0.629 (n=264)
- AU/VIC1/ensemble-inv-mae-14 bank_holiday/h24-48 @90%: PICP 0.689 (n=264)
- AU/VIC1/ensemble-inv-mae-14 bank_holiday/h24-48 @95%: PICP 0.765 (n=264)
- AU/VIC1/ensemble-inv-mae-14 cold_10pct/h0-24 @80%: PICP 0.713 (n=551)
- AU/VIC1/ensemble-inv-mae-14 cold_10pct/h0-24 @90%: PICP 0.813 (n=551)
- AU/VIC1/ensemble-inv-mae-14 cold_10pct/h0-24 @95%: PICP 0.869 (n=551)
- AU/VIC1/ensemble-inv-mae-14 cold_10pct/h24-48 @80%: PICP 0.668 (n=576)
- AU/VIC1/ensemble-inv-mae-14 cold_10pct/h24-48 @90%: PICP 0.767 (n=576)
- AU/VIC1/ensemble-inv-mae-14 cold_10pct/h24-48 @95%: PICP 0.859 (n=576)
- AU/VIC1/lightgbm-weather weekend/h0-24 @80%: PICP 0.733 (n=2273)
- AU/VIC1/lightgbm-weather weekend/h0-24 @90%: PICP 0.834 (n=2273)
- AU/VIC1/lightgbm-weather weekend/h0-24 @95%: PICP 0.862 (n=2273)
- AU/VIC1/lightgbm-weather bank_holiday/h24-48 @80%: PICP 0.67 (n=264)
- AU/VIC1/lightgbm-weather bank_holiday/h24-48 @90%: PICP 0.795 (n=264)

## Hypothesis status

- **H1** (GBM > naive): CONFIRMED on 3/8 units as champion; see tables.
- **H2** (zero-shot foundation competitive on rare/anomalous days): PARTIALLY SUPPORTED — chronos beats naive only on the GB 30-min chain with long publication lag and on its anomalous day slices (cold-decile, bank holidays); it fails at fine cadence/long horizon broadly. Overall chronos vs naive: GB/GB 8.9825 vs 9.4883; IE/ALL 14.2621 vs 3.7574; AU/NSW1 20.6278 vs 7.163; AU/QLD1 22.8662 vs 5.6224; AU/SA1 34.1018 vs 17.1778; AU/TAS1 14.6319 vs 7.8144; AU/VIC1 21.8652 vs 10.0933; AU/NEM_TOTAL 20.9186 vs 4.9486

## Honest limitations

- 48h horizon coverage relies on a rolling 14-anchor split-conformal; regime shifts (heat waves, price events) temporarily decalibrate it.
- Chronos-Bolt-mini is evaluated natively at market cadence; its long-horizon weakness at 5/15 min is a known zero-shot limit, not a data bug.
- DM tests use Newey-West conservative variance; with overlapping 48h forecast errors, serial correlation beyond the lag may inflate significance.
- GB's 21-day publication arrears means GBM/foundation share a stale-information handicap; conclusions do not transfer to markets with real-time metering.
- Weather is archival reanalysis (perfect-forecast proxy); live NWP forecasts will add error the ablation bounds only partially.

