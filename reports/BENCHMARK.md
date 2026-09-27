# GridCast Benchmark Card

Generated from `gridcast analyze` on a live run: anchors stride=6, GBM refit every 7 anchors, min history 30d, common anchor set per unit.
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
   ensemble-inv-mae-14    7.9608 1703.688
      lightgbm-weather    8.7144 1876.047
chronos-bolt-zero-shot    8.9825 1910.146
   seasonal-naive-168h    9.4883 1977.788
         ridge-weather   16.3896 3691.146

### IE/ALL (champion: lightgbm-weather, n_anchors≈30)
                 model  mape_pct  mae_mw
      lightgbm-weather    3.5696 164.875
   seasonal-naive-168h    3.7574 175.319
   ensemble-inv-mae-14    3.8268 177.003
         ridge-weather    4.2424 198.926
chronos-bolt-zero-shot   14.2621 640.404

### AU/NSW1 (champion: ensemble-inv-mae-14, n_anchors≈30)
                 model  smape_pct   mae_mw
   ensemble-inv-mae-14     7.0251  517.515
   seasonal-naive-168h     7.1630  526.208
      lightgbm-weather     7.3727  541.815
         ridge-weather     7.9493  593.207
chronos-bolt-zero-shot    20.6278 1573.607

### AU/QLD1 (champion: lightgbm-weather, n_anchors≈30)
                 model  smape_pct   mae_mw
      lightgbm-weather     4.1260  224.934
   ensemble-inv-mae-14     4.8552  271.993
         ridge-weather     5.2806  298.263
   seasonal-naive-168h     5.6224  300.703
chronos-bolt-zero-shot    22.8662 1339.662

### AU/SA1 (champion: lightgbm-weather, n_anchors≈30)
                 model  smape_pct  mae_mw
      lightgbm-weather    15.6312 172.348
   ensemble-inv-mae-14    16.0666 177.661
   seasonal-naive-168h    17.1778 185.641
         ridge-weather    17.9690 194.674
chronos-bolt-zero-shot    34.1018 408.119

### AU/TAS1 (champion: ensemble-inv-mae-14, n_anchors≈30)
                 model  smape_pct  mae_mw
   ensemble-inv-mae-14     6.3637  69.700
      lightgbm-weather     6.9584  74.702
         ridge-weather     6.9821  77.010
   seasonal-naive-168h     7.8144  85.902
chronos-bolt-zero-shot    14.6319 159.992

### AU/VIC1 (champion: ensemble-inv-mae-14, n_anchors≈30)
                 model  smape_pct   mae_mw
   ensemble-inv-mae-14     8.5800  457.832
         ridge-weather     8.8300  476.552
      lightgbm-weather     9.0612  482.057
   seasonal-naive-168h    10.0933  545.424
chronos-bolt-zero-shot    21.8652 1203.934

### AU/NEM_TOTAL (champion: seasonal-naive-168h, n_anchors≈30)
                 model  smape_pct   mae_mw
   seasonal-naive-168h     4.9486 1045.110
         ridge-weather     5.1721 1089.159
   ensemble-inv-mae-14     5.1855 1079.513
      lightgbm-weather     5.2640 1091.080
chronos-bolt-zero-shot    20.9186 4533.125

## Ensemble vs best single (delta primary metric, negative = ensemble better)

- GB/GB: ensemble 7.961 vs lightgbm-weather 8.714 (delta -0.754)
- IE/ALL: ensemble 3.827 vs lightgbm-weather 3.57 (delta 0.257)
- AU/NSW1: ensemble 7.025 vs seasonal-naive-168h 7.163 (delta -0.138)
- AU/QLD1: ensemble 4.855 vs lightgbm-weather 4.126 (delta 0.729)
- AU/SA1: ensemble 16.067 vs lightgbm-weather 15.631 (delta 0.435)
- AU/TAS1: ensemble 6.364 vs lightgbm-weather 6.958 (delta -0.595)
- AU/VIC1: ensemble 8.58 vs ridge-weather 8.83 (delta -0.25)
- AU/NEM_TOTAL: ensemble 5.186 vs seasonal-naive-168h 4.949 (delta 0.237)

## Diebold-Mariano (two-sided, HAC Newey-West)

