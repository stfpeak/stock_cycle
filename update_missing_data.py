#!/usr/bin/env python3
"""
缺失K线数据批量更新脚本
====================
使用 tushare pro.daily(trade_date=) 按日期批量补全（1次API调用=全部股票）。

使用方式：
    python update_missing_data.py                  # 增量更新（默认）
    python update_missing_data.py --days 10        # 更新最近N个交易日
    python update_missing_data.py --start 20260508 # 从指定日期开始
    python update_missing_data.py --all            # 更新全部交易日
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kline_database import KlineDB, _stock_code_to_tscode


def get_trading_days(db: KlineDB, start_date: str = None, end_date: str = None,
                     last_n: int = None) -> list:
    """获取交易日列表"""
    trade_dates = db.load_trade_calendar()
    if not trade_dates:
        print("无法加载交易日历")
        return []

    # 按时间排序（升序）
    trade_dates.sort()

    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')

    # 过滤
    result = [d for d in trade_dates if d <= end_date]
    if start_date:
        result = [d for d in result if d >= start_date]
    if last_n:
        result = result[-last_n:]

    return result


def update_by_date_range(db: KlineDB, trading_days: list, delay: float = 1.5):
    """
    按交易日批量更新K线数据

    对每个交易日，使用 pro.daily(trade_date=) 一次获取全部股票数据。

    Args:
        db: KlineDB 实例
        trading_days: 交易日列表（YYYYMMDD）
        delay: API调用间隔（秒），免费token限制50次/分钟 → 至少1.2s
    """
    if db.pro is None:
        print("tushare 未初始化")
        return

    total_days = len(trading_days)
    total_updated = 0
    success_days = 0
    failed_days = 0

    print(f"按日期批量更新 {total_days} 个交易日...")
    print("-" * 60)

    for i, trade_date in enumerate(trading_days):
        try:
            # 检查该日期是否已有数据
            conn = db._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM kline_daily WHERE trade_date = ?",
                          (f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}",))
            existing_count = cursor.fetchone()[0]
            conn.close()

            if existing_count > 5000:
                print(f"[{i+1}/{total_days}] {trade_date} 已有 {existing_count} 条记录，跳过")
                success_days += 1
                continue

            # 获取当日全部股票数据（1次API调用）
            params = {'trade_date': trade_date}
            df = db.pro.daily(**params)

            if df is None or df.empty:
                print(f"[{i+1}/{total_days}] {trade_date} 无数据")
                failed_days += 1
                continue

            # 字段映射
            df = df.rename(columns={
                'vol': 'volume',
                'pct_chg': 'change_pct',
            })
            df['trade_date'] = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"

            # 提取纯6位股票代码
            df['stock_code'] = df['ts_code'].str.extract(r'(\d{6})')

            # 逐只股票保存
            day_count = 0
            for _, row in df.iterrows():
                code = row['stock_code']
                record = {
                    'trade_date': row['trade_date'],
                    'open': row.get('open', 0),
                    'high': row.get('high', 0),
                    'low': row.get('low', 0),
                    'close': row.get('close', 0),
                    'volume': row.get('volume', 0),
                    'amount': row.get('amount', 0),
                    'change_pct': row.get('change_pct', 0),
                    'change_val': row.get('change', 0),
                    'pre_close': row.get('pre_close', 0),
                    'turnover_ratio': 0,
                }

                # 直接插入
                conn = db._get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT OR REPLACE INTO kline_daily (
                            stock_code, trade_date, open, high, low, close, volume,
                            amount, change_pct, change_val, prev_close, turnover_ratio
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        code, record['trade_date'],
                        record['open'], record['high'], record['low'],
                        record['close'], record['volume'], record['amount'],
                        record['change_pct'], record['change_val'],
                        record['pre_close'], record['turnover_ratio'],
                    ))
                    conn.commit()
                    day_count += 1
                finally:
                    conn.close()

            total_updated += day_count
            success_days += 1
            print(f"[{i+1}/{total_days}] {trade_date} ✓ {day_count} 条")

        except Exception as e:
            failed_days += 1
            print(f"[{i+1}/{total_days}] {trade_date} ✗ {type(e).__name__}: {e}")

        # 控制频率
        if i < total_days - 1:
            time.sleep(delay)

    print("-" * 60)
    print(f"完成! 成功: {success_days}/{total_days}, 失败: {failed_days}, 更新: {total_updated} 条记录")


def main():
    parser = argparse.ArgumentParser(description="缺失K线数据批量更新")
    parser.add_argument('--days', type=int, default=None, help='更新最近N个交易日')
    parser.add_argument('--start', type=str, default=None, help='开始日期 YYYYMMDD')
    parser.add_argument('--end', type=str, default=None, help='结束日期 YYYYMMDD')
    parser.add_argument('--all', action='store_true', help='更新全部交易日')
    parser.add_argument('--delay', type=float, default=1.5, help='API调用间隔（秒）')

    args = parser.parse_args()

    db = KlineDB()
    trading_days = []

    if args.all:
        trading_days = get_trading_days(db)
    elif args.start:
        trading_days = get_trading_days(db, start_date=args.start, end_date=args.end)
    elif args.days:
        trading_days = get_trading_days(db, last_n=args.days)
    else:
        # 默认更新最近6个交易日
        trading_days = get_trading_days(db, last_n=10)

    if not trading_days:
        print("没有待更新的交易日")
        return

    update_by_date_range(db, trading_days, delay=args.delay)


if __name__ == "__main__":
    main()
