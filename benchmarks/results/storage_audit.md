# Storage audit

## Calculation (official rate)

60 signals x 10 Hz x 86,400 s = **51,840,000 samples/day** (CALCULATION).

## Measured representations

| representation | measured | label |
|---|---|---|
| SQLite row incl. indexes | 647.2 bytes/row (over 500,000 rows) | MEASUREMENT |
| CSV dump | 82.2 bytes/sample | MEASUREMENT |
| gzip of that CSV | 5.5 bytes/sample (ratio 14.94x) | MEASUREMENT |

## Extrapolations at the official 10 Hz rate

| scenario | per day | 30 days | 60 days | label |
|---|---|---|---|---|
| SQLite, raw 10 Hz | 33.6 GB | 1006.5 GB | 2013.1 GB | ESTIMATE |
| gzip CSV, raw 10 Hz | 0.29 GB | - | 17.1 GB | ESTIMATE |

## Actually generated demo dataset

- size: **681.7 MB** over 60 days = **11.4 MB/day** (MEASUREMENT)
- representation: mixed rate: 1 Hz primary signals during trips, 0.2 Hz secondary, ambient every 5 min - i.e. the WARM (decimated) tier, not raw 10 Hz

## Conclusion

Full-rate 10 Hz x 60 signals cannot live in SQLite for weeks: the measured row cost gives ~33.6 GB/day. The architecture therefore keeps raw frames only for the hot window (48 h, not part of this prototype's persistence) and stores a decimated warm tier, which the demo dataset measures at 11.4 MB/day (0.7 GB for 60 days).
