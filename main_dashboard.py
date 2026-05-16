"""
涨停板看板主程序
================
功能：
    1. 获取近20日涨停股票
    2. 获取近30日K线数据
    3. 6种分类展示（3连板+、2连板、单次涨停、正常非连续、炸板、创业板10%+）
    4. K线图表展示

使用方法：
    python main_dashboard.py
    python main_dashboard.py --fetch-kline
    python main_dashboard.py --open-browser
"""

import adata
import akshare as ak
import pandas as pd
import json
import os
from datetime import datetime, timedelta
import argparse
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from kline_database import KlineDB

# ========== 路径配置 ==========
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
ZT_POOL_DIR = os.path.join(DATA_DIR, "zt_pool")
KLINE_DATA_DIR = os.path.join(DATA_DIR, "kline_data")
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports")
CONCEPT_STOCK_DIR = os.path.join(DATA_DIR, "concept_stock")
THS_CONCEPT_FILE = os.path.join(CONCEPT_STOCK_DIR, "ths_concept_stock.json")

os.makedirs(KLINE_DATA_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

# 创业板/科创版代码前缀
GEM_MARKET_CODES = {'300', '301', '688'}

# ========== 工具函数 ==========

def get_beijing_now():
    return datetime.now()

def get_today_str():
    return get_beijing_now().strftime('%Y%m%d')

def get_trading_dates(days=30):
    """获取近N个交易日期"""
    today_str = get_today_str()
    cache_file = os.path.join(DATA_DIR, 'trade_calendar_2026.json')

    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                trading_dates = json.load(f)
            trading_dates = [d.replace('-', '') for d in trading_dates]
            trading_dates = [d for d in trading_dates if d <= today_str][::-1]
            if len(trading_dates) >= days:
                return trading_dates[:days]
        except Exception:
            pass

    try:
        df = adata.stock.info.trade_calendar(year=2026)
        df_trading = df[df['trade_status'] == 1]
        trading_dates = df_trading['trade_date'].astype(str).tolist()
        trading_dates = [d.replace('-', '') for d in trading_dates]
        trading_dates = [d for d in trading_dates if d <= today_str][::-1]
        return trading_dates[:days] if len(trading_dates) >= days else trading_dates
    except Exception as e:
        print(f"获取交易日历失败: {e}")
        dates = []
        current = datetime.now()
        while len(dates) < days:
            if current.weekday() < 5:
                dates.append(current.strftime('%Y%m%d'))
            current -= timedelta(days=1)
        return dates

def is_gem_or_star(code):
    code_str = str(code)
    return code_str.startswith('300') or code_str.startswith('301') or code_str.startswith('688')

# ========== K线数据获取 ==========

def fetch_kline_for_stock(stock_code, start_date, end_date=None):
    """获取单只股票日K线数据 - 优先adata，失败则用Sina API"""
    # 转换日期格式
    if len(start_date) == 8:
        start_date_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    else:
        start_date_fmt = start_date

    if end_date is None:
        end_date_fmt = get_beijing_now().strftime('%Y-%m-%d')
    elif len(end_date) == 8:
        end_date_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
    else:
        end_date_fmt = end_date

    # 计算需要的天数
    start_dt = datetime.strptime(start_date_fmt, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date_fmt, '%Y-%m-%d')
    days = (end_dt - start_dt).days + 1

    # 优先使用adata
    try:
        df = adata.stock.market.get_market(
            stock_code=stock_code,
            start_date=start_date_fmt,
            k_type=1,
            adjust_type=1
        )
        if df is not None and not df.empty and len(df) > 0:
            return df
    except Exception as e:
        pass

    # 使用Sina API获取数据
    try:
        import requests
        # 判断交易所前缀
        if stock_code.startswith('6'):
            symbol = f'sh{stock_code}'
        else:
            symbol = f'sz{stock_code}'

        url = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
        params = {
            'symbol': symbol,
            'scale': '240',  # 日K
            'ma': '5',
            'datalen': str(days)
        }
        headers = {
            'Referer': 'https://finance.sina.com.cn/',
            'User-Agent': 'Mozilla/5.0'
        }
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code == 200:
            import json
            data = json.loads(resp.text)
            if data:
                df = pd.DataFrame(data)
                df = df.rename(columns={
                    'day': 'date',
                    'open': 'open',
                    'high': 'high',
                    'low': 'low',
                    'close': 'close',
                    'volume': 'volume'
                })
                df['open'] = df['open'].astype(float)
                df['high'] = df['high'].astype(float)
                df['low'] = df['low'].astype(float)
                df['close'] = df['close'].astype(float)
                df['volume'] = df['volume'].astype(float)
                # 过滤日期范围
                df['date'] = pd.to_datetime(df['date'])
                df = df[(df['date'] >= start_date_fmt) & (df['date'] <= end_date_fmt)]
                df['date'] = df['date'].dt.strftime('%Y-%m-%d')
                return df
    except Exception as e:
        pass

    return None

def kline_df_to_records(df):
    """将K线DataFrame转换为记录列表，直接使用adata返回的数据"""
    if df is None or df.empty:
        return []

    result = []
    for _, row in df.iterrows():
        record = {}

        # 处理日期字段
        trade_date = row.get('trade_date') or row.get('trade_time') or row.get('date')
        if pd.isna(trade_date):
            continue
        record['date'] = str(trade_date)[:10] if len(str(trade_date)) > 10 else str(trade_date)

        # 使用adata返回的字段
        record['open'] = float(row['open']) if not pd.isna(row.get('open')) else 0.0
        record['high'] = float(row['high']) if not pd.isna(row.get('high')) else 0.0
        record['low'] = float(row['low']) if not pd.isna(row.get('low')) else 0.0
        record['close'] = float(row['close']) if not pd.isna(row.get('close')) else 0.0
        record['volume'] = float(row['volume']) if not pd.isna(row.get('volume')) else 0.0

        # 使用adata返回的涨幅数据（更准确）
        if 'change_pct' in row and not pd.isna(row.get('change_pct')):
            record['change_pct'] = round(float(row['change_pct']), 2)
        else:
            record['change_pct'] = 0.0

        if 'pre_close' in row and not pd.isna(row.get('pre_close')):
            record['prev_close'] = float(row['pre_close'])
        else:
            record['prev_close'] = record['close']

        result.append(record)

    return result

def save_kline_data(stock_code, df):
    """保存K线数据到JSON文件"""
    file_path = os.path.join(KLINE_DATA_DIR, f"{stock_code}.json")
    records = kline_df_to_records(df)

    if not records:
        return False

    data = {
        "stock_code": stock_code,
        "last_updated": get_today_str(),
        "klines": records
    }

    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存 {stock_code} K线失败: {e}")
        return False

def load_kline_data(stock_code):
    """从JSON文件加载K线数据"""
    file_path = os.path.join(KLINE_DATA_DIR, f"{stock_code}.json")
    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

# ========== 涨停股票获取 ==========

def load_zt_stocks_from_pool(dates):
    """从涨停池加载涨停股票"""
    all_data = []

    for date in dates:
        file_path = os.path.join(ZT_POOL_DIR, f"{date}.csv")
        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path)
                df['交易日期'] = int(date)
                all_data.append(df)
            except Exception as e:
                print(f"读取 {date} 涨停池失败: {e}")

    if all_data:
        df = pd.concat(all_data, ignore_index=True)
        df['代码'] = pd.to_numeric(df['代码'], errors='coerce').astype('Int64')
        df['代码_str'] = df['代码'].apply(lambda x: str(int(x)).zfill(6) if pd.notna(x) else '')
        return df

    return None

