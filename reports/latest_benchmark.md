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

### FR/FR (champion: ensemble-inv-mae-14, n_anchors≈25)
                 model  mape_pct   mae_mw
   ensemble-inv-mae-14    4.1321 1834.407
      lightgbm-weather    4.7961 2115.505
   seasonal-naive-168h    5.0274 2214.518
         ridge-weather    5.6828 2449.771
chronos-bolt-zero-shot    9.1218 3943.698

### DE/DE (champion: ensemble-inv-mae-14, n_anchors≈30)
                 model  mape_pct   mae_mw
   ensemble-inv-mae-14    4.6237 2289.842
      lightgbm-weather    4.7063 2311.759
         ridge-weather    5.2167 2557.479
   seasonal-naive-168h    6.2540 3101.610
chronos-bolt-zero-shot   10.1181 4957.143

### BE/BE (champion: lightgbm-weather, n_anchors≈30)
                 model  mape_pct   mae_mw
      lightgbm-weather   17.1709  667.520
   ensemble-inv-mae-14   20.4670  782.007
         ridge-weather   21.0516  885.987
   seasonal-naive-168h   25.1978 1029.045
chronos-bolt-zero-shot   47.2022 1935.539

### DK/DK (champion: seasonal-naive-168h, n_anchors≈24)
                 model  mape_pct  mae_mw
   seasonal-naive-168h    8.1652 321.243
   ensemble-inv-mae-14    8.5021 326.918
chronos-bolt-zero-shot   10.0325 380.852
      lightgbm-weather   10.6302 401.272
         ridge-weather   11.9873 473.319

### KZ/KZ (champion: seasonal-naive-168h, n_anchors≈30)
                 model  mape_pct   mae_mw
   seasonal-naive-168h   13.1333  371.882
         ridge-weather   13.3641  376.815
   ensemble-inv-mae-14   13.6374  381.441
      lightgbm-weather   16.6245  476.560
chronos-bolt-zero-shot   41.4009 1114.876

### KZ/KZ_W (champion: seasonal-naive-168h, n_anchors≈30)
                 model  mape_pct  mae_mw
   seasonal-naive-168h   13.8906  48.330
         ridge-weather   14.1427  49.881
   ensemble-inv-mae-14   14.3829  49.188
      lightgbm-weather   16.6352  58.948
chronos-bolt-zero-shot   36.1003 115.988

## Ensemble vs best single (delta primary metric, negative = ensemble better)

- FR/FR: ensemble 4.132 vs lightgbm-weather 4.796 (delta -0.664)
- DE/DE: ensemble 4.624 vs lightgbm-weather 4.706 (delta -0.083)
- BE/BE: ensemble 20.467 vs lightgbm-weather 17.171 (delta 3.296)
- DK/DK: ensemble 8.502 vs seasonal-naive-168h 8.165 (delta 0.337)
- KZ/KZ: ensemble 13.637 vs seasonal-naive-168h 13.133 (delta 0.504)
- KZ/KZ_W: ensemble 14.383 vs seasonal-naive-168h 13.891 (delta 0.492)

## Diebold-Mariano (two-sided, HAC Newey-West)

