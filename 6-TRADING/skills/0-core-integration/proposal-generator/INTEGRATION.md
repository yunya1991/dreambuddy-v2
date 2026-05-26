# learning-proposal-generator 集成规范 (Process D — D3)

> **原始 SKILL**: dream-multiskill-v2/skills/0-CORE/learning-proposal-generator/SKILL.md
> **集成团队**: Process D — 交易复盘（三级学习闭环第 3 步，也是最后一步）
> **触发时机**: learning-lesson-distiller (D2) 完成后，Process D Step 4

---

## 一、职责

将 D2 输出的 `lessons_delta` 转化为可治理的系统改进提案。每个提案必须包含 `rollback_plan_id`（如何撤销）和 `evidence_refs`（指向具体 episode）。提案本身不自动执行，需人工审核。

---

## 二、提案类型（6-TRADING 版）

| type | 修改目标 | 示例 |
|------|---------|------|
| `trigger_prompt_patch` | Screen 1/2/3 CronCreate 触发提示词 | 新增 Phase-0 步骤 |
| `martingale_param_update` | Screen 2 马丁格参数（间距/仓位比例/止损距离） | 将 L0 仓位从 30% 降至 20%（资金费率风险）|
| `gate_threshold_update` | A7/Gate C 评分阈值 | 资金费率 < -5% 时 composite_confidence 折扣系数 0.8 |
| `knowledge_score_adjust` | 知识库策略评分参数 | 更新 futures_martingale SHORT 的历史胜率 |

---

## 三、Proposal Schema

```json
{
  "proposal_id": "PROP-20260526-001",
  "type": "trigger_prompt_patch",
  "title": "Screen 2 Phase-0 新增资金费率风险折扣逻辑",
  "target_file": "memory/reference_trading_cron_jobs.md",
  "patch_content": "在 Screen 2 Phase-0 P0.3 后新增: 若资金费率 < -5%，自动在 data_context 中注入 squeeze_risk_high=true，Screen 2 A1/A2/A3 须明确评估 Short Squeeze 概率",
  "reason": "F_SHORT_SQUEEZE_UNDERWEIGHTED: 3 次因资金费率极值导致空头亏损",
  "reason_codes": ["F_SHORT_SQUEEZE_UNDERWEIGHTED"],
  "rollback_plan_id": "ROLLBACK-20260526-001",
  "rollback_plan": "删除 squeeze_risk_high 注入步骤，恢复原 Phase-0 流程",
  "evidence_refs": ["20260526-BTC-SCREEN2-v2-episode-001"],
  "require_shadow_verification": true,
  "shadow_period_days": 7,
  "status": "pending_review",
  "created_at": "2026-05-26T06:30:00+08:00",
  "approved_by": null,
  "applied_at": null
}
```

---

## 四、审核流程

```
D3 生成 proposal → 写入 review/weekly-proposals.json
  → 用户人工审核（标注 approved/rejected）
    → approved → 人工修改对应文件（trigger_prompt / 参数文件）
      → shadow 验证期（7-14天，仅模拟，不实盘）
        → 效果评估（A8 score 变化 / RR 变化）
          → 正式采纳 OR 回滚
```

**宪法 H009 约束**: proposals 未经人工审核，不得自动部署到 Screen 1/2/3 触发提示词。

---

## 五、输出文件

写入 `sessions/{latest_session}/review/weekly-proposals.json`:

```json
{
  "generated_at": "2026-05-26T06:30:00+08:00",
  "source_lessons": "review/weekly-lessons.json",
  "proposals": [ ... ]
}
```

---

*最后更新: 2026-05-26*
