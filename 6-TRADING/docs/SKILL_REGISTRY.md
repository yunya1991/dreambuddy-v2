# 6-TRADING SKILL Registry v1.1

> **版本**: v1.1 | **更新日期**: 2026-05-26
> **管理原则**: 所有执行均须符合治理基础层（dream-constitution v2.9）约束。
> **来源说明**: 1-TRADE / 0-CORE = dream-multiskill-v2 | 6-TRADING = 本仓库
> **v1.1 变更**: G1-G6 缺口修复 — 新增 dream-backtest/bayesian-opt (G1)；B3/B4/B5 并行合约 (G2)；phase7_contingency 生产合约 (G3)；Screen1 触发时间 Sunday 20:00 确认 (G6)

---

## 一、架构总览（Mermaid）

```mermaid
graph TD
    subgraph GOV["Governance 治理层"]
        G1[dream-constitution v2.9]
    end
    subgraph TA["Team A — 研究预设"]
        A1[Screen 1: dream-screen1-first]
        A2[Screen 2: dream-screen2-second]
        A3[A0: dream-contradiction-theory]
        A4[A1: dream-strategy-research]
        A5[A2: dream-first-principles]
        A6[A3: dream-strategy-designer]
        A7[dream-regime-detector]
        A8s["Phase-2: dream-backtest"]
        A9s["Phase-2: dream-bayesian-opt"]
    end
    subgraph TB["Team B — 入场执行"]
        B1[Screen 3: dream-screen3-third]
        B2[dream-strategy-parser]
        B3[dream-signal-scoring-spec]
        B4[dream-risk-position-sizing]
        B5[dream-execution-cost-model]
        AGG{{"AGGREGATE gate_inputs"}}
        B6["Gate C: dream-pretrade-gatekeeper"]
        B7[A4: dream-tactical-validator]
        B8[A5: dream-tactical-executor]
        B9["NEW: learning-episode-writer"]
    end
    subgraph TC["Team C — 日内监控离场"]
        C1[A6: dream-intelligence-monitor]
        C2[A7: A7-practice-theory]
        C3[A9: dream-exit-skill-v2]
        C4["NEW: artifact-alignment-manager"]
    end
    subgraph PD["Process D — 交易复盘"]
        D1[A8: A8-theory-practice-verification]
        D2["NEW: learning-lesson-distiller"]
        D3["NEW: learning-proposal-generator"]
    end
    subgraph KB["Knowledge Base — 策略知识库"]
        K1["NEW: dream-knowledge v1.1"]
    end

    G1 -.->|宪法约束| TA
    G1 -.->|宪法约束| TB
    G1 -.->|宪法约束| TC
    G1 -.->|宪法约束| PD

    A1 -->|Screen1方向| A2
    A2 -->|日线预设| B1
    A3 & A4 & A5 & A6 -.->|内嵌| A1
    A3 & A4 & A5 -.->|内嵌| A2
    A7 -.->|Regime触发| A1
    A2 -->|Phase-2触发| A8s
    A8s --> A9s

    B1 --> B2
    B2 -->|Step0 directive_bias| B3 & B4 & B5
    B3 & B4 & B5 --> AGG
    AGG -->|scores+position+cost| B6
    B6 --> C2 --> B7 --> B8
    A6 -.->|phase7_contingency| B8
    B8 --> B9
    B8 -->|持仓期间| C1
    C1 -->|P0告警| C3
    C3 --> C4
    B1 & A1 & A2 --> C4

    B8 -->|A9后| D1
    D1 --> K1 --> D2 --> D3
    D3 -->|提案审核| A1
    K1 -.->|Phase-0检索| A1
    K1 -.->|Phase-0检索| A2
```

---

## 二、5 大团队 SKILL 注册表

### Governance — 治理基础层

| ID | SKILL | 来源 | 版本 | 核心功能 |
|----|-------|------|------|---------|
| G1 | dream-constitution | 0-CORE | v2.9 | 所有决策宪法约束；Chapter2/4/14 映射交易链 |

所有触发提示词须前置引用；Chapter 14 H001-H009 为 Gate C 硬门禁基础。
集成规范: [CONSTITUTION_COMPLIANCE.md](CONSTITUTION_COMPLIANCE.md)

---

### Team A — 研究预设（9个）

**职责**: Screen 1 周线方向 + Screen 2 日线马丁格预设。**纯研究，不执行订单。**
**Phase-0 强制**: Tavily 6 查询 + knowledge 检索，数据不到位则 HARD BLOCK。
**Screen 2 执行顺序**: Phase-1（A1→A2→A3 分析）→ Phase-2（dream-backtest 验证 → dream-bayesian-opt 优化）→ Phase-3（输出 daily-presets + martingale-grid）。

