# ASR error-correction cascade — smoke results

- run: 2026-10-06T04:49:09.988802+00:00
- clips: 10 (zh 5, en 5) — all clips verified to contain real ASR errors
- thresholds: gate=0.35 suspect=0.5 choice_conf=0.6

## Aggregate (all clips)

| condition | n | err A→(B)/D | impr/same/worse | det P | det R | overcorr D | overcorr B | edits choice/llm | latency s |
|---|---|---|---|---|---|---|---|---|---|
| A raw ASR | 10 | 0.0736 | - | - | - | - | - | - | - |
| D jev-1.13-free | 10 | 0.0736 -> 0.0495 | 5/4/1 | 0.28 | 0.583 | 1 | 1 | 0/8 | 3.76 |

## Per-language err means


## Per-clip detail (SemIf)

## OpenCode usage guard (jev-1.13-free free-ness check)

before:
```
{"usage":{"rolling":{"status":"ok","percent":0,"resetsAt":"2026-10-06T09:48:00.293Z"},"weekly":{"status":"ok","percent":1,"resetsAt":"2026-10-12T00:00:00.000Z"},"monthly":{"status":"ok","percent":74,"resetsAt":"2026-10-13T08:49:05.000Z"}}}
```
after:
```
{"usage":{"rolling":{"status":"ok","percent":0,"resetsAt":"2026-10-06T09:49:09.928Z"},"weekly":{"status":"ok","percent":1,"resetsAt":"2026-10-12T00:00:00.000Z"},"monthly":{"status":"ok","percent":74,"resetsAt":"2026-10-13T08:49:05.000Z"}}}
```