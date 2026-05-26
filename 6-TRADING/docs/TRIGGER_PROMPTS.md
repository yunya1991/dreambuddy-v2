# 6-TRADING 触发提示词规范 v1.2

> **版本**: v1.2 | **更新日期**: 2026-05-26
> **维护说明**: 本文档是 6-TRADING 4 个 CronCreate 定时任务的**权威提示词来源**。
> **多 Claude Code 协作**: 每次修改触发提示词后，必须同步更新本文档，确保所有 Claude Code 实例使用相同版本。
> **同步关系**: 本文档 → Claude Code 本地 `memory/reference_trading_cron_jobs.md`（单向从此同步）

---

## 一、CronCreate 任务注册表

| 任务 | Cron 表达式 | 说明 | Job ID | 状态 |
|------|------------|------|--------|------|
| Screen 1 周线分析 | `0 20 * * 0` | 每周日 20:00 | `b9ce16da` | ✅ 运行中 |
| Screen 2 日线预设 | `30 7 * * 1-5` | 每工作日 07:30 | `cd7edd91` | ✅ 运行中 |
| Team B 状态检查 | `0 9 * * 1-5` | 每工作日 09:00 | `a30b1027` | ✅ 运行中 |
| Process D 复盘 | `0 6 * * 1` | 每周一 06:00 | `21514de4` | ✅ 运行中 |

---

## 二、Screen 1 触发提示词（每周日 20:00）

```
运行 6-TRADING Team A Screen 1 周线分析：

[Phase-0 强制数据采集 — P0.1-P0.6 HARD BLOCK，P0.4b/P0.9 非阻塞]
P0.1: Tavily搜索 "Bitcoin BTC price USD {YYYY-MM-DD} current" → 提取当前价格
P0.2: Tavily搜索 "Bitcoin perpetual futures funding rate {YYYY-MM-DD} OKX Binance" → 提取资金费率方向
P0.3: Tavily搜索 "Bitcoin spot ETF net inflow outflow {YYYY-MM-DD}" → 提取资金流向（亿USD）
P0.4: Tavily搜索 "Bitcoin macro risk factors {YYYY-MM-DD} Fed geopolitical" → 提取宏观驱动
P0.4b: [dream-archive-center] Tavily搜索 "Bitcoin {macro_keyword} historical price action 2020 2022 2024"
       → 提取 2-3 个历史类比情景（similarity_score/btc_outcome/key_difference）
       → 非 HARD BLOCK：失败则 archive_data:"unavailable"，继续执行
P0.5: Tavily搜索 "Bitcoin support resistance technical analysis {YYYY-MM-DD}" → 提取关键价格位
P0.6: Tavily搜索 "Bitcoin fear greed index {YYYY-MM-DD}" → 提取市场情绪
P0.7: 价格可信度验证 — 若搜索价格与上次记录基价偏差 > 20%，输出 DATA_ALERT 并停止执行
P0.9: [dream-knowledge K1 检索] 查询 knowledge/strategy_scores/ 中最近 5 个 BTC 同向策略：
       → 提取平均胜率、平均 RR、最常见失败原因
       → 如胜率 < 30% 且记录 ≥3，当前 screen1_score 折扣 × 0.85
       → 将检索结果注入 data_context 的 knowledge_context 字段
       → 非 HARD BLOCK：K1 无记录时继续执行
P0.8: 合并以上数据为 data_context（含 historical_analogues + knowledge_context），所有后续 Agent 必须以此作为分析基础
⛔ 若 P0.1-P0.6 任意步骤失败（Tavily 无结果），输出 SCREEN1_BLOCKED，等待人工干预

[Phase-1 分析执行]
1. 读取 memory 中当前会话状态
2. 创建 sessions/{YYYYMMDD}-BTC-SCREEN1/ 文件夹结构
3. 并行启动 3 个子 Agent，将 Phase-0 data_context 注入提示词：
   - A1（矛盾分析）: 执行调研 + [IA-A1] 在输出前检查：锚定偏见/可得性启发/代表性启发
     → 如发现偏见，在 a1-contradiction.md 末尾追加 [BIAS_FLAG: {类型}]
   - A2（第一性原理）: 执行分析 + [IA-A2] 在输出前检查：确认偏见/过度自信/镜像思维
     → 如发现偏见，在 a2-first-principles.md 末尾追加 [BIAS_FLAG: {类型}]
   - A3（沙盘推演）: 执行 S1/S2/S3 情景 + [IA-A3 红队分析]：
     → 构建反论：支持反向的3个最强理由 + 证伪条件 + 最脆弱假设
     → 若红队论据强度 > 主方向40%，在 strategy-type.json 设置 red_team_flag:true
     → 将红队分析写入 a3-simulation.md 末尾的 [RED_TEAM_ANALYSIS] 段落
     → A3 同时输出 phase7_contingency（黑天鹅/极端情景应对方案）写入 strategy-type.json
4. A3 完成后，触发 [master-seminar] 大师阵营辩论：
   - 标准模式：4 位大师（趋势/基本面/均值回归/宏观风险）分多空辩论
   - 强化模式（red_team_flag=true 或 screen1_score<60）：追加黑天鹅/量化大师
   - 输出 master-debate.json（含 screen1_score_adjustment）
   - 按调整规则修正 screen1_score：一致+5/分歧-5/对立-15(MASTER_DEBATE_WARNING)
5. 综合输出 strategy-type.json（含 red_team_flag/phase7_contingency/adjusted score）+ weekly-direction.md
6. C4 产物归档（artifact-alignment-manager）：
   - strategy-type.json / weekly-direction.md / master-debate.json
   - raw/a1-contradiction.md / a2-first-principles.md / a3-simulation.md
7. 更新记忆中的 screen1_direction 状态（含 btc_price_basis/data_source/adjusted screen1_score/master_debate_result）
```