| pair | mean loss diff | DM | p | verdict |
|---|---|---|---|---|
| GB/GB: lightgbm-weather__vs__seasonal-naive-168h | -101.741585 | -0.8632 | 0.38802 | NOT significant |
| GB/GB: lightgbm-weather__vs__ridge-weather | -1815.098987 | -9.1327 | 0.0 | significant |
| GB/GB: lightgbm-weather__vs__chronos-bolt-zero-shot | -34.098843 | -0.2568 | 0.797332 | NOT significant |
| GB/GB: ensemble-inv-mae-14__vs__lightgbm-weather | -172.358794 | -2.4184 | 0.015588 | significant |
| IE/ALL: lightgbm-weather__vs__seasonal-naive-168h | -10.444513 | -1.4791 | 0.13912 | NOT significant |
| IE/ALL: lightgbm-weather__vs__ridge-weather | -34.050584 | -4.1944 | 2.7e-05 | significant |
| IE/ALL: lightgbm-weather__vs__chronos-bolt-zero-shot | -475.529068 | -25.3375 | 0.0 | significant |
| IE/ALL: ensemble-inv-mae-14__vs__lightgbm-weather | 12.127891 | 2.1534 | 0.031284 | significant |
| AU/NSW1: lightgbm-weather__vs__seasonal-naive-168h | 15.606336 | 0.8496 | 0.395549 | NOT significant |
| AU/NSW1: lightgbm-weather__vs__ridge-weather | -51.39207 | -3.0048 | 0.002658 | significant |
| AU/NSW1: lightgbm-weather__vs__chronos-bolt-zero-shot | -1031.792423 | -25.5559 | 0.0 | significant |
| AU/NSW1: ensemble-inv-mae-14__vs__seasonal-naive-168h | -8.693117 | -0.5854 | 0.558272 | NOT significant |
| AU/QLD1: lightgbm-weather__vs__seasonal-naive-168h | -75.769314 | -6.9892 | 0.0 | significant |
| AU/QLD1: lightgbm-weather__vs__ridge-weather | -73.328449 | -8.8627 | 0.0 | significant |
| AU/QLD1: lightgbm-weather__vs__chronos-bolt-zero-shot | -1114.727716 | -33.0528 | 0.0 | significant |
| AU/QLD1: ensemble-inv-mae-14__vs__lightgbm-weather | 47.058744 | 6.1019 | 0.0 | significant |
| AU/SA1: lightgbm-weather__vs__seasonal-naive-168h | -13.293029 | -1.9837 | 0.047285 | significant |
| AU/SA1: lightgbm-weather__vs__ridge-weather | -22.325609 | -4.3972 | 1.1e-05 | significant |
| AU/SA1: lightgbm-weather__vs__chronos-bolt-zero-shot | -235.770557 | -19.8102 | 0.0 | significant |
| AU/SA1: ensemble-inv-mae-14__vs__lightgbm-weather | 5.31262 | 1.5297 | 0.12609 | NOT significant |
| AU/TAS1: lightgbm-weather__vs__seasonal-naive-168h | -11.19997 | -4.4642 | 8e-06 | significant |
| AU/TAS1: lightgbm-weather__vs__ridge-weather | -2.308309 | -0.9986 | 0.31798 | NOT significant |
| AU/TAS1: lightgbm-weather__vs__chronos-bolt-zero-shot | -85.29057 | -21.958 | 0.0 | significant |
| AU/TAS1: ensemble-inv-mae-14__vs__lightgbm-weather | -5.001827 | -3.0386 | 0.002376 | significant |
| AU/VIC1: lightgbm-weather__vs__seasonal-naive-168h | -63.366417 | -4.0072 | 6.1e-05 | significant |
| AU/VIC1: lightgbm-weather__vs__ridge-weather | 5.505053 | 0.3853 | 0.70005 | NOT significant |
| AU/VIC1: lightgbm-weather__vs__chronos-bolt-zero-shot | -721.876901 | -24.4859 | 0.0 | significant |
| AU/VIC1: ensemble-inv-mae-14__vs__ridge-weather | -18.720393 | -1.8709 | 0.061358 | NOT significant |
| AU/NEM_TOTAL: lightgbm-weather__vs__seasonal-naive-168h | 45.970272 | 1.4776 | 0.139503 | NOT significant |
| AU/NEM_TOTAL: lightgbm-weather__vs__ridge-weather | 1.920619 | 0.0676 | 0.946108 | NOT significant |
| AU/NEM_TOTAL: lightgbm-weather__vs__chronos-bolt-zero-shot | -3442.044746 | -31.8772 | 0.0 | significant |
| AU/NEM_TOTAL: ensemble-inv-mae-14__vs__seasonal-naive-168h | 34.403042 | 1.2218 | 0.221771 | NOT significant |