| ID | SKILL | 来源 | 阶段 | 核心功能 | 触发时机 |
|----|-------|------|------|---------|---------|
| A1 | dream-screen1-first | 6-TRADING | Screen 1 | 并行编排 A0+A1+A2+A3，输出周线方向+策略类型 | 每周日 20:00 |
| A2 | dream-screen2-second | 6-TRADING | Screen 2 | A1→A2→马丁格计算→Phase-2验证→输出日线预设 | 每工作日 07:30 |
| A3 | dream-contradiction-theory | 1-TRADE | A0 | 矛盾论 OS（C1-C8 矛盾发现，4维评分定主矛盾） | 嵌入 A1/A2/A3 内 |
| A4 | dream-strategy-research | 1-TRADE | A1 | 深度调研（五角形准则 + Tavily Phase-0） | Screen 1/2 A1 步骤 |
| A5 | dream-first-principles | 1-TRADE | A2 | 第一性原理（L1/L2/L3 资金流 + 趋势阶段） | Screen 1/2 A2 步骤 |
| A6 | dream-strategy-designer | 1-TRADE | A3 | 多情景战略合成（S1/S2/S3 概率+工具）；**输出 phase7_contingency 供 B8 读取** | Screen 1 A3 步骤 |
| A7 | dream-regime-detector | 1-TRADE | 支持 | 市场状态 7 分类，Master Fit 下降触发蒸馏 | Phase-0 + A6 联动 |
| **A8s** | **dream-backtest** | **1-TRADE** | **Screen 2 Phase-2** | **历史回测验证 martingale 参数可行性；输出 backtest_result（胜率/RR/最大回撤）** | **Screen 2 Phase-2，A1→A2→A3 完成后** |
| **A9s** | **dream-bayesian-opt** | **1-TRADE** | **Screen 2 Phase-2** | **贝叶斯优化马丁格参数（TP/SL/间距/仓位比例）；依赖 A8s backtest_result** | **Screen 2 Phase-2，dream-backtest 完成后** |

> **[G1 Fix]** `dream-backtest` 和 `dream-bayesian-opt` 是 Screen 2 Phase-2 的必须步骤。若任一步骤失败（回测数据不足/优化未收敛），Screen 2 降级为 Phase-1 输出（跳过 Phase-2，在 daily-presets.json 中标注 `phase2_skipped: true`）。

---

### Team B — 入场执行（9个）

**职责**: 读取 Screen 2 预设，执行完整入场链。Gate C BLOCK 不可绕过。
**硬约束**: A5 后无论 ENTER/SKIP 均必须调用 B9 写 episode。

**[G2 Fix] 并行合约**: B3/B4/B5 必须**并行执行**，各自独立完成后聚合结果供 B6。Gate C (B6) 的入参要求：
- `scores_result`（来自 B3）
- `position_result`（来自 B4）
- `execution_cost_result`（来自 B5）

三个结果必须同时就绪才可触发 B6。任意一个失败则 Screen 3 输出 `PARALLEL_INPUT_INCOMPLETE`，本轮终止，写 SKIP episode。

**[G3 Fix] phase7_contingency 合约**: A3（dream-strategy-designer）在 Screen 1 A3 步骤输出 S1/S2/S3 情景时，同时输出 `phase7_contingency`（黑天鹅/极端情景应对方案）。该字段写入 `sessions/{id}/team-a/screen1/strategy-type.json`，B8（dream-tactical-executor）在执行前必须读取此文件获取 contingency 指令。

| ID | SKILL | 来源 | 阶段 | 核心功能 | 触发时机 |
|----|-------|------|------|---------|---------|
| B1 | dream-screen3-third | 6-TRADING | Screen 3 | 编排器：Screen 2 presets → 完整执行链 | 每工作日 09:00 |
| B2 | dream-strategy-parser | 1-TRADE | Pre-A4 | Regime→策略路由，输出 directive_bias | Step 0 |
| B3 | dream-signal-scoring-spec | 1-TRADE | 评分 [并行] | 8 维评分；输出 scores_result（含 composite_confidence） | B2 后，与 B4/B5 并行 |
| B4 | dream-risk-position-sizing | 1-TRADE | 风控 [并行] | 风险预算仓位，ATR 止损；输出 position_result | B2 后，与 B3/B5 并行 |
| B5 | dream-execution-cost-model | 1-TRADE | 费用 [并行] | 费率+滑点估算；输出 execution_cost_result | B2 后，与 B3/B4 并行 |
| B6 | dream-pretrade-gatekeeper | 1-TRADE | Gate C | H001-H009；入参：scores+position+cost 三合一；裁决 PASS/SKIP | B3+B4+B5 全部完成后 |
| B7 | dream-tactical-validator | 1-TRADE | A4 | Demo 账户 3 层索引验证 | A4 步骤 |
| B8 | dream-tactical-executor | 1-TRADE | A5 | 读 phase7_contingency；实盘执行（A7 门禁 + RM 顾问否决） | A5 步骤 |
| **B9** | **learning-episode-writer** | **0-CORE** | **执行记录** | **结构化 episode，P006 梦游检测（SKIP≥7 告警）** | **A5 完成后** |