---

## 三、Screen 2 触发提示词（每工作日 07:30）

```
运行 6-TRADING Team A Screen 2 日线预设：

[Phase-0 数据采集与漂移检查]
P0.1: Tavily搜索获取当前 BTC 价格
P0.2: 与记忆中 screen1_btc_price_basis 比对
  - 偏差 > 10%：自动触发 Screen1 重跑，当前 Screen2 暂停
  - 偏差 5-10%：继续执行，在输出中标注 PRICE_DRIFT_WARNING
  - 偏差 < 5%：正常执行
P0.3: 验证 Screen1 有效期（valid_until 字段），已过期则先触发 Screen1

[Phase-1 日线分析]
1. 创建 sessions/{YYYYMMDD}-BTC-SCREEN2/ 文件夹
2. 并行执行 A1(日线矛盾)/A2(日线第一性原理)/A3(日线沙盘)，注入 Phase-0 数据
3. 计算马丁阶梯（3情景：S1基准/S2Squeeze/S3反转），生成初始 daily-presets.json

[Phase-2 回测验证与参数优化]（非 HARD BLOCK，失败则降级输出 Phase-1 结果）
4. [dream-data-analysis 趋势上下文] 读取 review/data-analysis-report.json（如存在）：
   - 提取 trend.direction / resistance.resistance_score / trend.trend_confidence
   - trend_confidence < 0.4 → 跳过 Phase-2，标注 phase2_skipped:true，直接输出 Phase-1 结果
5. [dream-backtest A8s] 回测验证 martingale 参数可行性：
   - 输入: Phase-1 初始 daily-presets + trend_context（来自 DA）
   - 输出: backtest_result（胜率/最大回撤/平均 RR）
   - 若回测失败（数据不足/收敛失败）→ phase2_skipped:true，输出 Phase-1 结果
6. [dream-bayesian-opt A9s] 贝叶斯优化马丁格参数：
   - 输入: backtest_result + Phase-1 参数范围
   - 优化目标: maximize RR，约束 max_drawdown < 15%
   - 输出: optimized_params（TP/SL/间距/仓位比例调整建议）

[Phase-3 合并输出]
7. 合并 Phase-1 分析 + Phase-2 优化（或降级结果），输出：
   - daily-presets.json（含 phase2_skipped 标志）
   - martingale-grid.json
   - order-plan.md
8. C4 产物归档
9. 更新记忆中的 screen2_presets 状态
```

---

## 四、Team B Screen 3 触发提示词（每工作日 09:00）

