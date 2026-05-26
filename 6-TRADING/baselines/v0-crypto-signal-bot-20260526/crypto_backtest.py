#!/usr/bin/env python3
"""
crypto_backtest.py  —  crypto-signal-bot 策略六个月回测
==========================================================
基线策略: https://github.com/yunya1991/crypto-signal-bot (btc_signal_bot.py)
回测标的: BTC / SOL / ETH  (USDT 现货)
周期:     1H
时间窗口: 过去 6 个月
数据源:   Binance Vision 公开 API (data-api.binance.vision)

对比指标:
  - 总收益率、年化收益率
  - 胜率 (TP命中率)
  - 夏普比率 (年化)
  - 最大回撤
  - 盈亏比 (Profit Factor)
  - 总交易次数 / 多空分布

运行: python -X utf8 crypto_backtest.py
"""

import json, math, time, urllib.request, os, statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 配置 ─────────────────────────────────────────────────────────────────────
SYMBOLS          = ['BTCUSDT', 'SOLUSDT', 'ETHUSDT']
INTERVAL         = '1h'
MONTHS_BACK      = 6
INITIAL_CAPITAL  = 10_000.0     # USD，每只标的独立模拟
CACHE_DIR        = Path('C:/tmp/backtest_cache')

# 交易参数 — 来自 BOT_ADVICE（与 btc_signal_bot.py 完全一致）
TRADE_PARAMS = {
    'LONG':         {'tp': 0.020, 'sl': 0.015, 'hold_bars': 12, 'dir': 'LONG'},
    'SHORT':        {'tp': 0.020, 'sl': 0.015, 'hold_bars': 12, 'dir': 'SHORT'},
    'STRONG SHORT': {'tp': 0.015, 'sl': 0.015, 'hold_bars': 12, 'dir': 'SHORT'},
    # STRONG LONG: 跳过（仅31.8%胜率，系统建议不操作）
}

# ── 指标计算（与 btc_signal_bot.py 完全一致，行为零差异）─────────────────────

def sma(a, n):
    return [None if i < n-1 else sum(a[i-n+1:i+1])/n for i in range(len(a))]

def ema(a, n):
    r = [None] * len(a)
    if len(a) < n: return r
    k = 2 / (n + 1)
    r[n-1] = sum(a[:n]) / n
    for i in range(n, len(a)):
        r[i] = a[i] * k + r[i-1] * (1 - k)
    return r

def rsi(a, n=14):
    r = [None] * len(a)
    if len(a) <= n: return r
    ag = al = 0
    for i in range(1, n+1):
        d = a[i] - a[i-1]
        ag += max(d, 0); al += max(-d, 0)
    ag /= n; al /= n
    r[n] = 100 if al == 0 else 100 - 100/(1 + ag/al)
    for i in range(n+1, len(a)):
        d = a[i] - a[i-1]
        ag = (ag*(n-1) + max(d, 0)) / n
        al = (al*(n-1) + max(-d, 0)) / n
        r[i] = 100 if al == 0 else 100 - 100/(1 + ag/al)
    return r

def macd_calc(a, f=12, s=26, sig=9):
    ef, es = ema(a, f), ema(a, s)
    line = [ef[i] - es[i] if ef[i] is not None and es[i] is not None else None
            for i in range(len(a))]
    vi = [i for i, v in enumerate(line) if v is not None]
    signal = [None] * len(a)
    if len(vi) >= sig:
        vals = [line[i] for i in vi]
        k = 2 / (sig + 1)
        signal[vi[sig-1]] = sum(vals[:sig]) / sig
        for j in range(sig, len(vi)):
            signal[vi[j]] = vals[j] * k + signal[vi[j-1]] * (1 - k)
    return line, signal

def bollinger(a, n=20):
    mid = [None] * len(a)
    for i in range(n-1, len(a)):
        w = a[i-n+1:i+1]
        mid[i] = sum(w) / n
    return mid


