"""
K线数据获取与存储模块
====================
功能：
    1. 使用adata获取股票日K线数据
    2. 存储到data/kline_data/*.json

使用方法：
    python fetch_kline_data.py
    python fetch_kline_data.py --codes 000001 000002 --days 30
"""

import adata
import pandas as pd
import json
import os
from datetime import datetime, timedelta
import argparse
import time
import sys

# 获取当前脚本所在目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# K线数据存储目录
KLINE_DATA_DIR = os.path.join(SCRIPT_DIR, "data", "kline_data")

# 确保目录存在
os.makedirs(KLINE_DATA_DIR, exist_ok=True)


def get_beijing_now():
    """获取当前北京时间"""
    return datetime.now()


def get_today_str():
    """获取今天的日期字符串 YYYYMMDD"""
    return get_beijing_now().strftime('%Y%m%d')


def get_trading_dates_around(days=30):
    """获取近N个交易日期"""
    today_str = get_beijing_now().strftime('%Y%m%d')

    # 尝试从本地缓存读取
    cache_file = os.path.join(SCRIPT_DIR, "data", 'trade_calendar_2026.json')
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

    # 尝试从API获取
    try:
        df = adata.stock.info.trade_calendar(year=2026)
        df_trading = df[df['trade_status'] == 1]
        trading_dates = df_trading['trade_date'].astype(str).tolist()
        trading_dates = [d.replace('-', '') for d in trading_dates]
        trading_dates = [d for d in trading_dates if d <= today_str][::-1]
        return trading_dates[:days] if len(trading_dates) >= days else trading_dates
    except Exception as e:
        print(f"获取交易日历失败: {e}")
        # 备用逻辑：工作日
        dates = []
        current = datetime.now()
        while len(dates) < days:
            if current.weekday() < 5:
                dates.append(current.strftime('%Y%m%d'))
            current -= timedelta(days=1)
        return dates


def fetch_kline_for_stock(stock_code, start_date, end_date=None):
    """
    获取单只股票日K线数据

    Args:
        stock_code: 股票代码，如 '000001'
        start_date: 开始日期 'YYYY-MM-DD' 或 'YYYYMMDD'
        end_date: 结束日期，默认今天

    Returns:
        DataFrame: 包含日K线数据的DataFrame
    """
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

    try:
        df = adata.stock.market.get_market(
            stock_code=stock_code,
            start_date=start_date_fmt,
            k_type=1,       # 日K
            adjust_type=1   # 前复权
        )
        return df
    except Exception as e:
        print(f"获取 {stock_code} K线数据失败: {e}")
        return None


def kline_df_to_records(df):
    """
    将K线DataFrame转换为记录列表

    Args:
        df: K线DataFrame

    Returns:
        list: 字典列表
    """
    if df is None or df.empty:
        return []

    # 尝试识别列名
    columns_lower = [c.lower() for c in df.columns]
    result = []

    for _, row in df.iterrows():
        record = {}
        for col in df.columns:
            col_lower = col.lower()
            val = row[col]
            if pd.isna(val):
                continue

            # 日期
            if 'date' in col_lower or '日期' in col or 'trade' in col_lower:
                if isinstance(val, str):
                    if len(val) == 8:
                        val = f"{val[:4]}-{val[4:6]}-{val[6:8]}"
                record['date'] = str(val)
            # 开盘
            elif 'open' in col_lower or '开盘' in col:
                record['open'] = float(val)
            # 最高
            elif 'high' in col_lower or '最高' in col:
                record['high'] = float(val)
            # 最低
            elif 'low' in col_lower or '最低' in col:
                record['low'] = float(val)
            # 收盘
            elif 'close' in col_lower or '收盘' in col:
                record['close'] = float(val)
            # 成交量
            elif 'volume' in col_lower or '成交' in col or 'vol' in col_lower:
                record['volume'] = float(val)
            # 涨跌幅
            elif 'pct' in col_lower or '涨幅' in col or 'change' in col_lower:
                try:
                    record['change_pct'] = float(val)
                except:
                    pass

        if record:
            result.append(record)

    return result