```
运行 6-TRADING Team B Screen 3 状态检查：
1. 读取 memory 中当前仓位状态（project_trading_session_state.md）
2. 如 status=no_position 且 Screen2 presets 存在 → 执行入场流程：
   Step0: dream-strategy-parser (Regime路由) → 输出 directive_bias
   → dream-signal-scoring-spec (8维评分) + dream-risk-position-sizing + dream-execution-cost-model [并行]
     ⚠️ 三者必须全部完成才能继续，任意一个失败 → PARALLEL_INPUT_INCOMPLETE → 写 SKIP episode 终止
   → A7-practice-theory (实践门禁)
   → dream-pretrade-gatekeeper (Gate C)：
     [IA-GC ACH验证] 在最终裁决前执行竞争性假设分析：
       读取 sessions/{最新Screen1_id}/team-a/screen1/strategy-type.json 的 red_team_flag
       假设A（入场有效）vs 假设B（虚假信号）的诊断证据：
         ① 资金费率方向是否与入场方向一致？（诊断性高）
         ② Screen1 btc_price_basis 偏差是否 <5%？（诊断性高）
         ③ A7 gate score 是否 >30/40？（诊断性中）
       若 red_team_flag=true：
         → 自动将 Gate C 信心阈值从 composite_confidence>60 提高到 >70
       若假设B诊断证据数量 ≥ 假设A → Gate C 降级为 SKIP
       → 将 ACH 摘要写入 gate-c/pretrade-check.json 的 ach_summary 字段
         （含 red_team_flag_applied / threshold_used / ach_result）
   → dream-tactical-validator (A4)
   → dream-tactical-executor (A5)：
     读取 sessions/{最新Screen1_session}/team-a/screen1/strategy-type.json
     提取 phase7_contingency 字段（黑天鹅/极端情景应对方案）作为执行约束
     → 若 phase7_contingency 不存在，继续执行（降级为无应急预案模式）
   → learning-episode-writer (B9): 无论 ENTER/SKIP 均写 episode.json
     读取 team-b/a7-gate.json 获取 a7_gate_score（优先读文件，失败则 null）
     扫描 sessions/*/team-b/episode.json 计算 consecutive_skip_count（最近20条，遇非SKIP停止）
   → artifact-alignment-manager (C4): 产物归档
     归档: a7-gate.json / gate-c/pretrade-check.json / team-b/episode.json / execution-log.md
3. 如 status=holding → dream-intelligence-monitor (A6) 监控 + dream-exit-skill-v2 (A9) 止盈止损检查
   A9 离场后 → artifact-alignment-manager (C4) 归档离场相关产物
4. 连续 SKIP ≥7 次 → sleepwalk_alert=true → 写入记忆文件，触发提前 Process D
```

---

## 五、Process D 触发提示词（每周一 06:00）