def calc_signal_at(closes, kdata, i):
    """
    在第 i 根 K 线结束时生成信号 (使用 closes[0..i], 无前瞻偏差)
    返回: (signal_str, long_score, short_score, max_score)
    """
    if i < 30:
        return 'NEUTRAL', 0, 0, 14

    n = i + 1
    c = closes[:n]
    ma7    = sma(c, 7);  ma25 = sma(c, 25)
    bb_mid = bollinger(c)
    r      = rsi(c)
    ml, ms = macd_calc(c)
    p      = n - 2

    last_close   = c[-1]
    rsi_val      = r[-1]
    macd_line    = ml[-1];  macd_line_p = ml[p] if p >= 0 else None
    macd_sig_v   = ms[-1];  macd_sig_p  = ms[p] if p >= 0 else None
    bb_m         = bb_mid[-1]
    ma7v         = ma7[-1];  ma25v = ma25[-1]
    vol          = kdata[i]['volume']
    recent       = kdata[max(0, i-20):i]
    vol_avg      = sum(k['volume'] for k in recent) / len(recent) if recent else vol

    def ok(v): return v is not None

    macd_above  = ok(macd_line) and ok(macd_sig_v)  and macd_line > macd_sig_v
    macd_golden = (ok(macd_line) and ok(macd_sig_v) and ok(macd_line_p) and ok(macd_sig_p)
                   and macd_line_p < macd_sig_p and macd_line > macd_sig_v)
    macd_bull   = ok(macd_line) and macd_line > 0
    macd_below  = ok(macd_line) and ok(macd_sig_v)  and macd_line < macd_sig_v
    macd_dead   = (ok(macd_line) and ok(macd_sig_v) and ok(macd_line_p) and ok(macd_sig_p)
                   and macd_line_p > macd_sig_p and macd_line < macd_sig_v)
    macd_bear   = ok(macd_line) and macd_line < 0
    rsi_os      = ok(rsi_val) and rsi_val < 35
    rsi_ob      = ok(rsi_val) and rsi_val > 65
    rsi_mb      = ok(rsi_val) and 35 <= rsi_val < 70
    rsi_ms      = ok(rsi_val) and 30 < rsi_val <= 65
    above_mid   = ok(bb_m) and last_close > bb_m
    below_mid   = ok(bb_m) and last_close < bb_m
    ma_bull     = ok(ma7v) and ok(ma25v) and ma7v > ma25v
    ma_bear     = ok(ma7v) and ok(ma25v) and ma7v < ma25v
    vol_spike   = vol > vol_avg * 1.5

    long_conds  = [('MACD金叉', macd_golden, 2), ('MACD>Signal', macd_above, 2),
                   ('MACD>0', macd_bull, 1),     ('RSI健康', rsi_mb, 2),
                   ('RSI超卖', rsi_os, 2),        ('价格>BB中轨', above_mid, 2),
                   ('MA7>MA25', ma_bull, 2),      ('放量', vol_spike, 1)]
    short_conds = [('MACD死叉', macd_dead, 2),   ('MACD<Signal', macd_below, 2),
                   ('MACD<0', macd_bear, 1),      ('RSI健康', rsi_ms, 2),
                   ('RSI超买', rsi_ob, 2),         ('价格<BB中轨', below_mid, 2),
                   ('MA7<MA25', ma_bear, 2),       ('放量', vol_spike, 1)]

    rsi_extreme = ok(rsi_val) and (rsi_val > 90 or rsi_val < 10)
    rsi_w       = 4
    max_score   = sum(w for _, _, w in long_conds)          # = 14
    eff_max     = max_score - rsi_w if rsi_extreme else max_score
    threshold   = math.ceil(eff_max * (0.50 if rsi_extreme else 0.57))

    long_score  = sum(w for _, ok_, w in long_conds  if ok_)
    short_score = sum(w for _, ok_, w in short_conds if ok_)

    if long_score > short_score and long_score >= threshold:
        sig = 'STRONG LONG' if long_score / max_score >= 0.75 else 'LONG'
    elif short_score > long_score and short_score >= threshold:
        sig = 'STRONG SHORT' if short_score / max_score >= 0.75 else 'SHORT'
    else:
        sig = 'NEUTRAL'

    return sig, long_score, short_score, max_score


