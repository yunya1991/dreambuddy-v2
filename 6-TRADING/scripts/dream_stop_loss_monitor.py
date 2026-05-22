#!/usr/bin/env python3
"""
Dream-MultiSkill 动态止损监控器 v1.0
====================================
集成 dynamic_stop_loss.json 配置
定时检查持仓状态，触发阈值时执行相应动作

功能:
1. 读取 dynamic_stop_loss.json 配置
2. 获取当前持仓状态 (杠杆/UPL/持仓时间)
3. 检查存量持仓豁免状态
4. 根据触发条件执行动作
5. 支持 dry_run 模式（只检查不下单）

使用方法:
    python scripts/dream_stop_loss_monitor.py           # 检查+执行
    python scripts/dream_stop_loss_monitor.py --dry   # 仅检查不下单
    python scripts/dream_stop_loss_monitor.py --report  # 生成状态报告
"""

import requests
import json
import time
import hmac
import base64
import hashlib
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

# ==================== 配置 ====================
API_KEY = "f9d0221c-b26a-48eb-b248-88b3d600eccd"
SECRET_KEY = "05912564EBA86936B3E799138A5DA502"
PASSPHRASE = "Zjt@199107293419"
BASE_URL = "https://www.okx.com"
INST_ID = "BTC-USDT-SWAP"

CONFIG_PATH = os.path.expanduser("~/.workbuddy/config/dynamic_stop_loss.json")
REPORTS_DIR = "/Users/zhangjiangtao/WorkBuddy/20260415144304/reports"
TRADING_DIR = "/Users/zhangjiangtao/.workbuddy/skills/boss-secretary/reports/trading"

# ==================== OKX API ====================
def get_headers(method, path, body=""):
    ts = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
    msg = ts + method + path + body
    mac = hmac.new(SECRET_KEY.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256)
    sign = base64.b64encode(mac.digest()).decode('utf-8')
    return {
        'OK-ACCESS-KEY': API_KEY, 'OK-ACCESS-SIGN': sign,
        'OK-ACCESS-TIMESTAMP': ts, 'OK-ACCESS-PASSPHRASE': PASSPHRASE,
        'Content-Type': 'application/json'
    }

def okx_get(path, params=None):
    sign_path = path
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        sign_path = path + "?" + qs
    headers = get_headers("GET", sign_path)
    resp = requests.get(BASE_URL + path, params=params, headers=headers, timeout=15)
    return resp.json()

def okx_post(path, body_dict):
    body = json.dumps(body_dict)
    headers = get_headers("POST", path, body)
    resp = requests.post(BASE_URL + path, data=body, headers=headers, timeout=15)
    return resp.json()

# ==================== 配置读取 ====================
def load_stop_loss_config() -> Optional[Dict]:
    """读取动态止损配置"""
    if not os.path.exists(CONFIG_PATH):
        print(f"⚠️ 配置文件不存在: {CONFIG_PATH}")
        return None
    
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def is_legacy_position_grace_period(config: Dict, position_open_time: datetime) -> Tuple[bool, int]:
    """
    检查存量持仓是否在豁免期内
    返回: (is_grace_period, remaining_hours)
    """
    grace_period_hours = config.get('legacy_position_grace_period_hours', 24)
    config_update_time_str = config.get('last_updated', '2000-01-01T00:00:00')
    config_update_time = datetime.fromisoformat(config_update_time_str.replace('Z', '+00:00'))
    
    grace_end_time = config_update_time + timedelta(hours=grace_period_hours)
    now = datetime.now(timezone.utc)
    
    if now < grace_end_time:
        remaining = (grace_end_time - now).total_seconds() / 3600
        return True, int(remaining)
    return False, 0

# ==================== 持仓检查 ====================
def get_positions() -> List[Dict]:
    """获取当前持仓"""
    resp = okx_get("/api/v5/account/positions", {"instType": "SWAP"})
    if resp.get('code') != '0':
        print(f"❌ 获取持仓失败: {resp}")
        return []
    
    positions = []
    for p in resp.get('data', []):
        if float(p.get('pos', 0)) > 0 and p.get('instId') == INST_ID:
            positions.append(p)
    return positions