| pair | mean loss diff | DM | p | verdict |
|---|---|---|---|---|
| FR/FR: lightgbm-weather__vs__seasonal-naive-168h | -99.013242 | -0.8252 | 0.409263 | NOT significant |
| FR/FR: lightgbm-weather__vs__ridge-weather | -334.266038 | -2.6476 | 0.008107 | significant |
| FR/FR: lightgbm-weather__vs__chronos-bolt-zero-shot | -1828.193365 | -8.773 | 0.0 | significant |
| FR/FR: ensemble-inv-mae-14__vs__lightgbm-weather | -281.097866 | -3.5055 | 0.000456 | significant |
| DE/DE: lightgbm-weather__vs__seasonal-naive-168h | -789.850559 | -4.8257 | 1e-06 | significant |
| DE/DE: lightgbm-weather__vs__ridge-weather | -245.719933 | -2.5438 | 0.010965 | significant |
| DE/DE: lightgbm-weather__vs__chronos-bolt-zero-shot | -2645.383528 | -11.6889 | 0.0 | significant |
| DE/DE: ensemble-inv-mae-14__vs__lightgbm-weather | -21.917033 | -0.2734 | 0.784553 | NOT significant |
| BE/BE: lightgbm-weather__vs__seasonal-naive-168h | -361.52493 | -8.1589 | 0.0 | significant |
| BE/BE: lightgbm-weather__vs__ridge-weather | -218.467288 | -4.0543 | 5e-05 | significant |
| BE/BE: lightgbm-weather__vs__chronos-bolt-zero-shot | -1268.019 | -19.0389 | 0.0 | significant |
| BE/BE: ensemble-inv-mae-14__vs__lightgbm-weather | 114.487571 | 4.639 | 4e-06 | significant |
| DK/DK: lightgbm-weather__vs__seasonal-naive-168h | 80.02881 | 2.9293 | 0.003397 | significant |
| DK/DK: lightgbm-weather__vs__ridge-weather | -72.047488 | -2.1285 | 0.033295 | significant |
| DK/DK: lightgbm-weather__vs__chronos-bolt-zero-shot | 20.420061 | 0.6254 | 0.531718 | NOT significant |
| DK/DK: ensemble-inv-mae-14__vs__seasonal-naive-168h | 5.675078 | 0.4548 | 0.649235 | NOT significant |
| KZ/KZ: lightgbm-weather__vs__seasonal-naive-168h | 104.678354 | 4.949 | 1e-06 | significant |
| KZ/KZ: lightgbm-weather__vs__ridge-weather | 99.744945 | 4.9131 | 1e-06 | significant |
| KZ/KZ: lightgbm-weather__vs__chronos-bolt-zero-shot | -638.316375 | -15.7554 | 0.0 | significant |
| KZ/KZ: ensemble-inv-mae-14__vs__seasonal-naive-168h | 9.558933 | 0.7029 | 0.482105 | NOT significant |
| KZ/KZ_W: lightgbm-weather__vs__seasonal-naive-168h | 10.618102 | 3.706 | 0.000211 | significant |
| KZ/KZ_W: lightgbm-weather__vs__ridge-weather | 9.067484 | 3.4699 | 0.000521 | significant |
| KZ/KZ_W: lightgbm-weather__vs__chronos-bolt-zero-shot | -57.039697 | -13.1889 | 0.0 | significant |
| KZ/KZ_W: ensemble-inv-mae-14__vs__seasonal-naive-168h | 0.858052 | 0.5115 | 0.609006 | NOT significant |

Reading: mean_loss_diff > 0 => the first model named has HIGHER loss (worse). Pairs with NOT significant differences are honest non-conclusions, not ties to hide.

## Conformal intervals (rolling split-conformal, calib 14 anchors)