集成规范: [skills/0-core-integration/episode-writer/INTEGRATION.md](../skills/0-core-integration/episode-writer/INTEGRATION.md)

---

### Team C — 日内监控离场（4个）

**职责**: 持仓期间高频监控、实践门禁、离场决策、产物标准化归档。
**说明**: 「持仓存活层」，不负责建仓，负责守仓和离场。

| ID | SKILL | 来源 | 阶段 | 核心功能 | 触发时机 |
|----|-------|------|------|---------|---------|
| C1 | dream-intelligence-monitor | 1-TRADE | A6 | 每小时监控，P0/P1 告警，触发 A1→A3 重启 | 持仓每小时 |
| C2 | A7-practice-theory | 1-TRADE | A7 | 5 项实践门禁（INDEPENDENT_AUTO，读近 4h episode） | A4/A5 前 |
| C3 | dream-exit-skill-v2 | 1-TRADE | A9 | 4 层离场链（TP/SL / 风险事件 / A6 联动 / 强制审计） | A6 告警 + 定时 |
| **C4** | **artifact-alignment-manager** | **0-CORE** | **产物** | **A-series 产物标准化投递，双渠道归档** | **各 Screen 完成后 + A9 后** |

集成规范: [skills/0-core-integration/artifact-alignment/INTEGRATION.md](../skills/0-core-integration/artifact-alignment/INTEGRATION.md)

---

### Process D — 交易复盘（3个）

**职责**: 每周复盘，A8 批评，串联三级学习闭环（knowledge→distill→propose）。

| ID | SKILL | 来源 | 阶段 | 核心功能 | 触发时机 |
|----|-------|------|------|---------|---------|
| D1 | A8-theory-practice-verification | 1-TRADE | A8 | 知行合一批评，纸上谈兵检测，7 步采纳周期 | 每周一 06:00 Step1 |
| **D2** | **learning-lesson-distiller** | **0-CORE** | **规律提炼** | **episodes→lessons（min_freq=3，防噪声过拟合）** | **A8 后 Step3** |
| **D3** | **learning-proposal-generator** | **0-CORE** | **改进提案** | **lessons→proposals（rollback_plan + evidence_refs）** | **D2 后 Step4** |

集成规范: [skills/0-core-integration/lesson-distiller/](../skills/0-core-integration/lesson-distiller/INTEGRATION.md) | [proposal-generator/](../skills/0-core-integration/proposal-generator/INTEGRATION.md)

---

### Knowledge Base — 策略知识库（1个）

**职责**: 沉淀历史策略经验，为 Screen 1/2 Phase-0 提供可检索知识支撑。

| ID | SKILL | 来源 | 版本 | 核心功能 | 存储路径 |
|----|-------|------|------|---------|---------|
| **K1** | **dream-knowledge** | **0-CORE** | **v1.1** | **策略知识库（regime/classic/master），100 分评分体系** | **[knowledge/](../knowledge/)** |

集成规范: [skills/0-core-integration/knowledge/INTEGRATION.md](../skills/0-core-integration/knowledge/INTEGRATION.md)

---

## 三、完整执行时序