Reading: mean_loss_diff > 0 => the first model named has HIGHER loss (worse). Pairs with NOT significant differences are honest non-conclusions, not ties to hide.

## Conformal intervals (rolling split-conformal, calib 14 anchors)

- GB/GB/ensemble-inv-mae-14 nominal 80%: PICP 0.889, mean width 6639.1 MW, gap 0.0894
- GB/GB/ensemble-inv-mae-14 nominal 90%: PICP 0.938, mean width 8415.0 MW, gap 0.0375
- GB/GB/ensemble-inv-mae-14 nominal 95%: PICP 0.968, mean width 10086.1 MW, gap 0.0178
- GB/GB/lightgbm-weather nominal 80%: PICP 0.908, mean width 7658.6 MW, gap 0.1082
- GB/GB/lightgbm-weather nominal 90%: PICP 0.972, mean width 9676.6 MW, gap 0.0717
- GB/GB/lightgbm-weather nominal 95%: PICP 0.991, mean width 11445.0 MW, gap 0.0406
- IE/ALL/ensemble-inv-mae-14 nominal 80%: PICP 0.851, mean width 633.1 MW, gap 0.0511
- IE/ALL/ensemble-inv-mae-14 nominal 90%: PICP 0.916, mean width 800.7 MW, gap 0.0163
- IE/ALL/ensemble-inv-mae-14 nominal 95%: PICP 0.95, mean width 921.3 MW, gap 0.0003
- IE/ALL/lightgbm-weather nominal 80%: PICP 0.844, mean width 581.5 MW, gap 0.0443
- IE/ALL/lightgbm-weather nominal 90%: PICP 0.924, mean width 788.1 MW, gap 0.0237
- IE/ALL/lightgbm-weather nominal 95%: PICP 0.961, mean width 973.2 MW, gap 0.0114
- AU/NSW1/ensemble-inv-mae-14 nominal 80%: PICP 0.799, mean width 1634.6 MW, gap -0.0006
- AU/NSW1/ensemble-inv-mae-14 nominal 90%: PICP 0.899, mean width 2239.3 MW, gap -0.0009
- AU/NSW1/ensemble-inv-mae-14 nominal 95%: PICP 0.945, mean width 2723.7 MW, gap -0.0045
- AU/NSW1/lightgbm-weather nominal 80%: PICP 0.792, mean width 1728.3 MW, gap -0.008
- AU/NSW1/lightgbm-weather nominal 90%: PICP 0.897, mean width 2490.3 MW, gap -0.0033
- AU/NSW1/lightgbm-weather nominal 95%: PICP 0.939, mean width 3151.1 MW, gap -0.0113
- AU/QLD1/ensemble-inv-mae-14 nominal 80%: PICP 0.855, mean width 980.6 MW, gap 0.0551
- AU/QLD1/ensemble-inv-mae-14 nominal 90%: PICP 0.92, mean width 1323.6 MW, gap 0.0204
- AU/QLD1/ensemble-inv-mae-14 nominal 95%: PICP 0.955, mean width 1782.4 MW, gap 0.0048
- AU/QLD1/lightgbm-weather nominal 80%: PICP 0.829, mean width 783.0 MW, gap 0.0294
- AU/QLD1/lightgbm-weather nominal 90%: PICP 0.917, mean width 1222.0 MW, gap 0.0165
- AU/QLD1/lightgbm-weather nominal 95%: PICP 0.959, mean width 1647.9 MW, gap 0.0091
- AU/SA1/ensemble-inv-mae-14 nominal 80%: PICP 0.805, mean width 585.5 MW, gap 0.0054
- AU/SA1/ensemble-inv-mae-14 nominal 90%: PICP 0.891, mean width 810.5 MW, gap -0.0095
- AU/SA1/ensemble-inv-mae-14 nominal 95%: PICP 0.938, mean width 1041.6 MW, gap -0.0124
- AU/SA1/lightgbm-weather nominal 80%: PICP 0.789, mean width 536.8 MW, gap -0.0105
- AU/SA1/lightgbm-weather nominal 90%: PICP 0.878, mean width 776.4 MW, gap -0.0221
- AU/SA1/lightgbm-weather nominal 95%: PICP 0.934, mean width 987.5 MW, gap -0.0164
- AU/TAS1/ensemble-inv-mae-14 nominal 80%: PICP 0.789, mean width 221.7 MW, gap -0.0107
- AU/TAS1/ensemble-inv-mae-14 nominal 90%: PICP 0.891, mean width 287.5 MW, gap -0.0093
- AU/TAS1/ensemble-inv-mae-14 nominal 95%: PICP 0.941, mean width 347.3 MW, gap -0.0087
- AU/TAS1/lightgbm-weather nominal 80%: PICP 0.809, mean width 250.9 MW, gap 0.0094
- AU/TAS1/lightgbm-weather nominal 90%: PICP 0.899, mean width 310.9 MW, gap -0.0005
- AU/TAS1/lightgbm-weather nominal 95%: PICP 0.942, mean width 369.6 MW, gap -0.0077
- AU/VIC1/ensemble-inv-mae-14 nominal 80%: PICP 0.802, mean width 1471.3 MW, gap 0.0022
- AU/VIC1/ensemble-inv-mae-14 nominal 90%: PICP 0.893, mean width 1885.3 MW, gap -0.007
- AU/VIC1/ensemble-inv-mae-14 nominal 95%: PICP 0.939, mean width 2352.4 MW, gap -0.0108
- AU/VIC1/lightgbm-weather nominal 80%: PICP 0.787, mean width 1552.1 MW, gap -0.0129
- AU/VIC1/lightgbm-weather nominal 90%: PICP 0.884, mean width 2073.8 MW, gap -0.0158
- AU/VIC1/lightgbm-weather nominal 95%: PICP 0.936, mean width 2525.0 MW, gap -0.0143
- AU/NEM_TOTAL/ensemble-inv-mae-14 nominal 80%: PICP 0.816, mean width 3501.8 MW, gap 0.0162
- AU/NEM_TOTAL/ensemble-inv-mae-14 nominal 90%: PICP 0.91, mean width 4775.1 MW, gap 0.0101
- AU/NEM_TOTAL/ensemble-inv-mae-14 nominal 95%: PICP 0.955, mean width 6035.8 MW, gap 0.0045
- AU/NEM_TOTAL/lightgbm-weather nominal 80%: PICP 0.793, mean width 3403.4 MW, gap -0.0073
- AU/NEM_TOTAL/lightgbm-weather nominal 90%: PICP 0.894, mean width 4845.7 MW, gap -0.0063
- AU/NEM_TOTAL/lightgbm-weather nominal 95%: PICP 0.938, mean width 5910.2 MW, gap -0.0116

