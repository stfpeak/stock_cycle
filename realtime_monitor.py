"""
实时涨停监控
============
功能：
    1. 使用easyquotation获取全市场实时数据
    2. 监控涨停板，发现后分析所在概念题材
    3. 展示近15个交易日相关概念的涨停股票
    4. 按涨停时间排序，树形结构展示

使用方法：
    python realtime_monitor.py
"""

import easyquotation
import pandas as pd
import json
import os
from datetime import datetime
import time
import sys

# 导入现有模块
from stock_dashboard_v3 import (
    load_all_concept_data,
    build_stock_to_concepts_index,
    build_concept_to_stocks_index,
    ZT_POOL_DIR,
    CONCEPT_STOCK_DIR,
    CLS_CONCEPT_FILE,
    KPL_CONCEPT_FILE
)

# 涨停板颜色标记
ZT_COLOR_RED = '\033[91m'
ZT_COLOR_GREEN = '\033[92m'
ZT_COLOR_YELLOW = '\033[93m'
ZT_COLOR_RESET = '\033[0m'


def is_market_open():
    """判断当前是否在交易时间内（简单判断）"""
    now = datetime.now()
    h, m = now.hour, now.minute
    weekday = now.weekday()
    if weekday >= 5:  # 周末
        return False
    # 9:25~15:00 大致判断（简化）
    if h < 9 or h >= 15:
        return False
    if h == 9 and m < 25:
        return False
    return True