def get_leverage(inst_id: str, pos_side: str) -> int:
    """获取持仓杠杆"""
    resp = okx_get("/api/v5/account/leverage-info", {"instId": inst_id, "mgnMode": "cross"})
    if resp.get('code') != '0':
        return 1
    
    for l in resp.get('data', []):
        if l.get('posSide') == pos_side:
            return int(l.get('lever', 1))
    return 1

def get_position_age_hours(avgPx: str) -> float:
    """
    估算持仓时间
    注意: OKX API 不直接返回开仓时间，这里通过 avgPx 变化历史估算
    简化处理: 返回 0 表示无法确定 (需要外部传入)
    """
    # 实际使用时需要通过订单历史或外部记录获取
    return 0.0

# ==================== 触发检查 ====================
def check_leverage_breach(position: Dict, config: Dict, is_grace: bool) -> Optional[Dict]:
    """检查杠杆是否超限"""
    max_leverage = config.get('trigger_conditions', {}).get('max_leverage', 2.0)
    pos_side = position.get('posSide', 'long')
    leverage = get_leverage(position.get('instId'), pos_side)
    
    if leverage > max_leverage:
        # 检查存量持仓豁免
        if is_grace:
            for rule in config.get('stop_loss_rules', []):
                if rule.get('condition') == 'leverage > 2.0':
                    if rule.get('legacy_exempt', False):
                        return None  # 豁免中
        
        return {
            'trigger': 'leverage_breach',
            'leverage': leverage,
            'max_allowed': max_leverage,
            'action': config.get('auto_actions', {}).get('leverage_breach', {}),
            'is_grace': is_grace
        }
    return None

def check_upl_breach(position: Dict, config: Dict) -> Optional[Dict]:
    """检查浮亏是否超限"""
    max_upl_loss = config.get('trigger_conditions', {}).get('max_upl_loss_usdt', -5.0)
    upl = float(position.get('upl', 0))
    
    if upl < max_upl_loss:
        return {
            'trigger': 'upl_breach',
            'upl': upl,
            'threshold': max_upl_loss,
            'action': config.get('auto_actions', {}).get('upl_breach', {}),
            'is_grace': False  # UPL 触发不豁免
        }
    return None

def check_position_age(position: Dict, config: Dict) -> Optional[Dict]:
    """检查持仓时间"""
    # 这里需要外部传入持仓时间，暂用简化逻辑
    return None

# ==================== 执行动作 ====================
def execute_reduction(position: Dict, action: Dict, dry_run: bool = True) -> Dict:
    """
    执行降仓动作
    action: {"action": "CLOSE_PARTIAL", "size_percent": 50, ...}
    """
    inst_id = position.get('instId')
    pos_side = position.get('posSide')
    current_pos = int(position.get('pos', 0))
    close_pct = action.get('size_percent', 50) / 100
    close_qty = max(1, int(current_pos * close_pct))
    
    result = {
        'action': 'CLOSE_PARTIAL',
        'direction': 'sell' if pos_side == 'long' else 'buy',
        'qty': close_qty,
        'inst_id': inst_id,
        'pos_side': pos_side,
        'dry_run': dry_run
    }
    
    if dry_run:
        result['status'] = 'DRY_RUN'
        print(f"  [DRY] 平仓 {close_qty} 张 ({int(close_pct*100)}%)")
        return result
    
    # 实际执行市价平仓
    resp = okx_post("/api/v5/trade/order", {
        "instId": inst_id,
        "tdMode": "cross",
        "side": result['direction'],
        "ordType": "market",
        "sz": str(close_qty),
        "posSide": pos_side
    })
    
    result['response'] = resp
    result['status'] = 'SUCCESS' if resp.get('code') == '0' else 'FAILED'
    print(f"  平仓结果: {resp.get('code')} {resp.get('msg')}")
    
    return result