def save_kline_data(stock_code, df):
    """
    保存K线数据到JSON文件

    Args:
        stock_code: 股票代码
        df: K线DataFrame

    Returns:
        bool: 是否成功保存
    """
    file_path = os.path.join(KLINE_DATA_DIR, f"{stock_code}.json")

    records = kline_df_to_records(df)

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
        print(f"保存 {stock_code} K线数据失败: {e}")
        return False


def load_kline_data(stock_code):
    """
    从JSON文件加载K线数据

    Args:
        stock_code: 股票代码

    Returns:
        dict: K线数据字典，失败返回None
    """
    file_path = os.path.join(KLINE_DATA_DIR, f"{stock_code}.json")
    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"加载 {stock_code} K线数据失败: {e}")
        return None


def fetch_and_save_kline(stock_code, start_date, end_date=None):
    """
    获取并保存单只股票K线数据

    Args:
        stock_code: 股票代码
        start_date: 开始日期
        end_date: 结束日期

    Returns:
        bool: 是否成功
    """
    df = fetch_kline_for_stock(stock_code, start_date, end_date)
    if df is not None and not df.empty:
        return save_kline_data(stock_code, df)
    return False


def batch_fetch_kline(stock_codes, start_date, end_date=None, delay=0.5):
    """
    批量获取K线数据

    Args:
        stock_codes: 股票代码列表
        start_date: 开始日期
        end_date: 结束日期
        delay: 请求间隔（秒）

    Returns:
        dict: {stock_code: success}
    """
    results = {}
    total = len(stock_codes)

    print(f"开始批量获取 {total} 只股票的K线数据...")
    print(f"日期范围: {start_date} ~ {end_date or '今天'}")
    print("-" * 50)

    for i, code in enumerate(stock_codes):
        success = fetch_and_save_kline(code, start_date, end_date)
        results[code] = success

        status = "✓" if success else "✗"
        print(f"[{i+1}/{total}] {code} {status}")

        if i < total - 1:
            time.sleep(delay)

    success_count = sum(1 for v in results.values() if v)
    print("-" * 50)
    print(f"完成: 成功 {success_count}/{total}")

    return results


def load_zt_stocks_from_pool(days=20):
    """
    从涨停池加载近N日的涨停股票代码列表

    Args:
        days: 近N日

    Returns:
        list: 股票代码列表（去重）
    """
    today_str = get_today_str()
    dates = get_trading_dates_around(days)

    all_codes = set()

    for date in dates:
        file_path = os.path.join(SCRIPT_DIR, "data", "zt_pool", f"{date}.csv")
        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path)
                if '代码' in df.columns:
                    codes = df['代码'].dropna().astype(int).astype(str).str.zfill(6)
                    all_codes.update(codes.tolist())
            except Exception as e:
                print(f"读取 {date} 涨停池失败: {e}")

    return sorted(list(all_codes))


def main():
    parser = argparse.ArgumentParser(description="K线数据获取与存储")
    parser.add_argument('--codes', nargs='*', help='股票代码列表，如 000001 000002')
    parser.add_argument('--days', type=int, default=30, help='获取近N个交易日K线，默认30')
    parser.add_argument('--from-zt', action='store_true', help='从涨停池获取近20日涨停股票列表')
    parser.add_argument('--delay', type=float, default=0.5, help='请求间隔（秒），默认0.5')

    args = parser.parse_args()

    # 确定股票代码列表
    stock_codes = args.codes if args.codes else []

    if args.from_zt:
        print("从涨停池获取近20日涨停股票...")
        stock_codes = load_zt_stocks_from_pool(20)
        print(f"共 {len(stock_codes)} 只股票")

    if not stock_codes:
        print("请指定股票代码或使用 --from-zt 从涨停池获取")
        print("示例: python fetch_kline_data.py --codes 000001 000002 --days 30")
        print("示例: python fetch_kline_data.py --from-zt --days 30")
        return

    # 确定日期范围
    dates = get_trading_dates_around(args.days)
    start_date = dates[-1] if dates else '20260301'
    end_date = dates[0] if dates else get_today_str()

    print(f"日期范围: {start_date} ~ {end_date} (共 {len(dates)} 个交易日)")

    # 批量获取
    results = batch_fetch_kline(stock_codes, start_date, end_date, args.delay)

    # 输出失败列表
    failed = [code for code, success in results.items() if not success]
    if failed:
        print(f"\n失败股票: {failed}")


if __name__ == "__main__":
    main()