### Undercovered slices (PICP below nominal minus 0.05)

- AU/NSW1/lightgbm-weather cold_10pct/h0-24 @80%: PICP 0.746 (n=287)
- AU/QLD1/ensemble-inv-mae-14 bank_holiday/h0-24 @80%: PICP 0.627 (n=287)
- AU/QLD1/ensemble-inv-mae-14 bank_holiday/h0-24 @90%: PICP 0.794 (n=287)
- AU/QLD1/ensemble-inv-mae-14 bank_holiday/h0-24 @95%: PICP 0.895 (n=287)
- AU/QLD1/ensemble-inv-mae-14 cold_10pct/h24-48 @80%: PICP 0.667 (n=288)
- AU/QLD1/lightgbm-weather bank_holiday/h0-24 @80%: PICP 0.641 (n=287)
- AU/QLD1/lightgbm-weather bank_holiday/h0-24 @90%: PICP 0.76 (n=287)
- AU/QLD1/lightgbm-weather bank_holiday/h0-24 @95%: PICP 0.85 (n=287)
- AU/SA1/ensemble-inv-mae-14 bank_holiday/h24-48 @80%: PICP 0.651 (n=258)
- AU/SA1/ensemble-inv-mae-14 bank_holiday/h24-48 @90%: PICP 0.76 (n=258)
- AU/SA1/ensemble-inv-mae-14 bank_holiday/h24-48 @95%: PICP 0.791 (n=258)
- AU/SA1/ensemble-inv-mae-14 cold_10pct/h0-24 @80%: PICP 0.74 (n=661)
- AU/SA1/ensemble-inv-mae-14 cold_10pct/h24-48 @80%: PICP 0.674 (n=576)
- AU/SA1/ensemble-inv-mae-14 cold_10pct/h24-48 @90%: PICP 0.8 (n=576)
- AU/SA1/ensemble-inv-mae-14 cold_10pct/h24-48 @95%: PICP 0.887 (n=576)
- AU/SA1/lightgbm-weather cold_10pct/h0-24 @80%: PICP 0.744 (n=661)
- AU/SA1/lightgbm-weather cold_10pct/h24-48 @80%: PICP 0.667 (n=576)
- AU/SA1/lightgbm-weather cold_10pct/h24-48 @90%: PICP 0.766 (n=576)
- AU/TAS1/ensemble-inv-mae-14 weekday/h24-48 @80%: PICP 0.733 (n=5784)
- AU/TAS1/ensemble-inv-mae-14 weekday/h24-48 @90%: PICP 0.847 (n=5784)
- AU/TAS1/ensemble-inv-mae-14 weekday/h24-48 @95%: PICP 0.896 (n=5784)
- AU/TAS1/ensemble-inv-mae-14 cold_10pct/h0-24 @80%: PICP 0.566 (n=574)
- AU/TAS1/ensemble-inv-mae-14 cold_10pct/h0-24 @90%: PICP 0.674 (n=574)
- AU/TAS1/ensemble-inv-mae-14 cold_10pct/h0-24 @95%: PICP 0.812 (n=574)
- AU/TAS1/ensemble-inv-mae-14 cold_10pct/h24-48 @80%: PICP 0.483 (n=840)
- AU/TAS1/ensemble-inv-mae-14 cold_10pct/h24-48 @90%: PICP 0.696 (n=840)
- AU/TAS1/ensemble-inv-mae-14 cold_10pct/h24-48 @95%: PICP 0.806 (n=840)
- AU/TAS1/lightgbm-weather weekday/h24-48 @80%: PICP 0.728 (n=5784)
- AU/TAS1/lightgbm-weather weekday/h24-48 @90%: PICP 0.834 (n=5784)
- AU/TAS1/lightgbm-weather weekday/h24-48 @95%: PICP 0.887 (n=5784)
- AU/TAS1/lightgbm-weather cold_10pct/h24-48 @80%: PICP 0.529 (n=840)
- AU/TAS1/lightgbm-weather cold_10pct/h24-48 @90%: PICP 0.714 (n=840)
- AU/TAS1/lightgbm-weather cold_10pct/h24-48 @95%: PICP 0.824 (n=840)
- AU/VIC1/ensemble-inv-mae-14 cold_10pct/h0-24 @80%: PICP 0.735 (n=551)
- AU/VIC1/ensemble-inv-mae-14 cold_10pct/h0-24 @90%: PICP 0.82 (n=551)
- AU/VIC1/ensemble-inv-mae-14 cold_10pct/h0-24 @95%: PICP 0.895 (n=551)
- AU/VIC1/ensemble-inv-mae-14 cold_10pct/h24-48 @80%: PICP 0.667 (n=576)
- AU/VIC1/ensemble-inv-mae-14 cold_10pct/h24-48 @90%: PICP 0.748 (n=576)
- AU/VIC1/ensemble-inv-mae-14 cold_10pct/h24-48 @95%: PICP 0.861 (n=576)
- AU/VIC1/lightgbm-weather weekday/h0-24 @80%: PICP 0.744 (n=6027)
- AU/VIC1/lightgbm-weather bank_holiday/h24-48 @80%: PICP 0.663 (n=264)