def execute_stop_loss(position: Dict, action: Dict, dry_run: bool = True) -> Dict:
    """
    执行设置止损动作
    action: {"action": "SET_STOP_LOSS", "trigger_offset_percent": 1.5, ...}
    """
    inst_id = position.get('instId')
    pos_side = position.get('posSide')
    avgPx = float(position.get('avgPx', 0))
    current_pos = int(position.get('pos', 0))
    offset_pct = action.get('trigger_offset_percent', 1.5) / 100
    
    # 计算止损价
    if pos_side == 'long':
        stop_price = avgPx * (1 - offset_pct)
    else:
        stop_price = avgPx * (1 + offset_pct)
    
    sl_side = 'sell' if pos_side == 'long' else 'buy'
    
    result = {
        'action': 'SET_STOP_LOSS',
        'trigger_price': round(stop_price, 2),
        'qty': current_pos,
        'inst_id': inst_id,
        'pos_side': pos_side,
        'dry_run': dry_run
    }
    
    if dry_run:
        result['status'] = 'DRY_RUN'
        print(f"  [DRY] 设置止损触发价 ${result['trigger_price']}")
        return result
    
    # 实际执行条件单
    resp = okx_post("/api/v5/trade/order-algo", {
        "instId": inst_id,
        "tdMode": "cross",
        "side": sl_side,
        "ordType": "conditional",
        "sz": str(current_pos),
        "posSide": pos_side,
        "slTriggerPx": str(round(stop_price, 2)),
        "slOrdPx": "-1",
        "slTriggerPxType": "mark"
    })
    
    result['response'] = resp
    result['status'] = 'SUCCESS' if resp.get('code') == '0' else 'FAILED'
    print(f"  止损设置结果: {resp.get('code')} {resp.get('msg')}")
    
    return result

def trigger_manual_review(position: Dict, reason: str, dry_run: bool = True) -> Dict:
    """触发人工确认"""
    result = {
        'action': 'FORCE_REVIEW',
        'reason': reason,
        'position': {
            'instId': position.get('instId'),
            'posSide': position.get('posSide'),
            'qty': position.get('pos'),
            'avgPx': position.get('avgPx'),
            'upl': position.get('upl')
        },
        'dry_run': dry_run,
        'status': 'PENDING_MANUAL_REVIEW'
    }
    
    print(f"  ⚠️ 需要人工确认: {reason}")
    return result