def get_zt_stocks_20d():
    """获取近20日涨停股票"""
    dates = get_trading_dates(20)
    print(f"近20个交易日: {dates[0]} ~ {dates[-1]}")

    df_zt = load_zt_stocks_from_pool(dates)
    if df_zt is None or df_zt.empty:
        print("未找到涨停池数据")
        return [], dates

    # 近20日有涨停的股票
    df_20d = df_zt[df_zt['交易日期'].astype(str).isin(dates)]
    stocks_20d = df_20d.groupby('代码_str').agg({
        '名称': 'first',
        '连板数': 'max',
        '交易日期': lambda x: sorted(x.tolist())
    }).reset_index()

    stocks_20d.columns = ['code', 'name', 'max_lianban', 'zt_dates']
    for s in stocks_20d.to_dict('records'):
        s['zt_dates'] = [str(d) for d in s['zt_dates']]
    stocks_list = stocks_20d.to_dict('records')

    print(f"近20日涨停股票数: {len(stocks_list)}")
    return stocks_list, dates

# ========== K线数据批量获取 ==========

def fetch_kline_batch(stock_codes, start_date, end_date, delay=0.3, max_workers=5):
    """批量获取K线数据"""
    results = {}
    total = len(stock_codes)

    print(f"开始获取K线数据: {total} 只股票")
    print(f"日期范围: {start_date} ~ {end_date}")

    def fetch_one(code):
        df = fetch_kline_for_stock(code, start_date, end_date)
        if df is not None and not df.empty:
            save_kline_data(code, df)
            return code, True
        return code, False

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, code): code for code in stock_codes}
        for i, future in enumerate(as_completed(futures)):
            code, success = future.result()
            results[code] = success
            status = "✓" if success else "✗"
            print(f"[{i+1}/{total}] {code} {status}")
            time.sleep(delay)

    success_count = sum(1 for v in results.values() if v)
    print(f"K线获取完成: 成功 {success_count}/{total}")
    return results

