# Performance report — 30-ticks (stress)

- Created: `2026-07-15T21:04:03+00:00`  ·  git `3953747`
- Machine: Linux-6.18.5-x86_64-with-glibc2.39  ·  4 CPU  ·  Python 3.11.15
- Frames replayed: 66  ·  config: `{'total_ticks': 30, 'persist': False}`
- wall_seconds=103.7608  ·  throughput_fps=0.289

## Global tick timing (ms)

| scope | mean | median | p95 | p99 | worst | fps |
|---|---|---|---|---|---|---|
| **total** | 3458.628 | 3637.424 | 5266.832 | 5318.961 | 5320.211 | 0.29 |
| capture | 0.001 | 0.001 | 0.001 | 0.002 | 0.002 | 894934.67 |
| detection | 3300.829 | 3486.384 | 5121.650 | 5171.226 | 5172.237 | 0.30 |
| classification | 59.513 | 57.100 | 71.320 | 84.528 | 87.614 | 16.80 |
| weakening_ocr | 98.165 | 94.305 | 121.849 | 153.178 | 160.098 | 10.19 |
| decision | 0.015 | 0.015 | 0.019 | 0.025 | 0.027 | 67615.08 |

## System

- Uptime: 103.763 s  ·  backend: proc
- CPU: avg 284.79%  ·  peak 322.53%  ·  4 cores
- RAM: avg 464.46 MB  ·  peak 465.54 MB  ·  current 465.54 MB
