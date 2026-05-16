#!/usr/bin/env python3
"""
更新涨停池股票K线数据
====================
从data/zt_pool/读取所有历史上过涨停的股票，批量更新其近1年K线数据到数据库。

使用方式：
    python update_zt_kline.py            # 增量更新（默认）
    python update_zt_kline.py --full     # 强制全量更新
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime, timedelta
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kline_database import KlineDB, get_zt_pool_stocks


def update_zt_stocks_kline(full_update=False, start_date=None, end_date=None, delay=0.3):
    """
    更新所有涨停池股票的K线数据

    Args:
        full_update: 是否强制全量更新（忽略已有数据）
        start_date: 开始日期 YYYYMMDD，默认取近250个交易日（约1年）
        end_date: 结束日期 YYYYMMDD，默认今天
        delay: 请求间隔（秒）

    Returns:
        dict: 更新统计
    """
    db = KlineDB()

    # 获取所有zt_pool股票
    stock_codes = get_zt_pool_stocks(days=999)
    print(f"涨停池股票总数: {len(stock_codes)}")

    if not stock_codes:
        print("没有找到涨停池股票")
        return {"total": 0, "success": 0, "failed": 0, "updated": 0}

    # 确定日期范围
    trade_dates = db.load_trade_calendar()
    if not trade_dates:
        print("无法加载交易日历")
        return {"total": 0, "success": 0, "failed": 0, "updated": 0}

    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')

    if start_date is None:
        # 取近约1年（~250个交易日）的数据
        today_str = datetime.now().strftime('%Y%m%d')
        past_dates = [d for d in trade_dates if d <= today_str]
        past_dates.sort(reverse=True)
        if len(past_dates) >= 250:
            start_date = past_dates[249]  # 第250个
        else:
            start_date = past_dates[-1] if past_dates else '20260101'

    print(f"日期范围: {start_date} ~ {end_date}")
    print(f"模式: {'全量更新' if full_update else '增量更新'}")
    print(f"请求间隔: {delay}秒")
    print("-" * 60)

    total = len(stock_codes)
    success = 0
    failed = 0
    total_updated = 0
    error_counts = Counter()

    for i, code in enumerate(stock_codes):
        try:
            if not full_update:
                # 检查是否已有今天的日期范围数据
                existing = db.get_existing_dates(code)
                existing_fmt = {d.replace('-', '') for d in existing}
                need_dates = [d for d in trade_dates
                              if start_date <= d <= end_date]
                missing = [d for d in need_dates if d not in existing_fmt]

                if not missing:
                    if (i + 1) % 200 == 0:
                        print(f"[{i+1}/{total}] {code} 数据完整，跳过")
                    success += 1
                    continue
            else:
                missing = [d for d in trade_dates
                           if start_date <= d <= end_date]

            # 使用 tushare 获取该股票的K线数据
            df = db.fetch_by_tushare(code, min(missing), max(missing))

            if df is not None and not df.empty:
                count = db.save_kline_data(code, df)
                total_updated += count
                success += 1
                status = f"+{count}"
            else:
                failed += 1
                status = "无数据"

        except Exception as e:
            failed += 1
            err_name = type(e).__name__
            error_counts[err_name] += 1
            status = f"{err_name}"

        if (i + 1) % 50 == 0 or failed > 0:
            print(f"[{i+1}/{total}] {code} {status}")

        if i < total - 1:
            time.sleep(delay)

    print("-" * 60)
    print(f"完成! 成功: {success}/{total}, 失败: {failed}, 更新记录: {total_updated}")
    if error_counts:
        print(f"错误分布: {dict(error_counts.most_common())}")

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "updated": total_updated,
        "errors": dict(error_counts)
    }


def main():
    parser = argparse.ArgumentParser(description="更新涨停池股票K线数据")
    parser.add_argument('--full', action='store_true', help='强制全量更新')
    parser.add_argument('--start', type=str, default=None, help='开始日期 YYYYMMDD')
    parser.add_argument('--end', type=str, default=None, help='结束日期 YYYYMMDD')
    parser.add_argument('--delay', type=float, default=0.3, help='请求间隔秒数')
    parser.add_argument('--codes', nargs='*', help='指定股票代码，默认全部涨停池')

    args = parser.parse_args()

    if args.codes:
        # 更新指定股票
        db = KlineDB()
        result = {"total": len(args.codes), "success": 0, "failed": 0, "updated": 0}

        for i, code in enumerate(args.codes):
            try:
                code = str(code).zfill(6)
                start_fmt = args.start or '2026-01-05'

                end_fmt = args.end or datetime.now().strftime('%Y%m%d')
                df = db.fetch_by_tushare(code, start_fmt, end_fmt)
                if df is not None and not df.empty:
                    count = db.save_kline_data(code, df)
                    result["updated"] += count
                    result["success"] += 1
                    print(f"[{i+1}/{len(args.codes)}] {code} +{count}")
                else:
                    result["failed"] += 1
                    print(f"[{i+1}/{len(args.codes)}] {code} 无数据")
            except Exception as e:
                result["failed"] += 1
                print(f"[{i+1}/{len(args.codes)}] {code} {type(e).__name__}: {e}")
            if i < len(args.codes) - 1:
                time.sleep(args.delay)

        print(f"完成: {result}")
    else:
        update_zt_stocks_kline(
            full_update=args.full,
            start_date=args.start,
            end_date=args.end,
            delay=args.delay
        )


if __name__ == "__main__":
    main()