```
每周日 20:00   Team A Screen 1        [G6: 权威触发时间，以 CronCreate job b9ce16da 为准]
  Phase-0: Tavily 6查询 + knowledge检索
  -> A0矛盾论 + A1调研 + A2第一性原理 + A3战略 [并行]
    A3输出 phase7_contingency → 写入 strategy-type.json
  -> C4 产物归档 -> 更新记忆

每工作日 07:30 Team A Screen 2
  Phase-0: 价格漂移检查 + Tavily日线
  Phase-1: A1→A2→马丁格计算 [顺序]
  Phase-2: dream-backtest → dream-bayesian-opt [顺序]   [G1: 新增]
    失败则降级：phase2_skipped=true，输出Phase-1结果
  Phase-3: 合并输出 daily-presets.json + martingale-grid.json
  -> C4 产物归档 -> 更新记忆

每工作日 09:00 Team B Screen 3
  Step0: B2 Regime路由 → directive_bias
  -> B3评分 + B4仓位 + B5成本 [并行，三者全部完成才继续]   [G2: 并行合约]
  -> AGGREGATE(scores+position+cost)
  -> C2 A7门禁 -> B6 Gate C
  -> B7 A4验证 -> B8 A5执行（读取 phase7_contingency）   [G3: contingency合约]
  -> B9 episode-writer [ENTER/SKIP 均写]
  -> C4 产物归档

持仓期间每小时 Team C
  C1 A6监控 -> P0告警 -> C3 A9离场 -> C4产物归档

每周一 06:00   Process D 复盘
  D1 A8批评 -> K1知识库写入 -> D2提炼lessons -> D3生成proposals
  -> 输出 a8-reflection + weekly-lessons + weekly-proposals -> 更新记忆
```

---

## 四、数据流合约摘要（跨团队接口）

| 接口 | 生产者 | 消费者 | 文件路径 | 备注 |
|------|-------|-------|---------|------|
| screen1_direction | A1 (Screen1) | A2 (Screen2), B1 (Screen3), B6 (Gate C H001) | memory/project_trading_session_state.md | H001/H002/H003 强制检查 |
| daily-presets | A2 (Screen2) | B1 (Screen3) | sessions/{id}/team-a/screen2/daily-presets.json | Screen3 入口依赖 |
| phase7_contingency | A6 (dream-strategy-designer) | B8 (dream-tactical-executor) | sessions/{id}/team-a/screen1/strategy-type.json | B8 执行前必读 [G3] |
| scores_result | B3 (signal-scoring) | B6 (Gate C) | 内存传递 (Screen3 session) | 必须与 B4/B5 并行完成 [G2] |
| position_result | B4 (position-sizing) | B6 (Gate C) | 内存传递 (Screen3 session) | 必须与 B3/B5 并行完成 [G2] |
| execution_cost_result | B5 (cost-model) | B6 (Gate C) | 内存传递 (Screen3 session) | 必须与 B3/B4 并行完成 [G2] |
| a7_gate_result | B8 内部调用A7 | B9 (episode-writer) | sessions/{id}/team-b/a7-gate.json | B9直接读文件 [G4] |
| consecutive_skip_count | B9 历史Episodes | B9 (episode-writer) | sessions/*/team-b/episode.json | B9读最近20 episodes [G5] |
| episode.json | B9 (episode-writer) | D2 (lesson-distiller) | sessions/{id}/team-b/episode.json | Process D 闭环基础 |
| weekly-lessons | D2 (lesson-distiller) | D3 (proposal-generator) | sessions/{id}/review/weekly-lessons.json | min_freq=3 过滤 |
| weekly-proposals | D3 (proposal-generator) | 人工审核 | sessions/{id}/review/weekly-proposals.json | H009: 不得自动部署 |

---

## 五、新增 SKILL 集成索引

| SKILL | 团队 | INTEGRATION.md |
|-------|------|----------------|
| dream-constitution | Governance | [CONSTITUTION_COMPLIANCE.md](CONSTITUTION_COMPLIANCE.md) |
| dream-backtest | Team A (A8s) | dream-multiskill-v2/skills/1-TRADE/dream-backtest |
| dream-bayesian-opt | Team A (A9s) | dream-multiskill-v2/skills/1-TRADE/dream-bayesian-opt |
| artifact-alignment-manager | Team C (C4) | [skills/0-core-integration/artifact-alignment/](../skills/0-core-integration/artifact-alignment/INTEGRATION.md) |
| learning-episode-writer | Team B (B9) | [skills/0-core-integration/episode-writer/](../skills/0-core-integration/episode-writer/INTEGRATION.md) |
| dream-knowledge | Knowledge Base (K1) | [skills/0-core-integration/knowledge/](../skills/0-core-integration/knowledge/INTEGRATION.md) |
| learning-lesson-distiller | Process D (D2) | [skills/0-core-integration/lesson-distiller/](../skills/0-core-integration/lesson-distiller/INTEGRATION.md) |
| learning-proposal-generator | Process D (D3) | [skills/0-core-integration/proposal-generator/](../skills/0-core-integration/proposal-generator/INTEGRATION.md) |

---

*最后更新: 2026-05-26 v1.1 | 修复缺口 G1/G2/G3/G6 | 维护者: 6-TRADING Claude Code 协作系统*
