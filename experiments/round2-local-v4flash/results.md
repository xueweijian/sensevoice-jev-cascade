# ASR error-correction cascade — smoke results

- run: 2026-10-06T07:01:53.203432+00:00
- clips: 10 (zh 5, en 5) — all clips verified to contain real ASR errors
- thresholds: gate=0.35 suspect=0.5 choice_conf=0.6

## Aggregate (all clips)

| condition | n | err A→(B)/D | impr/same/worse | det P | det R | overcorr D | overcorr B | edits choice/llm | latency s |
|---|---|---|---|---|---|---|---|---|---|
| A raw ASR | 10 | 0.0736 | - | - | - | - | - | - | - |
| D Kev-4B | 10 | 0.0736 -> 0.0631 | 2/7/1 | 0.667 | 0.167 | 1 | 1 | 0/3 | 3.43 |
| D SemIf | 10 | 0.0736 -> 0.0763 | 3/4/3 | 0.571 | 0.364 | 3 | 1 | 0/7 | 3.56 |
| D diffusiongemma | 10 | 0.0736 -> 0.0837 | 1/7/2 | 0.364 | 0.333 | 4 | 1 | 2/6 | 11.38 |
| D jev-1.13-free | 10 | 0.0736 -> 0.0818 | 3/3/4 | 0.25 | 0.667 | 6 | 1 | 0/13 | 11.22 |

## Per-language err means

- zh (SemIf): A 0.0779 -> D 0.1155, B 0.0118
- en (SemIf): A 0.0693 -> D 0.0372, B 0.0286

## Per-clip detail (SemIf)

### BAC009S0002W0122 (zh) err A=0.0667 B=0.0 D=0.1333
- ref: `而对楼市成交抑制作用最大的限购`
- hyp: `而对面楼市成交抑制作用最大的限购`
- D-fixed: `而对面楼市成交抑制作用最大的限构`
- edits: [(15, '购', '构', 'llm:deepseek')]
- B-fixed: `而对楼市成交抑制作用最大的限购`

### BAC009S0002W0130 (zh) err A=0.0833 B=0.0 D=0.0833
- ref: `财政金融政策紧随其后而来`
- hyp: `财政金融政策紧随其候而来`
- D-fixed: `财政金融政策紧随其候而来`
- edits: []
- B-fixed: `财政金融政策紧随其后而来`

### BAC009S0002W0132 (zh) err A=0.0588 B=0.0588 D=0.1176
- ref: `放松了与自往需求密切相关的房贷政策`
- hyp: `放松了与自网需求密切相关的房贷政策`
- D-fixed: `放送了与自网需求密切相关的房贷政策`
- edits: [(1, '松', '送', 'llm:deepseek')]
- B-fixed: `放松了与自网需求密切相关的房贷政策`

### BAC009S0002W0136 (zh) err A=0.125 B=0.0 D=0.1875
- ref: `这个后来被称为九三零新政策的措施`
- hyp: `这个后来被称为九百三十新政策的措施`
- D-fixed: `这个后赖被称为九百三十新政策的措施`
- edits: [(3, '来', '赖', 'llm:deepseek')]
- B-fixed: `这个后来被称为九三零新政策的措施`

### BAC009S0002W0139 (zh) err A=0.0556 B=0.0 D=0.0556
- ref: `支持缴存职工购买首套和改善型自住住房`
- hyp: `支持缴存职工购买手套和改善型自住住房`
- D-fixed: `支持缴存职工购买手套和改善型自住住房`
- edits: []
- B-fixed: `支持缴存职工购买首套和改善型自住住房`

### 1320-122612-0001 (en) err A=0.0333 B=0.0 D=0.0333
- ref: `the dews were suffered to exhale and the sun had dispersed the mists and was shedding a strong and clear light in the forest when the travelers resumed their journey`
- hyp: `the dews were suffered to exhale and the sun had dispersed the mists and was shedding a strong and clear light in the forest when the travellers resumed their journey`
- D-fixed: `the dews were suffered to exhale and the sun had dispersed the mists and was shedding a strong and clear light in the forest when the travellers resumed their journey`
- edits: []
- B-fixed: `the dews were suffered to exhale and the sun had dispersed the mists and was shedding a strong and clear light in the forest when the travelers resumed their journey`

### 1320-122612-0002 (en) err A=0.0556 B=0.0 D=0.0
- ref: `after proceeding a few miles the progress of hawkeye who led the advance became more deliberate and watchful`
- hyp: `after proceedcing a few miles the progress of hawkeye who led the advance became more deliberate and watchful`
- D-fixed: `after proceeding a few miles the progress of hawkeye who led the advance became more deliberate and watchful`
- edits: [(1, 'proceedcing', 'proceeding', 'llm:deepseek')]
- B-fixed: `after proceeding a few miles the progress of hawkeye who led the advance became more deliberate and watchful`

### 1320-122612-0003 (en) err A=0.0769 B=0.0 D=0.0385
- ref: `he often stopped to examine the trees nor did he cross a rivulet without attentively considering the quantity the velocity and the color of its waters`
- hyp: `he often stopped to examine the trees nor did he cross aivulet without attentively considering the quantity the velocity and the color of its waters`
- D-fixed: `he often stopped to examine the trees nor did he cross rivulet without attentively considering the quantity the velocity and the color of its waters`
- edits: [(11, 'aivulet', 'rivulet', 'llm:deepseek')]
- B-fixed: `he often stopped to examine the trees nor did he cross a rivulet without attentively considering the quantity the velocity and the color of its waters`

### 1320-122612-0004 (en) err A=0.1333 B=0.0 D=0.0667
- ref: `distrusting his own judgment his appeals to the opinion of chingachgook were frequent and earnest`
- hyp: `disistrusting his own judgment his appeals to the opinion of chingachchguk were frequent and earnest`
- D-fixed: `distrusting his own judgment his appeals to the opinion of chingachchguk were frequent and earnest`
- edits: [(0, 'disistrusting', 'distrusting', 'llm:deepseek')]
- B-fixed: `distrusting his own judgment his appeals to the opinion of chingachgook were frequent and earnest`

### 1320-122612-0005 (en) err A=0.0476 B=0.1429 D=0.0476
- ref: `yet here are we within a short range of the scaroons and not a sign of a trail have we crossed`
- hyp: `yet here are we within a short range of the scoonons and not a sign of a trail have we crossed`
- D-fixed: `yet here are we within a short range of the schooners and not a sign of a trail have we crossed`
- edits: [(10, 'scoonons', 'schooners', 'llm:deepseek')]
- B-fixed: `yet here we are within a short range of the scoonons and not a sign of a trail have we crossed`

## OpenCode usage guard (jev-1.13-free free-ness check)

before:
```
{"usage":{"rolling":{"status":"ok","percent":0,"resetsAt":"2026-10-06T09:59:51.000Z"},"weekly":{"status":"ok","percent":1,"resetsAt":"2026-10-12T00:00:00.000Z"},"monthly":{"status":"ok","percent":74,"resetsAt":"2026-10-13T08:49:05.000Z"}}}
```
after:
```
{"usage":{"rolling":{"status":"ok","percent":0,"resetsAt":"2026-10-06T09:59:51.000Z"},"weekly":{"status":"ok","percent":1,"resetsAt":"2026-10-12T00:00:00.000Z"},"monthly":{"status":"ok","percent":74,"resetsAt":"2026-10-13T08:49:05.000Z"}}}
```