def is_trading_day():
    """判断今天是否是交易日，基于交易日历文件"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    calendar_file = os.path.join(script_dir, "data", "trade_calendar_2026.json")
    today_str = datetime.now().strftime('%Y-%m-%d')

    try:
        with open(calendar_file, 'r', encoding='utf-8') as f:
            trading_days = json.load(f)
        return today_str in trading_days
    except Exception:
        # 如果文件读取失败，回退到简单判断（检查是否周末）
        return datetime.now().weekday() < 5


def get_realtime_zt_stocks_from_spot(realtime_codes=None):
    """
    使用全市场实时快照检测涨停股票
    realtime_codes: 已被纳入监控的股票代码集合，用于追踪首次封板时间
    """
    try:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 正在获取全市场实时数据...")
        import easyquotation
        sina = easyquotation.use('sina')
        all_stock = sina.market_snapshot(prefix=True)

        zt_stocks = []
        now_str = datetime.now().strftime('%Y%m%d')

        for code, data in all_stock.items():
            if not isinstance(data, dict):
                continue

            name = data.get('name', '')
            if not name:
                continue

            price = data.get('now', 0)
            yesterday_close = data.get('close', 0)

            if price <= 0 or yesterday_close <= 0:
                continue

            change_pct = (price - yesterday_close) / yesterday_close * 100

            # 判断是否涨停
            if code.startswith('60') or code.startswith('688'):
                zt_threshold = 9.8
            else:
                zt_threshold = 19.5

            if change_pct >= zt_threshold:
                # 追踪首次封板时间
                if realtime_codes is not None:
                    if code not in realtime_codes:
                        realtime_codes[code] = {
                            'name': name,
                            'first_zt_time': data.get('time', ''),
                            'price': price,
                            'change_pct': change_pct
                        }
                    else:
                        # 已跟踪的，更新最新价格
                        realtime_codes[code]['price'] = price
                        realtime_codes[code]['change_pct'] = change_pct

                zt_time = data.get('time', '')
                zt_stocks.append({
                    'code': code,
                    'name': name,
                    'price': price,
                    'change_pct': change_pct,
                    'zt_time': zt_time[:5] if zt_time else '',
                    'first_zt_time_raw': zt_time.replace(':', ''),
                    'lianban': 1  # 实时快照无法确定连板数
                })

        # 按涨停时间排序
        zt_stocks.sort(key=lambda x: x['first_zt_time_raw'])
        return zt_stocks

    except Exception as e:
        print(f"实时快照获取失败: {e}")
        return []


def get_realtime_zt_stocks(realtime_tracked_codes=None):
    """
    获取当日涨停的股票
    - 盘中：优先使用全市场快照实时检测涨停，结合已跟踪股票的首板时间
    - 盘后或失败：使用akshare涨停池（完整数据）
    """
    market_open = is_market_open()

    if market_open:
        # 盘中：使用实时快照检测（传入已跟踪股票以保留首板时间）
        zt_stocks = get_realtime_zt_stocks_from_spot(realtime_tracked_codes)
        if zt_stocks:
            return zt_stocks

    # 尝试涨停池
    try:
        import akshare as ak
        today = datetime.now().strftime('%Y%m%d')
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 正在获取当日涨停池...")
        df = ak.stock_zt_pool_em(date=today)

        zt_stocks = []
        for _, row in df.iterrows():
            code = str(int(row['代码'])).zfill(6)
            name = row['名称']
            price = row['最新价']
            change_pct = row['涨跌幅']
            first_zt_time = str(row['首次封板时间']) if pd.notna(row['首次封板时间']) else ''
            lianban = row['连板数']

            if len(first_zt_time) >= 6:
                zt_time_fmt = first_zt_time[:2] + ':' + first_zt_time[2:4] + ':' + first_zt_time[4:6]
            else:
                zt_time_fmt = first_zt_time

            zt_stocks.append({
                'code': code,
                'name': name,
                'price': price,
                'change_pct': change_pct,
                'zt_time': zt_time_fmt,
                'first_zt_time_raw': first_zt_time,
                'lianban': lianban
            })

        zt_stocks.sort(key=lambda x: x['first_zt_time_raw'])
        return zt_stocks

    except Exception as e:
        print(f"涨停池获取失败: {e}")
        # 最后 fallback：再试实时快照
        return get_realtime_zt_stocks_from_spot()


def load_zt_history(days=15):
    """加载近N日涨停历史数据"""
    all_data = []
    today_str = datetime.now().strftime('%Y%m%d')

    for i in range(days):
        from datetime import timedelta
        date = (datetime.now() - timedelta(days=i)).strftime('%Y%m%d')
        file_path = os.path.join(ZT_POOL_DIR, f"{date}.csv")
        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path)
                df['交易日期'] = date
                all_data.append(df)
            except Exception as e:
                print(f"读取 {date} 数据失败: {e}")

    if all_data:
        df = pd.concat(all_data, ignore_index=True)
        df['代码_str'] = df['代码'].apply(lambda x: str(int(x)).zfill(6) if pd.notna(x) else '')
        # 去除名称中的空格以便匹配概念数据
        df['名称_clean'] = df['名称'].str.replace(' ', '', regex=False)
        return df
    return None


def load_concept_data():
    """加载财联社和开盘啦的概念数据（不使用同花顺）"""
    concept_data = {'cls': {}, 'kpl': {}, 'ths': {}}

    # 财联社
    if os.path.exists(CLS_CONCEPT_FILE):
        try:
            with open(CLS_CONCEPT_FILE, 'r', encoding='utf-8') as f:
                concept_data['cls'] = json.load(f)
        except Exception as e:
            print(f"财联社概念加载失败: {e}")

    # 开盘啦
    if os.path.exists(KPL_CONCEPT_FILE):
        try:
            with open(KPL_CONCEPT_FILE, 'r', encoding='utf-8') as f:
                concept_data['kpl'] = json.load(f)
        except Exception as e:
            print(f"开盘啦概念加载失败: {e}")

    # 不再加载同花顺概念数据
    return concept_data


def find_stock_concepts(stock_name, concept_data):
    """查找股票所属的概念（财联社+开盘啦）"""
    cls_concepts = []
    kpl_concepts = []

    # 去除空格以便匹配
    stock_name_clean = stock_name.replace(' ', '')

    # 财联社 - 使用reverse映射
    cls_reverse = concept_data.get('cls', {}).get('reverse', {})
    # 尝试多种匹配方式
    for name_key in [stock_name_clean, stock_name]:
        if name_key in cls_reverse:
            cls_concepts = cls_reverse[name_key]
            if isinstance(cls_concepts, str):
                cls_concepts = [cls_concepts]
            break

    # 开盘啦 - 遍历forward
    kpl_forward = concept_data.get('kpl', {}).get('forward', {})
    for main_concept, sub_data in kpl_forward.items():
        if isinstance(sub_data, dict):
            for sub_concept, stocks in sub_data.items():
                for stock in stocks:
                    if isinstance(stock, dict):
                        name = stock.get('name', '')
                    else:
                        name = stock
                    name_clean = name.replace(' ', '')
                    if name_clean == stock_name_clean or name == stock_name:
                        kpl_concepts.append({
                            'concept': main_concept,
                            'sub': sub_concept
                        })
        elif isinstance(sub_data, list):
            for stock in sub_data:
                if isinstance(stock, dict):
                    name = stock.get('name', '')
                else:
                    name = stock
                name_clean = name.replace(' ', '')
                if name_clean == stock_name_clean or name == stock_name:
                    kpl_concepts.append({
                        'concept': main_concept,
                        'sub': ''
                    })

    return {
        'cls': cls_concepts,
        'kpl': kpl_concepts,
        'ths': []
    }


def find_related_zt_stocks(stock_name, concept_info, df_zt_history, today_zt_change=None):
    """查找相关概念的涨停股票
    today_zt_change: 今日涨停股票的涨跌幅字典，用于显示
    """
    related_stocks = []

    if df_zt_history is None:
        return related_stocks

    if today_zt_change is None:
        today_zt_change = {}

    # 收集所有概念（字符串形式）
    # cls: 直接字符串列表
    # kpl/ths: {'concept': '主概念', 'sub': '细分'} -> '主概念::细分'
    all_concepts_set = set()
    all_concepts_set.update(concept_info.get('cls', []))

    for c in concept_info.get('kpl', []):
        concept = c.get('concept', '')
        sub_list = c.get('sub', [])
        if isinstance(sub_list, list):
            for sub in sub_list:
                all_concepts_set.add(concept + '::' + sub if sub else concept)
        elif sub_list:
            all_concepts_set.add(concept + '::' + sub_list)

    # KPL concepts (THS已移除)
    for c in concept_info.get('kpl', []):
        concept = c.get('concept', '')
        sub_list = c.get('sub', [])
        if isinstance(sub_list, list):
            for sub in sub_list:
                all_concepts_set.add(concept + '::' + sub if sub else concept)
        elif sub_list:
            all_concepts_set.add(concept + '::' + sub_list)

    if not all_concepts_set:
        return related_stocks

    # 查找近15日涨停的相关概念股票
    matched_names = set()

    for _, row in df_zt_history.iterrows():
        name = row.get('名称', '')
        name_clean = row.get('名称_clean', name)  # 去除空格后的名称用于匹配
        code = row.get('代码_str', '')
        lianban = row.get('连板数', 1)
        trade_date = row.get('交易日期', '')

        if name_clean == stock_name:
            continue  # 排除自身

        # 先按名称匹配（同概念板块）
        if name_clean not in matched_names:
            matched_names.add(name_clean)
            related_stocks.append({
                'name': name,  # 保留原始名称用于显示
                'code': code,
                'lianban': lianban,
                'is_today': trade_date == datetime.now().strftime('%Y%m%d'),
                'change_pct': today_zt_change.get(name_clean)
            })

    # 按今日涨停优先，然后连板数排序
    related_stocks.sort(key=lambda x: (not x['is_today'], -x['lianban']))

    return related_stocks


def format_zt_time(zt_time_str):
    """格式化涨停时间
    支持格式: 92500 -> 09:25:00, 09:25:00 -> 09:25:00, 092503 -> 09:25:03
    """
    if not zt_time_str:
        return ''

    # 如果已经是 HH:MM:SS 或 HH:MM 格式，直接返回前5位
    if ':' in zt_time_str:
        return zt_time_str[:5]

    # 如果是纯数字格式如 92500 或 092500
    if zt_time_str.isdigit():
        # 补齐到6位
        zt_time_str = zt_time_str.zfill(6)
        return zt_time_str[:2] + ':' + zt_time_str[2:4] + ':' + zt_time_str[4:6]

    return zt_time_str


def print_zt_tree(zt_stock, related_stocks, realtime_prices):
    """打印涨停树形结构"""
    name = zt_stock['name']
    code = zt_stock['code']
    change_pct = zt_stock['change_pct']
    zt_time = format_zt_time(zt_stock.get('zt_time', ''))

    # 计算实际涨停时间
    if zt_time:
        time_display = f"@{zt_time}"
    else:
        time_display = ""

    print(f"\n{ZT_COLOR_RED}◆ {name}({code}) 今日涨幅:{change_pct:+.2f}% {time_display}{ZT_COLOR_RESET}")

    if related_stocks:
        # 按今日涨停和非今日分组
        today_zt = [s for s in related_stocks if s.get('is_today')]
        other_zt = [s for s in related_stocks if not s.get('is_today')]

        if today_zt:
            print(f"  {ZT_COLOR_YELLOW}└─ 今日涨停:{ZT_COLOR_RESET}")
            for s in today_zt[:10]:  # 最多显示10只
                lianban_tag = f"{s['lianban']}板" if s['lianban'] > 1 else "首板"
                # 获取实时价格
                price_info = realtime_prices.get(s['code'], {})
                now_price = price_info.get('now', 0)
                pct = price_info.get('percent', 0)
                if pct > 0:
                    pct_color = ZT_COLOR_RED
                elif pct < 0:
                    pct_color = ZT_COLOR_GREEN
                else:
                    pct_color = ''

                if now_price > 0:
                    print(f"    {ZT_COLOR_YELLOW}  ├─{ZT_COLOR_RESET} {s['name']}({s['code']}) {lianban_tag} 现价:{now_price} {pct_color}{pct:+.2f}%{ZT_COLOR_RESET}")
                else:
                    print(f"    {ZT_COLOR_YELLOW}  ├─{ZT_COLOR_RESET} {s['name']}({s['code']}) {lianban_tag}")

        if other_zt:
            print(f"  {ZT_COLOR_YELLOW}└─ 近期涨停:{ZT_COLOR_RESET}")
            for s in other_zt[:15]:  # 最多显示15只
                lianban_tag = f"{s['lianban']}板" if s['lianban'] > 1 else "首板"
                print(f"    {ZT_COLOR_YELLOW}  ├─{ZT_COLOR_RESET} {s['name']}({s['code']}) {lianban_tag}")


def generate_report(zt_stocks, concept_data, df_zt_history, realtime_prices):
    """
    生成报告：涨停股票按时间排序 → 展示概念 → 概念下近15日涨停股票（带今日涨跌幅）
    浅色主题UI
    """
    from collections import defaultdict
    now = datetime.now()
    date_str = now.strftime('%Y年%m月%d日')
    time_str = now.strftime('%H:%M:%S')

    stock_to_concepts = build_stock_to_concepts_index(concept_data)

    # 今日日期字符串
    today_str = now.strftime('%Y%m%d')

    # 构建15日涨停的名称→今日涨跌幅映射（从zt_stocks当前数据）
    today_zt_change = {}
    for zt in zt_stocks:
        today_zt_change[zt['name']] = zt['change_pct']

    # 15日涨停名称集合
    zt_15d_names = set()
    if df_zt_history is not None:
        for _, row in df_zt_history.iterrows():
            name = row.get('名称', '')
            if name:
                zt_15d_names.add(name.strip())

    # 构建CLS概念→近15日涨停股票列表（仅CLS）
    cls_forward = concept_data.get('cls', {}).get('forward', {})
    concept_15d_stocks = defaultdict(list)  # concept -> [stock_name, ...]

    for concept, stocks in cls_forward.items():
        for stock in stocks:
            if isinstance(stock, dict):
                sname = stock.get('name', '')
            else:
                sname = stock
            if sname in zt_15d_names:
                concept_15d_stocks[concept].append(sname)

    # 按涨停时间排序（全局）
    zt_stocks_sorted = sorted(zt_stocks, key=lambda x: x.get('zt_time', ''))

    # 构建股票名称→代码映射（从涨停历史和今日涨停数据）
    name_to_code = {}
    for zt in zt_stocks:
        name_to_code[zt['name']] = zt['code']
    if df_zt_history is not None:
        for _, row in df_zt_history.iterrows():
            name = row.get('名称', '')
            code = row.get('代码_str', '')
            if name and code and name not in name_to_code:
                name_to_code[name] = code

    # 构建股票名称→概念映射（用于弹窗显示）
    name_to_concepts = {}
    for stock_name, info in stock_to_concepts.items():
        cls_list = list(set(info.get('cls', [])))
        kpl_concepts = []
        for kpl_item in info.get('kpl', []):
            concept = kpl_item.get('concept', '')
            sub_list = kpl_item.get('sub', [])
            if isinstance(sub_list, list) and sub_list:
                for sub in sub_list:
                    kpl_concepts.append(concept + '::' + sub)
            else:
                kpl_concepts.append(concept)
        all_concepts = cls_list + kpl_concepts
        if all_concepts:
            name_to_concepts[stock_name] = all_concepts

    # 构建概念→涨停股票完整数据（用于走势看板）
    # 格式: concept -> [{code, name, zt_count, zt_dates, is_today}, ...]
    concept_stock_data = defaultdict(list)
    if df_zt_history is not None:
        # 按名称汇总涨停次数和日期
        stock_zt_info = defaultdict(lambda: {'dates': set(), 'code': ''})
        for _, row in df_zt_history.iterrows():
            name = row.get('名称', '')
            code = row.get('代码_str', '')
            date = row.get('交易日期', '')
            if name and date:
                stock_zt_info[name]['dates'].add(date)
                if not stock_zt_info[name]['code'] and code:
                    stock_zt_info[name]['code'] = code

        # 填充概念数据（使用CLS概念映射）
        for concept, stock_names in concept_15d_stocks.items():
            for sname in stock_names:
                info = stock_zt_info.get(sname, {})
                code = info.get('code', name_to_code.get(sname, ''))
                dates = sorted(info.get('dates', []))
                is_today = today_str in dates
                concept_stock_data[concept].append({
                    'name': sname,
                    'code': code,
                    'zt_count': len(dates),
                    'zt_dates': dates,
                    'is_today': is_today
                })
            # 按今日涨停优先，然后按涨停次数排序
            concept_stock_data[concept].sort(key=lambda x: (not x['is_today'], -x['zt_count']))

    html_style = """
    <style>
        :root {
            --blue: #3182ce;
            --blue-600: #2b6cb0;
            --blue-700: #2c5282;
            --gray-100: #f7fafc;
            --gray-200: #e2e8f0;
            --gray-400: #a0aec0;
            --gray-500: #718096;
            --gray-600: #4a5568;
            --gray-800: #2d3748;
            --green: #38a169;
            --light-orange: #fff8f0;
            --light-blue: #f0f7ff;
        }
        * { box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f6fa; color: #333; margin: 0; padding: 20px; }
        .container { max-width: 1400px; margin: 0 auto; }
        .header { background: linear-gradient(135deg, #1a365d 0%, #2c5282 50%, #3182ce 100%); border-radius: 12px; padding: 30px 25px; margin-bottom: 20px; box-shadow: 0 4px 16px rgba(0,0,0,0.12); position: relative; overflow: hidden; }
        .header::before { content: ''; position: absolute; top: -50%; right: -10%; width: 300px; height: 300px; background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, transparent 70%); border-radius: 50%; }
        .header::after { content: ''; position: absolute; bottom: -30%; left: 5%; width: 200px; height: 200px; background: radial-gradient(circle, rgba(255,255,255,0.08) 0%, transparent 70%); border-radius: 50%; }
        .header h1 { color: #fff; font-size: 2em; margin: 0 0 8px 0; font-weight: 700; text-align: center; text-shadow: 0 2px 8px rgba(0,0,0,0.3); letter-spacing: 2px; }
        .header .sub { color: rgba(255,255,255,0.85); font-size: 1em; text-align: center; display: block; }
        .summary { display: flex; gap: 20px; justify-content: center; margin-top: 16px; position: relative; z-index: 1; }
        .summary-item { background: rgba(255,255,255,0.15); padding: 8px 24px; border-radius: 20px; color: #fff; font-weight: bold; border: 1px solid rgba(255,255,255,0.25); backdrop-filter: blur(4px); }
        .zt-table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
        .zt-table-wrapper { overflow-x: auto; }
        .zt-table th { text-align: left; padding: 12px 14px; background: var(--gray-100); color: var(--gray-600); font-size: 0.85em; border-bottom: 2px solid var(--gray-200); font-weight: 600; }
        .zt-table td { padding: 10px 14px; border-bottom: 1px solid var(--gray-200); vertical-align: top; }
        .zt-table tr:last-child td { border-bottom: none; }
        .zt-table tr:hover { background: #fafbfc; }
        .zt-time { color: var(--blue-600); font-weight: bold; min-width: 60px; }
        /* 涨停板表头行深色背景 */
        .zt-stock-header td { background: #dce3f5 !important; font-weight: 600; }
        .zt-stock-header .zt-time { color: var(--blue-600); font-weight: bold; }
        .zt-stock-header .zt-pct { color: #e53e3e; font-weight: bold; }
        .clickable-name { color: var(--blue-600); font-weight: bold; cursor: pointer; }
        .clickable-name:hover { color: var(--blue-700); text-decoration: underline; }
        .zt-lianban { display: inline-block; padding: 1px 6px; border-radius: 10px; font-size: 0.75em; margin-left: 4px; }
        .lb-1 { background: #e8f5e9; color: #2e7d32; }
        .lb-2 { background: #fff3e0; color: #b7791f; }
        .lb-3 { background: #ebf8ff; color: var(--blue-600); }
        .zt-pct { color: #e53e3e; font-weight: bold; min-width: 60px; }
        .zt-concepts { color: var(--gray-500); font-size: 0.85em; line-height: 1.6; }
        .concept-label { color: var(--blue-600); font-weight: bold; margin-right: 4px; }
        .concept-chip { display: inline-block; background: #ebf8ff; color: var(--blue-600); padding: 1px 6px; border-radius: 8px; font-size: 0.8em; margin: 1px 2px; cursor: pointer; }
        .concept-chip:hover { background: var(--blue-600); color: #fff; }
        /* 相关涨停股票区 */
        .related-section { border-radius: 6px; overflow: hidden; margin-bottom: 6px; }
        /* 概念隔断标题行 - 视觉分隔每个涨停股区域 */
        .concept-section-header { display: flex; align-items: center; gap: 8px; padding: 6px 10px; }
        .concept-section-header .concept-name { font-weight: 600; color: var(--gray-700, #374151); font-size: 0.82em; }
        .toggle-trend-btn { background: var(--blue-600); color: #fff; border: none; border-radius: 4px; padding: 3px 10px; font-size: 0.78em; cursor: pointer; margin-left: auto; }
        .toggle-trend-btn:hover { background: var(--blue-700); }
        .toggle-trend-btn.active { background: var(--gray-600); }
        .related-stock-item { display: inline-block; background: #fff; border: 1px solid var(--gray-200); padding: 1px 6px; border-radius: 10px; margin: 2px; color: var(--gray-600); font-size: 0.85em; cursor: pointer; }
        .related-stock-item:hover { border-color: var(--blue-600); color: var(--blue-600); }
        .related-stock-item.today { background: #ebf8ff; border-color: #90cdf4; color: var(--blue-600); font-weight: bold; }
        .concept-stocks-list { padding: 6px 10px; flex-wrap: wrap; }
        .no-related { color: var(--gray-400); font-size: 0.8em; }
        .refresh-note { text-align: center; color: var(--gray-500); font-size: 0.8em; margin-top: 20px; }
        /* 刷新提示横幅 */
        .refresh-banner { position: fixed; top: 0; left: 0; right: 0; background: linear-gradient(135deg, #e53e3e 0%, #c53030 100%); color: white; padding: 12px 20px; display: flex; align-items: center; justify-content: center; gap: 15px; z-index: 999; box-shadow: 0 2px 10px rgba(0,0,0,0.2); }
        .refresh-banner.show { display: flex; }
        .refresh-btn { background: white; color: #c53030; border: none; padding: 6px 16px; border-radius: 4px; cursor: pointer; font-weight: 600; }
        .refresh-btn:hover { background: #f7f7f7; }
        .dismiss-btn { background: transparent; color: white; border: 1px solid white; padding: 5px 15px; border-radius: 4px; cursor: pointer; }
        .dismiss-btn:hover { background: rgba(255,255,255,0.2); }
        /* 走势看板 */
        .trend-board { display: none; padding: 10px; }
        .trend-board.show { display: block; }
        .trend-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }
        .trend-card { background: #fff; border-radius: 4px; text-align: center; overflow: hidden; border: 1px solid var(--gray-200); }
        .trend-card:hover { border-color: var(--blue-400); }
        .trend-kline { width: 100%; height: 150px; object-fit: contain; cursor: pointer; display: block; background: #fff; }
        .trend-kline:hover { opacity: 0.9; }
        .trend-info { padding: 5px 4px; font-size: 0.78em; color: var(--gray-600); background: #fff; }
        .trend-info .trend-name { font-weight: 600; color: var(--gray-800); }
        .trend-info .trend-zt { color: #e53e3e; font-weight: 600; }
        .trend-info .trend-dates { color: var(--gray-400); font-size: 0.85em; margin-top: 1px; }
        /* K线弹窗样式 */
        .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; justify-content: center; align-items: center; }
        .modal-content { background: #fff; border-radius: 12px; max-width: 800px; width: 90%; max-height: 90vh; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.2); }
        .modal-header { display: flex; justify-content: space-between; align-items: center; padding: 15px 20px; border-bottom: 1px solid var(--gray-200); }
        .modal-header h3 { margin: 0; color: var(--gray-800); font-size: 1.1em; }
        .close-btn { font-size: 1.5em; cursor: pointer; color: var(--gray-500); line-height: 1; }
        .close-btn:hover { color: var(--gray-800); }
        .modal-tabs { display: flex; padding: 10px 20px; gap: 10px; border-bottom: 1px solid var(--gray-200); }
        .tab-btn { padding: 6px 16px; border: 1px solid var(--gray-200); background: #fff; border-radius: 6px; cursor: pointer; font-size: 0.9em; color: var(--gray-600); }
        .tab-btn:hover { border-color: var(--blue-600); color: var(--blue-600); }
        .tab-btn.active { background: var(--blue-600); color: #fff; border-color: var(--blue-600); }
        .modal-body { padding: 15px; text-align: center; }
        #kline-info { text-align: left; font-size: 0.9em; color: var(--gray-600); line-height: 1.6; }
        #kline-info .info-pct { font-weight: bold; color: #e53e3e; margin-left: 8px; }
        #kline-info .concept-tag { display: inline-block; background: #ebf8ff; color: var(--blue-600); padding: 1px 6px; border-radius: 6px; font-size: 0.85em; margin: 2px; }
        #kline-img { max-width: 100%; max-height: 500px; object-fit: contain; }
    </style>"""

    html_lines = [
        "<!DOCTYPE html>",
        "<html lang='zh-CN'>",
        "<head>",
        "<meta charset='UTF-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        "<title>实时涨停监控 - " + date_str + "</title>",
        html_style,
        "</head>",
        "<body>",
        "<div class='header'>",
        "<h1>实时涨停监控</h1>",
        "<div class='sub'>" + date_str + " " + time_str + "</div>",
        "<div class='summary'>",
        "<div class='summary-item'>涨停股票: " + str(len(zt_stocks)) + "</div>",
        "<div class='summary-item'>近15日涨停: " + str(len(zt_15d_names)) + "</div>",
        "</div>",
        "</div>",
        "<div id='refresh-banner' class='refresh-banner' style='display:none;'>",
        "    <span id='refresh-msg'></span>",
        "    <button onclick='location.reload()' class='refresh-btn'>刷新页面</button>",
        "    <button onclick='dismissRefresh()' class='dismiss-btn'>暂不刷新</button>",
        "</div>",
        "<div class='zt-table-wrapper'><table class='zt-table'><thead><tr><th>涨停时间</th><th>股票</th><th>涨幅</th><th>概念</th></tr></thead><tbody>"
    ]

    md_lines = [
        "# 实时涨停监控",
        "**" + date_str + " " + time_str + "**  共 **" + str(len(zt_stocks)) + "** 只涨停",
        "",
        "---",
        ""
    ]

    for zt in zt_stocks_sorted:
        name = zt['name']
        code = zt['code']
        change_pct = zt['change_pct']
        zt_time = zt.get('zt_time', '')
        lianban = zt.get('lianban', 1)
        lb_class = 'lb-' + str(min(lianban, 3))
        lb_tag = str(lianban) + '板' if lianban > 1 else '首板'

        concept_info = stock_to_concepts.get(name, {'cls': [], 'kpl': [], 'ths': []})
        cls_list = list(set(concept_info.get('cls', [])))  # 去重

        # 收集所有概念用于显示（CLS + KPL）
        all_display_concepts = []
        all_display_concepts.extend(cls_list)
        for kpl_item in concept_info.get('kpl', []):
            concept = kpl_item.get('concept', '')
            sub_list = kpl_item.get('sub', [])
            if isinstance(sub_list, list) and sub_list:
                for sub in sub_list:
                    all_display_concepts.append(concept + '::' + sub)
            else:
                all_display_concepts.append(concept)

        # 构建概念标签HTML
        if all_display_concepts:
            chips = ['<span class="concept-chip">' + c + '</span>' for c in all_display_concepts]
            concept_chips_html = ''.join(chips)
        else:
            concept_chips_html = '<span class="no-related">-</span>'

        # 构建每个涨停股票行（表头行深色背景）
        html_lines.append("<tr class='zt-stock-header'>")
        html_lines.append("<td class='zt-time'>" + zt_time + "</td>")
        html_lines.append("<td><span class='clickable-name' onclick=\"openKLineModal('" + code + "', '" + name.replace("'", "\\'") + "')\">" + name + "</span><span class='zt-lianban " + lb_class + "'>" + lb_tag + "</span></td>")
        html_lines.append("<td class='zt-pct'>" + ('%+.2f' % change_pct) + "%</td>")
        html_lines.append("<td class='zt-concepts'>" + concept_chips_html + "</td>")
        html_lines.append("</tr>")

        # 概念详情行
        if all_display_concepts:
            related_html = ""
            for concept in all_display_concepts:
                board_stocks = concept_stock_data.get(concept, [])
                board_stocks_filtered = [s for s in board_stocks if s['name'] != name]
                if not board_stocks_filtered:
                    continue

                concept_id = str(hash(concept + str(zt_stocks_sorted.index(zt))))[:8]
                board_data = json.dumps(board_stocks_filtered, ensure_ascii=False)

                stock_tags = []
                for s in board_stocks_filtered:
                    pct = today_zt_change.get(s['name'])
                    if pct is not None:
                        css_cls = 'related-stock-item today'
                        pct_str = ('%+.2f%%' % pct)
                    else:
                        css_cls = 'related-stock-item'
                        pct_str = ''
                    stock_tags.append("<span class='" + css_cls + "' onclick=\"openKLineModal('" + s['code'] + "', '" + s['name'].replace("'", "\\'") + "')\">" + s['name'] + pct_str + "</span>")

                related_html += "<div class='related-section'>"
                related_html += "<div class='concept-section-header'>"
                related_html += "<span class='concept-name'>" + concept + "</span>"
                related_html += "<button class='toggle-trend-btn' id='btn-" + concept_id + "' onclick=\"toggleTrendBoard('" + concept_id + "')\">📈 走势</button>"
                related_html += "</div>"
                related_html += "<div class='concept-stocks-list' id='list-" + concept_id + "'>" + ''.join(stock_tags) + "</div>"
                related_html += "<div class='trend-board' id='board-" + concept_id + "'>"
                related_html += "<div class='trend-grid' id='grid-" + concept_id + "'></div>"
                related_html += "<div class='concept-stocks-data' id='cdata-" + concept_id + "' style='display:none'>" + board_data + "</div>"
                related_html += "</div>"
                related_html += "</div>"

            if related_html:
                html_lines.append("<tr><td colspan='4' style='padding:0 12px;'>" + related_html + "</td></tr>")

        # Markdown
        md_lines.append("| " + zt_time + " | " + name + "(" + lb_tag + ") | " + ('%+.2f' % change_pct) + "% | " + (", ".join(all_display_concepts) if all_display_concepts else "-") + " |")

    html_lines.extend([
        "</tbody>",
        "</table>",
        "</div>",
        "<div class='refresh-note'>如有新增涨停，页面将自动提示刷新</div>",
        "</body>",
        "</html>",
        "",
        "<!-- K线图弹窗 -->",
        "<div id='kline-modal' class='modal-overlay' onclick='closeKLineModal()'>",
        "    <div class='modal-content' onclick='event.stopPropagation()'>",
        "        <div class='modal-header'>",
        "            <h3 id='kline-title'>股票名称</h3>",
        "            <span class='close-btn' onclick='closeKLineModal()'>&times;</span>",
        "        </div>",
        "        <div class='modal-tabs'>",
        "            <button class='tab-btn active' onclick=\"switchKLineTab('min', this)\">分时</button>",
        "            <button class='tab-btn' onclick=\"switchKLineTab('daily', this)\">日K</button>",
        "        </div>",
        "        <div class='modal-body'>",
        "            <div id='kline-info' style='margin-bottom:10px;text-align:left;max-height:80px;overflow-y:auto;'></div>",
        "            <img id='kline-img' src='' alt='K线图加载中...'>",
        "        </div>",
        "    </div>",
        "</div>",
        "",
        "<script>",
        "var currentStockCode = '';",
        "var currentStockPrefix = '';",
        "",
        "function getSinaCode(code) {",
        "    if (!code) return '';",
        "    if (code.startsWith('60') || code.startsWith('688')) return 'sh' + code;",
        "    if (code.startsWith('00') || code.startsWith('30')) return 'sz' + code;",
        "    if (code.startsWith('4') || code.startsWith('8')) return 'bj' + code;",
        "    return 'sh' + code;",
        "}",
        "",
        "function openKLineModal(code, name, event) {",
        "    if (!code && name) {",
        "        var nameMap = " + json.dumps(name_to_code) + ";",
        "        code = nameMap[name] || '';",
        "    }",
        "    currentStockCode = code;",
        "    currentStockPrefix = getSinaCode(code);",
        "    document.getElementById('kline-title').innerText = name + (code ? ' (' + code + ')' : '');",
        "",
        "    // 显示概念和涨跌幅",
        "    var conceptMap = " + json.dumps(name_to_concepts) + ";",
        "    var changeMap = " + json.dumps(today_zt_change) + ";",
        "    var concepts = conceptMap[name] || [];",
        "    var pct = changeMap[name];",
        "    var infoHtml = '';",
        "    if (concepts.length > 0) {",
        "        infoHtml += '概念: ';",
        "        concepts.forEach(function(c) {",
        "            infoHtml += '<span class=\"concept-tag\">' + c + '</span>';",
        "        });",
        "    }",
        "    if (pct !== undefined) {",
        "        infoHtml += '<span class=\"info-pct\">今日涨幅: ' + (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%</span>';",
        "    }",
        "    document.getElementById('kline-info').innerHTML = infoHtml;",
        "",
        "    document.getElementById('kline-modal').style.display = 'flex';",
        "    switchKLineTab('daily');",
        "    if (event) event.stopPropagation();",
        "}",
        "",
        "function closeKLineModal() {",
        "    document.getElementById('kline-modal').style.display = 'none';",
        "    document.getElementById('kline-img').src = '';",
        "}",
        "",
        "function switchKLineTab(type, elm) {",
        "    document.querySelectorAll('.tab-btn').forEach(function(btn) { btn.classList.remove('active'); });",
        "    if (elm) {",
        "        elm.classList.add('active');",
        "    } else {",
        "        var tabs = document.querySelectorAll('.tab-btn');",
        "        if (type === 'min') tabs[0] && tabs[0].classList.add('active');",
        "        if (type === 'daily') tabs[1] && tabs[1].classList.add('active');",
        "    }",
        "    var t = Math.floor(new Date().getTime() / 10000);",
        "    var url = 'http://image.sinajs.cn/newchart/' + type + '/n/' + currentStockPrefix + '.png?' + t;",
        "    var img = document.getElementById('kline-img');",
        "    if (img) {",
        "        img.style.opacity = '0.5';",
        "        img.alt = 'K线图加载中...';",
        "        img.onload = function() { img.style.opacity = '1'; };",
        "        img.onerror = function() { img.alt = '获取失败，请重试'; img.style.opacity = '1'; };",
        "        img.src = url;",
        "    }",
        "}",
        "",
        "function toggleTrendBoard(conceptId) {",
        "    var board = document.getElementById('board-' + conceptId);",
        "    var btn = document.getElementById('btn-' + conceptId);",
        "    if (!board) return;",
        "    if (board.classList.contains('show')) {",
        "        board.classList.remove('show');",
        "        if (btn) { btn.classList.remove('active'); btn.textContent = '📈 走势'; }",
        "    } else {",
        "        board.classList.add('show');",
        "        if (btn) { btn.classList.add('active'); btn.textContent = '📈 收起'; }",
        "        renderTrendBoardCards(conceptId);",
        "    }",
        "}",
        "",
        "function renderTrendBoardCards(conceptId) {",
        "    var dataEl = document.getElementById('cdata-' + conceptId);",
        "    var grid = document.getElementById('grid-' + conceptId);",
        "    if (!dataEl || !grid || grid.children.length > 0) return;",
        "    var stocks;",
        "    try { stocks = JSON.parse(dataEl.textContent); }",
        "    catch(e) { return; }",
        "    if (!stocks || stocks.length === 0) return;",
        "    var html = '';",
        "    stocks.forEach(function(s) {",
        "        var prefix = s.code.startsWith('6') ? 'sh' : 'sz';",
        "        var ts = Math.floor(Date.now() / 10000);",
        "        var ztDatesStr = (s.zt_dates || []).map(function(d) { return d.substring(4,6) + '/' + d.substring(6,8); }).join(', ');",
        "        html += '<div class=\"trend-card\">';",
        "        html += '<img class=\"trend-kline\" src=\"http://image.sinajs.cn/newchart/daily/n/' + prefix + s.code + '.png?_t=' + ts + '\" onclick=\"openKLineModal(\\'' + s.code + '\\', \\'' + (s.name||'').replace(/'/g, \"\\\\'\") + '\\')\" alt=\"' + s.name + '\" onerror=\"this.src=\\'data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 200 150%22><rect fill=%22%23f5f5f5%22 width=%22200%22 height=%22150%22/><text x=%2250%22 y=%2275%22 fill=%22%23999%22 font-size=%2212%22 text-anchor=%22middle%22>加载失败</text></svg>\\'\">';",
        "        html += '<div class=\"trend-info\"><div class=\"trend-name\">' + s.name + ' <span style=\"color:#666;font-weight:normal\">(' + s.code + ')</span></div>';",
        "        html += '<div class=\"trend-zt\">' + s.zt_count + '次涨停</div>';",
        "        html += '<div class=\"trend-dates\">' + ztDatesStr + '</div></div></div>';",
        "    });",
        "    grid.innerHTML = html;",
        "}",
        "",
        "window.toggleTrendBoard = toggleTrendBoard;",
        "window.renderTrendBoardCards = renderTrendBoardCards;",
        "",
        "// 刷新检测功能",
        "var currentStockCount = " + str(len(zt_stocks)) + ";",
        "var currentStockNames = " + json.dumps([zt['name'] for zt in zt_stocks]) + ";",
        "var checkInterval = 30000; // 每30秒检查一次",
        "var lastFileSize = document.body.innerHTML.length;",
        "",
        "function dismissRefresh() {",
        "    document.getElementById('refresh-banner').classList.remove('show');",
        "}",
        "",
        "function checkForUpdates() {",
        "    fetch('realtime_report.html?t=' + Date.now())",
        "        .then(function(response) { return response.text(); })",
        "        .then(function(html) {",
        "            // 解析新报告的股票数量",
        "            var match = html.match(/涨停股票: (\\d+)/);",
        "            if (match) {",
        "                var newCount = parseInt(match[1], 10);",
        "                if (newCount > currentStockCount) {",
        "                    document.getElementById('refresh-msg').innerHTML = '检测到新增涨停股票！当前 ' + currentStockCount + ' 只 → 新增后 ' + newCount + ' 只';",
        "                    document.getElementById('refresh-banner').classList.add('show');",
        "                }",
        "            }",
        "        })",
        "        .catch(function(e) {",
        "            console.log('检查更新失败:', e);",
        "        });",
        "}",
        "",
        "// 启动定时检查",
        "setInterval(checkForUpdates, checkInterval);",
        "",
        "</script>"
    ])

    md_lines.append("")
    md_lines.append("---")
    md_lines.append("* 注：近15日同概念涨停股票显示在涨停股下方，今日有涨停的标红")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    md_file = os.path.join(script_dir, "realtime_report.md")
    html_file = os.path.join(script_dir, "realtime_report.html")

    with open(md_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(md_lines))

    with open(html_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(html_lines))

    return md_file, html_file

    

def main():
    print("=" * 60)
    print("实时涨停监控")
    print("=" * 60)

    # 检查今天是否是交易日
    today_is_trading_day = is_trading_day()
    market_is_open = is_market_open()

    if not today_is_trading_day:
        print("\n今天不是交易日（非周末或节假日）")
        print("将基于历史涨停数据生成报告")
    else:
        print(f"\n今天 是交易日")
        print(f"当前市场状态: {'开盘中' if market_is_open else '已闭市'}")

    # 加载概念数据
    print("\n加载概念数据...")
    concept_data = load_concept_data()
    print(f"  财联社: {len(concept_data.get('cls', {}).get('forward', {}))} 个概念")
    print(f"  开盘啦: {len(concept_data.get('kpl', {}).get('forward', {}))} 个概念")

    # 加载涨停历史
    print("\n加载涨停历史数据...")
    df_zt_history = load_zt_history(15)
    if df_zt_history is not None:
        print(f"  近15日涨停记录: {len(df_zt_history)} 条")

    # 非交易日：直接生成报告并退出
    if not today_is_trading_day:
        print("\n" + "=" * 60)
        print("非交易日模式：生成历史涨停报告")
        print("=" * 60)

        # 获取昨日收盘数据（从zt_pool读取最近一个有数据的交易日）
        from datetime import timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')

        # 查找最近的有效涨停数据
        script_dir = os.path.dirname(os.path.abspath(__file__))
        zt_file = os.path.join(script_dir, "data", "zt_pool", f"{yesterday}.csv")
        import glob
        all_zt_files = sorted(glob.glob(os.path.join(script_dir, "data", "zt_pool", "*.csv")))
        if all_zt_files:
            zt_file = all_zt_files[-1]  # 使用最新的涨停文件

        print(f"使用涨停数据: {zt_file}")

        try:
            df_yesterday_zt = pd.read_csv(zt_file)
            # 确保代码有6位前导零
            df_yesterday_zt['代码_str'] = df_yesterday_zt['代码'].apply(lambda x: str(int(x)).zfill(6) if pd.notna(x) else '')
            zt_stocks = []
            for _, row in df_yesterday_zt.iterrows():
                first_zt_time = str(int(row.get('首次封板时间', 0))) if pd.notna(row.get('首次封板时间')) else ''
                # 格式化时间 92500 -> 09:25:00, 092503 -> 09:25:03
                zt_time_fmt = first_zt_time.zfill(6)
                zt_time_fmt = zt_time_fmt[:2] + ':' + zt_time_fmt[2:4] + ':' + zt_time_fmt[4:6]
                # 去除名称中的空格以便匹配概念数据
                name = row.get('名称', '').replace(' ', '')
                zt_stocks.append({
                    'name': name,
                    'code': row.get('代码_str', ''),
                    'change_pct': float(row.get('涨跌幅', 0)),
                    'zt_time': zt_time_fmt,
                    'first_zt_time_raw': first_zt_time,
                })
            print(f"加载到 {len(zt_stocks)} 只涨停股票")
        except Exception as e:
            print(f"读取涨停数据失败: {e}")
            zt_stocks = []

        # 获取实时价格（模拟）
        sina = easyquotation.use('sina')
        all_stock = sina.market_snapshot(prefix=True)
        realtime_prices = {code: data for code, data in all_stock.items() if isinstance(data, dict)}

        # 构建today_zt_change
        today_zt_change = {}
        for zt in zt_stocks:
            today_zt_change[zt['name']] = zt['change_pct']

        # 处理所有涨停股票
        for zt in zt_stocks:
            concept_info = find_stock_concepts(zt['name'], concept_data)
            related = find_related_zt_stocks(zt['name'], concept_info, df_zt_history, today_zt_change)
            print_zt_tree(zt, related, realtime_prices)

        # 生成报告
        md_file, html_file = generate_report(zt_stocks, concept_data, df_zt_history, realtime_prices)
        print(f"\n报告已生成:")
        print(f"  Markdown: {md_file}")
        print(f"  HTML: {html_file}")
        print("\n非交易日模式，程序退出")
        return

    # 交易日模式：持续监控
    processed_zt = set()
    realtime_tracked_codes = {}

    print("\n开始监控 (按 Ctrl+C 退出)...")
    print("-" * 60)

    while True:
        try:
            # 获取实时涨停股票
            zt_stocks = get_realtime_zt_stocks(realtime_tracked_codes)

            new_zt_count = 0
            for zt in zt_stocks:
                key = f"{zt['code']}_{zt['name']}"
                if key not in processed_zt:
                    processed_zt.add(key)
                    new_zt_count += 1

            if new_zt_count > 0:
                print(f"\n{'=' * 60}")
                print(f"发现 {new_zt_count} 只新涨停股票!")
                print(f"{'=' * 60}")

            # 获取实时价格数据
            sina = easyquotation.use('sina')
            all_stock = sina.market_snapshot(prefix=True)
            realtime_prices = {}
            for code, data in all_stock.items():
                if isinstance(data, dict):
                    realtime_prices[code] = data

            # 构建today_zt_change
            today_zt_change = {}
            for zt in zt_stocks:
                today_zt_change[zt['name']] = zt['change_pct']

            # 处理所有涨停股票
            for zt in zt_stocks:
                # 查找概念
                concept_info = find_stock_concepts(zt['name'], concept_data)

                # 查找相关涨停
                related = find_related_zt_stocks(zt['name'], concept_info, df_zt_history, today_zt_change)

                # 打印树形结构
                print_zt_tree(zt, related, realtime_prices)

            if zt_stocks:
                print(f"\n{'-' * 60}")
                print(f"当前涨停股票数: {len(zt_stocks)}")

            # 生成Markdown和HTML报告
            md_file, html_file = generate_report(zt_stocks, concept_data, df_zt_history, realtime_prices)
            print(f"\n报告已生成:")
            print(f"  Markdown: {md_file}")
            print(f"  HTML: {html_file}")

            # 每90秒刷新一次
            time.sleep(90)

        except KeyboardInterrupt:
            print("\n\n监控已停止")
            break
        except Exception as e:
            print(f"\n监控出错: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(10)


if __name__ == "__main__":
    main()