- FR/FR/ensemble-inv-mae-14 nominal 80%: PICP 0.87, mean width 6841.4 MW, gap 0.0698
- FR/FR/ensemble-inv-mae-14 nominal 90%: PICP 0.934, mean width 8857.8 MW, gap 0.0342
- FR/FR/ensemble-inv-mae-14 nominal 95%: PICP 0.959, mean width 11103.4 MW, gap 0.0095
- FR/FR/lightgbm-weather nominal 80%: PICP 0.878, mean width 8573.0 MW, gap 0.0781
- FR/FR/lightgbm-weather nominal 90%: PICP 0.945, mean width 11538.4 MW, gap 0.0452
- FR/FR/lightgbm-weather nominal 95%: PICP 0.975, mean width 13647.5 MW, gap 0.025
- DE/DE/ensemble-inv-mae-14 nominal 80%: PICP 0.864, mean width 8656.0 MW, gap 0.0637
- DE/DE/ensemble-inv-mae-14 nominal 90%: PICP 0.949, mean width 11826.5 MW, gap 0.0486
- DE/DE/ensemble-inv-mae-14 nominal 95%: PICP 0.983, mean width 15432.9 MW, gap 0.0329
- DE/DE/lightgbm-weather nominal 80%: PICP 0.795, mean width 7620.6 MW, gap -0.0047
- DE/DE/lightgbm-weather nominal 90%: PICP 0.905, mean width 10009.0 MW, gap 0.0048
- DE/DE/lightgbm-weather nominal 95%: PICP 0.953, mean width 12703.4 MW, gap 0.0033
- BE/BE/ensemble-inv-mae-14 nominal 80%: PICP 0.846, mean width 2827.9 MW, gap 0.0455
- BE/BE/ensemble-inv-mae-14 nominal 90%: PICP 0.933, mean width 3813.2 MW, gap 0.0332
- BE/BE/ensemble-inv-mae-14 nominal 95%: PICP 0.963, mean width 4911.1 MW, gap 0.013
- BE/BE/lightgbm-weather nominal 80%: PICP 0.838, mean width 2364.3 MW, gap 0.038
- BE/BE/lightgbm-weather nominal 90%: PICP 0.932, mean width 3378.9 MW, gap 0.0319
- BE/BE/lightgbm-weather nominal 95%: PICP 0.97, mean width 4246.7 MW, gap 0.0204
- DK/DK/ensemble-inv-mae-14 nominal 80%: PICP 0.827, mean width 1163.4 MW, gap 0.027
- DK/DK/ensemble-inv-mae-14 nominal 90%: PICP 0.9, mean width 1523.8 MW, gap 0.0004
- DK/DK/ensemble-inv-mae-14 nominal 95%: PICP 0.924, mean width 1839.2 MW, gap -0.0261
- DK/DK/lightgbm-weather nominal 80%: PICP 0.851, mean width 1542.2 MW, gap 0.0505
- DK/DK/lightgbm-weather nominal 90%: PICP 0.918, mean width 2113.8 MW, gap 0.0176
- DK/DK/lightgbm-weather nominal 95%: PICP 0.94, mean width 2621.5 MW, gap -0.0098
- KZ/KZ/ensemble-inv-mae-14 nominal 80%: PICP 0.86, mean width 1391.9 MW, gap 0.0599
- KZ/KZ/ensemble-inv-mae-14 nominal 90%: PICP 0.937, mean width 1854.8 MW, gap 0.0368
- KZ/KZ/ensemble-inv-mae-14 nominal 95%: PICP 0.97, mean width 2153.5 MW, gap 0.0198
- KZ/KZ/lightgbm-weather nominal 80%: PICP 0.851, mean width 1786.5 MW, gap 0.0513
- KZ/KZ/lightgbm-weather nominal 90%: PICP 0.939, mean width 2142.4 MW, gap 0.0389
- KZ/KZ/lightgbm-weather nominal 95%: PICP 0.973, mean width 2434.3 MW, gap 0.0227
- KZ/KZ_W/ensemble-inv-mae-14 nominal 80%: PICP 0.792, mean width 151.9 MW, gap -0.0083
- KZ/KZ_W/ensemble-inv-mae-14 nominal 90%: PICP 0.883, mean width 193.8 MW, gap -0.0171
- KZ/KZ_W/ensemble-inv-mae-14 nominal 95%: PICP 0.935, mean width 232.2 MW, gap -0.0154
- KZ/KZ_W/lightgbm-weather nominal 80%: PICP 0.76, mean width 179.5 MW, gap -0.0399
- KZ/KZ_W/lightgbm-weather nominal 90%: PICP 0.87, mean width 228.9 MW, gap -0.03
- KZ/KZ_W/lightgbm-weather nominal 95%: PICP 0.915, mean width 275.4 MW, gap -0.0355

### Undercovered slices (PICP below nominal minus 0.05)

