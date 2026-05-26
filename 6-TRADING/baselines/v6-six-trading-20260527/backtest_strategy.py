#!/usr/bin/env python3
"""
回测策略实现模块 v8.0
======================
忠实实现 TRADING_WORKFLOW_SPEC_v1.md 设计规范

v9.0 — Level3加满后启用均价止损 (防整链亏损):
  1. is_martin_complete 时设置 stop_loss_price = avg_entry×0.80 (LONG) / ×1.20 (SHORT)
  2. check_exit_signals L1-SL 仅在 is_martin_complete 且 stop_loss_price>0 时触发
  3. 未加满前无固定SL, 仍靠信号反转/回撤出场

v8.0 — 用户马丁经验规则 (个人实战优化):
  1. 加仓间隔: 每跌 addon_gap_pct%×vol_mult 加一次仓 (复利计算, BTC=8%, SOL/ETH按波动率放大)
  2. 止盈: 均价+tp_pct%×vol_mult 一次全平 (BTC=4%, SOL/ETH按波动率放大), 无分批
  3. 加仓门禁: 需 Screen2 信号评分 ≥ addon_min_score (默认50)
  4. 无固定价格止损 (移除SL触发); 非明确信号不提前出场
  5. 出场条件: ① TP目标触及 ② Screen1方向明确反转 ③ 20%组合回撤强制全平
  6. 移除 risk_event 出场 (ATR扩张不再强制平仓)

v7.0 Opt-1B — 动态历史波动率(HV)驱动 Regime 阈值:
  1. _calc_quarterly_vol_mult(): 13周滚动 std / BTC基准(9%/周) → vol_mult
  2. 静态 _STATIC_REGIME_VOL_MULT 作为数据不足时的 fallback
  3. 回测自动滚动; 实盘建议每季度重新计算一次 vol_mult
  4. 效果: SOL vol_mult≈1.8, STRONG_BEAR 门槛动态扩宽至 ~-35% 4周跌幅

v7.0 Opt-2 — RSI+ATR 加仓抑制 (addon_suppressed, 阈值按代币波动率分档):
  1. Screen2Output 新增 addon_suppressed 字段
  2. ADDON_SUPPRESS_THRESHOLDS: BTC(RSI>70/ATR>1.4×) ETH(72/1.5×) SOL(76/1.8×)
  3. 引擎在 calc_martin_add_on 前检查 screen2.addon_suppressed

v6.0 Option C — 双向马丁 (bidirectional martingale):
  1. STRONG_BEAR regime → 强制做空 (direction=SHORT, 仓位60%)
  2. WEAK_BEAR regime → 继续观望 (direction=WAIT, 拒绝LONG)
  3. SHORT马丁底层全部就绪: 加仓触发high>=target, SL=均价×1.20, TP=均价-ATR×mult

v5.0 熊市门禁 (A+B方案):
  1. detect_market_regime() EMA50缺失时改用 price vs EMA20 (B: 解除50周数据依赖)
  2. Screen1 熊市入场门禁: regime=WEAK_BEAR/STRONG_BEAR → direction=WAIT, 拒绝新LONG (A)
  3. 移除失效的 EMA50×0.95 强制做空覆盖 (EMA50在27周数据内不可靠)

v4.0 市场状态增强 (v2改进):
  1. Screen1 熊市强制覆盖: 周线收盘低于EMA50×0.95 → 强制空头
  2. 新增 detect_market_regime(): 5档市场状态识别, 输出仓位乘数
  3. Screen1Output 新增 regime/regime_multiplier 字段
  4. Screen2 仓位计算引入 regime_multiplier (倍数缩放)
  5. TP倍数收窄: 0.8x/1.5x/2.5x ATR (原 2x/3x/5x)

v3.1 规范对齐修正 (D1/D2):
  D1. 分批止盈比例: 50%→30%→20% (原 30%/30%/40%)
  D2. 止损动态化: 加仓阶段=Level3极限价保护; 马丁完成后=均价×0.80

v3.0 基础修正 (完全对齐规范):
  1. 止损: 固定20% (基于入场价), 不再使用ATR倍数
  2. 加仓: 等额加仓 (不再递减)
  3. 止盈: 仅Level 3加满后启用 (不再Level 2即可)
  4. 离场: 分批止盈 50%/30%/20% (不再一次性全平)
  5. 仓位: 对齐规范 强多头60%/弱多头40%/观望20% 总仓位上限
  6. 止盈: 三层TP (ATR倍数), 渐进锁利

第一屏 (周线): 方向判断 + 策略类型选择 + 仓位上限
第二屏 (日线): 信号强度评估 + 四类订单设置
第三屏 (日线模拟): A9四层离场决策

简化说明:
  - 回测中以日线为主要时间粒度
  - 周线通过 resample 日线生成
  - 小时线信号简化为日线内的低点/高点触发
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import statistics


# ==================== 数据类型 ====================

class Direction(Enum):
    LONG = "long"
    SHORT = "short"
    WAIT = "wait"


class SignalStrength(Enum):
    STRONG = "strong"       # >=70
    MEDIUM = "medium"       # 50-69
    WEAK = "weak"           # 30-49
    NONE = "none"           # <30


class StrategyType(Enum):
    FUTURES_MARTIN = "futures_martin"
    SPOT_MARTIN = "spot_martin"


class ExitReason(Enum):
    TAKE_PROFIT_1 = "take_profit_1"      # v8.0: 单次全仓止盈 (均价+tp_pct%×vol_mult)
    TAKE_PROFIT_2 = "take_profit_2"      # 保留兼容 (v8.0不使用)
    TAKE_PROFIT_3 = "take_profit_3"      # 保留兼容 (v8.0不使用)
    STOP_LOSS = "stop_loss"              # 保留兼容 (v8.0不触发固定SL)
    SIGNAL_REVERSAL = "signal_reversal"
    DRAWDOWN_LIMIT = "drawdown_limit"
    RISK_EVENT = "risk_event"            # 保留兼容 (v8.0不触发)
    END_OF_BACKTEST = "end_of_backtest"
    NONE = "none"


@dataclass
class Screen1Output:
    """第一屏输出: 周线决策"""
    timestamp: int
    direction: Direction
    strategy_type: StrategyType
    weekly_score: float
    ema_trend: str
    macd_signal: str
    market_state: str = "观望"
    position_limit_pct: float = 0.20    # 总仓位上限: 20%/40%/60%
    regime: str = "CONSOLIDATION"       # 市场形态: STRONG_BULL/WEAK_BULL/CONSOLIDATION/WEAK_BEAR/STRONG_BEAR
    regime_multiplier: float = 0.5      # 仓位乘数: 0.5(震荡) / 0.75(弱趋势) / 1.0(强趋势)
    vol_mult: float = 1.0               # v8.0: 动态HV乘数, 用于加仓间隔和止盈计算


@dataclass
class Screen2Output:
    """第二屏输出: 日线预设"""
    timestamp: int
    signal_strength: SignalStrength
    signal_score: float
    entry_price: float
    position_pct: float              # 单层仓位比例 (总仓位的1/4)
    add_on_levels: List[float]       # 3个加仓价位 (复利间隔 addon_gap%×vol_mult)
    tp_target: float                 # v8.0: 单次全仓止盈目标 (均价+tp_pct%×vol_mult)
    atr: float
    volatility: float
    addon_suppressed: bool = False   # v7.0 Opt-2: RSI超买/ATR扩张时抑制本轮加仓


@dataclass
class Position:
    """当前持仓状态"""
    direction: Direction = Direction.WAIT
    entry_price: float = 0.0         # 加权平均入场价
    initial_size_usd: float = 0.0    # 初始入场大小 (用于等额加仓)
    size_usd: float = 0.0            # 当前持仓大小
    level: int = 0                   # 马丁层级 0=初始, 1-3=加仓
    add_on_levels: List[float] = field(default_factory=list)
    tp_target: float = 0.0           # v8.0: 单次全仓止盈目标 (随均价滚动更新)
    stop_loss_price: float = 0.0     # v9.0: 均价止损 (仅 Level3加满后启用, 默认0=未激活)
    highest_equity: float = 0.0
    entry_date: str = ""
    signal_strength: SignalStrength = SignalStrength.NONE
    screen1: Optional[Screen1Output] = None
    total_cost: float = 0.0
    is_martin_complete: bool = False  # Level 3加满标志 (用于统计)


@dataclass
class Trade:
    """交易记录"""
    trade_id: int
    timestamp: int
    date: str
    action: str           # open / add_on / partial_close / close
    direction: Direction
    price: float
    size_usd: float
    fee: float
    signal_strength: SignalStrength
    screen1_direction: Direction
    exit_reason: ExitReason = ExitReason.NONE
    pnl: float = 0.0
    pnl_pct: float = 0.0
    equity_at_close: float = 0.0


# ==================== 默认策略参数 (可被贝叶斯优化覆盖) ====================

DEFAULT_STRATEGY_PARAMS = {
    # 第一屏参数
    "strong_score_threshold": 65.0,   # 强多头阈值 (规范: >=65)
    "weak_score_threshold": 50.0,     # 弱多头阈值 (规范: >=50)
    "short_score_threshold": 35.0,    # 空头阈值 (规范: <=35)

    # v8.0 加仓参数: 按固定百分比复利计算间隔, 按 vol_mult 放大
    "addon_gap_pct": 8.0,             # BTC加仓间隔基准 (每跌8%加仓; SOL/ETH×vol_mult)
    "addon_min_score": 50.0,          # 加仓最低信号评分门禁 (Screen2 score)

    # v8.0 止盈参数: 单次全仓止盈, 按 vol_mult 放大
    "tp_pct": 4.0,                    # BTC止盈基准 (均价+4%; SOL/ETH×vol_mult)
}


def _apply_opt_params(defaults: dict, overrides: dict = None) -> dict:
    """合并优化参数 (保留默认值, 仅覆盖传入的参数)"""
    if not overrides:
        return defaults
    return {**defaults, **overrides}

# v7.0 Opt-1B: 动态 HV 驱动的 Regime 阈值乘数
# 静态表作为 fallback (数据 <4 周时使用)
# 推导: BTC~65%/ETH~85%/SOL~115% 年化波动率 → 周波动率基准 BTC≈9%/周
_STATIC_REGIME_VOL_MULT: dict = {
    "BTC-USDT-SWAP": 1.00,
    "ETH-USDT-SWAP": 1.30,
    "SOL-USDT-SWAP": 1.75,
}

# v7.0 Opt-2: 按代币波动率分档的加仓抑制阈值
# BTC 最敏感(低门槛), SOL 最宽松(高门槛), 避免误伤高波动品种正常行情
ADDON_SUPPRESS_THRESHOLDS: dict = {
    "BTC-USDT-SWAP": {"rsi_long": 70, "rsi_short": 30, "atr_mult": 1.4},
    "ETH-USDT-SWAP": {"rsi_long": 72, "rsi_short": 28, "atr_mult": 1.5},
    "SOL-USDT-SWAP": {"rsi_long": 76, "rsi_short": 24, "atr_mult": 1.8},
}


def _calc_quarterly_vol_mult(
    weekly_candles: List[Dict],
    idx: int,
    inst_id: str = "BTC-USDT-SWAP",
    reference_wv: float = 9.0,
) -> float:
    """
    动态历史波动率 (HV) → Regime 阈值乘数

    用最近 13 周 (≈一个季度) 的周收益率 std 除以 BTC 基准周波动率 (9%/周)
    返回值在 [0.8, 2.5] 之间, 数据不足时回退到静态表
    """
    if idx < 4:
        return _STATIC_REGIME_VOL_MULT.get(inst_id, 1.0)
    n = min(13, idx)
    returns = []
    for j in range(idx - n + 1, idx + 1):
        prev_close = weekly_candles[j - 1].get("close") or 0
        curr_close = weekly_candles[j].get("close") or 0
        if prev_close > 0:
            returns.append((curr_close - prev_close) / prev_close * 100)
    if len(returns) < 4:
        return _STATIC_REGIME_VOL_MULT.get(inst_id, 1.0)
    hv_weekly = statistics.stdev(returns)
    dynamic_mult = hv_weekly / reference_wv
    # 以静态基准为下限: 动态 HV 只能扩宽阈值, 不能收紧
    # 避免短期低波动期给高波动代币赋予过低的 vol_mult (冷启动问题)
    static_floor = _STATIC_REGIME_VOL_MULT.get(inst_id, 1.0)
    return max(static_floor, min(2.5, round(dynamic_mult, 3)))


# ==================== 市场形态识别 ====================

def detect_market_regime(
    weekly_candles: List[Dict],
    weekly_idx: int,
    vol_mult: float = 1.0,
) -> Tuple[str, float]:
    """
    市场状态识别 (5档), 返回 (regime_name, position_multiplier)

    vol_mult: 按代币波动率缩放价格动量阈值 (见 REGIME_VOL_MULT)
      BTC=1.0 (基准), ETH=1.3, SOL=1.75

    Regimes:
      STRONG_BULL  — EMA20>EMA50 >3%, MACD hist>0且增长, RSI 50-75  → 1.0
      WEAK_BULL    — EMA20>EMA50 0-3%, 或混合多头信号               → 0.75
      CONSOLIDATION— |EMA20-EMA50|/EMA50 <0.5%, ATR/close <2%       → 0.5
      WEAK_BEAR    — EMA20<EMA50 0-3%, 或 MACD hist<0               → 0.75
      STRONG_BEAR  — EMA20<EMA50 >3%, 或 close<EMA50×0.95           → 1.0
    """
    if weekly_idx < 1:
        return "CONSOLIDATION", 0.5

    curr = weekly_candles[weekly_idx]
    prev = weekly_candles[weekly_idx - 1]

    ema20     = curr.get("ema20")
    ema50     = curr.get("ema50")
    curr_hist = curr.get("macd_hist")
    prev_hist = prev.get("macd_hist")
    rsi       = curr.get("rsi")
    atr_val   = curr.get("atr") or 0
    close_val = curr.get("close") or 1

    # --- 主路径: EMA20+EMA50 均可用 ---
    if ema20 and ema50:
        ema_diff_pct = (ema20 - ema50) / ema50 * 100  # 正=多, 负=空

        if ema_diff_pct < -3.0:
            return "STRONG_BEAR", 1.0

        macd_growing = (curr_hist is not None and prev_hist is not None
                        and curr_hist > 0 and curr_hist > prev_hist)
        rsi_ok = rsi is not None and 50 <= rsi <= 75
        if ema_diff_pct > 3.0 and macd_growing and rsi_ok:
            return "STRONG_BULL", 1.0

        if abs(ema_diff_pct) < 0.5:
            atr_ratio = atr_val / close_val if close_val > 0 else 0
            if atr_ratio < 0.02:
                return "CONSOLIDATION", 0.5

        if ema_diff_pct < 0 or (curr_hist is not None and curr_hist < 0):
            return "WEAK_BEAR", 0.75

        return "WEAK_BULL", 0.75

    # --- B: 价格动量 fallback (EMA 数据不足时, 如周线窗口<50根) ---
    # 用4周涨跌幅 + 连续下跌判断趋势，无需EMA，最少需要4根周线
    if weekly_idx < 4:
        return "CONSOLIDATION", 0.5

    c4w = weekly_candles[weekly_idx - 4]["close"]
    c2w = weekly_candles[weekly_idx - 2]["close"] if weekly_idx >= 2 else close_val
    c1w = weekly_candles[weekly_idx - 1]["close"]
    chg4w = (close_val - c4w) / c4w * 100 if c4w > 0 else 0.0
    consec_down = close_val < c1w and c1w < c2w

    sb = 20 * vol_mult   # STRONG_BEAR/BULL 门槛 (BTC:-20/+20, SOL:-35/+35)
    wb = 8  * vol_mult   # WEAK_BEAR/BULL   门槛 (BTC:-8/+8,   SOL:-14/+14)
    sb2 = 10 * vol_mult  # STRONG_BEAR 连续下跌辅助门槛

    if chg4w < -sb or (chg4w < -sb2 and consec_down):
        return "STRONG_BEAR", 1.0
    if chg4w < -wb or (chg4w < -(wb * 0.5) and consec_down):
        return "WEAK_BEAR", 0.75
    if chg4w > sb:
        return "STRONG_BULL", 1.0
    if chg4w > wb:
        return "WEAK_BULL", 0.75
    return "CONSOLIDATION", 0.5


# ==================== 第一屏: 周线决策 ====================

def run_screen1(
    weekly_candles: List[Dict],
    current_idx: int,
    price: float,
    inst_id: str = "BTC-USDT-SWAP",
    opt_params: dict = None,
) -> Screen1Output:
    """
    第一屏: 周线决策 (对齐规范 1.1)

    评分维度 (各0-25分, 总分0-100):
    1. EMA趋势 (EMA20 vs EMA50)
    2. MACD金叉/死叉
    3. 价格与EMA关系
    4. 成交量趋势

    方向规则 (规范):
    - score >= 65: 强多头 LONG, 仓位上限60%, 合约马丁
    - score >= 50: 弱多头 LONG, 仓位上限40%
    - score > 35:  观望 LONG, 仓位上限20% (默认多头)
    - score <= 35: 空头 SHORT, 仓位上限60%, 合约马丁
    """
    if current_idx < 1:
        return Screen1Output(
            timestamp=weekly_candles[current_idx]["ts"],
            direction=Direction.LONG,
            strategy_type=StrategyType.SPOT_MARTIN,
            weekly_score=50.0,
            ema_trend="neutral",
            macd_signal="none",
            market_state="观望",
            position_limit_pct=0.20,
            regime="CONSOLIDATION",
            regime_multiplier=0.5,
            vol_mult=1.0,
        )

    params = _apply_opt_params(DEFAULT_STRATEGY_PARAMS, opt_params)
    strong_threshold = params["strong_score_threshold"]   # 65
    weak_threshold = params["weak_score_threshold"]       # 50
    short_threshold = params["short_score_threshold"]     # 35

    curr = weekly_candles[current_idx]
    prev = weekly_candles[current_idx - 1]
    vol_mult = _calc_quarterly_vol_mult(weekly_candles, current_idx, inst_id)
    regime, regime_multiplier = detect_market_regime(weekly_candles, current_idx, vol_mult)
    score = 50.0
    ema_trend = "neutral"
    macd_signal = "none"

    # 维度1: EMA趋势 (0-25分)
    if curr.get("ema20") and curr.get("ema50"):
        ema20, ema50 = curr["ema20"], curr["ema50"]
        if ema20 > ema50:
            trend_strength = min((ema20 / ema50 - 1) * 100, 5) / 5 * 25
            score += trend_strength
            ema_trend = "bullish"
        elif ema20 < ema50:
            trend_strength = min((ema50 / ema20 - 1) * 100, 5) / 5 * 25
            score -= trend_strength
            ema_trend = "bearish"

    # 维度2: MACD金叉/死叉 (0-25分)
    if (curr.get("macd_hist") is not None and prev.get("macd_hist") is not None
            and curr.get("macd") is not None):
        curr_hist = curr["macd_hist"]
        prev_hist = prev["macd_hist"]
        if prev_hist <= 0 and curr_hist > 0:
            score += 20
            macd_signal = "golden_cross"
        elif prev_hist >= 0 and curr_hist < 0:
            score -= 20
            macd_signal = "death_cross"
        elif curr_hist > 0:
            score += min(abs(curr_hist) / (abs(curr["macd"]) + 0.001) * 10, 10)
        elif curr_hist < 0:
            score -= min(abs(curr_hist) / (abs(curr["macd"]) + 0.001) * 10, 10)

    # 维度3: 价格与EMA关系 (0-25分)
    if curr.get("ema20"):
        ema20 = curr["ema20"]
        price_ratio = (price - ema20) / ema20 * 100
        if price_ratio > 0:
            score += min(price_ratio * 5, 12)
        else:
            score -= min(abs(price_ratio) * 5, 12)

    # 维度4: 成交量趋势 (0-25分)
    if curr.get("vol_ratio"):
        vr = curr["vol_ratio"]
        if vr > 1.5:
            score += 8
        elif vr < 0.7:
            score -= 5

    score = max(0, min(100, score))

    # 方向判断 (v5.0: 评分分支 + 熊市门禁, 移除失效的EMA50绝对跌破覆盖)
    if score <= short_threshold:
        direction = Direction.SHORT
        market_state = "空头"
        position_limit = 0.60
    elif score >= strong_threshold:
        direction = Direction.LONG
        market_state = "强多头"
        position_limit = 0.60
    elif score >= weak_threshold:
        direction = Direction.LONG
        market_state = "弱多头"
        position_limit = 0.40
    else:
        direction = Direction.LONG
        market_state = "观望"
        position_limit = 0.20

    # v6.0 Option C: 双向马丁 — 按 regime 决定 LONG/SHORT/WAIT
    # 仅影响新开仓; 已持仓由 check_exit_signals 正常管理
    if direction == Direction.LONG:
        if regime == "STRONG_BEAR":
            # 强熊市: 反转做空 (4w跌幅>20% 或 >10%+连续下跌)
            direction = Direction.SHORT
            market_state = "强制空头(STRONG_BEAR)"
            position_limit = 0.60
        elif regime == "WEAK_BEAR":
            # 弱熊市: 观望, 不冒险
            direction = Direction.WAIT
            market_state = "暂停入场(WEAK_BEAR)"
            position_limit = 0.0

    # 策略类型: 基于波动率
    atr_val = curr.get("atr") or 0
    close_val = curr["close"] or 1
    volatility = atr_val / close_val * 100 if close_val > 0 else 0
    strategy_type = StrategyType.FUTURES_MARTIN if volatility > 3 else StrategyType.SPOT_MARTIN

    return Screen1Output(
        timestamp=curr["ts"],
        direction=direction,
        strategy_type=strategy_type,
        weekly_score=round(score, 2),
        ema_trend=ema_trend,
        macd_signal=macd_signal,
        market_state=market_state,
        position_limit_pct=position_limit,
        regime=regime,
        regime_multiplier=regime_multiplier,
        vol_mult=vol_mult,
    )


# ==================== 第二屏: 日线预设 ====================

def _calc_20d_volatility(daily_candles: List[Dict], idx: int) -> float:
    """计算20日波动率 (百分比)"""
    if idx < 20:
        return 2.0
    returns = []
    for i in range(idx - 19, idx + 1):
        if i > 0 and daily_candles[i - 1]["close"] > 0:
            ret = (daily_candles[i]["close"] - daily_candles[i - 1]["close"]) / daily_candles[i - 1]["close"]
            returns.append(ret)
    if len(returns) < 5:
        return 2.0
    return statistics.stdev(returns) * 100


def _calc_20d_atr(daily_candles: List[Dict], idx: int) -> float:
    """计算20日ATR均值，用于判断ATR是否异常扩张"""
    if idx < 5:
        return daily_candles[idx].get("atr") or 0.0
    vals = [daily_candles[j].get("atr") or 0.0 for j in range(max(0, idx - 19), idx + 1) if daily_candles[j].get("atr")]
    return sum(vals) / len(vals) if vals else 0.0


def _classify_signal(score: float) -> SignalStrength:
    if score >= 70:
        return SignalStrength.STRONG
    elif score >= 50:
        return SignalStrength.MEDIUM
    elif score >= 30:
        return SignalStrength.WEAK
    return SignalStrength.NONE


def run_screen2(
    daily_candles: List[Dict],
    current_idx: int,
    screen1: Screen1Output,
    position: Optional[Position],
    inst_id: str = "BTC-USDT-SWAP",
    opt_params: dict = None,
) -> Screen2Output:
    """
    第二屏: 日线预设 (v8.0)

    v8.0 规则:
    - 加仓间隔: addon_gap_pct%×vol_mult 复利计算 (BTC=8%, SOL/ETH按波动率放大)
    - 止盈: 单次全仓, 均价+tp_pct%×vol_mult (BTC=4%, SOL/ETH按波动率放大)
    - 无固定止损价 (由 check_exit_signals L2/L4 管理出场)
    - 仓位: 对齐规范的60%/40%/20%总仓位上限
    """
    params = _apply_opt_params(DEFAULT_STRATEGY_PARAMS, opt_params)
    addon_gap_pct = params.get("addon_gap_pct", 8.0)
    tp_pct = params.get("tp_pct", 4.0)
    vol_mult = getattr(screen1, "vol_mult", 1.0)

    curr = daily_candles[current_idx]
    price = curr["close"]
    score = 50.0

    # 维度1: 趋势一致性 (日线与周线方向一致)
    if curr.get("ema20") and curr.get("ema50"):
        if screen1.direction == Direction.LONG and curr["ema20"] > curr["ema50"]:
            score += 15
        elif screen1.direction == Direction.SHORT and curr["ema20"] < curr["ema50"]:
            score += 15
        elif screen1.direction != Direction.WAIT:
            score -= 10

    # 维度2: MACD信号
    if current_idx >= 1:
        prev = daily_candles[current_idx - 1]
        curr_hist = curr.get("macd_hist") or 0
        prev_hist = prev.get("macd_hist") or 0
        if prev_hist <= 0 and curr_hist > 0 and screen1.direction == Direction.LONG:
            score += 20
        elif prev_hist >= 0 and curr_hist < 0 and screen1.direction == Direction.SHORT:
            score += 20
        elif curr_hist > 0 and screen1.direction == Direction.LONG:
            score += 8
        elif curr_hist < 0 and screen1.direction == Direction.SHORT:
            score += 8

    # 维度3: RSI信号
    rsi_val = curr.get("rsi")
    if rsi_val is not None:
        if screen1.direction == Direction.LONG:
            if rsi_val < 30:
                score += 15
            elif rsi_val > 70:
                score -= 10
            elif 40 <= rsi_val <= 60:
                score += 5
        elif screen1.direction == Direction.SHORT:
            if rsi_val > 70:
                score += 15
            elif rsi_val < 30:
                score -= 10
            elif 40 <= rsi_val <= 60:
                score += 5

    # 维度4: 成交量确认
    vr = curr.get("vol_ratio") or 1.0
    if vr > 1.3:
        score += 5
    elif vr < 0.6:
        score -= 5

    score = max(0, min(100, score))
    signal_strength = _classify_signal(score)

    # 波动率与ATR
    atr_val = curr.get("atr") or (price * 0.02)
    volatility = _calc_20d_volatility(daily_candles, current_idx)

    # === 仓位计算 (对齐规范) ===
    # 规范: 总仓位上限 = screen1.position_limit_pct (20%/40%/60%)
    # 马丁策略: 4个层级 (初始 + 3次加仓), 每层等额
    total_limit = screen1.position_limit_pct

    strength_mult = {
        SignalStrength.STRONG: 1.0,
        SignalStrength.MEDIUM: 0.7,
        SignalStrength.WEAK: 0.4,
        SignalStrength.NONE: 0.2,
    }.get(signal_strength, 0.2)

    effective_total = total_limit * strength_mult * screen1.regime_multiplier
    single_layer_pct = effective_total / 4.0  # 等额分4层

    # v8.0: 加仓间隔 = addon_gap_pct%×vol_mult 复利 (BTC=8%, SOL/ETH按波动率放大)
    gap = addon_gap_pct / 100.0 * vol_mult
    add_on_levels = []
    if screen1.direction == Direction.LONG:
        add_on_levels = [
            round(price * (1 - gap) ** 1, 2),
            round(price * (1 - gap) ** 2, 2),
            round(price * (1 - gap) ** 3, 2),
        ]
        tp_target = round(price * (1 + tp_pct / 100.0 * vol_mult), 2)
    elif screen1.direction == Direction.SHORT:
        add_on_levels = [
            round(price * (1 + gap) ** 1, 2),
            round(price * (1 + gap) ** 2, 2),
            round(price * (1 + gap) ** 3, 2),
        ]
        tp_target = round(price * (1 - tp_pct / 100.0 * vol_mult), 2)
    else:
        tp_target = 0.0

    # v7.0 Opt-2: RSI+ATR 加仓抑制 (阈值按代币波动率分档)
    sup_cfg = ADDON_SUPPRESS_THRESHOLDS.get(
        inst_id, ADDON_SUPPRESS_THRESHOLDS["ETH-USDT-SWAP"]
    )
    rsi_val = curr.get("rsi")
    avg_atr_20d = _calc_20d_atr(daily_candles, current_idx)
    atr_expanding = avg_atr_20d > 0 and atr_val > avg_atr_20d * sup_cfg["atr_mult"]
    addon_suppressed = False
    if atr_expanding:
        if screen1.direction == Direction.LONG and rsi_val and rsi_val > sup_cfg["rsi_long"]:
            addon_suppressed = True
        elif screen1.direction == Direction.SHORT and rsi_val and rsi_val < sup_cfg["rsi_short"]:
            addon_suppressed = True

    return Screen2Output(
        timestamp=curr["ts"],
        signal_strength=signal_strength,
        signal_score=round(score, 2),
        entry_price=price,
        position_pct=round(single_layer_pct, 4),
        add_on_levels=add_on_levels,
        tp_target=tp_target,
        atr=atr_val,
        volatility=round(volatility, 4),
        addon_suppressed=addon_suppressed,
    )


# ==================== 第三屏: A9离场决策 ====================

def check_exit_signals(
    position: Position,
    daily_candle: Dict,
    screen1: Screen1Output,
    current_equity: float,
    peak_equity: float,
    trade_count: int
) -> Tuple[bool, ExitReason, int]:
    """
    v8.0 简化离场决策 (三条件, 非明确信号不出场)

    返回: (should_exit, exit_reason, -1)  — v8.0 全部为全仓平仓 (-1)

    L1a: TP目标触及 (均价+tp_pct%×vol_mult) → 全平
    L1b: 均价止损 (仅 Level3加满后; avg×0.80/×1.20) → 全平
    L2:  Screen1 方向明确反转 (LONG→SHORT 或 SHORT→LONG)
    L4:  最大回撤约束 (20%强制全平)

    已移除: L1-固定SL(未加满时无SL), L1c(移动止盈), L3(风险事件/ATR扩张)
    """
    if position.direction == Direction.WAIT:
        return False, ExitReason.NONE, -1

    high = daily_candle["high"]
    low = daily_candle["low"]

    # --- L1a: 单次全仓止盈 (tp_target 触发) ---
    if position.tp_target > 0:
        if position.direction == Direction.LONG and high >= position.tp_target:
            return True, ExitReason.TAKE_PROFIT_1, -1
        elif position.direction == Direction.SHORT and low <= position.tp_target:
            return True, ExitReason.TAKE_PROFIT_1, -1

    # --- L1b: 均价止损 (v9.0: 仅 Level3加满后激活, stop_loss_price=avg×0.80/×1.20) ---
    if position.is_martin_complete and position.stop_loss_price > 0:
        if position.direction == Direction.LONG and low <= position.stop_loss_price:
            return True, ExitReason.STOP_LOSS, -1
        elif position.direction == Direction.SHORT and high >= position.stop_loss_price:
            return True, ExitReason.STOP_LOSS, -1

    # --- L2: Screen1 方向明确反转 ---
    if position.screen1 and screen1.direction != Direction.WAIT:
        if position.direction == Direction.LONG and screen1.direction == Direction.SHORT:
            return True, ExitReason.SIGNAL_REVERSAL, -1
        if position.direction == Direction.SHORT and screen1.direction == Direction.LONG:
            return True, ExitReason.SIGNAL_REVERSAL, -1

    # --- L4: 最大回撤约束 (20%强制全平) ---
    if peak_equity > 0:
        drawdown = (peak_equity - current_equity) / peak_equity * 100
        if drawdown >= 20:
            return True, ExitReason.DRAWDOWN_LIMIT, -1

    return False, ExitReason.NONE, -1


# ==================== 仓位管理 ====================

def calc_martin_add_on(
    position: Position,
    candle: Dict,
    available_capital: float,
    equity: float,
    taker_fee: float = 0.0005,
    min_score: float = 50.0,
    signal_score: float = 50.0,
) -> Optional[Tuple[float, float]]:
    """
    检查是否触发马丁加仓 (v8.0: 需信号评分门禁 + 等额加仓)

    返回: (add_price, add_size_usd) 或 None
    """
    if position.direction == Direction.WAIT:
        return None
    if position.level >= 3:  # 最多3次加仓
        return None

    # v8.0: 信号强度门禁 (加仓需 Screen2 评分达标)
    if signal_score < min_score:
        return None

    # 检查当前价格是否触发加仓位
    price = candle["close"]
    low = candle["low"]
    high = candle["high"]

    target_level = position.level
    if target_level >= len(position.add_on_levels):
        return None

    target_price = position.add_on_levels[target_level]

    # 检查是否触及
    triggered = False
    if position.direction == Direction.LONG and low <= target_price:
        triggered = True
    elif position.direction == Direction.SHORT and high >= target_price:
        triggered = True

    if not triggered:
        return None

    # === 等额加仓 (规范) ===
    add_size = position.initial_size_usd

    # 累计仓位上限
    total_after_add = position.size_usd + add_size + add_size * taker_fee
    if total_after_add / equity > 0.60:
        add_size = max(equity * 0.60 - position.size_usd, 0) * (1 - taker_fee)
        if add_size < 10:
            return None

    # 检查可用资金
    if add_size * (1 + taker_fee) > available_capital:
        add_size = available_capital / (1 + taker_fee)
        if add_size < 10:
            return None

    return (target_price, round(add_size, 2))



def recalc_avg_entry(
    position: Position,
    add_price: float,
    add_size: float,
    taker_fee: float = 0.0005,
    vol_mult: float = 1.0,
    tp_pct: float = 4.0,
):
    """重新计算平均入场价和止盈目标 (v8.0: TP随均价滚动更新, 无固定SL)"""
    old_total = position.entry_price * position.size_usd
    new_total = add_price * add_size
    total_size = position.size_usd + add_size

    if total_size > 0:
        position.entry_price = (old_total + new_total) / total_size
    position.size_usd = total_size
    position.total_cost += add_size * taker_fee
    position.level += 1

    # v8.0: TP目标 = 新均价 × (1 + tp_pct%×vol_mult)
    tp_gap = tp_pct / 100.0 * vol_mult
    if position.direction == Direction.LONG:
        position.tp_target = round(position.entry_price * (1 + tp_gap), 2)
    elif position.direction == Direction.SHORT:
        position.tp_target = round(position.entry_price * (1 - tp_gap), 2)

    # 马丁完成统计 (Level 3 = 初始 + 3次加仓)
    if position.level >= 3:
        position.is_martin_complete = True
        # v9.0: Level3加满后激活均价止损 (防整链全亏)
        if position.direction == Direction.LONG:
            position.stop_loss_price = round(position.entry_price * 0.80, 2)
        elif position.direction == Direction.SHORT:
            position.stop_loss_price = round(position.entry_price * 1.20, 2)
