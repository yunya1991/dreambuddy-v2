# learning-episode-writer 集成规范 (Team B — B9)

> **原始 SKILL**: dream-multiskill-v2/skills/0-CORE/learning-episode-writer/SKILL.md
> **集成团队**: Team B — 入场执行
> **触发时机**: A5 执行完成后（无论 ENTER 还是 SKIP，均必须写 episode）

---

## 一、职责

将每次 Team B Screen 3 的决策轮次（入场/跳过/加仓/离场）记录为结构化 episode JSON，替换自由格式 `execution-log.md`，使 Process D 的 D2（learning-lesson-distiller）可以量化统计。

---

## 二、Episode Schema（6-TRADING 版）

```json
{
  "episode_id": "{session_id}-{YYYYMMDDHHMMSS}",
  "trace_id": "{session_id}",
  "ts": "2026-05-26T09:00:00+08:00",
  "inst_id": "BTC-USDT-SWAP",
  "action": "ENTER_SHORT | ADD_SHORT | SKIP | EXIT_TP | EXIT_SL | EXIT_FORCED",
  "direction": "SHORT | LONG | NEUTRAL",
  "martingale_level": 0,
  "scoring": {
    "a7_gate_score": 35,
    "a7_gate_max": 40,
    "composite_confidence": 64,
    "screen1_score": 72
  },
  "gate": {
    "result": "PASS | PASS_WITH_CONDITIONS | SKIP | BLOCK",
    "reason_codes": [],
    "conditions": []
  },
  "execution": {
    "entry_price": null,
    "size_pct_of_capital": null,
    "order_id": null,
    "order_type": "limit | market",
    "stop_loss": null,
    "take_profit_1": null,
    "take_profit_2": null,
    "slippage_bps": null
  },
  "outcome": {
    "exit_price": null,
    "pnl_usdt": null,
    "pnl_pct": null,
    "max_drawdown_pct": null,
    "holding_hours": null,
    "exit_reason": null
  },
  "skip_tracking": {
    "consecutive_skip_count": 0,
    "sleepwalk_alert": false,
    "sleepwalk_force_review": false
  },
  "evidence_refs": [],
  "data_sources": ["tavily", "screen1_v2"],
  "session_path": "6-TRADING/sessions/{session_id}/"
}
```

---

## 三、P006 梦游惰性检测（6-TRADING 实现）

| 条件 | 动作 |
|------|------|
| `consecutive_skip_count >= 7` | 设置 `sleepwalk_alert: true` |
| `sleepwalk_alert: true` | 设置 `sleepwalk_force_review: true` |
| `sleepwalk_force_review: true` | 在记忆文件 `project_trading_session_state.md` 写入 `sleepwalk_alert: true`，触发 Process D 提前复盘 |

---

## 四、文件路径规范

- 写入位置: `sessions/{session_id}/team-b/episode.json`
- 每次 Screen 3 产生一个 episode
- 同一 session 多次执行（如加仓）追加到 `episode_history[]` 数组

---

## 五、与现有 execution-log.md 的关系

- Phase 1: episode.json 与 execution-log.md 并行存在（execution-log 保留人类可读摘要）
- Phase 2: execution-log.md 由 episode.json 自动生成，不再手写

---

*最后更新: 2026-05-26*
