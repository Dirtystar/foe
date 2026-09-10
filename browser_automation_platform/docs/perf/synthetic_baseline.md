# Performance report — 1-world (synthetic)

- Created: `2026-07-15T20:59:53+00:00`  ·  git `3953747`
- Machine: Linux-6.18.5-x86_64-with-glibc2.39  ·  4 CPU  ·  Python 3.11.15
- Frames replayed: 66  ·  config: `{'world_count': 1, 'ticks_per_world': 3, 'total_ticks': 3, 'persist': False}`
- wall_seconds=8.9839  ·  throughput_fps=0.334  ·  per_world_fps=0.334

## Global tick timing (ms)

| scope | mean | median | p95 | p99 | worst | fps |
|---|---|---|---|---|---|---|
| **total** | 2994.412 | 3355.081 | 3663.941 | 3691.395 | 3698.259 | 0.33 |
| capture | 0.002 | 0.002 | 0.002 | 0.002 | 0.002 | 534188.04 |
| detection | 2835.030 | 3191.636 | 3500.964 | 3528.459 | 3535.334 | 0.35 |
| classification | 55.381 | 54.327 | 57.530 | 57.815 | 57.886 | 18.06 |
| weakening_ocr | 103.875 | 105.423 | 108.532 | 108.808 | 108.877 | 9.63 |
| decision | 0.018 | 0.016 | 0.020 | 0.020 | 0.020 | 57002.79 |

## Per-World timing (ms)

| world | ticks | skipped | mean | median | p95 | worst | fps | worst stage |
|---|---|---|---|---|---|---|---|---|
| W1 | 3 | 0 | 2994.412 | 3355.081 | 3663.941 | 3698.259 | 0.33 | detection |

## System

- Uptime: 8.991 s  ·  backend: proc
- CPU: avg 317.82%  ·  peak 319.38%  ·  4 cores
- RAM: avg 461.23 MB  ·  peak 461.24 MB  ·  current 461.24 MB


---

# Performance report — 2-world (synthetic)

- Created: `2026-07-15T21:00:16+00:00`  ·  git `3953747`
- Machine: Linux-6.18.5-x86_64-with-glibc2.39  ·  4 CPU  ·  Python 3.11.15
- Frames replayed: 66  ·  config: `{'world_count': 2, 'ticks_per_world': 3, 'total_ticks': 6, 'persist': False}`
- wall_seconds=20.6325  ·  throughput_fps=0.291  ·  per_world_fps=0.291

## Global tick timing (ms)

| scope | mean | median | p95 | p99 | worst | fps |
|---|---|---|---|---|---|---|
| **total** | 3438.628 | 3647.613 | 3960.043 | 3963.461 | 3964.315 | 0.29 |
| capture | 0.002 | 0.002 | 0.002 | 0.002 | 0.002 | 591133.02 |
| detection | 3275.073 | 3487.592 | 3793.626 | 3801.380 | 3803.318 | 0.30 |
| classification | 59.779 | 59.087 | 65.149 | 65.456 | 65.532 | 16.73 |
| weakening_ocr | 103.648 | 98.966 | 119.490 | 121.241 | 121.678 | 9.65 |
| decision | 0.017 | 0.015 | 0.024 | 0.026 | 0.026 | 60546.13 |

## Per-World timing (ms)

| world | ticks | skipped | mean | median | p95 | worst | fps | worst stage |
|---|---|---|---|---|---|---|---|---|
| W1 | 3 | 0 | 3165.461 | 3615.919 | 3914.098 | 3947.229 | 0.32 | detection |
| W2 | 3 | 0 | 3711.796 | 3679.306 | 3935.814 | 3964.315 | 0.27 | detection |

## System

- Uptime: 20.635 s  ·  backend: proc
- CPU: avg 255.91%  ·  peak 310.22%  ·  4 cores
- RAM: avg 461.29 MB  ·  peak 461.3 MB  ·  current 461.3 MB


---

# Performance report — 4-world (synthetic)

- Created: `2026-07-15T21:00:58+00:00`  ·  git `3953747`
- Machine: Linux-6.18.5-x86_64-with-glibc2.39  ·  4 CPU  ·  Python 3.11.15
- Frames replayed: 66  ·  config: `{'world_count': 4, 'ticks_per_world': 3, 'total_ticks': 12, 'persist': False}`
- wall_seconds=40.7866  ·  throughput_fps=0.294  ·  per_world_fps=0.294

