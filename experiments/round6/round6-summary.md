# Round 6：换 ASR 底座

| 引擎（均为硅基流动） | 脏句基础错误率(zh/en) | 时间戳 | 说话人 |
|---|---|---|---|
| sensevoice | zh 0.0779 / en 0.0693 | ❌ | ❌ |
| qwen3asr | zh 0.0251 / en 0.0095 | ❌ | ❌ |
| xingchen-v32 | zh 0.0383 / en 0.0067 | ❌ | ❌ |
| xingchen-ultra | zh 0.0501 / en 0.0067 | ❌ | ❌ |
| xingchen-diarize | zh 0.1912 / en 0.0627 | ✅ | ✅ |

## 底座×纠错（前两名过冠军管线）

- **qwen3asr**: 0.0173 → 0.014
- **xingchen-v32**: 0.0225 → 0.0267

参考：SenseVoice 底座 + 冠军管线的 R5 终值 = 0.0331。