# ==================== 主监控逻辑 ====================
def monitor_positions(dry_run: bool = True) -> Dict:
    """主监控流程"""
    config = load_stop_loss_config()
    if not config:
        return {'status': 'NO_CONFIG', 'alerts': []}
    
    print(f"\n{'='*60}")
    print(f"🔍 动态止损监控 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"模式: {'🔎 DRY_RUN (仅检查)' if dry_run else '⚡ LIVE (执行动作)'}")
    
    # 获取持仓
    positions = get_positions()
    if not positions:
        print("\n✅ 无持仓，跳过检查")
        return {'status': 'NO_POSITIONS', 'alerts': []}
    
    results = []
    alerts = []
    
    for pos in positions:
        print(f"\n📊 持仓: {pos.get('instId')} | {pos.get('posSide')} | "
              f"数量:{pos.get('pos')} | 入场价:${float(pos.get('avgPx', 0)):.2f} | "
              f"浮亏:${float(pos.get('upl', 0)):.2f}")
        
        # 检查存量持仓豁免
        is_grace, remaining = is_legacy_position_grace_period(config, datetime.now())
        if is_grace:
            print(f"  ⏳ 存量持仓豁免中，剩余 {remaining}h")
        
        # 检查各项触发条件
        triggers = []
        
        # 1. 杠杆超限
        lever_breach = check_leverage_breach(pos, config, is_grace)
        if lever_breach:
            triggers.append(lever_breach)
            alerts.append({
                'level': '🔴',
                'type': '杠杆超限',
                'data': lever_breach
            })
        
        # 2. 浮亏超限
        upl_breach = check_upl_breach(pos, config)
        if upl_breach:
            triggers.append(upl_breach)
            alerts.append({
                'level': '🔴',
                'type': '浮亏超限',
                'data': upl_breach
            })
        
        # 3. 持仓时间告警
        pos_age = check_position_age(pos, config)
        if pos_age:
            triggers.append(pos_age)
            alerts.append({
                'level': '🟡',
                'type': '持仓超时',
                'data': pos_age
            })
        
        if not triggers:
            print("  ✅ 无触发条件")
            results.append({'position': pos, 'triggers': [], 'actions': []})
            continue
        
        # 执行动作
        actions = []
        for trigger in triggers:
            action_config = trigger.get('action', {})
            action_type = action_config.get('action')
            
            print(f"\n  📋 触发: {trigger['trigger']} | 动作: {action_type}")
            
            if action_type == 'CLOSE_PARTIAL':
                result = execute_reduction(pos, action_config, dry_run)
                actions.append(result)
            elif action_type == 'SET_STOP_LOSS':
                result = execute_stop_loss(pos, action_config, dry_run)
                actions.append(result)
            elif action_type == 'FORCE_REVIEW':
                result = trigger_manual_review(pos, trigger.get('description', ''), dry_run)
                actions.append(result)
        
        results.append({
            'position': pos,
            'triggers': triggers,
            'actions': actions
        })
    
    # 输出汇总
    print(f"\n{'='*60}")
    print("📋 检查汇总")
    print(f"{'='*60}")
    print(f"持仓数量: {len(positions)}")
    print(f"触发数量: {len(alerts)}")
    
    for alert in alerts:
        print(f"  {alert['level']} {alert['type']}: {alert['data']}")
    
    return {
        'status': 'COMPLETE',
        'positions_checked': len(positions),
        'alerts': alerts,
        'results': results,
        'dry_run': dry_run,
        'timestamp': datetime.now().isoformat()
    }

# ==================== 报告生成 ====================
def generate_report(monitor_result: Dict) -> str:
    """生成监控报告"""
    report_path = os.path.join(
        REPORTS_DIR,
        f"stop_loss_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    )
    
    report = f"""# 🔍 动态止损监控报告

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**模式**: {'🔎 DRY_RUN' if monitor_result.get('dry_run') else '⚡ LIVE'}

---

## 📊 检查汇总

| 项目 | 值 |
|:---|:---|
| 检查状态 | {monitor_result.get('status')} |
| 持仓数量 | {monitor_result.get('positions_checked', 0)} |
| 触发告警 | {len(monitor_result.get('alerts', []))} |

---

## 🚨 告警详情

"""
    
    for alert in monitor_result.get('alerts', []):
        data = alert.get('data', {})
        report += f"""### {alert['level']} {alert['type']}

| 项目 | 值 |
|:---|:---|
| 触发类型 | {data.get('trigger', 'N/A')} |
| 详细数据 | {json.dumps(data, indent=2)} |

"""
    
    if not monitor_result.get('alerts'):
        report += "\n✅ 无触发告警\n"
    
    report += f"""---

## 📎 配置信息

配置文件: `{CONFIG_PATH}`

"""
    
    with open(report_path, 'w') as f:
        f.write(report)
    
    print(f"\n📄 报告已生成: {report_path}")
    return report_path

# ==================== 主入口 ====================
def main():
    parser = argparse.ArgumentParser(description='动态止损监控器')
    parser.add_argument('--dry', action='store_true', help='仅检查不下单')
    parser.add_argument('--report', action='store_true', help='生成报告')
    parser.add_argument('--config', type=str, help='指定配置文件路径')
    args = parser.parse_args()
    
    # 自定义配置路径
    if args.config:
        global CONFIG_PATH
        CONFIG_PATH = args.config
    
    dry_run = args.dry or True  # 默认 dry_run
    
    result = monitor_positions(dry_run=dry_run)
    
    if args.report:
        generate_report(result)
    
    # 返回退出码
    if result.get('alerts'):
        sys.exit(1)  # 有告警
    sys.exit(0)

if __name__ == "__main__":
    main()