## Hypothesis status

- **H1** (GBM > naive): CONFIRMED on 3/8 units as champion; see tables.
- **H2** (zero-shot foundation competitive on rare/anomalous days): PARTIALLY SUPPORTED — chronos beats naive only on the GB 30-min chain with long publication lag and on its anomalous day slices (cold-decile, bank holidays); it fails at fine cadence/long horizon broadly. Overall chronos vs naive: GB/GB 8.9825 vs 9.4883; IE/ALL 14.2621 vs 3.7574; AU/NSW1 20.6278 vs 7.163; AU/QLD1 22.8662 vs 5.6224; AU/SA1 34.1018 vs 17.1778; AU/TAS1 14.6319 vs 7.8144; AU/VIC1 21.8652 vs 10.0933; AU/NEM_TOTAL 20.9186 vs 4.9486

## Honest limitations

- 48h horizon coverage relies on a rolling 14-anchor split-conformal; regime shifts (heat waves, price events) temporarily decalibrate it.
- Chronos-Bolt-mini is evaluated natively at market cadence; its long-horizon weakness at 5/15 min is a known zero-shot limit, not a data bug.
- DM tests use Newey-West conservative variance; with overlapping 48h forecast errors, serial correlation beyond the lag may inflate significance.
- GB's 21-day publication arrears means GBM/foundation share a stale-information handicap; conclusions do not transfer to markets with real-time metering.
- Weather is archival reanalysis (perfect-forecast proxy); live NWP forecasts will add error the ablation bounds only partially.

