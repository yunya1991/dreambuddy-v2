#!/usr/bin/env python3
"""
回测策略实现模块 v3.0
======================
忠实实现 TRADING_WORKFLOW_SPEC_v1.md 设计规范

v3.0 重大修正 (完全对齐规范):
  1. 止损: 固定20% (基于入场价), 不再使用ATR倍数
  2. 加仓: 等额加仓 (不再递减)
  3. 止盈: 仅Level 3加满后启用 (不再Level 2即可)
  4. 离场: 分批止盈 30%/30%/40% (不再一次性全平)
  5. 仓位: 对齐规范 强多头60%/弱多头40%/观望20% 总仓位上限
  6. 止盈: 三层TP (2x/3x/5x ATR), 渐进锁利

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
    TAKE_PROFIT_1 = "take_profit_1"      # 第一档止盈 (平30%)
    TAKE_PROFIT_2 = "take_profit_2"      # 第二档止盈 (平30%)
    TAKE_PROFIT_3 = "take_profit_3"      # 第三档止盈 (平40%)
    STOP_LOSS = "stop_loss"
    SIGNAL_REVERSAL = "signal_reversal"
    DRAWDOWN_LIMIT = "drawdown_limit"
    RISK_EVENT = "risk_event"
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


@dataclass
class Screen2Output:
    """第二屏输出: 日线预设"""
    timestamp: int
    signal_strength: SignalStrength
    signal_score: float
    entry_price: float
    position_pct: float              # 单层仓位比例 (总仓位的1/4)
    add_on_levels: List[float]       # 3个加仓价位
    tp_levels: List[float]           # 3个止盈价位 (2x/3x/5x ATR)
    stop_loss_price: float           # 固定20%止损价
    atr: float
    volatility: float


@dataclass
class Position:
    """当前持仓状态 — 支持分批仓位"""
    direction: Direction = Direction.WAIT
    entry_price: float = 0.0         # 加权平均入场价
    initial_size_usd: float = 0.0    # 初始入场大小 (用于等额加仓)
    size_usd: float = 0.0            # 当前持仓大小
    level: int = 0                   # 马丁层级 0=初始, 1-3=加仓
    add_on_levels: List[float] = field(default_factory=list)
    tp_levels: List[float] = field(default_factory=list)  # 三层止盈价位
    tp_hit: List[bool] = field(default_factory=list)      # 每层是否已触发
    stop_loss_price: float = 0.0
    highest_equity: float = 0.0
    entry_date: str = ""
    signal_strength: SignalStrength = SignalStrength.NONE
    screen1: Optional[Screen1Output] = None
    total_cost: float = 0.0
    is_martin_complete: bool = False  # Level 3加满标志


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

    # 第二屏参数
    "level_spacing_k": 0.5,           # 加仓间隔系数 (波动率 * 0.5, 最小1%)

    # 止盈参数 (ATR倍数)
    "tp_level_1": 2.0,                # 第一档止盈 ATR倍数 (平30%)
    "tp_level_2": 3.0,                # 第二档止盈 ATR倍数 (平30%)
    "tp_level_3": 5.0,                # 第三档止盈 ATR倍数 (平40%)

    # 止损: 固定20%, 不可被优化覆盖 (硬性约束)
    "stop_loss_pct": 20.0,            # 止损百分比 (固定, 不优化)

    # 仓位参数
    "base_pos_pct": 100.0,            # 基础仓位比例 (用于信号强度缩放)
}


def _apply_opt_params(defaults: dict, overrides: dict = None) -> dict:
    """合并优化参数 (保留默认值, 仅覆盖传入的参数)"""
    if not overrides:
        return defaults
    merged = {**defaults, **overrides}
    # 止损固定20%, 不允许优化覆盖
    merged["stop_loss_pct"] = 20.0
    return merged


# ==================== 分批止盈比例 (规范) ====================

TP_RATIOS = [0.30, 0.30, 0.40]  # 第一档30%, 第二档30%, 第三档40%


# ==================== 第一屏: 周线决策 ====================

def run_screen1(
    weekly_candles: List[Dict],
    current_idx: int,
    price: float,
    opt_params: dict = None
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
        )

    params = _apply_opt_params(DEFAULT_STRATEGY_PARAMS, opt_params)
    strong_threshold = params["strong_score_threshold"]   # 65
    weak_threshold = params["weak_score_threshold"]       # 50
    short_threshold = params["short_score_threshold"]     # 35

    curr = weekly_candles[current_idx]
    prev = weekly_candles[current_idx - 1]
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

    # 方向判断 (严格对齐规范)
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
        # score > short_threshold && < weak_threshold: 观望 = 弱多头 LONG
        direction = Direction.LONG
        market_state = "观望"
        position_limit = 0.20

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
    opt_params: dict = None
) -> Screen2Output:
    """
    第二屏: 日线预设 (对齐规范 1.2)

    核心修正:
    - 止损: 固定20% (规范硬性约束, 不考虑置信度)
    - 止盈: 三层 (2x/3x/5x ATR), 仅Level 3后启用
    - 加仓间隔: 20日波动率 * 0.5, 最小1%
    - 仓位: 对齐规范的60%/40%/20%总仓位上限
    """
    params = _apply_opt_params(DEFAULT_STRATEGY_PARAMS, opt_params)
    level_spacing_k = params["level_spacing_k"]
    tp_level_1 = params["tp_level_1"]
    tp_level_2 = params["tp_level_2"]
    tp_level_3 = params["tp_level_3"]
    stop_loss_pct = params["stop_loss_pct"]  # 固定20%

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
    # 单层仓位 = 总仓位上限 / 4
    total_limit = screen1.position_limit_pct

    # 信号强度缩放:
    #   STRONG (>=70): 使用100%的总仓位上限
    #   MEDIUM (50-69): 使用70%的总仓位上限
    #   WEAK (30-49): 使用40%的总仓位上限
    #   NONE (<30): 使用20%的总仓位上限 (观望也允许开仓)
    strength_mult = {
        SignalStrength.STRONG: 1.0,
        SignalStrength.MEDIUM: 0.7,
        SignalStrength.WEAK: 0.4,
        SignalStrength.NONE: 0.2,
    }.get(signal_strength, 0.2)

    effective_total = total_limit * strength_mult
    single_layer_pct = effective_total / 4.0  # 等额分4层

    # 加仓阶梯 (规范: 20日波动率 * 0.5, 最小1%)
    add_on_interval = max(volatility * level_spacing_k, 1.0) / 100.0  # 转为小数
    add_on_levels = []
    if screen1.direction == Direction.LONG:
        add_on_levels = [
            round(price * (1 - add_on_interval), 2),
            round(price * (1 - add_on_interval * 2), 2),
            round(price * (1 - add_on_interval * 3), 2),
        ]
    elif screen1.direction == Direction.SHORT:
        add_on_levels = [
            round(price * (1 + add_on_interval), 2),
            round(price * (1 + add_on_interval * 2), 2),
            round(price * (1 + add_on_interval * 3), 2),
        ]

    # 止盈: 三层 (规范: 2x/3x/5x ATR, 仅Level 3后启用)
    atr_pct = atr_val / price if price > 0 else 0.02
    if screen1.direction == Direction.LONG:
        tp_levels = [
            round(price * (1 + atr_pct * tp_level_1), 2),
            round(price * (1 + atr_pct * tp_level_2), 2),
            round(price * (1 + atr_pct * tp_level_3), 2),
        ]
        # 止损: 固定20% (规范硬性约束)
        sl_price = round(price * (1 - stop_loss_pct / 100.0), 2)
    elif screen1.direction == Direction.SHORT:
        tp_levels = [
            round(price * (1 - atr_pct * tp_level_1), 2),
            round(price * (1 - atr_pct * tp_level_2), 2),
            round(price * (1 - atr_pct * tp_level_3), 2),
        ]
        sl_price = round(price * (1 + stop_loss_pct / 100.0), 2)
    else:
        tp_levels = [
            round(price * (1 + atr_pct * tp_level_1), 2),
            round(price * (1 + atr_pct * tp_level_2), 2),
            round(price * (1 + atr_pct * tp_level_3), 2),
        ]
        sl_price = round(price * (1 - stop_loss_pct / 100.0), 2)

    return Screen2Output(
        timestamp=curr["ts"],
        signal_strength=signal_strength,
        signal_score=round(score, 2),
        entry_price=price,
        position_pct=round(single_layer_pct, 4),
        add_on_levels=add_on_levels,
        tp_levels=tp_levels,
        stop_loss_price=sl_price,
        atr=atr_val,
        volatility=round(volatility, 4),
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
    A9 四层离场决策检查 (对齐规范 1.3)

    返回: (should_exit, exit_reason, tp_level_to_close)
          tp_level_to_close: -1=全平, 0/1/2=关闭对应止盈档位

    L1: 技术止盈止损
      - 止损: 固定20%, 无条件触发
      - 止盈: 仅Level 3加满后启用, 分三层 (30%/30%/40%)
    L2: 信号反转 (连续2根K线确认)
    L3: 风险事件 (单日ATR超正常值3倍)
    L4: 最大回撤约束 (20%强制全平)
    """
    if position.direction == Direction.WAIT:
        return False, ExitReason.NONE, -1

    price = daily_candle["close"]
    low = daily_candle["low"]
    high = daily_candle["high"]

    # --- L1: 技术止损 (固定20%, 无条件触发, 所有层级) ---
    if position.direction == Direction.LONG:
        if low <= position.stop_loss_price:
            return True, ExitReason.STOP_LOSS, -1  # 全平
    elif position.direction == Direction.SHORT:
        if high >= position.stop_loss_price:
            return True, ExitReason.STOP_LOSS, -1  # 全平

    # --- L1: 技术止盈 (仅Level 3加满后启用, 分三层) ---
    if position.is_martin_complete and position.tp_levels:
        for tp_idx in range(len(position.tp_levels)):
            if position.tp_hit[tp_idx]:
                continue  # 已触发, 跳过
            tp_price = position.tp_levels[tp_idx]
            triggered = False
            if position.direction == Direction.LONG and high >= tp_price:
                triggered = True
            elif position.direction == Direction.SHORT and low <= tp_price:
                triggered = True

            if triggered:
                reason = [ExitReason.TAKE_PROFIT_1, ExitReason.TAKE_PROFIT_2, ExitReason.TAKE_PROFIT_3][tp_idx]
                return True, reason, tp_idx

    # --- L1b: 移动止盈 (Level 3加满后, 盈利超10%触发保护) ---
    if position.is_martin_complete:
        if position.direction == Direction.LONG:
            unrealized_pct = (price - position.entry_price) / position.entry_price
            if unrealized_pct > 0.10:
                # 所有TP已触发, 检查是否回撤到2%利润保护线
                all_tp_hit = all(position.tp_hit) if position.tp_hit else False
                if all_tp_hit and low <= position.entry_price * 1.02:
                    return True, ExitReason.TAKE_PROFIT_3, 2
        elif position.direction == Direction.SHORT:
            unrealized_pct = (position.entry_price - price) / position.entry_price
            if unrealized_pct > 0.10:
                all_tp_hit = all(position.tp_hit) if position.tp_hit else False
                if all_tp_hit and high >= position.entry_price * 0.98:
                    return True, ExitReason.TAKE_PROFIT_3, 2

    # --- L2: 信号反转 (需要极端偏离才触发) ---
    if position.screen1 and screen1.direction != Direction.WAIT:
        if (position.direction == Direction.LONG and screen1.direction == Direction.SHORT
                and screen1.weekly_score <= 25):
            return True, ExitReason.SIGNAL_REVERSAL, -1
        if (position.direction == Direction.SHORT and screen1.direction == Direction.LONG
                and screen1.weekly_score >= 75):
            return True, ExitReason.SIGNAL_REVERSAL, -1

    # --- L3: 风险事件 (单日波幅超10%) ---
    atr = daily_candle.get("atr") or 0
    if atr > 0 and position.entry_price > 0:
        atr_pct = atr / position.entry_price
        if atr_pct > 0.10:
            return True, ExitReason.RISK_EVENT, -1

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
    taker_fee: float = 0.0005
) -> Optional[Tuple[float, float]]:
    """
    检查是否触发马丁加仓 (对齐规范: 等额加仓)

    返回: (add_price, add_size_usd) 或 None
    """
    if position.direction == Direction.WAIT:
        return None
    if position.level >= 3:  # 最多3次加仓
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


def calc_partial_close(
    position: Position,
    tp_level: int
) -> float:
    """
    计算分批止盈的平仓数量 (规范: 30%/30%/40%)

    tp_level: 0=第一档, 1=第二档, 2=第三档
    返回: 要平仓的USD数量
    """
    if tp_level < 0 or tp_level >= len(TP_RATIOS):
        return position.size_usd  # 全平
    return position.size_usd * TP_RATIOS[tp_level]


def recalc_avg_entry(
    position: Position,
    add_price: float,
    add_size: float,
    taker_fee: float = 0.0005
):
    """重新计算平均入场价和总成本 (加仓用)"""
    old_total = position.entry_price * position.size_usd
    new_total = add_price * add_size
    total_size = position.size_usd + add_size

    if total_size > 0:
        position.entry_price = (old_total + new_total) / total_size
    position.size_usd = total_size
    position.total_cost += add_size * taker_fee
    position.level += 1

    # 检查是否完成全部加仓 (Level 3 = 初始 + 3次加仓)
    if position.level >= 3:
        position.is_martin_complete = True