# ── 数据获取 ─────────────────────────────────────────────────────────────────

def fetch_klines_page(symbol, interval, start_ms, end_ms, limit=1000):
    base = 'https://data-api.binance.vision/api/v3/klines'
    url  = (f'{base}?symbol={symbol}&interval={interval}'
            f'&startTime={start_ms}&endTime={end_ms}&limit={limit}')
    req = urllib.request.Request(url, headers={'User-Agent': 'crypto-backtest/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = json.loads(resp.read())
    except Exception as e:
        print(f'  [WARN] API 错误: {e}')
        return []
    return [{'ts': int(b[0]), 'open': float(b[1]), 'high': float(b[2]),
             'low': float(b[3]), 'close': float(b[4]), 'volume': float(b[5])}
            for b in raw]


def fetch_all_klines(symbol, interval, start_ms, end_ms):
    """分页获取完整历史 K 线，并写入缓存"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    start_d  = datetime.fromtimestamp(start_ms / 1000).strftime('%Y%m%d')
    end_d    = datetime.fromtimestamp(end_ms   / 1000).strftime('%Y%m%d')
    cache_f  = CACHE_DIR / f'{symbol}_{interval}_{start_d}_{end_d}.json'

    if cache_f.exists():
        print(f'  [CACHE] {cache_f.name}')
        with open(cache_f, 'r') as f:
            return json.load(f)

    print(f'  [API]   {symbol} {interval} {start_d}~{end_d} ...', end=' ', flush=True)
    all_bars = []
    cur = start_ms
    while cur < end_ms:
        page = fetch_klines_page(symbol, interval, cur, end_ms)
        if not page:
            break
        all_bars.extend(page)
        if page[-1]['ts'] >= end_ms or len(page) < 1000:
            break
        cur = page[-1]['ts'] + 1
        time.sleep(0.15)

    # 去重 + 升序
    seen = {}
    for b in all_bars:
        seen[b['ts']] = b
    all_bars = sorted(seen.values(), key=lambda x: x['ts'])

    print(f'{len(all_bars)} bars')
    with open(cache_f, 'w') as f:
        json.dump(all_bars, f)
    return all_bars


# ── 回测引擎 ─────────────────────────────────────────────────────────────────

def run_backtest(kdata, symbol, initial_capital=INITIAL_CAPITAL):
    """
    逐根 K 线模拟交易
    入场: 信号变化时，下一根 K 线开盘价入场
    出场: TP / SL (用 high/low 检测) / 超时 12H / 信号反转
    """
    closes = [k['close'] for k in kdata]
    n      = len(kdata)

    equity       = initial_capital
    equity_curve = [equity]    # 每根 K 线结束后的权益
    trades       = []
    position     = None        # {dir, signal, entry_price, entry_idx, tp, sl, hold_bars}
    prev_signal  = 'NEUTRAL'
    pending_entry = None       # 下一根 K 线执行

    for i in range(n):
        bar = kdata[i]

        # ── Step 1: 执行上一轮挂单 ──────────────────────────────
        if pending_entry is not None:
            sig_type = pending_entry['signal']
            params   = TRADE_PARAMS[sig_type]
            ep       = bar['open']          # 挂单以当前 K 线开盘价成交

            if params['dir'] == 'LONG':
                tp_price = ep * (1 + params['tp'])
                sl_price = ep * (1 - params['sl'])
            else:
                tp_price = ep * (1 - params['tp'])
                sl_price = ep * (1 + params['sl'])

            position = {
                'dir':        params['dir'],
                'signal':     sig_type,
                'entry_price': ep,
                'entry_idx':   i,
                'tp':          tp_price,
                'sl':          sl_price,
                'hold_bars':   params['hold_bars'],
            }
            pending_entry = None

        # ── Step 2: 检查持仓出场 ────────────────────────────────
        if position is not None:
            p = position
            exited      = False
            exit_price  = None
            exit_reason = None

            if p['dir'] == 'LONG':
                # SL 和 TP 同一根 K 线都命中时，保守假设 SL 先触发
                sl_hit = bar['low']  <= p['sl']
                tp_hit = bar['high'] >= p['tp']
                if sl_hit and tp_hit:
                    exit_price, exit_reason = p['sl'], 'SL'
                elif sl_hit:
                    exit_price, exit_reason = p['sl'], 'SL'
                elif tp_hit:
                    exit_price, exit_reason = p['tp'], 'TP'
            else:  # SHORT
                sl_hit = bar['high'] >= p['sl']
                tp_hit = bar['low']  <= p['tp']
                if sl_hit and tp_hit:
                    exit_price, exit_reason = p['sl'], 'SL'
                elif sl_hit:
                    exit_price, exit_reason = p['sl'], 'SL'
                elif tp_hit:
                    exit_price, exit_reason = p['tp'], 'TP'

            # 超时
            if not exited and (i - p['entry_idx']) >= p['hold_bars']:
                exit_price, exit_reason = bar['close'], 'TIMEOUT'

            if exit_price is not None:
                exited = True

            if exited:
                ep = p['entry_price']
                if p['dir'] == 'LONG':
                    ret = (exit_price - ep) / ep
                else:
                    ret = (ep - exit_price) / ep

                pnl    = equity * ret
                equity += pnl

                bar_ts  = kdata[i]['ts']
                e_ts    = kdata[p['entry_idx']]['ts']
                trades.append({
                    'symbol':       symbol,
                    'dir':          p['dir'],
                    'signal':       p['signal'],
                    'entry_ts':     e_ts,
                    'exit_ts':      bar_ts,
                    'entry_price':  round(ep, 4),
                    'exit_price':   round(exit_price, 4),
                    'exit_reason':  exit_reason,
                    'ret_pct':      round(ret * 100, 4),
                    'pnl':          round(pnl, 4),
                    'equity_after': round(equity, 4),
                })
                position = None

        # ── Step 3: 生成信号 ────────────────────────────────────
        sig, ls, ss, ms_val = calc_signal_at(closes, kdata, i)

        # ── Step 4: 信号变化时挂单 ──────────────────────────────
        if sig != prev_signal:
            # 如果有持仓且信号反转，立刻平仓
            if position is not None:
                p = position
                ep = p['entry_price']
                cp = bar['close']
                if p['dir'] == 'LONG':
                    ret = (cp - ep) / ep
                else:
                    ret = (ep - cp) / ep
                pnl = equity * ret
                equity += pnl
                trades.append({
                    'symbol':       symbol,
                    'dir':          p['dir'],
                    'signal':       p['signal'],
                    'entry_ts':     kdata[p['entry_idx']]['ts'],
                    'exit_ts':      bar['ts'],
                    'entry_price':  round(ep, 4),
                    'exit_price':   round(cp, 4),
                    'exit_reason':  'SIGNAL_FLIP',
                    'ret_pct':      round(ret * 100, 4),
                    'pnl':          round(pnl, 4),
                    'equity_after': round(equity, 4),
                })
                position = None

            # 新信号挂单（STRONG LONG 跳过）
            if sig in TRADE_PARAMS and i + 1 < n:
                pending_entry = {'signal': sig}

        prev_signal = sig
        equity_curve.append(equity)

    # 强制平仓（回测结束时仍持仓）
    if position is not None:
        p  = position
        ep = p['entry_price']
        cp = kdata[-1]['close']
        if p['dir'] == 'LONG':
            ret = (cp - ep) / ep
        else:
            ret = (ep - cp) / ep
        pnl = equity * ret
        equity += pnl
        trades.append({
            'symbol':       symbol,
            'dir':          p['dir'],
            'signal':       p['signal'],
            'entry_ts':     kdata[p['entry_idx']]['ts'],
            'exit_ts':      kdata[-1]['ts'],
            'entry_price':  round(ep, 4),
            'exit_price':   round(cp, 4),
            'exit_reason':  'END',
            'ret_pct':      round(ret * 100, 4),
            'pnl':          round(pnl, 4),
            'equity_after': round(equity, 4),
        })

    return trades, equity_curve


# ── 指标计算 ─────────────────────────────────────────────────────────────────

def calc_metrics(trades, equity_curve, initial_capital, kdata):
    """计算完整回测指标"""
    final_equity = equity_curve[-1]
    total_ret    = (final_equity - initial_capital) / initial_capital * 100

    # 年化收益 (以 6 个月数据估算)
    duration_years = len(kdata) / (365 * 24)
    ann_ret = ((final_equity / initial_capital) ** (1 / duration_years) - 1) * 100 if duration_years > 0 else 0

    # 最大回撤
    peak = initial_capital
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # 夏普比率 (基于小时级权益变动，年化)
    hourly_returns = []
    for j in range(1, len(equity_curve)):
        if equity_curve[j-1] > 0:
            hourly_returns.append((equity_curve[j] - equity_curve[j-1]) / equity_curve[j-1])
    sharpe = 0.0
    if len(hourly_returns) > 1:
        mu  = statistics.mean(hourly_returns)
        std = statistics.stdev(hourly_returns)
        if std > 0:
            sharpe = mu / std * math.sqrt(8760)   # 8760 小时/年

    # 交易统计
    n_trades   = len(trades)
    # TP命中率 (TP vs SL，对应 bot 原文声称的胜率)
    tp_trades  = [t for t in trades if t['exit_reason'] == 'TP']
    sl_trades  = [t for t in trades if t['exit_reason'] == 'SL']
    wins       = tp_trades
    losses     = [t for t in trades if t['pnl'] < 0]
    # TP vs SL win rate (bot 文档口径)
    tp_sl_denom = len(tp_trades) + len(sl_trades)
    win_rate    = len(tp_trades) / tp_sl_denom * 100 if tp_sl_denom else 0
    # 真实胜率 (所有盈利交易 / 总交易)
    profitable  = [t for t in trades if t['ret_pct'] > 0]
    true_win_rate = len(profitable) / n_trades * 100 if n_trades else 0

    gross_win  = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    gross_loss = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float('inf')

    # 平均收益
    avg_ret      = statistics.mean(t['ret_pct'] for t in trades) if trades else 0
    avg_win_ret  = statistics.mean(t['ret_pct'] for t in wins)   if wins   else 0
    avg_loss_ret = statistics.mean(t['ret_pct'] for t in losses) if losses else 0

    # 多空分布
    n_long  = sum(1 for t in trades if t['dir'] == 'LONG')
    n_short = sum(1 for t in trades if t['dir'] == 'SHORT')

    # 出场原因分布
    exit_dist = {}
    for t in trades:
        exit_dist[t['exit_reason']] = exit_dist.get(t['exit_reason'], 0) + 1

    # Buy-and-hold 对比
    if kdata:
        bh_ret = (kdata[-1]['close'] - kdata[0]['close']) / kdata[0]['close'] * 100
    else:
        bh_ret = 0.0

    return {
        'final_equity':   round(final_equity, 2),
        'total_ret':      round(total_ret, 2),
        'ann_ret':        round(ann_ret, 2),
        'max_dd':         round(max_dd, 2),
        'sharpe':         round(sharpe, 3),
        'n_trades':       n_trades,
        'win_rate':       round(win_rate, 1),       # TP vs SL 口径 (=bot 文档胜率)
        'true_win_rate':  round(true_win_rate, 1),  # 全部盈利笔数 / 总笔数
        'profit_factor':  round(profit_factor, 3) if profit_factor != float('inf') else 'Inf',
        'avg_ret':        round(avg_ret, 3),
        'avg_win_ret':    round(avg_win_ret, 3),
        'avg_loss_ret':   round(avg_loss_ret, 3),
        'n_long':         n_long,
        'n_short':        n_short,
        'exit_dist':      exit_dist,
        'bh_ret':         round(bh_ret, 2),
        'gross_win':      round(gross_win, 2),
        'gross_loss':     round(gross_loss, 2),
        'n_tp':           len(tp_trades),
        'n_sl':           len(sl_trades),
    }


# ── 报告生成 ─────────────────────────────────────────────────────────────────

LABEL = {'BTCUSDT': 'BTC/USDT', 'SOLUSDT': 'SOL/USDT', 'ETHUSDT': 'ETH/USDT'}

def print_report(results):
    print()
    print('=' * 80)
    print('  crypto-signal-bot 六个月回测报告  |  1H  |  BTC · SOL · ETH')
    print('=' * 80)

    # 核心指标对比表
    keys_order = [
        ('总收益率',         'total_ret',      '%',   True),
        ('年化收益率',       'ann_ret',        '%',   True),
        ('最大回撤',         'max_dd',         '%',   False),
        ('夏普比率',         'sharpe',         '',    True),
        ('胜率(TP/SL口径)', 'win_rate',       '%',   True),
        ('真实胜率(盈/总)', 'true_win_rate',  '%',   True),
        ('TP命中次数',       'n_tp',           '次',  True),
        ('SL触发次数',       'n_sl',           '次',  False),
        ('盈亏比',           'profit_factor',  '',    True),
        ('总交易次数',       'n_trades',       '次',  True),
        ('多/空次数',        None,             '',    None),
        ('平均交易收益',     'avg_ret',        '%',   True),
        ('平均盈利',         'avg_win_ret',    '%',   True),
        ('平均亏损',         'avg_loss_ret',   '%',   False),
        ('买持收益(BH)',     'bh_ret',         '%',   None),
        ('最终权益($)',      'final_equity',   '$',   True),
    ]

    syms = list(results.keys())
    col  = 18

    header = f"{'指标':<14}" + ''.join(f"{LABEL[s]:>{col}}" for s in syms)
    print(f'\n{header}')
    print('-' * (14 + col * len(syms)))

    for label, key, unit, higher_is_better in keys_order:
        vals = []
        raw  = []
        for s in syms:
            if key is None:
                v_str = f"{results[s]['metrics']['n_long']}L/{results[s]['metrics']['n_short']}S"
                vals.append(v_str)
                raw.append(0)
                continue
            v = results[s]['metrics'].get(key, 0)
            raw.append(float(str(v).replace('Inf', '9999')) if isinstance(v, (int, float)) else 0)
            if unit == '%':
                if key in ('max_dd',):            # 回撤不显示符号
                    vals.append(f'{v:.2f}%' if isinstance(v, float) else f'{v}%')
                else:                              # 其他带符号
                    vals.append(f'{v:+.2f}%' if isinstance(v, float) else f'{v}%')
            elif unit == '$':
                vals.append(f'${v:,.2f}' if isinstance(v, float) else f'${v}')
            elif unit == '次':
                vals.append(f'{v}次')
            else:
                vals.append(f'{v:.3f}' if isinstance(v, float) else str(v))

        # 标注最优值
        try:
            best_idx = raw.index(max(raw) if higher_is_better else min(raw)) if higher_is_better is not None else -1
        except:
            best_idx = -1

        row = f'{label:<18}'
        for idx, v in enumerate(vals):
            marker = ' *' if idx == best_idx else '  '
            row += f'{v + marker:>{col}}'
        print(row)

    # 出场原因分布
    print()
    print('出场原因分布:')
    all_reasons = set()
    for s in syms:
        all_reasons.update(results[s]['metrics']['exit_dist'].keys())

    reason_header = f"{'出场原因':<14}" + ''.join(f"{LABEL[s]:>{col}}" for s in syms)
    print(reason_header)
    print('-' * (14 + col * len(syms)))
    for reason in sorted(all_reasons):
        row = f'{reason:<14}'
        for s in syms:
            cnt = results[s]['metrics']['exit_dist'].get(reason, 0)
            row += f'{cnt:>{col}}'
        print(row)

    # 最近 5 笔交易样本（每个标的）
    print()
    for s in syms:
        trades = results[s]['trades']
        print(f'\n--- {LABEL[s]} 最近 5 笔交易 ---')
        if not trades:
            print('  (无交易)')
            continue
        print(f"  {'日期':<12} {'方向':<6} {'信号':<14} {'入场':>10} {'出场':>10} {'收益%':>8} {'原因':<12}")
        for t in trades[-5:]:
            dt  = datetime.fromtimestamp(t['entry_ts'] / 1000).strftime('%m-%d %H:%M')
            print(f"  {dt:<12} {t['dir']:<6} {t['signal']:<14} "
                  f"${t['entry_price']:>9,.2f} ${t['exit_price']:>9,.2f} "
                  f"{t['ret_pct']:>+7.2f}%  {t['exit_reason']:<12}")

    # 综合评价
    print()
    print('=' * 80)
    print('综合评价:')
    for s in syms:
        m = results[s]['metrics']
        verdict = []
        if m['sharpe'] > 1.0:
            verdict.append('夏普>1 风险调整收益良好')
        elif m['sharpe'] > 0:
            verdict.append('夏普正值 有超额收益迹象')
        else:
            verdict.append('夏普负值 策略跑输无风险')

        if m['win_rate'] > 55:
            verdict.append(f"胜率{m['win_rate']}%强")
        elif m['win_rate'] > 45:
            verdict.append(f"胜率{m['win_rate']}%适中")
        else:
            verdict.append(f"胜率{m['win_rate']}%偏低")

        bh_gap = m['total_ret'] - m['bh_ret']
        if bh_gap > 0:
            verdict.append(f"跑赢买持{bh_gap:+.1f}pp")
        else:
            verdict.append(f"跑输买持{bh_gap:+.1f}pp")

        print(f'  {LABEL[s]}: {" | ".join(verdict)}')

    print()


def save_markdown_report(results, path):
    lines = []
    lines.append('# crypto-signal-bot 六个月回测报告')
    lines.append(f'> 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  ')
    lines.append(f'> 策略来源: https://github.com/yunya1991/crypto-signal-bot  ')
    lines.append(f'> 周期: 1H  |  初始资金: ${INITIAL_CAPITAL:,.0f}  |  时间窗口: 过去6个月\n')

    lines.append('## 核心指标对比\n')
    syms = list(results.keys())
    lines.append('| 指标 | ' + ' | '.join(LABEL[s] for s in syms) + ' |')
    lines.append('|------|' + '|'.join(['------'] * len(syms)) + '|')

    metrics_rows = [
        ('总收益率',     'total_ret',     lambda v: f'{v:+.2f}%'),
        ('年化收益率',   'ann_ret',       lambda v: f'{v:+.2f}%'),
        ('最大回撤',     'max_dd',        lambda v: f'{v:.2f}%'),
        ('夏普比率',     'sharpe',        lambda v: f'{v:.3f}'),
        ('胜率',         'win_rate',      lambda v: f'{v:.1f}%'),
        ('盈亏比',       'profit_factor', lambda v: f'{v}'),
        ('总交易次数',   'n_trades',      lambda v: f'{v}'),
        ('多/空次数',    None,            None),
        ('平均交易收益', 'avg_ret',       lambda v: f'{v:+.3f}%'),
        ('买持对比(BH)', 'bh_ret',        lambda v: f'{v:+.2f}%'),
        ('最终权益',     'final_equity',  lambda v: f'${v:,.2f}'),
    ]

    for label, key, fmt in metrics_rows:
        if key is None:
            vals = [f"{results[s]['metrics']['n_long']}L / {results[s]['metrics']['n_short']}S"
                    for s in syms]
        else:
            vals = [fmt(results[s]['metrics'][key]) for s in syms]
        lines.append(f'| {label} | ' + ' | '.join(vals) + ' |')

    lines.append('\n## 出场原因分布\n')
    all_reasons = set()
    for s in syms:
        all_reasons.update(results[s]['metrics']['exit_dist'].keys())
    lines.append('| 出场原因 | ' + ' | '.join(LABEL[s] for s in syms) + ' |')
    lines.append('|---------|' + '|'.join(['------'] * len(syms)) + '|')
    for r in sorted(all_reasons):
        vals = [str(results[s]['metrics']['exit_dist'].get(r, 0)) for s in syms]
        lines.append(f'| {r} | ' + ' | '.join(vals) + ' |')

    lines.append('\n## 策略说明\n')
    lines.append('- **信号来源**: 与 btc_signal_bot.py 指标完全一致（SMA7/25, MACD12/26/9, RSI14, BB20, Volume）')
    lines.append('- **入场条件**: 信号发生变化时，下一根K线开盘价入场；STRONG LONG 信号跳过')
    lines.append('- **LONG**: TP +2.0%, SL -1.5%, 最长持有 12H')
    lines.append('- **SHORT / STRONG SHORT**: TP +2.0%/+1.5%, SL -1.5%, 最长持有 12H')
    lines.append('- **出场优先级**: TP/SL (按K线high/low判断) > 超时12H > 信号反转')
    lines.append('- **资金管理**: 100%仓位复利（每笔交易使用全部当前权益）')
    lines.append('\n## 规范差异备注\n')
    lines.append('- 回测使用Binance公开历史K线，与信号机器人实时数据一致')
    lines.append('- TP/SL采用悲观假设：同一根K线同时触发时，SL优先')

    Path(path).write_text('\n'.join(lines), encoding='utf-8')
    print(f'Markdown 报告: {path}')


# ── 主程序 ───────────────────────────────────────────────────────────────────

def main():
    # 时间范围: 过去 6 个月
    now_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=30 * MONTHS_BACK)).timestamp() * 1000)

    print('=' * 70)
    print(f'  crypto-signal-bot 回测  |  1H  |  过去{MONTHS_BACK}个月')
    print(f'  {datetime.fromtimestamp(start_ms/1000):%Y-%m-%d}  →  {datetime.now():%Y-%m-%d}')
    print('=' * 70)

    results = {}
    for sym in SYMBOLS:
        print(f'\n[{LABEL[sym]}]')
        kdata = fetch_all_klines(sym, INTERVAL, start_ms, now_ms)
        if len(kdata) < 50:
            print(f'  数据不足，跳过 {sym}')
            continue

        print(f'  数据: {len(kdata)} 根K线  '
              f'{datetime.fromtimestamp(kdata[0]["ts"]/1000):%Y-%m-%d} ~ '
              f'{datetime.fromtimestamp(kdata[-1]["ts"]/1000):%Y-%m-%d}')

        trades, equity_curve = run_backtest(kdata, sym, INITIAL_CAPITAL)
        metrics = calc_metrics(trades, equity_curve, INITIAL_CAPITAL, kdata)

        print(f'  交易: {metrics["n_trades"]}笔  '
              f'胜率: {metrics["win_rate"]}%  '
              f'总收益: {metrics["total_ret"]:+.2f}%  '
              f'夏普: {metrics["sharpe"]:.3f}  '
              f'最大回撤: {metrics["max_dd"]:.2f}%')

        results[sym] = {'trades': trades, 'equity_curve': equity_curve,
                        'metrics': metrics, 'kdata': kdata}

    if not results:
        print('无结果，退出')
        return

    print_report(results)

    # 保存报告
    out_dir = Path('C:/tmp/test_results')
    out_dir.mkdir(parents=True, exist_ok=True)
    save_markdown_report(results, out_dir / 'crypto_backtest_report.md')

    # 保存完整 JSON
    json_out = {}
    for s, r in results.items():
        json_out[s] = {
            'metrics': r['metrics'],
            'trades_count': len(r['trades']),
            'trades_sample': r['trades'][-10:],   # 最近10笔
        }
    with open(out_dir / 'crypto_backtest_results.json', 'w', encoding='utf-8') as f:
        json.dump(json_out, f, ensure_ascii=False, indent=2)
    print(f'JSON 结果: {out_dir}/crypto_backtest_results.json')


if __name__ == '__main__':
    main()