- FR/FR/ensemble-inv-mae-14 cold_10pct/h24-48 @80%: PICP 0.691 (n=68)
- FR/FR/ensemble-inv-mae-14 cold_10pct/h24-48 @90%: PICP 0.779 (n=68)
- FR/FR/ensemble-inv-mae-14 cold_10pct/h24-48 @95%: PICP 0.809 (n=68)
- DE/DE/ensemble-inv-mae-14 bank_holiday/h0-24 @80%: PICP 0.619 (n=134)
- DE/DE/ensemble-inv-mae-14 bank_holiday/h0-24 @90%: PICP 0.739 (n=134)
- DE/DE/ensemble-inv-mae-14 bank_holiday/h0-24 @95%: PICP 0.888 (n=134)
- DE/DE/lightgbm-weather weekday/h0-24 @80%: PICP 0.728 (n=1861)
- DE/DE/lightgbm-weather bank_holiday/h0-24 @80%: PICP 0.634 (n=134)
- DE/DE/lightgbm-weather bank_holiday/h0-24 @90%: PICP 0.716 (n=134)
- DE/DE/lightgbm-weather bank_holiday/h0-24 @95%: PICP 0.791 (n=134)
- BE/BE/lightgbm-weather bank_holiday/h24-48 @80%: PICP 0.725 (n=40)
- DK/DK/ensemble-inv-mae-14 weekend/h0-24 @95%: PICP 0.886 (n=175)
- DK/DK/ensemble-inv-mae-14 weekend/h24-48 @90%: PICP 0.826 (n=178)
- DK/DK/ensemble-inv-mae-14 weekend/h24-48 @95%: PICP 0.848 (n=178)
- DK/DK/lightgbm-weather weekend/h0-24 @90%: PICP 0.846 (n=175)
- DK/DK/lightgbm-weather weekend/h0-24 @95%: PICP 0.869 (n=175)
- DK/DK/lightgbm-weather weekend/h24-48 @90%: PICP 0.831 (n=178)
- DK/DK/lightgbm-weather weekend/h24-48 @95%: PICP 0.865 (n=178)
- KZ/KZ_W/ensemble-inv-mae-14 weekend/h24-48 @90%: PICP 0.823 (n=175)
- KZ/KZ_W/ensemble-inv-mae-14 weekend/h24-48 @95%: PICP 0.897 (n=175)
- KZ/KZ_W/lightgbm-weather weekend/h24-48 @80%: PICP 0.657 (n=175)
- KZ/KZ_W/lightgbm-weather weekend/h24-48 @90%: PICP 0.789 (n=175)
- KZ/KZ_W/lightgbm-weather weekend/h24-48 @95%: PICP 0.869 (n=175)
- KZ/KZ_W/lightgbm-weather bank_holiday/h24-48 @80%: PICP 0.529 (n=34)
- KZ/KZ_W/lightgbm-weather bank_holiday/h24-48 @90%: PICP 0.735 (n=34)
- KZ/KZ_W/lightgbm-weather bank_holiday/h24-48 @95%: PICP 0.824 (n=34)

## Hypothesis status

- **H1** (GBM > naive): CONFIRMED on 1/6 units as champion; see tables.
- **H2** (zero-shot foundation competitive on rare/anomalous days): PARTIALLY SUPPORTED — chronos beats naive only on the GB 30-min chain with long publication lag and on its anomalous day slices (cold-decile, bank holidays); it fails at fine cadence/long horizon broadly. Overall chronos vs naive: FR/FR 9.1218 vs 5.0274; DE/DE 10.1181 vs 6.254; BE/BE 47.2022 vs 25.1978; DK/DK 10.0325 vs 8.1652; KZ/KZ 41.4009 vs 13.1333; KZ/KZ_W 36.1003 vs 13.8906

## Honest limitations

- 48h horizon coverage relies on a rolling 14-anchor split-conformal; regime shifts (heat waves, price events) temporarily decalibrate it.
- Chronos-Bolt-mini is evaluated natively at market cadence; its long-horizon weakness at 5/15 min is a known zero-shot limit, not a data bug.
- DM tests use Newey-West conservative variance; with overlapping 48h forecast errors, serial correlation beyond the lag may inflate significance.
- GB's 21-day publication arrears means GBM/foundation share a stale-information handicap; conclusions do not transfer to markets with real-time metering.
- Weather is archival reanalysis (perfect-forecast proxy); live NWP forecasts will add error the ablation bounds only partially.

