#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取开盘红「精选板块 × 成分股」：python3 fetch_selected.py [日期 ...]
传入的日期里本目录已有 stocks_<日期>.csv 的会跳过。输出 sectors_<日期>.csv / stocks_<日期>.csv。
成分股接口较慢（每板块 2~3s），按日期串行、日内 4 线程并发。"""
import csv, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import levistock as lk

OUT = os.path.dirname(os.path.abspath(__file__))


def retry(f, *a, **k):
    for t in range(5):
        try:
            return f(*a, **k)
        except Exception as e:
            print('retry', t, type(e).__name__, flush=True)
            time.sleep(2 + t * 2)
    return None


def fetch_day(d):
    sec = retry(lk.sector_ranking_kph, date=d, zs_type=lk.SECTOR_SELECTED, fetch_all=True)
    if not sec:
        print(d, '板块列表获取失败', flush=True)
        return False
    sd = pd.DataFrame(sec)
    sd.insert(0, 'date', d)
    sd.to_csv(os.path.join(OUT, 'sectors_%s.csv' % d), index=False, encoding='utf-8-sig')

    def one(s):
        return s, retry(lk.sector_stocks_his_kph, plate_id=s['plate_id'], date=d)
    rows, failed = [], 0
    with ThreadPoolExecutor(4) as ex:
        for s, st in ex.map(one, sec):
            if st is None:
                failed += 1
                continue
            rows.extend({'date': d, 'plate_id': s['plate_id'], 'plate_name': s['plate_name'], **r} for r in st)
    if failed:
        print(d, '有 %d 个板块成分股获取失败，未落盘' % failed, flush=True)
        return False
    pd.DataFrame(rows).to_csv(os.path.join(OUT, 'stocks_%s.csv' % d), index=False, encoding='utf-8-sig')
    print(d, '完成：%d 板块 %d 行' % (len(sec), len(rows)), flush=True)
    return True


def main():
    days = sys.argv[1:]
    if not days:
        raise SystemExit('请传入日期：python3 fetch_selected.py 2026-10-08 2026-09-30 ...')
    for d in days:
        if not os.path.exists(os.path.join(OUT, 'stocks_%s.csv' % d)):
            fetch_day(d)


if __name__ == '__main__':
    main()