## Global tick timing (ms)

| scope | mean | median | p95 | p99 | worst | fps |
|---|---|---|---|---|---|---|
| **total** | 3398.774 | 3329.261 | 4373.739 | 4957.347 | 5103.249 | 0.29 |
| capture | 0.001 | 0.001 | 0.002 | 0.002 | 0.002 | 842400.86 |
| detection | 3242.035 | 3163.050 | 4216.156 | 4801.805 | 4948.217 | 0.31 |
| classification | 60.483 | 57.859 | 76.910 | 83.280 | 84.872 | 16.53 |
| weakening_ocr | 96.143 | 96.373 | 100.001 | 101.624 | 102.029 | 10.40 |
| decision | 0.013 | 0.014 | 0.015 | 0.015 | 0.015 | 77212.13 |

## Per-World timing (ms)

| world | ticks | skipped | mean | median | p95 | worst | fps | worst stage |
|---|---|---|---|---|---|---|---|---|
| W1 | 3 | 0 | 3074.641 | 3541.128 | 3753.293 | 3776.867 | 0.33 | detection |
| W2 | 3 | 0 | 3424.525 | 3412.106 | 3673.415 | 3702.450 | 0.29 | detection |
| W3 | 3 | 0 | 3290.686 | 3323.297 | 3334.032 | 3335.225 | 0.30 | detection |
| W4 | 3 | 0 | 3805.245 | 3211.932 | 4914.117 | 5103.249 | 0.26 | detection |

## System

- Uptime: 40.789 s  ·  backend: proc
- CPU: avg 286.3%  ·  peak 320.13%  ·  4 cores
- RAM: avg 461.35 MB  ·  peak 461.38 MB  ·  current 461.38 MB


---

# Performance report — 8-world (synthetic)

- Created: `2026-07-15T21:02:18+00:00`  ·  git `3953747`
- Machine: Linux-6.18.5-x86_64-with-glibc2.39  ·  4 CPU  ·  Python 3.11.15
- Frames replayed: 66  ·  config: `{'world_count': 8, 'ticks_per_world': 3, 'total_ticks': 24, 'persist': False}`
- wall_seconds=77.4001  ·  throughput_fps=0.31  ·  per_world_fps=0.31

## Global tick timing (ms)

| scope | mean | median | p95 | p99 | worst | fps |
|---|---|---|---|---|---|---|
| **total** | 3224.889 | 3236.332 | 5294.201 | 5377.027 | 5400.255 | 0.31 |
| capture | 0.001 | 0.001 | 0.002 | 0.002 | 0.002 | 859352.64 |
| detection | 3062.716 | 3073.834 | 5132.403 | 5225.030 | 5251.488 | 0.33 |
| classification | 58.278 | 57.725 | 63.336 | 64.821 | 65.177 | 17.16 |
| weakening_ocr | 103.779 | 96.660 | 146.031 | 193.016 | 205.025 | 9.64 |
| decision | 0.013 | 0.014 | 0.017 | 0.019 | 0.019 | 78058.68 |

## Per-World timing (ms)

| world | ticks | skipped | mean | median | p95 | worst | fps | worst stage |
|---|---|---|---|---|---|---|---|---|
| W1 | 3 | 0 | 3099.401 | 3398.372 | 3960.485 | 4022.941 | 0.32 | detection |
| W2 | 3 | 0 | 3529.064 | 3627.817 | 3707.058 | 3715.863 | 0.28 | detection |
| W3 | 3 | 0 | 3340.466 | 3340.319 | 3440.767 | 3451.928 | 0.30 | detection |
| W4 | 3 | 0 | 3886.036 | 3210.940 | 5090.432 | 5299.264 | 0.26 | detection |
| W5 | 3 | 0 | 3903.020 | 3335.637 | 5072.523 | 5265.510 | 0.26 | detection |
| W6 | 3 | 0 | 3645.211 | 3165.474 | 5176.777 | 5400.255 | 0.27 | detection |
| W7 | 3 | 0 | 2563.912 | 2242.194 | 3231.050 | 3340.922 | 0.39 | detection |
| W8 | 3 | 0 | 1832.001 | 2011.417 | 2196.215 | 2216.748 | 0.55 | detection |

## System

- Uptime: 77.402 s  ·  backend: proc
- CPU: avg 292.98%  ·  peak 319.69%  ·  4 cores
- RAM: avg 461.41 MB  ·  peak 461.43 MB  ·  current 461.43 MB