```
运行 6-TRADING Process D 复盘（三级学习闭环 v1.2）：

Step 0 [OE + A8 并行]:
  A) [dream-oneirology] 与 A8 并行运行（无 Gate 权力，纯顾问）：
     - 输入: sessions/*/team-b/episode.json (last 7 days)
     - 检测四大模块: 强迫性重复 / 维度凝缩 / 被压制判断 / 叙事二次修正
     - 触发阈值: consecutive_skip >= 3 → 强迫重复告警（早于 P006 的 7 次）
     - 输出: review/oneirology-report.json（dream_summary + 各模块分析）
  B) [A8-theory-practice-verification] 知行合一批评：
     - 读取上周所有 sessions/*/review/ 和 sessions/*/team-b/episode.json
     - [IA-PD] 偏见审计：确认偏见/群体思维/过度自信三项检查
     - 参考 oneirology-report.json 的 compulsive_skip_analysis 补充 bias_audit
     - 输出: review/a8-reflection.json（含 retrospective_score, key_findings, bias_audit）

Step 1.5 [DA 量化分析]:
  [dream-data-analysis] episodes 时序统计：
  - 输入: sessions/*/team-b/episode.json (last_20_episodes, last_4_weeks)
  - 计算: composite_confidence MA/EMA趋势 / skip率 / 梦游风险等级
  - 输出: review/data-analysis-report.json
    → trend.direction + resistance.resistance_score + calibration_suggestions
    → sleepwalk_risk: "low|medium|high"（与 OE 模块1交叉验证）

Step 2 [知识库写入]:
  调用 dream-knowledge (K1)：
  - 将本周 Screen1 结论写入 knowledge/strategy_scores/{session_id}.json
  - 如有 A9 离场结果，更新对应策略的胜率/RR字段
  - 识别新的市场状态模式，写入 knowledge/regime_patterns/

Step 3 [规律提炼]:
  调用 learning-lesson-distiller (D2)：
  - 输入: sessions/*/team-b/episode.json (last_20_episodes)
         + review/data-analysis-report.json（量化证据，calibration_suggestions 作为 lesson 依据）
         + review/oneirology-report.json（顾问视角，condensation_flags 辅助发现被压制规律）
  - 参数: min_frequency=3, min_severity=2, cooldown=10
  - 输出: review/weekly-lessons.json (lessons_delta: added/updated/deprecated)

Step 4 [改进提案]:
  调用 learning-proposal-generator (D3)：
  - 输入: review/weekly-lessons.json + data-analysis-report 的 calibration_suggestions
  - 提案类型: trigger_prompt_patch / martingale_param_update / gate_threshold_update
  - 强制字段: rollback_plan_id + evidence_refs[]
  - 输出: review/weekly-proposals.json（status=pending_review）

Step 3.5 [大师动态进化]（D1 A8 完成后执行）:
  [master-seminar 进化] 根据上周 PnL vs Screen1 预判方向：
  - 正确预判大师: knowledge/master_profiles/{id}.json confidence_weight +0.1
  - 错误预判大师: knowledge/master_profiles/{id}.json confidence_weight -0.05

Step 5 [产物归档]:
  调用 artifact-alignment-manager (C4)：
  - 归档: a8-reflection.json / oneirology-report.json / data-analysis-report.json
           weekly-lessons.json / weekly-proposals.json
  - frontmatter: chain_phase=A8, type=retrospective/lesson_delta/proposal, dept=process-d

Step 6 [记忆更新]:
  更新 project_trading_session_state.md：
  - last_process_d: 当日日期
  - last_retrospective_score: A8 得分
  - pending_proposals: proposals 数量
  - sleepwalk_alert: 重置为 false（如之前为 true）

⚠️ H009 宪法约束: weekly-proposals.json 中的提案禁止自动部署，须人工审核后修改触发提示词
⚠️ OE 约束: oneirology-report.json 所有结论标注为 advisory，不得直接影响 Screen 执行
```

---

## 六、版本历史

| 版本 | 日期 | 变更摘要 |
|------|------|---------|
| v1.0 | 2026-05 | 初始版本：Screen1/2/3 + Process D 基础结构 |
| v1.1 | 2026-05 | G1-G6 缺口修复：dream-backtest/bayesian-opt / B3/B4/B5 并行合约 / phase7_contingency |
| v1.2 | 2026-05-26 | 集成 5 个 2-INTELLIGENCE SKILL：IA 偏见注入 / ACH矩阵 / master-seminar / dream-archive-center P0.4b / OE dream-oneirology / DA quantitative |

---

## 七、多 Claude Code 协作同步规则

1. **此文档为权威来源** — 所有 Claude Code 实例的触发提示词必须与本文档一致
2. **修改流程**:
   - Process D D3 输出 `trigger_prompt_patch` 类型提案 → 人工审核
   - 审核通过后，先更新本文档（TRIGGER_PROMPTS.md），再更新各 Claude Code 本地 memory
3. **同步检查**: 每次 Screen 1 前，Claude Code 应比对本文档与本地 `reference_trading_cron_jobs.md` 版本号是否一致
4. **禁止规则**: 任何 Claude Code 实例不得在未更新本文档的情况下，单方面修改本地 memory 中的触发提示词

---

*维护者: 6-TRADING Claude Code 协作系统 | 关联文档: [SKILL_REGISTRY.md](SKILL_REGISTRY.md) | [CLAUDE_CODE_COLLAB_PLAN.md](CLAUDE_CODE_COLLAB_PLAN.md)*