# ========== 概念分类 ==========

def load_ths_concepts():
    """加载同花顺概念数据"""
    # 优先使用cls_concept_stock（数据更完整）
    cls_file = os.path.join(CONCEPT_STOCK_DIR, "cls_concept_stock.json")
    if os.path.exists(cls_file):
        try:
            with open(cls_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    if not os.path.exists(THS_CONCEPT_FILE):
        return {}

    try:
        with open(THS_CONCEPT_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def get_stock_concepts(stock_code, concepts_data):
    """获取股票所属所有概念"""
    concepts = []
    # Handle both 'forward' nested dict or direct dict
    data = concepts_data.get('forward', concepts_data) if isinstance(concepts_data, dict) else concepts_data

    for concept, stocks in data.items():
        for stock in stocks:
            code = stock.get('code', '')
            # Match: 'sz000001' or 'sh600001' -> '000001' or '600001'
            code_only = code.replace('sz', '').replace('sh', '')
            if code_only == stock_code:
                concepts.append(concept)
                break
    return concepts if concepts else ["其他"]

# ========== 炸板检测 ==========

def detect_zaban(kline_data, dates_5d):
    """检测炸板：日内曾涨停但又打开"""
    if not kline_data or 'klines' not in kline_data:
        return False

    for kline in kline_data['klines']:
        date = kline.get('date', '')
        date_compare = date.replace('-', '')
        if date_compare not in dates_5d:
            continue

        close = kline.get('close', 0)
        high = kline.get('high', 0)

        if close <= 0 or high <= 0:
            continue

        prev_close = kline.get('prev_close', close)
        if prev_close <= 0:
            prev_close = kline.get('open', close)

        max_rise_pct = (high - prev_close) / prev_close * 100 if prev_close > 0 else 0
        rise_pct = (close - prev_close) / prev_close * 100 if prev_close > 0 else 0

        if max_rise_pct >= 9.5 and rise_pct < max_rise_pct - 3:
            return True

    return False

def detect_10pct_rise(kline_data, dates_5d):
    """检测创业板/科创版近5日最大涨幅>10%"""
    if not kline_data or 'klines' not in kline_data:
        return False

    for kline in kline_data['klines']:
        date = kline.get('date', '')
        date_compare = date.replace('-', '')
        if date_compare not in dates_5d:
            continue

        high = kline.get('high', 0)
        if high <= 0:
            continue

        prev_close = kline.get('prev_close', kline.get('open', high))
        if prev_close <= 0:
            prev_close = kline.get('open', high)

        max_rise_pct = (high - prev_close) / prev_close * 100 if prev_close > 0 else 0

        if max_rise_pct > 10:
            return True

    return False

# ========== 全市场股票形态检测（从数据库查询）==========

def find_zaban_stocks_from_db(dates_5d, db=None):
    """
    从数据库查询近5个交易日有炸板的股票
    炸板定义：日内曾涨停但又打开（最高价涨幅>=9.5%，但收盘涨幅明显小于最高涨幅）

    Args:
        dates_5d: 近5个交易日日期列表
        db: KlineDB实例

    Returns:
        list: 股票代码列表
    """
    if db is None:
        db = KlineDB()

    zaban_codes = []
    all_codes = db.get_all_stocks()

    for code in all_codes:
        df = db.get_kline_data(code)
        if df is None or df.empty:
            continue

        # 转换日期格式用于比较
        df = df.copy()
        df['trade_date_fmt'] = df['trade_date'].apply(lambda x: x.replace('-', '') if isinstance(x, str) else str(x)[:10].replace('-', ''))
        df_5d = df[df['trade_date_fmt'].isin(dates_5d)]

        if df_5d.empty:
            continue

        for _, row in df_5d.iterrows():
            high = row.get('high', 0)
            close = row.get('close', 0)
            prev_close = row.get('prev_close', 0)
            open_price = row.get('open', 0)

            if close <= 0 or high <= 0:
                continue

            if prev_close <= 0:
                prev_close = open_price if open_price > 0 else close

            max_rise_pct = (high - prev_close) / prev_close * 100 if prev_close > 0 else 0
            rise_pct = (close - prev_close) / prev_close * 100 if prev_close > 0 else 0

            if max_rise_pct >= 9.5 and rise_pct < max_rise_pct - 3:
                zaban_codes.append(code)
                break

    return zaban_codes


def find_10pct_rise_stocks_from_db(dates_5d, db=None):
    """
    从数据库查询创业板/科创版近5个交易日最大涨幅超过10%的股票

    Args:
        dates_5d: 近5个交易日日期列表
        db: KlineDB实例

    Returns:
        list: 股票代码列表
    """
    if db is None:
        db = KlineDB()

    rise_10pct_codes = []
    all_codes = db.get_all_stocks()

    for code in all_codes:
        # 只检查创业板/科创版
        if not is_gem_or_star(code):
            continue

        df = db.get_kline_data(code)
        if df is None or df.empty:
            continue

        # 转换日期格式用于比较
        df = df.copy()
        df['trade_date_fmt'] = df['trade_date'].apply(lambda x: x.replace('-', '') if isinstance(x, str) else str(x)[:10].replace('-', ''))
        df_5d = df[df['trade_date_fmt'].isin(dates_5d)]

        if df_5d.empty:
            continue

        for _, row in df_5d.iterrows():
            high = row.get('high', 0)
            prev_close = row.get('prev_close', 0)
            open_price = row.get('open', 0)

            if high <= 0:
                continue

            if prev_close <= 0:
                prev_close = open_price if open_price > 0 else high

            max_rise_pct = (high - prev_close) / prev_close * 100 if prev_close > 0 else 0

            if max_rise_pct > 10:
                rise_10pct_codes.append(code)
                break

    return rise_10pct_codes

# ========== 股票分类 ==========

def classify_stocks(stocks_list, dates_20d, dates_30d, dates_5d, concepts_data, db=None):
    """分类涨停股票"""
    categories = {
        'lianban_3_plus': [],
        'lianban_2': [],
        'single_zt': [],
        'normal': [],
        'zaban_5d': [],
        'chuangke_10pct': []
    }

    category_names = {
        'lianban_3_plus': '3连板及以上',
        'lianban_2': '2连板',
        'single_zt': '近30日仅1次涨停',
        'normal': '正常非连续涨停',
        'zaban_5d': '近5日炸板',
        'chuangke_10pct': '创业板/科创版近5日涨幅>10%'
    }

    result_stocks = []

    # 先从数据库查询全市场炸板和10%涨幅股票
    print("  从数据库查询全市场炸板股票...")
    zaban_from_db = set(find_zaban_stocks_from_db(dates_5d, db))
    print(f"  全市场炸板股票: {len(zaban_from_db)} 只")

    print("  从数据库查询全市场创业板/科创版10%涨幅股票...")
    chuangke_10pct_from_db = set(find_10pct_rise_stocks_from_db(dates_5d, db))
    print(f"  创业板/科创版10%涨幅股票: {len(chuangke_10pct_from_db)} 只")

    for stock in stocks_list:
        code = stock['code']
        name = stock['name']
        zt_dates = stock['zt_dates']

        # 获取K线数据
        kline_data = load_kline_data(code)

        # 检测炸板 - 优先使用数据库结果
        is_zaban = code in zaban_from_db
        if not is_zaban:
            is_zaban = detect_zaban(kline_data, dates_5d)

        # 检测10%涨幅 - 优先使用数据库结果
        is_10pct = code in chuangke_10pct_from_db
        if not is_10pct:
            is_10pct = detect_10pct_rise(kline_data, dates_5d)

        # 获取概念
        concept = get_stock_concepts(code, concepts_data)

        # 构建股票信息
        stock_info = {
            'code': code,
            'name': name,
            'max_lianban': stock['max_lianban'],
            'zt_count': len(zt_dates),
            'zt_dates': zt_dates[-5:] if len(zt_dates) > 5 else zt_dates,
            'is_gem_or_star': is_gem_or_star(code),
            'is_zaban': is_zaban,
            'is_10pct': is_10pct,
            'concept': concept,
            'kline_data': kline_data
        }

        # 分类
        max_lb = stock['max_lianban']
        if max_lb >= 3:
            categories['lianban_3_plus'].append(code)
        elif max_lb == 2:
            categories['lianban_2'].append(code)
        elif len(zt_dates) == 1:
            categories['single_zt'].append(code)
        else:
            categories['normal'].append(code)

        if is_zaban:
            categories['zaban_5d'].append(code)

        if is_10pct and is_gem_or_star(code):
            categories['chuangke_10pct'].append(code)

        result_stocks.append(stock_info)

    # 构建最终结果
    result = {
        'date': get_today_str(),
        'generated_at': get_beijing_now().strftime('%H:%M:%S'),
        'categories': {}
    }

    for cat_key, codes in categories.items():
        cat_stocks = []
        for code in codes:
            for s in result_stocks:
                if s['code'] == code:
                    cat_stocks.append({
                        'code': s['code'],
                        'name': s['name'],
                        'max_lianban': s['max_lianban'],
                        'zt_count': s['zt_count'],
                        'zt_dates': s['zt_dates'],
                        'is_gem_or_star': s['is_gem_or_star'],
                        'is_zaban': s['is_zaban'],
                        'is_10pct': s['is_10pct'],
                        'concept': s['concept']
                    })
                    break

        # 排序
        cat_stocks.sort(key=lambda x: x['zt_dates'][-1] if x['zt_dates'] else '', reverse=True)

        result['categories'][cat_key] = {
            'name': category_names[cat_key],
            'count': len(cat_stocks),
            'stocks': cat_stocks
        }

    return result

# ========== 生成看板HTML ==========

def generate_dashboard_html(classified_data, output_file):
    """生成看板HTML - 使用新浪K线图和浅色主题"""

    html_template = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>涨停板看板 - {date}</title>
    <link rel="stylesheet" href="static/css/dashboard.css">
    <style>
        body {{ padding: 0; margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f6fa; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px 30px; }}
        .header {{ background: linear-gradient(135deg, #2b6cb0 0%, #3182ce 100%); border-radius: 12px; padding: 25px 30px; margin-bottom: 20px; box-shadow: 0 4px 12px rgba(43, 108, 176, 0.3); }}
        .header h1 {{ font-size: 1.8em; color: #fff; margin-bottom: 5px; font-weight: 600; text-align: center; }}
        .header .subtitle {{ color: rgba(255,255,255,0.9); font-size: 0.9em; text-align: center; }}
        .header .stats {{ display: flex; justify-content: center; gap: 30px; margin-top: 20px; flex-wrap: wrap; }}
        .header .stat-card {{ background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.3); border-radius: 10px; padding: 12px 25px; text-align: center; backdrop-filter: blur(10px); }}
        .header .stat-value {{ font-size: 1.6em; font-weight: bold; color: #fff; }}
        .header .stat-label {{ color: rgba(255,255,255,0.85); font-size: 0.8em; margin-top: 3px; }}
        .section-block {{ background: #fff; border-radius: 12px; padding: 20px 25px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
        .section-title {{ font-size: 1.2em; color: #2b6cb0; margin-bottom: 15px; padding-left: 10px; border-left: 4px solid #2b6cb0; font-weight: 600; }}
        .section-count {{ color: #718096; font-size: 0.9em; margin-left: 10px; }}
        .stock-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px; align-items: start; }}
        .stock-card {{ background: #f7fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 15px; cursor: pointer; transition: all 0.2s; }}
        .stock-card:hover {{ transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); border-color: #4299e1; }}
        .stock-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
        .stock-name {{ font-size: 1.1em; font-weight: 600; color: #2d3748; }}
        .stock-code {{ color: #718096; font-size: 0.85em; }}
        .stock-tags {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; min-height: 26px; }}
        .tag {{ padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }}
        .tag-lianban {{ background: #fed7d7; color: #c53030; }}
        .tag-zaban {{ background: #feebc8; color: #c05621; }}
        .tag-chuangke {{ background: #e9d8fd; color: #6b46c1; }}
        .tag-concept {{ background: #bee3f8; color: #2b6cb0; }}
        .stock-content {{ display: flex; flex-direction: column; }}
        .kline-img {{ width: 100%; height: 120px; border-radius: 6px; background: #f0f2f5; cursor: pointer; object-fit: cover; }}
        .stock-info {{ font-size: 0.85em; color: #718096; margin-top: 5px; text-align: center; }}
        .modal-overlay {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; justify-content: center; align-items: center; }}
        .modal-overlay.active {{ display: flex; }}
        .modal-content {{ background: #fff; border-radius: 16px; padding: 25px; width: 90%; max-width: 900px; max-height: 90vh; overflow: auto; }}
        .modal-header {{ display: flex; justify-content: space-between; margin-bottom: 15px; }}
        .modal-title {{ font-size: 1.4em; font-weight: 600; color: #2d3748; }}
        .modal-close {{ background: none; border: none; font-size: 24px; cursor: pointer; color: #718096; }}
        .modal-tabs {{ display: flex; gap: 10px; margin-bottom: 15px; }}
        .tab-btn {{ padding: 8px 16px; border: 1px solid #e2e8f0; border-radius: 6px; background: #fff; cursor: pointer; font-size: 0.9em; }}
        .tab-btn.active {{ background: #2b6cb0; color: #fff; border-color: #2b6cb0; }}
        .modal-body {{ background: #f7fafc; border-radius: 8px; padding: 10px; }}
        #kline-img {{ width: 100%; border-radius: 8px; }}
        .concept-tags {{ display: flex; gap: 5px; flex-wrap: wrap; margin-top: 5px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>涨停板看板</h1>
            <div class="subtitle">生成时间: {generated_at} | 近20日涨停分析</div>
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value">{total_stocks}</div>
                    <div class="stat-label">近20日涨停股票</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{lianban_3_count}</div>
                    <div class="stat-label">3连板及以上</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{lianban_2_count}</div>
                    <div class="stat-label">2连板</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{zaban_count}</div>
                    <div class="stat-label">近5日炸板</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{chuangke_count}</div>
                    <div class="stat-label">创业板/科创版10%+</div>
                </div>
            </div>
        </div>

        {category_sections}
    </div>

    <!-- K线弹窗 -->
    <div id="kline-modal" class="modal-overlay" onclick="closeKLineModal()">
        <div class="modal-content" onclick="event.stopPropagation()">
            <div class="modal-header">
                <div class="modal-title" id="kline-title">股票名称</div>
                <button class="modal-close" onclick="closeKLineModal()">&times;</button>
            </div>
            <div class="modal-tabs">
                <button class="tab-btn active" onclick="switchKLineTab('min', this)">分时</button>
                <button class="tab-btn" onclick="switchKLineTab('daily', this)">日K</button>
                <button class="tab-btn" onclick="switchKLineTab('weekly', this)">周K</button>
                <button class="tab-btn" onclick="switchKLineTab('monthly', this)">月K</button>
            </div>
            <div class="modal-body">
                <img id="kline-img" src="" alt="K线图加载中...">
            </div>
        </div>
    </div>

    <script>
        let currentStockCode = '';
        let currentStockPrefix = '';

        function getSinaPrefix(code) {{
            if (code.startsWith('6')) return 'sh' + code;
            return 'sz' + code;
        }}

        function openKLineModal(code, name) {{
            currentStockCode = code;
            currentStockPrefix = getSinaPrefix(code);
            document.getElementById('kline-title').textContent = name + ' (' + code + ')';
            document.getElementById('kline-modal').classList.add('active');
            switchKLineTab('daily');
        }}

        function closeKLineModal() {{
            document.getElementById('kline-modal').classList.remove('active');
            document.getElementById('kline-img').src = '';
        }}

        function switchKLineTab(type, elm) {{
            // 更新标签状态
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            if (elm) {{ elm.classList.add('active'); }}
            else {{
                const tabs = document.querySelectorAll('.tab-btn');
                if (type === 'min') tabs[0] && tabs[0].classList.add('active');
                if (type === 'daily') tabs[1] && tabs[1].classList.add('active');
                if (type === 'weekly') tabs[2] && tabs[2].classList.add('active');
                if (type === 'monthly') tabs[3] && tabs[3].classList.add('active');
            }}

            // 新浪K线图URL
            let t = Math.floor(new Date().getTime() / 10000);
            let url = "http://image.sinajs.cn/newchart/" + type + "/n/" + currentStockPrefix + ".png?" + t;

            let img = document.getElementById('kline-img');
            img.src = '';
            img.alt = 'K线图急速拉取中...';
            img.style.opacity = '0.5';
            img.onload = function() {{ img.style.opacity = '1'; }};
            img.onerror = function() {{ img.alt = '获取失败，请重试'; }};
            img.src = url;
        }}
    </script>
    <script>
    // 交易日16:30自动刷新（北京时间）
    (function(){
        function getNextRefreshTime() {
            var now = new Date();
            var beijingOffset = 8 * 60 * 60 * 1000;
            var today = new Date(now.getTime() + beijingOffset);
            var targetHour = 16, targetMin = 30;
            var targetToday = new Date(today.getFullYear(), today.getMonth(), today.getDate(), targetHour, targetMin, 0);
            targetToday = new Date(targetToday.getTime() - beijingOffset);
            if (now < targetToday) return targetToday;
            // 明天16:30
            var tomorrow = new Date(targetToday);
            tomorrow.setDate(tomorrow.getDate() + 1);
            return tomorrow;
        }
        setTimeout(function(){ location.reload(); }, getNextRefreshTime() - new Date());
    })();
    </script>
</body>
</html>'''

    # 计算统计
    total_stocks = sum(cat['count'] for cat in classified_data['categories'].values())
    lianban_3_count = classified_data['categories'].get('lianban_3_plus', {}).get('count', 0)
    lianban_2_count = classified_data['categories'].get('lianban_2', {}).get('count', 0)
    zaban_count = classified_data['categories'].get('zaban_5d', {}).get('count', 0)
    chuangke_count = classified_data['categories'].get('chuangke_10pct', {}).get('count', 0)

    # 生成分类区块
    category_sections = ""
    for cat_key, cat_data in classified_data['categories'].items():
        if cat_data['count'] == 0:
            continue

        stocks_html = ""
        for stock in cat_data['stocks']:
            tags = []
            if stock['max_lianban'] >= 2:
                tags.append(f'<span class="tag tag-lianban">{stock["max_lianban"]}连板</span>')
            if stock['is_zaban']:
                tags.append('<span class="tag tag-zaban">炸板</span>')
            if stock['is_10pct']:
                tags.append('<span class="tag tag-chuangke">10%+涨幅</span>')
            # 显示所有概念标签
            concepts = stock.get('concept', [])
            if isinstance(concepts, list):
                for c in concepts[:5]:
                    tags.append(f'<span class="tag tag-concept">{c}</span>')
            elif concepts:
                tags.append(f'<span class="tag tag-concept">{concepts}</span>')

            tags_html = ''.join(tags)

            # 新浪K线图 - 小图
            prefix = 'sh' + stock['code'] if stock['code'].startswith('6') else 'sz' + stock['code']
            kline_url = f"http://image.sinajs.cn/newchart/daily/n/{prefix}.png?_={get_beijing_now().strftime('%Y%m%d%H%M%S')}"

            # 涨停日期信息
            zt_dates_str = ", ".join([str(d) for d in stock['zt_dates'][-3:]]) if stock['zt_dates'] else "无"

            stocks_html += f'''
            <div class="stock-card" onclick="openKLineModal('{stock['code']}', '{stock['name']}')">
                <div class="stock-header">
                    <div class="stock-name">{stock['name']}</div>
                    <div class="stock-code">{stock['code']}</div>
                </div>
                <div class="stock-tags">{tags_html}</div>
                <div class="stock-content">
                    <img class="kline-img" src="{kline_url}" alt="K线">
                    <div class="stock-info">涨停{stock['zt_count']}次 | 近20日: {zt_dates_str}</div>
                </div>
            </div>
            '''

        category_sections += f'''
        <div class="section-block">
            <div class="section-title">{cat_data['name']}<span class="section-count">({cat_data['count']}只)</span></div>
            <div class="stock-grid">{stocks_html}</div>
        </div>
        '''

    # 渲染HTML
    html = html_template.format(
        date=classified_data['date'],
        generated_at=classified_data['generated_at'],
        total_stocks=total_stocks,
        lianban_3_count=lianban_3_count,
        lianban_2_count=lianban_2_count,
        zaban_count=zaban_count,
        chuangke_count=chuangke_count,
        category_sections=category_sections
    )

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"看板已生成: {output_file}")

# ========== 主程序 ==========

def main():
    parser = argparse.ArgumentParser(description="涨停板看板")
    parser.add_argument('--fetch-kline', action='store_true', help='强制获取K线数据')
    parser.add_argument('--open-browser', action='store_true', help='自动打开浏览器')
    parser.add_argument('--days', type=int, default=20, help='近N日涨停（默认20）')
    args = parser.parse_args()

    print("=" * 60)
    print("涨停板看板分析")
    print("=" * 60)

    # 1. 获取近20日涨停股票
    print("\n[1/5] 获取近20日涨停股票...")
    stocks_list, dates = get_zt_stocks_20d()
    if not stocks_list:
        print("未找到涨停股票数据")
        return 1

    dates_30d = get_trading_dates(30)
    dates_5d = get_trading_dates(5)

    # 初始化数据库
    print("\n[2/5] 初始化数据库...")
    db = KlineDB()
    print(f"数据库路径: {db.db_path}")

    # 3. 获取K线数据
    print("\n[3/5] 处理K线数据...")
    stock_codes = [s['code'] for s in stocks_list]

    # 检查需要获取的K线
    need_fetch = []
    for code in stock_codes:
        kline_file = os.path.join(KLINE_DATA_DIR, f"{code}.json")
        if args.fetch_kline or not os.path.exists(kline_file):
            need_fetch.append(code)

    if need_fetch:
        print(f"需要获取 {len(need_fetch)} 只股票的K线数据")
        start_date = dates_30d[-1] if len(dates_30d) >= 30 else '20260301'
        end_date = dates_30d[0] if dates_30d else get_today_str()
        fetch_kline_batch(need_fetch, start_date, end_date)
    else:
        print("K线数据已存在，跳过获取")

    # 4. 加载概念数据
    print("\n[4/5] 加载概念数据...")
    concepts_data = load_ths_concepts()
    print(f"加载了 {len(concepts_data)} 个概念板块")

    # 5. 分类并生成看板
    print("\n[5/5] 分类并生成看板...")
    classified_data = classify_stocks(stocks_list, dates, dates_30d, dates_5d, concepts_data, db)

    # 打印统计
    print("\n分类统计:")
    for cat_key, cat_data in classified_data['categories'].items():
        print(f"  {cat_data['name']}: {cat_data['count']} 只")

    # 生成HTML
    output_file = os.path.join(REPORTS_DIR, "dashboard.html")
    generate_dashboard_html(classified_data, output_file)

    print(f"\n完成! 看板路径: {output_file}")

    # 打开浏览器
    if args.open_browser:
        import webbrowser
        webbrowser.open(f'file://{os.path.abspath(output_file)}')

    return 0

if __name__ == "__main__":
    sys.exit(main())