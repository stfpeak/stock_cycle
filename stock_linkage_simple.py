#!/usr/bin/env python3
"""
股票联动查询 - 简化版Web服务 V5
使用Python内置http.server，无依赖问题
启动: python stock_linkage_simple.py
访问: http://localhost:5001
"""

import os
import sys
import json
import sqlite3
import threading
import time
import importlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stock_linkage_finder import StockLinkageFinder

# 全局finder
print("正在初始化股票联动查找器 V5 ...")
finder = StockLinkageFinder()
print("初始化完成!")

# 涨停理由数据（CSV加载）
import csv
import os
import re

_limit_rows = []
_limit_csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'invest_logic', 'limit_list_ths_all.csv')
try:
    with open(_limit_csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            _limit_rows.append(row)
    print(f"加载涨停理由数据: {len(_limit_rows)} 行")
except Exception as e:
    print(f"加载涨停理由CSV失败: {e}")
    _limit_rows = []

# 建dict索引：按交易日分组（大幅减少线性扫描）
_limit_rows_by_date = {}
_limit_rows_by_code = {}
for _r in _limit_rows:
    _d = _r.get('trade_date', '')
    if _d:
        _limit_rows_by_date.setdefault(_d, []).append(_r)
    _c = (_r.get('ts_code', '') or '').replace('.SH','').replace('.SZ','').replace('.BJ','')
    if _c:
        _limit_rows_by_code.setdefault(_c, []).append(_r)

# ===== KPL涨停深挖数据（懒加载，zt_data/日JSON） =====
_KPL_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'zt_data')
_kpl_stock_index = {}           # stock_code → {stock_name, dates[]}
_kpl_reason_index = {}          # reason_tag → [{date, stock_code, ...}]
_kpl_rows = []                  # 所有已加载记录
_kpl_rows_by_date = {}          # date → [records]
_kpl_rows_by_stock = {}         # stock_code → [records]
_kpl_day_cache = {}             # date_fmt → records（已加载的日JSON缓存）
_kpl_unique_plates = {}         # plate_name → count
_kpl_unique_tags = {}           # reason_tag → count
_kpl_unique_concepts = {}       # concept → count
_kpl_stock_latest_tag = {}      # stock_code → {tag, date, reason_brief} (全量历史)
_kpl_day_files = []             # 所有日JSON文件名（不含路径），排序后

# 启动时加载索引文件
try:
    _idx_path = os.path.join(_KPL_DATA_DIR, 'index.json')
    if os.path.exists(_idx_path):
        _kpl_stock_index = json.load(open(_idx_path, 'r', encoding='utf-8'))
    _ridx_path = os.path.join(_KPL_DATA_DIR, 'reason_index.json')
    if os.path.exists(_ridx_path):
        _kpl_reason_index = json.load(open(_ridx_path, 'r', encoding='utf-8'))
    # 构建唯一板块/标签/概念索引
    for tag, entries in _kpl_reason_index.items():
        _kpl_unique_tags[tag] = len(entries)
        for e in entries:
            pn = e.get('plate_name', '')
            if pn:
                _kpl_unique_plates[pn] = _kpl_unique_plates.get(pn, 0) + 1
            concepts_str = e.get('concepts', '') or ''
            for c in concepts_str.split('、'):
                c = c.strip()
                if c:
                    _kpl_unique_concepts[c] = _kpl_unique_concepts.get(c, 0) + 1
            # 构建股票→最新reason_tag映射（全量历史）
            sc = e.get('stock_code', '')
            d = e.get('date', '')
            if sc and d:
                if sc not in _kpl_stock_latest_tag or d > _kpl_stock_latest_tag[sc]['date']:
                    _kpl_stock_latest_tag[sc] = {'tag': tag, 'date': d, 'reason_brief': e.get('reason_brief', '') or ''}
    # 扫描日JSON文件列表
    if os.path.isdir(_KPL_DATA_DIR):
        _kpl_day_files = sorted([f for f in os.listdir(_KPL_DATA_DIR) if f.endswith('.json') and f not in ('index.json', 'reason_index.json')])
    print(f"加载KPL涨停深挖索引: {len(_kpl_stock_index)}只股票, {len(_kpl_reason_index)}个reason_tag, {len(_kpl_day_files)}个日文件")
except Exception as e:
    print(f"加载KPL涨停深挖索引失败: {e}")


def _kpl_ensure_loaded(date_start=None, date_end=None):
    """按日期范围逐一加载日JSON到缓存"""
    if not _kpl_day_files:
        return
    # 确定要加载的文件
    to_load = []
    for fname in _kpl_day_files:
        d = fname.replace('.json', '')
        d_stripped = d.replace('-', '')
        if date_start and d_stripped < date_start:
            continue
        if date_end and d_stripped > date_end:
            continue
        if d in _kpl_day_cache:
            continue
        to_load.append((d, fname))
    if not to_load:
        return
    for d, fname in to_load:
        try:
            records = json.load(open(os.path.join(_KPL_DATA_DIR, fname), 'r', encoding='utf-8'))
            _kpl_day_cache[d] = records
            for r in records:
                _kpl_rows.append(r)
                _kpl_rows_by_date.setdefault(d, []).append(r)
                sc = r.get('stock_code', '')
                if sc:
                    _kpl_rows_by_stock.setdefault(sc, []).append(r)
        except Exception:
            pass

# Apply levistock timeout patch globally for sector_ranking_kph and get_pmsl
import levistock.stock.stock_fupanla_kph as _kph_mod
def _kpl_patched_post(host, params):
    import requests
    r = requests.post(host, data=params, headers=_kph_mod._HEADERS, timeout=30)
    return r.json()
_kph_mod._post = _kpl_patched_post


def _get_sniper_data(lookback=20):
    """
    构建精准狙击数据:
    - dates: [最新→最旧] 交易日列表 (YYYY-MM-DD)
    - data: { date: { reason_tag: [records] } }  (已过滤ST)
    - freq: { date: { tag: count } }  (日期为维度)
    - sorted_tags: [标签名] 按总数降序 (已过滤ST)
    - tag_totals: { tag: total_count }
    - top_tags: [标签名] 用于频度矩阵顶部的Top标签
    """
    if not _kpl_day_files:
        return {'dates': [], 'data': {}, 'freq': {}, 'sorted_tags': [], 'tag_totals': {}, 'top_tags': []}

    # 取最近 lookback 个日期
    trade_dates_set = set()
    for fname in _kpl_day_files:
        d = fname.replace('.json', '')
        trade_dates_set.add(d)

    # 如果需要，通过 finder.trade_dates 补充未加载的日期
    all_trade = getattr(finder, 'all_trade_dates', [])
    if all_trade:
        # all_trade 格式是 YYYYMMDD
        recent_raw = all_trade[-lookback:]
        recent = []
        for rd in recent_raw:
            fmt_date = rd[:4] + '-' + rd[4:6] + '-' + rd[6:8]
            recent.append(fmt_date)
    else:
        recent = sorted(trade_dates_set)[-lookback:]

    # 只保留在 KPL 数据中有文件的日期
    valid_dates = [d for d in recent if d in trade_dates_set]
    # 最新在前
    valid_dates.reverse()
    # 取最近10个交易日用于强榜频度排序
    rank_dates = valid_dates[:10]

    # 确保数据已加载
    if valid_dates:
        start = valid_dates[-1].replace('-', '')
        end = valid_dates[0].replace('-', '')
        _kpl_ensure_loaded(start, end)

    # 按 date→reason_tag 分组，过滤ST板块
    data = {}
    freq = {}  # { tag: { date: count } }
    for d in valid_dates:
        day_rows = _kpl_rows_by_date.get(d, [])
        tag_groups = {}
        for r in day_rows:
            tag = r.get('reason_tag', '') or '未分类'
            # 过滤ST板块
            name = (r.get('stock_name', '') or '').strip()
            if name.startswith('*ST') or name.startswith('ST') or '退' in name:
                continue
            if tag.startswith('ST') or tag == '退市' or '退' in tag:
                continue
            tag_groups.setdefault(tag, []).append(r)
        data[d] = tag_groups
        for tag, rows in tag_groups.items():
            freq.setdefault(tag, {})[d] = len(rows)

    # 标签按总频度降序排列
    tag_totals = {}
    for tag, tag_data in freq.items():
        tag_totals[tag] = sum(tag_data.values())
    sorted_tags = sorted(tag_totals.keys(), key=lambda t: -tag_totals[t])

    # 频度矩阵补全缺失日期的0
    for tag in sorted_tags:
        for d in valid_dates:
            if d not in freq.get(tag, {}):
                freq.setdefault(tag, {})[d] = 0

    # 同时构建以标签为维度的频度（前端兼容）: freq = { tag: { date: count } }
    freq_by_tag = {}
    for tag in sorted_tags:
        freq_by_tag[tag] = {}
        for d in valid_dates:
            freq_by_tag[tag][d] = freq.get(tag, {}).get(d, 0)

    # 以日期为维度的频度: freq_by_date = { date: { tag: count } }
    freq_by_date = {}
    for d in valid_dates:
        freq_by_date[d] = {}
        for tag in sorted_tags:
            freq_by_date[d][tag] = freq.get(tag, {}).get(d, 0)

    # 过滤非题材类标签（并购重组类）
    SNIPER_EXCLUDE_TAGS = {'并购重组', '股权转让', '实控人变更', '借壳上市',
                           '资产注入', '定增', '增发'}
    sorted_tags = [t for t in sorted_tags if t not in SNIPER_EXCLUDE_TAGS]
    # Top标签：取总数前40的标签用于频度矩阵
    top_tags = sorted_tags[:40]

    # 计算近10个交易日的频度用于强榜排序
    rank_tag_totals = {}
    for tag in sorted_tags:
        rank_tag_totals[tag] = sum(freq_by_tag.get(tag, {}).get(d, 0) for d in rank_dates)
    rank_sorted_tags = sorted(rank_tag_totals.keys(), key=lambda t: -rank_tag_totals[t])

    # 强榜标签（按10日频度 >= 10）
    strong_tags_list = [t for t in rank_sorted_tags if rank_tag_totals.get(t, 0) >= 5]

    # 强榜标签近10日逐日明细
    tag_rank_daily = {}
    for tag in rank_sorted_tags:
        tag_rank_daily[tag] = {}
        for d in rank_dates:
            tag_rank_daily[tag][d] = freq_by_tag.get(tag, {}).get(d, 0)

    top_20_strong = []
    # 先建立 code→reason_tag 和 code→reason_brief 映射（最新日期优先）
    code_tag_map = {}
    code_brief_map = {}
    for d in valid_dates:
        for r in _kpl_rows_by_date.get(d, []):
            c = r.get('stock_code', '')
            # valid_dates 最新在前，首次出现即最新日期的标签
            if c and c not in code_tag_map:
                code_tag_map[c] = r.get('reason_tag', '') or '未分类'
                code_brief_map[c] = r.get('reason_brief', '') or ''
    for tag in strong_tags_list:
        tag_stocks = {}  # code -> {code, name, reason_tag, max_lianban, zt_count, latest_date, concepts, reason_brief}
        for d in valid_dates:
            day_records = data.get(d, {}).get(tag, [])
            for r in day_records:
                code = r.get('stock_code', '')
                if not code:
                    continue
                name = r.get('stock_name', '')
                lb = int(r.get('lianban_count', 0) or 0)
                concepts = r.get('concepts', '')
                rb = r.get('reason_brief', '') or ''
                if code not in tag_stocks:
                    tag_stocks[code] = {'code': code, 'name': name, 'reason_tag': tag, 'max_lianban': 0, 'zt_count': 0, 'latest_date': '', 'concepts': concepts, 'reason_brief': rb}
                tag_stocks[code]['max_lianban'] = max(tag_stocks[code]['max_lianban'], lb)
                tag_stocks[code]['zt_count'] += 1
                if d > tag_stocks[code]['latest_date']:
                    tag_stocks[code]['latest_date'] = d
                    tag_stocks[code]['reason_brief'] = rb
                if concepts and not tag_stocks[code]['concepts']:
                    tag_stocks[code]['concepts'] = concepts
        sorted_stocks = sorted(tag_stocks.values(), key=lambda x: (-x['max_lianban'], -x['zt_count']))
        top_20_strong.append({'tag': tag, 'total': rank_tag_totals.get(tag, 0), 'rank_daily': tag_rank_daily.get(tag, {}), 'stocks': sorted_stocks})

    # 获取今日涨停数据，匹配KPL reason_tag，合并到最强梯队中
    today_zt_with_tag = []
    _all_today_stocks = []  # 保存所有akshare原始数据，用于找出未匹配标签的股票
    try:
        import akshare as ak
        import pandas as pd
        today_str = datetime.now().strftime('%Y%m%d')
        df = ak.stock_zt_pool_em(date=today_str)
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                code = str(int(row['代码'])).zfill(6)
                name = row.get('名称', '')
                first_time = int(row['首次封板时间']) if pd.notna(row.get('首次封板时间')) else 999999
                lianban = int(row['连板数']) if pd.notna(row.get('连板数')) else 0
                _all_today_stocks.append({
                    'code': code, 'name': name,
                    'first_time': first_time, 'lianban': lianban
                })
                reason_tag = code_tag_map.get(code, '')
                if reason_tag:
                    today_zt_with_tag.append({
                        'code': code, 'name': name,
                        'first_time': first_time, 'lianban': lianban,
                        'reason_tag': reason_tag
                    })
                else:
                    # 在所有KPL历史数据中查找该股票最近一次涨停原因标签
                    _found_tag = ''
                    for d in sorted(_kpl_rows_by_date.keys(), reverse=True):
                        for r in _kpl_rows_by_date.get(d, []):
                            if r.get('stock_code', '') == code:
                                _found_tag = r.get('reason_tag', '') or ''
                                if _found_tag:
                                    today_zt_with_tag.append({
                                        'code': code, 'name': name,
                                        'first_time': first_time, 'lianban': lianban,
                                        'reason_tag': _found_tag
                                    })
                                    code_brief_map[code] = r.get('reason_brief', '') or ''
                                break
                        if _found_tag:
                            break
                    # 仍未能匹配 → 从全量历史数据(reason_index)中查找最近一次标签
                    if not _found_tag and code in _kpl_stock_latest_tag:
                        _found_tag = _kpl_stock_latest_tag[code]['tag']
                        today_zt_with_tag.append({
                            'code': code, 'name': name,
                            'first_time': first_time, 'lianban': lianban,
                            'reason_tag': _found_tag
                        })
                        code_brief_map[code] = _kpl_stock_latest_tag[code].get('reason_brief', '') or ''
    except Exception:
        pass

    # 将今日涨停合并到对应标签卡片顶部，收集未匹配到Top标签的今日涨停
    tag_to_strong = {item['tag']: item for item in top_20_strong}
    other_today_zt = []
    for zt in today_zt_with_tag:
        tag = zt['reason_tag']
        if tag in tag_to_strong:
            item = tag_to_strong[tag]
            # 移除旧的KPL条目（避免重复），再插入今日涨停
            item['stocks'] = [s for s in item['stocks'] if s['code'] != zt['code']]
            rb = code_brief_map.get(zt['code'], '')
            # 今日涨停股票的题材从KPL历史数据中获取
            zt_concepts = ''
            if zt['code'] in code_tag_map:
                for d in valid_dates:
                    for r in _kpl_rows_by_date.get(d, []):
                        if r.get('stock_code', '') == zt['code'] and r.get('concepts', ''):
                            zt_concepts = r.get('concepts', '')
                            break
                    if zt_concepts:
                        break
            insert_entry = {
                'code': zt['code'], 'name': zt['name'],
                'max_lianban': zt['lianban'], 'zt_count': 0,
                'latest_date': today_str[:4]+'-'+today_str[4:6]+'-'+today_str[6:8],
                'concepts': zt_concepts,
                'reason_brief': rb,
                'reason_tag': tag,
                'is_today_zt': True, 'first_time': zt['first_time']
            }
            item['stocks'].insert(0, insert_entry)
        else:
            # 未匹配到任何Top分类
            rb = code_brief_map.get(zt['code'], '')
            other_today_zt.append({
                'code': zt['code'], 'name': zt['name'],
                'first_time': zt['first_time'], 'lianban': zt['lianban'],
                'reason_tag': tag, 'reason_brief': rb
            })

    # 收集完全未匹配标签的今日涨停股票
    untagged_today_zt = []
    matched_codes = set(zt['code'] for zt in today_zt_with_tag)
    for s in _all_today_stocks:
        if s['code'] not in matched_codes:
            untagged_today_zt.append({
                'code': s['code'], 'name': s['name'],
                'first_time': s['first_time'], 'lianban': s['lianban'],
                'reason_tag': '\u672a\u5339\u914d\u6807\u7b7e'
            })

    # 注入今日实时数据到频度分析结构（盘中实时刷新）
    _today_fmt = today_str[:4] + '-' + today_str[4:6] + '-' + today_str[6:8]
    if today_zt_with_tag and _today_fmt not in valid_dates:
        valid_dates.insert(0, _today_fmt)
        # 注入到 data
        today_tag_groups = {}
        for zt in today_zt_with_tag:
            tag = zt['reason_tag']
            today_tag_groups.setdefault(tag, []).append({
                'stock_code': zt['code'], 'stock_name': zt['name'],
                'reason_tag': tag, 'reason_brief': code_brief_map.get(zt['code'], ''),
                'lianban_count': str(zt['lianban']), 'plate_name': '', 'concepts': ''
            })
        data[_today_fmt] = today_tag_groups
        # 更新频度计数
        for tag, rows_today in today_tag_groups.items():
            freq.setdefault(tag, {})[_today_fmt] = len(rows_today)
            freq_by_tag.setdefault(tag, {})[_today_fmt] = len(rows_today)
            freq_by_date.setdefault(_today_fmt, {})[tag] = len(rows_today)
            tag_totals[tag] = tag_totals.get(tag, 0) + len(rows_today)
        # 补全今日其他标签的0值
        for tag in freq_by_tag:
            if _today_fmt not in freq_by_tag[tag]:
                freq_by_tag[tag][_today_fmt] = 0
                freq_by_date.setdefault(_today_fmt, {})[tag] = 0
        # 重算 sorted_tags 和 top_tags
        sorted_tags = sorted(tag_totals.keys(), key=lambda t: -tag_totals[t])
        top_tags = sorted_tags[:40]
        # 更新 rank_dates（10个交易日，含今日）
        rank_dates = valid_dates[:10]
        # 重算强榜频度
        rank_tag_totals = {}
        for tag in sorted_tags:
            rank_tag_totals[tag] = sum(freq_by_tag.get(tag, {}).get(d, 0) for d in rank_dates)
        rank_sorted_tags = sorted(rank_tag_totals.keys(), key=lambda t: -rank_tag_totals[t])
        # 重算 tag_rank_daily
        for tag in sorted_tags:
            tag_rank_daily[tag] = {}
            for d in rank_dates:
                tag_rank_daily[tag][d] = freq_by_tag.get(tag, {}).get(d, 0)

    # ===== 风向标 (wind_vane_his_kph) =====
    wind_vane_data = []
    wind_vane_date = ''
    try:
        import levistock as lk
        now_dt = datetime.now()
        today_ymd = now_dt.strftime('%Y-%m-%d')
        wv_finder = StockLinkageFinder()
        # 取上一个交易日
        prev_trade_dates = [d for d in getattr(wv_finder, 'all_trade_dates', []) if d < today_ymd.replace('-','')]
        wv_date_ymd = ''
        if prev_trade_dates:
            wv_date_ymd = prev_trade_dates[-1]
            wv_date_fmt = wv_date_ymd[:4] + '-' + wv_date_ymd[4:6] + '-' + wv_date_ymd[6:]
            wv_raw = lk.wind_vane_his_kph(wv_date_fmt)
            wind_vane_data = wv_raw
            wind_vane_date = wv_date_fmt
    except Exception:
        wind_vane_data = []

    # ===== 盘面梳理 (get_pmsl) =====
    pmsl_data = []
    pmsl_date = ''
    try:
        import levistock as lk
        now_dt = datetime.now()
        today_fmt = now_dt.strftime('%Y-%m-%d')
        pmsl_raw = lk.get_pmsl(today_fmt, st=500)
        if isinstance(pmsl_raw, dict) and 'List' in pmsl_raw:
            pmsl_data = pmsl_raw['List']
            pmsl_date = today_fmt
    except Exception:
        pmsl_data = []

    return {
        'dates': valid_dates,  # 最新在前
        'rank_dates': rank_dates,  # 近10个交易日
        'data': data,
        'freq': freq_by_tag,  # tag → date → count (前端兼容)
        'freq_by_date': freq_by_date,  # date → tag → count
        'sorted_tags': sorted_tags,
        'tag_totals': tag_totals,
        'top_tags': top_tags,
        'top_20_strong': top_20_strong,
        'today_zt_count': len(today_zt_with_tag) + len(untagged_today_zt),
        'other_today_zt': other_today_zt,
        'untagged_today_zt': untagged_today_zt,
        'wind_vane': wind_vane_data,
        'wind_vane_date': wind_vane_date,
        'pmsl': pmsl_data,
        'pmsl_date': pmsl_date
    }


def _kpl_get_search_text(r):
    """获取KPL记录的可搜索文本字段"""
    return (r.get('stock_name', '') + r.get('stock_code', '') + r.get('plate_name', '')
            + (r.get('reason_tag', '') or '') + (r.get('reason_brief', '') or '') + (r.get('concepts', '') or ''))


def _kpl_get_strict_text(r):
    """严格模式：仅搜索reason_tag字段"""
    return (r.get('reason_tag', '') or '')


def _kpl_is_st(r):
    """判断KPL记录是否为ST股票"""
    name = (r.get('stock_name', '') or '').strip()
    return name.startswith('*ST') or name.startswith('ST') or name.startswith('S') or '退' in name


def _kpl_search_rows(q, strict=False):
    """搜索KPL涨停深挖数据。支持单关键词、OR(|)、AND(&)。
    strict=True时，仅匹配reason_tag字段。"""
    q = q.strip()
    if not q:
        return {'results': [], 'mode': 'single', 'query': q, 'total_hits': 0, 'kw_results': {}, 'keywords': []}
    q_lower = q.lower()
    text_fn = _kpl_get_strict_text if strict else _kpl_get_search_text
    # OR模式
    if '|' in q:
        keywords = [k.strip() for k in q.split('|') if k.strip()]
        if len(keywords) < 2:
            return _kpl_search_rows(keywords[0], strict) if keywords else {'results': [], 'mode': 'single', 'query': q, 'total_hits': 0, 'kw_results': {}, 'keywords': []}
        combined = []
        kw_results = {}
        for kw in keywords:
            kw_lower = kw.lower()
            matched = [r for r in _kpl_rows if kw_lower in text_fn(r).lower()]
            kw_results[kw] = matched
            combined.extend(matched)
        # 去重（同一记录可能在多个关键词中匹配）
        seen = set()
        deduped = []
        for r in combined:
            key = r.get('date', '') + r.get('stock_code', '')
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        return {'results': deduped, 'mode': 'or', 'query': q, 'total_hits': len(deduped), 'kw_results': kw_results, 'keywords': keywords}
    # AND模式
    if '&' in q:
        keywords = [k.strip() for k in q.split('&') if k.strip()]
        if len(keywords) < 2:
            return _kpl_search_rows(keywords[0], strict) if keywords else {'results': [], 'mode': 'single', 'query': q, 'total_hits': 0, 'kw_results': {}, 'keywords': []}
        matched = list(_kpl_rows)
        for kw in keywords:
            kw_lower = kw.lower()
            matched = [r for r in matched if kw_lower in text_fn(r).lower()]
        return {'results': matched, 'mode': 'and', 'query': q, 'total_hits': len(matched), 'kw_results': {}, 'keywords': keywords}
    # 单关键词模式
    matched = [r for r in _kpl_rows if q_lower in text_fn(r).lower()]
    return {'results': matched, 'mode': 'single', 'query': q, 'total_hits': len(matched), 'kw_results': {}, 'keywords': []}


def _kpl_analyze_rows(q, date_start=None, date_end=None, no_st=None, strict=None):
    """KPL搜索+日期+ST+严格模式过滤"""
    # 先确保数据已加载
    ds = date_start.replace('-', '') if date_start else None
    de = date_end.replace('-', '') if date_end else None
    _kpl_ensure_loaded(ds, de)
    result = _kpl_search_rows(q, strict=(strict == '1'))
    results = result.get('results', [])
    if no_st == '1':
        results = [r for r in results if not _kpl_is_st(r)]
    if date_start:
        results = [r for r in results if ((r.get('date', '') or '').replace('-', '')) >= ds]
    if date_end:
        results = [r for r in results if ((r.get('date', '') or '').replace('-', '')) <= de]
    results.sort(key=lambda x: x.get('date', ''), reverse=True)
    result['results'] = results
    result['total_hits'] = len(results)
    return result


def _kpl_suggest_rows(q):
    """从KPL索引中搜索自动补全建议"""
    q = q.strip().lower()
    if not q:
        return {'stocks': [], 'reason_tags': [], 'plates': [], 'concepts': []}
    # 股票匹配
    stock_results = []
    for code, info in _kpl_stock_index.items():
        name = info.get('stock_name', '')
        if q in name.lower() or q in code.lower():
            stock_results.append({'name': name, 'code': code, 'count': len(info.get('dates', []))})
            if len(stock_results) >= 5:
                break
    # reason_tag匹配
    tag_results = []
    for tag, entries in _kpl_reason_index.items():
        if q in tag.lower():
            tag_results.append({'tag': tag, 'count': len(entries)})
            if len(tag_results) >= 5:
                break
    # 板块匹配
    plate_results = []
    for pn, cnt in sorted(_kpl_unique_plates.items(), key=lambda x: -x[1]):
        if q in pn.lower():
            plate_results.append({'plate': pn, 'count': cnt})
            if len(plate_results) >= 5:
                break
    # 概念匹配
    concept_results = []
    for c, cnt in sorted(_kpl_unique_concepts.items(), key=lambda x: -x[1]):
        if q in c.lower():
            concept_results.append({'concept': c, 'count': cnt})
            if len(concept_results) >= 5:
                break
    return {'stocks': stock_results, 'reason_tags': tag_results, 'plates': plate_results, 'concepts': concept_results}


def _search_limit_rows(q):
    """搜索涨停理由数据。支持单关键词、OR(|)、AND(&)三种模式。
    返回 {results: [...], mode: 'single'|'or'|'and', query: str}
    """
    q = q.strip()
    if not q:
        return {'results': [], 'mode': 'single', 'query': q}

    q_lower = q.lower()

    # OR模式: 关键词用 | 分隔
    if '|' in q:
        keywords = [k.strip() for k in q.split('|') if k.strip()]
        if len(keywords) < 2:
            return _search_limit_rows(keywords[0]) if keywords else {'results': [], 'mode': 'single', 'query': q}
        combined = []
        kw_results = {}
        for kw in keywords:
            kw_lower = kw.lower()
            matched = [r for r in _limit_rows
                       if kw_lower in (r.get('name', '') + r.get('lu_desc', '')).lower()]
            kw_results[kw] = matched
            combined.extend(matched)
        # 去重并按日期倒序
        seen = set()
        deduped = []
        for r in combined:
            uid = r.get('ts_code', '') + r.get('trade_date', '')
            if uid not in seen:
                seen.add(uid)
                deduped.append(r)
        deduped.sort(key=lambda x: x.get('trade_date', ''), reverse=True)
        return {'results': deduped, 'mode': 'or', 'query': q, 'kw_results': kw_results, 'keywords': keywords}

    # AND模式: 关键词用 & 分隔
    if '&' in q:
        keywords = [k.strip() for k in q.split('&') if k.strip()]
        if len(keywords) < 2:
            return _search_limit_rows(keywords[0]) if keywords else {'results': [], 'mode': 'single', 'query': q}
        result = list(_limit_rows)
        for kw in keywords:
            kw_lower = kw.lower()
            result = [r for r in result
                      if kw_lower in (r.get('name', '') + r.get('lu_desc', '')).lower()]
        result.sort(key=lambda x: x.get('trade_date', ''), reverse=True)
        return {'results': result, 'mode': 'and', 'query': q}

    # 单关键词模式
    kw_lower = q_lower
    result = [r for r in _limit_rows
              if kw_lower in (r.get('name', '') + r.get('lu_desc', '')).lower()]
    result.sort(key=lambda x: x.get('trade_date', ''), reverse=True)
    return {'results': result, 'mode': 'single', 'query': q}


def _analyze_limit_rows(q, date_start=None, date_end=None, no_st=None):
    """分析涨停理由搜索，支持日期过滤和ST过滤。返回 results + total_hits + mode"""
    result = _search_limit_rows(q)
    results = result.get('results', [])
    # 按日期过滤
    if date_start:
        ds = date_start.replace('-', '')
        results = [r for r in results if (r.get('trade_date', '') or '') >= ds]
    if date_end:
        de = date_end.replace('-', '')
        results = [r for r in results if (r.get('trade_date', '') or '') <= de]
    # 过滤ST
    if no_st == '1':
        results = [r for r in results if not _is_st(r)]
    results.sort(key=lambda x: x.get('trade_date', ''), reverse=True)
    result['results'] = results
    result['total_hits'] = len(results)
    return result


def _is_st(r):
    """判断涨停理由记录是否为ST股票"""
    name = (r.get('name', '') or '').strip()
    return name.startswith('*ST') or name.startswith('ST') or name.startswith('S')


def _parse_chain_count(tag):
    """解析tag字段中的连板数。如'3天3板'→3，'首板'→1，'2板'→2"""
    if not tag:
        return 1
    tag = tag.strip()
    import re
    m = re.search(r'(\d+)天(\d+)板', tag)
    if m:
        return int(m.group(2))
    m = re.search(r'(\d+)板', tag)
    if m:
        return int(m.group(1))
    return 1


def _analyze_abnormal_movement(lookback=20):
    """分析近N个交易日涨幅>9%的异动股票，按最后一次异动日期分组"""
    # 1. 获取日期范围（多取5天做buffer）
    start_idx = max(0, len(finder.trade_dates) - lookback - 5)
    start_date = finder.trade_dates[start_idx]
    start_date_str = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"

    # 2. 批量SQL查询kline数据库
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'stocks_kline.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT stock_code, trade_date, change_pct
        FROM kline_daily
        WHERE trade_date >= ? AND change_pct > 9
        ORDER BY stock_code, trade_date
    """, [start_date_str])
    rows = cursor.fetchall()
    conn.close()

    # 3. 按股票分组，找到最后一个涨幅>9%的日期
    raw = {}
    for code, date, pct in rows:
        d = date.replace('-', '')
        if code not in raw:
            raw[code] = []
        raw[code].append({'date': d, 'pct': pct})

    # 4. 按最后异动日期分组（只保留近lookback个交易日内的异动）
    valid_dates = set(finder.trade_dates[-lookback:])
    by_last_date = {}
    by_last_date_info = {}  # {code: {'date': YYYYMMDD, 'pct': float}}
    for code, days in raw.items():
        valid_days = [d for d in days if d['date'] in valid_dates]
        if not valid_days:
            continue
        last_date = valid_days[-1]['date']
        # 过滤ST股票
        name = finder.get_stock_name(code)
        if name.startswith('ST') or name.startswith('*ST'):
            continue
        # 只保留主板（00/60）和创业板科创板（30/68），过滤北交所/三板等
        if not (code.startswith('00') or code.startswith('60') or code.startswith('30') or code.startswith('68')):
            continue
        if last_date not in by_last_date:
            by_last_date[last_date] = []
        by_last_date[last_date].append(code)
        by_last_date_info[code] = {
            'date': f"{last_date[:4]}-{last_date[4:6]}-{last_date[6:]}",
            'pct': round(valid_days[-1]['pct'], 2)
        }

    # 5. 获取股票信息（名称、概念等）
    all_stocks = {}
    for codes in by_last_date.values():
        for code in codes:
            if code not in all_stocks:
                name = finder.get_stock_name(code)
                concepts = finder.get_stock_concepts(code)
                info = by_last_date_info.get(code, {})
                all_stocks[code] = {
                    'code': code,
                    'name': name,
                    'concepts': concepts,
                    'last_alert_date': info.get('date', ''),
                    'last_alert_pct': info.get('pct', 0)
                }

    # 6. 日期转为YYYY-MM-DD格式并按倒序排列
    result = {}
    for date_str in sorted(by_last_date.keys(), reverse=True):
        display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        result[display_date] = [all_stocks[c] for c in by_last_date[date_str] if c in all_stocks]

    return {
        'dates': list(result.keys()),
        'data': result,
        'update_time': datetime.now().strftime('%m-%d %H:%M')
    }


def _screener_lianban_stocks():
    """筛选连板和大涨股票，返回5个分类用于N字战法页面前置卡片"""
    import sqlite3, os
    from datetime import datetime

    lookback_20 = 20
    lookback_15 = 15
    lookback_10 = 10

    # 日期范围（多取5天buffer）
    start_idx_20 = max(0, len(finder.trade_dates) - lookback_20 - 5)
    start_date_20 = finder.trade_dates[start_idx_20]
    start_date_20_str = f"{start_date_20[:4]}-{start_date_20[4:6]}-{start_date_20[6:]}"

    # 批量SQL查询kline数据库
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'stocks_kline.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT stock_code, trade_date, change_pct
        FROM kline_daily
        WHERE trade_date >= ? AND change_pct > 9
        ORDER BY stock_code, trade_date
    """, [start_date_20_str])
    rows = cursor.fetchall()
    conn.close()

    # 有效交易日集合
    valid_dates_20 = set(finder.trade_dates[-lookback_20:])
    valid_dates_15 = set(finder.trade_dates[-lookback_15:])
    valid_dates_10 = set(finder.trade_dates[-lookback_10:])

    # 交易日索引（用于连续连板判定）
    trade_date_idx = {d: i for i, d in enumerate(finder.all_trade_dates)}

    # 按股票分组
    raw = {}
    for code, date, pct in rows:
        d = date.replace('-', '')
        if d not in valid_dates_20:
            continue
        if code not in raw:
            raw[code] = []
        raw[code].append({'date': d, 'pct': pct})

    def _max_lianban(dates):
        """计算给定涨停日期列表的最大连续连板数"""
        sd = sorted(dates)
        if not sd:
            return 0
        cur = 1
        mx = 1
        for i in range(1, len(sd)):
            d1 = sd[i - 1]
            d2 = sd[i]
            idx1 = trade_date_idx.get(d1)
            idx2 = trade_date_idx.get(d2)
            if idx1 is not None and idx2 is not None and idx2 - idx1 == 1:
                cur += 1
                mx = max(mx, cur)
            else:
                cur = 1
        return mx

    def _get_board(code):
        if code.startswith(('300', '301')):
            return 'gem'
        if code.startswith(('688', '689')):
            return 'star'
        if code.startswith(('00', '60', '000', '001', '002', '003', '600', '601', '603', '605')):
            return 'main'
        return 'other'

    cat1, cat2, cat3, cat4, cat5 = [], [], [], [], []

    for code, days in raw.items():
        name = finder.get_stock_name(code)
        if not name or name.startswith('ST') or name.startswith('*ST'):
            continue

        board = _get_board(code)
        if board == 'other':
            continue

        # 筛选各窗口内的日期
        days_20 = [d for d in days if d['date'] in valid_dates_20]
        days_15 = [d for d in days if d['date'] in valid_dates_15]
        days_10 = [d for d in days if d['date'] in valid_dates_10]

        # 涨停日期（按板块不同阈值）
        if board == 'main':
            zt_dates_20 = [d['date'] for d in days_20 if d['pct'] > 9.5]
        else:
            zt_dates_20 = [d['date'] for d in days_20 if d['pct'] > 19.5]

        concepts = finder.get_stock_concepts(code)
        stock_info = {
            'code': code,
            'name': name,
            'concepts': concepts,
        }

        if board == 'main':
            max_lb = _max_lianban(zt_dates_20)
            if max_lb >= 3:
                stock_info['lianban'] = max_lb
                cat1.append(stock_info)
            elif max_lb == 2:
                stock_info['lianban'] = 2
                cat2.append(stock_info)
            elif max_lb >= 1:
                # 近15日有涨停但无2连板
                zt_dates_15 = [d['date'] for d in days_15 if d['pct'] > 9.5]
                if zt_dates_15:
                    max_lb_15 = _max_lianban(zt_dates_15)
                    if max_lb_15 < 2:
                        stock_info['lianban'] = max_lb_15
                        cat3.append(stock_info)
        elif board in ('gem', 'star'):
            if zt_dates_20:
                cat4.append(stock_info)
            else:
                # 近10日涨幅>10%但无涨停
                has_big = any(10 < d['pct'] <= 19.5 for d in days_10)
                if has_big:
                    cat5.append(stock_info)

    return {
        'sc1': cat1,
        'sc2': cat2,
        'sc3': cat3,
        'sc4': cat4,
        'sc5': cat5,
        'update_time': datetime.now().strftime('%m-%d %H:%M')
    }



    """搜索涨停理由并进行综合分析(概念频度/个股频度/日期分布/连板总结)。
    支持单关键词、OR(|)、AND(&)三种模式 + 日期范围过滤 + ST过滤。
    返回完整搜索结果（无限制）+ kw_results（用于OR模式分段展示）。
    """
    search_result = _search_limit_rows(q)
    results = search_result.get('results', [])
    mode = search_result.get('mode', 'single')
    keywords = search_result.get('keywords', [])
    kw_results = search_result.get('kw_results', {})

    # 日期过滤函数
    def _filter_dates(rows):
        if not rows:
            return rows
        filtered = list(rows)
        if date_start:
            ds = date_start.replace('-', '')
            filtered = [r for r in filtered if (r.get('trade_date', '') or '') >= ds]
        if date_end:
            de = date_end.replace('-', '')
            filtered = [r for r in filtered if (r.get('trade_date', '') or '') <= de]
        return filtered

    # ST过滤函数
    def _filter_st(rows):
        if not rows:
            return rows
        if no_st == '1':
            return [r for r in rows if 'ST' not in (r.get('name', '') or '').upper()]
        return rows

    # 应用日期过滤
    results = _filter_dates(results)
    if mode == 'or' and kw_results:
        for kw in keywords:
            kw_results[kw] = _filter_dates(kw_results.get(kw, []))

    # 应用ST过滤
    results = _filter_st(results)
    if mode == 'or' and kw_results:
        for kw in keywords:
            kw_results[kw] = _filter_st(kw_results.get(kw, []))

    total_hits = len(results)

    # 概念频度：将lu_desc按+分割统计
    concept_freq = {}
    for r in results:
        lu_desc = r.get('lu_desc', '') or ''
        for c in lu_desc.split('+'):
            c = c.strip()
            if c:
                concept_freq[c] = concept_freq.get(c, 0) + 1
    concept_freq_list = [{'concept': c, 'count': n}
                         for c, n in sorted(concept_freq.items(), key=lambda x: -x[1])[:30]]

    # 个股频度：按股票代码聚合
    stock_freq = {}
    for r in results:
        code = (r.get('ts_code', '') or '').replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        name = r.get('name', '') or ''
        tag = r.get('tag', '') or ''
        date = r.get('trade_date', '') or ''
        chain = _parse_chain_count(tag)
        if code not in stock_freq:
            stock_freq[code] = {'name': name, 'code': code, 'count': 0, 'max_chain': 0, 'last_date': ''}
        stock_freq[code]['count'] += 1
        stock_freq[code]['max_chain'] = max(stock_freq[code]['max_chain'], chain)
        if date > stock_freq[code]['last_date']:
            stock_freq[code]['last_date'] = date
    stock_freq_list = sorted(stock_freq.values(), key=lambda x: -x['count'])[:30]

    # 日期分布
    date_dist = {}
    for r in results:
        d = r.get('trade_date', '') or ''
        if d:
            date_dist[d] = date_dist.get(d, 0) + 1
    date_dist_list = [{'date': d, 'count': date_dist[d]} for d in sorted(date_dist.keys())]

    # 按连板总结：按概念分组，股票按最高连板降序
    summary_by_concept = {}
    for r in results:
        lu_desc = r.get('lu_desc', '') or ''
        concepts = [c.strip() for c in lu_desc.split('+') if c.strip()]
        code = (r.get('ts_code', '') or '').replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        name = r.get('name', '') or ''
        tag = r.get('tag', '') or ''
        date = r.get('trade_date', '') or ''
        chain = _parse_chain_count(tag)

        for c in concepts:
            if c not in summary_by_concept:
                summary_by_concept[c] = {'total_stocks': 0, 'total_hits': 0, 'stocks': {}}
            summary_by_concept[c]['total_hits'] += 1
            if code not in summary_by_concept[c]['stocks']:
                summary_by_concept[c]['stocks'][code] = {'name': name, 'code': code, 'count': 0, 'max_chain': 0, 'last_date': ''}
            summary_by_concept[c]['stocks'][code]['count'] += 1
            summary_by_concept[c]['stocks'][code]['max_chain'] = max(
                summary_by_concept[c]['stocks'][code]['max_chain'], chain)
            if date > summary_by_concept[c]['stocks'][code]['last_date']:
                summary_by_concept[c]['stocks'][code]['last_date'] = date

    # 整理summary输出：stocks转为列表并按max_chain降序
    final_summary = {}
    for c, info in summary_by_concept.items():
        stocks_list = sorted(info['stocks'].values(), key=lambda x: (-x['max_chain'], -x['count']))
        final_summary[c] = {
            'total_stocks': len(stocks_list),
            'total_hits': info['total_hits'],
            'stocks': stocks_list
        }

    return {
        'query': q, 'mode': mode,
        'date_start': date_start or '', 'date_end': date_end or '',
        'total_hits': total_hits,
        'results': results,
        'kw_results': kw_results,
        'keywords': keywords,
        'concept_freq': concept_freq_list,
        'stock_freq': stock_freq_list,
        'date_distribution': date_dist_list,
        'summary_by_concept': final_summary,
    }


def _suggest_limit_rows(q):
    """搜索建议：返回匹配的股票和概念关键词"""
    q_lower = q.strip().lower()
    if not q_lower:
        return {'stocks': [], 'concepts': []}

    seen_stocks = {}
    stock_results = []
    concept_count = {}

    for r in _limit_rows:
        name = r.get('name', '') or ''
        code = (r.get('ts_code', '') or '').replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        lu_desc = r.get('lu_desc', '') or ''
        combined = (name + code + lu_desc).lower()
        if q_lower not in combined:
            continue

        # 收集匹配的股票
        if code not in seen_stocks and len(stock_results) < 5:
            seen_stocks[code] = True
            stock_results.append({'name': name, 'code': code})

        # 收集匹配的概念关键词
        for c in lu_desc.split('+'):
            c = c.strip()
            if c and q_lower in c.lower():
                concept_count[c] = concept_count.get(c, 0) + 1

    concepts_sorted = sorted(concept_count.items(), key=lambda x: -x[1])[:5]
    return {
        'stocks': stock_results,
        'concepts': [{'concept': c, 'count': n} for c, n in concepts_sorted],
    }


def _get_stock_sub_tags(ts_code):
    """从涨停理由数据中提取某只股票的细分标签（子概念）"""
    tags = set()
    code_clean = ts_code.replace('.SH','').replace('.SZ','').replace('.BJ','')
    for r in _limit_rows:
        r_code = (r.get('ts_code','') or '').replace('.SH','').replace('.SZ','').replace('.BJ','')
        if r_code == code_clean:
            lu_desc = r.get('lu_desc', '') or ''
            for c in lu_desc.split('+'):
                c = c.strip()
                if c:
                    tags.add(c)
    return sorted(tags)


# 数据更新状态
_update_in_progress = False
_update_progress_msg = ""

# 分析结果缓存（大幅减少重复计算）
_cache = {}  # {key: {'data': ..., 'time': timestamp}}
_CACHE_TTL = 3600  # 缓存有效期1小时
_CACHE_MAX_SIZE = 200  # 最多缓存200个key，超过时淘汰最旧的

def _get_cached(key, ttl=None):
    """获取缓存，过期返回None"""
    entry = _cache.get(key)
    if entry and (time.time() - entry['time'] < (ttl or _CACHE_TTL)):
        return entry['data']
    return None

def _set_cache(key, data):
    """设置缓存（超过上限时淘汰最旧的1/3）"""
    _cache[key] = {'data': data, 'time': time.time()}
    if len(_cache) > _CACHE_MAX_SIZE:
        # 按时间排序，保留最新的 2/3
        sorted_keys = sorted(_cache.keys(), key=lambda k: _cache[k]['time'])
        for old_key in sorted_keys[:len(sorted_keys) // 3]:
            del _cache[old_key]

def _invalidate_cache(prefix=None):
    """清除缓存。prefix=None清全部，否则清匹配前缀的key"""
    if prefix is None:
        _cache.clear()
    else:
        for k in list(_cache.keys()):
            if k.startswith(prefix):
                del _cache[k]

def _do_data_update():
    """后台线程：按天批量拉取全市场K线 + 重载finder内存数据"""
    global _update_in_progress, _update_progress_msg

    import importlib
    try:
        import update_data_fast
        importlib.reload(update_data_fast)  # 确保使用最新代码

        # Step 1: 扩展交易日历
        _update_progress_msg = "📅 检查交易日历..."
        added_days = update_data_fast.extend_trade_calendar()
        if added_days > 0:
            _update_progress_msg = f"📅 交易日历新增 {added_days} 天"
        else:
            _update_progress_msg = "📅 交易日历已最新"

        # Step 2: 检查缺失数据
        _update_progress_msg = "🔍 检查K线数据完整性..."
        missing = update_data_fast.get_db_missing_dates()

        if not missing:
            _update_progress_msg = "✅ 数据已是最新，无需更新"
            _invalidate_cache()
            return

        # Step 3: 快速拉取缺失数据（盘中使用0.15s间隔，非盘中使用0.3s）
        delay = 0.15
        now_hour = datetime.now().hour
        if 9 <= now_hour <= 16:
            delay = 0.3  # 盘中稍慢避免触发限流

        _update_progress_msg = f"📥 正在拉取 {len(missing)} 天数据..."
        result = update_data_fast.fetch_and_save_missing_dates(
            missing, delay=delay,
            progress_callback=lambda msg: setattr(sys.modules[__name__], '_update_progress_msg', msg)
        )

        # Step 4: 重载finder内存数据
        _update_progress_msg = "🔄 正在重载涨停数据到内存..."
        finder._load_trade_calendar()
        finder._load_zt_pool_data()
        finder._load_zt_from_db()
        finder._merge_zt_data()
        _update_progress_msg = f"✅ 更新完成! 拉取 {result.get('success', 0)}/{len(missing)} 天, 新增 {result.get('records', 0)} 条记录"
        _invalidate_cache()
    except Exception as e:
        import traceback
        _update_progress_msg = f"❌ 更新失败: {e}"
        traceback.print_exc()
    finally:
        _update_in_progress = False


def _get_zt_from_akshare():
    """用akshare拉取最新交易日涨停板数据+关联概念。无数据返回[]，前端显示API不通"""
    import akshare as ak
    import pandas as pd

    today_ymd = datetime.now().strftime('%Y%m%d')
    trade_dates = getattr(finder, 'all_trade_dates', [])
    if not trade_dates:
        return []

    # 今天是否交易日：是则用今天，否则用最近交易日
    date_str = today_ymd if today_ymd in trade_dates else trade_dates[-1]

    try:
        df = ak.stock_zt_pool_em(date=date_str)
        if df is None or df.empty:
            return []
    except Exception:
        return []

    result = []
    for _, row in df.iterrows():
        code = str(int(row['代码'])).zfill(6)
        concepts = finder.get_stock_concepts(code)
        result.append({
            'code': code,
            'name': str(row['名称']),
            'lianban': int(row['连板数']) if pd.notna(row.get('连板数')) else 0,
            'first_time': int(row['首次封板时间']) if pd.notna(row.get('首次封板时间')) else 999999,
            'zb_count': int(row['炸板次数']) if pd.notna(row.get('炸板次数')) else 0,
            'concepts': list(concepts),
            'concept_count': len(concepts),
            'trade_date': date_str,
        })

    result.sort(key=lambda x: x['first_time'])
    return result


HTML_PAGE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>涨停深挖</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    min-height: 100vh;
    color: #eee;
    padding: 20px;
}
.container { max-width: 96vw; margin: 0 auto; }
h1 { color: #00d4ff; text-align: center; margin: 20px 0 5px 0; font-size: 2em; }
.sub { text-align: center; color: #666; margin-bottom: 20px; font-size: 0.85em; }

.search-box {
    background: #16213e;
    border-radius: 12px;
    padding: 20px 25px;
    margin: 15px 0;
}
.input-row { display: flex; gap: 12px; flex-wrap: wrap; }
.input-item { flex: 1; min-width: 180px; position: relative; }
label { display: block; margin-bottom: 5px; color: #00d4ff; font-size: 0.9em; }
input[type=text] {
    width: 100%;
    padding: 10px 14px;
    border: 2px solid #0f3460;
    border-radius: 8px;
    background: #1a1a2e;
    color: #eee;
    font-size: 15px;
}
input[type=date] {
    width: 100%;
    padding: 9px 10px;
    border: 2px solid #0f3460;
    border-radius: 8px;
    background: #1a1a2e;
    color: #eee;
    font-size: 14px;
    font-family: inherit;
    appearance: none;
    -webkit-appearance: none;
    -moz-appearance: none;
    min-height: 38px;
    box-sizing: border-box;
}
input[type=date]::-webkit-calendar-picker-indicator {
    filter: invert(0.7);
    cursor: pointer;
    padding: 4px;
}
input[type=date]::-webkit-datetime-edit { color: #eee; }
input[type=date]::-webkit-datetime-edit-fields-wrapper { color: #eee; }
input[type=date]::-webkit-datetime-edit-text { color: #888; }
input[type=checkbox] {
    width: 16px;
    height: 16px;
    accent-color: #00d4ff;
    cursor: pointer;
    vertical-align: middle;
    margin-right: 4px;
}
input:focus { border-color: #00d4ff; outline: none; }
.checkbox-label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: #ccc;
    font-size: 0.9em;
    cursor: pointer;
    white-space: nowrap;
    user-select: none;
    padding: 8px 0;
}
.filter-bar {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 10px;
}
.date-group {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}
.date-group label {
    display: inline;
    margin-bottom: 0;
    color: #aaa;
    font-size: 0.85em;
}
.date-group input[type=date] {
    width: 140px;
}
.btn-group {
    display: flex;
    align-items: center;
    gap: 6px;
}
.kpl-status-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 2px 0 6px;
    padding: 5px 12px;
    background: rgba(15,52,96,0.4);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 1px solid rgba(0,212,255,0.1);
    border-radius: 8px;
    font-size: 0.78em;
}
.kpl-status-bar .status-text {
    color: #aaa;
}
.kpl-status-bar .update-btn {
    background: #1a1a2e;
    border: 1px solid #0f3460;
    border-radius: 6px;
    cursor: pointer;
    padding: 2px 10px;
    font-size: 0.9em;
    color: #ccc;
    line-height: 1.8;
    transition: all 0.2s;
}
.kpl-status-bar .update-btn:hover {
    border-color: #00d4ff;
    color: #fff;
    background: rgba(0,212,255,0.08);
}

/* Search Suggestions */
.suggestions {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    background: #16213e;
    border: 1px solid #0f3460;
    border-radius: 0 0 8px 8px;
    max-height: 400px;
    overflow-y: auto;
    z-index: 1000;
    display: none;
    box-shadow: 0 8px 20px rgba(0,0,0,0.5);
}
.suggestions.active { display: block; }
.suggestion-item {
    padding: 9px 12px;
    cursor: pointer;
    border-bottom: 1px solid #0f3460;
    display: flex;
    justify-content: space-between;
}
.suggestion-item:hover { background: #0f3460; }
.sug-code { color: #00d4ff; font-weight: bold; }
.sug-meta { color: #888; font-size: 0.85em; }

button {
    padding: 10px 26px;
    background: linear-gradient(135deg, #00d4ff, #0066cc);
    border: none;
    border-radius: 8px;
    color: #fff;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
}
button:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(0,212,255,0.3); }
button:disabled { background: #555; cursor: not-allowed; }
.btn-con { background: #0f3460; border: 1px solid #00d4ff; font-weight: 400; margin-left: 8px; }

/* Tabs */
.tabs { display: flex; gap: 0; margin: 15px 0; }
.tab {
    padding: 9px 24px;
    background: #1a1a2e;
    border: 1px solid #0f3460;
    cursor: pointer;
    color: #888;
    font-size: 0.9em;
}
.tab:first-child { border-radius: 8px 0 0 8px; }
.tab:last-child { border-radius: 0 8px 8px 0; }
.tab.active { background: #0f3460; color: #00d4ff; border-color: #00d4ff; }
.tab-content { display: none; }
.tab-content.active { display: block; }

/* Mobile touch optimization */
@media (max-width: 768px) {
    body { padding: 10px; }
    h1 { font-size: 1.3em; margin: 12px 0 3px 0; }
    .sub { font-size: 0.75em; margin-bottom: 10px; }
    .search-box { padding: 12px 14px; margin: 8px 0; }
    .input-row { gap: 8px; }
    .input-item { min-width: 100%; }
    input[type=text] { padding: 12px 12px; font-size: 16px; }
    button { padding: 12px 20px; font-size: 15px; min-height: 44px; }
    .tab { padding: 12px 10px; font-size: 0.78em; flex: 1; text-align: center; }
    .tabs { flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch; }
    label { font-size: 0.82em; }
    .suggestion-item { padding: 12px 10px; }
    .rt-zt-table { font-size: 0.75em; }
    .rt-zt-table td, .rt-zt-table th { padding: 8px 4px; }
    .rt-section { padding: 10px; }
    .rt-section h3 { font-size: 0.85em; }
    .concept-chip { font-size: 0.7em; padding: 2px 5px; margin: 1px; }
    .rt-lb { font-size: 0.75em; padding: 2px 6px; min-width: 24px; }
    .stock-info { flex-direction: column; gap: 4px; }
    .stock-info .zt-count { font-size: 0.8em; }
    .refresh-banner { font-size: 0.75em; padding: 5px; }
    .rt-summary-item .rt-val { font-size: 1.1em; }
    .rt-summary-item .rt-label { font-size: 0.65em; }
    #updateArea { font-size: 0.78em; }
    #updateHint { font-size: 0.7em; }
    .count-badge { font-size: 0.65em; }
    .peak-item { padding: 3px 8px; font-size: 0.75em; }
    .rhythm-cell { min-width: 28px; height: 28px; font-size: 0.65em; }
    .event-row td { padding: 6px 8px; }
    .date-group { width: 100%; }
    .date-group input[type=date] { flex: 1; min-width: 0; width: auto; }
    .filter-bar { flex-direction: column; align-items: stretch; }
    .btn-group { width: 100%; }
    .btn-group button { flex: 1; }
}

/* Result */
.result {
    background: #16213e;
    border-radius: 12px;
    padding: 20px;
    margin: 15px 0;
}
.stock-info {
    display: flex;
    align-items: center;
    gap: 15px;
    margin-bottom: 15px;
    padding-bottom: 12px;
    border-bottom: 1px solid #333;
    flex-wrap: wrap;
}
.code-badge { background: #e94560; padding: 6px 14px; border-radius: 15px; font-weight: bold; }
.stock-name { font-size: 1.3em; color: #00d4ff; font-weight: 600; }
.zt-count { color: #888; }
.badge { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 0.8em; margin: 2px; }
.badge-pool { background: #0f3460; border: 1px solid #00d4ff; color: #00d4ff; }
.badge-db { background: #1a3a1a; border: 1px solid #00ff88; color: #00ff88; }
.tag {
    display: inline-block;
    background: #0f3460;
    border: 1px solid #00d4ff;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.85em;
    margin: 2px;
}
.zt-date-tag {
    display: inline-block;
    background: #1a1a2e;
    padding: 2px 8px;
    border-radius: 4px;
    margin: 2px;
    font-size: 0.85em;
    border: 1px solid #333;
}

table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 0.9em; }
th { background: #0f3460; color: #00d4ff; padding: 10px; text-align: left; }
th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { background: #1a4a7a; }
td { padding: 8px 10px; border-bottom: 1px solid #333; }
tr:hover { background: #1a1a2e; }
tr.clickable { cursor: pointer; }
tr.clickable:hover { background: #0f3460; }
.link-stock-name { cursor:pointer; color:#00d4ff; }
.link-stock-name:hover { text-decoration:underline; }

/* Sort controls */
.sort-bar { display: flex; align-items: center; gap: 6px; margin: 10px 0; flex-wrap: wrap; }
.sort-label { color: #888; font-size: 0.85em; margin-right: 4px; }
.sort-btn {
    padding: 4px 12px;
    border: 1px solid #0f3460;
    border-radius: 6px;
    background: #1a1a2e;
    color: #aaa;
    cursor: pointer;
    font-size: 0.85em;
    transition: all 0.2s;
}
.sort-btn:hover { border-color: #00d4ff; color: #00d4ff; }
.sort-btn.active { background: #0f3460; border-color: #00d4ff; color: #00d4ff; }
.sort-btn.asc::after { content: ' ▲'; font-size: 0.7em; }
.sort-btn.desc::after { content: ' ▼'; font-size: 0.7em; }
.top-n-badge {
    display: inline-block;
    background: #e94560;
    color: #fff;
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 0.8em;
    margin-left: 8px;
}

.prob-cell { display: flex; align-items: center; gap: 6px; }
.prob-bar { width: 60px; height: 16px; background: #0f3460; border-radius: 3px; overflow: hidden; }
.prob-fill { height: 100%; }
.prob-fill.t0 { background: linear-gradient(90deg, #ff6b6b, #ff0022); }
.prob-fill.t1 { background: linear-gradient(90deg, #e94560, #ff6b6b); }
.prob-fill.t2 { background: linear-gradient(90deg, #ffc107, #ff9800); }
.prob-fill.t3 { background: linear-gradient(90deg, #00bcd4, #00d4ff); }

.strength { color: #00ff88; font-weight: bold; }
.empty { text-align: center; padding: 50px; color: #666; }
.loading { text-align: center; padding: 50px; color: #888; }
.error { background: rgba(233,69,96,0.2); border: 1px solid #e94560; padding: 15px; border-radius: 8px; color: #e94560; }
h3 { color: #ff6b6b; margin: 15px 0 8px; }

/* Concept tabs */
.concept-tabs { display: flex; flex-wrap: wrap; gap: 4px; margin: 10px 0; }
.concept-tab {
    padding: 4px 12px;
    border: 1px solid #0f3460;
    border-radius: 14px;
    background: #1a1a2e;
    color: #aaa;
    cursor: pointer;
    font-size: 0.82em;
    transition: all 0.2s;
}
.concept-tab:hover { border-color: #00d4ff; color: #00d4ff; }
.concept-tab.active { background: #0f3460; border-color: #00d4ff; color: #00d4ff; }
.concept-section { margin-bottom: 20px; }
.concept-section h4 { color: #ff9800; margin-bottom: 6px; font-size: 1em; display: inline; }
.section-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }

/* 涨停节奏网格（高对比暗色主题） */
.rhythm-section { background: #0d1117; border: 1px solid #30363d; border-radius: 10px; padding: 16px; margin-top: 12px; margin-bottom: 12px; }
.rhythm-title { color: #58a6ff; font-size: 0.95em; margin-bottom: 14px; font-weight: 700; letter-spacing: 0.5px; }
.rhythm-grid { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 6px; }
.rhythm-date { flex: 0 0 auto; min-width: 80px; background: #161b22; border: 1px solid #30363d; border-radius: 8px; overflow: hidden; }
.rhythm-header { background: #1f2937; color: #f0f6fc; text-align: center; padding: 5px 8px; font-weight: 700; font-size: 0.82em; letter-spacing: 0.3px; }
.rhythm-content { display: flex; flex-direction: column; gap: 4px; padding: 6px; }
.rhythm-item { display: flex; align-items: center; gap: 4px; }
.stock-block { display: inline-flex; flex-direction: column; align-items: center; padding: 5px 8px; border-radius: 6px; font-size: 0.82em; min-width: 54px; position: relative; cursor: pointer; transition: all 0.15s; }
.stock-block .name { font-weight: 700; margin-bottom: 2px; position: relative; color: #fff; }
.lb-tag { font-size: 0.65em; padding: 1px 5px; border-radius: 3px; color: #fff; font-weight: 700; display: inline-flex; align-items: center; gap: 3px; white-space: nowrap; }
.board-inline { font-size: 0.75em; opacity: 0.7; margin-left: 2px; }
.pct-tag { font-size: 0.65em; padding: 1px 5px; border-radius: 3px; color: #fff; font-weight: 700; background: rgba(0,0,0,0.35); }
/* 首板 - 亮蓝色 */
.stock-block.lb-1 { background: linear-gradient(135deg, #1a4a8a, #2563eb); border: 1px solid #3b82f6; color: #fff; }
.stock-block.lb-1 .lb-tag { background: rgba(0,0,0,0.3); }
/* 2板 - 亮橙色 */
.stock-block.lb-2 { background: linear-gradient(135deg, #92400e, #d97706); border: 1px solid #f59e0b; color: #fff; }
.stock-block.lb-2 .lb-tag { background: rgba(0,0,0,0.3); }
/* 3板+ - 亮红色 */
.stock-block.lb-3 { background: linear-gradient(135deg, #991b1b, #dc2626); border: 1px solid #ef4444; color: #fff; }
.stock-block.lb-3 .lb-tag { background: rgba(0,0,0,0.3); }
/* 大涨（非涨停）- 亮绿色 */
.stock-block.lb-0 { background: linear-gradient(135deg, #065f46, #059669); border: 1px solid #10b981; color: #fff; }
.stock-block.lb-0 .pct-tag { background: rgba(0,0,0,0.3); }
/* Hover/高亮 — 只加外框，不减亮度 */
.rhythm-item:hover .stock-block, .stock-block:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.4); }
.stock-block.highlighted { outline: 2px solid #fbbf24; outline-offset: 1px; box-shadow: 0 0 12px rgba(251, 191, 36, 0.6); }
/* 图例 */
.legend { display: flex; gap: 18px; justify-content: center; margin-top: 10px; padding-top: 12px; border-top: 1px solid #30363d; flex-wrap: wrap; }
.legend .item { display: flex; align-items: center; gap: 6px; font-size: 0.78em; color: #c9d1d9; font-weight: 500; }
.legend .dot { width: 14px; height: 14px; border-radius: 4px; }
.legend .dot.lb-1 { background: linear-gradient(135deg, #1a4a8a, #2563eb); }
.legend .dot.lb-2 { background: linear-gradient(135deg, #92400e, #d97706); }
.legend .dot.lb-3 { background: linear-gradient(135deg, #991b1b, #dc2626); }
.legend .dot.lb-0 { background: linear-gradient(135deg, #065f46, #059669); }

.show-all-btn {
    font-size: 0.78em;
    color: #00d4ff;
    cursor: pointer;
    padding: 2px 10px;
    border: 1px solid #00d4ff;
    border-radius: 10px;
    background: transparent;
    transition: all 0.2s;
}
.show-all-btn:hover { background: #0f3460; }

/* ZT Filter bar */
.zt-filter-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.zt-filter-label { color: #888; font-size: 0.85em; white-space: nowrap; }
.zt-filter-btn {
    padding: 4px 12px; border-radius: 14px; font-size: 0.82em; cursor: pointer;
    border: 1px solid #444; background: #1a1a2e; color: #aaa; transition: all 0.2s;
}
.zt-filter-btn:hover { border-color: #00d4ff; color: #eee; }
.zt-filter-btn.active { background: #0f3460; border-color: #00d4ff; color: #00d4ff; font-weight: bold; }

/* Event details row */
.event-row td { padding: 8px 12px; background: #1a1a2e; border-bottom: 1px solid #0f3460; }
.event-header { margin-bottom: 6px; display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
.dir-label { color: #888; font-size: 0.85em; }
.stock-a { color: #00d4ff; font-weight: bold; font-size: 0.85em; }
.stock-b { color: #ff6b6b; font-weight: bold; font-size: 0.85em; }
.dir-sep { color: #333; margin: 0 4px; font-size: 0.8em; }
.dir-item { color: #aaa; font-size: 0.82em; }
.event-timeline { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; margin-top: 4px; font-size: 0.85em; }
.event-tag {
    display: inline-flex;
    align-items: center;
    background: #0f3460;
    border-radius: 4px;
    padding: 2px 6px;
    gap: 2px;
    font-size: 0.82em;
}
.evt-a { color: #00d4ff; font-weight: bold; }
.evt-arrow { color: #555; margin: 0 1px; }
.evt-b { color: #ff6b6b; font-weight: bold; }
.evt-lag { color: #ff9800; font-size: 0.75em; margin-left: 2px; padding: 0 3px; background: #1a1a2e; border-radius: 2px; }

.quick-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 15px; }
.quick-stock {
    background: #1a1a2e;
    border: 1px solid #333;
    padding: 8px 14px;
    border-radius: 8px;
    cursor: pointer;
}
.quick-stock:hover { border-color: #00d4ff; background: #0f3460; }
.qs-code { color: #00d4ff; font-weight: bold; }
.qs-name { color: #aaa; margin-left: 6px; }
.qs-zt { color: #ff6b6b; margin-left: 6px; font-size: 0.85em; }

.peak-list { display: flex; flex-wrap: wrap; gap: 8px; }
.peak-item { background: #0f3460; border: 1px solid #ff6b6b; padding: 5px 12px; border-radius: 8px; font-size: 0.85em; }
.peak-date { color: #ff6b6b; }
.peak-count { color: #00d4ff; font-weight: bold; }

/* Stats Tab */
.stat-cards { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }
.stat-card {
    background: #1a1a2e;
    border: 1px solid #0f3460;
    border-radius: 10px;
    padding: 15px 20px;
    min-width: 140px;
    flex: 1;
}
.stat-card .stat-label { color: #888; font-size: 0.85em; }
.stat-card .stat-value { color: #00d4ff; font-size: 1.8em; font-weight: bold; }
.stat-card .stat-value.red { color: #ff6b6b; }
.stat-card .stat-value.green { color: #00ff88; }

.filter-bar {
    display: flex; gap: 14px; align-items: flex-end;
    flex-wrap: wrap; margin-bottom: 18px;
    background: linear-gradient(135deg, #1a1a3e, #0f3460);
    padding: 16px 22px; border-radius: 14px;
    border: 1px solid rgba(0,212,255,0.15);
}
.filter-bar label { color: #aaa; font-size: 0.82em; letter-spacing: 0.5px; }
.filter-bar input[type=date] {
    background: #1a1a2e; border: 1px solid #0f3460;
    color: #00d4ff; padding: 8px 12px; border-radius: 8px;
    font-size: 0.9em; outline: none;
    transition: border-color 0.2s;
}
.filter-bar input[type=date]:focus { border-color: #00d4ff; }
.filter-bar .btn {
    background: linear-gradient(135deg, #00d4ff, #0099cc);
    color: #1a1a2e; border: none; padding: 8px 22px;
    border-radius: 8px; cursor: pointer; font-weight: bold;
    font-size: 0.9em; transition: transform 0.1s, opacity 0.2s;
}
.filter-bar .btn:hover { opacity: 0.9; transform: translateY(-1px); }

.chart-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 18px;
    margin-bottom: 22px;
}
.chart-box {
    background: #16213e;
    border-radius: 12px;
    padding: 15px 18px;
    margin-bottom: 15px;
}
.chart-grid .chart-box { margin-bottom: 0; }
.chart-box h4 { color: #00d4ff; margin-bottom: 10px; font-size: 1em; }
.chart-box canvas { max-height: 500px; height: 420px !important; }

/* Distribution bucket buttons */
.dist-section { margin-bottom: 20px; }
.dist-section h4 { color: #ff6b6b; margin-bottom: 10px; font-size: 1em; }
.bucket-bar {
    display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px;
}
.bucket-btn {
    padding: 8px 16px; border-radius: 8px; cursor: pointer;
    font-size: 0.9em; font-weight: bold; text-align: center;
    background: #0f3460; color: #aaa; border: 1px solid transparent;
    transition: all 0.2s; user-select: none;
}
.bucket-btn:hover { background: #1a4a8a; color: #eee; }
.bucket-btn.active {
    background: #00d4ff; color: #1a1a2e; border-color: #00d4ff;
    box-shadow: 0 0 12px rgba(0,212,255,0.3);
}

/* Bucket detail table */
.bucket-detail {
    background: #1a1a2e; border-radius: 10px; padding: 12px;
    margin-top: 8px; display: none; max-height: 400px; overflow-y: auto;
}
.bucket-detail.active { display: block; }
.bucket-detail table { width: 100%; border-collapse: collapse; }
.bucket-detail th {
    background: #0f3460; color: #888; padding: 6px 8px;
    text-align: left; font-size: 0.82em; position: sticky; top: 0; z-index: 1;
}
.bucket-detail td {
    padding: 5px 8px; border-bottom: 1px solid #0f3460;
    font-size: 0.85em;
}
.bucket-detail tr.clickable { cursor: pointer; }
.bucket-detail tr.clickable:hover { background: #16213e; }
.concept-badge {
    display: inline-block; background: #0f3460; color: #00d4ff;
    padding: 1px 6px; border-radius: 4px; font-size: 0.82em; margin: 1px 2px;
}

/* Stats hot stocks section */
.hot-section { margin-top: 15px; }
.hot-section h4 { color: #ff6b6b; margin-bottom: 10px; font-size: 1em; }
.hot-section table { width: 100%; border-collapse: collapse; }
.hot-section th {
    background: #0f3460; color: #888; padding: 7px 10px;
    text-align: left; font-size: 0.85em;
}
.hot-section td {
    padding: 6px 10px; border-bottom: 1px solid #0f3460; font-size: 0.88em;
}
.hot-section tr.clickable { cursor: pointer; }
.hot-section tr.clickable:hover { background: #16213e; }

/* Score badge colors */
.score-badge {
    display: inline-block; padding: 2px 10px; border-radius: 10px;
    font-weight: bold; font-size: 0.85em; min-width: 36px; text-align: center;
}
.score-high { background: rgba(255, 60, 60, 0.25); color: #ff6b6b; }
.score-mid { background: rgba(255, 193, 7, 0.2); color: #ffc107; }
.score-low { background: rgba(0, 212, 255, 0.15); color: #00d4ff; }

.stats-section { margin-bottom: 25px; }
.stats-section h3 { color: #ff6b6b; margin-bottom: 12px; font-size: 1.1em; }

/* 精准狙击 Tab */
.sniper-section { margin-bottom: 25px; }
.sniper-section h3 { color: #00d4ff; margin-bottom: 12px; font-size: 1.1em; display: flex; align-items: center; gap: 10px; }

/* 实时行情 · 板块强度排行 */
.sr-table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
.sr-table th { background: #1a3a6a; color: #aac; padding: 7px 10px;
    text-align: left; font-size: 0.82em; font-weight: normal; position: sticky; top: 0; }
.sr-table td { padding: 6px 10px; border-bottom: 1px solid #0f3460; }
.sr-table tr:hover td { background: rgba(15,52,96,0.25); }
.sr-table-wrapper { max-height: 400px; overflow-y: auto; border-radius: 8px;
    border: 1px solid #0f3460; background: #1e2e4e; }
.sr-change-up { color: #ff6b6b; }
.sr-change-down { color: #4fc3f7; }
.sr-inflow-pos { color: #ff6b6b; }
.sr-inflow-neg { color: #4fc3f7; }

.sniper-placeholder {
    background: rgba(15,52,96,0.35); border: 1px dashed rgba(0,212,255,0.2);
    border-radius: 10px; padding: 30px; text-align: center; color: #666; font-size: 0.9em;
}
.sniper-tag-section { margin-bottom: 10px; }
.sniper-tag-header {
    display: flex; align-items: center; gap: 8px; padding: 6px 14px;
    background: rgba(15,52,96,0.35); border-radius: 8px; cursor: pointer;
    margin-bottom: 8px; user-select: none; font-size: 0.88em;
}
.sniper-tag-header:hover { background: rgba(15,52,96,0.6); }
.sniper-tag-name { color: #ffc107; font-weight: bold; }
.sniper-tag-count { color: #888; font-size: 0.85em; margin-left: 4px; }
.sniper-tag-arrow { margin-left: auto; color: #666; font-size: 0.8em; transition: transform 0.2s; }
.sniper-tag-header.collapsed .sniper-tag-arrow { transform: rotate(-90deg); }
.sniper-tag-body.collapsed { display: none; }
.sniper-tag-body { margin-bottom: 4px; }

/* 题材走势区域 */
.sniper-trend-section {
    padding: 4px 0;
}
.sniper-trend-divider {
    border-top: 1px solid rgba(255,255,255,0.06);
    margin: 8px 0;
}
.sniper-trend-header {
    display: flex; align-items: center; gap: 6px;
    padding: 6px 4px; cursor: pointer; user-select: none;
    font-size: 0.85em; color: #ffc107;
    transition: background 0.15s; border-radius: 6px;
}
.sniper-trend-header:hover { background: rgba(255,193,7,0.06); }
.sniper-trend-icon { font-size: 0.7em; opacity: 0.6; }
.sniper-trend-label { font-weight: bold; flex: 1; }
.sniper-trend-body { margin-top: 8px; }

/* 实时强榜卡片 */
.sniper-strong-grid {
    display: grid; grid-template-columns: repeat(var(--sn-cols, 4), 1fr);
    gap: 10px;
}
.sniper-strong-card {
    background: rgba(15,52,96,0.15); border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.05); overflow: hidden;
    transition: border-color 0.15s;
}
.sniper-strong-card:hover { border-color: rgba(255,255,255,0.12); }
.sniper-strong-card-header {
    display: flex; align-items: center; gap: 6px;
    padding: 7px 10px; background: rgba(15,52,96,0.3);
    font-size: 0.85em; cursor: pointer; user-select: none;
}
.sniper-strong-card-header:hover { background: rgba(15,52,96,0.5); }
.sniper-strong-rank { color: #888; font-weight: bold; min-width: 22px; text-align: center; }
.sniper-strong-tag { color: #ffc107; font-weight: bold; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sniper-trend-btn {
    cursor: pointer; font-size: 0.82em; opacity: 0.6; flex-shrink: 0;
    transition: opacity 0.2s; padding: 0 2px;
}
.sniper-trend-btn:hover { opacity: 1; }
.sniper-strong-total { color: #ff6b6b; font-size: 0.82em; white-space: nowrap; }
.sniper-strong-daily {
    margin-left: 6px; font-size: 0.72em; color: #ffc107;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    flex: 1; min-width: 0; direction: ltr;
}
.sniper-strong-stocks { padding: 2px 0; max-height: 300px; overflow-y: auto; }
.sniper-strong-stock {
    display: flex; align-items: center; gap: 5px;
    padding: 3px 10px; font-size: 0.8em;
    border-bottom: 1px solid rgba(255,255,255,0.02);
    cursor: pointer; transition: background 0.1s;
}
.sniper-strong-stock:hover { background: rgba(15,52,96,0.25); }
.sniper-strong-stock-rank { color: #555; min-width: 16px; font-size: 0.78em; text-align: right; }
.sniper-strong-stock .np-card-code { font-size: 0.9em; }
.sniper-strong-stock .np-card-name { flex-shrink: 0; max-width: 30%; }
.sniper-stock-inline-info {
    font-size: 0.72em; color: #999;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    flex: 1 1 auto; min-width: 0;
}
.sniper-strong-lb { color: #ff6b6b; font-weight: bold; font-size: 0.82em; margin-left: auto; white-space: nowrap; }
.sniper-strong-zt-count { color: #ffc107; font-size: 0.78em; white-space: nowrap; }
/* 今日涨停跑马灯高亮 */
.sniper-strong-stock-today {
    background: linear-gradient(90deg, rgba(255,107,53,0.12) 0%, rgba(255,215,0,0.08) 50%, rgba(255,107,53,0.12) 100%);
    background-size: 200% 100%;
    animation: todayGlow 2s ease-in-out infinite;
    border-left: 2px solid #ff6b35;
}
@keyframes todayGlow {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}
.today-zt-badge {
    display: inline-flex; align-items: center; gap: 2px;
    background: linear-gradient(90deg, #ff6b35, #ffd700);
    background-size: 200% 100%;
    animation: badgeGlow 1.5s ease-in-out infinite;
    color: #000; font-size: 0.7em; font-weight: bold;
    padding: 1px 5px; border-radius: 3px; white-space: nowrap;
}
@keyframes badgeGlow {
    0%, 100% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
}
.today-zt-time {
    color: #ffd700; font-size: 0.75em; font-weight: bold; white-space: nowrap;
}

/* 风向标 Table */
.wv-table-wrapper { overflow-x: auto; margin-bottom: 4px; }
.wv-table {
  width: 100%; border-collapse: collapse; font-size: 13px;
}
.wv-table thead th {
  position: sticky; top: 0; z-index: 1;
  background: #0d1f3c;
}
.wv-table th {
  text-align: left; padding: 6px 8px; font-weight: 500; color: #888;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  font-size: 11px; white-space: nowrap; letter-spacing: 0.5px;
}
.wv-table td {
  padding: 5px 8px; border-bottom: 1px solid rgba(255,255,255,0.03);
  transition: background 0.12s; white-space: nowrap;
}
.wv-table tr:hover td { background: rgba(15,52,96,0.25); }
.wv-table tr { cursor: pointer; }
.wv-table tr.group-header { cursor: default; }
.wv-table tr.group-header:hover td { background: transparent; }
.wv-table .code-tag {
  display: inline-block; padding: 1px 5px; border-radius: 3px;
  font-size: 11px; font-family: 'SF Mono', monospace;
}
.wv-table .code-tag.main { color: #42a5f5; background: rgba(66,165,245,0.12); }
.wv-table .code-tag.gem { color: #ff7043; background: rgba(255,112,67,0.12); }
.wv-table .code-tag.tech { color: #ab47bc; background: rgba(171,71,188,0.12); }
.wv-table .themes-text { color: #ccc; font-size: 12px; max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; }
.wv-table .num-green { color: #4caf50; }
.wv-table .num-red { color: #ef5350; }
.wv-table .num-gray { color: #888; }
/* 盘面梳理 Timeline */
.pmsl-timeline { column-count: 1; }
.pmsl-type-group { margin-bottom: 10px; break-inside: avoid; }
.pmsl-type-title {
  font-size: 12px; font-weight: 500; margin-bottom: 6px; padding: 3px 8px;
  border-radius: 4px; display: inline-block;
}
.pmsl-type-title.pos { color: #ff6b6b; background: rgba(255,107,107,0.08); }
.pmsl-type-title.neg { color: #888; background: rgba(255,255,255,0.03); }
.pmsl-type-title.neu { color: #4fc3f7; background: rgba(79,195,247,0.08); }
.pmsl-event {
  display: flex; gap: 10px; padding: 6px 10px; margin-bottom: 4px;
  border-radius: 6px; border-left: 3px solid transparent;
  break-inside: avoid;
  background: rgba(15,52,96,0.06);
}
.pmsl-event.pos { border-left-color: #ff6b6b; }
.pmsl-event.neg { border-left-color: #666; }
.pmsl-event.neu { border-left-color: #4fc3f7; }
.pmsl-left { width: 50px; flex-shrink: 0; padding-top: 1px; }
.pmsl-time { color: #888; font-size: 11px; font-family: 'SF Mono', monospace; }
.pmsl-right { flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.pmsl-sector { color: #42a5f5; font-size: 11px; font-weight: 500; flex-shrink: 0; }
.pmsl-detail { color: #aaa; font-size: 12px; line-height: 1.4; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pmsl-stocks { display: inline-flex; gap: 4px; flex-shrink: 0; }
.pmsl-stock-tag {
  display: inline-block; padding: 1px 6px; border-radius: 3px;
  font-size: 11px; cursor: pointer; transition: all 0.12s;
}
.pmsl-stock-tag:hover { filter: brightness(1.3); }
.pmsl-stock-tag.main { color: #42a5f5; background: rgba(66,165,245,0.12); }
.pmsl-stock-tag.gem { color: #ff7043; background: rgba(255,112,67,0.12); }
.pmsl-stock-tag.tech { color: #ab47bc; background: rgba(171,71,188,0.12); }

/* N字战法 页面样式 */
.np-section { margin-bottom: 25px; }
.np-section h3 { color: #00d4ff; margin-bottom: 15px; font-size: 1.1em; display: flex; align-items: center; gap: 10px; }
.np-section .count-badge { background: #0f3460; color: #00d4ff; padding: 2px 10px; border-radius: 10px; font-size: 0.8em; }

.np-board-section { margin-bottom: 20px; }
.np-board-header {
    display: flex; align-items: center; gap: 8px; margin-bottom: 10px;
    padding: 6px 12px; border-radius: 8px; font-size: 0.9em; font-weight: bold;
}
.np-board-header.main { background: #1a3a5c; color: #4fc3f7; }
.np-board-header.sub { background: #0f3460; color: #00d4ff; border-left: 3px solid #00d4ff; }
.np-board-header.gem { background: #3a1a3a; color: #f48fb1; }
.np-board-header.star { background: #1a3a1a; color: #81c784; }
.np-board-header.bj { background: #3a3a1a; color: #ffd54f; }
.np-board-header.other { background: #2a2a1a; color: #ffcc80; }
.np-board-header.gem_star { background: #2a1a3a; color: #ce93d8; }

/* Collapsible board header */
.np-board-header.collapsible { cursor: pointer; user-select: none; transition: background 0.2s; }
.np-board-header.collapsible:hover { filter: brightness(1.3); }
.np-board-header .board-arrow { margin-left: auto; color: #888; font-size: 0.8em; transition: transform 0.2s; }
.np-board-header.collapsed .board-arrow { transform: rotate(-90deg); }
.np-board-body { overflow: hidden; transition: max-height 0.3s ease; }
.np-board-body.collapsed { max-height: 0 !important; }


.np-board-divider {
    text-align: center; color: #00d4ff; font-size: 0.95em;
    margin: 24px 0 16px 0; padding: 8px 0;
    border-top: 1px solid #0f3460; border-bottom: 1px solid #0f3460;
    background: rgba(0, 212, 255, 0.05);
    letter-spacing: 2px; font-weight: bold;
}

.np-card-grid {
    display: grid;
    grid-template-columns: repeat(var(--np-cols, 4), minmax(0, 1fr));
    gap: 16px;
    margin-bottom: 20px;
}
.np-card {
    min-width: 0;
    border-radius: 12px;
    padding: 14px;
    border: 1px solid #0f3460;
    transition: transform 0.2s, box-shadow 0.2s;
    position: relative;
}
.np-card:hover { transform: scale(1.03); }
/* 股票搜索高亮 — 金色发光边框 */
.np-card.kpl-stock-highlight {
    border-color: #ffc107 !important;
    border-width: 2px !important;
    background: rgba(255, 193, 7, 0.06);
    box-shadow: 0 0 20px rgba(255, 193, 7, 0.55), 0 0 40px rgba(255, 193, 7, 0.2);
}
.np-card.kpl-stock-highlight .np-card-code { color: #ffc107; }
.np-card.kpl-stock-highlight .np-card-name { color: #fff; }

/* 板块边框颜色 */
.np-card-board-zhuban { border-color: #42a5f5; }
.np-card-board-chuangye { border-color: #ff7043; }
.np-card-board-kechuang { border-color: #ab47bc; }
.np-card-board-other { border-color: #90a4ae; }
.np-card.star-card { border-left: 3px solid #ffc107; }
.np-card.tld-card { border-left: 4px solid #e94560; background: linear-gradient(135deg, #1a1a2e, #2a1020); }
.np-card.tld-shouban-card { border-left: 4px solid #ff6b6b; background: linear-gradient(135deg, #1a1a2e, #301515); }
.np-card.nw-card { border-left: 4px solid #ff5722; background: linear-gradient(135deg, #1a1a2e, #2a1a10); }
.np-card .tld-badge { background: rgba(233, 69, 96, 0.25); color: #e94560; border: 1px solid #e94560; padding: 2px 8px; border-radius: 4px; font-size: 0.78em; font-weight: bold; margin-left: 4px; }
.np-card .tld-shouban-badge { background: rgba(255, 107, 107, 0.25); color: #ff6b6b; border: 1px solid #ff6b6b; padding: 2px 8px; border-radius: 4px; font-size: 0.78em; font-weight: bold; margin-left: 4px; animation: pulse-red 1.5s ease-in-out infinite; }
.np-card .nw-badge { background: rgba(255, 87, 34, 0.2); color: #ff5722; border: 1px solid #ff5722; padding: 2px 8px; border-radius: 4px; font-size: 0.78em; font-weight: bold; margin-left: 4px; }
@keyframes pulse-red { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
.np-card-header {
    display: flex; justify-content: space-between; align-items: flex-start;
    margin-bottom: 8px;
}
.np-card-code { font-size: 1.1em; font-weight: bold; color: #00d4ff; cursor: pointer; }
.np-card-code:hover { text-decoration: underline; }
.np-card-name { font-size: 0.9em; color: #ddd; margin-left: 6px; }
.np-card-badges { display: flex; gap: 4px; flex-wrap: wrap; margin: 4px 0; }
.np-card-badge {
    background: #0f3460; padding: 2px 8px; border-radius: 4px;
    font-size: 0.78em; color: #aaa;
}
.np-card-badge.lianban { background: rgba(255, 193, 7, 0.15); color: #ffc107; border-color: #ffc107; }
.np-card-badge.alert { background: rgba(255, 60, 60, 0.15); color: #ff6b6b; border-color: #ff6b6b; }
.np-card-badge.oscillation { background: rgba(0, 212, 255, 0.15); color: #00d4ff; border-color: #00d4ff; }

.np-metrics {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 4px;
    margin: 8px 0;
    font-size: 0.82em;
}
.np-metric { text-align: center; padding: 4px; background: #0f3460; border-radius: 6px; }
.np-metric .label { color: #888; font-size: 0.78em; }
.np-metric .value { color: #ddd; font-weight: bold; }
.np-metric .value.positive { color: #ff6b6b; }
.np-metric .value.negative { color: #81c784; }

.np-nw-metrics {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 4px;
    margin: 6px 0 8px 0;
    font-size: 0.82em;
}

.np-kline-container { margin: 8px 0; position: relative; }
.np-kline-container canvas { width: 100%; height: 200px; border-radius: 6px; background: #1a1a2e; }
.np-kline-toggle {
    background: #0f3460; color: #aaa; border: none; padding: 4px 12px;
    border-radius: 4px; cursor: pointer; font-size: 0.78em;
    margin-top: 4px;
}
.np-kline-toggle:hover { background: #1a4a8a; color: #eee; }
.np-kline-latest { text-align: center; color: #666; font-size: 0.72em; margin-top: 2px; }
.np-kline-latest span { color: #4caf50; }

.arb-btn {
    background: linear-gradient(135deg, #ff9800, #e94560); color: #fff; border: none;
    padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 0.85em; font-weight: bold;
    transition: transform 0.2s, box-shadow 0.2s;
}
.arb-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(233, 69, 96, 0.4); }

.np-alert-card {
    background: #1a1a2e; border-radius: 10px; padding: 12px;
    margin-bottom: 8px; border-left: 3px solid #e94560;
}
.np-alert-card.gem { border-left-color: #f48fb1; }
.np-alert-card.zha_ban { border-left-color: #ff9800; }

.np-cat-header {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 16px; background: #0f3460; border-radius: 10px;
    margin-bottom: 12px; cursor: pointer; user-select: none;
}
.np-cat-header:hover { background: #1a4a8a; }
.np-cat-header .cat-icon { font-size: 1.2em; }
.np-cat-header .cat-name { font-weight: bold; font-size: 0.95em; }
.np-cat-header .cat-count { color: #888; font-size: 0.85em; }
.np-cat-header .cat-arrow { margin-left: auto; color: #666; transition: transform 0.2s; }
.np-cat-header.collapsed .cat-arrow { transform: rotate(-90deg); }
.np-cat-body.collapsed { display: none; }

/* Pullback progress bar */
.np-pullback-bar {
    height: 6px; background: #0f3460; border-radius: 3px; margin: 6px 0; overflow: hidden;
}
.np-pullback-fill { height: 100%; border-radius: 3px; }
.np-pullback-fill.shallow { background: linear-gradient(90deg, #81c784, #4caf50); }
.np-pullback-fill.normal { background: linear-gradient(90deg, #4caf50, #ffc107); }
.np-pullback-fill.deep { background: linear-gradient(90deg, #ffc107, #ff9800); }
.np-pullback-fill.severe { background: linear-gradient(90deg, #ff9800, #ff6b6b); }
.np-pullback-fill.extreme { background: linear-gradient(90deg, #ff6b6b, #e94560); }

.np-update-time { text-align: center; color: #666; font-size: 0.85em; padding: 10px; }

/* N字战法 UI Enhancements: sidebar, filters, grid toggle, back-to-top */
.np-wrapper {
    display: flex;
    align-items: flex-start;
    gap: 18px;
}
.np-sidebar {
    position: sticky;
    top: 20px;
    width: 150px;
    flex-shrink: 0;
    background: rgba(15,52,96,0.55);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border-radius: 12px;
    border: 1px solid rgba(0,212,255,0.12);
    padding: 8px 0;
    z-index: 10;
    max-height: 90vh;
    overflow-y: auto;
}
.np-sidebar-item {
    display: block;
    padding: 7px 12px;
    font-size: 0.78em;
    color: #888;
    cursor: pointer;
    transition: all 0.2s;
    border-left: 3px solid transparent;
    text-decoration: none;
    line-height: 1.3;
}
.np-sidebar-item:hover { color: #ddd; background: rgba(0,212,255,0.05); }
.np-sidebar-item.active {
    color: #00d4ff;
    border-left-color: #00d4ff;
    background: rgba(0,212,255,0.08);
}
.np-sidebar-subitem {
    display: block;
    padding: 4px 12px 4px 24px;
    font-size: 0.72em;
    color: #777;
    cursor: pointer;
    transition: all 0.2s;
    line-height: 1.3;
    text-decoration: none;
}
.np-sidebar-subitem:hover { color: #00d4ff; background: rgba(0,212,255,0.05); }
.np-sidebar.hidden { display: none; }
.np-sidebar-hide {
    text-align: right; padding: 2px 8px 4px; cursor: pointer; color: #555;
    font-size: 0.85em; transition: color 0.15s; user-select: none;
}
.np-sidebar-hide:hover { color: #ddd; }
.np-sidebar-showbtn {
    position: sticky; top: 20px; flex-shrink: 0;
    width: 32px; height: 32px; padding: 0; margin: 0;
    background: rgba(15,52,96,0.55); border: 1px solid rgba(0,212,255,0.12);
    border-radius: 8px; color: #888; cursor: pointer; font-size: 1em;
    display: flex; align-items: center; justify-content: center;
    z-index: 10; transition: color 0.15s;
}
.np-sidebar-showbtn:hover { color: #ddd; }
.np-main-content {
    flex: 1;
    min-width: 0;
}
.np-back-top {
    text-align: center;
    padding: 6px;
    font-size: 0.8em;
    color: #555;
    cursor: pointer;
    transition: color 0.2s;
    border-top: 1px solid rgba(255,255,255,0.04);
    margin-top: 4px;
}
.np-back-top:hover { color: #00d4ff; }

/* Filter bar */
.np-filter-bar {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 16px;
    padding: 10px 14px;
    background: rgba(15,52,96,0.35);
    border-radius: 10px;
    border: 1px solid rgba(0,212,255,0.08);
}
.np-filter-bar .fl { color: #888; font-size: 0.8em; }
.np-filter-input {
    background: #0f3460; color: #ddd;
    border: 1px solid rgba(0,212,255,0.2); border-radius: 6px;
    padding: 5px 10px; font-size: 0.82em; outline: none; min-width: 160px;
}
.np-filter-input:focus { border-color: #00d4ff; }
.np-filter-cb {
    display: flex; align-items: center; gap: 3px;
    font-size: 0.8em; color: #aaa; cursor: pointer;
    padding: 3px 8px; background: rgba(15,52,96,0.5); border-radius: 5px;
}
.np-filter-cb:hover { color: #ddd; }
.np-filter-cb input { accent-color: #00d4ff; margin: 0; }

/* Grid column toggle */
.np-grid-tog {
    display: flex; gap: 3px; align-items: center; margin-left: auto;
}
.np-grid-tog button {
    background: #0f3460; color: #888;
    border: 1px solid rgba(0,212,255,0.12); padding: 3px 9px;
    border-radius: 4px; cursor: pointer; font-size: 0.76em; transition: all 0.2s;
}
.np-grid-tog button:hover { color: #ddd; border-color: #00d4ff; }
.np-grid-tog button.active, .sn-grid-tog button.active {
    color: #00d4ff; border-color: #00d4ff; background: rgba(0,212,255,0.1);
}

.sn-grid-tog {
    display: flex; gap: 3px; align-items: center; margin-left: 6px;
}
.sn-grid-tog button {
    background: #0f3460; color: #888;
    border: 1px solid rgba(0,212,255,0.12); padding: 2px 7px;
    border-radius: 4px; cursor: pointer; font-size: 0.7em; transition: all 0.2s;
}
.sn-grid-tog button:hover { color: #ddd; border-color: #00d4ff; }

/* K-line modal overlay */
.kline-modal-overlay {
    display: none; position: fixed; z-index: 1000;
    left: 0; top: 0; width: 100%; height: 100%;
    background: rgba(0,0,0,0.7); backdrop-filter: blur(4px);
}
.kline-modal-overlay.active { display: flex; align-items: center; justify-content: center; }
.kline-modal {
    background: #16213e; border-radius: 16px; border: 1px solid #0f3460;
    width: 90%; max-width: 900px; max-height: 90vh; overflow-y: auto;
    padding: 24px; position: relative;
}
.kline-modal-close {
    position: absolute; top: 12px; right: 16px;
    color: #888; font-size: 1.5em; cursor: pointer;
    transition: color 0.2s;
}
.kline-modal-close:hover { color: #ff6b6b; }
.kline-modal h3 { color: #00d4ff; margin: 0 0 8px 0; }
.kline-modal .np-metrics { grid-template-columns: repeat(4, 1fr); }
.kline-modal .np-card-badges { margin: 8px 0; }
.kline-modal-header {
    display: flex; align-items: center; gap: 10px;
    margin-bottom: 8px;
}
.kline-modal-title-area { flex: 1; text-align: center; }
.kline-modal-title-area h3 { margin: 0; }
.kline-modal-counter {
    font-size: 0.8em; color: #888; display: block; margin-top: 2px;
}
.kline-modal-nav-btn {
    font-size: 1.2em; color: #888; cursor: pointer; padding: 6px 12px;
    border-radius: 8px; transition: all 0.2s; user-select: none;
    background: rgba(255,255,255,0.05);
}
.kline-modal-nav-btn:hover { color: #00d4ff; background: rgba(0,212,255,0.1); }
.kline-modal-nav-btn.disabled { color: #444; cursor: not-allowed; background: transparent; }

.np-enlarge-btn {
    display: inline-flex; align-items: center; justify-content: center;
    width: 22px; height: 22px; border-radius: 50%; margin-left: 4px;
    background: rgba(0,212,255,0.12); border: 1px solid rgba(0,212,255,0.25);
    color: #00d4ff; font-size: 0.7em; cursor: pointer;
    transition: all 0.2s; line-height: 1; padding: 0; vertical-align: middle;
}
.np-enlarge-btn:hover { background: #00d4ff; color: #0a1628; }
/* 卡片内容放大弹框 */
.enlarge-card-modal { max-width: 700px; }
.enlarge-card-btn {
    position: absolute; top: 4px; right: 4px; z-index: 5;
    width: 28px; height: 28px; border-radius: 50%;
    background: rgba(0,212,255,0.15); border: 1px solid rgba(0,212,255,0.3);
    color: #00d4ff; font-size: 0.85em; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: all 0.2s; line-height: 1; padding: 0;
}
.enlarge-card-btn:hover { background: #00d4ff; color: #0a1628; }
.enlarged-card-content .ds-stock-kline-img { width: 100%; min-height: 200px; }
.enlarged-card-content .ds-stock-kline-section { margin-bottom: 20px; }
.enlarged-card-content .concept-kline-grid { grid-template-columns: 1fr; }
.enlarged-card-content .kline-img { width: 100%; min-height: 180px; border-radius: 8px; border: 1px solid #0f3460; background: #fff; margin-bottom: 8px; }
.enlarged-card-content .sk-header { margin-bottom: 10px; }
.enlarged-card-content .sk-name { font-size: 1.2em; color: #00d4ff; font-weight: bold; }
.enlarged-card-content .sk-code { font-size: 0.9em; color: #888; margin-left: 8px; }
@media (max-width: 600px) {
    .enlarge-card-modal { max-width: 100%; width: 98%; padding: 16px; }
    .enlarged-card-content .ds-stock-kline-img { min-height: 150px; }
}

/* 开盘啦 题材概念树浏览器 */
.kpl-wrapper { max-width: 100%; }
.kpl-tree-node { margin: 2px 0; }
.kpl-tree-node .kpl-header {
    display: flex; align-items: center; gap: 6px; cursor: pointer;
    padding: 6px 10px; border-radius: 6px; transition: background 0.15s;
    user-select: none;
}
.kpl-tree-node .kpl-header:hover { background: rgba(0,212,255,0.06); }
.kpl-tree-node .kpl-arrow {
    color: #666; font-size: 0.7em; transition: transform 0.2s;
    width: 14px; flex-shrink: 0; text-align: center;
}
.kpl-tree-node.collapsed > .kpl-header .kpl-arrow { transform: rotate(-90deg); }
.kpl-tree-node .kpl-label { font-size: 0.9em; }
.kpl-tree-node .kpl-count { color: #888; font-size: 0.78em; margin-left: 6px; }
.kpl-tree-node .kpl-children { padding-left: 22px; overflow: hidden; transition: max-height 0.25s ease; }
.kpl-tree-node.collapsed > .kpl-children { max-height: 0 !important; }

/* Expand/collapse all button */
.kpl-expand-btn {
    margin-left:auto; cursor:pointer; font-size:0.85em; opacity:0.6;
    padding:2px 6px; border-radius:4px; user-select:none; line-height:1;
}
.kpl-expand-btn:hover { opacity:1; background:rgba(255,255,255,0.1); }

/* L1 node */
.kpl-node-l1 > .kpl-header {
    padding: 8px 14px; border-radius: 8px;
    background: linear-gradient(135deg, #1a2a4e, #0f3460);
    border-left: 3px solid #00d4ff;
}
.kpl-node-l1 > .kpl-header .kpl-label { color: #00d4ff; font-weight: bold; font-size: 1em; }
.kpl-node-l1 > .kpl-header .kpl-count { color: #4fc3f7; }
.kpl-node-l1 > .kpl-header:hover { filter: brightness(1.2); }
.kpl-node-l1 > .kpl-children { border-left: 1px solid rgba(0,212,255,0.12); margin: 2px 0 4px 8px; }

/* L2 node */
.kpl-node-l2 > .kpl-header {
    padding: 6px 12px; border-radius: 6px;
    background: #0f3460;
    border-left: 2px solid #4fc3f7;
}
.kpl-node-l2 > .kpl-header .kpl-label { color: #4fc3f7; font-size: 0.88em; font-weight: bold; }
.kpl-node-l2 > .kpl-header .kpl-count { color: #7ab; }
.kpl-node-l2 > .kpl-header:hover { filter: brightness(1.3); }
.kpl-node-l2 > .kpl-children { border-left: 1px solid rgba(79,195,247,0.1); margin: 2px 0 4px 8px; }

/* L3 node */
.kpl-node-l3 > .kpl-header {
    padding: 4px 10px; border-radius: 6px;
    background: rgba(255, 152, 0, 0.07);
    border-left: 2px solid rgba(255, 152, 0, 0.25);
}
.kpl-node-l3 > .kpl-header .kpl-label { color: #ffb74d; font-size: 0.85em; }
.kpl-node-l3 > .kpl-header .kpl-count { color: #ca8; }
.kpl-node-l3 > .kpl-header:hover { background: rgba(255, 152, 0, 0.14); }
.kpl-node-l3 > .kpl-children { padding-left: 0; margin: 4px 0 8px 12px; }
.kpl-node-l3 > .kpl-children .kpl-card-grid {
    display: grid;
    grid-template-columns: repeat(var(--np-cols, 4), minmax(0, 1fr));
    gap: 12px;
}
/* General kpl-card-grid (for watch tab groups etc.) */
.kpl-card-grid {
    display: grid;
    grid-template-columns: repeat(var(--np-cols, 4), minmax(0, 1fr));
    gap: 12px;
}

/* Watch/star styles */
.np-watch-star { cursor:pointer; user-select:none; color:#555; font-size:1.1em; margin-right:4px; transition:color 0.15s,transform 0.15s; display:inline-block; }
.np-watch-star:hover { transform:scale(1.25); }
.np-watch-star.watched-c1 { color:#e94560; } /* 持仓关注红 */
.np-watch-star.watched-c2 { color:#42a5f5; } /* 已清仓蓝 */
.np-watch-star.watched-c3 { color:#ff7043; } /* 热点橙 */
.np-watch-star.watched-concept { color:#ffc107; } /* 概念金 */
.watch-popup-menu { position:fixed; background:#1a2744; border:1px solid #0f3460; border-radius:8px; padding:4px 0; z-index:9999; box-shadow:0 4px 20px rgba(0,0,0,0.5); min-width:140px; }
.watch-popup-item { padding:8px 14px; cursor:pointer; color:#ccc; font-size:0.85em; white-space:nowrap; display:flex; align-items:center; gap:6px; transition:background 0.1s; }
.watch-popup-item:hover { background:rgba(0,212,255,0.12); color:#fff; }
.watch-popup-item.watch-popup-remove { border-top:1px solid #0f3460; margin-top:2px; color:#e94560; }
.watch-popup-item .wp-dot { display:inline-block; width:10px; height:10px; border-radius:50%; flex-shrink:0; }
.watch-container { padding:6px 0; }
.watch-section { margin-bottom:20px; }
.watch-section-title { color:#4fc3f7; font-size:0.95em; font-weight:bold; margin-bottom:10px; padding-bottom:6px; border-bottom:1px solid #0f3460; display:flex; align-items:center; gap:8px; }
.watch-subgroup { margin-bottom:16px; }
.watch-subgroup-title { color:#aaa; font-size:0.82em; font-weight:bold; margin-bottom:8px; padding:4px 10px; border-radius:4px; display:inline-block; }
.watch-empty { color:#666; padding:12px; text-align:center; font-size:0.9em; }
.kpl-watch-star { cursor:pointer; user-select:none; font-size:0.85em; margin-left:4px; color:#555; transition:color 0.15s,transform 0.15s; display:inline-block; vertical-align:middle; }
.kpl-watch-star:hover { transform:scale(1.3); }
.kpl-watch-star.watched-concept { color:#ffc107; }

/* Search highlight */
.kpl-header.highlight { background: rgba(255, 193, 7, 0.12) !important; border-left: 3px solid #ffc107; }
.kpl-highlight { background: rgba(255, 193, 7, 0.2); color: #ffc107; padding: 0 2px; border-radius: 2px; }

/* Search match info */
.kpl-search-info { margin: 8px 0; padding: 10px 14px; background: rgba(0,212,255,0.06); border-radius: 8px; border-left: 3px solid #00d4ff; font-size: 0.85em; color: #aaa; }
.kpl-search-info strong { color: #00d4ff; }

/* 股票K线弹窗 */
.ds-stock-kline-section { margin-bottom: 16px; position: relative; }
.ds-stock-kline-label { color: #888; font-size: 0.85em; margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.ds-stock-kline-img { width: 100%; border-radius: 8px; border: 1px solid #0f3460; background: #fff; }
.img-refresh-btn {
    display: inline-flex; align-items: center; justify-content: center;
    width: 22px; height: 22px; border-radius: 50%;
    background: #0f3460; border: 1px solid rgba(0,212,255,0.2);
    color: #aaa; font-size: 0.7em; cursor: pointer;
    transition: all 0.2s; line-height: 1; padding: 0;
}
.img-refresh-btn:hover { background: #00d4ff; color: #0a1628; border-color: #00d4ff; }
.stock-detail-tag { display:inline-block; background:#0f3460; border:1px solid #00d4ff; padding:2px 10px; border-radius:12px; font-size:0.82em; color:#b0d4ff; margin:2px; }
.stock-detail-date-chip { display:inline-block; background:rgba(0,212,255,0.1); border:1px solid #0f3460; padding:1px 8px; border-radius:10px; font-size:0.78em; color:#888; }
/* 表格行鼠标悬浮高亮 - 同名称高亮 */
tr.ds-stock-hover td { background: rgba(0, 212, 255, 0.08) !important; }
.ds-name-link { cursor: pointer; color: #00d4ff; font-weight: 600; transition: color 0.15s; }
.ds-name-link:hover { color: #ff9800; }

/* Realtime Dashboard */
.rt-header {
    background: linear-gradient(135deg, #0a1628, #1a2a4a);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 15px;
    border: 1px solid #0f3460;
}
.rt-header h2 { color: #00d4ff; margin: 0 0 8px 0; font-size: 1.3em; }
.rt-header .rt-summary {
    display: flex; gap: 15px; flex-wrap: wrap; margin-top: 10px;
}
.rt-summary-item {
    background: rgba(0,212,255,0.06);
    border: 1px solid #0f3460;
    border-radius: 8px;
    padding: 10px 16px;
    text-align: center;
    min-width: 80px;
    flex: 1;
}
.rt-summary-item .rt-val { font-size: 1.4em; font-weight: bold; color: #ff6b6b; }
.rt-summary-item .rt-label { font-size: 0.75em; color: #888; margin-top: 2px; }

.rt-zt-table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 0.88em; }
.rt-zt-table th {
    background: #1a3a6a; color: #aac; padding: 7px 8px;
    text-align: left; font-size: 0.82em; font-weight: normal;
}
.rt-zt-table th.sortable { cursor: pointer; user-select: none; }
.rt-zt-table th.sortable:hover { background: #1f4a7a; color: #fff; }
.rt-zt-table td { padding: 6px 8px; border-bottom: 1px solid #0f3460; background: #1e2e4e; }
.rt-zt-table tr:hover td { background: #2a4070; }
.rt-zt-table tr.clickable { cursor: pointer; }

.rt-lb {
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-weight: bold; font-size: 0.85em; min-width: 30px; text-align: center;
}
.rt-lb-1 { background: rgba(0,123,255,0.2); color: #5a9cff; }
.rt-lb-2 { background: rgba(255,152,0,0.2); color: #ffb74d; }
.rt-lb-3 { background: rgba(255,87,34,0.2); color: #ff7043; }
.rt-lb-4 { background: rgba(233,30,99,0.3); color: #ff4081; }
.rt-lb-5 { background: rgba(156,39,176,0.3); color: #ce93d8; }
.rt-lb-high { background: linear-gradient(135deg, #e94560, #ff4081); color: #fff; }

.concept-chip {
    display: inline-block;
    background: #1e3a6a;
    color: #aad4ff;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 0.78em;
    margin: 1px 2px;
    cursor: pointer;
    transition: all 0.15s;
    border: 1px solid transparent;
}
.concept-chip:hover { background: #1a4a7a; color: #00d4ff; border-color: #00d4ff; }

/* KPL path display in tables */
.kpl-paths { margin-top: 2px; font-size: 0.78em; line-height: 1.8; }
.kpl-path-chip {
    display: inline-block;
    background: #1a2d4a;
    padding: 2px 8px;
    border-radius: 4px;
    margin: 2px 6px 2px 0;
    white-space: nowrap;
    border: 1px solid rgba(0,212,255,0.12);
}
.kpl-path-l1 { color: #00d4ff; cursor: pointer; }
.kpl-path-l2 { color: #4fc3f7; cursor: pointer; }
.kpl-path-l3 { color: #ffb74d; cursor: pointer; }
.kpl-path-l1:hover, .kpl-path-l2:hover, .kpl-path-l3:hover { text-decoration: underline; }
.kpl-path-sep { color: #555; margin: 0 3px; user-select: none; }

.lu-chip {
    display: inline-block;
    background: #3d1f00;
    color: #ffa726;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 0.78em;
    margin: 1px 2px;
    border: 1px solid transparent;
    white-space: nowrap;
}
.lu-chip-clickable {
    cursor: pointer;
    transition: all 0.15s;
    border-color: #5a3a00;
}
.lu-chip-clickable:hover {
    background: #5a3a00;
    color: #ffc107;
    border-color: #ffa726;
    box-shadow: 0 0 6px rgba(255,167,38,0.3);
}
.lu-chip-freq {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: rgba(255,167,38,0.15);
    color: #ffcc80;
    font-size: 0.75em;
    min-width: 14px;
    height: 14px;
    border-radius: 7px;
    padding: 0 4px;
    margin-left: 2px;
    vertical-align: middle;
}

.rt-section {
    background: #16213e;
    border-radius: 10px;
    padding: 15px;
    margin-bottom: 12px;
}
.rt-section h3 {
    color: #ff9800; font-size: 1em; margin: 0 0 10px 0;
    display: flex; align-items: center; gap: 6px;
}
.rt-section h3 .count-badge {
    background: #0f3460; color: #888; font-size: 0.75em;
    padding: 1px 8px; border-radius: 8px; font-weight: normal;
}

/* Trend grid for ladder + hot sections */
.trend-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
}
@media (max-width: 900px) { .trend-grid { grid-template-columns: 1fr; } }

.rt-tag-zt { color: #ff6b6b; font-weight: bold; }

/* Refresh banner */
.refresh-banner {
    background: linear-gradient(90deg, #e94560, #ff6b6b);
    color: #fff; text-align: center; padding: 6px;
    border-radius: 8px; font-size: 0.85em; margin-bottom: 12px;
}

/* Refresh icon for realtime section headings */
.rt-refresh-icon {
    display: inline-flex; align-items: center; justify-content: center;
    cursor: pointer; font-size: 0.85em;
    margin-left: auto; opacity: 0.5;
    transition: all 0.2s;
    width: 24px; height: 24px; border-radius: 50%;
    user-select: none;
}
.rt-refresh-icon:hover {
    opacity: 1; color: #ff9800;
    background: rgba(255,152,0,0.12);
}
.rt-refresh-icon:active {
    transform: scale(0.9);
}
.rt-refresh-icon.spinning {
    animation: rt-spin 0.6s linear infinite;
}
@keyframes rt-spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}

/* Auto-refresh toggle button */
.rt-auto-refresh-btn {
    display: inline-flex; align-items: center; gap: 4px;
    cursor: pointer; border: 1px solid rgba(255,255,255,0.25);
    border-radius: 16px; padding: 3px 12px;
    font-size: 0.8em; color: rgba(255,255,255,0.7);
    background: rgba(255,255,255,0.08);
    transition: all 0.3s; white-space: nowrap;
    line-height: 1.4;
}
.rt-auto-refresh-btn:hover {
    border-color: #00d4ff; color: #00d4ff;
    background: rgba(0,212,255,0.1);
}
.rt-auto-refresh-btn.active {
    background: rgba(0,212,255,0.15);
    border-color: #00d4ff; color: #00d4ff;
    box-shadow: 0 0 10px rgba(0,212,255,0.2);
}
.rt-auto-refresh-btn.active .rt-pulse-dot {
    display: inline-block;
    width: 6px; height: 6px; border-radius: 50%;
    background: #00d4ff;
    animation: rt-pulse 1.5s ease-in-out infinite;
}
@keyframes rt-pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.3; transform: scale(0.6); }
}

/* Toast notification */
.rt-toast {
    position: fixed; top: 20px; right: 20px; z-index: 99999;
    padding: 10px 18px; border-radius: 10px; font-size: 0.85em;
    color: #fff; max-width: 320px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    transform: translateX(120%); opacity: 0;
    transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
    pointer-events: none;
}
.rt-toast.show { transform: translateX(0); opacity: 1; }
.rt-toast.info { background: linear-gradient(135deg, #1a3a6a, #0f3460); border: 1px solid #00d4ff; }
.rt-toast.warning { background: linear-gradient(135deg, #5a3a00, #7a4a00); border: 1px solid #ffc107; }

/* Word frequency timeline */
.wf-timeline {
    display: flex; gap: 8px; overflow-x: auto; padding: 8px 4px 4px 4px;
}
.wf-day {
    flex: 0 0 auto; min-width: 130px; max-width: 160px;
    background: rgba(0,0,0,0.15); border-radius: 8px; padding: 8px;
    border: 1px solid #0f3460;
}
.wf-day-header {
    font-size: 0.75em; color: #888; text-align: center;
    padding-bottom: 6px; margin-bottom: 6px;
    border-bottom: 1px solid #0f3460;
    white-space: nowrap;
}
.wf-tag {
    display: inline-block; font-size: 0.72em;
    padding: 2px 5px; margin: 1px;
    border-radius: 3px; cursor: pointer;
    transition: all 0.15s;
    white-space: nowrap;
}
.wf-tag:hover {
    transform: scale(1.05); box-shadow: 0 0 6px rgba(0,212,255,0.3);
}
.wf-tag-high { background: rgba(255,107,107,0.2); color: #ff6b6b; border: 1px solid rgba(255,107,107,0.3); }
.wf-tag-mid { background: rgba(255,167,38,0.15); color: #ffa726; border: 1px solid rgba(255,167,38,0.2); }
.wf-tag-low { background: rgba(0,212,255,0.1); color: #4fc3f7; border: 1px solid rgba(0,212,255,0.15); }
.wf-tag .wf-count { font-size: 0.75em; opacity: 0.6; margin-left: 1px; }
.wf-day-empty { color: #555; font-size: 0.75em; text-align: center; padding: 10px 0; }
.wf-level { margin: 3px 0; padding: 2px 0; border-bottom: 1px solid rgba(15,52,96,0.3); }
.wf-level:last-child { border-bottom: none; }
.wf-level-label { display: inline-block; font-size: 0.65em; font-weight: bold; margin-right: 4px; vertical-align: top; line-height: 1.8; min-width: 18px; }

/* Update status bar */
#updateArea {
    display: inline-flex; align-items: center; gap: 6px;
    margin-left: 12px; font-size: 0.9em; line-height: 1;
}
#updateDataBtn {
    cursor: pointer; border: 1px solid #444; border-radius: 10px;
    padding: 1px 10px; font-size: 0.9em; transition: all 0.2s;
    color: #888; background: transparent;
    white-space: nowrap;
}
#updateDataBtn:hover { color: #00d4ff; border-color: #00d4ff; }
#updateDataBtn:disabled { cursor: not-allowed; opacity: 0.5; }
#updateDataBtn.status-idle { color: #888; border-color: #444; }
#updateDataBtn.status-checking { color: #ffc107; border-color: #ffc107; }
#updateDataBtn.status-running { color: #00d4ff; border-color: #00d4ff; }
#updateDataBtn.status-done { color: #4caf50; border-color: #4caf50; }
#updateDataBtn.status-error { color: #ff5252; border-color: #ff5252; }
#updateDataBtn.status-skip { color: #888; border-color: #555; }
#updateHint {
    font-size: 0.8em; color: #666; white-space: nowrap;
    transition: all 0.3s;
}
#updateHint.hint-checking { color: #ffc107; }
#updateHint.hint-running { color: #00d4ff; }
#updateHint.hint-done { color: #4caf50; }
#updateHint.hint-error { color: #ff5252; }
#updateHint.hint-skip { color: #666; }

/* 涨停深挖 Tab */
.reason-hl { background: #ffd54f; color: #1a1a2e; padding: 1px 4px; border-radius: 3px; font-weight: bold; }
.tag-badge { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 0.78em; margin: 1px 2px; font-weight: bold; }
.tag-badge.shouban { background: rgba(0,123,255,0.2); color: #5a9cff; }
.tag-badge.liangban { background: rgba(255,152,0,0.2); color: #ffb74d; }
.tag-badge.sanban { background: rgba(233,30,99,0.2); color: #ff4081; }
.tag-badge.gaoban { background: rgba(156,39,176,0.3); color: #ce93d8; }
.status-badge { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 0.78em; margin: 1px 2px; }
.status-badge.huan { background: rgba(0,212,255,0.15); color: #00d4ff; }
.status-badge.yizi { background: rgba(76,175,80,0.2); color: #81c784; }
.or-section { margin-bottom: 18px; }
.or-section h4 { color: #ff9800; font-size: 1em; margin: 0 0 8px 0; padding-bottom: 4px; border-bottom: 1px solid #0f3460; }
.ds-result-count { color: #888; font-size: 0.85em; margin-bottom: 12px; }
.ds-name-link { color: #00d4ff; cursor: pointer; font-weight: bold; }
.ds-name-link:hover { text-decoration: underline; color: #ff6b6b; }

/* 涨停深挖 - 多视图样式 */
.ds-view-section { display: none; }
.ds-view-section.active { display: block; }
.ds-view-section .section-title { color: #ff9800; font-size: 1.1em; margin: 15px 0 10px 0; padding-bottom: 6px; border-bottom: 1px solid #0f3460; }

/* 频度标签 */
.freq-cloud { display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 0; }
.freq-chip {
    display: inline-flex; flex-direction: column; align-items: center;
    background: #0f3460; border: 1px solid #0f3460; border-radius: 8px;
    padding: 6px 12px; cursor: default; transition: all 0.15s;
    min-width: 70px; position: relative; overflow: hidden;
}
.freq-chip .freq-name { color: #ddd; font-size: 0.85em; font-weight: 600; z-index: 1; }
.freq-chip .freq-count { color: #00d4ff; font-size: 1.1em; font-weight: bold; z-index: 1; }
.freq-chip .freq-bar {
    position: absolute; bottom: 0; left: 0; right: 0;
    background: rgba(0,212,255,0.12); height: 100%; z-index: 0;
    transition: width 0.3s;
}

/* 个股频度表格 */
.ds-stock-link { color: #00d4ff; cursor: pointer; font-weight: bold; }
.ds-stock-link:hover { text-decoration: underline; color: #ff6b6b; }
.chain-badge {
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-weight: bold; font-size: 0.82em; min-width: 28px; text-align: center;
}
.chain-badge.c1 { background: rgba(0,123,255,0.2); color: #5a9cff; }
.chain-badge.c2 { background: rgba(255,152,0,0.2); color: #ffb74d; }
.chain-badge.c3 { background: rgba(255,87,34,0.2); color: #ff7043; }
.chain-badge.c4 { background: rgba(156,39,176,0.3); color: #ce93d8; }

/* 日期分布条形图 */
.dist-chart { display: flex; align-items: flex-end; gap: 3px; padding: 15px 5px; min-height: 200px; overflow-x: auto; }
.dist-bar-wrapper { display: flex; flex-direction: column; align-items: center; min-width: 36px; }
.dist-bar {
    width: 28px; background: linear-gradient(180deg, #00d4ff, #0066cc);
    border-radius: 3px 3px 0 0; min-height: 2px; transition: height 0.3s;
    cursor: pointer; position: relative;
}
.dist-bar:hover { opacity: 0.8; }
.dist-bar-label { font-size: 0.6em; color: #888; margin-top: 4px; writing-mode: vertical-lr; text-orientation: mixed; transform: rotate(180deg); white-space: nowrap; }
.dist-bar-count { font-size: 0.7em; color: #00d4ff; margin-bottom: 2px; font-weight: bold; }

/* 连板总结卡片 */
.summary-grid { display: flex; flex-direction: column; gap: 12px; }
.summary-card {
    background: #16213e; border: 1px solid #0f3460; border-radius: 10px;
    padding: 12px 16px; transition: border-color 0.2s;
}
.summary-card:hover { border-color: #00d4ff; }
.summary-card .sc-header {
    display: flex; align-items: center; gap: 10px; margin-bottom: 8px;
    padding-bottom: 6px; border-bottom: 1px solid #0f3460;
}
.summary-card .sc-concept { color: #ff9800; font-size: 1em; font-weight: bold; }
.summary-card .sc-meta { color: #888; font-size: 0.8em; margin-left: auto; }
.summary-card .sc-stock-list { display: flex; flex-wrap: wrap; gap: 6px; }
.summary-card .sc-stock {
    display: flex; align-items: center; gap: 6px;
    background: #1a1a2e; border: 1px solid #333; border-radius: 6px;
    padding: 5px 10px; font-size: 0.82em;
}
.summary-card .sc-stock:hover { border-color: #00d4ff; cursor: pointer; }
.summary-card .sc-stock-name { color: #ddd; font-weight: 600; }
.summary-card .sc-stock-code { color: #888; font-size: 0.85em; }

/* 搜索统计标签（复刻hot_analysis.html） */
.reason-stats { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0 10px 0; }
.reason-stat-chip {
    display: inline-flex; align-items: center; gap: 4px;
    background: #0f3460; border: 1px solid #1a3a6a; border-radius: 14px;
    padding: 3px 10px; font-size: 0.78em; cursor: pointer;
    transition: all 0.15s; color: #ccc;
}
.reason-stat-chip:hover { border-color: #00d4ff; background: #16213e; }
.reason-stat-chip .name { color: #fff; font-weight: 600; }
.reason-stat-chip .count { color: #ff6b6b; font-weight: bold; }
.reason-stat-chip .board { color: #ffb74d; font-weight: bold; margin-left: 2px; padding: 0 3px; }
.reason-stat-chip .board.high { color: #ff4081; }
.reason-stat-chip .dates { color: #888; font-size: 0.92em; }
.or-section-title {
    color: #ff9800; font-size: 1.05em; font-weight: bold;
    margin: 16px 0 8px 0; padding-bottom: 6px;
    border-bottom: 1px solid #0f3460;
}
.or-divider { border: none; border-top: 1px solid #0f3460; margin: 18px 0; }
.concept-btn {
    background: linear-gradient(135deg, #1a3a6a, #0f3460);
    color: #00d4ff; border: 1px solid #0f3460; border-radius: 6px;
    padding: 4px 12px; font-size: 0.82em; cursor: pointer;
    transition: all 0.15s;
}
.concept-btn:hover { background: #1a3a6a; border-color: #00d4ff; }

/* K线网格 */
.concept-kline-wrap { overflow: hidden; transition: max-height .3s ease; }
.concept-kline-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 8px; padding: 8px 0; }
.concept-kline-cell {
    border: 1px solid #0f3460; border-radius: 8px; padding: 6px 6px 8px;
    background: #16213e; text-align: center;
}
.concept-kline-cell .sk-header {
    display: flex; align-items: center; justify-content: center; gap: 6px;
    padding: 4px 8px; margin: -6px -6px 6px;
    border-radius: 8px 8px 0 0;
    background: linear-gradient(135deg, #1a3a6a, #0f3460); color: #fff;
}
.concept-kline-cell .sk-name { font-size: 13px; font-weight: 700; }
.concept-kline-cell .sk-code { font-size: 10px; opacity: 0.8; padding: 1px 6px; border-radius: 8px; background: rgba(255,255,255,0.15); }
.concept-kline-cell .sk-concepts { margin-left: auto; font-size: 9px; color: #888; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60%; text-align: right; flex-shrink: 1; }
.concept-kline-cell .kline-img { width: 100%; height: auto; border-radius: 4px; background: #fff; margin-bottom: 3px; display: block; border: 1px solid #0f3460; }
.concept-kline-cell .kline-img.min { margin-bottom: 0; }
.concept-kline-cell .min-fallback { display: flex; align-items: center; justify-content: center; height: 48px; background: rgba(255,255,255,0.05); border-radius: 4px; color: #888; font-size: 12px; border: 1px dashed #333; margin-bottom: 3px; }

/* 日期分布图 */
.dist-chart { margin: 8px 0; }
.dist-bar-row { display: flex; align-items: center; gap: 6px; margin: 2px 0; }
.dist-label { min-width: 70px; color: #888; font-size: 0.78em; text-align: right; }
.dist-bar-track { flex: 1; height: 14px; background: #0d1b36; border-radius: 7px; overflow: hidden; }
.dist-bar-fill { height: 100%; background: linear-gradient(90deg, #00d4ff, #ff6b6b); border-radius: 7px; transition: width 0.3s; }
.dist-count { min-width: 30px; color: #aaa; font-size: 0.78em; }
.freq-chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
.freq-chip {
    display: inline-block; background: #162d50; color: #88c0ff;
    padding: 3px 10px; border-radius: 12px; font-size: 0.82em;
    cursor: pointer; border: 1px solid #2a4a7a; transition: all 0.15s;
}
.freq-chip:hover { background: #1a4a7a; color: #00d4ff; border-color: #00d4ff; }
.freq-chip .count { color: #ff6b6b; font-weight: bold; margin-left: 2px; }

/* 子概念标签 */
.sub-tag {
    display: inline-block; background: #162d50; color: #88c0ff;
    padding: 2px 8px; border-radius: 10px; font-size: 0.78em;
    margin: 2px 3px; cursor: pointer; border: 1px solid #2a4a7a; transition: all 0.15s;
}
.sub-tag:hover { background: #1a4a7a; color: #00d4ff; border-color: #00d4ff; }

/* 个股查询tab */
.sq-header { display:flex; align-items:center; gap:12px; margin:16px 0; padding:12px 16px; background:#16213e; border-radius:10px; border-left:3px solid #00d4ff; }
.sq-header h2 { margin:0; color:#00d4ff; font-size:1.1em; }
.sq-header .sq-code { color:#888; font-size:0.85em; }

.sq-concepts { margin:12px 0; padding:12px 16px; background:rgba(0,212,255,0.04); border-radius:8px; }
.sq-concepts-label { color:#00d4ff; font-size:0.88em; font-weight:bold; margin-bottom:8px; }

.sq-kline-row { display:flex; gap:12px; margin:12px 0; }
.sq-kline-col { flex:1; background:#16213e; border-radius:8px; padding:12px; border:1px solid #0f3460; }
.sq-kline-col img { width:100%; height:auto; display:block; }

.sq-section { margin:16px 0; }
.sq-section-title { color:#4fc3f7; font-size:0.9em; font-weight:bold; margin-bottom:8px; padding-bottom:4px; border-bottom:1px solid #0f3460; }
/* 个股查询KPL记录表格 */
.sq-section table { width:100%; border-collapse:collapse; font-size:0.85em; }
.sq-section table th { background:#0f3460; color:#90caf9; padding:6px 8px; text-align:left; white-space:nowrap; position:sticky; top:0; }
.sq-section table td { padding:5px 8px; border-bottom:1px solid #0f3460; vertical-align:middle; }
.sq-section table tbody tr:hover { background:rgba(0,212,255,0.06); }

/* ETF 基金 tab */
.etf-summary { display:flex; gap:16px; padding:12px 16px; background:linear-gradient(135deg,#1a2a4e,#0f3460); border-radius:10px; margin:12px 0; flex-wrap:wrap; align-items:center; }
.etf-summary-item { color:#b0bec5; font-size:0.85em; }
.etf-summary-item span { color:#e0e0e0; font-weight:bold; }
.etf-summary-item .up { color:#ff6b6b; }
.etf-summary-item .down { color:#4caf50; }

.etf-category { margin:16px 0; }
.etf-category-title { display:flex; align-items:center; gap:12px; padding:8px 14px; background:linear-gradient(135deg,#1a2a4e,#0f3460); border-left:3px solid #00d4ff; border-radius:4px; margin-bottom:10px; cursor:pointer; user-select:none; }
.etf-category-title .cat-name { color:#00d4ff; font-weight:bold; font-size:0.9em; }
.etf-category-title .cat-count { color:#4fc3f7; font-size:0.78em; }
.etf-category-title .cat-up { color:#ff6b6b; font-size:0.78em; margin-left:auto; }
.etf-category-title .cat-down { color:#4caf50; font-size:0.78em; }

.etf-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
@media(max-width:900px) { .etf-grid { grid-template-columns:repeat(2,1fr); } }
@media(max-width:600px) { .etf-grid { grid-template-columns:1fr; } }

.etf-card { background:#16213e; border-radius:8px; border:1px solid #0f3460; padding:10px 12px; transition:border-color 0.15s; cursor:pointer; }
.etf-card:hover { border-color:#4fc3f7; }
.etf-card-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:6px; }
.etf-card-name { color:#e0e0e0; font-weight:bold; font-size:0.88em; }
.etf-card-code { color:#546e7a; font-size:0.72em; }
.etf-card-price { margin:4px 0; }
.etf-card-price-val { color:#e0e0e0; font-size:1.1em; font-weight:bold; }
.etf-card-price-unit { color:#78909c; font-size:0.72em; margin-left:2px; }
.etf-change-up { color:#ff6b6b; }
.etf-change-down { color:#4caf50; }
.etf-change-zero { color:#78909c; }
.etf-meta { display:flex; gap:12px; margin-top:4px; font-size:0.75em; color:#546e7a; }
.etf-meta span { white-space:nowrap; }

.etf-charts { display:flex; gap:6px; margin-top:8px; }
.etf-chart-col { flex:1; min-width:0; }
.etf-chart-col img { width:100%; height:auto; display:block; border-radius:4px; cursor:pointer; background:#fff; }
.etf-chart-col .mini-label { color:#546e7a; font-size:0.62em; text-align:center; margin-bottom:2px; }

/* ETF L2 subcategory */
.etf-subcategory { margin-left:16px; border-left:2px solid rgba(79,195,247,0.25); padding-left:12px; margin-bottom:8px; }
.etf-subcategory-title { display:flex; align-items:center; gap:8px; padding:5px 10px; background:rgba(79,195,247,0.06); border-radius:4px; cursor:pointer; font-size:0.82em; color:#80cbc4; transition:background 0.15s; margin-bottom:4px; }
.etf-subcategory-title:hover { background:rgba(79,195,247,0.12); }
.etf-subcategory-title .subcat-arrow { font-size:0.65em; color:#4fc3f7; transition:transform 0.2s; }
.etf-subcategory-title .subcat-name { font-weight:bold; min-width:72px; }
.etf-subcategory-title .subcat-top3 { margin-left:2em; font-size:0.76em; display:flex; gap:8px; align-items:center; flex-wrap:wrap; flex:1; }
.etf-subcategory-title .subcat-top3-item { white-space:nowrap; display:inline-flex; align-items:baseline; gap:4px; }
.etf-subcategory-title .subcat-top3-chg { font-weight:bold; margin-left:2px; border-radius:4px; padding:1px 6px; }
.etf-subcategory-title .subcat-top3-chg.etf-change-up { color:#fff; background:#c62828; }
.etf-subcategory-title .subcat-top3-chg.etf-change-down { color:#fff; background:#2e7d32; }
.etf-subcategory-title .subcat-top3-sep { color:#455a64; font-size:0.8em; }
.etf-search-wrap { margin:8px 0; }
.etf-search { width:100%; padding:9px 14px; border-radius:8px; border:1px solid #0f3460; background:rgba(15,52,96,0.4); color:#e0e0e0; font-size:0.85em; outline:none; transition:border-color 0.2s; }
.etf-search:focus { border-color:#4fc3f7; background:rgba(15,52,96,0.6); }
.etf-search::placeholder { color:#546e7a; }
.etf-subcat-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
@media(max-width:900px) { .etf-subcat-grid { grid-template-columns:repeat(2,1fr); } }
@media(max-width:600px) { .etf-subcat-grid { grid-template-columns:1fr; } }

/* ETF 浮动导航 */
.etf-wrapper { display:flex; align-items:flex-start; gap:18px; }
.etf-sidebar {
    position:sticky; top:20px; width:150px; flex-shrink:0;
    background:rgba(15,52,96,0.55); backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px);
    border-radius:12px; border:1px solid rgba(0,212,255,0.12);
    padding:8px 0; z-index:10; max-height:90vh; overflow-y:auto;
}
.etf-sidebar-item {
    display:block; padding:7px 12px; font-size:0.78em; color:#888;
    cursor:pointer; transition:all 0.2s;
    border-left:3px solid transparent; text-decoration:none; line-height:1.3;
}
.etf-sidebar-item:hover { color:#ddd; background:rgba(0,212,255,0.05); }
.etf-sidebar-item.active { color:#00d4ff; border-left-color:#00d4ff; background:rgba(0,212,255,0.08); }
.etf-sidebar-subitem {
    display:block; padding:4px 12px 4px 24px; font-size:0.72em; color:#777;
    cursor:pointer; transition:all 0.2s; line-height:1.3; text-decoration:none;
}
.etf-sidebar-subitem:hover { color:#00d4ff; background:rgba(0,212,255,0.05); }
.etf-main-content { flex:1; min-width:0; }
@media(max-width:768px) { .etf-sidebar { display:none; } }

/* ETF 三章节布局 */
.etf-section { margin:20px 0; }
.etf-section-title { display:flex; align-items:center; gap:10px; padding:10px 16px; background:linear-gradient(135deg,#1a2a4e,#0f3460); border-radius:10px; margin-bottom:14px; font-size:0.95em; color:#e0e0e0; border-left:4px solid #00d4ff; }
.etf-section-num { display:inline-flex; align-items:center; justify-content:center; width:24px; height:24px; border-radius:50%; background:#00d4ff; color:#0d1b2a; font-weight:bold; font-size:0.8em; }

/* 关注星标 */
.etf-watch-star { cursor:pointer; font-size:1.2em; color:#546e7a; margin-left:auto; transition:color 0.2s,transform 0.15s; user-select:none; line-height:1; }
.etf-watch-star:hover { transform:scale(1.25); }
.etf-watch-star.etf-watch-star-on { color:#ffd54f; text-shadow:0 0 6px rgba(255,213,79,0.5); }

/* 关注列表 */
.etf-watch-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
.etf-watch-card { background:#16213e; border-radius:8px; border:1px solid #2a4a6e; padding:10px 12px; transition:border-color 0.15s; cursor:pointer; }
.etf-watch-card:hover { border-color:#4fc3f7; }
.etf-watch-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:6px; }
@media(max-width:1100px) { .etf-watch-grid { grid-template-columns:repeat(3,1fr); } }
@media(max-width:700px) { .etf-watch-grid { grid-template-columns:repeat(2,1fr); } }
@media(max-width:450px) { .etf-watch-grid { grid-template-columns:1fr; } }


/* sq-tree hierarchy */
.sq-tree-wrap { background:rgba(0,212,255,0.03); border-radius:12px; border:1px solid #0f3460; padding:8px 0; margin:8px 0; }
.sq-tree-l1-header {
    display:flex; align-items:center; gap:8px; padding:8px 14px;
    background:linear-gradient(135deg, #1a2a4e, #0f3460);
    border-left:3px solid #00d4ff; border-radius:4px; margin:4px 8px;
    cursor:pointer; transition:filter 0.15s;
}
.sq-tree-l1-header:hover { filter:brightness(1.2); }
.sq-tree-l1-header .sq-arrow { color:#4fc3f7; font-size:0.7em; }
.sq-tree-l1-header .sq-label { color:#00d4ff; font-weight:bold; font-size:0.85em; }
.sq-tree-l1-header .sq-goto { margin-left:auto; color:#4fc3f7; font-size:0.65em; opacity:0.4; }
.sq-tree-l1-header:hover .sq-goto { opacity:1; }

.sq-tree-l2-header {
    display:flex; align-items:center; gap:6px; padding:6px 12px;
    margin:0 8px 0 24px; border-left:2px solid #4fc3f7;
    cursor:pointer; transition:background 0.15s;
}
.sq-tree-l2-header:hover { background:rgba(79,195,247,0.08); }
.sq-tree-l2-header .sq-label { color:#4fc3f7; font-size:0.83em; font-weight:bold; }
.sq-tree-l2-header .sq-goto { margin-left:auto; color:#4fc3f7; font-size:0.65em; opacity:0.4; }
.sq-tree-l2-header:hover .sq-goto { opacity:1; }

.sq-tree-l3-header {
    display:flex; align-items:center; gap:6px; padding:4px 10px;
    margin:0 8px 0 40px; background:rgba(255,152,0,0.06);
    border-left:2px solid rgba(255,152,0,0.2);
    cursor:pointer; transition:background 0.15s;
}
.sq-tree-l3-header:hover { background:rgba(255,152,0,0.14); }
.sq-tree-l3-header .sq-label { color:#ffb74d; font-size:0.82em; }
.sq-tree-l3-header .sq-goto { margin-left:auto; color:#ffb74d; font-size:0.65em; opacity:0.4; }
.sq-tree-l3-header:hover .sq-goto { opacity:1; }

.sq-stock-row { padding:6px 8px 6px 52px; display:flex; flex-wrap:wrap; gap:4px; }
.sq-stock-link {
    display:inline-flex; align-items:center; gap:4px;
    background:#0f3460; color:#b0d4ff; cursor:pointer;
    font-size:0.82em; padding:3px 12px; border-radius:14px;
    border:1px solid rgba(0,212,255,0.15); transition:all 0.15s;
}
.sq-stock-link:hover { background:#00d4ff; color:#0a1628; border-color:#00d4ff; }
.sq-stock-link .sq-link-icon { font-size:0.65em; opacity:0.6; }
.sq-stock-link.sq-stock-highlight { background:#ffc107; color:#1a1a2e; border-color:#ffc107; font-weight:bold; box-shadow:0 0 8px rgba(255,193,7,0.4); }
</style>
</head>
<body>
<div class="container">
    <h1 style="margin:20px 0 5px 0;text-align:center;">📊 A股题材轮动分析系统</h1>
    <p class="sub">N字战法·涨停回调 | T+0同日联动 | 双源涨停检测 | 方向性分析 | 概念轮动</p>
    <p class="sub" style="font-size:0.75em;color:#555;margin-top:2px;">
        <span id="dataStatus">加载中...</span>
        <span id="updateArea">
            <span id="updateDataBtn" onclick="updateAllData()" class="status-idle">🔄 更新</span>
            <span id="updateHint"></span>
        </span>
    </p>

    <div class="tabs">
        <div class="tab active" onclick="switchTab('realtime')">📡 实时</div>
        <div class="tab" onclick="switchTab('alertmon')">⚠ 异动跟踪</div>
        <div class="tab" onclick="switchTab('npattern')">N字战法</div>
        <div class="tab" onclick="switchTab('linkage')">联动查询</div>
        <div class="tab" onclick="switchTab('concept')">概念分析</div>
        <div class="tab" onclick="switchTab('kpltree')"><img src="data:image/png;base64,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" style="width:16px;height:16px;vertical-align:middle;margin-right:3px;"> 开盘啦</div>
        <div class="tab" onclick="switchTab('kplsearch')">KPL涨停深挖</div>
        <div class="tab" onclick="switchTab('deepsearch')">🔍 涨停深挖</div>
        <div class="tab" onclick="switchTab('stockquery')">📋 个股查询</div>
        <div class="tab" onclick="switchTab('etf')">📊 ETF基金</div>
        <div class="tab" onclick="switchTab('specialwatch')">⭐ 特别关注</div>
        <div class="tab" onclick="switchTab('sniper')">🎯 精准狙击</div>
        <div class="tab" onclick="switchTab('stats')">📈 统计</div>
    </div>

    <div class="tab-content active" id="tab-realtime">
        <div id="realtimeContainer"><div class="loading">加载实时看板...</div></div>
    </div>
    <div class="tab-content" id="tab-alertmon">
        <div id="alertmonContainer"></div>
    </div>
    <div class="tab-content" id="tab-npattern">
        <div id="npatternContainer"><div class="loading">加载N字战法分析中...</div></div>
    </div>
    <div class="tab-content" id="tab-linkage">
        <div class="search-box">
            <div class="input-row">
                <div class="input-item">
                    <label>股票代码或名称</label>
                    <input type="text" id="linkageStockInput" placeholder="如: 600396 或 华电辽能" autocomplete="off">
                    <div class="suggestions" id="linkageSuggestions"></div>
                </div>
                <div style="display: flex; align-items: flex-end;">
                    <button onclick="doLinkageSearch()">查询联动</button>
                </div>
            </div>
        </div>
        <div id="resultContainer">
            <div id="linkageDefaultSections"><div class="loading">加载默认联动数据...</div></div>
        </div>
    </div>
    <div class="tab-content" id="tab-concept">
        <div class="search-box">
            <div class="input-row">
                <div class="input-item" style="position:relative;">
                    <label>概念（细分）名称</label>
                    <input type="text" id="conceptQueryInput" placeholder="如: 存储芯片、MLCC、绿色电力、光刻胶" autocomplete="off">
                    <div class="suggestions" id="conceptSuggestions"></div>
                </div>
                <div style="display: flex; align-items: flex-end;">
                    <button onclick="doConceptSearch()">分析概念</button>
                </div>
            </div>
            <div class="filter-bar" style="margin-top:6px;">
                <label class="checkbox-label">
                    <input type="checkbox" id="conceptSourceThs" checked>THS
                </label>
                <label class="checkbox-label">
                    <input type="checkbox" id="conceptSourceReason" checked>涨停理由
                </label>
            </div>
        </div>
        <div id="topConceptTable"></div>
        <div id="conceptResult"><div class="empty">输入概念名称进行分析</div></div>
    </div>
    <div class="tab-content" id="tab-kpltree">
        <div class="search-box">
            <div class="input-row">
                <div class="input-item" style="position:relative;">
                    <label>搜索股票名称或概念</label>
                    <input type="text" id="kplSearchInput" placeholder="如: 赣锋锂业、盐湖提锂、GPU" autocomplete="off">
                    <div class="suggestions" id="kplSuggestions"></div>
                </div>
            </div>
        </div>
        <div id="kplTreeContainer"><div class="loading">加载题材结构...</div></div>
    </div>
    <div class="tab-content" id="tab-kplsearch">
        <div class="search-box">
            <div class="input-row">
                <div class="input-item" style="position:relative;">
                    <label>搜索股票/板块/涨停标签/概念</label>
                    <input type="text" id="kplSearchInput2" placeholder="支持单关键词、OR(|)、AND(&)。如: 机器人、算力|金属、芯片&军工" autocomplete="off">
                    <div class="suggestions" id="kplSearchSuggestions"></div>
                </div>
            </div>
            <div class="filter-bar">
                <label class="checkbox-label">
                    <input type="checkbox" id="kplNoStCheck" checked>不含ST
                </label>
                <label class="checkbox-label" style="margin-left:0;">
                    <input type="checkbox" id="kplStrictCheck">仅标签搜索
                </label>
                <div class="date-group">
                    <label>开始</label>
                    <input type="date" id="kplSearchDateStart">
                    <label>结束</label>
                    <input type="date" id="kplSearchDateEnd">
                </div>
                <div class="btn-group">
                    <button onclick="doKplSearch()">搜索</button>
                    <button onclick="resetKplSearch()" class="btn-con">重置</button>
                </div>
            </div>
        </div>
        <div class="kpl-status-bar">
            <span class="status-text" id="kplDataStatus">涨停原因数据</span>
            <span style="display:flex;align-items:center;gap:4px;">
                <button class="update-btn" onclick="doKplUpdate(this)" title="检查并补全缺失交易日的涨停原因">&#x21bb; 检查更新</button>
            </span>
        </div>
        <div id="kplSearchResult"><div class="empty">输入关键词搜索KPL涨停数据</div></div>
    </div>
    <div class="tab-content" id="tab-deepsearch">
        <div class="search-box">
            <div class="input-row">
                <div class="input-item" style="position:relative;">
                    <label>搜索股票或涨停理由</label>
                    <input type="text" id="deepSearchInput" placeholder="支持单关键词、OR(|)、AND(&)。如: 光刻胶、算力|AI、机器人&军工" autocomplete="off">
                    <div class="suggestions" id="deepSearchSuggestions"></div>
                </div>
            </div>
            <div class="filter-bar">
                <label class="checkbox-label">
                    <input type="checkbox" id="noStCheck" checked>不含ST
                </label>
                <div class="date-group">
                    <label>开始</label>
                    <input type="date" id="deepSearchDateStart">
                    <label>结束</label>
                    <input type="date" id="deepSearchDateEnd">
                </div>
                <div class="btn-group">
                    <button onclick="doDeepSearch()">搜索</button>
                    <button onclick="resetDeepSearch()" class="btn-con">重置</button>
                </div>
            </div>
        </div>
        <div id="deepSearchResult"><div class="empty">输入关键词和时间范围搜索涨停理由</div></div>
    </div>
    <div class="tab-content" id="tab-stockquery">
        <div class="search-box">
            <div class="input-row">
                <div class="input-item" style="position:relative;">
                    <label>搜索股票名称或代码</label>
                    <input type="text" id="stockQueryInput" placeholder="如: 600396 或 华电辽能" autocomplete="off">
                    <div class="suggestions" id="stockQuerySuggestions"></div>
                </div>
                <div style="display:flex;align-items:flex-end;">
                    <button onclick="stockQueryDoSearch()">查询</button>
                </div>
            </div>
        </div>
        <div id="stockQueryResult">
            <div class="empty">搜索股票名称或代码查看个股详情</div>
        </div>
    </div>
    <div class="tab-content" id="tab-etf">
        <div id="etfContainer"><div class="loading">加载ETF数据...</div></div>
    </div>
    <div class="tab-content" id="tab-specialwatch">
        <div id="specialwatchContainer"><div class="loading">加载特别关注...</div></div>
    </div>
    <!-- 股票K线弹窗 -->
    <div id="dsStockModal" class="kline-modal-overlay" onclick="if(event.target===this)closeDsStockModal()">
        <div class="kline-modal" style="max-width:700px;">
            <div class="kline-modal-header">
                <span class="kline-modal-close" onclick="closeDsStockModal()">&times;</span>
            </div>
            <div class="kline-modal-title-area" style="text-align:center; margin-bottom:16px;">
                <h3 id="dsStockModalTitle" style="margin:0;">Loading...</h3>
            </div>
            <div id="dsStockModalBody"></div>
        </div>
    </div>
    </div>
    <div class="tab-content" id="tab-sniper">
        <div id="sniperContainer"><div class="loading">加载精准狙击数据中...</div></div>
    </div>
    <div class="tab-content" id="tab-stats">
        <div id="statsContainer"><div class="loading">加载统计中...</div></div>
    </div>
</div>

<div id="klineModal" class="kline-modal-overlay" onclick="if(event.target===this)closeKlineModal()">
    <div class="kline-modal" id="klineModalContent">
        <div class="kline-modal-header">
            <span class="kline-modal-nav-btn" id="klinePrevBtn" onclick="navigateCard(-1)" title="上一个 (←)">&#9664;</span>
            <div class="kline-modal-title-area">
                <h3 id="klineModalTitle">Loading...</h3>
                <span id="klineModalCounter" class="kline-modal-counter"></span>
            </div>
            <span class="kline-modal-nav-btn" id="klineNextBtn" onclick="navigateCard(1)" title="下一个 (→)">&#9654;</span>
            <span class="kline-modal-close" onclick="closeKlineModal()">&times;</span>
        </div>
        <div id="klineModalBadges" class="np-card-badges"></div>
        <div id="klineModalMetrics" class="np-metrics"></div>
        <div id="klineModalCanvas" style="margin-top:12px;"><canvas id="klineModalChart" height="280"></canvas></div>
    </div>
</div>

<!-- 卡片内容放大弹框 -->
<div id="enlargeCardModal" class="kline-modal-overlay" onclick="if(event.target===this)closeEnlargeCardModal()">
    <div class="kline-modal enlarge-card-modal">
        <div class="kline-modal-header">
            <span class="kline-modal-close" onclick="closeEnlargeCardModal()">&times;</span>
        </div>
        <div id="enlargeCardModalBody"></div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js"></script>
<script>
Chart.register(ChartDataLabels);

var currentTab = 'realtime';
var _tabCache = {};

function _cachedFetch(url) {
    if (_tabCache[url] !== undefined) {
        if (_tabCache[url] instanceof Promise) return _tabCache[url];
        return Promise.resolve(_tabCache[url]);
    }
    var p = fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (Array.isArray(data) && data.length === 0) {
                delete _tabCache[url];
                return data;
            }
            _tabCache[url] = data;
            return data;
        })
        .catch(function(e) { delete _tabCache[url]; throw e; });
    _tabCache[url] = p;
    return p;
}

function _clearTabCache() { _tabCache = {}; }

function _prefetchAllTabs() {
    _cachedFetch('/api/stats');
    _cachedFetch('/api/stats?top_n=20');
    _cachedFetch('/api/hot_stocks?top_n=200');
    _cachedFetch('/api/hot_stocks?top_n=100');
    _cachedFetch('/api/hot_concept_20');
    _cachedFetch('/api/hot_rank_100');
    _cachedFetch('/api/lianban_ladder?top_n=10');
    _cachedFetch('/api/sniper_data');
    _cachedFetch('/api/n_pattern');
    _cachedFetch('/api/abnormal_movement');
}

// Tab switching
function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    if (tab === 'realtime') document.querySelectorAll('.tab')[0].classList.add('active');
    else if (tab === 'alertmon') document.querySelectorAll('.tab')[1].classList.add('active');
    else if (tab === 'npattern') document.querySelectorAll('.tab')[2].classList.add('active');
    else if (tab === 'linkage') document.querySelectorAll('.tab')[3].classList.add('active');
    else if (tab === 'concept') document.querySelectorAll('.tab')[4].classList.add('active');
    else if (tab === 'kpltree') document.querySelectorAll('.tab')[5].classList.add('active');
    else if (tab === 'kplsearch') document.querySelectorAll('.tab')[6].classList.add('active');
    else if (tab === 'deepsearch') document.querySelectorAll('.tab')[7].classList.add('active');
    else if (tab === 'stockquery') document.querySelectorAll('.tab')[8].classList.add('active');
    else if (tab === 'etf') document.querySelectorAll('.tab')[9].classList.add('active');
    else if (tab === 'specialwatch') document.querySelectorAll('.tab')[10].classList.add('active');
    else if (tab === 'sniper') document.querySelectorAll('.tab')[11].classList.add('active');
    else if (tab === 'stats') document.querySelectorAll('.tab')[12].classList.add('active');
    document.getElementById('tab-' + tab).classList.add('active');

    if (tab === 'realtime') {
        if (!_realtimeLoaded) loadRealtime();
    }
    if (tab === 'npattern') loadNPattern();
    if (tab === 'stats') loadStats();
    if (tab === 'sniper') loadSniper();
    if (tab === 'concept') {
        _conceptSearched = false;
        _hotConceptSortCol = '';
        _hotConceptSortDir = -1;
        // 恢复topConceptTable显示
        var tt = document.getElementById('topConceptTable');
        if (tt) tt.style.display = '';
        // 清空搜索结果
        var cr = document.getElementById('conceptResult');
        if (cr) cr.innerHTML = '<div class="empty">输入概念名称进行分析</div>';
        loadTopConcepts();
    }
    if (tab === 'alertmon') loadAlertMonitor();
    if (tab === 'kpltree') loadKplTree();
    if (tab === 'kplsearch') {
        var kplInput = document.getElementById('kplSearchInput2');
        if (kplInput && kplInput.value.trim()) {
            setTimeout(function() { kplInput.focus(); }, 100);
        }
    }
    if (tab === 'deepsearch') {
        // focus input if already has content
        var dsInput = document.getElementById('deepSearchInput');
        if (dsInput && dsInput.value.trim()) {
            setTimeout(function() { dsInput.focus(); }, 100);
        }
    }
    if (tab === 'linkage') loadLinkageDefaultSections();
    if (tab === 'specialwatch') loadSpecialWatch();
    if (tab !== 'etf' && _etfAutoRefreshActive) toggleEtfAutoRefresh();
    if (tab === 'etf') { _etfLoaded = false; loadEtfData(); }
}

// ===== 异动跟踪 =====

function loadAlertMonitor() {
    var container = document.getElementById('alertmonContainer');
    container.innerHTML = '<div class="loading">分析异动股票中...</div>';

    _cachedFetch('/api/abnormal_movement').then(function(data) {
        if (!data || !data.dates || data.dates.length === 0) {
            container.innerHTML = '<div class="result"><div class="error">暂无异动数据</div></div>';
            return;
        }

        var html = '<div class="result" id="am-nav-top">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;">';
        html += '<h3 style="color:#ff6b6b;margin:0;">\u26a0 \u5f02\u52a8\u8ddf\u8e2a</h3>';
        html += '<span style="color:#888;font-size:0.85em;">\u8fd120\u4ea4\u6613\u65e5\u6da8\u5e45>9% | \u6309\u6700\u540e\u5f02\u52a8\u65e5\u671f\u5206\u7ec4</span>';
        html += '</div>';

        // Sidebar + main content
        html += '<div class="np-wrapper">';
        html += '<nav class="np-sidebar" id="alertmonSidebar">';
        data.dates.forEach(function(date) {
            html += '<a class="np-sidebar-item" onclick="scrollToNpSection(\\x27am-section-' + date + '\\x27)">' + date + '</a>';
            _boardSubKeys.forEach(function(bk) {
                if (bk === 'other') return;
                html += '<a class="np-sidebar-subitem" onclick="scrollToNpSection(\\x27am-section-' + date + '-' + bk + '\\x27)">' + _boardSubLabels[bk] + '</a>';
            });
        });
        html += '</nav>';

        html += '<div class="np-main-content">';
        html += '<div id="am-cat-results">';

        // Render each date
        data.dates.forEach(function(date) {
            var stocks = data.data[date] || [];
            var boards = _npSplitByBoard(stocks);
            var hasAny = boards.main_board.length > 0 || boards.gem_star.length > 0;
            if (!hasAny) return;

            html += '<div class="np-section" id="am-section-' + date + '">';
            html += '<div class="np-cat-header" onclick="toggleNpCategory(this)">';
            html += '<span class="cat-icon">\U0001f4c5</span>';
            html += '<span class="cat-name">' + date + '</span>';
            html += '<span class="cat-count">' + stocks.length + '\u53ea</span>';
            html += '<span class="cat-arrow">\u25bc</span>';
            html += '</div>';
            html += '<div class="np-cat-body">';

            var boardDefs = [
                {key: 'main_board', label: '\u4e3b\u677f', cls: 'main'},
                {key: 'gem_star', label: '\u521b\u4e1a\u677f/\u79d1\u521b\u677f', cls: 'gem_star'}
            ];
            boardDefs.forEach(function(board) {
                var bStocks = boards[board.key] || [];
                if (bStocks.length === 0) return;
                var secId = 'am-section-' + date + '-' + board.key;

                html += '<div class="np-board-section">';
                html += '<div class="np-board-header collapsible ' + board.cls + '" onclick="toggleAlertmonBoard(this)" data-np-board="' + secId + '">';
                html += board.label + ' (' + bStocks.length + '\u53ea)';
                html += '<span class="board-arrow">\u25bc</span>';
                html += '</div>';
                html += '<div class="np-board-body collapsed" id="' + secId + '">';
                html += '<div class="np-card-grid">';

                // Render cards — same structure as N字战法
                bStocks.forEach(function(s) {
                    var code = s.code || (s.ts_code ? s.ts_code.split('.')[0] : '');
                    var name = s.name || '';
                    var concepts = s.concepts || [];
                    var alertDate = s.last_alert_date || '';
                    var alertPct = s.last_alert_pct || 0;

                    html += '<div class="np-card">';
                    html += '<div class="np-card-header">';
                    html += '<div>';
                    html += '<span class="np-card-code" data-code="' + code + '" data-name="' + name + '">' + code + '</span>';
                    html += '<span class="np-card-name">' + name + '</span>' + _watchStarHtml(code, name, _watchGetCategory(code));
                    html += '</div>';
                    html += '<div><span class="np-card-badge lianban">\u5f02\u52a8</span><button class="np-enlarge-btn" onclick="event.stopPropagation();showEnlargedCardDetail(\\x27' + code + '\\x27)" title="放大卡片">⛶</button></div>';
                    html += '</div>';
                    // Async detail loading (shared with N字战法 loadNpCardDetails)
                    html += '<div class="am-detail-placeholder" data-am-code="' + code + '" data-concepts=\\x27' + JSON.stringify(concepts) + '\\x27 data-alert-date="' + alertDate + '" data-alert-pct="' + alertPct + '"><div class="empty" style="padding:8px;">\u5c55\u5f00\u540e\u52a0\u8f7d\u8be6\u60c5</div></div>';
                    html += '</div>';
                });

                html += '</div></div></div>'; // card-grid, board-body, board-section
            });

            html += '<div class="np-back-top" onclick="scrollToNpSection(\\x27am-nav-top\\x27)">\u2191 \u56de\u5230\u9876\u90e8</div>';
            html += '</div></div>'; // cat-body, section
        });

        html += '</div></div></div>'; // cat-results, main-content, wrapper

        if (data.update_time) {
            html += '<div class="np-update-time">\u66f4\u65b0\u65f6\u95f4: ' + data.update_time + '</div>';
        }
        html += '</div>'; // result
        container.innerHTML = html;

        // Apply current column count
        document.querySelectorAll('.np-card-grid').forEach(function(g) {
            g.style.setProperty('--np-cols', _npGridCols);
        });

        // Collapse all date categories by default (lazy load)
        setTimeout(function() {
            document.querySelectorAll('#am-cat-results .np-cat-header').forEach(function(h) {
                if (!h.classList.contains('collapsed')) {
                    h.classList.add('collapsed');
                    var body = h.nextElementSibling;
                    if (body) body.style.display = 'none';
                }
            });
        }, 50);
    });
}

// ZT filter state
var _activeZtFilters = [];
var _currentQueryConcept = '';

// Concept autocomplete
var conceptNames = [];
fetch('/api/concepts').then(function(r) { return r.json(); }).then(function(names) {
    conceptNames = names || [];
});

// Close suggestions when clicking outside
document.addEventListener('click', function(e) {
    if (!e.target.closest('.input-item')) {
        var cs = document.getElementById('conceptSuggestions');
        if (cs) cs.classList.remove('active');
        var dss = document.getElementById('deepSearchSuggestions');
        if (dss) dss.classList.remove('active');
        var ls = document.getElementById('linkageSuggestions');
        if (ls) ls.classList.remove('active');
        var ks = document.getElementById('kplSuggestions');
        if (ks) ks.classList.remove('active');
        var sqs = document.getElementById('stockQuerySuggestions');
        if (sqs) sqs.classList.remove('active');
    }
});

document.getElementById('conceptQueryInput').addEventListener('input', function() {
    var q = this.value.trim().toLowerCase();
    var el = document.getElementById('conceptSuggestions');
    if (q.length < 1 || conceptNames.length === 0) {
        el.classList.remove('active');
        return;
    }
    var matches = conceptNames.filter(function(n) { return n.toLowerCase().indexOf(q) !== -1; }).slice(0, 12);
    if (matches.length === 0) { el.classList.remove('active'); return; }
    var html = '';
    matches.forEach(function(name) {
        html += '<div class="suggestion-item" data-suggest-concept="' + name + '">';
        html += '<span>' + name + '</span>';
        html += '</div>';
    });
    el.innerHTML = html;
    el.classList.add('active');
});
function selectStock(code, name) {
    doSearch(code, '');
}

// Global event delegation for stock rows, concept tabs, sortable headers, and show-all
document.addEventListener('click', function(e) {
    var showBtn = e.target.closest('[data-show-section]');
    if (showBtn) {
        var section = showBtn.getAttribute('data-show-section');
        if (section === 'linkage') {
            window._showAllLinkage = !(window._showAllLinkage);
        } else if (section === 'concept') {
            window._showAllConcept = !(window._showAllConcept);
        } else if (section === 'hot') {
            window._showAllHot = !(window._showAllHot);
        } else if (section === 'stats') {
            window._showAllStats = !(window._showAllStats);
        } else if (section === 'conceptLinkage') {
            window._showAllConceptLinkage = !(window._showAllConceptLinkage);
            if (window._conceptLinkagePairs) {
                renderConceptLinkageResult(window._currentStockName, window._conceptLinkagePairs);
            }
            return;
        }
        // Re-render current view
        if (currentTab === 'linkage') renderSortedLinkages();
        else if (currentTab === 'concept') doConceptSearch();
        else if (currentTab === 'hot') loadHotStocks();
        else if (currentTab === 'stats') loadStats();
        return;
    }
    var filterBtn = e.target.closest('[data-filter]');
    if (filterBtn) {
        var filter = filterBtn.getAttribute('data-filter');
        var idx = _activeZtFilters.indexOf(filter);
        if (idx === -1) {
            _activeZtFilters.push(filter);
        } else {
            _activeZtFilters.splice(idx, 1);
        }
        filterBtn.classList.toggle('active');
        // Re-query linkage with new filters
        if (window._currentStockCode) {
            var url = '/api/linkage?stock=' + encodeURIComponent(window._currentStockCode);
            if (_currentQueryConcept) {
                url += '&concept=' + encodeURIComponent(_currentQueryConcept);
            }
            url += '&min_prob=0.10';
            if (_activeZtFilters.length > 0) url += '&filters=' + _activeZtFilters.join(',');
            var container = document.getElementById('resultContainer');
            container.innerHTML = '<div class="loading">过滤中...</div>';
            fetch(url).then(r => r.json()).then(renderLinkageResult).catch(function(e) {
                container.innerHTML = '<div class="error">请求失败</div>';
            });
        }
        return;
    }
    var bucketBtn = e.target.closest('[data-bucket]');
    if (bucketBtn) {
        var bType = bucketBtn.getAttribute('data-bucket');
        var bKey = bucketBtn.getAttribute('data-bucket-key');
        // Highlight this button, un-highlight others in same bar
        var bar = bucketBtn.closest('.bucket-bar');
        if (bar) bar.querySelectorAll('.bucket-btn').forEach(function(b) { b.classList.remove('active'); });
        bucketBtn.classList.add('active');
        _currentBucketType = bType;
        _currentBucketKey = bKey;
        // Get current date params
        var sd = document.getElementById('statsStartDate') ? document.getElementById('statsStartDate').value : '';
        var ed = document.getElementById('statsEndDate') ? document.getElementById('statsEndDate').value : '';
        var params = [];
        if (sd) params.push('start_date=' + sd.replace(/-/g, ''));
        if (ed) params.push('end_date=' + ed.replace(/-/g, ''));
        var paramStr = params.length ? '&' + params.join('&') : '';
        loadBucketDetail(bType, bKey, paramStr);
        return;
    }
    var conceptTab = e.target.closest('[data-concept]');
    if (conceptTab) {
        var concept = conceptTab.getAttribute('data-concept');
        // top-concept-btn badges should navigate to concept tab and search
        if (conceptTab.classList.contains('top-concept-btn')) {
            switchTab('concept');
            document.getElementById('conceptQueryInput').value = concept;
            doConceptSearch();
        } else {
            selectConcept(concept);
        }
        return;
    }
    var conceptSuggest = e.target.closest('[data-suggest-concept]');
    if (conceptSuggest) {
        var conceptName = conceptSuggest.getAttribute('data-suggest-concept');
        document.getElementById('conceptQueryInput').value = conceptName;
        document.getElementById('conceptSuggestions').classList.remove('active');
        doConceptSearch();
        return;
    }
    var kplSuggest = e.target.closest('[data-suggest-kpl]');
    if (kplSuggest) {
        var kplVal = kplSuggest.getAttribute('data-suggest-kpl');
        document.getElementById('kplSearchInput').value = kplVal;
        document.getElementById('kplSuggestions').classList.remove('active');
        _kplDoSearch(kplVal);
        return;
    }
    // Oscillation toggle
    var oscBtn = e.target.closest('[data-osc-toggle]');
    if (oscBtn) {
        var secKey = oscBtn.getAttribute('data-osc-toggle');
        var extraGrid = document.getElementById('osc-grid-extra-' + secKey);
        var btn = document.getElementById('osc-btn-' + secKey);
        if (extraGrid && btn) {
            var isHidden = extraGrid.style.display === 'none';
            extraGrid.style.display = isHidden ? '' : 'none';
            var total = parseInt(btn.textContent.match(/\\d+/)) || 0;
            btn.textContent = isHidden ? '收起' : '显示全部 (' + total + '只)';
            if (isHidden) {
                _npDetailLoading = false;
                setTimeout(function() { loadNpCardDetails(); }, 100);
                initNpSidebar();
            }
        }
        return;
    }
    var header = e.target.closest('th[data-sort]');
    if (header) {
        var field = header.getAttribute('data-sort');
        toggleSort(field);
        return;
    }
    // Concept chip click → switch to concept tab and search
    var chip = e.target.closest('.concept-chip');
    if (chip) {
        var conceptName = chip.textContent.trim();
        if (conceptName) {
            switchTab('concept');
            document.getElementById('conceptQueryInput').value = conceptName;
            doConceptSearch();
            return;
        }
    }
    // 涨停理由标签点击 → 已由 searchLuTag 处理，阻止冒泡到 K线弹框
    var lc = e.target.closest('.lu-chip-clickable');
    if (lc) return;
    var el = e.target.closest('[data-code]');
    if (el) {
        var code = el.getAttribute('data-code');
        var name = el.getAttribute('data-name');
        if (code) {
            if (currentTab === 'realtime') {
                // 实时tab点击股票 → 显示详情卡片（涨停理由+3月统计+日K/分时图）
                showRealtimeCardDetail(code, name || code);
            } else {
                // 其余所有tab点击卡片→不弹框（仅各卡片上的放大/详情按钮有效）
                return;
            }
        }
        return;
    }
    var klineBtn = e.target.closest('[data-kline-id]');
    if (klineBtn) {
        var klineId = klineBtn.getAttribute('data-kline-id');
        toggleNpKline(klineId);
        return;
    }
});

// Linkage tab — stock autocomplete
var _linkageSuggestTimer = null;
document.getElementById('linkageStockInput').addEventListener('input', function() {
    var self = this;
    if (_linkageSuggestTimer) clearTimeout(_linkageSuggestTimer);
    _linkageSuggestTimer = setTimeout(function() {
        var q = self.value.trim();
        var el = document.getElementById('linkageSuggestions');
        if (q.length < 1) { el.classList.remove('active'); return; }
        fetch('/api/stock_search?q=' + encodeURIComponent(q))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.length === 0) { el.classList.remove('active'); return; }
                var html = '';
                data.forEach(function(s) {
                    html += '<div class="suggestion-item" onclick="doLinkageSearchWithVal(\\x27' + s.code + '\\x27)">';
                    html += '<span>' + s.code + ' ' + s.name + '</span>';
                    html += '</div>';
                });
                el.innerHTML = html;
                el.classList.add('active');
            })
            .catch(function() { el.classList.remove('active'); });
    }, 200);
});
function doLinkageSearchWithVal(val) {
    document.getElementById('linkageSuggestions').classList.remove('active');
    document.getElementById('linkageStockInput').value = val;
    doSearch(val, '');
}

// Linkage tab search — reads from linkageStockInput
function doLinkageSearch() {
    var input = document.getElementById('linkageStockInput');
    if (!input) return;
    var val = input.value.trim();
    if (!val) { alert('请输入股票代码或名称'); return; }
    doSearch(val, '');
}

// Main search — accepts optional stockVal and conceptVal params for progammatic calls
function doSearch(stockVal, conceptVal) {
    var raw = (stockVal || '').trim();
    var concept = (conceptVal || '').trim();
    if (!raw) {
        // Fallback to DOM input (legacy support for inline onclick without params)
        var si = document.getElementById('stockInput');
        if (si) raw = si.value.trim();
    }
    if (!concept && !conceptVal) {
        var ci = document.getElementById('conceptInput');
        if (ci) concept = ci.value.trim();
    }
    if (!raw) { alert('请输入股票代码、名称或概念名称'); return; }

    var codeMatch = raw.match(/(\\d{6})/);
    var isCode = codeMatch !== null;

    switchTab('linkage');

    var container = document.getElementById('resultContainer');
    container.innerHTML = '<div class="loading">查询中...</div>';

    if (!isCode) {
        // 非股票代码 → 按概念名称搜索
        _doConceptNameSearch(raw);
        return;
    }

    var stock = codeMatch[1];
    var url = '/api/linkage?stock=' + encodeURIComponent(stock);
    _currentQueryConcept = concept;
    if (concept) url += '&concept=' + encodeURIComponent(concept);
    url += '&min_prob=0.10';
    if (_activeZtFilters.length > 0) url += '&filters=' + _activeZtFilters.join(',');

    fetch(url).then(r => r.json()).then(renderLinkageResult).catch(function(e) {
        container.innerHTML = '<div class="error">请求失败</div>';
    });
}

function _doConceptNameSearch(conceptName) {
    var container = document.getElementById('resultContainer');
    fetch('/api/concept_linkage?concept=' + encodeURIComponent(conceptName) + '&top_n=100').then(function(r) {
        return r.json();
    }).then(function(data) {
        if (!data || !data.pairs || data.pairs.length === 0) {
            container.innerHTML = '<div class="result"><div class="empty">概念"' + conceptName + '"未找到联动数据</div></div>';
            return;
        }
        renderConceptLinkageResult(conceptName, data.pairs);
    }).catch(function(e) {
        container.innerHTML = '<div class="error">请求失败</div>';
    });
}

function renderConceptLinkageResult(conceptName, pairs) {
    var container = document.getElementById('resultContainer');
    // Store globally for potential sorting
    window._linkageData = null; // clear stock linkage data
    window._currentSubTags = [];
    window._currentStockCode = conceptName;
    window._currentStockName = conceptName;
    window._currentConcepts = [conceptName];
    window._conceptLinkagePairs = pairs;

    var totalPairs = pairs.length;
    var showAll = window._showAllConceptLinkage || false;
    var limit = showAll ? totalPairs : 30;
    var displayPairs = pairs.slice(0, limit);
    var hiddenCount = totalPairs - limit;

    var html = '<div class="result">';
    // 头部
    html += '<div class="stock-info">';
    html += '<span class="stock-name">' + conceptName + '</span>';
    html += '<span class="zt-count">共 <strong style="color:#ff6b6b">' + totalPairs + '</strong> 对联动组合</span>';
    html += '</div>';

    // 概念tag
    html += '<div style="margin-bottom: 10px;">';
    html += '<span class="tag">' + conceptName + '</span>';
    html += '</div>';

    // 联动对表格
    html += '<div class="section-header"><h3>概念联动组合</h3>';
    if (totalPairs > 30) {
        html += '<span class="show-all-btn" data-show-section="conceptLinkage">' + (showAll ? '收起' : '显示全部 (' + hiddenCount + '对)') + '</span>';
    }
    html += '<span style="font-weight:normal;font-size:0.85em;color:#888;margin-left:auto;">共' + totalPairs + '对</span></div>';

    html += '<table>';
    html += '<tr><th>#</th><th>代码A</th><th>名称A</th><th>\u2192</th><th>代码B</th><th>名称B</th><th>T+0</th><th>T+1</th><th>T+2</th><th>T+3</th><th>综合</th></tr>';

    displayPairs.forEach(function(p, i) {
        var t0 = (p.prob_t0 * 100).toFixed(0);
        var t1 = (p.lag1_prob * 100).toFixed(0);
        var t2 = (p.lag2_prob * 100).toFixed(0);
        var t3 = (p.lag3_prob * 100).toFixed(0);
        html += '<tr class="clickable" data-code="' + p.stock_a + '" data-name="' + p.name_a + '">';
        html += '<td style="color:#888;">' + (i + 1) + '</td>';
        html += '<td><strong>' + p.stock_a + '</strong></td><td>' + p.name_a + '</td>';
        html += '<td style="text-align:center;color:#00d4ff">\u2192</td>';
        html += '<td><strong>' + p.stock_b + '</strong></td><td>' + p.name_b + '</td>';
        html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t0" style="width:' + t0 + '%"></div></div><span>' + t0 + '%</span></div></td>';
        html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t1" style="width:' + t1 + '%"></div></div><span>' + t1 + '%</span></div></td>';
        html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t2" style="width:' + t2 + '%"></div></div><span>' + t2 + '%</span></div></td>';
        html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t3" style="width:' + t3 + '%"></div></div><span>' + t3 + '%</span></div></td>';
        html += '<td><strong style="color:#00ff88">' + (p.strength * 100).toFixed(0) + '%</strong></td></tr>';
    });
    html += '</table>';
    html += '</div>'; // .result
    container.innerHTML = html;
}

function renderLinkageResult(data) {
    var container = document.getElementById('resultContainer');
    if (data.error) { container.innerHTML = '<div class="error">' + data.error + '</div>'; return; }

    if (!data.linkages || data.linkages.length === 0) {
        var html = '<div class="result"><div class="stock-info">';
        html += '<span class="code-badge">' + data.stock_code + '</span>';
        html += '<span class="stock-name">' + (data.stock_name || data.stock_code) + '</span>';
        html += '<span class="zt-count">涨停 <strong style="color:#ff6b6b">' + (data.base_zt_count || 0) + '</strong> 次</span>';
        if (data.base_zt_dates && data.base_zt_dates.length > 0) {
            html += '<div style="margin-top:8px;">';
            data.base_zt_dates.forEach(function(d) { html += '<span class="zt-date-tag">' + d + '</span>'; });
            html += '</div>';
        }
        html += '</div><div class="empty">未找到联动股票（涨停次数需≥2）</div></div>';
        container.innerHTML = html;
        return;
    }

    // Store data globally for sorting
    window._linkageData = data.linkages || [];
    window._currentSortField = 'strength';
    window._currentSortOrder = 'desc';
    window._currentStockCode = data.stock_code;
    window._currentStockName = data.stock_name || data.stock_code;
    window._currentConcepts = data.concepts || [];
    window._currentBaseZtCount = data.base_zt_count || 0;
    window._currentDataSource = data.data_source;
    window._currentBaseZtDates = data.base_zt_dates || [];
    window._currentDirectionA = data.direction_a_to_b;
    window._currentSubTags = data.sub_tags || [];

    container.innerHTML = '<div class="loading">排序中...</div>';
    renderSortedLinkages();
}

function renderSortedLinkages() {
    var data = window._linkageData;
    if (!data || data.length === 0) return;

    var sortField = window._currentSortField || 'strength';
    var sortOrder = window._currentSortOrder || 'desc';

    // Build concept groups (deduplicated)
    var grouped = {};
    data.forEach(function(link) {
        var concepts = link.shared_concepts || [link.concept || '未知'];
        concepts.forEach(function(c) {
            if (!grouped[c]) grouped[c] = [];
            var exists = grouped[c].some(function(x) { return x.linked_stock === link.linked_stock; });
            if (!exists) grouped[c].push(link);
        });
    });
    var conceptNames = Object.keys(grouped);
    // If a concept was previously selected, validate it still exists
    var selectedConcept = window._selectedConcept;
    if (selectedConcept && selectedConcept !== '全部' && grouped[selectedConcept]) {
        // keep it
    } else {
        window._selectedConcept = '全部';
        selectedConcept = '全部';
    }

    var html = '<div class="result"><div class="stock-info">';
    html += '<span class="code-badge">' + window._currentStockCode + '</span>';
    html += '<span class="stock-name">' + window._currentStockName + '</span>';
    html += '<span class="zt-count">涨停 <strong style="color:#ff6b6b">' + (window._currentBaseZtCount || 0) + '</strong> 次</span>';
    if (window._currentDataSource) {
        html += '<span class="badge badge-pool">涨停池 ' + (window._currentDataSource.zt_pool_count || 0) + '次</span>';
        html += '<span class="badge badge-db">数据库 ' + (window._currentDataSource.db_count || 0) + '次</span>';
    }
    html += '</div>';

    // ZT dates
    if (window._currentBaseZtDates && window._currentBaseZtDates.length > 0) {
        html += '<div style="margin-bottom: 15px;"><span style="color: #888; font-size: 0.9em;">涨停日期: </span>';
        window._currentBaseZtDates.forEach(function(d) { html += '<span class="zt-date-tag">' + d + '</span>'; });
        html += '</div>';
    }

    // Concepts
    if (window._currentConcepts && window._currentConcepts.length > 0) {
        html += '<div style="margin-bottom: 10px;">';
        window._currentConcepts.forEach(function(c) { html += '<span class="tag">' + c + '</span>'; });
        html += '</div>';
    }

    // 子概念标签（从涨停理由提取）
    if (window._currentSubTags && window._currentSubTags.length > 0) {
        html += '<div style="margin: 6px 0 10px 0;">';
        html += '<span style="color:#888;font-size:0.85em;margin-right:6px;">涨停理由Tags: </span>';
        window._currentSubTags.forEach(function(tag) {
            html += '<span class="sub-tag" data-tag="' + tag + '">' + tag + '</span> ';
        });
        html += '</div>';
    }

    // 子概念过滤输入框
    html += '<div style="margin: 6px 0;display:flex;align-items:center;gap:8px;">';
    html += '<span style="color:#888;font-size:0.85em;">Tag过滤:</span>';
    html += '<input type="text" id="subTagFilter" placeholder="输入Tag文本过滤（不区分大小写）" style="flex:1;max-width:300px;padding:4px 8px;background:#0d1b36;border:1px solid #1a3a5c;border-radius:4px;color:#ccc;font-size:0.85em;">';
    html += '</div>';

    // ZT filter bar (always show)
    var filterLabels = { 'n15': 'N15 近15日涨停', 'n15f': 'N15F 首板', 'n10zb': 'N10ZB 炸板', 'n10zbf': 'N10ZBF 新炸板' };
    html += '<div class="zt-filter-bar">';
    html += '<span class="zt-filter-label">涨停过滤:</span>';
    Object.keys(filterLabels).forEach(function(key) {
        var active = _activeZtFilters.indexOf(key) !== -1 ? ' active' : '';
        html += '<button class="zt-filter-btn' + active + '" data-filter="' + key + '">' + filterLabels[key] + '</button>';
    });
    if (_activeZtFilters.length > 0) {
        html += '<span style="color:#ff6b6b;font-size:0.85em;margin-left:8px;">已过滤: ' + data.length + '只</span>';
    }
    html += '</div>';

    if (!data || data.length === 0) {
        html += '<div class="empty">未找到联动股票（涨停次数需≥2）</div></div>';
        document.getElementById('resultContainer').innerHTML = html;
        return;
    }

    // Directionality summary
    if (window._currentDirectionA) {
        html += '<div style="margin-bottom: 12px; display: flex; gap: 15px; flex-wrap: wrap;">';
        html += '<span class="badge badge-pool">A\u2192B 联动股票: ' + window._currentDirectionA.total_linked_stocks + '只</span>';
        html += '<span class="badge badge-db">强联动(\u226530%): ' + window._currentDirectionA.strong_linkages + '只</span>';
        html += '</div>';
    }

    // Concept tabs
    var sortedNames = conceptNames.slice().sort(function(a, b) { return grouped[b].length - grouped[a].length; });
    html += '<div class="concept-tabs">';
    var allActive = selectedConcept === '全部' ? ' active' : '';
    html += '<span class="concept-tab' + allActive + '" data-concept="全部">全部 (' + data.length + ')</span>';
    sortedNames.forEach(function(c) {
        var active = selectedConcept === c ? ' active' : '';
        html += '<span class="concept-tab' + active + '" data-concept="' + c + '">' + c + ' (' + grouped[c].length + ')</span>';
    });
    html += '</div>';

    // Sort arrow helper
    function sortArrow(field) {
        if (sortField !== field) return '';
        return sortOrder === 'desc' ? ' \u25BC' : ' \u25B2';
    }

    // Render tables
    var conceptsToShow = selectedConcept === '全部' ? sortedNames : [selectedConcept];
    conceptsToShow.forEach(function(concept) {
        var links = grouped[concept];
        // Sort within this concept
        var sorted = links.slice().sort(function(a, b) {
            var va = a[sortField] !== undefined ? a[sortField] : 0;
            var vb = b[sortField] !== undefined ? b[sortField] : 0;
            return sortOrder === 'desc' ? vb - va : va - vb;
        });
        var showAll = window._showAllLinkage || false;
        var limit = showAll ? sorted.length : 15;
        var topData = sorted.slice(0, limit);
        var hiddenCount = sorted.length - limit;

        html += '<div class="concept-section">';
        html += '<div class="section-header">';
        html += '<h4>' + concept + ' (' + sorted.length + '只)</h4>';
        if (sorted.length > 15) {
            var btnText = showAll ? '收起' : '显示全部';
            html += '<span class="show-all-btn" data-show-section="linkage">' + btnText + '</span>';
        }
        html += '</div>';
        html += '<table>';
        html += '<tr><th>#</th><th>代码</th><th>名称</th>';
        html += '<th data-sort="prob_t0" class="sortable">T+0' + sortArrow('prob_t0') + '</th>';
        html += '<th data-sort="prob_t1" class="sortable">T+1' + sortArrow('prob_t1') + '</th>';
        html += '<th data-sort="prob_t2" class="sortable">T+2' + sortArrow('prob_t2') + '</th>';
        html += '<th data-sort="prob_t3" class="sortable">T+3' + sortArrow('prob_t3') + '</th>';
        html += '<th data-sort="strength" class="sortable">综合' + sortArrow('strength') + '</th>';
        html += '<th>联动次数</th><th>自身ZT</th></tr>';

        topData.forEach(function(link, idx) {
            var l0 = (link.prob_t0 * 100).toFixed(0);
            var l1 = (link.prob_t1 * 100).toFixed(0);
            var l2 = (link.prob_t2 * 100).toFixed(0);
            var l3 = (link.prob_t3 * 100).toFixed(0);
            var sp = (link.strength * 100).toFixed(0);
            var events = link.linkage_events || [];

            html += '<tr class="clickable" data-code="' + link.linked_stock + '" data-name="' + link.linked_name + '">';
            html += '<td style="color:#888;">' + (idx + 1) + '</td>';
            html += '<td><strong>' + link.linked_stock + '</strong></td><td>' + link.linked_name + '</td>';
            html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t0" style="width:' + l0 + '%"></div></div><span>' + l0 + '%</span></div></td>';
            html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t1" style="width:' + l1 + '%"></div></div><span>' + l1 + '%</span></div></td>';
            html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t2" style="width:' + l2 + '%"></div></div><span>' + l2 + '%</span></div></td>';
            html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t3" style="width:' + l3 + '%"></div></div><span>' + l3 + '%</span></div></td>';
            html += '<td><strong style="color:#00ff88">' + sp + '%</strong></td>';
            html += '<td>' + events.length + '</td><td>' + (link.linked_zt_count || 0) + '</td>';
            html += '</tr>';

            // Event details row
            if (events.length > 0) {
                var stockName = window._currentStockName || 'A';
                var linkedName = link.linked_name || 'B';
                html += '<tr class="event-row"><td colspan="11">';
                // Direction & reverse probability
                html += '<div class="event-header">';
                html += '<span class="dir-label">方向:</span> ';
                html += '<span class="stock-a">' + stockName + '</span>';
                html += '<span style="color:#888;margin:0 4px;">\u2192</span>';
                html += '<span class="stock-b">' + linkedName + '</span>';
                html += '<span class="dir-sep">|</span>';
                html += '<span class="dir-item">正向(A涨\u2192B涨): <b style="color:#00d4ff">' + sp + '%</b></span>';
                if (link.reverse_strength !== undefined) {
                    var revStr = (link.reverse_strength * 100).toFixed(0);
                    html += '<span class="dir-sep">|</span>';
                    html += '<span class="dir-item">反向(B涨\u2192A涨): <b style="color:#ffc107">' + revStr + '%</b></span>';
                }
                html += '</div>';

                // Event timeline
                html += '<div class="event-timeline">';
                html += '<span style="color:#888;margin-right:6px;">联动记录:</span>';
                events.slice(-5).forEach(function(evt) {
                    var lagLabel = evt.lag > 0 ? 'T+' + evt.lag : 'T+0';
                    var baseShort = evt.base_date.slice(2);
                    var linkedShort = evt.linked_date.slice(2);
                    html += '<span class="event-tag">';
                    html += '<span class="evt-a">' + baseShort + '</span>';
                    html += '<span class="evt-arrow">\u2192</span>';
                    html += '<span class="evt-b">' + linkedShort + '</span>';
                    html += '<span class="evt-lag">' + lagLabel + '</span>';
                    html += '</span> ';
                });
                if (events.length > 5) html += '<span style="color:#666;font-size:0.85em;">...等' + events.length + '次</span>';
                html += '</div>';
                html += '</td></tr>';
            }
        });
        html += '</table></div>';
    });

    // Gem/Star arbitrage button at bottom (only for main board stocks)
    var sc = window._currentStockCode || '';
    if (!sc.startsWith('3') && !sc.startsWith('688') && !sc.startsWith('4') && !sc.startsWith('8') && sc.length === 6) {
        html += '<div style="margin-top: 16px; border-top: 1px solid rgba(255,152,0,0.3); padding-top: 12px;">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
        html += '<button class="arb-btn" onclick="loadGemArbitrage(&#39;' + sc + '&#39;)">\u7B5B\u67E5\u521B\u4E1A\u677F/\u79D1\u521B\u677F\u5957\u5229\u673A\u4F1A</button>';
        html += '<span style="color:#888;font-size:0.85em;">\u540C\u6982\u5FF5\u4E0B\u521B\u4E1A\u677F/\u79D1\u521B\u677F >10% \u6DA8\u5E45\u8054\u52A8</span>';
        html += '</div>';
        html += '<div id="gemArbitrageContainer"></div>';
        html += '</div>';
    }

    html += '</div>';
    document.getElementById('resultContainer').innerHTML = html;

    // 子概念过滤逻辑
    setTimeout(function() {
        var filterInput = document.getElementById('subTagFilter');
        if (filterInput) {
            filterInput.addEventListener('input', function() {
                var q = this.value.trim().toLowerCase();
                document.querySelectorAll('#resultContainer .concept-section table tr.clickable').forEach(function(row) {
                    if (!q) { row.style.display = ''; return; }
                    var name = (row.getAttribute('data-name') || '').toLowerCase();
                    var code = (row.getAttribute('data-code') || '');
                    var match = name.indexOf(q) !== -1 || code.indexOf(q) !== -1;
                    row.style.display = match ? '' : 'none';
                });
                // 也隐藏对应的 event-detail row
                document.querySelectorAll('#resultContainer .concept-section table tr.event-row').forEach(function(row) {
                    var prevRow = row.previousElementSibling;
                    if (prevRow && prevRow.style.display === 'none') {
                        row.style.display = 'none';
                    } else if (prevRow && prevRow.style.display !== 'none') {
                        row.style.display = '';
                    }
                });
            });
        }
        // 子概念标签点击 → 填入过滤框
        document.querySelectorAll('.sub-tag').forEach(function(el) {
            el.addEventListener('click', function() {
                var tagText = this.getAttribute('data-tag');
                var fi = document.getElementById('subTagFilter');
                if (fi) {
                    fi.value = tagText;
                    fi.dispatchEvent(new Event('input'));
                }
            });
        });
    }, 100);
}

function toggleSort(field) {
    if (window._currentSortField === field) {
        window._currentSortOrder = window._currentSortOrder === 'desc' ? 'asc' : 'desc';
    } else {
        window._currentSortField = field;
        window._currentSortOrder = 'desc';
    }
    renderSortedLinkages();
}

function selectConcept(concept) {
    window._selectedConcept = concept;
    renderSortedLinkages();
}

// Concept analysis
var _conceptSearched = false;

function doConceptSearch() {
    var q = document.getElementById('conceptQueryInput').value.trim();
    if (!q) { alert('请输入概念（细分）名称'); return; }

    var useThs = document.getElementById('conceptSourceThs').checked;
    var useReason = document.getElementById('conceptSourceReason').checked;
    if (!useThs && !useReason) { alert('请至少选择一个搜索来源'); return; }

    _conceptSearched = true;
    var container = document.getElementById('conceptResult');
    container.innerHTML = '<div class="loading">分析中...</div>';

    // 默认3个月日期
    var now = new Date();
    var de = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0');
    var s = new Date(now); s.setMonth(s.getMonth()-3);
    var ds = s.getFullYear() + '-' + String(s.getMonth()+1).padStart(2,'0') + '-' + String(s.getDate()).padStart(2,'0');

    Promise.all([
        useReason ? fetch('/api/reason_search?q=' + encodeURIComponent(q) + '&date_start=' + ds + '&date_end=' + de).then(function(r){return r.json();}) : Promise.resolve(null),
        useThs ? fetch('/api/concept_zt_stats?concept=' + encodeURIComponent(q)).then(function(r){return r.json().catch(function(){return null;});}) : Promise.resolve(null),
        useThs ? fetch('/api/concept_linkage?concept=' + encodeURIComponent(q) + '&top_n=50').then(function(r){return r.json().catch(function(){return null;});}) : Promise.resolve(null)
    ]).then(function(results) {
        var reasonData = results[0];
        var stats = results[1];
        var linkage = results[2];

        var hasReason = useReason && reasonData && reasonData.total_hits > 0;
        var hasConcept = useThs && stats && stats.total_stocks > 0;

        if (!hasReason && !hasConcept) {
            container.innerHTML = '<div class="result"><div class="empty">未匹配到结果</div></div>';
            return;
        }

        var html = '<div class="result">';
        // 头部
        html += '<div class="stock-info">';
        html += '<span class="stock-name">' + q + '</span>';
        if (hasReason) {
            html += '<span class="zt-count">涨停理由匹配 <strong style="color:#ff6b6b">' + reasonData.total_hits + '</strong> 次</span>';
        }
        if (hasConcept) {
            html += '<span class="zt-count">成分股 <strong>' + stats.total_stocks + '</strong>只, 有涨停 <strong style="color:#ff6b6b">' + stats.zt_stock_count + '</strong>只</span>';
        }
        if (hasReason) {
            html += '<span style="color:#888;font-size:0.85em;">' + ds + ' ~ ' + de + '</span>';
        }
        html += '</div>';

        // 概念峰值涨停日（仅THS来源）
        if (useThs) {
            html += '<div class="section-header"><h3>峰值涨停日</h3></div>';
            if (hasConcept && stats.peak_dates && stats.peak_dates.length > 0) {
                html += '<div style="margin-bottom: 15px;">';
                html += '<div class="peak-list" style="display:inline-flex;">';
                stats.peak_dates.slice(0, 6).forEach(function(p) {
                    html += '<span class="peak-item"><span class="peak-date">' + p.date + '</span> <span class="peak-count">' + p.count + '股</span></span>';
                });
                html += '</div></div>';
            } else {
                html += '<div style="color:#484f58;font-size:0.85em;margin-bottom:15px;padding:8px 0;">暂无峰值数据</div>';
            }
        }

        // 涨停节奏网格
        html += '<div class="rhythm-section">';
        html += '<div class="rhythm-title">涨停节奏</div>';
        if (hasConcept && stats.daily_rhythm && stats.daily_rhythm.length > 0) {
            html += '<div class="rhythm-grid">';
            stats.daily_rhythm.slice().reverse().forEach(function(day) {
                html += '<div class="rhythm-date">';
                html += '<div class="rhythm-header">' + day.display_date + '</div>';
                html += '<div class="rhythm-content">';
                if (day.stocks && day.stocks.length > 0) {
                    day.stocks.forEach(function(stk) {
                        var blockClass = stk.is_limit_up ? ('lb-' + Math.min(stk.lianban, 3)) : 'lb-0';
                        var labelHtml;
                        if (stk.is_limit_up) {
                            var lbLabel = stk.lianban === 1 ? '首板' : (stk.lianban >= 3 ? '3板+' : stk.lianban + '板');
                            labelHtml = '<span class="lb-tag">' + lbLabel + '<span class="board-inline">' + stk.board + '</span></span>';
                        } else {
                            var pctStr = (stk.change_pct > 0 ? '+' : '') + stk.change_pct + '%';
                            labelHtml = '<span class="pct-tag">' + pctStr + '</span>';
                        }
                        html += '<div class="rhythm-item" data-stock="' + stk.name + '">';
                        html += '<div class="stock-block ' + blockClass + '" data-code="' + stk.code + '">';
                        html += '<span class="name">' + stk.name + '</span>';
                        html += labelHtml;
                        html += '</div>';
                        html += '</div>';
                    });
                } else {
                    html += '<div style="color:#484f58;font-size:0.75em;padding:6px 4px;text-align:center;">-</div>';
                }
                html += '</div>';
                html += '</div>';
            });
            html += '</div>';
            html += '<div class="legend">';
            html += '<div class="item"><span class="dot lb-1"></span>首板</div>';
            html += '<div class="item"><span class="dot lb-2"></span>2板</div>';
            html += '<div class="item"><span class="dot lb-3"></span>3板+</div>';
            html += '<div class="item"><span class="dot lb-0"></span>大涨≥10%</div>';
            html += '</div>';
            setTimeout(function() {
                var grid = document.querySelector('.rhythm-grid');
                if (!grid) return;
                grid.querySelectorAll('.rhythm-item').forEach(function(item) {
                    item.addEventListener('mouseenter', function() {
                        var stockName = this.getAttribute('data-stock');
                        if (!stockName) return;
                        grid.querySelectorAll('.rhythm-item').forEach(function(other) {
                            var blocks = other.querySelectorAll('.stock-block');
                            if (other.getAttribute('data-stock') === stockName) {
                                blocks.forEach(function(b) { b.classList.add('highlighted'); });
                            } else {
                                blocks.forEach(function(b) { b.classList.remove('highlighted'); });
                            }
                        });
                    });
                    item.addEventListener('mouseleave', function() {
                        grid.querySelectorAll('.rhythm-item .stock-block').forEach(function(b) {
                            b.classList.remove('highlighted');
                        });
                    });
                    var block = item.querySelector('.stock-block');
                    if (block) {
                        block.addEventListener('click', function(e) {
                            e.stopPropagation();
                            var stockName = item.getAttribute('data-stock');
                            var stockCode = this.getAttribute('data-code');
                            if (stockName && stockCode) {
                                deepSearchShowStock(stockName, stockCode, q);
                            }
                        });
                    }
                });
            }, 50);
        } else if (hasReason && reasonData.results && reasonData.results.length > 0) {
            // 从涨停理由数据构建涨停节奏（非THS概念的关键词搜索）
            html += '<div class="rhythm-grid">';
            var dateGroups = {};
            reasonData.results.forEach(function(r) {
                var d = r.trade_date;
                if (!dateGroups[d]) dateGroups[d] = [];
                dateGroups[d].push(r);
            });
            var sortedDates = Object.keys(dateGroups).sort().reverse();
            sortedDates.forEach(function(dateStr) {
                var stocks = dateGroups[dateStr];
                var displayDate = String(dateStr).slice(2);
                html += '<div class="rhythm-date">';
                html += '<div class="rhythm-header">' + displayDate + '</div>';
                html += '<div class="rhythm-content">';
                stocks.forEach(function(stk) {
                    var tag = stk.tag || '首板';
                    var lianban = 1;
                    var m = tag.match(/天(\d+)板/);
                    if (m) lianban = parseInt(m[1]);
                    var blockClass = 'lb-' + Math.min(lianban, 3);
                    var tsCode = stk.ts_code || '';
                    var board = '主';
                    if (tsCode.endsWith('.SZ')) board = '主';
                    else if (tsCode.endsWith('.BJ')) board = '科';
                    var lbLabel = lianban === 1 ? '首板' : (lianban >= 3 ? '3板+' : lianban + '板');
                    var labelHtml = '<span class="lb-tag">' + lbLabel + '<span class="board-inline">' + board + '</span></span>';
                    html += '<div class="rhythm-item" data-stock="' + stk.name + '">';
                    var codeClean = tsCode.replace(/\.(SH|SZ|BJ)$/, '');
                    html += '<div class="stock-block ' + blockClass + '" data-code="' + codeClean + '">';
                    html += '<span class="name">' + stk.name + '</span>';
                    html += labelHtml;
                    html += '</div></div>';
                });
                html += '</div></div>';
            });
            html += '</div>';
            html += '<div class="legend">';
            html += '<div class="item"><span class="dot lb-1"></span>首板</div>';
            html += '<div class="item"><span class="dot lb-2"></span>2板</div>';
            html += '<div class="item"><span class="dot lb-3"></span>3板+</div>';
            html += '</div>';
            // 跨日期高亮
            setTimeout(function() {
                var grid = document.querySelector('.rhythm-grid');
                if (!grid) return;
                grid.querySelectorAll('.rhythm-item').forEach(function(item) {
                    item.addEventListener('mouseenter', function() {
                        var stockName = this.getAttribute('data-stock');
                        if (!stockName) return;
                        grid.querySelectorAll('.rhythm-item').forEach(function(other) {
                            var blocks = other.querySelectorAll('.stock-block');
                            if (other.getAttribute('data-stock') === stockName) {
                                blocks.forEach(function(b) { b.classList.add('highlighted'); });
                            } else {
                                blocks.forEach(function(b) { b.classList.remove('highlighted'); });
                            }
                        });
                    });
                    item.addEventListener('mouseleave', function() {
                        grid.querySelectorAll('.rhythm-item .stock-block').forEach(function(b) {
                            b.classList.remove('highlighted');
                        });
                    });
                    var block = item.querySelector('.stock-block');
                    if (block) {
                        block.addEventListener('click', function(e) {
                            e.stopPropagation();
                            var stockName = item.getAttribute('data-stock');
                            var stockCode = this.getAttribute('data-code');
                            if (stockName && stockCode) {
                                deepSearchShowStock(stockName, stockCode);
                            }
                        });
                    }
                });
            }, 50);
        } else {
            html += '<div style="color:#484f58;font-size:0.85em;padding:12px 0;text-align:center;">暂无涨停节奏数据</div>';
        }
        html += '</div>';

        // 涨停理由匹配的股票列表（仅涨停理由来源）
        if (useReason) {
            html += '<div class="section-header"><h3>涨停理由相关股票</h3></div>';
            if (hasReason && reasonData.stock_freq && reasonData.stock_freq.length > 0) {
            html += '<table><tr><th>#</th><th>名称</th><th>涨停次数</th><th>最高连板</th><th>最近涨停</th></tr>';
            reasonData.stock_freq.forEach(function(s, i) {
                html += '<tr><td>' + (i+1) + '</td>';
                html += '<td><span class="ds-name-link" onclick="deepSearchShowStock(\\x27' + s.name.replace(/'/g,'') + '\\x27, \\x27' + s.code + '\\x27, \\x27' + (q||'').replace(/'/g,'') + '\\x27)">' + s.name + '</span></td>';
                html += '<td style="color:#ff6b6b;font-weight:bold;">' + s.count + '</td>';
                html += '<td>' + (s.max_chain > 0 ? '<span class="chain-badge chain-' + Math.min(s.max_chain,4) + '">' + s.max_chain + '板</span>' : '-') + '</td>';
                html += '<td>' + (s.last_date || '-') + '</td></tr>';
            });
            html += '</table>';
        } else {
            html += '<div style="color:#484f58;font-size:0.85em;padding:8px 0;">暂无涨停理由匹配数据</div>';
        }
        }

        // 联动对（优先使用概念联动，否则从涨停理由数据构建）
        if (hasConcept && linkage && linkage.pairs && linkage.pairs.length > 0) {
            var showAllConcept = window._showAllConcept || false;
            var pairLimit = showAllConcept ? linkage.pairs.length : 15;
            html += '<div class="section-header"><h3>最强联动对</h3>';
            if (linkage.pairs.length > 15) {
                html += '<span class="show-all-btn" data-show-section="concept">' + (showAllConcept ? '收起' : '显示全部') + '</span>';
            }
            html += '<span style="font-weight:normal;font-size:0.85em;color:#888;margin-left:auto;">共' + linkage.pairs.length + '对</span></div>';
            html += '<table><tr><th>股票A</th><th>名称A</th><th>→</th><th>股票B</th><th>名称B</th><th>T+0</th><th>T+1</th><th>T+2</th><th>T+3</th><th>综合</th></tr>';
            linkage.pairs.slice(0, pairLimit).forEach(function(p) {
                var t0 = (p.prob_t0 * 100).toFixed(0);
                var t1 = (p.lag1_prob * 100).toFixed(0);
                var t2 = (p.lag2_prob * 100).toFixed(0);
                var t3 = (p.lag3_prob * 100).toFixed(0);
                html += '<tr class="clickable" data-code="' + p.stock_a + '" data-name="' + p.name_a + '">';
                html += '<td><strong>' + p.stock_a + '</strong></td><td>' + p.name_a + '</td>';
                html += '<td style="text-align:center;color:#00d4ff">→</td>';
                html += '<td><strong>' + p.stock_b + '</strong></td><td>' + p.name_b + '</td>';
                html += '<td>' + t0 + '%</td>';
                html += '<td>' + t1 + '%</td>';
                html += '<td>' + t2 + '%</td>';
                html += '<td>' + t3 + '%</td>';
                html += '<td><strong style="color:#00ff88">' + (p.strength * 100).toFixed(0) + '%</strong></td></tr>';
            });
            html += '</table>';
        } else if (hasReason && reasonData.results && reasonData.results.length > 1) {
            // 从涨停理由数据构建联动对
            var byDate = {};
            var stockSet = {};
            reasonData.results.forEach(function(r) {
                var d = r.trade_date;
                if (!byDate[d]) byDate[d] = [];
                var code = (r.ts_code || '').replace(/\.(SH|SZ|BJ)$/, '');
                byDate[d].push({code: code, name: r.name});
                stockSet[code] = r.name;
            });
            var dates = Object.keys(byDate).sort();
            var stockList = Object.keys(stockSet);

            // 初始化所有股票对
            var pairMap = {};
            for (var i = 0; i < stockList.length; i++) {
                for (var j = i + 1; j < stockList.length; j++) {
                    var key = stockList[i] < stockList[j] ? stockList[i] + '_' + stockList[j] : stockList[j] + '_' + stockList[i];
                    pairMap[key] = {stock_a: stockList[i], name_a: stockSet[stockList[i]], stock_b: stockList[j], name_b: stockSet[stockList[j]], sameDay: 0, lag1: 0, lag2: 0, lag3: 0};
                }
            }

            // 统计每个股票的出现次数
            var stockCnt = {};
            stockList.forEach(function(c) { stockCnt[c] = 0; });
            dates.forEach(function(d) {
                var seen = {};
                byDate[d].forEach(function(s) {
                    if (!seen[s.code]) { seen[s.code] = true; stockCnt[s.code]++; }
                });
            });

            // 计算共现
            dates.forEach(function(d, idx) {
                var codes = [];
                var seen = {};
                byDate[d].forEach(function(s) {
                    if (!seen[s.code]) { seen[s.code] = true; codes.push(s.code); }
                });

                // 同日共现
                for (var i = 0; i < codes.length; i++) {
                    for (var j = i + 1; j < codes.length; j++) {
                        var key = codes[i] < codes[j] ? codes[i] + '_' + codes[j] : codes[j] + '_' + codes[i];
                        if (pairMap[key]) pairMap[key].sameDay++;
                    }
                }
                // T+1, T+2, T+3
                for (var lag = 1; lag <= 3; lag++) {
                    if (idx + lag < dates.length) {
                        var laterSeen = {};
                        var laterCodes = [];
                        byDate[dates[idx + lag]].forEach(function(s) {
                            if (!laterSeen[s.code]) { laterSeen[s.code] = true; laterCodes.push(s.code); }
                        });
                        for (var i = 0; i < codes.length; i++) {
                            for (var j = 0; j < laterCodes.length; j++) {
                                if (codes[i] === laterCodes[j]) continue;
                                var key = codes[i] < laterCodes[j] ? codes[i] + '_' + laterCodes[j] : laterCodes[j] + '_' + codes[i];
                                if (pairMap[key]) {
                                    if (lag === 1) pairMap[key].lag1++;
                                    else if (lag === 2) pairMap[key].lag2++;
                                    else if (lag === 3) pairMap[key].lag3++;
                                }
                            }
                        }
                    }
                }
            });

            // 构建结果
            var pairs = [];
            Object.keys(pairMap).forEach(function(key) {
                var p = pairMap[key];
                var totalA = stockCnt[p.stock_a] || 1;
                var totalB = stockCnt[p.stock_b] || 1;
                p.prob_t0 = p.sameDay / Math.min(totalA, totalB);
                p.lag1_prob = p.lag1 / totalA;
                p.lag2_prob = p.lag2 / totalA;
                p.lag3_prob = p.lag3 / totalA;
                p.strength = p.prob_t0 * 0.4 + p.lag1_prob * 0.3 + p.lag2_prob * 0.2 + p.lag3_prob * 0.1;
                if (p.sameDay > 0 || p.lag1 > 0) pairs.push(p);
            });
            pairs.sort(function(a, b) { return b.strength - a.strength; });
            var topPairs = pairs.slice(0, 30);

            html += '<div class="section-header"><h3>最强联动对</h3>';
            html += '<span style="font-weight:normal;font-size:0.85em;color:#888;margin-left:auto;">共' + topPairs.length + '对</span></div>';
            html += '<table><tr><th>股票A</th><th>名称A</th><th>→</th><th>股票B</th><th>名称B</th><th>T+0</th><th>T+1</th><th>T+2</th><th>T+3</th><th>综合</th></tr>';
            topPairs.forEach(function(p) {
                var t0 = Math.round(p.prob_t0 * 100);
                var t1 = Math.round(p.lag1_prob * 100);
                var t2 = Math.round(p.lag2_prob * 100);
                var t3 = Math.round(p.lag3_prob * 100);
                html += '<tr class="clickable" data-code="' + p.stock_a + '" data-name="' + p.name_a + '">';
                html += '<td><strong>' + p.stock_a + '</strong></td><td>' + p.name_a + '</td>';
                html += '<td style="text-align:center;color:#00d4ff">→</td>';
                html += '<td><strong>' + p.stock_b + '</strong></td><td>' + p.name_b + '</td>';
                html += '<td>' + t0 + '%</td>';
                html += '<td>' + t1 + '%</td>';
                html += '<td>' + t2 + '%</td>';
                html += '<td>' + t3 + '%</td>';
                html += '<td><strong style="color:#00ff88">' + Math.round(p.strength * 100) + '%</strong></td></tr>';
            });
            html += '</table>';
        } else {
            html += '<div class="section-header"><h3>最强联动对</h3><span style="font-weight:normal;font-size:0.85em;color:#555;margin-left:auto;">无数据</span></div>';
            html += '<div style="color:#484f58;font-size:0.85em;padding:8px 0;">暂无联动对数据</div>';
        }

        // 相关概念关键词（仅涨停理由来源）
        if (useReason) {
            html += '<div class="section-header"><h3>相关概念关键词</h3></div>';
            if (hasReason && reasonData.concept_freq && reasonData.concept_freq.length > 0) {
                html += '<div class="freq-chips">';
                reasonData.concept_freq.slice(0, 15).forEach(function(c) {
                    html += '<span class="freq-chip" onclick="document.getElementById(\\x27conceptQueryInput\\x27).value=\\x27' + c.concept.replace(/'/g,'') + '\\x27;doConceptSearch();">' + c.concept + ' <span class="count">' + c.count + '</span></span>';
                });
                html += '</div>';
            } else {
                html += '<div style="color:#484f58;font-size:0.85em;padding:8px 0;">暂无关键词数据</div>';
            }
        }

        html += '</div>';
        container.innerHTML = html;

        // 搜索时隐藏上方的Top20独立表格，只在结果下方显示
        var topTable = document.getElementById('topConceptTable');
        if (topTable) topTable.style.display = 'none';
        // 搜索后始终在结果下方显示Top20热门概念板块
        if (_hotConceptsData && _hotConceptsData.length > 0) {
            var topHtml = '<div class="result top20-section" style="margin-top:20px;border-top:1px solid #0f3460;padding-top:15px;">';
            topHtml += '<div style="margin-bottom:8px;color:#888;font-size:0.85em;">📈 同花顺热门概念板块 Top20</div>';
            topHtml += renderHotConceptTable(_hotConceptsData);
            topHtml += '</div>';
            container.innerHTML += topHtml;
        }
    });
}

// Hot stocks
// Stats page
var statsCharts = [];
var _currentBucketType = '';
var _currentBucketKey = '';

function loadStats() {
    var container = document.getElementById('statsContainer');
    container.innerHTML = '<div class="loading">加载统计中...</div>';

    // Destroy previous charts
    statsCharts.forEach(function(c) { if (c) c.destroy(); });
    statsCharts = [];

    // Read date filter values from UI
    var sd = document.getElementById('statsStartDate') ? document.getElementById('statsStartDate').value : '';
    var ed = document.getElementById('statsEndDate') ? document.getElementById('statsEndDate').value : '';
    // Default: last 90 days on first load
    if (!sd && !document.getElementById('statsStartDate')) {
        var d = new Date();
        d.setDate(d.getDate() - 90);
        sd = d.toISOString().slice(0, 10);
    }
    var params = [];
    if (sd) params.push('start_date=' + sd.replace(/-/g, ''));
    if (ed) params.push('end_date=' + ed.replace(/-/g, ''));
    var paramStr = params.length ? '?' + params.join('&') : '';
    var bucketParamStr = params.length ? '&' + params.join('&') : '';
    var statsUrl = '/api/stats' + paramStr;

    var fetchFn = paramStr ? function(u) { return fetch(u).then(function(r) { return r.json(); }); } : _cachedFetch;
    fetchFn(statsUrl).then(function(data) {
        if (!data || data.error) {
            container.innerHTML = '<div class="error">统计数据加载失败</div>';
            return;
        }

        var html = '<div class="result">';

        // ---- Date filter bar ----
        var defaultStart = sd || '';
        if (!defaultStart) {
            var d = new Date();
            d.setDate(d.getDate() - 90);
            defaultStart = d.toISOString().slice(0, 10);
        }
        var defaultEnd = ed || data.summary.date_range.end || '';
        if (defaultStart && defaultStart.indexOf('-') === -1 && defaultStart.length === 8) {
            defaultStart = defaultStart.slice(0,4) + '-' + defaultStart.slice(4,6) + '-' + defaultStart.slice(6,8);
        }
        if (defaultEnd && defaultEnd.indexOf('-') === -1 && defaultEnd.length === 8) {
            defaultEnd = defaultEnd.slice(0,4) + '-' + defaultEnd.slice(4,6) + '-' + defaultEnd.slice(6,8);
        }
        html += '<div class="filter-bar">';
        html += '<div><label>开始日期</label><br><input type="date" id="statsStartDate" value="' + defaultStart + '"></div>';
        html += '<div><label>结束日期</label><br><input type="date" id="statsEndDate" value="' + defaultEnd + '"></div>';
        html += '<button class="btn" id="statsFilterBtn">更新统计</button>';
        html += '</div>';

        // ---- Summary cards ----
        html += '<div class="stat-cards">';
        html += '<div class="stat-card"><div class="stat-label">涨停股票</div><div class="stat-value red">' + data.summary.total_stocks_with_zt + '</div></div>';
        html += '<div class="stat-card"><div class="stat-label">涨停事件</div><div class="stat-value">' + data.summary.total_zt_events + '</div></div>';
        html += '<div class="stat-card"><div class="stat-label">交易日</div><div class="stat-value" style="font-size:1.2em;">' + data.summary.date_range.start.slice(2) + '~' + data.summary.date_range.end.slice(2) + '</div></div>';
        html += '<div class="stat-card"><div class="stat-label">题材概念</div><div class="stat-value green">' + data.summary.total_concepts + '</div></div>';
        html += '</div>';

        // ---- Chart grid: Top 50 stocks + Top 50 concepts (2-col) ----
        html += '<div class="chart-grid">';
        html += '<div class="chart-box"><h4>涨停次数最多股票 Top 50 <span style="color:#888;font-size:0.8em;font-weight:normal;">（点击跳转）</span></h4><canvas id="chartTopStocks"></canvas></div>';
        html += '<div class="chart-box"><h4>涨停活跃概念 Top 50 <span style="color:#888;font-size:0.8em;font-weight:normal;">（点击跳转）</span></h4><canvas id="chartTopConcepts"></canvas></div>';
        html += '</div>';

        // ---- Chart: Daily activity (full width) ----
        html += '<div class="chart-box"><h4>每日涨停股票数</h4><canvas id="chartDaily"></canvas></div>';

        // ---- 连板分布 (clickable buttons) ----
        var lianban = data.summary.lianban_distribution || {};
        var lbLabels = Object.keys(lianban);
        html += '<div class="dist-section"><h4>连板分布</h4>';
        html += '<div class="bucket-bar" data-bucket-type="lianban">';
        lbLabels.forEach(function(k) {
            var active = (_currentBucketType === 'lianban' && _currentBucketKey === k) ? ' active' : '';
            html += '<span class="bucket-btn' + active + '" data-bucket="lianban" data-bucket-key="' + k + '">' + k + ': ' + lianban[k] + '</span>';
        });
        html += '</div>';
        html += '<div class="bucket-detail' + (_currentBucketType === 'lianban' ? ' active' : '') + '" id="bucketDetailLianban"></div>';
        html += '</div>';

        // ---- 涨停次数分布 (clickable buttons) ----
        var dist = data.summary.daily_zt_distribution || {};
        var distLabels = Object.keys(dist);
        html += '<div class="dist-section"><h4>涨停次数分布</h4>';
        html += '<div class="bucket-bar" data-bucket-type="zt">';
        distLabels.forEach(function(k) {
            var active = (_currentBucketType === 'zt' && _currentBucketKey === k) ? ' active' : '';
            html += '<span class="bucket-btn' + active + '" data-bucket="zt" data-bucket-key="' + k + '">' + k + ': ' + dist[k] + '</span>';
        });
        html += '</div>';
        html += '<div class="bucket-detail' + (_currentBucketType === 'zt' ? ' active' : '') + '" id="bucketDetailZt"></div>';
        html += '</div>';

        // ---- 热门涨停股票 (at bottom) ----
        html += '<div class="hot-section">';
        html += '<div class="section-header" style="margin-bottom:8px;">';
        html += '<h4>热门涨停股票</h4>';
        var showAllHot = window._showAllHot || false;
        html += '<span class="show-all-btn" data-show-section="hot">' + (showAllHot ? '收起' : '显示全部') + '</span>';
        html += '</div>';
        html += '<div id="statsHotContainer"><div class="loading" style="padding:10px;">加载中...</div></div>';
        html += '</div>';

        html += '</div>';
        container.innerHTML = html;

        // Wire up filter button
        document.getElementById('statsFilterBtn').addEventListener('click', function() {
            loadStats();
        });

        // ===== Chart 1: Top stocks (horizontal bar) =====
        var topStocks = data.top_stocks || [];
        if (topStocks.length > 0) {
            var ctx1 = document.getElementById('chartTopStocks').getContext('2d');
            statsCharts.push(new Chart(ctx1, {
                type: 'bar',
                data: {
                    labels: topStocks.map(function(s) { return s.code + ' ' + s.name; }),
                    datasets: [{
                        label: '涨停次数',
                        data: topStocks.map(function(s) { return s.zt_count; }),
                        backgroundColor: topStocks.map(function(s) {
                            var c = s.zt_count;
                            return c >= 15 ? '#e94560' : c >= 10 ? '#ffc107' : c >= 5 ? '#00d4ff' : '#0f3460';
                        }),
                        borderRadius: 4
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false, indexAxis: 'y',
                    onClick: function(e, elements) {
                        if (elements.length > 0) {
                            var idx = elements[0].index;
                            var stock = topStocks[idx];
                            if (stock) selectStock(stock.code, stock.name);
                        }
                    },
                    plugins: {
                        legend: { display: false },
                        datalabels: { anchor: 'end', align: 'end', color: '#eee', font: { size: 9 }, formatter: function(v) { return v + '次'; } }
                    },
                    scales: {
                        x: { grid: { color: '#333' }, ticks: { color: '#888' } },
                        y: { grid: { display: false }, ticks: { color: '#aaa', font: { size: 9 } } }
                    }
                }
            }));
        }

        // ===== Chart 2: Top concepts (horizontal bar) =====
        var topConcepts = data.top_concepts || [];
        if (topConcepts.length > 0) {
            var ctx2 = document.getElementById('chartTopConcepts').getContext('2d');
            statsCharts.push(new Chart(ctx2, {
                type: 'bar',
                data: {
                    labels: topConcepts.map(function(s) { return s.concept; }),
                    datasets: [{
                        label: '涨停事件',
                        data: topConcepts.map(function(s) { return s.total_zt_events; }),
                        backgroundColor: topConcepts.map(function(s) {
                            var c = s.total_zt_events;
                            return c >= 100 ? '#e94560' : c >= 50 ? '#ffc107' : c >= 20 ? '#00d4ff' : '#0f3460';
                        }),
                        borderRadius: 4
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false, indexAxis: 'y',
                    onClick: function(e, elements) {
                        if (elements.length > 0) {
                            var idx = elements[0].index;
                            var concept = topConcepts[idx];
                            if (concept) {
                                switchTab('concept');
                                var ci = document.getElementById('conceptQueryInput');
                                if (ci) { ci.value = concept.concept; }
                                setTimeout(function() { doConceptSearch(); }, 50);
                            }
                        }
                    },
                    plugins: {
                        legend: { labels: { color: '#888', font: { size: 10 } } },
                        datalabels: {
                            anchor: 'end', align: 'end', color: '#eee', font: { size: 8 },
                            formatter: function(v, ctx) {
                                var idx = ctx.dataIndex;
                                var sc = topConcepts[idx] ? topConcepts[idx].zt_stock_count : 0;
                                return v + '次/' + sc + '股';
                            }
                        }
                    },
                    scales: {
                        x: { grid: { color: '#333' }, ticks: { color: '#888' } },
                        y: { grid: { display: false }, ticks: { color: '#aaa', font: { size: 9 } } }
                    }
                }
            }));
        }

        // ===== Chart 3: Daily activity =====
        var dailyData = data.daily_activity || [];
        if (dailyData.length > 0) {
            var ctx3 = document.getElementById('chartDaily').getContext('2d');
            statsCharts.push(new Chart(ctx3, {
                type: 'line',
                data: {
                    labels: dailyData.map(function(d) { return d.date.slice(4); }),
                    datasets: [{
                        label: '涨停股票数',
                        data: dailyData.map(function(d) { return d.zt_count; }),
                        borderColor: '#00d4ff',
                        backgroundColor: 'rgba(0,212,255,0.1)',
                        fill: true, tension: 0.3, pointRadius: 2, pointHitRadius: 10
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { labels: { color: '#888' } }, datalabels: { display: false } },
                    scales: {
                        x: { grid: { color: '#333' }, ticks: { color: '#888', font: { size: 9 } } },
                        y: { grid: { color: '#333' }, ticks: { color: '#888' } }
                    }
                }
            }));
        }

        // ===== Load hot stocks =====
        loadStatsHotStocks(paramStr);

        // ===== Already loaded bucket content if needed =====
        if (_currentBucketType && _currentBucketKey) {
            loadBucketDetail(_currentBucketType, _currentBucketKey, bucketParamStr);
        }

    }).catch(function(e) {
        container.innerHTML = '<div class="error">统计加载失败: ' + e.message + '</div>';
    });
}

// Load hot stocks section at bottom of stats
function loadStatsHotStocks(paramStr) {
    var container = document.getElementById('statsHotContainer');
    if (!container) return;
    var url = '/api/hot_stocks?top_n=200' + (paramStr ? paramStr.replace('?', '&') : '');
    _cachedFetch(url).then(function(data) {
        if (!data || data.length === 0) {
            container.innerHTML = '<div class="empty">暂无数据</div>';
            return;
        }
        window._statsHotData = data;
        renderStatsHotTable();
    }).catch(function() {
        if (container) container.innerHTML = '<div class="error">加载失败</div>';
    });
}

var _statsHotSortCol = '';
var _statsHotSortDir = 'desc';
function sortStatsHot(col) {
    if (_statsHotSortCol === col) {
        _statsHotSortDir = _statsHotSortDir === 'desc' ? 'asc' : 'desc';
    } else {
        _statsHotSortCol = col;
        _statsHotSortDir = 'desc';
    }
    renderStatsHotTable();
}
function renderStatsHotTable() {
    var container = document.getElementById('statsHotContainer');
    if (!container) return;
    var data = window._statsHotData;
    if (!data || data.length === 0) {
        container.innerHTML = '<div class="empty">暂无数据</div>';
        return;
    }
    // Sort
    var sorted = data.slice();
    if (_statsHotSortCol === 'zt_count') {
        sorted.sort(function(a, b) {
            return _statsHotSortDir === 'desc' ? (b.zt_count - a.zt_count) : (a.zt_count - b.zt_count);
        });
    } else if (_statsHotSortCol === 'last_zt') {
        sorted.sort(function(a, b) {
            var da = a.last_zt || '';
            var db = b.last_zt || '';
            if (da === db) return 0;
            if (!da) return 1;
            if (!db) return -1;
            return _statsHotSortDir === 'desc' ? (db.localeCompare(da)) : (da.localeCompare(db));
        });
    }

    var showAllHot = window._showAllHot || false;
    var limit = showAllHot ? sorted.length : 30;
    var displayData = sorted.slice(0, limit);

    function sortArrow(col) {
        if (_statsHotSortCol !== col) return '';
        return _statsHotSortDir === 'desc' ? ' &#9660;' : ' &#9650;';
    }
    function scoreClass(sc) {
        if (sc >= 70) return 'score-high';
        if (sc >= 40) return 'score-mid';
        return 'score-low';
    }
    var html = '<table><tr><th>#</th><th>代码</th><th>名称</th><th style="cursor:pointer;user-select:none;" onclick="sortStatsHot(\\x27zt_count\\x27)">涨停' + sortArrow('zt_count') + '</th><th>综合评分</th><th>题材概念</th><th>时间周期</th><th style="cursor:pointer;user-select:none;" onclick="sortStatsHot(\\x27last_zt\\x27)">最近涨停' + sortArrow('last_zt') + '</th></tr>';
    displayData.forEach(function(s, i) {
        var conceptHtml = renderConceptChips(s.concepts, s.code, s.name);
        html += '<tr class="clickable" data-code="' + s.code + '" data-name="' + s.name + '">';
        html += '<td style="color:#888;">' + (i+1) + '</td>';
        html += '<td><strong>' + s.code + '</strong></td>';
        html += '<td>' + (s.name || '') + '</td>';
        html += '<td style="color:#ff6b6b;font-weight:bold;">' + s.zt_count + '次</td>';
        html += '<td><span class="score-badge ' + scoreClass(s.weighted_score) + '">' + s.weighted_score + '</span></td>';
        html += '<td>' + conceptHtml + '</td>';
        html += '<td style="color:#888;font-size:0.85em;">' + (s.date_range_text || '') + '</td>';
        html += '<td>' + (s.last_zt || '') + '</td></tr>';
    });
    html += '</table>';
    // 显示全部 toggle at bottom of table
    if (data.length > 30) {
        if (showAllHot) {
            html += '<div style="text-align:center;padding:6px;"><a href="javascript:window._showAllHot=false;renderStatsHotTable();" style="color:#4fc3f7;font-size:0.85em;cursor:pointer;">收起</a> <span style="color:#666;font-size:0.85em;">共' + data.length + '只</span></div>';
        } else {
            html += '<div style="text-align:center;padding:6px;"><a href="javascript:window._showAllHot=true;renderStatsHotTable();" style="color:#4fc3f7;font-size:0.85em;cursor:pointer;">显示全部 ' + data.length + '只</a></div>';
        }
    }
    container.innerHTML = html;
    loadLuReasons();
    _fillKplPaths();
}

// Fetch and display bucket detail
function loadBucketDetail(type, key, paramStr) {
    var containerId = type === 'lianban' ? 'bucketDetailLianban' : 'bucketDetailZt';
    var container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '<div class="loading" style="padding:8px;">加载中...</div>';
    container.classList.add('active');

    fetch('/api/stats_bucket?type=' + type + '&bucket=' + encodeURIComponent(key) + (paramStr || '') + '&top_n=100')
        .then(function(r) { return r.json(); }).then(function(data) {
        var stocks = data.stocks || [];
        if (stocks.length === 0) {
            container.innerHTML = '<div style="color:#888;padding:8px;font-size:0.85em;">无数据</div>';
            return;
        }
        window._bucketDetailStocks = {type: type, stocks: stocks};
        _bucketDetailSortCol = '';
        _bucketDetailSortDir = 'asc';
        renderBucketDetail();
    }).catch(function() {
        container.innerHTML = '<div class="error">加载失败</div>';
    });
}

var _bucketDetailSortCol = '';
var _bucketDetailSortDir = 'asc';
function sortBucket(col) {
    if (_bucketDetailSortCol === col) {
        _bucketDetailSortDir = _bucketDetailSortDir === 'asc' ? 'desc' : 'asc';
    } else {
        _bucketDetailSortCol = col;
        _bucketDetailSortDir = 'asc';
    }
    renderBucketDetail();
}
function renderBucketDetail() {
    var info = window._bucketDetailStocks;
    if (!info) return;
    var type = info.type;
    var stocks = info.stocks;
    var container = document.getElementById(type === 'lianban' ? 'bucketDetailLianban' : 'bucketDetailZt');
    if (!container) return;

    // Sort for zt type
    var sorted = stocks.slice();
    if (type !== 'lianban' && _bucketDetailSortCol) {
        if (_bucketDetailSortCol === 'zt_count') {
            sorted.sort(function(a, b) {
                return _bucketDetailSortDir === 'desc' ? (b.zt_count - a.zt_count) : (a.zt_count - b.zt_count);
            });
        } else if (_bucketDetailSortCol === 'last_zt') {
            sorted.sort(function(a, b) {
                var da = a.last_zt || '';
                var db = b.last_zt || '';
                if (da === db) return 0;
                if (!da) return 1;
                if (!db) return -1;
                return _bucketDetailSortDir === 'desc' ? (db.localeCompare(da)) : (da.localeCompare(db));
            });
        }
    }

    function sortArrow(col) {
        if (_bucketDetailSortCol !== col) return '';
        return _bucketDetailSortDir === 'desc' ? ' &#9660;' : ' &#9650;';
    }

    var html = '<table><tr><th>#</th><th>代码</th><th>名称</th>';
    if (type === 'lianban') {
        html += '<th>最大连板</th><th>最近连板日期</th><th>连板日期</th>';
    } else {
        html += '<th style="cursor:pointer;user-select:none;" onclick="sortBucket(\\x27zt_count\\x27)">涨停次数' + sortArrow('zt_count') + '</th>';
        html += '<th style="cursor:pointer;user-select:none;" onclick="sortBucket(\\x27last_zt\\x27)">最近涨停' + sortArrow('last_zt') + '</th>';
    }
    html += '<th>题材概念</th></tr>';
    sorted.forEach(function(s, i) {
        html += '<tr class="clickable" data-code="' + s.code + '" data-name="' + s.name + '">';
        html += '<td style="color:#888;">' + (i+1) + '</td>';
        html += '<td><strong>' + s.code + '</strong></td>';
        html += '<td>' + (s.name || '') + '</td>';
        if (type === 'lianban') {
            html += '<td style="color:#ffc107;">' + s.max_lianban + '板</td>';
            html += '<td style="color:#ff6b6b;">' + (s.lianban_end_date || '') + '</td>';
            html += '<td>' + (s.lianban_dates || []).slice(-3).join(', ') + '</td>';
        } else {
            html += '<td style="color:#ff6b6b;font-weight:bold;">' + s.zt_count + '次</td>';
            html += '<td>' + (s.last_zt || '') + '</td>';
        }
        html += '<td>' + renderConceptChips(s.concepts, s.code, s.name) + '</td></tr>';
    });
    html += '</table>';
    container.innerHTML = html;
    loadLuReasons();
    _fillKplPaths();
}

// 精准狙击
function loadSniper() {
    var container = document.getElementById('sniperContainer');
    container.innerHTML = '<div class="loading">加载精准狙击数据中...</div>';

    Promise.all([
        _cachedFetch('/api/sniper_data').catch(function() { return null; }),
        _cachedFetch('/api/sector_ranking').catch(function() { return null; })
    ]).then(function(results) {
        var data = results[0];
        var sectorData = results[1];
        if (!data || data.error || !data.dates || data.dates.length === 0) {
            container.innerHTML = '<div class="result"><div class="empty">暂无精准狙击数据</div></div>';
            return;
        }

        var html = '<div class="result" id="sn-nav-top">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;">';
        html += '<h3 style="color:#ff6b6b;margin:0;">\U0001F3AF 精准狙击</h3>';
        html += '<div style="display:flex;align-items:center;gap:8px;">';
        html += '<span style="color:#888;font-size:0.85em;">\u57fa\u4e8e\u5f00\u76d8\u5566\u6da8\u505c\u539f\u56e0\u6807\u7b7e | \u6700\u8fd1' + data.dates.length + '\u4e2a\u4ea4\u6613\u65e5</span>';
        html += '<span class="rt-refresh-icon" onclick="manualRefreshSniper()" title="\u624b\u52a8\u5237\u65b0">\u21bb</span>';
        html += '<button class="rt-auto-refresh-btn" id="sniperAutoRefreshBtn" onclick="toggleSniperAutoRefresh()">\u23f1 \u81ea\u52a8\u5237\u65b0 3\u5206\u949f</button>';
        html += '</div></div>';

        // Sidebar
        html += '<div class="np-wrapper">';
        html += '<button class="np-sidebar-showbtn" id="sniperSidebarShow" onclick="toggleSniperSidebar()" style="display:none;" title="\u663e\u793a\u5bfc\u822a">\u2630</button>';
        html += '<nav class="np-sidebar" id="sniperSidebar">';
        html += '<div class="np-sidebar-hide" onclick="toggleSniperSidebar()" title="\u9690\u85cf\u5bfc\u822a">\u2715</div>';
        html += '<a class="np-sidebar-item" onclick="scrollToNpSection(\\x27sn-section-realtime\\x27)">实时行情</a>';
        html += '<a class="np-sidebar-item" onclick="scrollToNpSection(\\x27sn-section-placeholder\\x27)">\u26a1 \u5b9e\u65f6\u5f3a\u699c</a>';
        html += '<a class="np-sidebar-item" onclick="scrollToNpSection(\\x27sn-section-freq\\x27)">\U0001F4CA 频度分析</a>';
        html += '<a class="np-sidebar-item" onclick="scrollToNpSection(\\x27sn-section-wind-vane\\x27)">\u26a1 风向标</a>';
        html += '<a class="np-sidebar-item" onclick="scrollToNpSection(\\x27sn-section-pmsl\\x27)">\U0001F4CB 盘面梳理</a>';
        html += '<div style="border-top:1px solid rgba(255,255,255,0.06);margin:6px 0;"></div>';
        data.dates.forEach(function(date) {
            html += '<a class="np-sidebar-item" onclick="scrollToNpSection(\\x27sn-section-date-' + date + '\\x27)">' + date + '</a>';
            var tagGroup = data.data[date] || {};
            var tags = Object.keys(tagGroup).sort(function(a, b) { return tagGroup[b].length - tagGroup[a].length; });
            tags.slice(0, 5).forEach(function(tag) {
                var tagEsc = ('' + tag).replace(/['"&<>]/g, '');
                html += '<a class="np-sidebar-subitem" onclick="scrollToNpSection(\\x27sn-section-date-' + date + '-' + tagEsc + '\\x27)">' + _kplEsc(tag) + '</a>';
            });
        });
        html += '</nav>';

        // Main content
        html += '<div class="np-main-content">';
        html += '<div id="sn-results">';

        // Section 0: 实时行情 · 精选板块强度排行
        html += '<div class="sniper-section" id="sn-section-realtime">';
        html += '<h3>\U0001F4C8 \u5b9e\u65f6\u884c\u60c5 \u00b7 \u7cbe\u9009\u677f\u5757\u5f3a\u5ea6\u6392\u884c</h3>';
        if (sectorData && !sectorData.error && Array.isArray(sectorData) && sectorData.length > 0) {
            var sItems = sectorData.slice().sort(function(a,b){return (b.stock_count||0)-(a.stock_count||0);}).slice(0, 20);
            html += '<div class="sr-table-wrapper"><table class="sr-table">';
            html += '<thead><tr><th>#</th><th>\u677f\u5757\u540d\u79f0</th><th>\u5f3a\u5ea6</th><th>\u4e3b\u529b\u51c0\u989d</th><th>\u6da8\u8dcc\u5e45</th></tr></thead><tbody>';
            sItems.forEach(function(si, siIdx) {
                var plateName = si.plate_name || si.name || '--';
                var changePct = si.change_pct;
                var netInflow5d = si.net_inflow_5d;
                var stockCount = si.stock_count !== undefined && si.stock_count !== null ? si.stock_count : '--';
                // 涨跌幅格式化
                var pctStr, pctCls;
                if (changePct === undefined || changePct === null) {
                    pctStr = '--'; pctCls = '';
                } else {
                    var arrow = changePct > 0 ? '\u2191' : (changePct < 0 ? '\u2193' : '');
                    pctStr = (changePct > 0 ? '+' : '') + changePct.toFixed(2) + '%' + arrow;
                    pctCls = changePct >= 0 ? 'sr-change-up' : 'sr-change-down';
                }
                // 净额格式化
                function _srFmtInflow(v) {
                    if (v === undefined || v === null) return '--';
                    var a = v / 1e8;
                    return (v >= 0 ? '+' : '') + a.toFixed(2) + '\u4ebf';
                }
                var inflow5dStr = _srFmtInflow(netInflow5d);
                var inflow5dCls = (netInflow5d !== undefined && netInflow5d !== null) ? (netInflow5d >= 0 ? 'sr-inflow-pos' : 'sr-inflow-neg') : '';
                html += '<tr>';
                html += '<td style="color:#888;width:32px;">' + (siIdx + 1) + '</td>';
                html += '<td><strong>' + _kplEsc(plateName) + '</strong></td>';
                html += '<td style="color:#888;">' + stockCount + '</td>';
                html += '<td class="' + inflow5dCls + '">' + inflow5dStr + '</td>';
                html += '<td class="' + pctCls + '">' + pctStr + '</td>';
                html += '</tr>';
            });
            html += '</tbody></table></div>';
        } else {
            html += '<div class="sniper-placeholder">\u6682\u65e0\u5b9e\u65f6\u677f\u5757\u6570\u636e\uff0c\u975e\u4ea4\u6613\u65f6\u6bb5\u6216\u6570\u636e\u52a0\u8f7d\u5931\u8d25</div>';
        }
        html += '</div>';

        // Section 1: 实时强榜 - 涨停原因标签最强梯队
        var strongList = data.top_20_strong || [];
        var totalTags = strongList.length;
        // 题材走势数据存储
        var _sniperTrendStocks = {};
        html += '<div class="sniper-section" id="sn-section-placeholder">';
        html += '<div class="np-cat-header" onclick="toggleNpCategory(this)">';
        html += '<span class="cat-icon">\u26a1</span>';
        html += '<span class="cat-name">\u5b9e\u65f6\u5f3a\u699c \u00b7 ' + totalTags + '\u4e2a\u70ed\u95e8\u6807\u7b7e</span>';
        if (data.today_zt_count) {
            html += '<span class="cat-count" style="color:#ff6b6b;">\U0001F525\u4eca\u65e5' + data.today_zt_count + '\u53ea\u6da8\u505c</span>';
        }
        html += '<span class="sn-grid-tog">';
        html += '<button' + (_sniperGridCols === 1 ? ' class="active"' : '') + ' onclick="event.stopPropagation();setSniperGridCols(1)" data-cols="1">1\u5217</button>';
        html += '<button' + (_sniperGridCols === 2 ? ' class="active"' : '') + ' onclick="event.stopPropagation();setSniperGridCols(2)" data-cols="2">2\u5217</button>';
        html += '<button' + (_sniperGridCols === 4 ? ' class="active"' : '') + ' onclick="event.stopPropagation();setSniperGridCols(4)" data-cols="4">4\u5217</button>';
        html += '</span>';
        html += '<span class="cat-arrow">\u25bc</span>';
        html += '</div>';
        html += '<div class="np-cat-body">';
        html += '<div class="sniper-strong-grid">';

        strongList.forEach(function(item, idx) {
            // 今日涨停排前面，按封板时间升序（越早越前）；非今日按连板数降序
            item.stocks.sort(function(a, b) {
                if (a.is_today_zt && b.is_today_zt) {
                    return (a.first_time || 999999) - (b.first_time || 999999);
                }
                if (a.is_today_zt) return -1;
                if (b.is_today_zt) return 1;
                return (b.max_lianban || 0) - (a.max_lianban || 0) || (b.zt_count || 0) - (a.zt_count || 0);
            });
            // 存储题材走势数据
            _sniperTrendStocks[item.tag] = item.stocks.map(function(s) {
                return {code: s.code, name: s.name, concepts: s.concepts || ''};
            });
            var rankStr = (idx < 3 ? ['\U0001F947','\U0001F948','\U0001F949'][idx] : '#' + (idx+1));
            html += '<div class="sniper-strong-card">';
            html += '<div class="sniper-strong-card-header" onclick="scrollToNpSection(\\x27sn-section-date-' + data.dates[0] + '-' + (''+item.tag).replace(/[\\s'"]/g,'') + '\\x27)">';
            html += '<span class="sniper-strong-rank">' + rankStr + '</span>';
            html += '<span class="sniper-strong-tag">' + _kplEsc(item.tag) + '</span>';
            html += '<span class="sniper-trend-btn" onclick="toggleTagTrend(\\x27' + _kplEsc(item.tag).replace(/'/g,"\\'") + '\\x27)" title="\u67e5\u770b\u8be5\u9898\u6750\u6240\u6709\u80a1\u7968\u7684K\u7ebf\u8d70\u52bf">\u25b3 \u8d70\u52bf</span>';
            html += '<span class="sniper-strong-total">' + item.total + '\u6b21</span>';
            // 近10日逐日频度
            var dailyParts = [];
            var rankDates = data.rank_dates || [];
            rankDates.forEach(function(rd) {
                dailyParts.push(item.rank_daily && item.rank_daily[rd] != null ? item.rank_daily[rd] : 0);
            });
            if (dailyParts.length) {
                html += '<span class="sniper-strong-daily">' + dailyParts.join('\u2190') + '</span>';
            }
            html += '</div>';
            html += '<div class="sniper-strong-stocks">';
            // 收集该卡片所有股票code，用于生成详情占位
            var cardCodes = [];
            item.stocks.forEach(function(s, si) {
                var boardCls = _kplGetBoardClass(s.code);
                var lbStr = s.max_lianban > 0 ? '<span class="sniper-strong-lb">' + s.max_lianban + '\u8fde\u677f</span>' : '';
                var todayCls = s.is_today_zt ? ' sniper-strong-stock-today' : '';
                var ft = s.first_time;
                var timeStr = '';
                if (ft && ft < 999999) {
                    var ts = String(ft).padStart(6, '0');
                    timeStr = ts.slice(0, 2) + ':' + ts.slice(2, 4);
                }
                html += '<div class="sniper-strong-stock' + todayCls + '" onclick="showEnlargedCardDetail(\\x27' + s.code + '\\x27)">';
                html += '<span class="sniper-strong-stock-rank">' + (si+1) + '</span>';
                if (s.is_today_zt) {
                    html += '<span class="today-zt-badge">\U0001F525\u4eca\u65e5\u6da8\u505c</span>';
                    if (timeStr) html += '<span class="today-zt-time">' + timeStr + '</span>';
                }
                html += '<span class="np-card-code ' + boardCls + '">' + s.code + '</span>';
                // 名称+附加信息行内
                var infoParts = [];
                if (s.concepts) infoParts.push(_kplEsc(s.concepts));
                if (s.reason_tag) infoParts.push(_kplEsc(s.reason_tag));
                if (s.is_today_zt) {
                    if (s.reason_brief) infoParts.push(_kplEsc(s.reason_brief));
                    infoParts.push('\U0001F525\u4eca\u65e5');
                } else {
                    if (s.reason_brief) infoParts.push(_kplEsc(s.reason_brief));
                    if (s.latest_date) infoParts.push(s.latest_date);
                }
                html += '<div style="flex:1;min-width:0;display:flex;align-items:center;gap:3px;overflow:hidden;">';
                html += '<span class="np-card-name">' + _kplEsc(s.name) + '</span>';
                if (infoParts.length > 0) {
                    html += '<span class="sniper-stock-inline-info">' + infoParts.join(' | ') + '</span>';
                }
                html += '</div>';
                html += lbStr;
                if (s.zt_count > 1) {
                    html += '<span class="sniper-strong-zt-count">' + s.zt_count + '\u6b21</span>';
                }
                html += '</div>';
                if (s.code) cardCodes.push(s.code);
            });
            // 为强榜股票生成隐藏的详情占位，以便点击弹出放大卡片
            cardCodes.forEach(function(c) {
                html += '<div class="np-detail-placeholder" data-np-code="' + c + '" style="display:none;"></div>';
            });
            html += '</div></div>';
        });

        // 其他卡片：未匹配到Top分类的今日涨停
        var otherZt = data.other_today_zt || [];
        if (otherZt.length > 0) {
            html += '<div class="sniper-strong-card" style="border-color:rgba(255,193,7,0.2);">';
            html += '<div class="sniper-strong-card-header" style="background:rgba(255,193,7,0.1);">';
            html += '<span class="sniper-strong-rank" style="color:#ffc107;">\U0001F4AB</span>';
            html += '<span class="sniper-strong-tag" style="color:#ffc107;">\u5176\u4ed6</span>';
            html += '<span class="sniper-strong-total">' + otherZt.length + '\u53ea\u4eca\u65e5\u6da8\u505c</span>';
            html += '</div>';
            html += '<div class="sniper-strong-stocks">';
            otherZt.forEach(function(s, si) {
                var boardCls = _kplGetBoardClass(s.code);
                var ft = s.first_time;
                var timeStr = '';
                if (ft && ft < 999999) {
                    var ts = String(ft).padStart(6, '0');
                    timeStr = ts.slice(0, 2) + ':' + ts.slice(2, 4);
                }
                html += '<div class="sniper-strong-stock sniper-strong-stock-today" onclick="showEnlargedCardDetail(\\x27' + s.code + '\\x27)">';
                html += '<span class="sniper-strong-stock-rank">' + (si+1) + '</span>';
                html += '<span class="today-zt-badge">\U0001F525\u4eca\u65e5\u6da8\u505c</span>';
                if (timeStr) html += '<span class="today-zt-time">' + timeStr + '</span>';
                html += '<span class="np-card-code ' + boardCls + '">' + s.code + '</span>';
                // 名称+附加信息行内
                var otherInfo = [];
                if (s.reason_tag) otherInfo.push(_kplEsc(s.reason_tag));
                if (s.reason_brief) otherInfo.push(_kplEsc(s.reason_brief));
                html += '<div style="flex:1;min-width:0;display:flex;align-items:center;gap:3px;overflow:hidden;">';
                html += '<span class="np-card-name">' + _kplEsc(s.name) + '</span>';
                if (otherInfo.length > 0) {
                    html += '<span class="sniper-stock-inline-info">' + otherInfo.join(' | ') + '</span>';
                }
                html += '</div>';
                if (s.lianban > 0) {
                    html += '<span class="sniper-strong-lb">' + s.lianban + '\u8fde\u677f</span>';
                }
                html += '</div>';
                if (s.code) {
                    html += '<div class="np-detail-placeholder" data-np-code="' + s.code + '" style="display:none;"></div>';
                }
            });
            html += '</div></div>';
        }

        // 未匹配标签的今日涨停
        var untaggedZt = data.untagged_today_zt || [];
        if (untaggedZt.length > 0) {
            html += '<div class="sniper-strong-card" style="border-color:rgba(158,158,158,0.2);">';
            html += '<div class="sniper-strong-card-header" style="background:rgba(158,158,158,0.1);">';
            html += '<span class="sniper-strong-rank" style="color:#9e9e9e;">\u2753</span>';
            html += '<span class="sniper-strong-tag" style="color:#9e9e9e;">\u672a\u5339\u914d\u6807\u7b7e</span>';
            html += '<span class="sniper-strong-total">' + untaggedZt.length + '\u53ea\u4eca\u65e5\u6da8\u505c</span>';
            html += '</div>';
            html += '<div class="sniper-strong-stocks">';
            untaggedZt.forEach(function(s, si) {
                var boardCls = _kplGetBoardClass(s.code);
                var ft = s.first_time;
                var timeStr = '';
                if (ft && ft < 999999) {
                    var ts = String(ft).padStart(6, '0');
                    timeStr = ts.slice(0, 2) + ':' + ts.slice(2, 4);
                }
                html += '<div class="sniper-strong-stock sniper-strong-stock-today" onclick="showEnlargedCardDetail(\\x27' + s.code + '\\x27)">';
                html += '<span class="sniper-strong-stock-rank">' + (si+1) + '</span>';
                html += '<span class="today-zt-badge">\U0001F525\u4eca\u65e5\u6da8\u505c</span>';
                if (timeStr) html += '<span class="today-zt-time">' + timeStr + '</span>';
                html += '<span class="np-card-code ' + boardCls + '">' + s.code + '</span>';
                html += '<div style="flex:1;min-width:0;display:flex;align-items:center;gap:3px;overflow:hidden;">';
                html += '<span class="np-card-name">' + _kplEsc(s.name) + '</span>';
                html += '<span class="sniper-stock-inline-info" style="color:#9e9e9e;">\u672a\u5339\u914d\u6807\u7b7e</span>';
                html += '</div>';
                if (s.lianban > 0) {
                    html += '<span class="sniper-strong-lb">' + s.lianban + '\u8fde\u677f</span>';
                }
                html += '</div>';
                if (s.code) {
                    html += '<div class="np-detail-placeholder" data-np-code="' + s.code + '" style="display:none;"></div>';
                }
            });
            html += '</div></div>';
        }

        html += '</div>'; // close sniper-strong-grid

        // 题材走势区域（可折叠）
        html += '<div class="sniper-trend-section" id="sniperTrendSection" style="display:none;">';
        html += '<div class="sniper-trend-divider"></div>';
        html += '<div class="sniper-trend-header" onclick="closeTagTrend()">';
        html += '<span class="sniper-trend-icon">\u25b8</span>';
        html += '<span class="sniper-trend-label" id="sniperTrendLabel">\u8d70\u52bf</span>';
        html += '<span style="margin-left:auto;color:#666;font-size:0.8em;opacity:0.5;">\u2716 \u5173\u95ed</span>';
        html += '</div>';
        html += '<div class="sniper-trend-body" id="sniperTrendBody">';
        html += '<div id="sniperTrendCards"></div>';
        html += '</div>';
        html += '</div>';

        html += '</div></div>'; // close np-cat-body, sniper-section

        // 暴露趋势数据到全局
        window._sniperTrendStocks = _sniperTrendStocks;

        // Section 3: 按日期展示涨停原因标签频度（wf-timeline 风格）
        html += '<div class="sniper-section" id="sn-section-freq">';
        html += '<h3>\U0001F4CA 涨停原因标签频度分析</h3>';
        html += '<div class="wf-timeline">';

        data.dates.forEach(function(date) {
            var tagCounts = data.freq_by_date[date] || {};
            var tags = Object.keys(tagCounts).sort(function(a, b) { return tagCounts[b] - tagCounts[a]; });
            var total = 0;
            tags.forEach(function(t) { total += tagCounts[t]; });

            html += '<div class="wf-day">';
            html += '<div class="wf-day-header">\U0001F4C5 ' + date + '<span style="float:right;color:#888;font-size:0.75em;">\u5171' + total + '\u53ea</span></div>';

            var hasTags = false;
            tags.forEach(function(tag) {
                var count = tagCounts[tag];
                if (count === 0) return;
                hasTags = true;
                var cls = count >= 5 ? 'wf-tag-high' : (count >= 3 ? 'wf-tag-mid' : 'wf-tag-low');
                html += '<span class="wf-tag ' + cls + '" data-tag="' + _kplEsc(tag) + '">' + _kplEsc(tag) + ' <span class="wf-count">' + count + '</span></span>';
            });

            if (!hasTags) {
                html += '<div class="wf-day-empty">\u6682\u65e0\u6da8\u505c</div>';
            }
            html += '</div>';
        });

        html += '</div></div>';

        // ===== Section: 风向标 =====
        html += '<div class="sniper-section" id="sn-section-wind-vane">';
        html += '<h3>\u26a1 \u98ce\u5411\u6807<span class="date-tag" style="margin-left:8px;">' + (data.wind_vane_date || '') + '</span><span style="font-size:11px;color:#888;font-weight:400;margin-left:4px;">\u00b7 \u5171' + (data.wind_vane ? data.wind_vane.length : 0) + '\u53ea</span></h3>';

        if (data.wind_vane && data.wind_vane.length > 0) {
            // 按题材分组
            var wvGroups = [
                {name:'\u5149\u901a\u4fe1/\u7535\u5b50', color:'#1a6b3c', keywords:['\u901a\u4fe1','\u5149\u6a21\u5757','\u5149\u82af\u7247','\u5149\u7ea4','\u7535\u5b50\u5e03','\u8986\u94dc\u677f','\u7535\u5b50\u6811\u8102','PCB','\u5370\u5236\u7535\u8def\u677f','\u590d\u5408\u96c6\u6d41\u4f53']},
                {name:'\u534a\u5bfc\u4f53/\u5b58\u50a8', color:'#7b1fa2', keywords:['\u5b58\u50a8','MCU','HBM','\u5148\u8fdb\u5c01\u88c5','\u82af\u7247','\u6c2e\u5316\u94dd']},
                {name:'\u7b97\u529b/AI', color:'#e65100', keywords:['\u7b97\u529b','\u82f1\u4f1f\u8fbe','\u7269\u7406AI','\u6db2\u51b7','\u8bad\u63a8\u4e00\u4f53\u673a','\u7aef\u4fa7AI']},
                {name:'\u6709\u8272/\u5c0f\u91d1\u5c5e', color:'#bf360c', keywords:['\u6709\u8272\u91d1\u5c5e','\u91d1\u5c5e\u94a8','\u91d1\u5c5e\u94bc','\u91d1\u5c5e\u94dc','\u91d1\u5c5e\u9530','\u7a00\u571f','\u9547','\u6c27\u5316\u9547']},
                {name:'\u7535\u5b50\u6750\u6599', color:'#1565c0', keywords:['\u7535\u963b\u7535\u5bb9','\u7535\u5b50\u6c14\u4f53','\u9776\u6750','\u78f7\u5316\u9521','\u65b0\u6750\u6599','\u73bb\u7483\u57fa\u677f','\u975e\u91d1\u5c5e\u6750\u6599']},
            ];
            var wvOther = {name:'\u5176\u4ed6', color:'#888', stocks:[]};
            var wvSorted = wvGroups.map(function(g) { return {name:g.name, color:g.color, keywords:g.keywords, stocks:[]}; });
            data.wind_vane.forEach(function(s) {
                var themes = s.themes || '';
                var placed = false;
                for (var gi = 0; gi < wvSorted.length; gi++) {
                    for (var ki = 0; ki < wvSorted[gi].keywords.length; ki++) {
                        if (themes.indexOf(wvSorted[gi].keywords[ki]) !== -1) {
                            wvSorted[gi].stocks.push(s);
                            placed = true; break;
                        }
                    }
                    if (placed) break;
                }
                if (!placed) wvOther.stocks.push(s);
            });
            wvSorted.forEach(function(g) { g.stocks.sort(function(a,b) { return (b.turnover_rate||0) - (a.turnover_rate||0); }); });
            wvOther.stocks.sort(function(a,b) { return (b.turnover_rate||0) - (a.turnover_rate||0); });
            if (wvOther.stocks.length > 0) wvSorted.push(wvOther);

            function renderWvTable(groups) {
                var t = '<table class="wv-table"><thead><tr>';
                t += '<th style="width:28px;">#</th><th style="width:72px;">\u4ee3\u7801</th><th>\u540d\u79f0</th><th>\u9898\u6750</th><th style="width:62px;">\u6362\u624b\u7387</th><th style="width:80px;">\u51c0\u6d41\u5165</th>';
                t += '</tr></thead><tbody>';
                var idx2 = 0;
                groups.forEach(function(g) {
                    if (g.stocks.length === 0) return;
                    t += '<tr class="group-header" style="background:' + g.color + '22;"><td colspan="6" style="padding:3px 8px;font-size:11px;color:' + g.color + ';font-weight:500;border-bottom:none;">\u25b8 ' + g.name + ' <span style="color:#888;font-weight:400;">(' + g.stocks.length + '\u53ea)</span></td></tr>';
                    g.stocks.forEach(function(s) {
                        idx2++;
                        var code = s.code || '';
                        var name = s.name || '';
                        var themes = s.themes || '';
                        var tr = s.turnover_rate || 0;
                        var ni = s.net_inflow || 0;
                        var niFmt = (ni >= 0 ? '+' : '') + (ni / 1e8).toFixed(2) + '\u4ebf';
                        var niCls = ni >= 0 ? 'num-red' : 'num-green';
                        var boardCls = code.startsWith('30') ? 'gem' : (code.startsWith('688') || code.startsWith('689') ? 'tech' : 'main');
                        t += '<tr onclick="showEnlargedCardDetail(\\x27' + code + '\\x27)">';
                        t += '<td style="color:#555;">' + idx2 + '</td><td><span class="code-tag ' + boardCls + '">' + code + '</span></td><td style="color:#e8eaed;">' + _kplEsc(name) + '</td><td><span class="themes-text">' + _kplEsc(themes) + '</span></td><td><span class="num-gray">' + tr + '%</span></td><td><span class="' + niCls + '">' + niFmt + '</span></td>';
                        t += '</tr>';
                    });
                });
                t += '</tbody></table>';
                return t;
            }

            html += '<div class="wv-table-wrapper">' + renderWvTable(wvSorted) + '</div>';


            // \u5b58\u50a8\u98ce\u5411\u6807\u80a1\u7968\u6570\u636e\uff08\u5e26\u9898\u6750\uff09
            var wvKlineHits = data.wind_vane.map(function(s) {
                var themes = s.themes || '';
                var suffix = themes ? ' (' + themes + ')' : '';
                return {stock_name: (s.name || '') + suffix, stock_code: s.code || ''};
            });
            window._wvKlineHits = wvKlineHits;
            // K\u7ebf\u8d70\u52bf\u6309\u94ae
            html += '<div style="text-align:center;padding:6px 0;display:flex;justify-content:center;gap:8px;">';
            html += '<button class="concept-btn" onclick="toggleWvKlines()">\U0001F4C8 K\u7EBF\u8D70\u52BF</button>';
            html += '<button class="concept-btn" onclick="refreshWvKlines()">\U0001F503 \u5237\u65B0</button>';
            html += '</div>';
            html += '<div id="wv-kline-wrap" data-open="0" style="max-height:0;overflow:hidden;transition:max-height 0.3s ease;"></div>';
        } else {
            html += '<div class="wf-day-empty" style="text-align:center;padding:20px;color:#555;">\u6682\u65e0\u98ce\u5411\u6807\u6570\u636e</div>';
        }
        html += '</div>';

        // ===== Section: 盘面梳理 =====
        html += '<div class="sniper-section" id="sn-section-pmsl">';
        html += '<h3>\U0001F4CB \u76d8\u9762\u68b3\u7406<span class="date-tag" style="margin-left:8px;">' + (data.pmsl_date || '') + '</span><span style="font-size:11px;color:#888;font-weight:400;margin-left:4px;">\u00b7 \u5171' + (data.pmsl ? data.pmsl.length : 0) + '\u6761</span></h3>';

        if (data.pmsl && data.pmsl.length > 0) {
            var pmslTypeOrder = ['\u5927\u5355\u4e00\u5b57','\u76f4\u7ebf\u62c9\u5347','\u6743\u91cd\u62c9\u5347','\u8d8b\u52bf\u65b0\u9ad8','\u7ade\u4ef7\u52a0\u5355','\u5f31\u8f6c\u5f3a','\u5927\u957f\u817f','T\u5b57\u677f','\u9886\u5148\u8eab\u4f4d','\u4eba\u6c14\u80a1\u53cd\u62bd','\u5c3e\u76d8\u70b8\u677f\u56de\u5c01','\u4eba\u6c14\u80a1\u6740\u8dcc','\u6743\u91cd\u6740\u8dcc','\u5317\u4ea4\u6240'];
            var pmslGroups = {};
            data.pmsl.forEach(function(ev) {
                var tn = ev.TagName || '\u672a\u77e5';
                if (!pmslGroups[tn]) pmslGroups[tn] = [];
                pmslGroups[tn].push(ev);
            });
            Object.keys(pmslGroups).forEach(function(tn) {
                pmslGroups[tn].sort(function(a,b) { return (a.TimeMin||0) - (b.TimeMin||0); });
            });

            html += '<div class="pmsl-timeline">';
            pmslTypeOrder.forEach(function(tn) {
                var evts = pmslGroups[tn] || [];
                if (evts.length === 0) return;
                var firstShuXing = evts[0].TagShuXing;
                var cls = firstShuXing === 2 ? 'pos' : (firstShuXing === 0 ? 'neg' : 'neu');
                html += '<div class="pmsl-type-group">';
                html += '<span class="pmsl-type-title ' + cls + '">' + _kplEsc(tn) + ' ' + evts.length + '</span>';
                evts.forEach(function(ev) {
                    var ts = ev.TimeMin || 0;
                    var d = new Date((ts + 8 * 3600) * 1000);
                    var hh = String(d.getUTCHours()).padStart(2,'0');
                    var mm = String(d.getUTCMinutes()).padStart(2,'0');
                    var timeStr = hh + ':' + mm;
                    var zsName = ev.ZSName || '';
                    var detail = ev.Detail || '';
                    var stockList = ev.StockList || [];
                    var evCls = ev.TagShuXing === 2 ? 'pos' : (ev.TagShuXing === 0 ? 'neg' : 'neu');
                    html += '<div class="pmsl-event ' + evCls + '">';
                    html += '<div class="pmsl-left"><div class="pmsl-time">' + timeStr + '</div></div>';
                    html += '<div class="pmsl-right">';
                    if (zsName) html += '<div class="pmsl-sector">' + _kplEsc(zsName) + '</div>';
                    if (detail) html += '<div class="pmsl-detail">' + _kplEsc(detail) + '</div>';
                    if (stockList.length > 0) {
                        html += '<div class="pmsl-stocks">';
                        stockList.forEach(function(stk) {
                            var stkCode = stk[0] || '';
                            var stkName = stk[1] || '';
                            var stkBoard = stkCode.startsWith('30') ? 'gem' : (stkCode.startsWith('688') || stkCode.startsWith('689') ? 'tech' : 'main');
                            html += '<span class="pmsl-stock-tag ' + stkBoard + '" onclick="showEnlargedCardDetail(\\x27' + stkCode + '\\x27)">' + _kplEsc(stkName) + '</span>';
                        });
                        html += '</div>';
                    }
                    html += '</div></div>';
                });
                html += '</div>';
            });
            html += '</div>';

            // 存储盘面梳理股票数据（带板块名作题材）
            var pmslStockMap = {};
            data.pmsl.forEach(function(ev) {
                var zs = ev.ZSName || '';
                (ev.StockList || []).forEach(function(stk) {
                    var code = stk[0] || '';
                    var name = stk[1] || '';
                    if (code && !pmslStockMap[code]) {
                        pmslStockMap[code] = {name: name, code: code, sector: zs};
                    }
                });
            });
            var pmslKlineHits = [];
            for (var code in pmslStockMap) {
                var s = pmslStockMap[code];
                var suffix = s.sector ? ' (' + s.sector + ')' : '';
                pmslKlineHits.push({stock_name: s.name + suffix, stock_code: s.code});
            }
            window._pmslKlineHits = pmslKlineHits;
            // K线走势按钮
            html += '<div style="text-align:center;padding:6px 0;display:flex;justify-content:center;gap:8px;">';
            html += '<button class="concept-btn" onclick="togglePmslKlines()">\U0001F4C8 K\u7EBF\u8D70\u52BF</button>';
            html += '<button class="concept-btn" onclick="refreshPmslKlines()">\U0001F503 \u5237\u65B0</button>';
            html += '</div>';
            html += '<div id="pmsl-kline-wrap" data-open="0" style="max-height:0;overflow:hidden;transition:max-height 0.3s ease;"></div>';
        } else {
            html += '<div class="wf-day-empty" style="text-align:center;padding:20px;color:#555;">\u6682\u65e0\u76d8\u9762\u68b3\u7406\u6570\u636e</div>';
        }
        html += '</div>';

        // Section 2: 按日期渲染
        data.dates.forEach(function(date) {
            var tagGroup = data.data[date] || {};
            var tags = Object.keys(tagGroup).sort(function(a, b) { return tagGroup[b].length - tagGroup[a].length; });
            var total = 0;
            for (var t in tagGroup) total += tagGroup[t].length;

            html += '<div class="sniper-section" id="sn-section-date-' + date + '">';
            html += '<div class="np-cat-header collapsed" onclick="toggleSniperDate(this)" data-sn-date="' + date + '">';
            html += '<span class="cat-icon">\U0001F4C5</span>';
            html += '<span class="cat-name">' + date + '</span>';
            html += '<span class="cat-count">' + total + '\u53ea</span>';
            html += '<span class="cat-arrow">\u25bc</span>';
            html += '</div>';
            html += '<div class="np-cat-body collapsed">';

            tags.forEach(function(tag) {
                var tagEsc = ('' + tag).replace(/['"&<>\s]/g, '');
                var records = tagGroup[tag];
                html += '<div class="sniper-tag-section" id="sn-section-date-' + date + '-' + tagEsc + '">';
                html += '<div class="sniper-tag-header collapsed" onclick="toggleSniperTag(this)" data-sn-date="' + date + '" data-sn-tag="' + _kplEsc(tag) + '">';
                html += '<span class="sniper-tag-name">' + _kplEsc(tag) + '</span>';
                html += '<span class="sniper-tag-count">' + records.length + '\u53ea</span>';
                html += '<span class="sniper-tag-arrow">\u25bc</span>';
                html += '</div>';
                html += '<div class="sniper-tag-body collapsed">';
                html += '<div class="np-card-grid" data-sn-grid="' + date + '-' + tagEsc + '">';

                records.forEach(function(r) {
                    var code = r.stock_code || '';
                    var name = r.stock_name || '';
                    var boardCls = _kplGetBoardClass(code);
                    var concepts = r.concepts || '';

                    html += '<div class="np-card ' + boardCls + '" data-code="' + code + '" data-name="' + _kplEsc(name) + '">';
                    html += '<div class="np-card-header"><div>';
                    html += '<span class="np-card-code" data-code="' + code + '" data-name="' + _kplEsc(name) + '">' + (code || '') + '</span>';
                    html += _watchStarHtml(code, name, _watchGetCategory(code));
                    html += '<span class="np-card-name">' + _kplEsc(name) + '</span>';
                    html += '</div>';
                    html += '<div>' + (code ? '<button class="np-enlarge-btn" onclick="event.stopPropagation();showEnlargedCardDetail(\\x27' + code + '\\x27)" title="\u653e\u5927\u5361\u7247">\u2b36</button>' : '') + '</div>';
                    html += '</div>';
                    if (code) {
                        html += '<div class="np-detail-placeholder" data-np-code="' + code + '"><div class="empty" style="padding:8px;">\u5c55\u5f00\u540e\u52a0\u8f7d\u8be6\u60c5</div></div>';
                    }
                    html += '</div>';
                });

                html += '</div></div></div>'; // tag-body, tag-section
            });

            html += '<div class="np-back-top" onclick="scrollToNpSection(\\x27sn-nav-top\\x27)">\u2191 \u56de\u5230\u9876\u90e8</div>';
            html += '</div></div>'; // cat-body, section
        });

        html += '</div></div></div>'; // cat-results, main-content, wrapper
        html += '</div>'; // result
        container.innerHTML = html;

        // 自动加载实时强榜股票的详情（用于弹窗放大）
        setTimeout(function() { loadSniperCardDetails(); }, 100);

        // Apply grid columns
        document.querySelectorAll('.np-card-grid').forEach(function(g) {
            g.style.setProperty('--np-cols', _npGridCols);
        });
        document.querySelectorAll('.sniper-strong-grid').forEach(function(g) {
            g.style.setProperty('--sn-cols', _sniperGridCols);
        });

        // 频度分析标签点击 → KPL搜索（委托事件）
        container.querySelectorAll('.wf-tag[data-tag]').forEach(function(el) {
            el.onclick = function() {
                searchTagInKpl(this.getAttribute('data-tag'));
            };
        });
    }).catch(function(e) {
        container.innerHTML = '<div class="result"><div class="error">精准狙击数据加载失败: ' + e.message + '</div></div>';
    });
}

// 精准狙击 —— 手动刷新（跳过缓存）
function manualRefreshSniper() {
    var icon = document.querySelector('#tab-sniper .rt-refresh-icon');
    if (icon) icon.classList.add('spinning');
    // 清除板块排行客户端缓存并预热服务端缓存
    delete _tabCache['/api/sector_ranking'];
    fetch('/api/sector_ranking?refresh=1').catch(function(){});
    fetch('/api/sniper_data?refresh=1')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            // 清除客户端缓存，确保 loadSniper 不走 stale cache
            delete _tabCache['/api/sniper_data'];
            loadSniper();
        })
        .catch(function(e) {
            console.error('精准狙击刷新失败:', e);
            showToast('刷新失败: ' + e.message, 'error');
        })
        .finally(function() {
            if (icon) icon.classList.remove('spinning');
        });
}

// 精准狙击 —— 自动刷新（3分钟）
var _sniperAutoRefreshActive = false;
var _sniperAutoRefreshCountdown = null;
var _sniperAutoRefreshRemaining = 0;

function toggleSniperAutoRefresh() {
    var btn = document.getElementById('sniperAutoRefreshBtn');
    if (!btn) return;

    if (_sniperAutoRefreshActive) {
        clearInterval(_sniperAutoRefreshCountdown);
        _sniperAutoRefreshActive = false;
        _sniperAutoRefreshCountdown = null;
        btn.innerHTML = '\u23f1 \u81ea\u52a8\u5237\u65b0 3\u5206\u949f';
        btn.classList.remove('active');
        showToast('\u5df2\u505c\u6b62\u81ea\u52a8\u5237\u65b0', 'info');
        return;
    }

    // Check A-stock trading hours (Beijing time 9:25 ~ 15:00)
    var now = new Date();
    var beijingHour = (now.getUTCHours() + 8) % 24;
    var beijingMin = now.getUTCMinutes();
    var totalMin = beijingHour * 60 + beijingMin;
    if (totalMin < 565 || totalMin >= 900) {
        showToast('\u23f0 \u975e\u4ea4\u6613\u65f6\u6bb5 (9:25~15:00)\uff0c\u81ea\u52a8\u5237\u65b0\u4e0d\u53ef\u7528', 'warning');
        return;
    }

    _sniperAutoRefreshActive = true;
    _sniperAutoRefreshRemaining = 180;
    btn.classList.add('active');

    function updateBtn() {
        var m = Math.floor(_sniperAutoRefreshRemaining / 60);
        var s = _sniperAutoRefreshRemaining % 60;
        btn.innerHTML = '<span class="rt-pulse-dot"></span> \u81ea\u52a8\u5237\u65b0 (' + m + ':' + (s < 10 ? '0' : '') + s + ')';
    }
    updateBtn();

    _sniperAutoRefreshCountdown = setInterval(function() {
        _sniperAutoRefreshRemaining--;
        if (_sniperAutoRefreshRemaining <= 0) {
            var now = new Date();
            var h = (now.getUTCHours() + 8) % 24;
            var m = now.getUTCMinutes();
            var total = h * 60 + m;
            if (total < 565 || total >= 900) {
                clearInterval(_sniperAutoRefreshCountdown);
                _sniperAutoRefreshActive = false;
                _sniperAutoRefreshCountdown = null;
                btn.innerHTML = '\u23f1 \u81ea\u52a8\u5237\u65b0 3\u5206\u949f';
                btn.classList.remove('active');
                showToast('\u23f0 \u5df2\u8fc7\u4ea4\u6613\u65f6\u6bb5\uff0c\u81ea\u52a8\u5237\u65b0\u5df2\u505c\u6b62', 'info');
                return;
            }
            _sniperAutoRefreshRemaining = 180;
            manualRefreshSniper();
        }
        updateBtn();
    }, 1000);
}

// 精准狙击 —— 题材走势切换
function toggleTagTrend(tag) {
    var section = document.getElementById('sniperTrendSection');
    var body = document.getElementById('sniperTrendBody');
    var label = document.getElementById('sniperTrendLabel');
    var cardsContainer = document.getElementById('sniperTrendCards');
    if (!section || !body || !label || !cardsContainer) return;

    // 点击同一个标签则折叠
    if (section.getAttribute('data-active-tag') === tag && section.style.display !== 'none') {
        section.style.display = 'none';
        section.removeAttribute('data-active-tag');
        return;
    }

    var stocks = window._sniperTrendStocks ? window._sniperTrendStocks[tag] : null;
    if (!stocks || stocks.length === 0) return;

    label.textContent = '\u25b3 ' + tag + ' \u2014 ' + stocks.length + '\u53ea\u80a1\u7968';
    section.setAttribute('data-active-tag', tag);

    var html = '';
    var cells = [];
    stocks.forEach(function(s) {
        if (!s.code) return;
        var kurl = sinaKlineImg(s.code);
        var murl = sinaMinImg(s.code);
        var concepts = s.concepts || '';
        cells.push('<div class="concept-kline-cell" onclick="showEnlargedCardDetail(\\x27' + s.code + '\\x27)" style="cursor:pointer;">' +
            '<div class="sk-header"><span class="sk-name">' + _kplEsc(s.name) + '</span>' +
            _watchStarHtml(s.code, s.name, _watchGetCategory(s.code)) +
            '<span class="sk-code">' + s.code + '</span>' +
            (concepts ? '<span class="sk-concepts">' + _kplEsc(concepts) + '</span>' : '') +
            '</div>' +
            '<img class="kline-img" src="' + kurl + '" onerror="retryImg(this)">' +
            '<img class="kline-img min" src="' + murl + '" onerror="retryImg(this)">' +
            '</div>');
    });
    // 4列网格
    for (var i = 0; i < cells.length; i += 4) {
        html += '<div class="concept-kline-grid">' + cells.slice(i, i + 4).join('') + '</div>';
    }

    cardsContainer.innerHTML = html;
    body.style.display = '';
    section.style.display = 'block';

    // 滚动到走势区域
    setTimeout(function() {
        section.scrollIntoView({behavior: 'smooth', block: 'start'});
    }, 150);
}

function closeTagTrend() {
    var section = document.getElementById('sniperTrendSection');
    if (section) {
        section.style.display = 'none';
        section.removeAttribute('data-active-tag');
    }
}

function toggleSniperDate(el) {
    var wasCollapsed = el.classList.contains('collapsed');
    el.classList.toggle('collapsed');
    var body = el.nextElementSibling;
    if (body) {
        if (wasCollapsed) {
            body.classList.remove('collapsed');
            body.style.display = '';
        } else {
            body.classList.add('collapsed');
            body.style.display = 'none';
        }
    }
    if (wasCollapsed) {
        setTimeout(function() { loadSniperCardDetails(); }, 150);
    }
}

function toggleSniperTag(el) {
    var wasCollapsed = el.classList.contains('collapsed');
    el.classList.toggle('collapsed');
    var body = el.nextElementSibling;
    if (body) {
        if (wasCollapsed) {
            body.classList.remove('collapsed');
            body.style.display = '';
        } else {
            body.classList.add('collapsed');
            body.style.display = 'none';
        }
    }
    if (wasCollapsed) {
        setTimeout(function() { loadSniperCardDetails(); }, 150);
    }
}

function loadSniperCardDetails() {
    if (_npDetailLoading) return;
    var codes = [];
    document.querySelectorAll('#sn-results .np-detail-placeholder').forEach(function(ph) {
        var p = ph.parentElement;
        while (p) {
            if (p.classList && (p.classList.contains('sniper-tag-body') || p.classList.contains('np-cat-body'))) {
                if (p.classList.contains('collapsed')) return;
            }
            p = p.parentElement;
        }
        var c = ph.getAttribute('data-np-code');
        if (c && codes.indexOf(c) === -1) codes.push(c);
    });
    if (codes.length === 0) return;
    _npDetailLoading = true;
    fetch('/api/stock_detail_batch?codes=' + codes.join(','))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            for (var code in data) { _npDetailData[code] = data[code]; }
            document.querySelectorAll('#sn-results .np-detail-placeholder').forEach(function(ph) {
                var p = ph.parentElement;
                while (p) {
                    if (p.classList && (p.classList.contains('sniper-tag-body') || p.classList.contains('np-cat-body'))) {
                        if (p.classList.contains('collapsed')) return;
                    }
                    p = p.parentElement;
                }
                var c = ph.getAttribute('data-np-code');
                if (_npDetailData[c] && _npDetailData[c].limit_rows) {
                    ph.innerHTML = _renderCardDetailContent(c, _npDetailData[c], null, '', '');
                    ph.removeAttribute('data-np-code');
                }
            });
            _npDetailLoading = false;
            setTimeout(function() { loadSniperCardDetails(); }, 50);
        })
        .catch(function() { _npDetailLoading = false; setTimeout(function() { loadSniperCardDetails(); }, 50); });
}

// ========== 创业板/科创板套利 ==========
function loadGemArbitrage(stockCode) {
    var container = document.getElementById('gemArbitrageContainer');
    if (!container) return;
    container.innerHTML = '<div class="loading" style="padding:8px;">查询创业板/科创板套利机会...</div>';

    fetch('/api/gem_arbitrage?stock=' + stockCode + '&max_lag=2')
        .then(function(r) { return r.json(); }).then(function(data) {
        if (data.error) {
            container.innerHTML = '<div style="color:#e94560;padding:8px;font-size:0.85em;">' + data.error + '</div>';
            return;
        }
        if (!data.pairs || data.pairs.length === 0) {
            container.innerHTML = '<div style="color:#888;padding:8px;font-size:0.85em;">未发现创业板/科创板套利机会</div>';
            return;
        }

        // Group by concept
        var grouped = {};
        data.pairs.forEach(function(p) {
            var c = p.concept || '未知';
            if (!grouped[c]) grouped[c] = [];
            // Dedup by gem_stock+date within concept group
            var exists = grouped[c].some(function(x) { return x.gem_stock === p.gem_stock && x.zt_date === p.zt_date; });
            if (!exists) grouped[c].push(p);
        });
        var conceptNames = Object.keys(grouped).sort(function(a, b) { return grouped[b].length - grouped[a].length; });

        var html = '<div style="margin-top:10px;padding:12px;background:#1a1a2e;border-radius:10px;border:1px solid #ff9800;">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
        html += '<strong style="color:#ff9800;">创业板/科创板套利 (' + data.stock_name + ', 共' + data.total_pairs + '次联动)</strong>';
        html += '</div>';

        // Concept filter tabs
        html += '<div class="concept-tabs" style="margin-bottom:10px;" id="arbConceptTabs">';
        html += '<span class="concept-tab active" data-arb-concept="">全部 (' + data.total_pairs + ')</span>';
        conceptNames.forEach(function(c) {
            html += '<span class="concept-tab" data-arb-concept="' + c.replace(/"/g, '') + '">' + c + ' (' + grouped[c].length + ')</span>';
        });
        html += '</div>';

        // Store data for filtering
        window._arbData = data;
        window._arbGrouped = grouped;
        window._arbConceptNames = conceptNames;
        window._arbContainer = container;
        window._arbHtmlTemplate = html;
        container.innerHTML = html + '<div id="arbTablesContainer"></div>';
        window._arbSelectedConcept = null;
        // Event delegation for concept tab clicks
        var arbTabs = document.getElementById('arbConceptTabs');
        if (arbTabs && !arbTabs._hasListener) {
            arbTabs._hasListener = true;
            arbTabs.addEventListener('click', function(e) {
                var tab = e.target.closest('.concept-tab[data-arb-concept]');
                if (tab) {
                    window._arbSelectedConcept = tab.getAttribute('data-arb-concept') || null;
                    renderGemArbitrageContent();
                }
            });
        }
        renderGemArbitrageContent();
    }).catch(function(e) {
        container.innerHTML = '<div style="color:#e94560;padding:8px;font-size:0.85em;">查询失败: ' + e.message + '</div>';
    });
}

function renderGemArbitrageContent() {
    var container = window._arbContainer;
    if (!container) return;
    var grouped = window._arbGrouped || {};
    var selectedConcept = window._arbSelectedConcept;
    var conceptNames = window._arbConceptNames || [];

    // Update tab active states
    var tabs = container.querySelectorAll('.concept-tab[data-arb-concept]');
    tabs.forEach(function(t) {
        var tc = t.getAttribute('data-arb-concept') || '';
        if (tc === (selectedConcept || '')) {
            t.classList.add('active');
        } else {
            t.classList.remove('active');
        }
    });

    var conceptsToShow = selectedConcept ? [selectedConcept] : conceptNames;
    var tablesHtml = '';
    var totalPairs = 0;

    conceptsToShow.forEach(function(concept) {
        var pairs = grouped[concept] || [];
        if (pairs.length === 0) return;

        tablesHtml += '<div style="margin-top:10px;">';
        tablesHtml += '<div class="section-header"><h4 style="color:#ff9800;">' + concept + ' (' + pairs.length + '只)</h4></div>';
        tablesHtml += '<table style="font-size:0.85em;">';
        tablesHtml += '<tr><th>#</th><th>代码</th><th>名称</th><th>板块</th><th>日期</th><th>滞后</th><th>涨幅</th><th>收盘价</th></tr>';

        pairs.forEach(function(p, i) {
            var lagLabel = p.lag === 0 ? '同日' : 'T+' + p.lag;
            var gainCls = p.gain_pct >= 15 ? ' style="color:#ff6b6b;font-weight:bold;"' : (p.gain_pct >= 10 ? ' style="color:#ff9800;font-weight:bold;"' : ' style="color:#81c784;"');
            var boardLabel = p.gem_board === 'gem' ? '创业板' : '科创板';
            var boardCls = p.gem_board === 'gem' ? ' style="color:#f48fb1;"' : ' style="color:#81c784;"';
            tablesHtml += '<tr' + (i % 2 === 0 ? '' : ' style="background:rgba(255,255,255,0.02);"') + '>';
            tablesHtml += '<td style="color:#888;">' + (totalPairs + i + 1) + '</td>';
            tablesHtml += '<td><strong style="color:#00d4ff;">' + p.gem_stock + '</strong></td>';
            tablesHtml += '<td>' + p.gem_name + '</td>';
            tablesHtml += '<td' + boardCls + '>' + boardLabel + '</td>';
            tablesHtml += '<td>' + p.zt_date + '</td>';
            tablesHtml += '<td>' + lagLabel + '</td>';
            tablesHtml += '<td' + gainCls + '>' + p.gain_pct.toFixed(2) + '%</td>';
            tablesHtml += '<td>' + p.close_price.toFixed(2) + '</td>';
            tablesHtml += '</tr>';
        });
        tablesHtml += '</table></div>';
        totalPairs += pairs.length;
    });

    var tablesContainer = document.getElementById('arbTablesContainer');
    if (!tablesContainer) {
        // If container doesn't exist, create it
        var div = document.createElement('div');
        div.id = 'arbTablesContainer';
        container.appendChild(div);
        tablesContainer = div;
    }
    tablesContainer.innerHTML = tablesHtml || '<div style="color:#888;padding:8px;">该概念下无数据</div>';
}

// Enter key
document.getElementById('conceptQueryInput').addEventListener('keypress', function(e) { if (e.key === 'Enter') doConceptSearch(); });
var linkageInput = document.getElementById('linkageStockInput');
if (linkageInput) {
    linkageInput.addEventListener('keypress', function(e) { if (e.key === 'Enter') doLinkageSearch(); });
}

// ===== N字战法 =====
var _npData = null;
var _npCatKeys = ['tld', '0-2', '2-5', '5-8', '8-10', '10+'];
var _npCatLabels = {'tld': '屠龙刀战法', '0-2': '0~2%', '2-5': '2~5%', '5-8': '5~8%', '8-10': '8~10%', '10+': '10%+'};
var _boardSubLabels = {main_board: '主板', gem_star: '创业板/科创板'};
var _boardSubKeys = ['main_board', 'gem_star'];
var _npGridCols = 4;
var _sniperGridCols = 4;
var _npObserver = null;
var _ztWindowData = null;  // cached zt_window data
var _npDetailData = {};
var _npDetailLoading = false;
var _screenerData = null;
var _npFilterKeyword = '';
// 检查元素是否在可见（未折叠）分区内
function _isNpInVisibleSection(el) {
    var p = el.parentElement;
    while (p) {
        if (p.classList && (p.classList.contains('np-cat-body') || p.classList.contains('np-board-body'))) {
            if (p.classList.contains('collapsed')) return false;
        }
        p = p.parentElement;
    }
    return true;
}
function loadNpCardDetails(forceAll) {
    if (_npDetailLoading) return;
    // 当 forceAll 为 true 时，忽略折叠状态加载所有卡片（用于过滤时涨停理由匹配）
    var visibleOnly = forceAll ? function() { return true; } : function(el) { return _isNpInVisibleSection(el); };
    // 先渲染已有缓存数据的卡片（无需API请求）
    document.querySelectorAll('[data-np-detail]').forEach(function(el) {
        if (!visibleOnly(el)) return;
        var c = el.getAttribute('data-np-detail');
        if (c && _npDetailData[c]) {
            var alertDate = el.getAttribute('data-alert-date') || '';
            var alertPct = parseFloat(el.getAttribute('data-alert-pct')) || 0;
            var alertInfo = alertDate ? {date: alertDate, pct: alertPct} : null;
            el.innerHTML = _renderCardDetailContent(c, _npDetailData[c], alertInfo, '', el.getAttribute('data-concepts'));
            el.removeAttribute('data-np-detail');
            el.removeAttribute('data-alert-date');
            el.removeAttribute('data-alert-pct');
        }
    });
    var codes = [];
    document.querySelectorAll('[data-np-detail]').forEach(function(el) {
        if (!visibleOnly(el)) return;
        var c = el.getAttribute('data-np-detail');
        if (c && !_npDetailData[c] && codes.indexOf(c) === -1) codes.push(c);
    });
    if (codes.length === 0) return;
    _npDetailLoading = true;
    fetch('/api/stock_detail_batch?codes=' + codes.join(','))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            for (var code in data) { _npDetailData[code] = data[code]; }
            document.querySelectorAll('[data-np-detail]').forEach(function(el) {
                if (!visibleOnly(el)) return;
                var c = el.getAttribute('data-np-detail');
                if (_npDetailData[c]) {
                    var alertDate = el.getAttribute('data-alert-date') || '';
                    var alertPct = parseFloat(el.getAttribute('data-alert-pct')) || 0;
                    var alertInfo = alertDate ? {date: alertDate, pct: alertPct} : null;
                    el.innerHTML = _renderCardDetailContent(c, _npDetailData[c], alertInfo, '', el.getAttribute('data-concepts'));
                    el.removeAttribute('data-np-detail');
                    el.removeAttribute('data-alert-date');
                    el.removeAttribute('data-alert-pct');
                }
            });
            _npDetailLoading = false;
            // 当过滤激活时，数据加载后重新过滤
            if (_npFilterKeyword) {
                filterNPattern();
            } else {
                // 继续处理剩余未加载的卡片（异步添加的卡片可能被上一轮跳过）
                setTimeout(function() { loadNpCardDetails(forceAll); }, 50);
            }
        })
        .catch(function() { _npDetailLoading = false; if (!_npFilterKeyword) setTimeout(function() { loadNpCardDetails(forceAll); }, 50); });
}

// Sidebar nav items (excluding alert — added separately)
var _screenerSidebarKeys = ['sc1', 'sc2', 'sc3', 'sc4', 'sc5'];
var _screenerSidebarLabels = {
    'sc1': '主板3连板+',
    'sc2': '主板2连板',
    'sc3': '主板涨停（近15交易日，无连板）',
    'sc4': '创业板/科创板涨停',
    'sc5': '创业板/科创板异动（10%+）'
};
var _npSidebarItems = [
    {key: 'sc1', label: '主板3连板+'},
    {key: 'sc2', label: '主板2连板'},
    {key: 'sc3', label: '主板涨停（近15交易日，无连板）'},
    {key: 'sc4', label: '创业板/科创板涨停'},
    {key: 'sc5', label: '创业板/科创板异动（10%+）'},
    {key: 'tld', label: '屠龙刀战法'},
    {key: '0-2', label: '0~2%'},
    {key: '2-5', label: '2~5%'},
    {key: '5-8', label: '5~8%'},
    {key: '8-10', label: '8~10%'},
    {key: '10+', label: '10%+'},
    {key: 'yang', label: '阳线回调'},
    {key: 'three_yin', label: '三连阴回调'}
];

function loadNPattern() {
    var container = document.getElementById('npatternContainer');
    container.innerHTML = '<div class="loading">分析N字战法候选股票中...</div>';

    Promise.all([
        _cachedFetch('/api/n_pattern'),
        _cachedFetch('/api/lianban_screener')
    ]).then(function(results) {
        var data = results[0];
        var screener = results[1] || {};
        if (!data || data.error || !data.categories) {
            container.innerHTML = '<div class="result"><div class="error">分析失败</div></div>';
            return;
        }

        _npData = data;
        _screenerData = screener;

        // --- Summary bar ---
        var html = '<div class="result" id="np-nav-top">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;">';
        html += '<h3 style="color:#ff6b6b;margin:0;">N字战法·涨停回调分析</h3>';
        html += '<span style="color:#888;font-size:0.85em;">共' + data.summary.total_stocks + '只股票 | 候选' + data.summary.candidate_count + '只</span>';
        html += '</div>';

        // Strategy description
        html += '<p style="color:#888;font-size:0.85em;margin-bottom:12px;">策略：涨停连板后回调企稳，识别二波主升机会。按回调深度分类，⭐标记为高连板+无大跌异动标的</p>';

        // Alert badges (above wrapper)
        if (data.alerts) {
            var alertBar = [];
            if (data.alerts.zha_ban && data.alerts.zha_ban.length > 0) alertBar.push('炸板异动 ' + data.alerts.zha_ban.length + '只');
            if (data.alerts.gem_alert && data.alerts.gem_alert.length > 0) alertBar.push('创业板/科创板异动 ' + data.alerts.gem_alert.length + '只');
            if (alertBar.length > 0) {
                html += '<div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">';
                alertBar.forEach(function(t) { html += '<span class="badge badge-pool">' + t + '</span>'; });
                html += '</div>';
            }
        }

        // --- Sidebar + Main content wrapper ---
        html += '<div class="np-wrapper">';

        // Sidebar nav with board sub-items
        html += '<nav class="np-sidebar" id="npSidebar">';
        _npSidebarItems.forEach(function(item) {
            var targetId = item.key === 'alert' ? 'np-section-alert' : 'np-section-' + item.key;
            html += '<a class="np-sidebar-item" data-np-section="' + targetId + '" onclick="scrollToNpSection(\\x27' + targetId + '\\x27)">' + item.label + '</a>';
            // Board sub-items for main categories (tld, 0-2, 2-5, 5-8, 8-10, 10+)
            if (_npCatKeys.indexOf(item.key) !== -1) {
                _boardSubKeys.forEach(function(bk) {
                    var subTarget = 'np-section-' + item.key + '-' + bk;
                    html += '<a class="np-sidebar-subitem" data-np-section="' + subTarget + '" onclick="scrollToNpSection(\\x27' + subTarget + '\\x27)">' + _boardSubLabels[bk] + '</a>';
                });
            }
        });
        html += '</nav>';

        // Main content (built by helper so filter can re-render)
        html += '<div class="np-main-content" id="np-main-content">';
        html += renderNpFilterBar();
        html += '<div id="np-cat-results">';
        html += renderNpResults(data, screener);
        html += '</div>';
        html += '</div>'; // .np-main-content

        html += '</div>'; // .np-wrapper

        // Update time
        if (data.update_time) {
            html += '<div class="np-update-time">更新时间: ' + data.update_time + '</div>';
        }

        html += '</div>'; // .result
        container.innerHTML = html;

        // Apply current column count
        document.querySelectorAll('.np-card-grid').forEach(function(g) {
            g.style.setProperty('--np-cols', _npGridCols);
        });

        // Render all kline canvases
        setTimeout(function() {
            _npCatKeys.forEach(function(ck) {
                var cat = data.categories[ck];
                if (!cat) return;
                var allStocks = (cat.main_board || []).concat(cat.gem || []).concat(cat.star || []).concat(cat.bj || []);
                allStocks.forEach(function(stock) {
                    renderNpKline('npk_' + stock.code, stock.klines);
                });
            });
            // Render alert klines
            if (data.alerts) {
                (data.alerts.zha_ban || []).concat(data.alerts.gem_alert || []).forEach(function(s) {
                    if (s.klines) renderNpKline('npk_' + s.code + '_alert', s.klines);
                });
            }
            // Render new pattern klines
            (data.yang_pattern || []).forEach(function(s) { renderNpKline('yang_' + s.code, s.klines); });
            (data.three_yin_pattern || []).forEach(function(s) { renderNpKline('three_yin_' + s.code, s.klines); });
            // Render hot concept buttons
            renderNpHotConceptButtons();
            // Init sidebar IntersectionObserver
            initNpSidebar();

            setTimeout(function() { loadNpCardDetails(); }, 500);
        }, 150);

    }).catch(function(e) {
        container.innerHTML = '<div class="result"><div class="error">加载失败: ' + e.message + '</div></div>';
    });
}

// Render the filter bar (separate from results so filter doesn't clear itself)
function renderNpFilterBar() {
    var html = '<div class="np-filter-bar">';
    html += '<span class="fl">概念或涨停理由</span>';
    html += '<input class="np-filter-input" id="npFilterConcept" placeholder="多概念用逗号分隔" oninput="filterNPattern()">';
    html += '<label class="np-filter-cb"><input type="checkbox" id="npFilterNW" onchange="filterNPattern()"> N+W</label>';
    html += '<label class="np-filter-cb"><input type="checkbox" id="npFilterTldSb" onchange="filterNPattern()"> 首板屠龙</label>';
    html += '<label class="np-filter-cb"><input type="checkbox" id="npFilterTld" onchange="filterNPattern()"> 屠龙刀</label>';
    html += '<span class="np-grid-tog">';
    html += '<button' + (_npGridCols === 2 ? ' class="active"' : '') + ' onclick="setNpGridCols(2)" data-cols="2">2列</button>';
    html += '<button' + (_npGridCols === 4 ? ' class="active"' : '') + ' onclick="setNpGridCols(4)" data-cols="4">4列</button>';
    html += '<button' + (_npGridCols === 6 ? ' class="active"' : '') + ' onclick="setNpGridCols(6)" data-cols="6">6列</button>';
    html += '</span>';
    html += '</div>';
    // Hot concept quick-select container
    html += '<div id="npHotConceptBar" style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:12px;"></div>';
    return html;
}

// Render the results area (categories + screener + alerts)
function renderNpResults(data, screener) {
    data = data || _npData;
    if (!data) return '';
    screener = screener || _screenerData || {};

    var html = '';

    // Count totals (for display)
    var allCount = 0;
    _npCatKeys.forEach(function(ck) {
        var cat = data.categories[ck];
        if (!cat) return;
        allCount += (cat.main_board || []).length + (cat.gem || []).length + (cat.star || []).length + (cat.bj || []).length;
    });
    html += '<div class="np-filter-count" id="npFilterCount" style="color:#666;font-size:0.82em;margin-bottom:10px;">共 ' + allCount + ' 只</div>';

    // Screener sections (before F4 categories)
    _screenerSidebarKeys.forEach(function(sk) {
        html += renderScreenerCategory(screener[sk], sk);
    });

    // Categories
    _npCatKeys.forEach(function(ck) {
        html += renderNpCategory(data.categories[ck], ck);
    });

    // 阳线回调 section
    html += renderNpSimplePatternSection(data.yang_pattern, 'yang', '阳线回调', '📈', '涨停后阴线回调(至少1根) + 最后一根阳线企稳信号');

    // 三连阴回调 section
    html += renderNpSimplePatternSection(data.three_yin_pattern, 'three_yin', '三连阴回调', '📉', '近15日有涨停 + 连续3日收阴线(close < open)');

    return html;
}

// Render a screener category section (collapsible, cards with data-np-detail)
var _screenerIcons = {'sc1': '\U0001F3C6', 'sc2': '\U0001F4CA', 'sc3': '\U0001F4C9', 'sc4': '\U0001F7E2', 'sc5': '\U0001F525'};
function renderScreenerCategory(stocks, key) {
    if (!stocks || stocks.length === 0) return '';
    var label = _screenerSidebarLabels[key] || key;
    var icon = _screenerIcons[key] || '\U0001F4CA';
    var html = '<div class="np-section" id="np-section-' + key + '">';
    html += '<div class="np-cat-header collapsed" onclick="toggleNpCategory(this)" data-np-cat="' + key + '">';
    html += '<span class="cat-icon">' + icon + '</span>';
    html += '<span class="cat-name">' + label + '</span>';
    html += '<span class="cat-count">' + stocks.length + '\u53ea</span>';
    html += '<span class="cat-arrow">\u25bc</span>';
    html += '</div>';
    html += '<div class="np-cat-body collapsed" id="np-cat-body-' + key + '">';
    html += '<div class="np-card-grid">';
    stocks.forEach(function(s) {
        var code = s.code || '';
        var name = s.name || '';
        var lianban = s.lianban || '';
        var badgeLabel = lianban ? lianban + '\u8fde\u677f' : '';
        html += '<div class="np-card" data-code="' + code + '" data-name="' + name + '">';
        html += '<div class="np-card-header">';
        html += '<div>';
        html += '<span class="np-card-code" data-code="' + code + '" data-name="' + name + '">' + code + '</span>';
        html += '<span class="np-card-name">' + highlightText(name, _npFilterKeyword) + '</span>';
        html += _watchStarHtml(code, name, _watchGetCategory(code));
        html += '</div>';
        html += '<div>' + (badgeLabel ? '<span class="np-card-badge lianban">' + badgeLabel + '</span>' : '') + '<button class="np-enlarge-btn" onclick="event.stopPropagation();showEnlargedCardDetail(\\x27' + code + '\\x27)" title="\u653e\u5927\u5361\u7247">\u2b36</button></div>';
        html += '</div>';
        html += '<div data-np-detail="' + code + '" data-concepts=\\x27' + JSON.stringify(s.concepts || []) + '\\x27><div class="empty" style="padding:8px;">\u52a0\u8f7d\u4e2d...</div></div>';
        html += '</div>';
    });
    html += '</div></div></div>';
    return html;
}

// Render alert section using np-card style (with collapsible header + show-all)
function renderNpAlertSection(data) {
    if (!data.alerts || (data.alerts.zha_ban.length === 0 && data.alerts.gem_alert.length === 0)) return '';

    var totalAlert = data.alerts.zha_ban.length + data.alerts.gem_alert.length;
    var INIT_SHOW = 10;

    var html = '<div class="np-section" id="np-section-alert">';
    html += '<div class="np-cat-header collapsed" onclick="toggleNpCategory(this)" data-np-cat="alert">';
    html += '<span class="cat-icon">⚠</span>';
    html += '<span class="cat-name">额外关注</span>';
    html += '<span class="cat-count">' + totalAlert + '只</span>';
    html += '<span class="cat-arrow">▼</span>';
    html += '</div>';
    html += '<div class="np-cat-body collapsed" id="np-cat-body-alert">';

    // Split zha_ban by board
    var zbByBoard = { 'main': [], 'gem': [], 'star': [] };
    (data.alerts.zha_ban || []).forEach(function(s) {
        var b = s.board || 'main';
        if (zbByBoard[b]) zbByBoard[b].push(s); else zbByBoard['main'].push(s);
    });
    // Split gem_alert by board
    var gaByBoard = { 'gem': [], 'star': [] };
    (data.alerts.gem_alert || []).forEach(function(s) {
        var b = s.board || 'gem';
        if (gaByBoard[b]) gaByBoard[b].push(s); else gaByBoard['gem'].push(s);
    });

    var boardDefs = [
        {key: 'main', label: '主板', hasZb: zbByBoard['main'].length > 0, hasGa: false},
        {key: 'gem', label: '创业板', hasZb: zbByBoard['gem'].length > 0, hasGa: gaByBoard['gem'].length > 0},
        {key: 'star', label: '科创板', hasZb: zbByBoard['star'].length > 0, hasGa: gaByBoard['star'].length > 0},
    ];

    boardDefs.forEach(function(bd) {
        if (!bd.hasZb && !bd.hasGa) return;
        html += '<div class="np-board-divider">━━━ ' + bd.label + ' ━━━</div>';
        if (bd.hasZb) {
            html += _renderAlertBoard(zbByBoard[bd.key], 'zha_ban-' + bd.key, bd.label + ' · 炸板异动', bd.key, INIT_SHOW);
        }
        if (bd.hasGa) {
            html += _renderAlertBoard(gaByBoard[bd.key], 'gem_alert-' + bd.key, bd.label + ' · 涨幅异动', bd.key, INIT_SHOW);
        }
    });

    html += '<div class="np-back-top" onclick="scrollToNpSection(\\x27np-nav-top\\x27)">↑ 回到顶部</div>';
    html += '</div></div>'; // .np-cat-body, .np-section
    return html;
}

function _renderAlertBoard(stocks, typeKey, boardLabel, boardCls, initShow) {
    if (!stocks || stocks.length === 0) return '';
    // typeKey can be "zha_ban-main" or "gem_alert-gem" — extract base type for card rendering
    var cardType = typeKey.split('-')[0];
    var total = stocks.length;
    var needsToggle = total > initShow;
    var boardId = 'alert-board-' + typeKey;

    var html = '<div class="np-board-section" id="' + boardId + '">';
    html += '<div class="np-board-header ' + boardCls + '">' + boardLabel + ' (' + total + '只)</div>';
    // First batch
    html += '<div class="np-card-grid" id="alert-grid-' + typeKey + '">';
    for (var i = 0; i < Math.min(initShow, total); i++) {
        html += renderAlertNpCard(stocks[i], cardType);
    }
    html += '</div>';
    // Hidden extras
    if (needsToggle) {
        html += '<div class="np-card-grid" id="alert-grid-extra-' + typeKey + '" style="display:none;">';
        for (var i = initShow; i < total; i++) {
            html += renderAlertNpCard(stocks[i], cardType);
        }
        html += '</div>';
        html += '<div class="np-show-toggle" style="text-align:center;margin:8px 0;">';
        html += '<button class="arb-btn" style="padding:6px 18px;font-size:0.85em;" onclick="toggleAlertBoard(\\x27' + typeKey + '\\x27)" id="alert-btn-' + typeKey + '">显示全部 (' + total + '只)</button>';
        html += '</div>';
    }
    html += '</div>';
    return html;
}

// Toggle show-all for alert board section
function toggleAlertBoard(typeKey) {
    var extraGrid = document.getElementById('alert-grid-extra-' + typeKey);
    var btn = document.getElementById('alert-btn-' + typeKey);
    if (!extraGrid || !btn) return;
    var isHidden = extraGrid.style.display === 'none';
    extraGrid.style.display = isHidden ? '' : 'none';
    // Get total from button label
    var match = btn.textContent.match(/\\d+/);
    var total = match ? parseInt(match[0]) : 0;
    btn.textContent = isHidden ? '收起' : '显示全部 (' + total + '只)';

    // Load card details for newly visible cards
    if (isHidden) {
        _npDetailLoading = false;
        setTimeout(function() { loadNpCardDetails(); }, 100);
        initNpSidebar();
    }
}

// Render a single alert stock as np-card format
function renderAlertNpCard(s, type) {
    var borderCls = type === 'zha_ban' ? ' tld-card' : '';
    var html = '<div class="np-card' + borderCls + '" data-code="' + s.code + '" data-name="' + s.name + '">';
    html += '<div class="np-card-header">';
    html += '<div>';
    html += '<span class="np-card-code" data-code="' + s.code + '" data-name="' + s.name + '">' + s.code + '</span>';
    html += '<span class="np-card-name">' + s.name + '</span>' + _watchStarHtml(s.code, s.name, _watchGetCategory(s.code));
    html += '</div>';
    if (type === 'zha_ban') {
        html += '<span class="np-card-badge alert">炸板' + s.zb_count + '次</span><button class="np-enlarge-btn" onclick="event.stopPropagation();showEnlargedCardDetail(\\x27' + s.code + '\\x27)" title="放大卡片">⛶</button></div>';
    } else {
        var boardLabel = s.board === 'gem' ? '创业板' : '科创板';
        var boardColor = s.board === 'gem' ? 'rgba(244,143,177,0.15);color:#f48fb1' : 'rgba(129,199,132,0.15);color:#81c784';
        html += '<span class="np-card-badge lianban" style="background:' + boardColor + '">' + boardLabel + '</span><button class="np-enlarge-btn" onclick="event.stopPropagation();showEnlargedCardDetail(\\x27' + s.code + '\\x27)" title="放大卡片">⛶</button></div>';
    }

    // == OLD CONTENT (keep for reversion) ==
    // // Metrics
    // html += '<div class="np-metrics">';
    // if (type === 'zha_ban') {
    //     html += '<div class="np-metric"><div class="label">涨停日</div><div class="value">' + (s.last_zt_date || '-') + '</div></div>';
    //     html += '<div class="np-metric"><div class="label">回调</div><div class="value positive">' + (s.current_pullback_pct != null ? s.current_pullback_pct.toFixed(1) + '%' : '-') + '</div></div>';
    //     html += '<div class="np-metric"><div class="label">封板价</div><div class="value">' + (s.top_high || '-') + '</div></div>';
    //     html += '<div class="np-metric"><div class="label">基准</div><div class="value">' + (s.base_price != null ? s.base_price.toFixed(2) : '-') + '</div></div>';
    // } else {
    //     html += '<div class="np-metric"><div class="label">涨停日</div><div class="value">' + (s.last_zt_date || '-') + '</div></div>';
    //     html += '<div class="np-metric"><div class="label">连板</div><div class="value">' + (s.lianban_count || 0) + '板</div></div>';
    //     html += '<div class="np-metric"><div class="label">回调</div><div class="value positive">' + (s.current_pullback_pct != null ? s.current_pullback_pct.toFixed(1) + '%' : '-') + '</div></div>';
    //     html += '<div class="np-metric"><div class="label">' + (s.board === 'gem' ? '创业板' : '科创板') + '</div><div class="value" style="color:#888;">异动</div></div>';
    // }
    // html += '</div>';
    // // Pullback bar
    // if (s.current_pullback_pct != null) {
    //     var pbPct = Math.min(s.current_pullback_pct / 15 * 100, 100);
    //     var fc = 'normal';
    //     if (s.current_pullback_pct >= 8) fc = 'severe';
    //     else if (s.current_pullback_pct >= 5) fc = 'deep';
    //     else if (s.current_pullback_pct >= 2) fc = 'normal';
    //     html += '<div class="np-pullback-bar"><div class="np-pullback-fill ' + fc + '" style="width:' + pbPct + '%"></div></div>';
    // }
    // // K-line canvas
    // var canvasId = 'npk_' + s.code + '_alert';
    // html += '<div class="np-kline-container">';
    // html += '<canvas id="' + canvasId + '" height="200"></canvas>';
    // html += '</div>';
    // html += '<button class="np-kline-toggle" data-kline-id="' + canvasId + '">收起K线</button>';
    // var latestDate = getKlineLatestDate(s.klines);
    // if (latestDate) html += '<div class="np-kline-latest">最新: <span>' + latestDate + '</span></div>';
    // == END OLD CONTENT ==

    html += '<div data-np-detail="' + s.code + '" data-concepts=\\x27' + JSON.stringify(s.concepts || []) + '\\x27><div class="empty" style="padding:8px;">加载中...</div></div>';

    html += '</div>';
    return html;
}

// 按板块分组（主板/创业板科创板/其他），9开头归入其他
function _npSplitByBoard(stocks) {
    var boards = {main_board: [], gem_star: [], other: []};
    for (var i = 0; i < stocks.length; i++) {
        var s = stocks[i];
        var code = (s.ts_code || s.code || '').split('.')[0];
        if (code.startsWith('00') || code.startsWith('60')) {
            boards.main_board.push(s);
        } else if (code.startsWith('30') || code.startsWith('68')) {
            boards.gem_star.push(s);
        } else {
            boards.other.push(s);
        }
    }
    return boards;
}

// 异动跟踪：展开板块时懒加载卡片详情
function toggleAlertmonBoard(el) {
    el.classList.toggle('collapsed');
    var body = el.nextElementSibling;
    if (body) body.classList.toggle('collapsed');

    // 懒加载：只展开时才加载
    if (body && !body.classList.contains('collapsed')) {
        setTimeout(function() {
            var newCodes = [];
            body.querySelectorAll('.am-detail-placeholder').forEach(function(ph) {
                var code = ph.getAttribute('data-am-code');
                if (code) {
                    ph.setAttribute('data-np-detail', code);
                    // Restore alert-date/pct attributes for loadNpCardDetails
                    var alertDate = ph.getAttribute('data-alert-date') || '';
                    var alertPct = ph.getAttribute('data-alert-pct') || '0';
                    if (alertDate) ph.setAttribute('data-alert-date', alertDate);
                    if (alertPct) ph.setAttribute('data-alert-pct', alertPct);
                    if (!_npDetailData[code] && newCodes.indexOf(code) === -1) newCodes.push(code);
                }
            });
            if (newCodes.length > 0) {
                _npDetailLoading = false;
            }
            loadNpCardDetails();
        }, 150);
    }
}

function renderNpCategory(cat, catKey) {
    if (!cat) return '';
    // Collect all stocks from all boards
    var allStocks = (cat.main_board || []).concat(cat.gem || []).concat(cat.star || []).concat(cat.bj || []);
    if (allStocks.length === 0) return '';

    // Icon/color for categories
    var catIcons = {'tld': '🔪', '0-2': '🟢', '2-5': '🟡', '5-8': '🟠', '8-10': '🔴', '10+': '⛔'};
    var icon = catIcons[catKey] || '📊';

    var html = '<div class="np-section" id="np-section-' + catKey + '">';
    html += '<div class="np-cat-header collapsed" onclick="toggleNpCategory(this)" data-np-cat="' + catKey + '">';
    html += '<span class="cat-icon">' + icon + '</span>';
    html += '<span class="cat-name">' + cat.name + '</span>';
    html += '<span class="cat-count">' + allStocks.length + '只</span>';
    html += '<span class="cat-arrow">▼</span>';
    html += '</div>';

    html += '<div class="np-cat-body collapsed" id="np-cat-body-' + catKey + '">';

    // Split by board and render board sections
    var boards = _npSplitByBoard(allStocks);
    var boardDefs = [
        {key: 'main_board', label: '主板', cls: 'main'},
        {key: 'gem_star', label: '创业板/科创板', cls: 'gem_star'}
    ];
    boardDefs.forEach(function(board) {
        var bStocks = boards[board.key] || [];
        if (bStocks.length === 0) return;
        var secId = 'np-section-' + catKey + '-' + board.key;

        html += '<div class="np-board-section" id="' + secId + '">';
        html += '<div class="np-board-header collapsible collapsed ' + board.cls + '" onclick="toggleNpBoard(this)" data-np-board="' + secId + '">';
        html += board.label + ' (' + bStocks.length + '\u53ea)';
        html += '<span class="board-arrow">\u25bc</span>';
        html += '</div>';
        html += '<div class="np-board-body collapsed">';
        html += '<div class="np-card-grid">';

        bStocks.forEach(function(s) {
            var starCls = s.is_lianban2plus ? ' star-card' : '';
            var tldCls = s.is_tld_shouban ? ' tld-shouban-card' : (s.is_tld ? ' tld-card' : '');
            var nwCls = s.is_nw_pattern ? ' nw-card' : '';
            html += '<div class="np-card' + starCls + tldCls + nwCls + '">';

            // Header: code, name, badges
            html += '<div class="np-card-header">';
            html += '<div>';
            html += '<span class="np-card-code" data-code="' + s.code + '" data-name="' + s.name + '">' + s.code + '</span>';
            html += '<span class="np-card-name">' + highlightText(s.name, _npFilterKeyword) + '</span>' + _watchStarHtml(s.code, s.name, _watchGetCategory(s.code));
            if (s.is_lianban2plus) html += '<span style="margin-left:4px;color:#ffc107;">\u2b50</span>';
            if (s.is_oscillation) html += '<span style="margin-left:4px;color:#00d4ff;font-size:0.85em;">\u27f3</span>';
            if (s.has_zha_ban) html += '<span style="margin-left:4px;color:#ff9800;font-size:0.85em;">\u26a0</span>';
            if (s.is_tld_shouban) html += '<span class="tld-shouban-badge">\u9996\u677f\u5c60\u9f99</span>';
            else if (s.is_tld) html += '<span class="tld-badge">\u5c60\u9f99\u5200</span>';
            if (s.is_nw_pattern) html += '<span class="nw-badge">N+W\u53cc\u5e95</span>';
            html += '</div>';
            html += '<div><span class="np-card-badge lianban">' + s.lianban_count + '\u8fde\u677f</span><button class="np-enlarge-btn" onclick="event.stopPropagation();showEnlargedCardDetail(\\x27' + s.code + '\\x27)" title="\u653e\u5927\u5361\u7247">\u2b36</button></div>';
            html += '</div>';

            html += '<div class="np-detail-placeholder" data-np-code="' + s.code + '" data-concepts=\\x27' + JSON.stringify(s.concepts || []) + '\\x27><div class="empty" style="padding:8px;">\u52a0\u8f7d\u8be6\u60c5...</div></div>';

            html += '</div>'; // .np-card
        });

        html += '</div></div></div>'; // .np-card-grid, .np-board-body, .np-board-section
    });

    html += '<div class="np-back-top" onclick="scrollToNpSection(\\x27np-nav-top\\x27)">\u2191 \u56de\u5230\u9876\u90e8</div>';
    html += '</div></div>'; // .np-cat-body, .np-section
    return html;
}

// N字战法：展开/收起板块二级目录，展开时懒加载卡片详情
function toggleNpBoard(el) {
    el.classList.toggle('collapsed');
    var body = el.nextElementSibling;
    if (body) body.classList.toggle('collapsed');
    // 展开时加载本板块的卡片详情
    if (body && !body.classList.contains('collapsed')) {
        setTimeout(function() {
            var newCodes = [];
            body.querySelectorAll('.np-detail-placeholder').forEach(function(ph) {
                var code = ph.getAttribute('data-np-code');
                if (code) {
                    ph.setAttribute('data-np-detail', code);
                    if (!_npDetailData[code] && newCodes.indexOf(code) === -1) newCodes.push(code);
                }
            });
            if (newCodes.length > 0) {
                _npDetailLoading = false;
            }
            loadNpCardDetails();
        }, 150);
    }
}

function toggleNpCategory(el) {
    var wasCollapsed = el.classList.contains('collapsed');
    el.classList.toggle('collapsed');
    var body = el.nextElementSibling;
    if (body) {
        if (wasCollapsed) {
            body.classList.remove('collapsed');
            body.style.display = '';
        } else {
            body.classList.add('collapsed');
            body.style.display = 'none';
        }
    }
    // 展开时加载本区卡片详情（选股器/阳线回调/三连阴等无二级board的section）
    // 有二级board的section（N字战法主分类），卡片详情在toggleNpBoard中加载
    if (wasCollapsed) {
        setTimeout(function() { loadNpCardDetails(); }, 150);
    }
}

function toggleNpKline(canvasId) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    var container = canvas.parentElement;
    var btn = container.nextElementSibling;
    if (canvas.style.display === 'none') {
        canvas.style.display = '';
        btn.textContent = '收起K线';
    } else {
        canvas.style.display = 'none';
        btn.textContent = '展开K线';
    }
}

// Scroll to N-section
function scrollToNpSection(sectionId) {
    var el = document.getElementById(sectionId);
    if (el) el.scrollIntoView({behavior: 'smooth', block: 'start'});
}

// Filter N-pattern stocks
function filterNPattern() {
    var conceptVal = (document.getElementById('npFilterConcept').value || '').trim();
    var kw = conceptVal.replace(/,/g, '|');
    _npFilterKeyword = kw;
    var filterNW = document.getElementById('npFilterNW').checked;
    var filterTldSb = document.getElementById('npFilterTldSb').checked;
    var filterTld = document.getElementById('npFilterTld').checked;

    var selectedConcepts = conceptVal ? conceptVal.split(',').map(function(s) { return s.trim(); }).filter(function(s) { return s; }) : [];

    // 当有概念/理由过滤时，确保所有详情数据已加载（用于涨停理由匹配）
    if (selectedConcepts.length > 0 && !_npDetailLoading) {
        var someMissing = false;
        if (_npData) {
            for (var _ck in _npData.categories) {
                var _cat = _npData.categories[_ck];
                if (!_cat) continue;
                var _boards = (_cat.main_board || []).concat(_cat.gem || []).concat(_cat.star || []).concat(_cat.bj || []);
                for (var _bi = 0; _bi < _boards.length; _bi++) {
                    if (!_npDetailData[_boards[_bi].code]) { someMissing = true; break; }
                }
                if (someMissing) break;
            }
        }
        if (someMissing) {
            loadNpCardDetails(true);
        }
    }

    // Check if any filter is active
    var hasFilter = selectedConcepts.length > 0 || filterNW || filterTldSb || filterTld;

    // Deep-clone data for filtered rendering
    var data = _npData;
    if (!data) return;

    // Create a filtered copy of categories
    var filteredData = {categories: {}, alerts: data.alerts, summary: data.summary, update_time: data.update_time};

    var filteredTotal = 0;
    _npCatKeys.forEach(function(ck) {
        var origCat = data.categories[ck];
        if (!origCat || (!origCat.name)) return;

        var newCat = {name: origCat.name};
        var boards = ['main_board', 'gem', 'star', 'bj'];
        boards.forEach(function(bk) {
            var origStocks = origCat[bk] || [];
            var filtered = origStocks;
            if (hasFilter) {
                filtered = origStocks.filter(function(s) {
                    // Concept filter
                    if (selectedConcepts.length > 0) {
                        var matchesConcept = false;
                        (s.concepts || []).forEach(function(c) {
                            selectedConcepts.forEach(function(sc) {
                                if (c.indexOf(sc) !== -1) matchesConcept = true;
                            });
                        });
                        if (!matchesConcept) {
                            // 检查KPL涨停理由（仅当有缓存时）
                            var matchesReason = false;
                            var detail = _npDetailData[s.code];
                            if (detail && detail.kpl_records) {
                                detail.kpl_records.forEach(function(r) {
                                    var allText = (r.concepts || '') + (r.reason_tag || '') + (r.reason_brief || '');
                                    selectedConcepts.forEach(function(sc) {
                                        if (allText.indexOf(sc) !== -1) {
                                            matchesReason = true;
                                        }
                                    });
                                });
                            } else if (detail && detail.limit_rows) {
                                detail.limit_rows.forEach(function(r) {
                                    selectedConcepts.forEach(function(sc) {
                                        if ((r.lu_desc && r.lu_desc.indexOf(sc) !== -1) ||
                                            (r.name && r.name.indexOf(sc) !== -1)) {
                                            matchesReason = true;
                                        }
                                    });
                                });
                            }
                            if (!matchesReason) return false;
                        }
                    }
                    // NW filter
                    if (filterNW && !s.is_nw_pattern) return false;
                    // TLD shouban filter
                    if (filterTldSb && !s.is_tld_shouban) return false;
                    // TLD filter (includes shouban too)
                    if (filterTld && !s.is_tld && !s.is_tld_shouban) return false;
                    return true;
                });
            }
            newCat[bk] = filtered;
            filteredTotal += filtered.length;
        });
        filteredData.categories[ck] = newCat;
    });

    // Update count
    var countEl = document.getElementById('npFilterCount');
    if (countEl) countEl.textContent = (hasFilter ? '过滤后 ' : '共 ') + filteredTotal + ' 只';

    // Filter screener data
    var filteredScreener = {};
    if (selectedConcepts.length > 0 && _screenerData) {
        _screenerSidebarKeys.forEach(function(sk) {
            var orig = _screenerData[sk];
            if (!orig) { filteredScreener[sk] = orig; return; }
            filteredScreener[sk] = orig.filter(function(s) {
                // Concept filter
                var matchesConcept = false;
                (s.concepts || []).forEach(function(c) {
                    selectedConcepts.forEach(function(sc) {
                        if (c.indexOf(sc) !== -1) matchesConcept = true;
                    });
                });
                if (matchesConcept) return true;
                // Reason filter (KPL版)
                var matchesReason = false;
                var detail = _npDetailData[s.code];
                if (detail && detail.kpl_records) {
                    detail.kpl_records.forEach(function(r) {
                        var allText = (r.concepts || '') + (r.reason_tag || '') + (r.reason_brief || '');
                        selectedConcepts.forEach(function(sc) {
                            if (allText.indexOf(sc) !== -1) matchesReason = true;
                        });
                    });
                } else if (detail && detail.limit_rows) {
                    detail.limit_rows.forEach(function(r) {
                        selectedConcepts.forEach(function(sc) {
                            if ((r.lu_desc && r.lu_desc.indexOf(sc) !== -1) ||
                                (r.name && r.name.indexOf(sc) !== -1)) {
                                matchesReason = true;
                            }
                        });
                    });
                }
                return matchesReason;
            });
        });
    } else {
        _screenerSidebarKeys.forEach(function(sk) {
            filteredScreener[sk] = _screenerData[sk];
        });
    }

    // Re-render results area (filter bar stays intact)
    var resultsEl = document.getElementById('np-cat-results');
    if (resultsEl) {
        resultsEl.innerHTML = renderNpResults(filteredData, filteredScreener);
        // Re-render K-lines
        setTimeout(function() {
            _npCatKeys.forEach(function(ck) {
                var cat = filteredData.categories[ck];
                if (!cat) return;
                var allStocks = (cat.main_board || []).concat(cat.gem || []).concat(cat.star || []).concat(cat.bj || []);
                allStocks.forEach(function(stock) {
                    renderNpKline('npk_' + stock.code, stock.klines);
                });
            });
            // Render alert klines
            var alertData = filteredData.alerts;
            if (alertData) {
                (alertData.zha_ban || []).concat(alertData.gem_alert || []).forEach(function(s) {
                    if (s.klines) renderNpKline('npk_' + s.code + '_alert', s.klines);
                });
            }
            // Collapse categories
            document.querySelectorAll('.np-cat-header:not(.collapsed)').forEach(function(h) {
                h.classList.add('collapsed');
                var body = h.nextElementSibling;
                if (body) {
                    body.classList.add('collapsed');
                    body.style.display = 'none';
                }
            });
        }, 100);
    }
}

// Set grid columns (card width stays fixed, centered layout)
function setNpGridCols(n) {
    _npGridCols = n;
    // Update button active state
    document.querySelectorAll('.np-grid-tog button').forEach(function(b) {
        b.classList.toggle('active', parseInt(b.getAttribute('data-cols')) === n);
    });
    // Apply column count to all card grids via CSS variable
    document.querySelectorAll('.np-card-grid').forEach(function(g) {
        g.style.setProperty('--np-cols', n);
    });
}

// Set sniper strong grid columns
function setSniperGridCols(n) {
    _sniperGridCols = n;
    document.querySelectorAll('.sn-grid-tog button').forEach(function(b) {
        b.classList.toggle('active', parseInt(b.getAttribute('data-cols')) === n);
    });
    document.querySelectorAll('.sniper-strong-grid').forEach(function(g) {
        g.style.setProperty('--sn-cols', n);
    });
}

// 精准狙击侧边栏隐藏/显示
function toggleSniperSidebar() {
    var sidebar = document.getElementById('sniperSidebar');
    var showBtn = document.getElementById('sniperSidebarShow');
    if (!sidebar) return;
    var isHidden = sidebar.classList.toggle('hidden');
    if (showBtn) {
        showBtn.style.display = isHidden ? 'flex' : 'none';
    }
}

// 频度分析标签点击 → KPL搜素
function searchTagInKpl(tag) {
    switchTab('kplsearch');
    document.getElementById('kplSearchInput2').value = tag;
    doKplSearch();
}

// Helper to find kline data for a canvas ID
function _getKlineDataForCanvas(canvasId) {
    if (!_npData) return null;
    var prefix = 'npk_';
    if (canvasId.indexOf(prefix) !== 0) return null;
    var code = canvasId.slice(prefix.length);
    var found = null;
    _npCatKeys.forEach(function(ck) {
        if (found) return;
        var cat = _npData.categories[ck];
        if (!cat) return;
        ['main_board', 'gem', 'star', 'bj'].forEach(function(bk) {
            if (found) return;
            (cat[bk] || []).forEach(function(s) {
                if (s.code === code) found = s.klines || null;
            });
        });
    });
    return found;
}

// Init sidebar IntersectionObserver
function initNpSidebar() {
    // Disconnect previous observer
    if (_npObserver) _npObserver.disconnect();

    var sections = [];
    _npSidebarItems.forEach(function(item) {
        var id = item.key === 'alert' ? 'np-section-alert' : 'np-section-' + item.key;
        var el = document.getElementById(id);
        if (el) sections.push(el);
    });

    if (sections.length === 0) return;

    _npObserver = new IntersectionObserver(function(entries) {
        var visibleItems = [];
        entries.forEach(function(entry) {
            if (entry.isIntersecting) {
                visibleItems.push({el: entry.target, ratio: entry.intersectionRatio});
            }
        });
        if (visibleItems.length === 0) return;
        // Pick the one with highest intersection ratio
        visibleItems.sort(function(a, b) { return b.ratio - a.ratio; });
        var bestId = visibleItems[0].el.id;
        // Update sidebar
        document.querySelectorAll('.np-sidebar-item').forEach(function(item) {
            var target = item.getAttribute('data-np-section');
            item.classList.toggle('active', target === bestId);
        });
    }, {rootMargin: '-10px 0px -15% 0px', threshold: [0, 0.1]});

    sections.forEach(function(el) { _npObserver.observe(el); });
}

// ===== 15日涨停板 Section =====
function renderNpZtWindow(ztData) {
    if (!ztData) return '';
    var sections = [
        {key: 'hot', label: '3日狙击', icon: '🔴'},
        {key: 'warm', label: '5日蓄势', icon: '🟠'},
        {key: 'cool', label: '10日潜伏', icon: '🟡'},
        {key: 'cold', label: '15日余波', icon: '🟢'}
    ];
    var boardKeys = ['main', 'gem', 'star'];
    var boardLabels = { 'main': '主板', 'gem': '创业板', 'star': '科创板' };
    var boardIcons = { 'main': '', 'gem': '📈', 'star': '🔬' };

    // 按板块分组
    var byBoard = { 'main': {}, 'gem': {}, 'star': {} };
    var totalAll = 0;
    var boardTotal = { 'main': 0, 'gem': 0, 'star': 0 };
    sections.forEach(function(sec) {
        var stocks = ztData[sec.key] || [];
        byBoard['main'][sec.key] = [];
        byBoard['gem'][sec.key] = [];
        byBoard['star'][sec.key] = [];
        stocks.forEach(function(s) {
            var b = s.board || 'main';
            if (!byBoard[b]) b = 'main';
            byBoard[b][sec.key].push(s);
            totalAll++;
            boardTotal[b]++;
        });
    });
    if (totalAll === 0) return '<div class="empty">暂无数据</div>';

    var INIT_SHOW = 20;  // 手机适配：减少初始卡片数避免OOM

    var html = '<div class="np-section" id="np-section-zt">';
    html += '<div class="np-cat-header collapsed" onclick="toggleNpCategory(this)" data-np-cat="zt">';
    html += '<span class="cat-icon">📅</span>';
    html += '<span class="cat-name">15日涨停板</span>';
    html += '<span class="cat-count">' + totalAll + '只</span>';
    html += '<span class="cat-arrow">▼</span>';
    html += '</div>';
    html += '<div class="np-cat-body collapsed" id="np-cat-body-zt">';

    // Helper: render one board's sub-section for a time window
    function renderBoardSection(sec, boardKey, stockList) {
        if (!stockList || stockList.length === 0) return '';
        var needsToggle = stockList.length > INIT_SHOW;
        var prefix = sec.key + '-' + boardKey;
        var h = '';
        h += '<div class="np-board-section" id="zt-section-' + prefix + '">';
        h += '<div class="np-board-header' + (boardKey === 'main' ? ' main' : ' sub') + '">';
        if (boardKey !== 'main') h += boardIcons[boardKey] + ' ';
        h += sec.icon + ' ' + sec.label;
        if (boardKey !== 'main') h += ' · ' + boardLabels[boardKey];
        h += ' (' + stockList.length + '只)</div>';
        h += '<div class="np-card-grid" id="zt-grid-' + prefix + '">';
        stockList.slice(0, INIT_SHOW).forEach(function(s) {
            h += renderNpZtCard(s);
        });
        h += '</div>';
        if (needsToggle) {
            h += '<div class="np-card-grid" id="zt-grid-extra-' + prefix + '" style="display:none;">';
            for (var i = INIT_SHOW; i < stockList.length; i++) {
                h += renderNpZtCard(stockList[i]);
            }
            h += '</div>';
            h += '<div class="np-show-toggle" style="text-align:center;margin:8px 0;">';
            h += '<button class="arb-btn" style="padding:6px 18px;font-size:0.85em;" onclick="toggleZtBoard(\\x27' + prefix + '\\x27)" id="zt-btn-' + prefix + '">显示全部 (' + stockList.length + '只)</button>';
            h += '</div>';
        }
        h += '</div>';
        return h;
    }

    // 1. 主板 — 按时间窗口分节
    var hasMain = boardTotal['main'] > 0;
    var hasGem = boardTotal['gem'] > 0;
    var hasStar = boardTotal['star'] > 0;

    if (hasMain) {
        html += '<div id="zt-board-main"></div>';
        sections.forEach(function(sec) {
            html += renderBoardSection(sec, 'main', byBoard['main'][sec.key]);
        });
    }

    // 2. 创业板 — 独立小章节
    if (hasGem) {
        html += '<div id="zt-board-gem"></div>';
        html += '<div class="np-board-divider">━━━ 创业板 (' + boardTotal['gem'] + '只) ━━━</div>';
        sections.forEach(function(sec) {
            html += renderBoardSection(sec, 'gem', byBoard['gem'][sec.key]);
        });
    }

    // 3. 科创板 — 独立小章节
    if (hasStar) {
        html += '<div id="zt-board-star"></div>';
        html += '<div class="np-board-divider">━━━ 科创板 (' + boardTotal['star'] + '只) ━━━</div>';
        sections.forEach(function(sec) {
            html += renderBoardSection(sec, 'star', byBoard['star'][sec.key]);
        });
    }

    html += '<div class="np-back-top" onclick="scrollToNpSection(\\x27np-nav-top\\x27)">↑ 回到顶部</div>';
    html += '</div></div>';
    return html;
}

function renderNpZtCard(s) {
    var html = '<div class="np-card">';
    html += '<div class="np-card-header">';
    html += '<div>';
    html += '<span class="np-card-code" data-code="' + s.code + '" data-name="' + s.name + '">' + s.code + '</span>';
    html += '<span class="np-card-name">' + s.name + '</span>';
    html += '</div>';
    html += '<div><span class="np-card-badge lianban">' + s.zt_count + '次涨停</span><button class="np-enlarge-btn" onclick="event.stopPropagation();showEnlargedCardDetail(\\x27' + s.code + '\\x27)" title="放大卡片">⛶</button></div>';
    html += '</div>';

    // Concepts badges
    html += '<div class="np-card-badges">';
    (s.concepts || []).forEach(function(c) {
        html += '<span class="np-card-badge">' + c + '</span>';
    });
    html += '</div>';

    // == OLD CONTENT (keep for reversion) ==
    // // Metrics row
    // html += '<div class="np-metrics">';
    // html += '<div class="np-metric"><div class="label">最近涨停</div><div class="value">' + s.last_zt_date + '</div></div>';
    // html += '<div class="np-metric"><div class="label">距今日</div><div class="value">' + s.days_ago + '天</div></div>';
    // html += '<div class="np-metric"><div class="label">15日涨停</div><div class="value">' + s.zt_count + '次</div></div>';
    // html += '</div>';
    // // K-line canvas
    // var canvasId = 'ztk_' + s.code;
    // html += '<div class="np-kline-container">';
    // html += '<canvas id="' + canvasId + '" height="200"></canvas>';
    // html += '</div>';
    // html += '<button class="np-kline-toggle" data-kline-id="' + canvasId + '">收起K线</button>';
    // var latestDate = getKlineLatestDate(s.klines);
    // if (latestDate) html += '<div class="np-kline-latest">最新: <span>' + latestDate + '</span></div>';
    // == END OLD CONTENT ==

    html += '<div data-np-detail="' + s.code + '" data-concepts=\\x27' + JSON.stringify(s.concepts || []) + '\\x27><div class="empty" style="padding:8px;">加载中...</div></div>';

    html += '</div>';
    return html;
}

// Toggle show-all for zt board section (prefix = secKey-boardKey)
function toggleZtBoard(prefix) {
    var extraGrid = document.getElementById('zt-grid-extra-' + prefix);
    var btn = document.getElementById('zt-btn-' + prefix);
    if (!extraGrid || !btn) return;
    var isHidden = extraGrid.style.display === 'none';
    extraGrid.style.display = isHidden ? '' : 'none';
    var total = parseInt(btn.textContent.match(/\\d+/)) || 0;
    btn.textContent = isHidden ? '收起' : '显示全部 (' + total + '只)';

    // If expanding, load card details for newly visible cards
    if (isHidden) {
        // 重置加载锁让loadNpCardDetails可以处理新卡
        _npDetailLoading = false;
        setTimeout(function() { loadNpCardDetails(); }, 100);
        initNpSidebar();
    }
}

// ===== 震荡企稳模式 =====
var _oscData = null;

// 震荡企稳分类标签和阈值
var _oscCategories = [
    {key: 'preferred', label: '优选', minScore: 75, icon: '⭐'},
    {key: 'watch', label: '关注', minScore: 50, icon: '✅'},
    {key: 'observe', label: '观察', minScore: 0, icon: '📊'}
];

function loadNpOscillation() {
    fetch('/api/oscillation').then(function(r) { return r.json(); }).then(function(oscData) {
        if (!oscData || oscData.error || !oscData.stocks) return;
        _oscData = oscData;
        var oscSection = document.getElementById('np-oscillation-section');
        if (!oscSection) return;
        oscSection.innerHTML = renderNpOscillation(oscData);

        // Render klines for visible cards (first 30 per category)
        setTimeout(function() {
            var catKeys = ['preferred', 'watch', 'observe'];
            catKeys.forEach(function(key) {
                var grid = document.getElementById('osc-grid-' + key);
                if (!grid) return;
                grid.querySelectorAll('canvas').forEach(function(canvas) {
                    var code = canvas.id.replace('osck_', '').split('_')[0];
                    var stocks = oscData.stocks || [];
                    for (var i = 0; i < stocks.length; i++) {
                        if (stocks[i].code === code && stocks[i].klines) {
                            renderNpKline(canvas.id, stocks[i].klines);
                            break;
                        }
                    }
                });
            });
        }, 100);

        initNpSidebar();
        loadNpCardDetails();
    }).catch(function(e) {
        console.error('震荡企稳加载失败:', e);
    });
}

function renderNpOscillation(oscData) {
    if (!oscData || !oscData.stocks || oscData.stocks.length === 0) {
        return '<div class="empty">暂无符合条件的震荡企稳股票</div>';
    }

    var stocks = oscData.stocks;
    var total = stocks.length;
    var INIT_SHOW = 30;

    var html = '<div class="np-section" id="np-section-osc">';
    html += '<div class="np-cat-header collapsed" onclick="toggleNpCategory(this)" data-np-cat="osc">';
    html += '<span class="cat-icon">🌊</span>';
    html += '<span class="cat-name">震荡企稳</span>';
    html += '<span class="cat-count">' + total + '只</span>';
    html += '<span class="cat-arrow">▼</span>';
    html += '</div>';
    html += '<div class="np-cat-body collapsed" id="np-cat-body-osc">';
    html += '<p style="color:#888;font-size:0.85em;margin:0 0 10px 0;">检测条件：连板≥2 → 回调不低于首板K线中位(不A杀) → 企稳震荡≥5天 → 量缩明显。评分维度：震荡质量(35%)+量缩程度(25%)+均线支撑(20%)+连板高度(20%)</p>';

    // 按分类展示
    _oscCategories.forEach(function(cat) {
        var catStocks = stocks.filter(function(s) {
            if (cat.key === 'preferred') return s.stabilization_score >= 75;
            if (cat.key === 'watch') return s.stabilization_score >= 50 && s.stabilization_score < 75;
            return s.stabilization_score < 50;
        });
        if (catStocks.length === 0) return;

        var needsToggle = catStocks.length > INIT_SHOW;
        var showCount = needsToggle ? INIT_SHOW : catStocks.length;

        html += '<div class="np-board-section" id="osc-section-' + cat.key + '">';
        html += '<div class="np-board-header main">' + cat.icon + ' ' + cat.label + ' (' + catStocks.length + '只)</div>';
        html += '<div class="np-card-grid" id="osc-grid-' + cat.key + '">';
        catStocks.forEach(function(s, idx) {
            if (needsToggle && idx >= INIT_SHOW) return;
            html += renderOscCard(s);
        });
        html += '</div>';
        if (needsToggle) {
            html += '<div class="np-card-grid" id="osc-grid-extra-' + cat.key + '" style="display:none;">';
            for (var i = INIT_SHOW; i < catStocks.length; i++) {
                html += renderOscCard(catStocks[i]);
            }
            html += '</div>';
            html += '<div class="np-show-toggle" style="text-align:center;margin:8px 0;">';
            html += '<button class="arb-btn" style="padding:6px 18px;font-size:0.85em;" data-osc-toggle="' + cat.key + '" id="osc-btn-' + cat.key + '">显示全部 (' + catStocks.length + '只)</button>';
            html += '</div>';
        }
        html += '</div>'; // .np-board-section
    });

    html += '<div class="np-back-top" onclick="scrollToNpSection(\\x27np-nav-top\\x27)">↑ 回到顶部</div>';
    html += '</div></div>'; // .np-cat-body, .np-section
    return html;
}

function renderOscCard(s) {
    var scoreColor = s.stabilization_score >= 75 ? '#4fc3f7' : (s.stabilization_score >= 50 ? '#ff9800' : '#888');
    var ma5Status = s.above_ma5 ? '✓ MA5' : '✗ MA5';
    var ma5Color = s.above_ma5 ? '#4fc3f7' : '#e94560';
    var ma10Status = s.above_ma10 ? '✓ MA10' : '✗ MA10';
    var ma10Color = s.above_ma10 ? '#ff9800' : '#e94560';

    var html = '<div class="np-card">';
    html += '<div class="np-card-header">';
    html += '<div>';
    html += '<span class="np-card-code" data-code="' + s.code + '" data-name="' + s.name + '">' + s.code + '</span>';
    html += '<span class="np-card-name">' + s.name + '</span>';
    html += '</div>';
    html += '<div><span class="np-card-badge lianban">' + s.lianban_count + '连板</span>';
    html += '<span class="np-card-badge" style="background:' + scoreColor + ';color:#0a0a1a;">' + s.stabilization_score + '分</span><button class="np-enlarge-btn" onclick="event.stopPropagation();showEnlargedCardDetail(\\x27' + s.code + '\\x27)" title="放大卡片">⛶</button></div>';
    html += '</div>';

    // Concepts
    html += '<div class="np-card-badges">';
    (s.concepts || []).forEach(function(c) {
        html += '<span class="np-card-badge">' + c + '</span>';
    });
    html += '</div>';

    // == OLD CONTENT (keep for reversion) ==
    // // Metrics row
    // html += '<div class="np-metrics">';
    // html += '<div class="np-metric"><div class="label">涨停日期</div><div class="value">' + s.last_zt_date + '</div></div>';
    // html += '<div class="np-metric"><div class="label">回调深度</div><div class="value">' + s.max_pullback_pct + '%</div></div>';
    // html += '<div class="np-metric"><div class="label">震荡天数</div><div class="value">' + s.osc_days + '天</div></div>';
    // html += '<div class="np-metric"><div class="label">震荡区间</div><div class="value">' + s.osc_range_pct + '%</div></div>';
    // html += '</div>';
    // // Second metrics row
    // html += '<div class="np-metrics" style="margin-top:4px;">';
    // html += '<div class="np-metric"><div class="label">量缩比</div><div class="value">' + s.volume_shrink_ratio.toFixed(2) + '</div></div>';
    // html += '<div class="np-metric"><div class="label" style="color:' + ma5Color + '">' + ma5Status + '</div><div class="value">' + s.ma5.toFixed(2) + '</div></div>';
    // html += '<div class="np-metric"><div class="label" style="color:' + ma10Color + '">' + ma10Status + '</div><div class="value">' + s.ma10.toFixed(2) + '</div></div>';
    // html += '<div class="np-metric"><div class="label">距涨停</div><div class="value">' + s.days_since_last_zt + '天</div></div>';
    // html += '</div>';
    // // K-line canvas
    // var canvasId = 'osck_' + s.code;
    // html += '<div class="np-kline-container">';
    // html += '<canvas id="' + canvasId + '" height="200"></canvas>';
    // html += '</div>';
    // html += '<button class="np-kline-toggle" data-kline-id="' + canvasId + '">收起K线</button>';
    // var latestDate = getKlineLatestDate(s.klines);
    // if (latestDate) html += '<div class="np-kline-latest">最新: <span>' + latestDate + '</span></div>';
    // == END OLD CONTENT ==

    html += '<div data-np-detail="' + s.code + '" data-concepts=\\x27' + JSON.stringify(s.concepts || []) + '\\x27><div class="empty" style="padding:8px;">加载中...</div></div>';

    html += '</div>';
    return html;
}

// ===== N字战法新模式：阳线回调 + 三连阴回调 =====

function renderNpSimplePatternSection(stocks, key, label, icon, desc) {
    if (!stocks || stocks.length === 0) return '';

    var total = stocks.length;

    var html = '<div class="np-section" id="np-section-' + key + '">';
    html += '<div class="np-cat-header collapsed" onclick="toggleNpCategory(this)" data-np-cat="' + key + '">';
    html += '<span class="cat-icon">' + icon + '</span>';
    html += '<span class="cat-name">' + label + '</span>';
    html += '<span class="cat-count">' + total + '只</span>';
    html += '<span class="cat-arrow">▼</span>';
    html += '</div>';
    html += '<div class="np-cat-body collapsed" id="np-cat-body-' + key + '">';
    html += '<p style="color:#888;font-size:0.85em;margin:0 0 10px 0;">' + desc + '</p>';
    html += '<div class="np-card-grid" id="simple-grid-' + key + '">';
    for (var i = 0; i < total; i++) {
        html += renderNpSimpleCard(stocks[i], key);
    }
    html += '</div>';
    html += '<div class="np-back-top" onclick="scrollToNpSection(\\x27np-nav-top\\x27)">↑ 回到顶部</div>';
    html += '</div></div>'; // .np-cat-body, .np-section
    return html;
}

function renderNpSimpleCard(s, prefix) {
    var pctColor = s.change_pct >= 0 ? '#4fc3f7' : '#e94560';
    var pctSign = s.change_pct >= 0 ? '+' : '';

    var html = '<div class="np-card" data-code="' + s.code + '" data-name="' + s.name + '">';
    html += '<div class="np-card-header">';
    html += '<div>';
    html += '<span class="np-card-code" data-code="' + s.code + '" data-name="' + s.name + '">' + s.code + '</span>';
    html += '<span class="np-card-name">' + highlightText(s.name, _npFilterKeyword) + '</span>' + _watchStarHtml(s.code, s.name, _watchGetCategory(s.code));
    html += '</div>';
    html += '<span class="np-card-badge lianban">' + s.recent_zt_count + '次涨停</span>';
    html += '<button class="np-enlarge-btn" onclick="event.stopPropagation();showEnlargedCardDetail(\\x27' + s.code + '\\x27)" title="放大卡片">⛶</button>';
    html += '</div>';

    html += '<div data-np-detail="' + s.code + '" data-concepts=\\x27' + JSON.stringify(s.concepts || []) + '\\x27><div class="empty" style="padding:8px;">加载中...</div></div>';

    html += '</div>';
    return html;
}

function _renderCardDetailContent(code, detail, alertInfo, stockName, conceptsJson) {
    if (!detail || (!detail.kpl_records && !detail.limit_rows)) return '<div class="empty" style="padding:8px;">暂无数据</div>';
    // 从KPL或CSV获取股票名称
    if (!stockName) {
        if (detail.name) {
            stockName = detail.name;
        } else if (detail.kpl_records && detail.kpl_records.length > 0) {
            stockName = detail.kpl_records[0].stock_name || '';
        } else if (detail.limit_rows && detail.limit_rows.length > 0) {
            stockName = detail.limit_rows[0].name || '';
        }
    }
    var h = '<div class="ds-card-detail-wrap" style="position:relative;" data-code="' + code + '" data-name="' + _kplEsc(stockName || code) + '">';
    // 异动信息（紧挨日K线图上方）
    if (alertInfo && alertInfo.date) {
        var pctColor = alertInfo.pct >= 10 ? '#ff6b6b' : '#ff9800';
        var pctSign = alertInfo.pct > 0 ? '+' : '';
        h += '<div class="ds-stock-kline-section" style="padding:6px 12px;background:rgba(255,107,107,0.06);border:1px solid rgba(255,107,107,0.15);border-radius:6px;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;">';
        h += '<span style="color:#aaa;font-size:0.85em;">\u6700\u8fd1\u5f02\u52a8\u65e5: <span style="color:#fff;font-weight:bold;">' + alertInfo.date + '</span></span>';
        h += '<span style="color:' + pctColor + ';font-weight:bold;font-size:1em;">' + pctSign + alertInfo.pct.toFixed(2) + '%</span>';
        h += '</div>';
    }
    // 日K线图
    h += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">日K线图（新浪）<button class="img-refresh-btn" onclick="reloadSinaImg(this)" title="重新加载">⟳</button></div>';
    h += '<img data-orig-src="' + sinaKlineImg(code) + '" src="' + sinaKlineImg(code) + '" class="ds-stock-kline-img" loading="lazy" onerror="retryImg(this)"></div>';
    // 分时图
    h += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">分时图（新浪）<button class="img-refresh-btn" onclick="reloadSinaImg(this)" title="重新加载">⟳</button></div>';
    h += '<img data-orig-src="' + sinaMinImg(code) + '" src="' + sinaMinImg(code) + '" class="ds-stock-kline-img" loading="lazy" onerror="retryImg(this)"></div>';
    // 查询概念 + 查询联动按钮
    h += '<div style="text-align:center;padding:8px 0;">';
    h += '<button onclick="closeEnlargeCardModal();sqJumpToKpl(\\x27' + (stockName || code) + '\\x27)" style="background:#ff7043;color:#fff;border:none;padding:8px 24px;border-radius:6px;font-size:0.95em;font-weight:600;cursor:pointer;">查询概念</button>';
    h += '<button onclick="closeEnlargeCardModal();modalQueryLinkage(\\x27' + code + '\\x27)" style="margin-left:8px;background:#00d4ff;color:#0a1628;border:none;padding:8px 24px;border-radius:6px;font-size:0.95em;font-weight:600;cursor:pointer;">查询联动</button>';
    h += '</div>';
    // KPL近3个月涨停统计
    var tmKpl = detail.three_month_kpl || detail.three_month || {count:0, dates:[]};
    h += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">近3个月涨停（KPL）：共' + tmKpl.count + '次</div><div>';
    if (tmKpl.dates && tmKpl.dates.length > 0) {
        tmKpl.dates.forEach(function(d) {
            var display = d.length === 8 ? d.slice(0,4) + '-' + d.slice(4,6) + '-' + d.slice(6,8) : d;
            h += '<span class="stock-detail-date-chip">' + display + '</span> ';
        });
    } else {
        h += '<span style="color:#666;font-size:0.85em;">近3个月无涨停</span>';
    }
    h += '</div></div>';
    // KPL涨停记录（替换涨停理由）
    var kplRec = detail.kpl_records || [];
    h += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">KPL涨停记录（共' + kplRec.length + '条）</div>';
    h += '<div style="max-height:210px;overflow-y:auto;">';
    h += renderKplRecords(kplRec, code, stockName);
    h += '</div></div>';
    // KPL概念（替换同花顺概念）
    var kplCpts = detail.kpl_concepts || [];
    if (kplCpts.length > 0) {
        h += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">开盘啦概念</div><div class="np-card-badges" style="margin:0;">';
        kplCpts.forEach(function(c) { h += '<span class="np-card-badge">' + c + '</span>'; });
        h += '</div></div>';
    } else if (conceptsJson) {
        try {
            var concepts = JSON.parse(conceptsJson);
            if (concepts && concepts.length > 0) {
                h += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">同花顺概念</div><div class="np-card-badges" style="margin:0;">';
                concepts.forEach(function(c) { h += '<span class="np-card-badge">' + highlightText(c, _npFilterKeyword) + '</span>'; });
                h += '</div></div>';
            }
        } catch(e) {}
    }
    h += '</div>'; // close ds-card-detail-wrap
    return h;
}

function renderNpKline(canvasId, klines) {
    var canvas = document.getElementById(canvasId);
    if (!canvas || !klines || klines.length < 2) return;

    var ctx = canvas.getContext('2d');
    var W = canvas.width = canvas.clientWidth || 480;
    var H = canvas.height = 200;
    var pad = { top: 12, bottom: 28, left: 10, right: 10 };
    var plotW = W - pad.left - pad.right;
    var n = klines.length;

    // Find price range
    var minP = Infinity, maxP = -Infinity;
    klines.forEach(function(k) {
        if (k.low < minP) minP = k.low;
        if (k.high > maxP) maxP = k.high;
    });
    var padP = (maxP - minP) * 0.1 || minP * 0.02;
    minP -= padP;
    maxP += padP;
    var pRange = maxP - minP || 1;

    function px(idx) { return pad.left + (idx / (n - 1)) * plotW; }
    function py(price) { return pad.top + (1 - (price - minP) / pRange) * (H - pad.top - pad.bottom); }
    function clamp(v, mn, mx) { return Math.max(mn, Math.min(mx, v)); }

    // Clear
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(0, 0, W, H);

    var barWidth = Math.max(1, plotW / n * 0.6);
    var halfBar = barWidth / 2;

    // Grid lines
    ctx.strokeStyle = '#2a2a3e';
    ctx.lineWidth = 0.5;
    for (var i = 0; i <= 4; i++) {
        var y = pad.top + (H - pad.top - pad.bottom) * i / 4;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(W - pad.right, y);
        ctx.stroke();
    }

    // Draw MA5 and MA10
    function drawMA(key, color) {
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        var started = false;
        klines.forEach(function(k, idx) {
            var val = k[key];
            if (val === undefined || val === null || val === 0) return;
            var x = px(idx);
            var y = py(val);
            if (!started) { ctx.moveTo(x, y); started = true; }
            else { ctx.lineTo(x, y); }
        });
        ctx.stroke();
    }
    drawMA('ma5', '#4fc3f7');
    drawMA('ma10', '#ff9800');

    // Draw candlesticks
    klines.forEach(function(k, idx) {
        var x = px(idx);
        var isRed = k.close >= k.open;
        var bodyTop = Math.min(py(k.open), py(k.close));
        var bodyBot = Math.max(py(k.open), py(k.close));
        var yHigh = py(k.high);
        var yLow = py(k.low);

        // Detect 炸板: 上影线明显+涨幅较大 (涨停但没封住)
        var bodyTopPrice = Math.max(k.open, k.close);
        var upperShadow = k.high - bodyTopPrice;
        var shadowRatio = bodyTopPrice > 0 ? upperShadow / bodyTopPrice : 0;
        var hasZtFlag = k.is_zt === true;
        var isZhaBan = (hasZtFlag || (k.change_pct != null && k.change_pct > 5))
                       && shadowRatio > 0.005;

        // Candle color: 炸板→金色, yang→红, yin→绿
        var candleColor;
        if (isZhaBan) {
            candleColor = '#ffd700';
        } else {
            candleColor = isRed ? '#e94560' : '#00ff88';
        }
        ctx.fillStyle = candleColor;
        ctx.strokeStyle = candleColor;
        ctx.lineWidth = 1;

        // High-low line
        ctx.beginPath();
        ctx.moveTo(x, yHigh);
        ctx.lineTo(x, yLow);
        ctx.stroke();

        // Candle body
        var bodyH = Math.max(bodyBot - bodyTop, 1);
        ctx.fillRect(x - halfBar, bodyTop, barWidth, bodyH);

        // === Marker dots (only on ZT/炸板 days) ===
        if (k.is_zt && !isZhaBan) {
            // 涨停封住 → 紫色圆点
            ctx.fillStyle = '#9c27b0';
            ctx.beginPath();
            ctx.arc(x, yHigh - 6, 3, 0, Math.PI * 2);
            ctx.fill();
            ctx.fillStyle = 'rgba(156, 39, 176, 0.25)';
            ctx.fillRect(x - halfBar, bodyTop, barWidth, bodyH * 0.15);
        }

        if (isZhaBan) {
            // 涨停炸板 → 阳线红点 / 阴线绿点 + 金色蜡烛
            var dotColor = isRed ? '#ff1744' : '#00e676';
            ctx.fillStyle = dotColor;
            ctx.beginPath();
            ctx.arc(x, yHigh - 6, 3, 0, Math.PI * 2);
            ctx.fill();
            ctx.fillStyle = 'rgba(255, 215, 0, 0.15)';
            ctx.fillRect(x - halfBar, bodyTop, barWidth, bodyH);
        }
    });

    // X-axis labels
    ctx.fillStyle = '#888';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'center';
    var labelStep = Math.max(1, Math.floor(n / 6));
    for (var i = 0; i < n; i += labelStep) {
        var dateStr = klines[i].date || '';
        var shortDate = dateStr.slice(4);
        ctx.fillText(shortDate, px(i), H - 6);
    }
}

// ===== Hot Concept Quick-Select for N-pattern =====
function renderNpHotConceptButtons() {
    var el = document.getElementById('npHotConceptBar');
    if (!el) return;
    // 先显示加载状态
    el.innerHTML = '<span style="color:#888;font-size:0.8em;margin-right:4px;line-height:28px;">实时热门:</span><span style="color:#555;font-size:0.75em;">加载中...</span>';
    _cachedFetch('/api/hot_concept_20').then(function(hotConcepts) {
        if (!hotConcepts || hotConcepts.length === 0) {
            el.innerHTML = '<span style="color:#888;font-size:0.8em;margin-right:4px;line-height:28px;">实时热门:</span><span style="color:#555;font-size:0.75em;">暂无数据</span>';
            return;
        }
        el.innerHTML = '<span style="color:#888;font-size:0.8em;margin-right:4px;line-height:28px;">实时热门:</span>';
        var curVal = (document.getElementById('npFilterConcept').value || '').trim();
        var selectedSet = {};
        if (curVal) {
            curVal.split(',').forEach(function(v) { selectedSet[v.trim()] = true; });
        }
        // 按涨幅降序排列，取前20
        var sorted = hotConcepts.slice().sort(function(a, b) {
            return (b.change_pct || 0) - (a.change_pct || 0);
        }).slice(0, 20);
        // 生成2行，每行10个
        for (var row = 0; row < 2; row++) {
            var rowDiv = document.createElement('div');
            rowDiv.style.cssText = 'display:flex;flex-wrap:nowrap;gap:5px;margin-bottom:4px;';
            for (var col = 0; col < 10; col++) {
                var idx = row * 10 + col;
                if (idx >= sorted.length) break;
                var item = sorted[idx];
                var c = item.concept_name;
                if (!c) continue;
                var isSelected = selectedSet[c] || false;
                var btn = document.createElement('span');
                var pctColor = item.change_pct >= 0 ? '#ff6b6b' : '#4caf50';
                btn.style.cssText = 'padding:3px 8px;border-radius:12px;font-size:0.76em;cursor:pointer;transition:all 0.2s;white-space:nowrap;' +
                    (isSelected ? 'background:#00d4ff;color:#0a0a1a;' : 'background:#0f3460;color:#ccc;');
                btn.innerHTML = c + ' <span style="color:' + pctColor + ';font-weight:bold;">' + (item.change_pct >= 0 ? '+' : '') + item.change_pct.toFixed(1) + '%</span>';
                btn.title = '热度值: ' + (item.hot_value || 0) + (item.hot_tag ? ' | ' + item.hot_tag : '');
                btn.onclick = (function(conceptName) {
                    return function() {
                        var input = document.getElementById('npFilterConcept');
                        if (!input) return;
                        var val = (input.value || '').trim();
                        var parts = val ? val.split(',').map(function(v) { return v.trim(); }).filter(function(v) { return v; }) : [];
                        var idx = parts.indexOf(conceptName);
                        if (idx >= 0) {
                            parts.splice(idx, 1);
                        } else {
                            parts.push(conceptName);
                        }
                        input.value = parts.join(',');
                        filterNPattern();
                    };
                })(c);
                rowDiv.appendChild(btn);
            }
            el.appendChild(rowDiv);
        }
    }).catch(function() {
        el.innerHTML = '<span style="color:#888;font-size:0.8em;margin-right:4px;line-height:28px;">实时热门:</span><span style="color:#555;font-size:0.75em;">加载失败</span>';
    });
}

// ===== 15日涨停板 二级导航 =====
function initZtSubNav() {
    // Remove only zt sub-nav items (those with data-np-cat="zt")
    document.querySelectorAll('.np-sidebar-subitem[data-np-cat="zt"]').forEach(function(el) { el.remove(); });

    var boardLabels = { 'main': '主板', 'gem': '创业板', 'star': '科创板' };
    var boardKeys = ['main', 'gem', 'star'];

    // Find "15日涨停" sidebar item
    var ztItem = null;
    document.querySelectorAll('.np-sidebar-item').forEach(function(item) {
        if (item.getAttribute('data-np-section') === 'np-section-zt') ztItem = item;
    });
    if (!ztItem) return;

    var refNode = ztItem;
    boardKeys.forEach(function(bk) {
        if (!document.getElementById('zt-board-' + bk)) return;
        var subItem = document.createElement('a');
        subItem.className = 'np-sidebar-subitem';
        subItem.setAttribute('data-np-section', 'zt-board-' + bk);
        subItem.setAttribute('data-np-cat', 'zt');
        subItem.textContent = boardLabels[bk];
        subItem.onclick = function() { scrollToNpSection('zt-board-' + bk); };
        refNode.parentNode.insertBefore(subItem, refNode.nextSibling);
        refNode = subItem;
    });
}

// ===== Load 15日涨停板 Data =====
function loadNpZtWindow() {
    fetch('/api/zt_window?top_n=9999').then(function(r) { return r.json(); }).then(function(ztData) {
        if (!ztData || ztData.error) return;
        _ztWindowData = ztData;
        var ztSection = document.getElementById('np-ztwindow-section');
        if (!ztSection) return;
        ztSection.innerHTML = renderNpZtWindow(ztData);

        // Render klines for visible cards (all board grids)
        setTimeout(function() {
            var ztBody = document.getElementById('np-cat-body-zt');
            if (!ztBody) return;
            var allGrids = ztBody.querySelectorAll('.np-card-grid');
            var secKeys = ['hot', 'warm', 'cool', 'cold'];
            var allStocks = [];
            secKeys.forEach(function(k) {
                (ztData[k] || []).forEach(function(s) { allStocks.push(s); });
            });
            allGrids.forEach(function(grid) {
                grid.querySelectorAll('canvas').forEach(function(canvas) {
                    var code = canvas.id.replace('ztk_', '');
                    for (var i = 0; i < allStocks.length; i++) {
                        if (allStocks[i].code === code && allStocks[i].klines) {
                            renderNpKline(canvas.id, allStocks[i].klines);
                            break;
                        }
                    }
                });
            });
        }, 100);

        // Re-init sidebar observer to include new section
        initNpSidebar();
        // 初始化15日涨停二级导航
        initZtSubNav();
        // 加载新板块的卡片详情
        loadNpCardDetails();
    }).catch(function(e) {
        console.error('15日涨停板加载失败:', e);
    });
}

// ===== K-line Modal =====
// ===== Stock Card Popup (replaces old K-line modal) =====
// ===== 股票卡片导航上下文 =====
var _cardStocks = [];  // [{code, name}, ...] 当前列表
var _cardIndex = -1;   // 当前在列表中位置
var _cardFetchId = 0;  // 递增请求ID，防过时fetch覆盖

// 设置卡片导航上下文（在渲染股票列表时调用）
function setCardContext(stocks, clickedIndex) {
    _cardStocks = stocks || [];
    _cardIndex = clickedIndex >= 0 ? clickedIndex : -1;
}

function navigateCard(direction) {
    var newIndex = _cardIndex + direction;
    if (newIndex < 0 || newIndex >= _cardStocks.length) return;
    _cardIndex = newIndex;
    var s = _cardStocks[newIndex];
    showStockCard(s.code, s.name, true);  // skipLoading=true 不闪屏
}

function showStockCard(code, name, skipLoading) {
    var modal = document.getElementById('klineModal');
    var titleEl = document.getElementById('klineModalTitle');
    var badgesEl = document.getElementById('klineModalBadges');
    var metricsEl = document.getElementById('klineModalMetrics');
    var canvasContainer = document.getElementById('klineModalCanvas');

    // 生成递增请求ID，用于防止过时fetch覆盖最新结果
    var fetchId = ++_cardFetchId;

    // 更新导航状态（总是在fetch前更新）
    var prevBtn = document.getElementById('klinePrevBtn');
    var nextBtn = document.getElementById('klineNextBtn');
    var counterEl = document.getElementById('klineModalCounter');
    if (prevBtn) prevBtn.className = 'kline-modal-nav-btn' + (_cardIndex <= 0 ? ' disabled' : '');
    if (nextBtn) nextBtn.className = 'kline-modal-nav-btn' + (_cardIndex >= _cardStocks.length - 1 ? ' disabled' : '');
    if (counterEl) {
        counterEl.textContent = _cardStocks.length > 0
            ? (_cardIndex + 1) + ' / ' + _cardStocks.length
            : '';
    }

    if (skipLoading) {
        // 导航切换：不闪屏，保留旧内容，仅更新标题
        titleEl.textContent = code + ' ' + name + ' ...';
    } else {
        // 首次打开：显示loading
        titleEl.textContent = code + ' ' + name + ' - 加载中...';
        badgesEl.innerHTML = '';
        metricsEl.innerHTML = '<div style="color:#888;padding:8px;">正在获取数据...</div>';
        canvasContainer.innerHTML = '';
        modal.classList.add('active');
    }

    // Fetch kline + stock info in parallel
    Promise.all([
        fetch('/api/kline?stock=' + code + '&days=120').then(function(r) { return r.json(); }),
        fetch('/api/search?q=' + code).then(function(r) { return r.json(); })
    ]).then(function(results) {
        // 过时fetch直接丢弃（用户已点击其他股票）
        if (fetchId !== _cardFetchId) return;
        var klineData = results[0];
        var searchData = results[1];
        var klines = (klineData && klineData.klines) || [];
        var stockName = (klineData && klineData.stock_name) || name;

        // Find stock info from search results
        var stockInfo = null;
        if (searchData && Array.isArray(searchData)) {
            for (var si = 0; si < searchData.length; si++) {
                if (searchData[si].code === code) {
                    stockInfo = searchData[si];
                    break;
                }
            }
        }

        // === 一次性构建全部HTML字符串，减少DOM重排 ===
        titleEl.textContent = code + ' ' + stockName;

        // 1. Badges: 一次性innerHTML
        var badgesHtml = '';
        var concepts = (stockInfo && stockInfo.concepts) || [];
        concepts.forEach(function(c) {
            badgesHtml += '<span class="np-card-badge">' + c + '</span>';
        });
        badgesEl.innerHTML = badgesHtml;

        // 2. Metrics: 一次性innerHTML
        var ztCount = (stockInfo && stockInfo.zt_count) || 0;
        var ztDates = (klineData && klineData.zt_dates) || [];
        var lastZt = (stockInfo && stockInfo.last_zt_date) || (ztDates.length > 0 ? ztDates[ztDates.length - 1] : '-');
        var ztDateStr = ztDates.slice(-3).join(' ') || lastZt;
        metricsEl.innerHTML =
            '<div class="np-metric"><div class="label">涨停次数</div><div class="value">' + ztCount + '次</div></div>' +
            '<div class="np-metric"><div class="label">最近涨停</div><div class="value">' + ztDateStr + '</div></div>' +
            '<div class="np-metric"><div class="label">K线天数</div><div class="value">' + klines.length + '天</div></div>' +
            '<div class="np-metric"><div class="label">概念数</div><div class="value">' + (stockInfo && stockInfo.concept_count || concepts.length) + '个</div></div>';

        // 3. 复用现有canvas，避免重建闪屏
        var existingCanvas = document.getElementById('klineModalChart');
        if (klines.length >= 2) {
            if (!existingCanvas) {
                canvasContainer.innerHTML = '<canvas id="klineModalChart" height="280" style="width:100%;"></canvas>';
                existingCanvas = document.getElementById('klineModalChart');
            }
            if (existingCanvas) {
                renderNpKline('klineModalChart', klines);
            }
        } else {
            canvasContainer.innerHTML = '<div style="color:#888;padding:12px;text-align:center;">K线数据不足（仅' + klines.length + '条）</div>';
        }

        // 4. 操作按钮
        var oldBtnDiv = document.getElementById('stockCardBtnDiv');
        if (oldBtnDiv) oldBtnDiv.parentNode.removeChild(oldBtnDiv);
        var btnDiv = document.createElement('div');
        btnDiv.id = 'stockCardBtnDiv';
        btnDiv.style.cssText = 'margin-top: 12px; display: flex; gap: 10px; justify-content: center;';
        var navBtn = document.createElement('button');
        navBtn.textContent = '📊 查询联动';
        navBtn.className = 'arb-btn';
        navBtn.style.cssText = 'padding:8px 20px;font-size:0.9em;';
        navBtn.onclick = function() {
            closeKlineModal();
            doSearch(code, '');
        };
        btnDiv.appendChild(navBtn);
        metricsEl.parentNode.appendChild(btnDiv);

    }).catch(function(err) {
        titleEl.textContent = code + ' ' + name;
        badgesEl.innerHTML = '';
        metricsEl.innerHTML = '<div style="color:#e94560;padding:12px;">数据加载失败: ' + err.message + '</div>';
        canvasContainer.innerHTML = '';
    });
}

function closeKlineModal() {
    document.getElementById('klineModal').classList.remove('active');
}

// 键盘快捷键：左右箭头切换卡片，Esc关闭
document.addEventListener('keydown', function(e) {
    var klineModal = document.getElementById('klineModal');
    var enlargeModal = document.getElementById('enlargeCardModal');
    if (klineModal && klineModal.classList.contains('active')) {
        if (e.key === 'ArrowLeft') { navigateCard(-1); e.preventDefault(); }
        else if (e.key === 'ArrowRight') { navigateCard(1); e.preventDefault(); }
        else if (e.key === 'Escape') { closeKlineModal(); e.preventDefault(); }
    } else if (enlargeModal && enlargeModal.classList.contains('active')) {
        if (e.key === 'Escape') { closeEnlargeCardModal(); e.preventDefault(); }
    }
});

// ===== Real-time Dashboard =====
function loadRealtime() {
    var container = document.getElementById('realtimeContainer');
    container.innerHTML = '<div class="loading">加载实时看板...</div>';

    Promise.all([
        fetch('/api/realtime_zt?_t=' + Date.now()).then(function(r) { return r.json(); }).catch(function() { return []; }),
        _cachedFetch('/api/lianban_ladder?top_n=30'),
        _cachedFetch('/api/stats?top_n=5'),
        _cachedFetch('/api/data_status'),
    ]).then(function(results) {
        var todayZt = results[0] || [];
        var lianbanLadder = results[1] || [];
        var stats = results[2] || {};
        var dataStatus = results[3] || {};

        var summary = stats.summary || {};
        var latestDate = dataStatus.latest_display || (todayZt.length > 0 ? todayZt[0].trade_date : '');
        var ztCountToday = todayZt.length;
        var apiUnavailable = todayZt.length === 0;

        var html = '';

        // Compute max lianban from ladder data
        var maxLb = lianbanLadder.length > 0 ? (lianbanLadder[0].consecutive_lianban || 0) : 0;

        // Refresh banner
        if (apiUnavailable) {
            html += '<div class="refresh-banner" style="background:#5a1a1a;">⚠️ 实时API暂时无法获取数据</div>';
        } else {
            html += '<div class="refresh-banner" style="display:flex;align-items:center;justify-content:center;gap:8px;flex-wrap:wrap;">';
            html += '<span>📡 最近交易日: ' + (latestDate || 'N/A') + ' | 今日涨停: ' + ztCountToday + ' 只 | 连板天梯: ' + lianbanLadder.length + ' 只</span>';
            html += '<button class="rt-auto-refresh-btn" id="autoRefreshBtn" onclick="toggleAutoRefresh()">⏱ 自动刷新 5分钟</button>';
            html += '</div>';
        }

        // === HEADER SUMMARY ===
        html += '<div class="rt-header">';
        html += '<h2>📊 实时看盘 · ' + (latestDate || '') + '</h2>';
        html += '<div class="rt-summary">';
        html += '<div class="rt-summary-item"><div class="rt-val">' + (summary.total_stocks_with_zt || 0) + '</div><div class="rt-label">涨停股票(总)</div></div>';
        html += '<div class="rt-summary-item"><div class="rt-val" style="color:#ffc107;">' + ztCountToday + '</div><div class="rt-label">今日涨停</div></div>';
        html += '<div class="rt-summary-item"><div class="rt-val" style="color:#00d4ff;">' + (summary.total_concepts || 0) + '</div><div class="rt-label">题材概念</div></div>';
        html += '<div class="rt-summary-item"><div class="rt-val" style="color:#4caf50;">' + (summary.total_zt_events || 0) + '</div><div class="rt-label">总涨停次数</div></div>';
        html += '<div class="rt-summary-item"><div class="rt-val" style="color:#ce93d8;">' + maxLb + '</div><div class="rt-label">最高连板</div></div>';
        html += '</div></div>';

        // === 今日涨停（全量显示，按首次封板时间排序） ===
        html += '<div class="rt-section">';
        html += '<h3>\u26a1 \u4eca\u65e5\u6da8\u505c <span class="count-badge">' + todayZt.length + '\u53ea</span><span class="rt-refresh-icon" onclick="manualRefreshTodayZt()" title="\u624b\u52a8\u5237\u65b0\u4eca\u65e5\u6da8\u505c">\u21bb</span></h3>';
        html += renderTodayZtList(todayZt);
        html += '</div>';

        // === \u4eca\u65e5\u6da8\u505c\u8d70\u52bf\uff08\u6298\u53e0\u5361\u7247\uff09 ===
        html += '<div class="rt-section kpl-tree-node" id="todayZtTrendSection">';
        html += '<div class="kpl-header" onclick="_watchToggleTodayZtCards(this)" style="cursor:pointer;">';
        html += '<span class="kpl-arrow">&#9660;</span>';
        html += '<span class="kpl-label" style="color:#4fc3f7;">\U0001f4c8 \u4eca\u65e5\u6da8\u505c\u8d70\u52bf <span class="count-badge" id="todayZtCardsBadge">' + todayZt.length + '\u53ea</span></span>';
        html += '<span class="rt-refresh-icon" onclick="event.stopPropagation();refreshTodayZtCards()" title="\u5237\u65b0">\u21bb</span>';
        html += '</div>';
        html += '<div class="kpl-children collapsed" id="todayZtCardsBody">';
        html += '<div class="kpl-card-grid" id="todayZtCardsGrid" style="--np-cols:4;">';
        html += '<div class="empty" style="grid-column:1/-1;padding:12px;color:#666;font-size:0.85em;">\u5c55\u5f00\u540e\u52a0\u8f7d</div>';
        html += '</div></div></div>';

        // === \u8fde\u677f\u5929\u68af\uff08\u5168\u91cf\uff09 ===
        html += '<div class="rt-section">';
        html += '<h3>🏆 连板天梯 <span class="count-badge">' + lianbanLadder.length + '只</span></h3>';
        html += renderLianbanLadderTable(lianbanLadder);
        html += '</div>';

        // === 历史涨停（15个交易日，按日期选择） ===
        html += '<div class="rt-section" id="rtHistorySection">';
        html += '<h3>📅 历史涨停 <span class="count-badge" id="historyZtBadge">加载中...</span>';
        html += '<span style="margin-left:auto;display:flex;align-items:center;gap:6px;">';
        html += '<input type="date" id="historyZtDate" style="background:#1a1a2e;border:1px solid #0f3460;border-radius:6px;color:#eee;padding:3px 8px;font-size:0.82em;width:140px;cursor:pointer;" onchange="loadHistoryZtByDate(this.value)"';
        html += ' title="选择日期查看历史涨停">';
        html += '</span></h3>';
        html += '<div id="historyZtList"><div class="loading" style="padding:20px;">选择日期查看历史涨停...</div></div>';
        html += '</div>';

        // === 涨停理由词频时间线（资金流向分析） ===
        html += '<div class="rt-section">';
        html += '<h3>🔍 题材频度分析 · L1/L2/L3层级 <span class="count-badge" id="wordFreqBadge">近15日</span></h3>';
        html += '<div id="ztWordFreqTimeline"><div class="loading" style="padding:20px;">加载词频分析...</div></div>';
        html += '</div>';

        container.innerHTML = html;
        loadLuReasons();
        _fillKplPaths();
        // 加载历史涨停默认日期 + 词频时间线
        loadHistoryZtByDate();
        loadZtWordFreqTimeline();
        _realtimeLoaded = true;
    }).catch(function(e) {
        container.innerHTML = '<div class="error">实时看板加载失败: ' + e.message + '</div>';
        _realtimeLoaded = true; // 即使失败也标记已加载，避免无限重试
    });
}

// Manual refresh for 今日涨停 section only
function manualRefreshTodayZt() {
    var icon = document.querySelector('.rt-refresh-icon');
    if (!icon) return;
    icon.classList.add('spinning');

    fetch('/api/realtime_zt?_t=' + Date.now())
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var section = document.querySelector('.rt-section');
            if (section) {
                section.innerHTML = '<h3>⚡ 今日涨停 <span class="count-badge">' + data.length + '只</span><span class="rt-refresh-icon" onclick="manualRefreshTodayZt()" title="手动刷新今日涨停">↻</span></h3>' + renderTodayZtList(data);
                // 重新填充新DOM中的涨停理由
                loadLuReasons();
                _fillKplPaths();
            }
            // 同步更新今日涨停走势的badge
            var trendBadge = document.getElementById('todayZtCardsBadge');
            if (trendBadge) trendBadge.textContent = data.length + '\u53ea';
        })
        .catch(function(e) {
            console.error('\u624b\u52a8\u5237\u65b0\u5931\u8d25:', e);
        })
        .finally(function() {
            icon.classList.remove('spinning');
        });
}

// \u6298\u53e0\u5207\u6362 \u4eca\u65e5\u6da8\u505c\u8d70\u52bf \u5361\u7247\u533a\u57df
function _watchToggleTodayZtCards(el) {
    var node = el.closest('.kpl-tree-node');
    if (!node) return;
    var wasCollapsed = node.classList.contains('collapsed');
    node.classList.toggle('collapsed');
    if (wasCollapsed) {
        var grid = document.getElementById('todayZtCardsGrid');
        if (!grid) return;
        // \u9996\u6b21\u5c55\u5f00\u65f6\u52a0\u8f7d\u5361\u7247
        if (!grid.querySelector('.np-card')) {
            refreshTodayZtCards();
        }
    }
}

// \u5237\u65b0 \u4eca\u65e5\u6da8\u505c\u8d70\u52bf \u5361\u7247
function refreshTodayZtCards() {
    var grid = document.getElementById('todayZtCardsGrid');
    if (!grid) return;
    var badge = document.getElementById('todayZtCardsBadge');
    grid.innerHTML = '<div class="empty" style="grid-column:1/-1;padding:12px;color:#666;font-size:0.85em;">\u52a0\u8f7d\u4e2d...</div>';
    fetch('/api/realtime_zt?_t=' + Date.now())
        .then(function(r) { return r.json(); })
        .then(function(stocks) {
            if (!stocks || stocks.length === 0) {
                grid.innerHTML = '<div class="empty" style="grid-column:1/-1;padding:12px;color:#666;font-size:0.85em;">\u6682\u65e0\u4eca\u65e5\u6da8\u505c</div>';
                if (badge) badge.textContent = '0\u53ea';
                return;
            }
            // \u6309\u5c01\u677f\u65f6\u95f4\u5347\u5e8f\u6392\u5217
            stocks.sort(function(a, b) {
                return (a.first_time || 999999) - (b.first_time || 999999);
            });
            if (badge) badge.textContent = stocks.length + '\u53ea';
            var html = '';
            stocks.forEach(function(s) {
                var boardCls = _kplGetBoardClass(s.code);
                var lb = s.lianban || 0;
                var ft = s.first_time;
                var timeStr = '--:--';
                if (ft && ft < 999999) {
                    var ts = String(ft).padStart(6, '0');
                    timeStr = ts.slice(0, 2) + ':' + ts.slice(2, 4);
                }
                html += '<div class="np-card ' + boardCls + '" data-code="' + s.code + '" data-name="' + _kplEsc(s.name) + '" onclick="showEnlargedCardDetail(\\x27' + s.code + '\\x27)" style="cursor:pointer;">';
                html += '<div class="np-card-header"><div>';
                html += '<span class="np-card-code">' + s.code + '</span>';
                html += '<span class="np-card-name">' + _kplEsc(s.name) + '</span>';
                html += '</div><div>';
                html += '<span class="np-card-badge lianban" style="background:rgba(79,195,247,0.15);color:#4fc3f7;">' + timeStr + '</span>';
                if (lb > 0) {
                    html += '<span class="np-card-badge lianban" style="background:rgba(255,107,107,0.15);color:#ff6b6b;">' + lb + '\u8fde\u677f</span>';
                }
                html += '<button class="np-enlarge-btn" onclick="event.stopPropagation();showEnlargedCardDetail(\\x27' + s.code + '\\x27)" title="\u653e\u5927\u5361\u7247">\u2b36</button></div></div>';
                // Concepts
                html += '<div class="np-card-badges">';
                (s.concepts || []).forEach(function(c) { html += '<span class="np-card-badge">' + c + '</span>'; });
                html += '</div>';
                // Detail placeholder
                html += '<div data-np-detail="' + s.code + '"><div class="empty" style="padding:8px;">\u52a0\u8f7d\u4e2d...</div></div>';
                html += '</div>';
            });
            grid.innerHTML = html;
            loadNpCardDetails();
        })
        .catch(function() {
            grid.innerHTML = '<div class="empty" style="grid-column:1/-1;padding:12px;color:#666;font-size:0.85em;">\u52a0\u8f7d\u5931\u8d25</div>';
            if (badge) badge.textContent = '?\u53ea';
        });
}

// Auto refresh state and toggle
var _autoRefreshTimer = null;
var _autoRefreshCountdown = null;
var _autoRefreshRemaining = 0;
var _autoRefreshActive = false;
var _realtimeLoaded = false;

function toggleAutoRefresh() {
    var btn = document.getElementById('autoRefreshBtn');
    if (!btn) return;

    if (_autoRefreshActive) {
        // Stop
        clearInterval(_autoRefreshTimer);
        clearInterval(_autoRefreshCountdown);
        _autoRefreshActive = false;
        _autoRefreshTimer = null;
        _autoRefreshCountdown = null;
        btn.innerHTML = '\u23f1 自动刷新 5\u5206\u949f';
        btn.classList.remove('active');
        showToast('已停止自动刷新', 'info');
        return;
    }

    // Check A-stock trading hours (Beijing time 9:25 ~ 15:00)
    var now = new Date();
    var beijingHour = (now.getUTCHours() + 8) % 24;
    var beijingMin = now.getUTCMinutes();
    var totalMin = beijingHour * 60 + beijingMin;
    if (totalMin < 565 || totalMin >= 900) {
        showToast('\u23f0 \u975e\u4ea4\u6613\u65f6\u6bb5 (9:25~15:00)\uff0c\u81ea\u52a8\u5237\u65b0\u4e0d\u53ef\u7528', 'warning');
        return;
    }

    // Start
    _autoRefreshActive = true;
    _autoRefreshRemaining = 300;
    btn.classList.add('active');

    function updateAutoRefreshBtn() {
        var m = Math.floor(_autoRefreshRemaining / 60);
        var s = _autoRefreshRemaining % 60;
        btn.innerHTML = '<span class="rt-pulse-dot"></span> \u81ea\u52a8\u5237\u65b0 (' + m + ':' + (s < 10 ? '0' : '') + s + ')';
    }
    updateAutoRefreshBtn();

    _autoRefreshCountdown = setInterval(function() {
        _autoRefreshRemaining--;
        if (_autoRefreshRemaining <= 0) {
            // Check trading hours before each refresh cycle
            var now = new Date();
            var h = (now.getUTCHours() + 8) % 24;
            var m = now.getUTCMinutes();
            var total = h * 60 + m;
            if (total < 565 || total >= 900) {
                // Out of trading hours, auto-stop
                clearInterval(_autoRefreshTimer);
                clearInterval(_autoRefreshCountdown);
                _autoRefreshActive = false;
                _autoRefreshTimer = null;
                _autoRefreshCountdown = null;
                btn.innerHTML = '\u23f1 自动刷新 5\u5206\u949f';
                btn.classList.remove('active');
                showToast('\u23f0 \u5df2\u8fc7\u4ea4\u6613\u65f6\u6bb5\uff0c\u81ea\u52a8\u5237\u65b0\u5df2\u505c\u6b62', 'info');
                return;
            }
            _autoRefreshRemaining = 300;
            manualRefreshTodayZt();
        }
        updateAutoRefreshBtn();
    }, 1000);
}

// Toast notification helper
var _toastTimer = null;
function showToast(msg, type) {
    type = type || 'info';
    var el = document.getElementById('rtToast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'rtToast';
        el.className = 'rt-toast';
        document.body.appendChild(el);
    }
    el.className = 'rt-toast ' + type;
    el.textContent = msg;
    // Force reflow before adding show class
    void el.offsetWidth;
    el.classList.add('show');
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(function() {
        el.classList.remove('show');
    }, 3500);
}

// Render helpers for realtime dashboard

var _stockDetailCache = {};
var _stockLuLoading = false;
function loadLuReasons() {
    if (_stockLuLoading) return;
    var codes = [];
    document.querySelectorAll('.lu-reasons').forEach(function(el) {
        var c = el.getAttribute('data-code');
        if (c && !_stockDetailCache[c] && codes.indexOf(c) === -1) codes.push(c);
    });
    // 先利用缓存渲染已有的数据（再进入tab时走此路径）
    document.querySelectorAll('.lu-reasons').forEach(function(el) {
        var c = el.getAttribute('data-code');
        if (c && _stockDetailCache[c]) {
            _renderLuReasons(el, c);
        }
    });
    if (codes.length === 0) return;
    _stockLuLoading = true;
    fetch('/api/stock_detail_batch?codes=' + codes.join(','))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            for (var code in data) { _stockDetailCache[code] = data[code]; }
            document.querySelectorAll('.lu-reasons').forEach(function(el) {
                var c = el.getAttribute('data-code');
                if (c && _stockDetailCache[c]) {
                    _renderLuReasons(el, c);
                }
            });
            _stockLuLoading = false;
        })
        .catch(function() { _stockLuLoading = false; });
}

// Shared helper: render lu reason chips from cache for one element (KPL版)
function _renderLuReasons(el, code) {
    var cache = _stockDetailCache[code];
    var kplRecs = (cache && cache.kpl_records) || [];
    var freq = {};
    if (kplRecs.length > 0) {
        kplRecs.forEach(function(r) {
            var tag = r.reason_tag || '';
            if (tag) freq[tag] = (freq[tag] || 0) + 1;
            var cs = r.concepts || '';
            cs.split('\u3001').forEach(function(c) {
                c = c.trim();
                if (c) freq[c] = (freq[c] || 0) + 1;
            });
        });
        var sortedTags = Object.keys(freq).sort(function(a, b) {
            return freq[b] - freq[a];
        }).slice(0, 10);
        var chips = sortedTags.map(function(tag) {
            return '<span class="lu-chip lu-chip-clickable" data-tag="' + tag.replace(/"/g, '') + '" onclick="searchLuTag(this)">' + tag + ' <span class="lu-chip-freq">' + freq[tag] + '</span></span>';
        }).join('');
        el.innerHTML = '<div style="margin-top:3px;">' + chips + '</div>';
    } else {
        // fallback: CSV数据
        var rows = cache ? (cache.limit_rows || []) : [];
        var seen = {};
        rows.forEach(function(r) {
            var desc = r.lu_desc || '';
            if (seen[desc]) return;
            seen[desc] = true;
            desc.split('+').forEach(function(tag) {
                tag = tag.trim();
                if (tag) freq[tag] = (freq[tag] || 0) + 1;
            });
        });
        var sortedTags = Object.keys(freq).sort(function(a, b) {
            return freq[b] - freq[a];
        }).slice(0, 10);
        var chips = sortedTags.map(function(tag) {
            return '<span class="lu-chip lu-chip-clickable" data-tag="' + tag.replace(/"/g, '') + '" onclick="searchLuTag(this)">' + tag + ' <span class="lu-chip-freq">' + freq[tag] + '</span></span>';
        }).join('');
        if (chips) {
            el.innerHTML = '<div style="margin-top:3px;">' + chips + '</div>';
        } else {
            el.innerHTML = '<div style="margin-top:3px;"><span class="lu-chip" style="background:transparent;color:#666;font-size:0.75em;">暂无涨停理由</span></div>';
        }
    }
    el.removeAttribute('data-code');
}

// Click a split reason tag -> jump to 涨停深挖 tab and search all history
function searchLuTag(el) {
    var tag = el.getAttribute('data-tag');
    if (!tag) return;
    switchTab('deepsearch');
    document.getElementById('deepSearchInput').value = tag;
    // 默认近2个月，与直接搜索一致
    var now = new Date();
    document.getElementById('deepSearchDateEnd').value = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0');
    var start = new Date(now);
    start.setMonth(start.getMonth() - 2);
    document.getElementById('deepSearchDateStart').value = start.getFullYear() + '-' + String(start.getMonth()+1).padStart(2,'0') + '-' + String(start.getDate()).padStart(2,'0');
    doDeepSearch();
}

// ===== 历史涨停（按日期选择） =====
var _historyTradeDates = [];
function loadHistoryZtByDate(dateStr) {
    // If no date provided, fetch trade dates and set default
    if (!dateStr) {
        fetch('/api/recent_trade_dates?n=20')
            .then(function(r) { return r.json(); })
            .then(function(dates) {
                _historyTradeDates = dates;
                // Default: trading day before latestDate
                var container = document.getElementById('realtimeContainer');
                var bannerText = container ? container.querySelector('.refresh-banner span') : null;
                var latestDate = '';
                if (bannerText) {
                    var m = bannerText.textContent.match(/交易日:\s*(\d{8})/);
                    if (m) latestDate = m[1];
                }
                var defaultDate = '';
                if (latestDate && dates.length > 1) {
                    var idx = dates.indexOf(latestDate);
                    if (idx > 0) defaultDate = dates[idx - 1];
                    else if (idx === 0) defaultDate = dates[1]; // 今日涨停,默认用前一个交易日
                    else defaultDate = dates[0]; // 找不到该日期
                } else {
                    defaultDate = dates[0] || '';
                }
                if (defaultDate) {
                    var isoDate = defaultDate.slice(0,4) + '-' + defaultDate.slice(4,6) + '-' + defaultDate.slice(6,8);
                    var input = document.getElementById('historyZtDate');
                    if (input) { input.value = isoDate; input.setAttribute('data-ymd', defaultDate); }
                    loadHistoryZtByDate(defaultDate);
                }
            });
        return;
    }
    var apiDate = dateStr.replace(/-/g, '');
    var listEl = document.getElementById('historyZtList');
    if (listEl) listEl.innerHTML = '<div class="loading" style="padding:15px;">加载 ' + apiDate + ' 涨停数据...</div>';
    fetch('/api/history_zt_by_date?date=' + apiDate)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var stocks = data || [];
            var listEl = document.getElementById('historyZtList');
            var badge = document.getElementById('historyZtBadge');
            if (badge) badge.textContent = stocks.length + '只';
            if (listEl) {
                listEl.innerHTML = renderTodayZtList(stocks);
                loadLuReasons();
                _fillKplPaths();
            }
        })
        .catch(function(e) {
            var listEl = document.getElementById('historyZtList');
            if (listEl) listEl.innerHTML = '<div class="error" style="padding:15px;">加载失败: ' + e.message + '</div>';
        });
}

// ===== 涨停理由词频时间线 =====
function loadZtWordFreqTimeline() {
    fetch('/api/zt_word_freq_timeline?days=15')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var container = document.getElementById('ztWordFreqTimeline');
            if (!container) return;
            if (!data || data.length === 0) {
                container.innerHTML = '<div class="empty" style="padding:15px;">暂无数据</div>';
                return;
            }
            var html = '<div class="wf-timeline">';
            data.forEach(function(day) {
                var hasL1 = day.l1 && day.l1.length > 0;
                var hasL2 = day.l2 && day.l2.length > 0;
                var hasL3 = day.l3 && day.l3.length > 0;
                var dateLabel = day.date.slice(0,4) + '-' + day.date.slice(4,6) + '-' + day.date.slice(6,8);
                html += '<div class="wf-day"><div class="wf-day-header">' + dateLabel + '</div>';
                if (!hasL1 && !hasL2 && !hasL3) {
                    html += '<div class="wf-day-empty">暂无涨停</div>';
                } else {
                    // L1 section
                    if (hasL1) {
                        html += '<div class="wf-level"><span class="wf-level-label" style="color:#00d4ff;">L1</span>';
                        day.l1.forEach(function(t) {
                            html += '<span class="wf-tag wf-tag-high" onclick="sqJumpToKpl(\\x27' + t.tag.replace(/'/g, '') + '\\x27)" title="' + t.tag + '">' + t.tag + ' <span class="wf-count">' + t.count + '</span></span>';
                        });
                        html += '</div>';
                    }
                    // L2 section
                    if (hasL2) {
                        html += '<div class="wf-level"><span class="wf-level-label" style="color:#4fc3f7;">L2</span>';
                        day.l2.forEach(function(t) {
                            html += '<span class="wf-tag wf-tag-mid" onclick="sqJumpToKpl(\\x27' + t.tag.replace(/'/g, '') + '\\x27)" title="' + t.tag + '">' + t.tag + ' <span class="wf-count">' + t.count + '</span></span>';
                        });
                        html += '</div>';
                    }
                    // L3 section
                    if (hasL3) {
                        html += '<div class="wf-level"><span class="wf-level-label" style="color:#ffb74d;">L3</span>';
                        day.l3.forEach(function(t) {
                            html += '<span class="wf-tag wf-tag-low" onclick="sqJumpToKpl(\\x27' + t.tag.replace(/'/g, '') + '\\x27)" title="' + t.tag + '">' + t.tag + ' <span class="wf-count">' + t.count + '</span></span>';
                        });
                        html += '</div>';
                    }
                }
                html += '</div>';
            });
            html += '</div>';
            container.innerHTML = html;
        })
        .catch(function(e) {
            var container = document.getElementById('ztWordFreqTimeline');
            if (container) container.innerHTML = '<div class="error" style="padding:15px;">题材频度分析加载失败</div>';
        });
}

// Click word freq tag -> jump to deep search
function searchLuTagFromWf(tag) {
    switchTab('deepsearch');
    document.getElementById('deepSearchInput').value = tag;
    // 默认近2个月，与直接搜索一致
    var now = new Date();
    document.getElementById('deepSearchDateEnd').value = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0');
    var start = new Date(now);
    start.setMonth(start.getMonth() - 2);
    document.getElementById('deepSearchDateStart').value = start.getFullYear() + '-' + String(start.getMonth()+1).padStart(2,'0') + '-' + String(start.getDate()).padStart(2,'0');
    doDeepSearch();
}

// Helper: render concept chips (全量显示，不省略)
function renderConceptChips(concepts, code, name) {
    var arr = concepts || [];
    var h = '';
    if (arr.length === 0) {
        h = '<span style="color:#555;font-size:0.8em;">-</span>';
    } else {
        h = arr.map(function(c) {
            return '<span class="concept-chip">' + c + '</span>';
        }).join('');
    }
    // 如果提供了股票代码，添加涨停理由占位符
    if (code) {
        h += '<div class="lu-reasons" data-code="' + code + '"></div>';
    }
    // 如果提供了股票名称，添加KPL路径占位符
    if (code && name) {
        h += '<div class="kpl-paths" data-code="' + code + '" data-name="' + name + '"></div>';
    }
    return h;
}
// Helper: render lianban badge with color
function renderLbBadge(lb) {
    var lbClass = lb >= 5 ? 'rt-lb-high' : ('rt-lb-' + Math.min(lb, 5));
    return '<span class="rt-lb ' + lbClass + '">' + lb + '</span>';
}

function renderLianbanLadderTable(stocks) {
    if (!stocks || stocks.length === 0) return '<div class="empty" style="padding:15px;">暂无连板数据</div>';
    var html = '<table class="rt-zt-table"><tr><th>#</th><th>代码</th><th>名称</th><th>连板</th><th>涨停</th><th>概念</th></tr>';
    stocks.forEach(function(s, i) {
        var lb = s.consecutive_lianban || 0;
        var conceptHtml = renderConceptChips(s.concepts, s.code, s.name);
        var rankIcon = i === 0 ? '🥇' : (i === 1 ? '🥈' : (i === 2 ? '🥉' : (i + 1)));
        html += '<tr class="clickable" data-code="' + s.code + '" data-name="' + s.name + '">';
        html += '<td style="font-size:0.9em;">' + rankIcon + '</td>';
        html += '<td><strong>' + s.code + '</strong></td>';
        html += '<td>' + _watchStarHtml(s.code, s.name, _watchGetCategory(s.code)) + '<span class="link-stock-name" onclick="event.stopPropagation();stockQueryGoTo(\\x27' + (s.name||'').replace(/'/g,'') + '\\x27)">' + (s.name || '') + '</span></td>';
        html += '<td>' + renderLbBadge(lb) + '</td>';
        html += '<td>' + (s.zt_count || 0) + '</td>';
        html += '<td>' + conceptHtml + '</td></tr>';
    });
    html += '</table>';
    return html;
}

function renderTodayZtList(stocks) {
    if (!stocks || stocks.length === 0) return '<div class="empty" style="padding:15px;">暂无今日涨停数据</div>';
    // 格式化封板时间: 简写HH:MM或9位数字转HH:MM:SS
    function fmtTime(t) {
        if (!t || t >= 999999) return '--:--';
        var s = String(t).padStart(6, '0');
        return s.slice(0, 2) + ':' + s.slice(2, 4);
    }
    var html = '<table class="rt-zt-table"><tr><th>#</th><th>代码</th><th style="white-space:nowrap;min-width:90px;">名称</th><th style="min-width:90px;white-space:nowrap;">封板时间</th><th>连板</th><th>概念</th></tr>';
    stocks.forEach(function(s, i) {
        var lb = s.lianban || 0;
        var rankStr = (i + 1) <= 3 ? ['🥇', '🥈', '🥉'][i] : (i + 1);
        html += '<tr class="clickable" data-code="' + s.code + '" data-name="' + s.name + '">';
        html += '<td style="font-size:0.9em;">' + rankStr + '</td>';
        html += '<td><strong>' + s.code + '</strong></td>';
        html += '<td style="white-space:nowrap;">' + _watchStarHtml(s.code, s.name, _watchGetCategory(s.code)) + '<span class="link-stock-name" onclick="event.stopPropagation();stockQueryGoTo(\\x27' + (s.name||'').replace(/'/g,'') + '\\x27)">' + (s.name || '') + '</span></td>';
        html += '<td style="color:#4fc3f7;font-weight:bold;font-size:0.9em;white-space:nowrap;">' + fmtTime(s.first_time) + '</td>';
        html += '<td>' + renderLbBadge(lb) + '</td>';
        html += '<td>' + renderConceptChips(s.concepts, s.code, s.name) + '</td></tr>';
    });
    html += '</table>';
    return html;
}

function renderHotStocksTable(stocks) {
    if (!stocks || stocks.length === 0) return '<div class="empty" style="padding:15px;">暂无数据</div>';
    var html = '<table class="rt-zt-table"><tr><th>#</th><th>代码</th><th>名称</th><th>涨停</th><th>概念</th><th>最近涨停</th></tr>';
    stocks.forEach(function(s, i) {
        html += '<tr class="clickable" data-code="' + s.code + '" data-name="' + s.name + '">';
        html += '<td style="color:#888;">' + (i+1) + '</td>';
        html += '<td><strong>' + s.code + '</strong></td>';
        html += '<td>' + _watchStarHtml(s.code, s.name, _watchGetCategory(s.code)) + '<span class="link-stock-name" onclick="event.stopPropagation();stockQueryGoTo(\\x27' + (s.name||'').replace(/'/g,'') + '\\x27)">' + (s.name || '') + '</span></td>';
        html += '<td style="color:#ff6b6b;font-weight:bold;">' + (s.zt_count || 0) + '次</td>';
        html += '<td>' + renderConceptChips(s.concepts, s.code, s.name) + '</td>';
        html += '<td style="color:#888;font-size:0.85em;">' + (s.last_zt || '') + '</td></tr>';
    });
    html += '</table>';
    return html;
}

// 同花顺热股Top100表格
function renderHotRank100Table(stocks) {
    if (!stocks || stocks.length === 0) return '<div class="empty" style="padding:15px;">暂无数据</div>';
    var html = '<table class="rt-zt-table"><tr><th style="width:36px;white-space:nowrap;">排名</th><th style="width:64px;white-space:nowrap;">代码</th><th style="width:72px;white-space:nowrap;">名称</th><th style="width:58px;white-space:nowrap;">涨幅</th><th style="width:56px;white-space:nowrap;">热度值</th><th style="width:48px;white-space:nowrap;">标签</th><th style="white-space:nowrap;">概念</th></tr>';
    stocks.forEach(function(s) {
        var cp = s.change_pct;
        if (cp === null || cp === undefined) cp = 0;
        var pctColor = cp >= 0 ? '#ff6b6b' : '#4caf50';
        var pctStr = (cp > 0 ? '+' : '') + cp.toFixed(2) + '%';
        var popLabel = s.pop_tag ? '<span class="badge badge-pool" style="font-size:0.75em;">' + s.pop_tag + '</span>' : '';
        html += '<tr class="clickable" data-code="' + s.code + '" data-name="' + s.name + '">';
        html += '<td style="color:#888;white-space:nowrap;">' + s.rank + '</td>';
        html += '<td style="white-space:nowrap;"><strong>' + s.code + '</strong></td>';
        html += '<td style="white-space:nowrap;">' + _watchStarHtml(s.code, s.name, _watchGetCategory(s.code)) + '<span class="link-stock-name" onclick="event.stopPropagation();stockQueryGoTo(\\x27' + (s.name||'').replace(/'/g,'') + '\\x27)">' + (s.name || '') + '</span></td>';
        html += '<td style="color:' + pctColor + ';font-weight:bold;white-space:nowrap;">' + pctStr + '</td>';
        html += '<td style="color:#ffc107;white-space:nowrap;">' + (s.hot_value || 0) + '</td>';
        html += '<td style="white-space:nowrap;">' + popLabel + '</td>';
        html += '<td>' + renderConceptChips(s.concepts, s.code, s.name) + '</td></tr>';
    });
    html += '</table>';
    return html;
}

// 同花顺热门概念板块Top20表格（可排序）
var _hotConceptSortCol = '';
var _hotConceptSortDir = -1;
var _hotConceptsData = null;
function sortHotConcept(col) {
    if (_hotConceptSortCol === col) {
        _hotConceptSortDir = -_hotConceptSortDir;
    } else {
        _hotConceptSortCol = col;
        _hotConceptSortDir = -1; // 切换列时默认降序
    }
    if (!_hotConceptsData) return;
    if (_conceptSearched) {
        // 搜索模式下：更新 conceptResult 中的Top20区域
        var rc = document.getElementById('conceptResult');
        if (!rc) return;
        var topSection = rc.querySelector('.top20-section');
        if (topSection) {
            topSection.innerHTML = '<div style="margin-bottom:8px;color:#888;font-size:0.85em;">📈 同花顺热门概念板块 Top20</div>';
            topSection.innerHTML += renderHotConceptTable(_hotConceptsData);
        }
    } else {
        // 默认模式下：更新顶部的topConceptTable
        var tc = document.getElementById('topConceptTable');
        if (tc) {
            var html = '<div class="result">';
            html += '<div style="margin-bottom:8px;color:#888;font-size:0.85em;">📈 同花顺热门概念板块 Top20 — 点击概念名称查看详细分析，或在上方搜索框输入概念</div>';
            html += renderHotConceptTable(_hotConceptsData);
            html += '<div style="margin-top:20px;padding:15px;background:#0d1b36;border-radius:8px;">';
            html += '<div style="color:#888;font-size:0.85em;">&#128161; 在上方搜索框输入概念（细分）名称即可搜索，支持同花顺概念和涨停理由关键词</div>';
            html += '</div>';
            html += '</div>';
            tc.innerHTML = html;
        }
    }
}
function renderHotConceptTable(concepts) {
    if (!concepts || concepts.length === 0) return '<div class="empty" style="padding:15px;">暂无数据</div>';
    // 排序
    if (_hotConceptSortCol) {
        concepts = concepts.slice().sort(function(a, b) {
            var va = a[_hotConceptSortCol] || 0, vb = b[_hotConceptSortCol] || 0;
            return (va - vb) * _hotConceptSortDir;
        });
    }
    var arrow = function(col) {
        if (_hotConceptSortCol === col) return _hotConceptSortDir === 1 ? ' ▲' : ' ▼';
        return ' <span style="opacity:0.2;">▲</span>';
    };
    var html = '<table class="rt-zt-table">';
    html += '<tr><th>排名</th><th>概念名称</th>';
    html += '<th class="sortable" onclick="sortHotConcept(&#39;change_pct&#39;)">涨幅' + arrow('change_pct') + '</th>';
    html += '<th class="sortable" onclick="sortHotConcept(&#39;hot_value&#39;)">热度值' + arrow('hot_value') + '</th>';
    html += '<th>标签</th></tr>';
    concepts.forEach(function(c) {
        var cp = c.change_pct;
        if (cp === null || cp === undefined) cp = 0;
        var pctColor = cp >= 0 ? '#ff6b6b' : '#4caf50';
        var pctStr = (cp > 0 ? '+' : '') + cp.toFixed(2) + '%';
        var tagLabel = c.hot_tag ? '<span class="badge" style="background:#0f3460;color:#88c0ff;font-size:0.75em;">' + c.hot_tag + '</span>' : '';
        html += '<tr>';
        html += '<td style="color:#888;">' + c.rank + '</td>';
        html += '<td><span class="concept-chip" style="color:#00d4ff;background:transparent;border:none;padding:0;font-weight:bold;">' + c.concept_name + '</span></td>';
        html += '<td style="color:' + pctColor + ';font-weight:bold;">' + pctStr + '</td>';
        html += '<td style="color:#ffc107;">' + (c.hot_value || 0) + '</td>';
        html += '<td>' + tagLabel + '</td></tr>';
    });
    html += '</table>';
    return html;
}

// ===== Linkage Tab - Default Sections =====
function loadLinkageDefaultSections() {
    var container = document.getElementById('linkageDefaultSections');
    // 如果没有linkageDefaultSections（已被搜索结果覆盖），跳过
    if (!container) return;
    // 已经加载过且未被替换，跳过
    if (container.getAttribute('data-loaded') === 'true') return;

    container.innerHTML = '<div class="loading">加载默认联动数据...</div>';

    Promise.all([
        _cachedFetch('/api/lianban_ladder?top_n=10'),
        _cachedFetch('/api/hot_stocks?top_n=100'),
        _cachedFetch('/api/hot_rank_100')
    ]).then(function(results) {
        container.setAttribute('data-loaded', 'true');
        var ladder = results[0] || [];
        var hotStocks = results[1] || [];
        var hotRank100 = results[2] || [];

        var now = new Date();
        var timeStr = now.toLocaleTimeString('zh-CN', {hour12:false});
        var timeHtml = '<span style="float:right;color:#888;font-size:0.7em;font-weight:normal;display:inline-flex;align-items:center;gap:4px;">\u66f4\u65b0: ' + timeStr + '<span class="rt-refresh-icon" onclick="refreshLinkageAll()" title="\u5237\u65b0\u5168\u90e8">\u21bb</span></span>';

        var html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-wrap:wrap;">';
        html += '<div style="color:#888;font-size:0.85em;">⬇ 输入代码/名称搜索联动，或浏览默认数据</div>';
        html += '</div>';

        // 连板天梯 Top 10
        html += '<div class="rt-section">';
        html += '<h3>🏆 连板天梯 Top 10' + timeHtml + '</h3>';
        html += renderLianbanLadderTable(ladder);
        html += '<div class="rt-section kpl-tree-node" style="margin-top:-16px;padding-top:8px;">';
        html += '<div class="kpl-header" onclick="toggleLinkageCards(this)">';
        html += '<span class="kpl-arrow">&#9660;</span>';
        html += '<span class="kpl-label" style="color:#4fc3f7;">📈 K线走势 <span class="count-badge">' + ladder.length + '只</span></span></div>';
        html += '<div class="kpl-children collapsed"><div class="np-card-grid" data-key="ladder" style="--np-cols:4;"><div class="empty" style="grid-column:1/-1;padding:12px;color:#666;">展开后加载</div></div></div></div>';
        html += '</div>';

        // 热门涨停 Top 100
        var showAllHotLinkage = window._showAllHot || false;
        var hotLimit = showAllHotLinkage ? hotStocks.length : 20;
        html += '<div class="rt-section">';
        html += '<h3>🔥 活跃涨停 Top 100' + timeHtml + '</h3>';
        var hotHtml = '<table class="rt-zt-table"><tr><th>#</th><th>代码</th><th>名称</th><th>涨停</th><th>评分</th><th>概念</th><th>周期</th><th>最近涨停</th></tr>';
        hotStocks.slice(0, hotLimit).forEach(function(s, i) {
            var conceptHtml = renderConceptChips(s.concepts, s.code, s.name);
            hotHtml += '<tr class="clickable" data-code="' + s.code + '" data-name="' + s.name + '">';
            hotHtml += '<td style="color:#888;">' + (i+1) + '</td>';
            hotHtml += '<td><strong>' + s.code + '</strong></td>';
            hotHtml += '<td>' + _watchStarHtml(s.code, s.name, _watchGetCategory(s.code)) + '<span class="link-stock-name" onclick="event.stopPropagation();stockQueryGoTo(\\x27' + (s.name||'').replace(/'/g,'') + '\\x27)">' + (s.name || '') + '</span></td>';
            hotHtml += '<td style="color:#ff6b6b;font-weight:bold;">' + (s.zt_count || 0) + '次</td>';
            hotHtml += '<td><span class="score-badge ' + (s.weighted_score >= 70 ? 'score-high' : (s.weighted_score >= 40 ? 'score-mid' : 'score-low')) + '">' + (s.weighted_score || 0) + '</span></td>';
            hotHtml += '<td>' + conceptHtml + '</td>';
            hotHtml += '<td style="color:#888;font-size:0.85em;">' + (s.date_range_text || '') + '</td>';
            hotHtml += '<td>' + (s.last_zt || '') + '</td></tr>';
        });
        hotHtml += '</table>';
        if (hotStocks.length > hotLimit) {
            hotHtml += '<div style="text-align:center;color:#666;padding:6px;font-size:0.85em;">共' + hotStocks.length + '只，显示' + hotLimit + '只</div>';
        }
        html += hotHtml;
        html += '<div class="rt-section kpl-tree-node" style="margin-top:-16px;padding-top:8px;">';
        html += '<div class="kpl-header" onclick="toggleLinkageCards(this)">';
        html += '<span class="kpl-arrow">&#9660;</span>';
        html += '<span class="kpl-label" style="color:#4fc3f7;">📈 K线走势 <span class="count-badge">' + hotStocks.length + '只</span></span></div>';
        html += '<div class="kpl-children collapsed"><div class="np-card-grid" data-key="hotStocks" style="--np-cols:4;"><div class="empty" style="grid-column:1/-1;padding:12px;color:#666;">展开后加载</div></div></div></div>';
        html += '</div>';

        // === 同花顺热股Top100 ===
        html += '<div class="rt-section">';
        html += '<h3>🔥 同花顺热股Top100 <span class="count-badge">' + hotRank100.length + '只</span>' + timeHtml + '</h3>';
        html += renderHotRank100Table(hotRank100);
        html += '<div class="rt-section kpl-tree-node" style="margin-top:-16px;padding-top:8px;">';
        html += '<div class="kpl-header" onclick="toggleLinkageCards(this)">';
        html += '<span class="kpl-arrow">&#9660;</span>';
        html += '<span class="kpl-label" style="color:#4fc3f7;">📈 K线走势 <span class="count-badge">' + hotRank100.length + '只</span></span></div>';
        html += '<div class="kpl-children collapsed"><div class="np-card-grid" data-key="hotRank100" style="--np-cols:4;"><div class="empty" style="grid-column:1/-1;padding:12px;color:#666;">展开后加载</div></div></div></div>';
        html += '</div>';

        container.innerHTML = html;
        // Store data for K-line card lazy loading
        _linkageCardData['ladder'] = ladder;
        _linkageCardData['hotStocks'] = hotStocks;
        _linkageCardData['hotRank100'] = hotRank100;
        loadLuReasons();
        _fillKplPaths();
    }).catch(function(e) {
        container.innerHTML = '<div class="empty">🔍 输入股票代码或名称开始查询联动</div>';
    });
}

// ===== Linkage Tab - K-line Card Data & Rendering =====
var _linkageCardData = {};

function renderLinkageCards(stocks) {
    var html = '';
    stocks.forEach(function(s) {
        var code = s.code || '';
        var name = s.name || '';
        var concepts = s.concepts || [];
        var boardCls = _kplGetBoardClass(code);
        var ztCount = s.zt_count || s.consecutive_lianban || 0;
        var ztLabel = s.consecutive_lianban ? s.consecutive_lianban + '连板' : (s.zt_count ? s.zt_count + '次涨停' : '0涨停');

        html += '<div class="np-card ' + boardCls + '" data-code="' + code + '" data-name="' + name + '">';
        html += '<div class="np-card-header">';
        html += '<div>';
        html += '<span class="np-card-code" data-code="' + code + '" data-name="' + name + '">' + code + '</span>';
        html += '<span class="np-card-name">' + name + '</span>';
        html += '</div>';
        html += '<span class="np-card-badge lianban">' + ztLabel + '</span><button class="np-enlarge-btn" onclick="event.stopPropagation();showEnlargedCardDetail(\\x27' + code + '\\x27)" title="放大卡片">⛶</button></div>';
        html += '<div class="np-card-badges">';
        concepts.forEach(function(c) { html += '<span class="np-card-badge">' + c + '</span>'; });
        html += '</div>';
        html += '<div data-np-detail="' + code + '"><div class="empty" style="padding:8px;">\u52a0\u8f7d\u4e2d...</div></div>';
        html += '</div>';
    });
    return html;
}

function toggleLinkageCards(el) {
    var node = el.closest('.kpl-tree-node');
    if (!node) return;
    var wasCollapsed = node.classList.contains('collapsed');
    node.classList.toggle('collapsed');
    if (wasCollapsed) {
        var grid = node.querySelector('.np-card-grid');
        if (grid && !grid.querySelector('.np-card')) {
            var key = grid.getAttribute('data-key');
            if (key && _linkageCardData[key]) {
                grid.innerHTML = renderLinkageCards(_linkageCardData[key]);
                loadNpCardDetails();
            }
        }
    }
}

// 联动查询全部默认表手动刷新
function refreshLinkageAll() {
    var container = document.getElementById('linkageDefaultSections');
    if (!container) return;
    // 清除前端缓存强制重新拉取
    _clearTabCache();
    container.removeAttribute('data-loaded');
    loadLinkageDefaultSections();
}

// ===== Concept Top20 auto-load =====
var _topConceptTableLoaded = false;
function loadTopConcepts() {
    var container = document.getElementById('topConceptTable');
    if (!container) return;
    // 防止重复加载
    if (_topConceptTableLoaded) return;
    container.innerHTML = '<div class="loading" style="padding:8px;">加载热门概念...</div>';

    // 并行加载本地统计Top20 + 同花顺热门概念Top20
    Promise.all([
        _cachedFetch('/api/stats?top_n=20'),
        _cachedFetch('/api/hot_concept_20')
    ]).then(function(results) {
        var data = results[0];
        var hotConcepts = results[1] || [];
        _hotConceptsData = hotConcepts;

        _topConceptTableLoaded = true;

        // 渲染同花顺热门概念板块Top20表格
        var html = '<div class="result">';
        html += '<div style="margin-bottom:8px;color:#888;font-size:0.85em;">📈 同花顺热门概念板块 Top20 — 点击概念名称查看详细分析，或在上方搜索框输入概念</div>';
        html += renderHotConceptTable(hotConcepts);
        html += '<div style="margin-top:20px;padding:15px;background:#0d1b36;border-radius:8px;">';
        html += '<div style="color:#888;font-size:0.85em;">&#128161; 在上方搜索框输入概念（细分）名称即可搜索，支持同花顺概念和涨停理由关键词</div>';
        html += '</div>';
        html += '</div>';
        container.innerHTML = html;

        // 如果还未搜索，也填充 conceptResult 的初始内容（兼容旧版）
        var resultContainer = document.getElementById('conceptResult');
        if (!_conceptSearched && resultContainer && !resultContainer.querySelector('.result')) {
            // empty state already shown in HTML, no need to overwrite
        }
    }).catch(function(e) {
        container.innerHTML = '';
    });
}

// ===== 数据状态 =====
function loadDataStatus() {
    _cachedFetch('/api/data_status').then(function(data) {
        var el = document.getElementById('dataStatus');
        if (!el) return;
        if (data.error) { el.textContent = '数据状态加载失败'; return; }
        var minDate = data.kline_min || 'N/A';
        var maxDate = data.kline_max || 'N/A';
        var ztDays = data.zt_pool_days || 0;
        var concepts = data.concept_count || 0;
        var stocksZt = data.stock_zt_count || 0;
        var latestDate = data.latest_display || maxDate;
        el.innerHTML = 'K线数据: ' + minDate + ' ~ <strong>' + maxDate + '</strong>'
            + ' | 涨停池: ' + ztDays + '个交易日'
            + ' | 概念: ' + concepts + '个题材'
            + ' | 涨停股票: ' + stocksZt + '只'
            + ' <span style="color:#4caf50;font-size:0.9em;">&#9679; ' + latestDate + '</span>';
        el.title = '最后交易日: ' + maxDate;
    }).catch(function() {
        var el = document.getElementById('dataStatus');
        if (el) el.textContent = '数据状态加载失败';
    });
}
// ===== 更新数据 =====
function getKlineLatestDate(klines) {
    if (!klines || klines.length === 0) return '';
    var last = klines[klines.length - 1];
    return last.date || last.trade_date || '';
}

// 设置按钮状态
function setUpdateBtn(mode, hint) {
    var btn = document.getElementById('updateDataBtn');
    var hintEl = document.getElementById('updateHint');
    if (!btn) return;
    btn.className = 'status-' + mode;
    btn.disabled = (mode === 'running' || mode === 'checking');
    if (mode === 'idle') {
        btn.textContent = '🔄 更新';
    } else if (mode === 'checking') {
        btn.textContent = '⏳ 检测中';
    } else if (mode === 'running') {
        btn.textContent = '⏳ 更新中';
    } else if (mode === 'done') {
        btn.textContent = '✅';
    } else if (mode === 'error') {
        btn.textContent = '❌ 重试';
    } else if (mode === 'skip') {
        btn.textContent = '🔄 更新';
    }
    if (hintEl) {
        hintEl.textContent = hint || '';
        hintEl.className = 'hint-' + (mode === 'idle' ? 'checking' : mode);
    }
}

// 一键更新
function updateAllData() {
    var btn = document.getElementById('updateDataBtn');
    if (!btn || btn.disabled) return;
    setUpdateBtn('running', '正在启动...');
    fetch('/api/update_data').then(function(r) { return r.json(); }).then(function(data) {
        if (data.status === 'running' || data.status === 'started') {
            pollUpdateStatus();
        } else {
            setUpdateBtn('done', data.msg || '完成');
            afterUpdateDone();
        }
    }).catch(function(e) {
        setUpdateBtn('error', '请求失败: ' + e.message);
        console.error('更新数据失败:', e);
    });
}

function pollUpdateStatus() {
    var check = function() {
        fetch('/api/update_status').then(function(r) { return r.json(); }).then(function(data) {
            if (data.status === 'running') {
                setUpdateBtn('running', data.msg || '更新中...');
                setTimeout(check, 1500);
            } else {
                var msg = data.msg || '完成';
                var isError = msg.indexOf('❌') >= 0 || msg.indexOf('失败') >= 0;
                setUpdateBtn(isError ? 'error' : 'done', msg);
                afterUpdateDone(isError);
            }
        }).catch(function() {
            setTimeout(check, 2000);
        });
    };
    setTimeout(check, 800);
}

// 更新完成后：刷新数据状态 + 重置缓存 + 原地刷新当前标签页
function afterUpdateDone(isError) {
    _clearTabCache();
    loadDataStatus();  // 刷新顶部数据状态
    // 清除前端data-loaded缓存
    _topConceptTableLoaded = false;
    var ld = document.getElementById('linkageDefaultSections');
    if (ld) ld.removeAttribute('data-loaded');
    // 原地刷新当前标签页
    if (!isError) {
        if (currentTab === 'realtime') loadRealtime();
        else if (currentTab === 'npattern') loadNPattern();
        else if (currentTab === 'stats') loadStats();
        else if (currentTab === 'sniper') loadSniper();
        else if (currentTab === 'concept') { _conceptSearched = false; loadTopConcepts(); }
        else if (currentTab === 'deepsearch') {} // no-op
        else if (currentTab === 'specialwatch') loadSpecialWatch();
        else if (currentTab === 'linkage') loadLinkageDefaultSections();
    }
    // 5秒后按钮恢复
    setTimeout(function() {
        setUpdateBtn('idle', '');
    }, isError ? 30000 : 5000);
}

// 页面加载时自动检测数据状态（不拉取，仅提示）
function checkDataStatus() {
    fetch('/api/check_update').then(function(r) { return r.json(); }).then(function(data) {
        var hintEl = document.getElementById('updateHint');
        if (!hintEl) return;
        if (data.missing_dates === 0) {
            hintEl.textContent = '数据最新';
            hintEl.className = 'hint-done';
        } else if (data.market_open || data.market_settling) {
            hintEl.textContent = '盘中·数据待收';
            hintEl.className = 'hint-checking';
        } else if (data.missing_dates > 0) {
            hintEl.textContent = '缺 ' + data.missing_dates + ' 天数据';
            hintEl.className = 'hint-checking';
        }
    }).catch(function() {});
}
loadDataStatus();
checkDataStatus();
loadRealtime();
_prefetchAllTabs();
_loadKplDataEager();
// 涨停深挖搜索
var _deepSuggestTimer = null;
var _sectionReasonHits = {};
var _deepSearchHits = [];

// 默认日期：结束=今天，开始=2个月前同一天
(function() {
    var now = new Date();
    var y = now.getFullYear();
    var m = String(now.getMonth()+1).padStart(2,'0');
    var d = String(now.getDate()).padStart(2,'0');
    var endStr = y + '-' + m + '-' + d;
    var start = new Date(now);
    start.setMonth(start.getMonth() - 2);
    var sy = start.getFullYear();
    var sm = String(start.getMonth()+1).padStart(2,'0');
    var sd = String(start.getDate()).padStart(2,'0');
    var startStr = sy + '-' + sm + '-' + sd;
    var dsEl = document.getElementById('deepSearchDateStart');
    var deEl = document.getElementById('deepSearchDateEnd');
    if (dsEl) dsEl.value = startStr;
    if (deEl) deEl.value = endStr;
})();

// 辅助：解析连板数
function _parseBoardCount(tag) {
    if (!tag) return 1;
    var m;
    if (tag === '首板') return 1;
    if ((m = tag.match(/(\d+)天(\d+)板/))) return parseInt(m[2], 10);
    if ((m = tag.match(/(\d+)板/))) return parseInt(m[1], 10);
    return 1;
}

// 统计函数：按股票聚合涨停数据
function _computeDeepStats(hits) {
    var map = {};
    for (var i = 0; i < hits.length; i++) {
        var r = hits[i];
        var n = r.name || '';
        if (!map[n]) map[n] = { name: n, code: r.ts_code || '', count: 0, maxBoard: 0, lastDate: '' };
        map[n].count++;
        var d = r.trade_date || '';
        if (d > map[n].lastDate) map[n].lastDate = d;
        map[n].maxBoard = Math.max(map[n].maxBoard, _parseBoardCount(r.tag || ''));
    }
    var stats = [];
    for (var k in map) stats.push(map[k]);
    stats.sort(function(a, b) {
        return b.maxBoard - a.maxBoard || b.count - a.count || (b.lastDate > a.lastDate ? 1 : -1);
    });
    return stats;
}

// 渲染统计标签条
function _renderDeepStats(stats, totalHits) {
    var h = '<div class="text-xs" style="color:#888;margin-bottom:8px;">共 ' + totalHits + ' 条 · ' + stats.length + ' 只股票，按连板强度排序：</div>';
    h += '<div class="reason-stats">';
    for (var i = 0; i < stats.length; i++) {
        var s = stats[i];
        var boardStr = s.maxBoard > 1 ? '<span class="board' + (s.maxBoard >= 5 ? ' high' : '') + '">' + s.maxBoard + '板</span>' : '';
        var dt = (s.lastDate || '').length === 8 ? s.lastDate.slice(0,4) + '-' + s.lastDate.slice(4,6) + '-' + s.lastDate.slice(6,8) : (s.lastDate || '');
        h += '<span class="reason-stat-chip" onclick="scrollToDeepStock(\\x27' + (s.name||'').replace(/'/g, '') + '\\x27)">';
        h += '<span class="name">' + s.name + '</span>';
        h += '<span class="count">' + s.count + '次</span>' + boardStr;
        h += '<span class="dates">' + dt + '</span>';
        h += '</span>';
    }
    h += '</div>';
    return h;
}

function scrollToDeepStock(name) {
    var el = document.querySelector('tr[data-stock="' + name.replace(/'/g, '') + '"]');
    if (el) el.scrollIntoView({behavior:'smooth', block:'center'});
}

// Sina K-line图片 (同 generate_hot_html.py 一致)
function getSinaCode(ts_code) {
    if (!ts_code) return '';
    if (ts_code.startsWith('60') || ts_code.startsWith('68')) return 'sh' + ts_code.split('.')[0];
    if (ts_code.startsWith('00') || ts_code.startsWith('30')) return 'sz' + ts_code.split('.')[0];
    return 'sh' + ts_code.split('.')[0];
}
function getSinaTs() { return Date.now(); }
function sinaKlineImg(ts_code) {
    return 'https://image.sinajs.cn/newchart/daily/n/' + getSinaCode(ts_code) + '.png?' + getSinaTs();
}
function sinaMinImg(ts_code) {
    return 'https://image.sinajs.cn/newchart/min/n/' + getSinaCode(ts_code) + '.png?' + getSinaTs();
}

// 手动刷新新浪K线/分时图（btn = button element）
function reloadSinaImg(btn) {
    var img = btn.parentNode.nextElementSibling;
    if (!img) return;
    var src = img.getAttribute('data-orig-src') || img.src;
    img.src = src.replace(/\?\d*$/, '') + '?' + Date.now();
}

// 图片加载失败重试（最多3次，逐次增加延迟）
function retryImg(img, maxRetries) {
    if (maxRetries === undefined) maxRetries = 3;
    var retries = parseInt(img.getAttribute('data-retry') || '0');
    if (retries >= maxRetries) {
        var fallback = document.createElement('div');
        fallback.className = 'min-fallback';
        fallback.textContent = '暂无分时数据';
        img.parentNode.replaceChild(fallback, img);
        return;
    }
    img.setAttribute('data-retry', String(retries + 1));
    // 用新时间戳重试
    var newSrc = img.src.replace(/\?\d*$/, '') + '?' + Date.now();
    setTimeout(function() { img.src = newSrc; }, (retries + 1) * 1000);
}

// 渲染K线网格
function renderDeepKlineGrid(hits, forceTs) {
    if (!hits || hits.length === 0) return '<div class="empty" style="padding:10px 0;">暂无含代码的标的</div>';
    var seen = {};
    var unique = [];
    for (var i = 0; i < hits.length; i++) {
        var s = hits[i];
        var key = s.name || '';
        var code = s.ts_code || '';
        if (!seen[key] && code) { seen[key] = true; unique.push({name:key, code:code}); }
    }
    var rows = [];
    for (var i = 0; i < unique.length; i += 4) {
        var cells = '';
        for (var j = i; j < i + 4 && j < unique.length; j++) {
            var s = unique[j];
            var kurl = sinaKlineImg(s.code);
            var murl = sinaMinImg(s.code);
            var srcK = forceTs ? kurl.replace(/\?\d*$/, '') + '?' + forceTs : kurl;
            var srcM = forceTs ? murl.replace(/\?\d*$/, '') + '?' + forceTs : murl;
            cells += '<div class="concept-kline-cell" onclick="showEnlargedConceptCell(this)" style="cursor:pointer;">' +
                '<div class="sk-header"><span class="sk-name">' + s.name + '</span><span class="sk-code">' + s.code.replace('.SH','').replace('.SZ','') + '</span></div>' +
                '<img class="kline-img" src="' + srcK + '" onerror="retryImg(this)">' +
                '<img class="kline-img min" src="' + srcM + '" onerror="retryImg(this)">' +
                '</div>';
        }
        rows.push('<div class="concept-kline-grid">' + cells + '</div>');
    }
    return rows.join('');
}

function toggleDeepKlines(secId) {
    if (secId) {
        var wrap = document.getElementById('ds-kline-wrap-' + secId);
        if (!wrap) return;
        var isOpen = wrap.getAttribute('data-open') === '1';
        if (isOpen) {
            wrap.style.maxHeight = '0';
            wrap.setAttribute('data-open', '0');
        } else {
            if (!wrap.innerHTML.trim() && _sectionReasonHits[secId]) {
                wrap.innerHTML = renderDeepKlineGrid(_sectionReasonHits[secId]);
            }
            wrap.style.maxHeight = '10000px';
            wrap.setAttribute('data-open', '1');
        }
        return;
    }
    var wrap = document.getElementById('ds-kline-wrap-all');
    if (!wrap) return;
    var isOpen = wrap.getAttribute('data-open') === '1';
    if (isOpen) {
        wrap.style.maxHeight = '0';
        wrap.setAttribute('data-open', '0');
    } else {
        if (!wrap.innerHTML.trim() && _deepSearchHits.length > 0) {
            wrap.innerHTML = renderDeepKlineGrid(_deepSearchHits);
        }
        wrap.style.maxHeight = '10000px';
        wrap.setAttribute('data-open', '1');
    }
}

function refreshDeepKlines(secId) {
    var ts = String(Date.now());
    if (secId) {
        var wrap = document.getElementById('ds-kline-wrap-' + secId);
        if (!wrap || !_sectionReasonHits[secId]) return;
        wrap.innerHTML = renderDeepKlineGrid(_sectionReasonHits[secId], ts);
        if (wrap.getAttribute('data-open') === '1') wrap.style.maxHeight = '10000px';
        return;
    }
    var wrap = document.getElementById('ds-kline-wrap-all');
    if (!wrap || !_deepSearchHits.length) return;
    wrap.innerHTML = renderDeepKlineGrid(_deepSearchHits, ts);
    if (wrap.getAttribute('data-open') === '1') wrap.style.maxHeight = '10000px';
}

// 自动补全

document.addEventListener('DOMContentLoaded', function() {
    var dsInput = document.getElementById('deepSearchInput');
    if (dsInput) {
        dsInput.addEventListener('input', function() {
            clearTimeout(_deepSuggestTimer);
            var q = this.value.trim();
            var sugEl = document.getElementById('deepSearchSuggestions');
            if (q.length < 1) { sugEl.classList.remove('active'); return; }
            _deepSuggestTimer = setTimeout(function() {
                fetch('/api/reason_suggest?q=' + encodeURIComponent(q))
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        var html = '';
                        var stocks = data.stocks || [];
                        var concepts = data.concepts || [];
                        if (stocks.length === 0 && concepts.length === 0) {
                            sugEl.classList.remove('active');
                            return;
                        }
                        stocks.forEach(function(s) {
                            html += '<div class="suggestion-item" onclick="selectDeepSuggest(\\x27' + s.code + '\\x27, \\x27' + (s.name||'').replace(/'/g, '') + '\\x27)">';
                            html += '<span><span class="sug-code">' + s.code + '</span> ' + s.name + ' <span class="sug-meta">股票</span></span>';
                            html += '</div>';
                        });
                        concepts.forEach(function(c) {
                            html += '<div class="suggestion-item" onclick="selectDeepSuggestConcept(\\x27' + (c.concept||'').replace(/'/g, '') + '\\x27)">';
                            html += '<span>' + c.concept + ' <span class="sug-meta">概念 (' + c.count + ')</span></span>';
                            html += '</div>';
                        });
                        sugEl.innerHTML = html;
                        sugEl.classList.add('active');
                    });
            }, 300);
        });
        dsInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') doDeepSearch();
        });
    }
});

function selectDeepSuggest(code, name) {
    document.getElementById('deepSearchInput').value = name;
    document.getElementById('deepSearchSuggestions').classList.remove('active');
    doDeepSearch();
}

function selectDeepSuggestConcept(concept) {
    document.getElementById('deepSearchInput').value = concept;
    document.getElementById('deepSearchSuggestions').classList.remove('active');
    doDeepSearch();
}

function doDeepSearch() {
    var q = document.getElementById('deepSearchInput').value.trim();
    if (!q) { document.getElementById('deepSearchResult').innerHTML = '<div class="empty">输入关键词搜索涨停理由</div>'; return; }
    var dateStart = document.getElementById('deepSearchDateStart').value;
    var dateEnd = document.getElementById('deepSearchDateEnd').value;
    var el = document.getElementById('deepSearchResult');
    el.innerHTML = '<div class="loading">搜索中...</div>';
    var url = '/api/reason_search?q=' + encodeURIComponent(q);
    if (dateStart) url += '&date_start=' + encodeURIComponent(dateStart);
    if (dateEnd) url += '&date_end=' + encodeURIComponent(dateEnd);
    var noSt = document.getElementById('noStCheck');
    url += '&no_st=' + (noSt && noSt.checked ? '1' : '0');
    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            renderFullDeepSearch(data, q);
        })
        .catch(function(e) {
            el.innerHTML = '<div class="error">搜索失败: ' + e.message + '</div>';
        });
}

function _splitByBoard(rows) {
    var boards = {main_board: [], gem_star: [], other: []};
    for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        var code = (r.ts_code || '').split('.')[0];
        if (code.startsWith('00') || code.startsWith('60')) {
            boards.main_board.push(r);
        } else if (code.startsWith('30') || code.startsWith('68')) {
            boards.gem_star.push(r);
        } else {
            boards.other.push(r);
        }
    }
    return boards;
}

function _renderBoardSection(boardRows, boardSecId, boardLabel, highlightKw, secIdPrefix) {
    if (boardRows.length === 0) return '';
    var stats = _computeDeepStats(boardRows);
    var statsHtml = _renderDeepStats(stats, boardRows.length);
    var tableRows = _renderSearchTable(boardRows, highlightKw);
    var klineSecId = secIdPrefix ? secIdPrefix + '-' + boardSecId : boardSecId;
    var h = '';
    h += '<div class="board-section">';
    h += '<div class="board-section-title" style="font-weight:bold;font-size:14px;margin:10px 0 6px;color:#333;">【' + boardLabel + '】共 ' + boardRows.length + ' 只</div>';
    h += statsHtml;
    h += '<div style="display:flex;gap:6px;margin-bottom:8px;">';
    h += '<button class="concept-btn" onclick="toggleDeepKlines(\\x27' + klineSecId + '\\x27)">题材走势</button>';
    h += '<button class="concept-btn" onclick="refreshDeepKlines(\\x27' + klineSecId + '\\x27)" title="刷新K线图">⟳</button>';
    h += '</div>';
    h += '<div id="ds-kline-wrap-' + klineSecId + '" class="concept-kline-wrap" style="max-height:0;overflow:hidden"></div>';
    h += '<div style="overflow-x:auto;">';
    h += tableRows;
    h += '</div>';
    h += '</div>';
    return h;
}

function renderFullDeepSearch(data, rawQuery) {
    var results = data.results || [];
    var totalHits = data.total_hits || 0;
    var mode = data.mode || 'single';
    var keywords = data.keywords || [];
    var kwResults = data.kw_results || {};

    _deepSearchHits = results;
    _sectionReasonHits = {};

    var html = '<div class="ds-result-count">共 ' + totalHits + ' 条结果</div>';

    var boardLabels = {main_board: '主板', gem_star: '创业板/科创板', other: '其他'};

    if (mode === 'or' && keywords.length > 1) {
        // OR模式：每个关键词独立分段，其下再按板块分组
        for (var i = 0; i < keywords.length; i++) {
            var kw = keywords[i];
            var kwRows = kwResults[kw] || [];
            if (kwRows.length === 0) continue;
            var secIdPrefix = kw.replace(/[^a-zA-Z0-9\u4e00-\u9fa5]/g, '_');
            html += '<div class="or-section">';
            html += '<div class="or-section-title">🔍 "' + highlightText(kw, kw) + '" — 共 ' + kwRows.length + ' 条</div>';
            var boards = _splitByBoard(kwRows);
            var boardIds = ['main_board', 'gem_star', 'other'];
            for (var b = 0; b < boardIds.length; b++) {
                var bid = boardIds[b];
                var secId = secIdPrefix + '-' + bid;
                _sectionReasonHits[secId] = boards[bid];
                html += _renderBoardSection(boards[bid], bid, boardLabels[bid], kw, secIdPrefix);
            }
            html += '</div>';
            if (i < keywords.length - 1) html += '<hr class="or-divider">';
        }
    } else {
        // AND/单关键词模式：按板块分组
        var boards = _splitByBoard(results);
        var boardIds = ['main_board', 'gem_star', 'other'];
        for (var b = 0; b < boardIds.length; b++) {
            var bid = boardIds[b];
            _sectionReasonHits[bid] = boards[bid];
            html += _renderBoardSection(boards[bid], bid, boardLabels[bid], rawQuery, '');
        }
    }

    // 不再渲染子视图
    document.getElementById('deepSearchResult').innerHTML = html;
}

function resetDeepSearch() {
    document.getElementById('deepSearchInput').value = '';
    // 重置为默认日期
    var now = new Date();
    var de = document.getElementById('deepSearchDateEnd');
    if (de) de.value = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0');
    var start = new Date(now);
    start.setMonth(start.getMonth() - 2);
    var ds = document.getElementById('deepSearchDateStart');
    if (ds) ds.value = start.getFullYear() + '-' + String(start.getMonth()+1).padStart(2,'0') + '-' + String(start.getDate()).padStart(2,'0');
    document.getElementById('deepSearchResult').innerHTML = '<div class="empty">输入关键词和时间范围搜索涨停理由</div>';
    _deepSearchHits = [];
    _sectionReasonHits = {};
}

function _renderSearchTable(rows, highlightKw) {
    if (!rows || rows.length === 0) return '<div class="empty">无数据</div>';
    var h = '<table><thead><tr><th>日期</th><th>名称</th><th>代码</th><th>涨停理由</th><th>标记</th><th>状态</th></tr></thead><tbody>';
    for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        var date = r.trade_date || '';
        var dateDisplay = date.length === 8 ? date.slice(0,4) + '-' + date.slice(4,6) + '-' + date.slice(6,8) : date;
        var name = r.name || '';
        var code = (r.ts_code || '').replace('.SH','').replace('.SZ','').replace('.BJ','');
        var luDesc = r.lu_desc || '';
        var tag = r.tag || '';
        var status = r.status || '';
        h += '<tr data-stock="' + (name||'').replace(/'/g, '') + '">';
        h += '<td>' + dateDisplay + '</td>';
        h += '<td><span class="ds-name-link" onclick="deepSearchShowStock(\\x27' + (name||'').replace(/'/g, '') + '\\x27, \\x27' + code + '\\x27)">' + highlightText(name, highlightKw) + '</span></td>';
        h += '<td>' + code + '</td>';
        h += '<td>' + highlightText(luDesc, highlightKw) + '</td>';
        h += '<td>' + _renderTagBadge(tag) + '</td>';
        h += '<td>' + _renderStatusBadge(status) + '</td>';
        h += '</tr>';
    }
    h += '</tbody></table>';
    return h;
}

function _renderTagBadge(tag) {
    if (!tag) return '';
    var cls = 'tag-badge';
    var t = tag.trim();
    if (t === '首板') cls += ' shouban';
    else if (t === '两板' || t === '2板') cls += ' liangban';
    else if (t === '三板' || t === '3板') cls += ' sanban';
    else cls += ' gaoban';
    return '<span class="' + cls + '">' + t + '</span>';
}

function _renderStatusBadge(status) {
    if (!status) return '';
    var cls = 'status-badge';
    var s = status.trim();
    if (s.indexOf('一字') >= 0) cls += ' yizi';
    else cls += ' huan';
    return '<span class="' + cls + '">' + s + '</span>';
}

function highlightText(text, kw) {
    if (!text || !kw) return text || '';
    var words = kw.split(/[|&]/);
    var result = text;
    for (var i = 0; i < words.length; i++) {
        var w = words[i].trim();
        if (!w) continue;
        var re = new RegExp('(' + w.replace(/[.*+?^${}()|[\]\\\\]/g, '\\$&') + ')', 'gi');
        result = result.replace(re, '<span class="reason-hl">$1</span>');
    }
    return result;
}

// 弹窗显示股票详细信息（6行布局）
function deepSearchShowStock(name, ts_code, concept) {
    var code = ts_code || '';
    // 如果没传code，从 _deepSearchHits / _sectionReasonHits 查找
    if (!code) {
        var allHits = _deepSearchHits;
        for (var i = 0; i < allHits.length; i++) {
            if (allHits[i].name === name && allHits[i].ts_code) {
                code = allHits[i].ts_code;
                break;
            }
        }
        if (!code) {
            for (var k in _sectionReasonHits) {
                var rows = _sectionReasonHits[k];
                for (var i = 0; i < rows.length; i++) {
                    if (rows[i].name === name && rows[i].ts_code) {
                        code = rows[i].ts_code;
                        break;
                    }
                }
                if (code) break;
            }
        }
    }
    var cleanCode = code.replace('.SH','').replace('.SZ','').replace('.BJ','');
    var modal = document.getElementById('dsStockModal');
    var title = document.getElementById('dsStockModalTitle');
    var body = document.getElementById('dsStockModalBody');
    title.textContent = name + (cleanCode ? ' ' + cleanCode : '');
    body.innerHTML = '<div class="empty">加载中...</div>';
    modal.classList.add('active');
    if (!cleanCode) {
        body.innerHTML = '<div class="empty">暂无该股票代码</div>';
        return;
    }
    var url = '/api/stock_detail?code=' + cleanCode;
    if (concept) url += '&concept=' + encodeURIComponent(concept);
    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            renderStockDetail(data, name, cleanCode);
        })
        .catch(function() {
            body.innerHTML = '<div class="empty">数据加载失败</div>';
        });
}
function renderStockDetail(data, name, code) {
    var body = document.getElementById('dsStockModalBody');
    var html = '';
    var hasConcept = data.concept && data.concept.length > 0;
    // Row 1: KPL概念标签（替换同花顺）
    html += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">\u5f00\u76d8\u5566\u6982\u5ff5\u6807\u7b7e</div><div>';
    if (data.kpl_concepts && data.kpl_concepts.length > 0) {
        data.kpl_concepts.forEach(function(c) {
            html += '<span class="stock-detail-tag">' + c + '</span>';
        });
    } else {
        html += '<span style="color:#666;font-size:0.85em;">\u6682\u65e0\u6982\u5ff5\u6807\u7b7e</span>';
    }
    html += '</div></div>';
    // Row 2: KPL涨停记录（替换涨停理由）
    var kplRec = data.kpl_records || [];
    html += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">KPL\u6da8\u505c\u8bb0\u5f55\uff08\u5171' + kplRec.length + '\u6761\uff09</div>';
    html += '<div style="max-height:300px;overflow-y:auto;">';
    html += renderKplRecords(kplRec, code, name);
    html += '</div></div>';
    // Row 3: \u8fd13\u4e2a\u6708\u6da8\u505c\u7edf\u8ba1\uff08KPL\uff09
    var tm = data.three_month || {count:0, dates:[]};
    html += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">\u8fd13\u4e2a\u6708\u6da8\u505c\uff08KPL\uff09\uff1a\u5171' + tm.count + '\u6b21</div><div>';
    if (tm.dates && tm.dates.length > 0) {
        tm.dates.forEach(function(d) {
            var display = d.length === 8 ? d.slice(0,4) + '-' + d.slice(4,6) + '-' + d.slice(6,8) : d;
            html += '<span class="stock-detail-date-chip">' + display + '</span> ';
        });
    } else {
        html += '<span style="color:#666;font-size:0.85em;">近3个月无涨停</span>';
    }
    html += '</div></div>';
    // Row 4: 联动数据（指定了concept时显示）
    if (hasConcept && data.linkage && data.linkage.length > 0) {
        html += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">概念「' + data.concept + '」联动股票</div>';
        html += '<table><tr><th>代码</th><th>名称</th><th>同日期出现</th></tr>';
        data.linkage.forEach(function(p) {
            html += '<tr><td>' + p.stock + '</td><td>' + p.name + '</td><td style="color:#ff6b6b;font-weight:bold;">' + p.cooccurrence + '次</td></tr>';
        });
        html += '</table></div>';
    }
    // Row 5: 日K线图
    html += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">日K线图（新浪）<button class="img-refresh-btn" onclick="reloadSinaImg(this)" title="重新加载">⟳</button></div>';
    html += '<img data-orig-src="' + sinaKlineImg(code) + '" src="' + sinaKlineImg(code) + '" class="ds-stock-kline-img" loading="lazy" onerror="retryImg(this)"></div>';
    // Row 6: 分时图
    html += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">分时图（新浪）<button class="img-refresh-btn" onclick="reloadSinaImg(this)" title="重新加载">⟳</button></div>';
    html += '<img data-orig-src="' + sinaMinImg(code) + '" src="' + sinaMinImg(code) + '" class="ds-stock-kline-img" loading="lazy" onerror="retryImg(this)"></div>';
    // Row 7: 查询概念 + 查询联动按钮（交换位置，点击关闭弹框）
    html += '<div style="text-align:center;padding:8px 0;">';
    html += '<button onclick="closeDsStockModal();sqJumpToKpl(\\x27' + (name || code) + '\\x27)" style="background:#ff7043;color:#fff;border:none;padding:8px 24px;border-radius:6px;font-size:0.95em;font-weight:600;cursor:pointer;">查询概念</button>';
    html += '<button onclick="modalQueryLinkage(\\x27' + code + '\\x27)" style="margin-left:8px;background:#00d4ff;color:#0a1628;border:none;padding:8px 24px;border-radius:6px;font-size:0.95em;font-weight:600;cursor:pointer;">查询联动</button>';
    html += '</div>';
    body.innerHTML = html;
}
function modalQueryLinkage(code) {
    closeDsStockModal();
    doSearch(code, '');
}
function closeDsStockModal() {
    document.getElementById('dsStockModal').classList.remove('active');
}

// ===== KPL涨停深挖搜索 =====
var _kplSuggestTimer = null;
var _kplSectionHits = {};
var _kplSearchHits = [];

// 默认日期：结束=今天，开始=2个月前同一天
(function() {
    var now = new Date();
    var y = now.getFullYear();
    var m = String(now.getMonth()+1).padStart(2,'0');
    var d = String(now.getDate()).padStart(2,'0');
    var endStr = y + '-' + m + '-' + d;
    var start = new Date(now);
    start.setMonth(start.getMonth() - 2);
    var sy = start.getFullYear();
    var sm = String(start.getMonth()+1).padStart(2,'0');
    var sd = String(start.getDate()).padStart(2,'0');
    var startStr = sy + '-' + sm + '-' + sd;
    var dsEl = document.getElementById('kplSearchDateStart');
    var deEl = document.getElementById('kplSearchDateEnd');
    if (dsEl) dsEl.value = startStr;
    if (deEl) deEl.value = endStr;
})();

function _kplParseBoardCount(tag) {
    if (!tag) return 1;
    var m;
    if (tag === '首板') return 1;
    if ((m = tag.match(/(\d+)天(\d+)板/))) return parseInt(m[2], 10);
    if ((m = tag.match(/(\d+)板/))) return parseInt(m[1], 10);
    return 1;
}

function _kplComputeStats(hits) {
    var map = {};
    for (var i = 0; i < hits.length; i++) {
        var r = hits[i];
        var n = r.stock_name || '';
        if (!map[n]) map[n] = { name: n, code: r.stock_code || '', count: 0, maxBoard: 0, lastDate: '' };
        map[n].count++;
        var d = r.date || '';
        if (d > map[n].lastDate) map[n].lastDate = d;
        map[n].maxBoard = Math.max(map[n].maxBoard, _kplParseBoardCount(r.lianban_desc || ''));
    }
    var stats = [];
    for (var k in map) stats.push(map[k]);
    stats.sort(function(a, b) {
        return b.maxBoard - a.maxBoard || b.count - a.count || (b.lastDate > a.lastDate ? 1 : -1);
    });
    return stats;
}

function _kplRenderStats(stats, totalHits) {
    var h = '<div class="text-xs" style="color:#888;margin-bottom:8px;">共 ' + totalHits + ' 条 · ' + stats.length + ' 只股票，按连板强度排序：</div>';
    h += '<div class="reason-stats">';
    for (var i = 0; i < stats.length; i++) {
        var s = stats[i];
        var boardStr = s.maxBoard > 1 ? '<span class="board' + (s.maxBoard >= 5 ? ' high' : '') + '">' + s.maxBoard + '板</span>' : '';
        var dt = (s.lastDate || '');
        h += '<span class="reason-stat-chip" onclick="scrollToKplStock(\\x27' + (s.name||'').replace(/'/g, '') + '\\x27)">';
        h += '<span class="name">' + s.name + '</span>';
        h += '<span class="count">' + s.count + '次</span>' + boardStr;
        h += '<span class="dates">' + dt + '</span>';
        h += '</span>';
    }
    h += '</div>';
    return h;
}

function scrollToKplStock(name) {
    var el = document.querySelector('tr[data-kplstock="' + name.replace(/'/g, '') + '"]');
    if (el) el.scrollIntoView({behavior:'smooth', block:'center'});
}

function renderKplKlineGrid(hits, forceTs) {
    if (!hits || hits.length === 0) return '<div class="empty" style="padding:10px 0;">暂无含代码的标的</div>';
    var seen = {};
    var unique = [];
    for (var i = 0; i < hits.length; i++) {
        var s = hits[i];
        var key = s.stock_name || '';
        var code = s.stock_code || '';
        if (!seen[key] && code) { seen[key] = true; unique.push({name:key, code:code}); }
    }
    var rows = [];
    for (var i = 0; i < unique.length; i += 4) {
        var cells = '';
        for (var j = i; j < i + 4 && j < unique.length; j++) {
            var s = unique[j];
            var kurl = sinaKlineImg(s.code);
            var murl = sinaMinImg(s.code);
            var srcK = forceTs ? kurl.replace(/\?\d*$/, '') + '?' + forceTs : kurl;
            var srcM = forceTs ? murl.replace(/\?\d*$/, '') + '?' + forceTs : murl;
            cells += '<div class="concept-kline-cell" onclick="showEnlargedConceptCell(this)" style="cursor:pointer;">' +
                '<div class="sk-header"><span class="sk-name">' + s.name + '</span><span class="sk-code">' + s.code + '</span></div>' +
                '<img class="kline-img" src="' + srcK + '" onerror="retryImg(this)">' +
                '<img class="kline-img min" src="' + srcM + '" onerror="retryImg(this)">' +
                '</div>';
        }
        rows.push('<div class="concept-kline-grid">' + cells + '</div>');
    }
    return rows.join('');
}

function toggleKplKlines(secId) {
    if (secId) {
        var wrap = document.getElementById('kpl-kline-wrap-' + secId);
        if (!wrap) return;
        var isOpen = wrap.getAttribute('data-open') === '1';
        if (isOpen) {
            wrap.style.maxHeight = '0';
            wrap.setAttribute('data-open', '0');
        } else {
            if (!wrap.innerHTML.trim() && _kplSectionHits[secId]) {
                wrap.innerHTML = renderKplKlineGrid(_kplSectionHits[secId]);
            }
            wrap.style.maxHeight = '10000px';
            wrap.setAttribute('data-open', '1');
        }
        return;
    }
    var wrap = document.getElementById('kpl-kline-wrap-all');
    if (!wrap) return;
    var isOpen = wrap.getAttribute('data-open') === '1';
    if (isOpen) {
        wrap.style.maxHeight = '0';
        wrap.setAttribute('data-open', '0');
    } else {
        if (!wrap.innerHTML.trim() && _kplSearchHits.length > 0) {
            wrap.innerHTML = renderKplKlineGrid(_kplSearchHits);
        }
        wrap.style.maxHeight = '10000px';
        wrap.setAttribute('data-open', '1');
    }
}

function refreshKplKlines(secId) {
    var ts = String(Date.now());
    if (secId) {
        var wrap = document.getElementById('kpl-kline-wrap-' + secId);
        if (!wrap || !_kplSectionHits[secId]) return;
        wrap.innerHTML = renderKplKlineGrid(_kplSectionHits[secId], ts);
        if (wrap.getAttribute('data-open') === '1') wrap.style.maxHeight = '10000px';
        return;
    }
    var wrap = document.getElementById('kpl-kline-wrap-all');
    if (!wrap || !_kplSearchHits.length) return;
    wrap.innerHTML = renderKplKlineGrid(_kplSearchHits, ts);
    if (wrap.getAttribute('data-open') === '1') wrap.style.maxHeight = '10000px';
}

// 风向标K线走势切换
function toggleWvKlines() {
    var wrap = document.getElementById('wv-kline-wrap');
    if (!wrap) return;
    var isOpen = wrap.getAttribute('data-open') === '1';
    if (isOpen) {
        wrap.style.maxHeight = '0';
        wrap.setAttribute('data-open', '0');
    } else {
        if (!wrap.innerHTML.trim() && window._wvKlineHits) {
            wrap.innerHTML = renderKplKlineGrid(window._wvKlineHits);
        }
        wrap.style.maxHeight = '10000px';
        wrap.setAttribute('data-open', '1');
    }
}

// 盘面梳理K线走势切换
function togglePmslKlines() {
    var wrap = document.getElementById('pmsl-kline-wrap');
    if (!wrap) return;
    var isOpen = wrap.getAttribute('data-open') === '1';
    if (isOpen) {
        wrap.style.maxHeight = '0';
        wrap.setAttribute('data-open', '0');
    } else {
        if (!wrap.innerHTML.trim() && window._pmslKlineHits) {
            wrap.innerHTML = renderKplKlineGrid(window._pmslKlineHits);
        }
        wrap.style.maxHeight = '10000px';
        wrap.setAttribute('data-open', '1');
    }
}

// 风向标K线刷新
function refreshWvKlines() {
    var wrap = document.getElementById('wv-kline-wrap');
    if (!wrap || !window._wvKlineHits) return;
    var ts = String(Date.now());
    wrap.innerHTML = renderKplKlineGrid(window._wvKlineHits, ts);
    if (wrap.getAttribute('data-open') === '1') wrap.style.maxHeight = '10000px';
}

// 盘面梳理K线刷新
function refreshPmslKlines() {
    var wrap = document.getElementById('pmsl-kline-wrap');
    if (!wrap || !window._pmslKlineHits) return;
    var ts = String(Date.now());
    wrap.innerHTML = renderKplKlineGrid(window._pmslKlineHits, ts);
    if (wrap.getAttribute('data-open') === '1') wrap.style.maxHeight = '10000px';
}

// 自动补全
document.addEventListener('DOMContentLoaded', function() {
    var kplInput = document.getElementById('kplSearchInput2');
    if (kplInput) {
        kplInput.addEventListener('input', function() {
            clearTimeout(_kplSuggestTimer);
            var q = this.value.trim();
            var sugEl = document.getElementById('kplSearchSuggestions');
            if (q.length < 1) { sugEl.classList.remove('active'); return; }
            _kplSuggestTimer = setTimeout(function() {
                fetch('/api/kpl_reason_suggest?q=' + encodeURIComponent(q))
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        var html = '';
                        var stocks = data.stocks || [];
                        var tags = data.reason_tags || [];
                        var plates = data.plates || [];
                        var concepts = data.concepts || [];
                        if (stocks.length === 0 && tags.length === 0 && plates.length === 0 && concepts.length === 0) {
                            sugEl.classList.remove('active');
                            return;
                        }
                        stocks.forEach(function(s) {
                            html += '<div class="suggestion-item" onclick="selectKplSuggestStock(\\x27' + s.code + '\\x27, \\x27' + (s.name||'').replace(/'/g, '') + '\\x27)">';
                            html += '<span><span class="sug-code">' + s.code + '</span> ' + s.name + ' <span class="sug-meta">股票</span></span>';
                            html += '</div>';
                        });
                        tags.forEach(function(t) {
                            html += '<div class="suggestion-item" onclick="selectKplSuggestTag(\\x27' + (t.tag||'').replace(/'/g, '') + '\\x27)">';
                            html += '<span>' + t.tag + ' <span class="sug-meta">标签 (' + t.count + ')</span></span>';
                            html += '</div>';
                        });
                        plates.forEach(function(p) {
                            html += '<div class="suggestion-item" onclick="selectKplSuggestPlate(\\x27' + (p.plate||'').replace(/'/g, '') + '\\x27)">';
                            html += '<span>' + p.plate + ' <span class="sug-meta">板块 (' + p.count + ')</span></span>';
                            html += '</div>';
                        });
                        concepts.forEach(function(c) {
                            html += '<div class="suggestion-item" onclick="selectKplSuggestConcept(\\x27' + (c.concept||'').replace(/'/g, '') + '\\x27)">';
                            html += '<span>' + c.concept + ' <span class="sug-meta">概念 (' + c.count + ')</span></span>';
                            html += '</div>';
                        });
                        sugEl.innerHTML = html;
                        sugEl.classList.add('active');
                    });
            }, 300);
        });
        kplInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') doKplSearch();
        });
    }
});

function selectKplSuggestStock(code, name) {
    document.getElementById('kplSearchInput2').value = name;
    document.getElementById('kplSearchSuggestions').classList.remove('active');
    doKplSearch();
}
function selectKplSuggestTag(tag) {
    document.getElementById('kplSearchInput2').value = tag;
    document.getElementById('kplSearchSuggestions').classList.remove('active');
    doKplSearch();
}
function selectKplSuggestPlate(plate) {
    document.getElementById('kplSearchInput2').value = plate;
    document.getElementById('kplSearchSuggestions').classList.remove('active');
    doKplSearch();
}
function selectKplSuggestConcept(concept) {
    document.getElementById('kplSearchInput2').value = concept;
    document.getElementById('kplSearchSuggestions').classList.remove('active');
    doKplSearch();
}

function doKplSearch() {
    var q = document.getElementById('kplSearchInput2').value.trim();
    if (!q) { document.getElementById('kplSearchResult').innerHTML = '<div class="empty">输入关键词搜索KPL涨停数据</div>'; return; }
    var dateStart = document.getElementById('kplSearchDateStart').value;
    var dateEnd = document.getElementById('kplSearchDateEnd').value;
    var noSt = document.getElementById('kplNoStCheck');
    var strict = document.getElementById('kplStrictCheck');
    var el = document.getElementById('kplSearchResult');
    el.innerHTML = '<div class="loading">搜索中...</div>';
    var url = '/api/kpl_reason_search?q=' + encodeURIComponent(q);
    if (dateStart) url += '&date_start=' + encodeURIComponent(dateStart);
    if (dateEnd) url += '&date_end=' + encodeURIComponent(dateEnd);
    url += '&no_st=' + (noSt && noSt.checked ? '1' : '0');
    url += '&strict=' + (strict && strict.checked ? '1' : '0');
    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            renderFullKplSearch(data, q);
        })
        .catch(function(e) {
            el.innerHTML = '<div class="error">搜索失败: ' + e.message + '</div>';
        });
}

function _kplSplitByBoard(rows) {
    var boards = {main_board: [], gem_star: [], other: []};
    for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        var code = r.stock_code || '';
        if (code.startsWith('00') || code.startsWith('60') || code.startsWith('001') || code.startsWith('002') || code.startsWith('003')) {
            boards.main_board.push(r);
        } else if (code.startsWith('30') || code.startsWith('68') || code.startsWith('300') || code.startsWith('301') || code.startsWith('688') || code.startsWith('689')) {
            boards.gem_star.push(r);
        } else {
            boards.other.push(r);
        }
    }
    return boards;
}

function _renderKplBoardSection(boardRows, boardSecId, boardLabel, highlightKw, secIdPrefix) {
    if (boardRows.length === 0) return '';
    var stats = _kplComputeStats(boardRows);
    var statsHtml = _kplRenderStats(stats, boardRows.length);
    var tableRows = renderKplSearchTable(boardRows, highlightKw);
    var klineSecId = secIdPrefix ? secIdPrefix + '-' + boardSecId : boardSecId;
    var h = '';
    h += '<div class="board-section">';
    h += '<div class="board-section-title" style="font-weight:bold;font-size:14px;margin:10px 0 6px;color:#333;">\u3010' + boardLabel + '\u3011\u5171 ' + boardRows.length + ' \u53ea</div>';
    h += statsHtml;
    h += '<div style="display:flex;gap:6px;margin-bottom:8px;">';
    h += '<button class="concept-btn" onclick="toggleKplKlines(\\x27' + klineSecId + '\\x27)">\u9898\u6750\u8d70\u52bf</button>';
    h += '<button class="concept-btn" onclick="refreshKplKlines(\\x27' + klineSecId + '\\x27)" title="\u5237\u65b0K\u7ebf\u56fe">\u27f3</button>';
    h += '</div>';
    h += '<div id="kpl-kline-wrap-' + klineSecId + '" class="concept-kline-wrap" style="max-height:0;overflow:hidden"></div>';
    h += '<div style="overflow-x:auto;">';
    h += tableRows;
    h += '</div>';
    h += '</div>';
    return h;
}

function renderFullKplSearch(data, rawQuery) {
    var results = data.results || [];
    var totalHits = data.total_hits || 0;
    var mode = data.mode || 'single';
    var keywords = data.keywords || [];
    var kwResults = data.kw_results || {};

    _kplSearchHits = results;
    _kplSectionHits = {};

    var html = '<div class="ds-result-count">\u5171 ' + totalHits + ' \u6761\u7ed3\u679c</div>';

    var boardLabels = {main_board: '\u4e3b\u677f', gem_star: '\u521b\u4e1a\u677f/\u79d1\u521b\u677f', other: '\u5176\u4ed6'};

    if (mode === 'or' && keywords.length > 1) {
        for (var i = 0; i < keywords.length; i++) {
            var kw = keywords[i];
            var kwRows = kwResults[kw] || [];
            if (kwRows.length === 0) continue;
            var secIdPrefix = kw.replace(/[^a-zA-Z0-9\u4e00-\u9fa5]/g, '_');
            html += '<div class="or-section">';
            html += '<div class="or-section-title">"' + highlightText(kw, kw) + '" \u2014 \u5171 ' + kwRows.length + ' \u6761</div>';
            var boards = _kplSplitByBoard(kwRows);
            var boardIds = ['main_board', 'gem_star', 'other'];
            for (var b = 0; b < boardIds.length; b++) {
                var bid = boardIds[b];
                var secId = secIdPrefix + '-' + bid;
                _kplSectionHits[secId] = boards[bid];
                html += _renderKplBoardSection(boards[bid], bid, boardLabels[bid], kw, secIdPrefix);
            }
            html += '</div>';
            if (i < keywords.length - 1) html += '<hr class="or-divider">';
        }
    } else {
        var boards = _kplSplitByBoard(results);
        var boardIds = ['main_board', 'gem_star', 'other'];
        for (var b = 0; b < boardIds.length; b++) {
            var bid = boardIds[b];
            _kplSectionHits[bid] = boards[bid];
            html += _renderKplBoardSection(boards[bid], bid, boardLabels[bid], rawQuery, '');
        }
    }

    document.getElementById('kplSearchResult').innerHTML = html;
}

function renderKplSearchTable(rows, highlightKw) {
    if (!rows || rows.length === 0) return '<div class="empty">\u65e0\u6570\u636e</div>';
    var h = '<table><thead><tr><th>\u65e5\u671f</th><th>\u80a1\u7968</th><th>\u677f\u5757</th><th>\u8fde\u677f</th><th>\u6240\u5c5e\u6982\u5ff5</th><th>\u6da8\u505c\u539f\u56e0\u6807\u7b7e</th><th>\u539f\u56e0\u7b80\u8ff0</th><th>\u8be6\u60c5</th></tr></thead><tbody>';
    for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        var date = r.date || '';
        var stockName = r.stock_name || '';
        var stockCode = r.stock_code || '';
        var plateName = r.plate_name || '';
        var lianbanDesc = r.lianban_desc || '';
        var concepts = r.concepts || '';
        var reasonTag = r.reason_tag || '';
        var reasonBrief = r.reason_brief || '';
        var reasonDetail = r.reason_detail || '';

        // 连板badge
        var badgeHtml = '';
        if (lianbanDesc) {
            var bc = 'tag-badge';
            var t = lianbanDesc.trim();
            if (t === '\u9996\u677f') bc += ' shouban';
            else if (t.indexOf('\u4e8c\u677f') >= 0 || t.indexOf('2\u677f') >= 0) bc += ' liangban';
            else if (t.indexOf('\u4e09\u677f') >= 0 || t.indexOf('3\u677f') >= 0) bc += ' sanban';
            else bc += ' gaoban';
            badgeHtml = '<span class="' + bc + '">' + t + '</span>';
        }

        // 概念tags
        var conceptsHtml = '';
        if (concepts) {
            var parts = concepts.split('\u3001');
            for (var c = 0; c < parts.length; c++) {
                var cp = parts[c].trim();
                if (cp) conceptsHtml += '<span class="stock-detail-tag" style="font-size:0.75em;">' + cp + '</span> ';
            }
        }

        // 原因标签
        var tagHtml = reasonTag ? '<span style="display:inline-block;background:#e3f2fd;color:#1565c0;padding:1px 6px;border-radius:3px;font-size:0.75em;">' + reasonTag + '</span>' : '';

        h += '<tr data-kplstock="' + (stockName||'').replace(/'/g, '') + '">';
        h += '<td>' + date + '</td>';
        h += '<td><span class="ds-name-link" onclick="kplSearchShowStock(\\x27' + (stockName||'').replace(/'/g, '') + '\\x27, \\x27' + stockCode + '\\x27)">' + highlightText(stockName, highlightKw) + '</span><span style="color:#aaa;font-size:0.75em;margin-left:4px;">' + stockCode + '</span></td>';
        h += '<td>' + plateName + '</td>';
        h += '<td>' + badgeHtml + '</td>';
        h += '<td>' + conceptsHtml + '</td>';
        h += '<td>' + tagHtml + '</td>';
        h += '<td>' + highlightText(reasonBrief, highlightKw) + '</td>';
        h += '<td>' + (reasonDetail ? '<button class="detail-btn" onclick="toggleKplDetail(this)" style="background:none;border:1px solid #ddd;border-radius:3px;cursor:pointer;padding:1px 6px;font-size:0.75em;">+</button>' : '') + '</td>';
        h += '</tr>';
        if (reasonDetail) {
            h += '<tr id="kpl-detail-' + i + '" style="display:none;"><td colspan="8" style="background:#f9f9f9;font-size:0.85em;color:#555;line-height:1.5;padding:8px 12px;">' + highlightText(reasonDetail, highlightKw) + '</td></tr>';
        }
    }
    h += '</tbody></table>';
    return h;
}

function toggleKplDetail(btn) {
    var tr = btn.parentNode.parentNode;
    var detailId = tr.nextElementSibling ? tr.nextElementSibling.id : '';
    if (detailId && detailId.startsWith('kpl-detail-')) {
        var detailTr = document.getElementById(detailId);
        if (detailTr) {
            if (detailTr.style.display === 'none') {
                detailTr.style.display = 'table-row';
                btn.textContent = '-';
            } else {
                detailTr.style.display = 'none';
                btn.textContent = '+';
            }
        }
    }
}

function resetKplSearch() {
    document.getElementById('kplSearchInput2').value = '';
    var now = new Date();
    var de = document.getElementById('kplSearchDateEnd');
    if (de) de.value = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0');
    var start = new Date(now);
    start.setMonth(start.getMonth() - 2);
    var ds = document.getElementById('kplSearchDateStart');
    if (ds) ds.value = start.getFullYear() + '-' + String(start.getMonth()+1).padStart(2,'0') + '-' + String(start.getDate()).padStart(2,'0');
    document.getElementById('kplSearchResult').innerHTML = '<div class="empty">输入关键词搜索KPL涨停数据</div>';
    _kplSearchHits = [];
    _kplSectionHits = {};
}

function doKplUpdate(btn) {
    if (btn) {
        btn.disabled = true;
        btn.textContent = '检查中...';
    }
    var statusEl = document.getElementById('kplDataStatus');
    statusEl.innerHTML = '检查中...';

    // 第一步：先检查数据状态
    fetch('/api/kpl_update_data')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                statusEl.innerHTML = '<span style="color:#e53935;">检查失败</span>';
                if (btn) { btn.disabled = false; btn.textContent = '\u21bb 检查更新'; }
                return;
            }
            if (data.total_missing === 0) {
                // 数据已是最新
                statusEl.innerHTML = '<span style="color:#4caf50;">\u2713 数据已是最新</span>';
                if (btn) { btn.disabled = false; btn.textContent = '\u21bb 检查更新'; }
            } else {
                // 有缺失，显示状态后开始获取
                statusEl.innerHTML = '<span style="color:#ff9800;">\u23f3 缺少' + data.total_missing + '天数据，正在获取中...</span>';
                if (btn) { btn.textContent = '获取中...'; }
                // 第二步：发起实际获取
                fetch('/api/kpl_update_data?fetch=1')
                    .then(function(r2) { return r2.json(); })
                    .then(function(d2) {
                        if (d2.total_missing && d2.total_missing > 0) {
                            statusEl.innerHTML = '<span style="color:#ff9800;">\u23f3 获取中(最近' + d2.fetching + '天)...</span>';
                        }
                        if (btn) { btn.disabled = false; btn.textContent = '\u21bb 检查更新'; }
                        // 30秒后自动刷新状态
                        setTimeout(function() {
                            fetch('/api/kpl_update_data')
                                .then(function(r3) { return r3.json(); })
                                .then(function(d3) {
                                    var se = document.getElementById('kplDataStatus');
                                    if (d3.total_missing === 0) {
                                        se.innerHTML = '<span style="color:#4caf50;">\u2713 数据已是最新</span>';
                                    } else {
                                        se.innerHTML = '涨停原因数据 <span style="color:#999;font-size:0.9em;">(缺' + d3.total_missing + '天)</span>';
                                    }
                                }).catch(function() {});
                        }, 30000);
                    })
                    .catch(function() {
                        statusEl.innerHTML = '<span style="color:#e53935;">获取失败</span>';
                        if (btn) { btn.disabled = false; btn.textContent = '\u21bb 检查更新'; }
                    });
            }
        })
        .catch(function(e) {
            statusEl.innerHTML = '<span style="color:#e53935;">检查失败</span>';
            if (btn) { btn.disabled = false; btn.textContent = '\u21bb 检查更新'; }
        });
}

function kplSearchShowStock(name, code) {
    var cleanCode = code || '';
    if (!cleanCode) {
        var allHits = _kplSearchHits;
        for (var i = 0; i < allHits.length; i++) {
            if (allHits[i].stock_name === name && allHits[i].stock_code) {
                cleanCode = allHits[i].stock_code;
                break;
            }
        }
        if (!cleanCode) {
            for (var k in _kplSectionHits) {
                var rows = _kplSectionHits[k];
                for (var i = 0; i < rows.length; i++) {
                    if (rows[i].stock_name === name && rows[i].stock_code) {
                        cleanCode = rows[i].stock_code;
                        break;
                    }
                }
                if (cleanCode) break;
            }
        }
    }
    var modal = document.getElementById('dsStockModal');
    var title = document.getElementById('dsStockModalTitle');
    var body = document.getElementById('dsStockModalBody');
    title.textContent = name + (cleanCode ? ' ' + cleanCode : '');
    body.innerHTML = '<div class="loading">\u52a0\u8f7d\u4e2d...</div>';
    modal.classList.add('active');
    if (!cleanCode) {
        body.innerHTML = '<div class="empty">\u6682\u65e0\u8be5\u80a1\u7968\u4ee3\u7801</div>';
        return;
    }
    fetch('/api/kpl_stock_detail?code=' + cleanCode)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            renderKplStockDetail(data, name, cleanCode);
        })
        .catch(function() {
            body.innerHTML = '<div class="empty">\u6570\u636e\u52a0\u8f7d\u5931\u8d25</div>';
        });
}

function renderKplStockDetail(data, name, code) {
    var body = document.getElementById('dsStockModalBody');
    var html = '';
    // Row 1: 概念标签（同花顺）
    html += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">\u540c\u82b1\u987a\u6982\u5ff5\u6807\u7b7e</div><div>';
    if (data.ths_concepts && data.ths_concepts.length > 0) {
        data.ths_concepts.forEach(function(c) {
            html += '<span class="stock-detail-tag">' + c + '</span>';
        });
    } else {
        html += '<span style="color:#666;font-size:0.85em;">\u6682\u65e0\u6982\u5ff5\u6807\u7b7e</span>';
    }
    html += '</div></div>';
    // Row 2: KPL概念标签
    html += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">KPL\u6982\u5ff5\u6807\u7b7e</div><div>';
    if (data.concepts && data.concepts.length > 0) {
        data.concepts.forEach(function(c) {
            html += '<span class="stock-detail-tag" style="background:#fff3e0;color:#e65100;">' + c + '</span>';
        });
    } else {
        html += '<span style="color:#666;font-size:0.85em;">\u6682\u65e0KPL\u6982\u5ff5</span>';
    }
    html += '</div></div>';
    // Row 3: 历史涨停记录
    var records = data.records || [];
    html += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">\u5386\u53f2\u6da8\u505c\u8bb0\u5f55\uff08\u5171' + records.length + '\u6761\uff09</div>';
    html += '<div style="max-height:300px;overflow-y:auto;">';
    html += '<table><thead><tr><th>\u65e5\u671f</th><th>\u677f\u5757</th><th>\u8fde\u677f</th><th>\u6807\u7b7e</th><th>\u7b80\u8ff0</th></tr></thead><tbody>';
    for (var i = 0; i < records.length; i++) {
        var r = records[i];
        html += '<tr><td>' + (r.date||'') + '</td><td>' + (r.plate_name||'') + '</td><td>' + (r.lianban_desc||'') + '</td><td>' + (r.reason_tag ? '<span style="cursor:pointer;background:#e3f2fd;color:#1565c0;padding:1px 6px;border-radius:3px;" onclick="sqJumpToKpl(\\x27' + r.reason_tag.replace(/'/g, '') + '\\x27)" title="点击搜索KPL">' + r.reason_tag + '</span>' : '') + '</td><td>' + (r.reason_brief||'') + '</td></tr>';
    }
    html += '</tbody></table></div></div>';
    // Row 4: 日K线图
    html += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">\u65e5K\u7ebf\u56fe\uff08\u65b0\u6d6a\uff09<button class="img-refresh-btn" onclick="reloadSinaImg(this)" title="\u91cd\u65b0\u52a0\u8f7d">\u27f3</button></div>';
    html += '<img data-orig-src="' + sinaKlineImg(code) + '" src="' + sinaKlineImg(code) + '" class="ds-stock-kline-img" loading="lazy" onerror="retryImg(this)"></div>';
    // Row 5: 分时图
    html += '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">\u5206\u65f6\u56fe\uff08\u65b0\u6d6a\uff09<button class="img-refresh-btn" onclick="reloadSinaImg(this)" title="\u91cd\u65b0\u52a0\u8f7d">\u27f3</button></div>';
    html += '<img data-orig-src="' + sinaMinImg(code) + '" src="' + sinaMinImg(code) + '" class="ds-stock-kline-img" loading="lazy" onerror="retryImg(this)"></div>';
    // Row 6: 查询概念按钮
    html += '<div style="text-align:center;padding:8px 0;">';
    html += '<button onclick="closeDsStockModal();sqJumpToKpl(\\x27' + (name || code) + '\\x27)" style="background:#ff7043;color:#fff;border:none;padding:8px 24px;border-radius:6px;font-size:0.95em;font-weight:600;cursor:pointer;">\u67e5\u8be2\u6982\u5ff5</button>';
    html += '</div>';
    body.innerHTML = html;
}

// 实时tab点击股票 → 显示N字战法样式详细卡片（涨停理由+3月统计+日K/分时图）
var _realtimeCardFetchId = 0;
function showRealtimeCardDetail(code, name) {
    var fetchId = ++_realtimeCardFetchId;
    var modal = document.getElementById('enlargeCardModal');
    var body = document.getElementById('enlargeCardModalBody');
    // 显示加载状态
    body.innerHTML = '<div style="padding:20px;text-align:center;color:#888;">正在获取 ' + code + ' ' + name + ' 数据...</div>';
    modal.classList.add('active');

    fetch('/api/stock_detail_batch?codes=' + encodeURIComponent(code))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (fetchId !== _realtimeCardFetchId) return; // 过时fetch丢弃
            var detail = data && data[code];
            if (!detail || (!detail.kpl_records && !detail.limit_rows)) {
                body.innerHTML = '<div style="padding:20px;text-align:center;color:#888;">暂无数据</div>';
                return;
            }
            var html = '<div style="padding:12px 16px;">';
            html += '<h3 style="margin:0 0 8px 0;color:#00d4ff;">' + code + ' ' + name + ' ' + _watchStarHtml(code, name, _watchGetCategory(code)) + '</h3>';
            html += _renderCardDetailContent(code, detail, null, name);
            html += '</div>';
            body.innerHTML = html;
        })
        .catch(function() {
            if (fetchId !== _realtimeCardFetchId) return;
            body.innerHTML = '<div style="padding:20px;text-align:center;color:#888;">请求失败</div>';
        });
}

// 卡片内容放大弹框
function showEnlargedCardDetail(code) {
    var wrap = document.querySelector('.ds-card-detail-wrap[data-code="' + code + '"]');
    if (wrap) {
        _showEnlargedFromWrap(wrap);
        return;
    }
    // 无已有占位 → 按需拉取
    _fetchDetailAndShowModal(code);
}

function _showEnlargedFromWrap(wrap) {
    var modal = document.getElementById('enlargeCardModal');
    var body = document.getElementById('enlargeCardModalBody');
    var clone = wrap.cloneNode(true);
    var btn = clone.querySelector('.enlarge-card-btn');
    if (btn) btn.remove();
    clone.className = 'enlarged-card-content';
    var imgs = clone.querySelectorAll('img.ds-stock-kline-img');
    imgs.forEach(function(img) {
        var orig = img.getAttribute('data-orig-src');
        if (orig) {
            var ts = Math.floor(Date.now() / 10000);
            img.src = orig.split('?')[0] + '?' + ts;
        }
    });
    // 添加股票名称头部（放大弹窗无卡片头部）
    var code = wrap.getAttribute('data-code') || '';
    var name = wrap.getAttribute('data-name') || code;
    var header = document.createElement('div');
    header.className = 'ds-stock-kline-section';
    header.style.cssText = 'padding:4px 12px;margin-bottom:4px;display:flex;align-items:center;gap:8px;';
    header.innerHTML = '<span style="font-size:1.1em;font-weight:bold;color:#00d4ff;">' + _kplEsc(name) + '</span>' + _watchStarHtml(code, name, _watchGetCategory(code)) + '<span style="color:#666;font-size:0.85em;">' + code + '</span>';
    body.innerHTML = '';
    body.appendChild(header);
    body.appendChild(clone);
    modal.classList.add('active');
}

function _fetchDetailAndShowModal(code) {
    var modal = document.getElementById('enlargeCardModal');
    var body = document.getElementById('enlargeCardModalBody');
    body.innerHTML = '<div class="loading" style="padding:20px;text-align:center;color:#888;">\u52a0\u8f7d\u4e2d...</div>';
    modal.classList.add('active');
    fetch('/api/stock_detail_batch?codes=' + code)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var detail = data && data[code];
            if (detail && (detail.kpl_records || detail.limit_rows)) {
                var stockName = detail.name || (detail.kpl_records && detail.kpl_records.length > 0 ? detail.kpl_records[0].stock_name : '') || (detail.limit_rows && detail.limit_rows[0] ? detail.limit_rows[0].name : '') || '';
                var displayName = stockName || code;
                body.innerHTML = '<div class="ds-stock-kline-section" style="padding:4px 12px;margin-bottom:4px;display:flex;align-items:center;gap:8px;"><span style="font-size:1.1em;font-weight:bold;color:#00d4ff;">' + _kplEsc(displayName) + '</span>' + _watchStarHtml(code, displayName, _watchGetCategory(code)) + '<span style="color:#666;font-size:0.85em;">' + code + '</span></div>' + _renderCardDetailContent(code, detail, null, stockName, '');
            } else {
                body.innerHTML = '<div style="padding:20px;text-align:center;color:#888;">\u6682\u65e0\u8be5\u80a1\u7968\u8be6\u60c5\u6570\u636e</div>';
            }
        })
        .catch(function(e) {
            body.innerHTML = '<div style="padding:20px;text-align:center;color:#e94560;">\u52a0\u8f7d\u5931\u8d25: ' + e.message + '</div>';
        });
}
function closeEnlargeCardModal() {
    document.getElementById('enlargeCardModal').classList.remove('active');
    document.getElementById('enlargeCardModalBody').innerHTML = '';
}
// 题材走势网格细胞放大
function showEnlargedConceptCell(el) {
    var modal = document.getElementById('enlargeCardModal');
    var body = document.getElementById('enlargeCardModalBody');
    var clone = el.cloneNode(true);
    clone.style.cursor = 'default';
    clone.className = 'enlarged-card-content';
    var imgs = clone.querySelectorAll('img.kline-img');
    imgs.forEach(function(img) {
        var ts = Math.floor(Date.now() / 10000);
        var src = img.getAttribute('src') || '';
        img.src = src.split('?')[0] + '?' + ts;
    });
    body.innerHTML = '';
    body.appendChild(clone);
    modal.classList.add('active');
}

// 表格内同名称股票hover高亮
document.addEventListener('mouseover', function(e) {
    // 清除所有之前的高亮
    document.querySelectorAll('tr.ds-stock-hover').forEach(function(el) { el.classList.remove('ds-stock-hover'); });
    var link = e.target.closest('.ds-name-link');
    if (link) {
        var tr = link.closest('tr');
        if (tr) {
            var name = tr.getAttribute('data-stock');
            if (name) {
                document.querySelectorAll('tr[data-stock="' + name.replace(/'/g, '') + '"]').forEach(function(el) { el.classList.add('ds-stock-hover'); });
            }
        }
    }
});
document.addEventListener('mouseout', function(e) {
    if (e.target.closest('.ds-name-link')) {
        document.querySelectorAll('tr.ds-stock-hover').forEach(function(el) { el.classList.remove('ds-stock-hover'); });
    }
});

// Star click delegation
document.addEventListener('click', function(e) {
    var star = e.target.closest('.np-watch-star');
    if (star) {
        e.stopPropagation();
        e.preventDefault();
        e.stopImmediatePropagation();
        var code = star.getAttribute('data-wcode');
        var name = star.getAttribute('data-wname');
        if (code && name) _watchShowPopup(code, name, e);
        return;
    }
    // Unwatch concept from watch tab (wat-remove)
    var wremove = e.target.closest('.wat-remove');
    if (wremove) {
        e.stopPropagation();
        e.preventDefault();
        e.stopImmediatePropagation();
        var path = wremove.getAttribute('data-watch-path');
        if (path) {
            var d = _watchLoad();
            if (d.concepts[path]) {
                delete d.concepts[path];
                _watchSave(d);
                _watchRefreshConceptStars();
                if (document.getElementById('tab-specialwatch')) loadSpecialWatch();
            }
        }
        return;
    }
    var cstar = e.target.closest('.kpl-watch-star');
    if (cstar) {
        e.stopPropagation();
        e.preventDefault();
        e.stopImmediatePropagation();
        var l1 = cstar.getAttribute('data-wl1') || '';
        var l2 = cstar.getAttribute('data-wl2') || '';
        var l3 = cstar.getAttribute('data-wl3') || '';
        // Get labels from parent tree node headers
        var header = cstar.closest('.kpl-header');
        var l1Label = '', l2Label = '', l3Label = '';
        if (header) {
            var labelEls = header.querySelectorAll('.kpl-label');
            if (labelEls.length > 0) {
                if (l3) l3Label = labelEls[labelEls.length-1].textContent;
                else if (l2) l2Label = labelEls[labelEls.length-1].textContent;
                else l1Label = labelEls[labelEls.length-1].textContent;
            }
        }
        _watchToggleConcept(l1, l2, l3, l1Label, l2Label, l3Label);
        // Re-render special watch tab if active
        if (document.getElementById('tab-specialwatch') && currentTab === 'specialwatch') {
            loadSpecialWatch();
        }
        return;
    }
    // Close popup menu on outside click
    if (!e.target.closest('.watch-popup-menu')) {
        var menu = document.querySelector('.watch-popup-menu');
        if (menu) menu.remove();
    }
});

// ===== 特别关注 (Watch/Star) =====
var _watchData = null;
var _WATCH_KEY = 'stock_special_watch';
var _WATCH_COLORS = {c1:'#e94560', c2:'#42a5f5', c3:'#ff7043'};
var _WATCH_NAMES = {c1:'持仓关注', c2:'已清仓关注', c3:'热点关注'};

function _watchLoad() {
    if (_watchData) return _watchData;
    try {
        var raw = localStorage.getItem(_WATCH_KEY);
        if (raw) _watchData = JSON.parse(raw);
        if (!_watchData) _watchData = {stocks:{}, concepts:{}};
    } catch(e) { _watchData = {stocks:{}, concepts:{}}; }
    return _watchData;
}
function _watchSave(data) {
    _watchData = data;
    try { localStorage.setItem(_WATCH_KEY, JSON.stringify(data)); } catch(e) {}
}
function _watchGetCategory(code) {
    var d = _watchLoad();
    return d.stocks[code] ? d.stocks[code].category : '';
}
function _watchStarHtml(code, name, category) {
    var isWatched = !!category;
    var starChar = isWatched ? '\u2605' : '\u2606';
    var cls = 'np-watch-star';
    if (isWatched) cls += ' watched-' + category;
    return '<span class="' + cls + '" data-wcode="' + code + '" data-wname="' + name.replace(/'/g, '') + '">' + starChar + '</span>';
}
function _watchAddStock(code, name, category) {
    var d = _watchLoad();
    if (!d.stocks[code]) d.stocks[code] = {};
    d.stocks[code].name = name;
    d.stocks[code].category = category;
    _watchSave(d);
    _watchRefreshStars();
}
function _watchRemoveStock(code) {
    var d = _watchLoad();
    delete d.stocks[code];
    _watchSave(d);
    _watchRefreshStars();
}
function _watchRefreshStars() {
    document.querySelectorAll('.np-watch-star').forEach(function(el) {
        var code = el.getAttribute('data-wcode');
        if (!code) return;
        var cat = _watchGetCategory(code);
        var isWatched = !!cat;
        el.textContent = isWatched ? '\u2605' : '\u2606';
        el.className = 'np-watch-star';
        if (isWatched) el.classList.add('watched-' + cat);
    });
    // Also refresh concept stars
    _watchRefreshConceptStars();
}

// Concept watch
function _watchIsConceptWatched(l1, l2, l3) {
    var d = _watchLoad();
    var path = l1 + '|' + (l2 || '') + '|' + (l3 || '');
    return !!d.concepts[path];
}
function _watchToggleConcept(l1Key, l2Key, l3Concept, l1Label, l2Label, l3Label) {
    var d = _watchLoad();
    var l3 = l3Concept || '';
    var path = l1Key + '|' + (l2Key || '') + '|' + l3;
    if (d.concepts[path]) {
        delete d.concepts[path];
    } else {
        d.concepts[path] = {
            l1: l1Key, l2: l2Key || '', l3: l3,
            l1Label: l1Label || l1Key, l2Label: l2Label || (l2Key || ''),
            l3Label: l3Label || l3Concept || ''
        };
    }
    _watchSave(d);
    _watchRefreshConceptStars();
}
function _watchRefreshConceptStars() {
    document.querySelectorAll('.kpl-watch-star').forEach(function(el) {
        var l1 = el.getAttribute('data-wl1') || '';
        var l2 = el.getAttribute('data-wl2') || '';
        var l3 = el.getAttribute('data-wl3') || '';
        var path = l1 + '|' + l2 + '|' + l3;
        var d = _watchLoad();
        var isWatched = !!d.concepts[path];
        el.textContent = isWatched ? '\u2605' : '\u2606';
        el.className = 'kpl-watch-star';
        if (isWatched) el.classList.add('watched-concept');
    });
}
function _watchConceptStarHtml(l1Key, l2Key, l3Concept) {
    var path = l1Key + '|' + (l2Key || '') + '|' + (l3Concept || '');
    var d = _watchLoad();
    var isWatched = !!d.concepts[path];
    var starChar = isWatched ? '\u2605' : '\u2606';
    return '<span class="kpl-watch-star' + (isWatched ? ' watched-concept' : '') + '" data-wl1="' + _kplEsc(l1Key) + '" data-wl2="' + _kplEsc(l2Key||'') + '" data-wl3="' + _kplEsc(l3Concept||'') + '">' + starChar + '</span>';
}
function _watchFindConceptStocks(l1Key, l2Key, conceptName) {
    if (!_kplTreeData || !_kplNameCodeMap) return [];
    var stocks = [];
    var l1 = _kplTreeData[l1Key];
    if (!l1) return stocks;
    // If l2Key is empty, search entire L1
    var l2Keys = l2Key ? [l2Key] : Object.keys(l1);
    for (var li = 0; li < l2Keys.length; li++) {
        var items = l1[l2Keys[li]];
        if (!items) continue;
        for (var j = 0; j < items.length; j++) {
            if (!conceptName || items[j].概念 === conceptName) {
                var sarr = items[j].标的 || [];
                for (var k = 0; k < sarr.length; k++) {
                    var sname = sarr[k];
                    var scode = _kplNameCodeMap[sname] || '';
                    stocks.push({name: sname, code: scode});
                }
            }
        }
    }
    return stocks;
}

// Star click popup menu
function _watchShowPopup(code, name, event) {
    var existing = document.querySelector('.watch-popup-menu');
    if (existing) existing.remove();
    var cat = _watchGetCategory(code);
    var menu = document.createElement('div');
    menu.className = 'watch-popup-menu';
    var items = [
        {id:'c1', label:'持仓关注', color:'#e94560'},
        {id:'c2', label:'已清仓关注', color:'#42a5f5'},
        {id:'c3', label:'热点关注', color:'#ff7043'}
    ];
    items.forEach(function(it) {
        var item = document.createElement('div');
        item.className = 'watch-popup-item' + (cat === it.id ? ' watch-popup-active' : '');
        item.innerHTML = '<span class="wp-dot" style="background:' + it.color + ';"></span>' + it.label + (cat === it.id ? ' ✓' : '');
        item.onclick = function(e) {
            e.stopPropagation();
            if (cat === it.id) {
                _watchRemoveStock(code);
            } else {
                _watchAddStock(code, name, it.id);
            }
            menu.remove();
        };
        menu.appendChild(item);
    });
    // Remove option
    if (cat) {
        var sep = document.createElement('div');
        sep.className = 'watch-popup-item watch-popup-remove';
        sep.textContent = '取消关注';
        sep.onclick = function(e) {
            e.stopPropagation();
            _watchRemoveStock(code);
            menu.remove();
        };
        menu.appendChild(sep);
    }
    document.body.appendChild(menu);
    var x = event.clientX, y = event.clientY;
    // Position near click, avoid overflow
    var mw = 160, mh = menu.children.length * 36 + 8;
    if (x + mw > window.innerWidth) x = window.innerWidth - mw - 10;
    if (y + mh > window.innerHeight) y = window.innerHeight - mh - 10;
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
    // Click elsewhere to close
    setTimeout(function() {
        document.addEventListener('click', function _closePopup(ce) {
            if (!menu.contains(ce.target)) {
                menu.remove();
                document.removeEventListener('click', _closePopup);
            }
        });
    }, 10);
}

// Special Watch tab main render
function loadSpecialWatch() {
    var container = document.getElementById('specialwatchContainer');
    if (!container) return;
    var d = _watchLoad();
    var stockKeys = Object.keys(d.stocks);
    var conceptKeys = Object.keys(d.concepts);
    var html = '<div class="watch-container">';

    // Ensure KPL tree data is loaded for concept expansion
    if (conceptKeys.length > 0 && !_kplTreeData && !_kplLoading) {
        _kplLoading = true;
        _cachedFetch('/api/kpl_concept_tree').then(function(data) {
            if (data && !data.error) _kplTreeData = data;
            return _cachedFetch('/api/kpl_name_code_map');
        }).then(function(mapData) {
            _kplNameCodeMap = mapData || {};
            _kplLoading = false;
            _kplLoaded = true;
            // Re-render after data loaded
            loadSpecialWatch();
        });
        // Show loading for concept section
        html += _watchRenderStockSection(stockKeys, d);
        html += '<div class="kpl-tree-node kpl-node-l1" style="margin-bottom:16px;">';
        html += '<div class="kpl-header" onclick="_watchToggleStockSection(this)" style="cursor:pointer;padding:6px 0;">';
        html += '<span class="kpl-arrow">&#9660;</span>';
        html += '<span class="kpl-label" style="font-size:1.25em;color:#ffc107;font-weight:bold;">&#x1f3af; 关注概念 (' + conceptKeys.length + ')</span>';
        html += '</div>';
        html += '<div class="kpl-children" style="border-left:1px solid rgba(255,193,7,0.2);margin-top:6px;">';
        html += '<div class="watch-empty">加载题材数据中...</div>';
        html += '</div></div>';
        html += '</div>';
        container.innerHTML = html;
        return;
    }

    // Watched stocks section - always show
    html += _watchRenderStockSection(stockKeys, d);
    // Watched concepts section - always show
    html += '<div class="kpl-tree-node kpl-node-l1" style="margin-bottom:16px;">';
    html += '<div class="kpl-header" onclick="_watchToggleStockSection(this)" style="cursor:pointer;padding:6px 0;">';
    html += '<span class="kpl-arrow">&#9660;</span>';
    html += '<span class="kpl-label" style="font-size:1.25em;color:#ffc107;font-weight:bold;">&#x1f3af; 关注概念 (' + conceptKeys.length + ')</span>';
    html += '</div>';
    html += '<div class="kpl-children" style="border-left:1px solid rgba(255,193,7,0.2);margin-top:6px;">';
    if (conceptKeys.length > 0) {
        html += _watchRenderConceptTree(conceptKeys, d);
    } else {
        html += '<div class="watch-empty">暂无关注概念。在题材树节点上点击星标 &#9734; 添加关注。</div>';
    }
    html += '</div></div>'; // close kpl-children and kpl-tree-node

    html += '</div>';
    container.innerHTML = html;
}
function _watchRenderStockSection(stockKeys, d) {
    var html = '<div class="kpl-tree-node kpl-node-l1" style="margin-bottom:16px;">';
    html += '<div class="kpl-header" onclick="_watchToggleStockSection(this)" style="cursor:pointer;padding:6px 0;">';
    html += '<span class="kpl-arrow">&#9660;</span>';
    html += '<span class="kpl-label" style="font-size:1.25em;color:#4fc3f7;font-weight:bold;">&#x1f4c8; 关注股票 (' + stockKeys.length + ')</span>';
    html += '</div>';
    html += '<div class="kpl-children" style="border-left:1px solid rgba(79,195,247,0.2);margin-top:6px;">';
    if (stockKeys.length > 0) {
        var groups = {c1:[], c2:[], c3:[]};
        stockKeys.forEach(function(code) {
            var s = d.stocks[code];
            if (groups[s.category]) groups[s.category].push({code:code, name:s.name});
        });
        ['c1','c2','c3'].forEach(function(cat) {
            if (groups[cat].length > 0) {
                html += _watchRenderStockGroup(_WATCH_NAMES[cat], groups[cat], _WATCH_COLORS[cat]);
            }
        });
    } else {
        html += '<div class="watch-empty">暂无关注股票。在股票卡片上点击星标 &#9734; 添加关注。</div>';
    }
    html += '</div></div>';
    return html;
}
function _watchToggleStockSection(el) {
    var node = el.closest('.kpl-tree-node');
    if (!node) return;
    node.classList.toggle('collapsed');
}
function _watchRenderStockGroup(label, stocks, color) {
    var catKey = label;
    var html = '<div class="kpl-tree-node kpl-node-l1 collapsed watch-stock-group" data-watch-cat="' + catKey + '">';
    html += '<div class="kpl-header" onclick="_watchToggleStockGroup(this)" style="cursor:pointer;">';
    html += '<span class="kpl-arrow">&#9660;</span>';
    html += '<span class="kpl-label" style="color:' + color + ';">' + label + ' (' + stocks.length + ')</span>';
    html += '</div><div class="kpl-children">';
    html += '<div class="kpl-card-grid" data-watch-grid="' + catKey + '" data-watch-stocks=\\'' + JSON.stringify(stocks) + '\\' style="--np-cols:4;">';
    html += '<div class="empty" style="grid-column:1/-1;padding:12px;color:#666;font-size:0.85em;">展开后加载</div>';
    html += '</div></div></div>';
    return html;
}
function _watchToggleStockGroup(el) {
    var node = el.closest('.kpl-tree-node');
    if (!node) return;
    var wasCollapsed = node.classList.contains('collapsed');
    node.classList.toggle('collapsed');
    if (wasCollapsed) {
        var grid = node.querySelector('.kpl-card-grid[data-watch-grid]');
        if (!grid) return;
        var catLabel = node.getAttribute('data-watch-cat') || '';
        // Map category label to key
        var catKey = '';
        if (catLabel === '\u6301\u4ed3\u5173\u6ce8') catKey = 'c1';
        else if (catLabel === '\u5df2\u6e05\u4ed3\u5173\u6ce8') catKey = 'c2';
        else if (catLabel === '\u70ed\u70b9\u5173\u6ce8') catKey = 'c3';
        // Get fresh watch data
        var d = _watchLoad();
        var stocks = [];
        Object.keys(d.stocks).forEach(function(code) {
            if (d.stocks[code].category === catKey) {
                stocks.push({code: code, name: d.stocks[code].name});
            }
        });
        // Update count in header label
        var label = node.querySelector('.kpl-label');
        if (label) label.textContent = catLabel + ' (' + stocks.length + ')';
        // Re-render with current data
        grid.innerHTML = '';
        if (stocks.length === 0) {
            grid.innerHTML = '<div class="empty" style="grid-column:1/-1;padding:12px;color:#666;font-size:0.85em;">暂无关注</div>';
            return;
        }
        var html = '';
        var codesWithName = [];
        stocks.forEach(function(s) {
            var boardCls = _kplGetBoardClass(s.code);
            codesWithName.push(s.code);
            html += '<div class="np-card ' + boardCls + '" data-code="' + s.code + '" data-name="' + _kplEsc(s.name) + '" data-stock-code="' + s.code + '" data-stock-name="' + _kplEsc(s.name) + '" onclick="showEnlargedCardDetail(\\x27' + s.code + '\\x27)" style="cursor:pointer;">';
            html += '<div class="np-card-header"><div>';
            html += '<span class="np-card-code">' + s.code + '</span>';
            html += _watchStarHtml(s.code, s.name, _watchGetCategory(s.code));
            html += '<span class="np-card-name">' + _kplEsc(s.name) + '</span>';
            html += '</div>';
            html += '<div>' + _watchStarHtml(s.code, s.name, _watchGetCategory(s.code)) + '</div></div>';
            html += '<div class="np-card-badges"></div>';
            if (s.code) html += '<div class="np-detail-placeholder" data-np-code="' + s.code + '"><div class="empty" style="padding:8px;">加载详情...</div></div>';
            html += '</div>';
        });
        grid.innerHTML = html;
        if (codesWithName.length > 0) _kplLoadCardDetails(grid, codesWithName);
    }
}
function _watchRenderConceptTree(conceptKeys, d) {
    var l1Groups = {};
    conceptKeys.forEach(function(path) {
        var c = d.concepts[path];
        if (!c) return;
        if (!l1Groups[c.l1]) l1Groups[c.l1] = [];
        l1Groups[c.l1].push(c);
    });
    var html = '';
    var l1Names = Object.keys(l1Groups);
    l1Names.sort();
    l1Names.forEach(function(l1Key) {
        html += '<div class="kpl-tree-node kpl-node-l1 collapsed" style="margin-bottom:8px;">';
        html += '<div class="kpl-header" onclick="kplToggle(this)" style="cursor:pointer;"><span class="kpl-arrow">&#9660;</span>';
        html += '<span class="kpl-label" style="color:#ffc107;">' + _kplEsc(l1Key) + '</span>';
        html += '<span class="kpl-count" style="color:#ffc107;">' + l1Groups[l1Key].length + '概念</span></div>';
        html += '<div class="kpl-children" style="border-left:1px solid rgba(255,193,7,0.2);">';
        var l2Groups = {};
        l1Groups[l1Key].forEach(function(c) {
            var l2Key = c.l2 || '';
            if (!l2Groups[l2Key]) l2Groups[l2Key] = [];
            l2Groups[l2Key].push(c);
        });
        var l2Keys = Object.keys(l2Groups);
        l2Keys.sort();
        l2Keys.forEach(function(l2Key) {
            if (l2Key) {
                html += '<div class="kpl-tree-node kpl-node-l2 collapsed" style="margin-bottom:4px;">';
                html += '<div class="kpl-header" onclick="kplToggle(this)" style="cursor:pointer;"><span class="kpl-arrow">&#9660;</span>';
                html += '<span class="kpl-label">' + _kplEsc(l2Key) + '</span>';
                html += '<span class="kpl-count">' + l2Groups[l2Key].length + '概念</span></div>';
                html += '<div class="kpl-children">';
            }
            l2Groups[l2Key].forEach(function(c) {
                // Expand L1/L2-only watched concepts into individual L3 nodes
                var l3Concepts = _watchExpandConcept(c);
                l3Concepts.forEach(function(expanded) {
                    var stocks = _watchFindConceptStocks(expanded.l1, expanded.l2, expanded.l3);
                    var safeId = 'wc_' + (expanded.l1 + '_' + (expanded.l2||'') + '_' + (expanded.l3||'')).replace(/[^a-zA-Z0-9_]/g,'_');
                    _watchConceptStockMap[safeId] = stocks.map(function(s){return s.name;});
                    var label = expanded.l3Label || expanded.l3 || expanded.l2Label || expanded.l2 || expanded.l1;
                    html += '<div class="kpl-tree-node kpl-node-l3 collapsed">';
                    html += '<div class="kpl-header" onclick="_watchToggleConceptL3(this)" style="cursor:pointer;"><span class="kpl-arrow">&#9660;</span>';
                    html += '<span class="kpl-label">' + _kplEsc(label) + '</span>';
                    html += '<span class="kpl-watch-star wat-remove" data-watch-path="' + (c.l1 + '|' + (c.l2||'') + '|' + (c.l3||'')) + '" title="取消关注">\u2605</span>';
                    html += '<span class="kpl-count">' + stocks.length + '只</span></div>';
                    html += '<div class="kpl-children" style="padding-left:0;margin:4px 0 8px 12px;">';
                    html += '<div class="kpl-card-grid" data-watch-concepts="' + safeId + '" style="--np-cols:4;"><div class="empty" style="grid-column:1/-1;padding:12px;color:#666;font-size:0.85em;">展开后加载</div></div>';
                    html += '</div></div>';
                });
            });
            if (l2Key) html += '</div></div>';
        });
        html += '</div></div>';
    });
    return html;
}
function _watchExpandConcept(c) {
    // If already an L3 concept, return as-is
    if (c.l3) return [c];
    // L2-only: expand all L3s under L1|L2
    if (c.l2) {
        var results = [];
        if (!_kplTreeData || !_kplTreeData[c.l1] || !_kplTreeData[c.l1][c.l2]) return results;
        _kplTreeData[c.l1][c.l2].forEach(function(item) {
            results.push({
                l1: c.l1, l2: c.l2, l3: item.概念 || '',
                l1Label: c.l1Label || c.l1, l2Label: c.l2Label || c.l2, l3Label: item.概念 || ''
            });
        });
        return results;
    }
    // L1-only: expand all L3s under L1
    var results = [];
    if (!_kplTreeData || !_kplTreeData[c.l1]) return results;
    var l2Keys = Object.keys(_kplTreeData[c.l1]);
    l2Keys.forEach(function(l2k) {
        _kplTreeData[c.l1][l2k].forEach(function(item) {
            results.push({
                l1: c.l1, l2: l2k, l3: item.概念 || '',
                l1Label: c.l1Label || c.l1, l2Label: l2k, l3Label: item.概念 || ''
            });
        });
    });
    return results;
}
function _watchToggleConceptL3(el) {
    var node = el.closest('.kpl-tree-node');
    if (!node) return;
    var wasCollapsed = node.classList.contains('collapsed');
    node.classList.toggle('collapsed');
    if (wasCollapsed) {
        var grid = node.querySelector('.kpl-card-grid[data-watch-concepts]');
        if (grid && !grid.querySelector('.np-card')) {
            var safeId = grid.getAttribute('data-watch-concepts');
            var names = _watchConceptStockMap[safeId] || [];
            if (names.length > 0) {
                _kplRenderCards(grid, names);
            } else {
                grid.innerHTML = '<div class="empty" style="grid-column:1/-1;padding:12px;">无标的股票</div>';
            }
        }
    }
}
var _watchConceptStockMap = {};
function hexToRgb(hex) {
    var r = parseInt(hex.slice(1,2),16)*17 || parseInt(hex.slice(1,3),16);
    var g = parseInt(hex.slice(3,4),16)*17 || parseInt(hex.slice(3,5),16);
    var b = parseInt(hex.slice(5,6),16)*17 || parseInt(hex.slice(5,7),16);
    return r + ',' + g + ',' + b;
}

// ===== 开盘啦 题材概念树浏览器 =====
var _kplTreeData = null;
var _kplNameCodeMap = null;
var _kplLoaded = false;
var _kplLoading = false;
var _kplSearchTimer = null;
var _kplStockMap = {};
var _kplStockPaths = null;  // stockName -> [{l1, l2, l3}]

function _buildKplStockPaths() {
    var data = _kplTreeData;
    if (!data) return;
    _kplStockPaths = {};
    var l1Keys = Object.keys(data);
    for (var li = 0; li < l1Keys.length; li++) {
        var l1Key = l1Keys[li];
        var l2Keys = Object.keys(data[l1Key]);
        for (var l2i = 0; l2i < l2Keys.length; l2i++) {
            var l2Key = l2Keys[l2i];
            var items = data[l1Key][l2Key];
            for (var it = 0; it < items.length; it++) {
                var cname = items[it].概念 || '';
                var stocks = items[it].标的 || [];
                for (var st = 0; st < stocks.length; st++) {
                    var sn = stocks[st];
                    if (!_kplStockPaths[sn]) _kplStockPaths[sn] = [];
                    _kplStockPaths[sn].push({l1: l1Key, l2: l2Key, l3: cname});
                }
            }
        }
    }
}

function _fillKplPaths() {
    if (!_kplStockPaths) return;
    document.querySelectorAll('.kpl-paths').forEach(function(el) {
        var name = el.getAttribute('data-name');
        if (!name) return;
        var paths = _kplStockPaths[name];
        if (!paths || paths.length === 0) return;
        var parts = [];
        for (var pi = 0; pi < paths.length; pi++) {
            var p = paths[pi];
            var p1 = '<span class="kpl-path-l1" onclick="sqJumpToKpl(\\x27' + p.l1.replace(/'/g, '') + '\\x27)">' + _kplEsc(p.l1) + '</span>';
            var p2 = '<span class="kpl-path-l2" onclick="sqJumpToKpl(\\x27' + p.l2.replace(/'/g, '') + '\\x27)">' + _kplEsc(p.l2) + '</span>';
            var p3 = '<span class="kpl-path-l3" onclick="sqJumpToKpl(\\x27' + p.l3.replace(/'/g, '') + '\\x27)">' + _kplEsc(p.l3) + '</span>';
            parts.push('<span class="kpl-path-chip">' + p1 + '<span class="kpl-path-sep">›</span>' + p2 + '<span class="kpl-path-sep">›</span>' + p3 + '</span>');
        }
        el.innerHTML = '<span class="kpl-path-label" style="color:#888;margin-right:4px;">📋</span> ' + parts.join(' ');
    });
}

var _kplNodeIdx = 0;
var _kplHighlightStockName = '';

// 页面初始化时预加载KPL数据，让实时/联动表格的路径直接显示
function _loadKplDataEager() {
    if (_kplLoaded) {
        _buildKplStockPaths();
        _fillKplPaths();
        return;
    }
    _cachedFetch('/api/kpl_concept_tree').then(function(data) {
        if (data && data.error) return;
        _kplTreeData = data;
        return _cachedFetch('/api/kpl_name_code_map');
    }).then(function(mapData) {
        if (!_kplTreeData) return;
        _kplNameCodeMap = mapData || {};
        _kplLoaded = true;
        _buildKplStockPaths();
        _fillKplPaths();
    });
}

function loadKplTree() {
    var container = document.getElementById('kplTreeContainer');
    if (!container) return;
    // 数据已加载但树未渲染（来自个股查询tab的预加载）
    if (_kplTreeData && container.innerHTML.indexOf('kpl-wrapper') === -1) {
        _kplStockMap = {};
        _kplNodeIdx = 0;
        _kplRenderTree();
        return;
    }
    if (_kplLoaded) return;
    container.innerHTML = '<div class="loading">加载题材结构...</div>';

    _cachedFetch('/api/kpl_concept_tree').then(function(data) {
        if (data && data.error) { container.innerHTML = '<div class="error">加载失败</div>'; return; }
        _kplTreeData = data;
        return _cachedFetch('/api/kpl_name_code_map');
    }).then(function(mapData) {
        _kplNameCodeMap = mapData || {};
        _kplLoaded = true;
        _kplStockMap = {};
        _kplNodeIdx = 0;
        _kplRenderTree();
    });
}

function _kplRenderTree() {
    var container = document.getElementById('kplTreeContainer');
    var data = _kplTreeData;
    if (!data || data.error) { container.innerHTML = '<div class="error">无数据</div>'; return; }

    var html = '<div class="kpl-wrapper">';
    var l1Keys = Object.keys(data);
    for (var i = 0; i < l1Keys.length; i++) {
        html += _kplRenderL1(l1Keys[i], data[l1Keys[i]]);
    }
    html += '</div>';
    container.innerHTML = html;
    _kplSetupSearch();
    _kplSetupCardClicks(container);
    _buildKplStockPaths();
    _fillKplPaths();
}

var _kplSuggestionData = []; // [{label, type, ...}]

function _kplBuildSuggestionData() {
    var data = _kplTreeData;
    if (!data) return;
    var seen = {};
    _kplSuggestionData = [];
    for (var l1Key in data) {
        // Add L1 key as suggestion
        if (l1Key && !seen[l1Key]) {
            seen[l1Key] = true;
            _kplSuggestionData.push({label: l1Key, type: 'concept'});
        }
        for (var l2Key in data[l1Key]) {
            // Add L2 key as suggestion
            if (l2Key && !seen[l2Key]) {
                seen[l2Key] = true;
                _kplSuggestionData.push({label: l2Key, type: 'concept'});
            }
            var items = data[l1Key][l2Key];
            for (var i = 0; i < items.length; i++) {
                var conceptName = items[i].概念 || '';
                if (conceptName && !seen[conceptName]) {
                    seen[conceptName] = true;
                    _kplSuggestionData.push({label: conceptName, type: 'concept'});
                }
                var stocks = items[i].标的 || [];
                for (var j = 0; j < stocks.length; j++) {
                    var sname = stocks[j];
                    if (!seen[sname] && sname.indexOf('ST') === -1) {
                        seen[sname] = true;
                        _kplSuggestionData.push({label: sname, type: 'stock'});
                    }
                }
            }
        }
    }
}

function _kplSetupSearch() {
    var input = document.getElementById('kplSearchInput');
    if (!input) return;
    _kplBuildSuggestionData();

    input.oninput = function() {
        var val = this.value.trim();
        var el = document.getElementById('kplSuggestions');
        // Show autocomplete suggestions
        if (val.length >= 1 && _kplSuggestionData.length > 0) {
            var lower = val.toLowerCase();
            var matches = [];
            for (var i = 0; i < _kplSuggestionData.length; i++) {
                var item = _kplSuggestionData[i];
                if (item.label.toLowerCase().indexOf(lower) !== -1) {
                    matches.push(item);
                }
            }
            // 排序：股票在前，概念在后；同名按字母序
            matches.sort(function(a, b) {
                if (a.type !== b.type) return a.type === 'stock' ? -1 : 1;
                return a.label.localeCompare(b.label, 'zh');
            });
            // 自动补全最多展示60个
            var displayMatches = matches.slice(0, 60);
            if (displayMatches.length > 0) {
                var html = '';
                for (var i = 0; i < displayMatches.length; i++) {
                    var m = displayMatches[i];
                    var badge = m.type === 'concept' ? '概念' : '股票';
                    html += '<div class="suggestion-item" data-suggest-kpl="' + _kplEsc(m.label) + '">';
                    html += '<span>' + _kplEsc(m.label) + '</span>';
                    html += '<span class="sug-meta">' + badge + '</span></div>';
                }
                if (matches.length > displayMatches.length) {
                    html += '<div class="suggestion-item sug-more">...还有' + (matches.length - displayMatches.length) + '个匹配</div>';
                }
                el.innerHTML = html;
                el.classList.add('active');
            } else {
                el.classList.remove('active');
            }
        } else {
            el.classList.remove('active');
        }

        // Trigger search (debounced)
        clearTimeout(_kplSearchTimer);
        _kplSearchTimer = setTimeout(function() { _kplDoSearch(val); }, 300);
    };
}

function _kplRenderL1(l1Key, l1Data) {
    var l2Keys = Object.keys(l1Data);
    var l3Count = 0, stockCount = 0;
    for (var i = 0; i < l2Keys.length; i++) {
        var items = l1Data[l2Keys[i]];
        l3Count += items.length;
        for (var j = 0; j < items.length; j++) { stockCount += (items[j].标的 || []).length; }
    }
    var html = '<div class="kpl-tree-node kpl-node-l1 collapsed">';
    html += '<div class="kpl-header" onclick="kplToggle(this)"><span class="kpl-arrow">&#9660;</span>';
    html += '<span class="kpl-label">' + _kplEsc(l1Key) + '</span>';
    html += _watchConceptStarHtml(l1Key, '', '');
    html += '<span class="kpl-count">' + l2Keys.length + '子类 ' + l3Count + '概念</span>';
    html += '<span class="kpl-expand-btn" onclick="event.stopPropagation();_kplToggleSubtree(this)" title="展开/收起全部">&#xb1;</span>';
    html += '</div><div class="kpl-children">';
    for (var i = 0; i < l2Keys.length; i++) { html += _kplRenderL2(l2Keys[i], l1Data[l2Keys[i]], l1Key); }
    html += '</div></div>';
    return html;
}

function _kplRenderL2(l2Key, items, l1Key) {
    var stockCount = 0;
    for (var i = 0; i < items.length; i++) { stockCount += (items[i].标的 || []).length; }
    var html = '<div class="kpl-tree-node kpl-node-l2 collapsed">';
    html += '<div class="kpl-header" onclick="kplToggle(this)"><span class="kpl-arrow">&#9660;</span>';
    html += '<span class="kpl-label">' + _kplEsc(l2Key) + '</span>';
    html += _watchConceptStarHtml(l1Key, l2Key, '');
    html += '<span class="kpl-count">' + items.length + '概念 ' + stockCount + '只</span>';
    html += '<span class="kpl-expand-btn" onclick="event.stopPropagation();_kplToggleSubtree(this)" title="展开/收起全部">&#xb1;</span>';
    html += '</div><div class="kpl-children">';
    for (var i = 0; i < items.length; i++) { html += _kplRenderL3(items[i], l1Key, l2Key); }
    html += '</div></div>';
    return html;
}

function _kplRenderL3(item, l1Key, l2Key) {
    var conceptName = item.概念 || '';
    var stocks = item.标的 || [];
    var nodeId = _kplNodeIdx++;
    _kplStockMap[nodeId] = stocks;
    var html = '<div class="kpl-tree-node kpl-node-l3 collapsed" data-kpl-id="' + nodeId + '">';
    html += '<div class="kpl-header" onclick="kplToggleL3(this)"><span class="kpl-arrow">&#9660;</span>';
    html += '<span class="kpl-label">' + _kplEsc(conceptName) + '</span>';
    html += _watchConceptStarHtml(l1Key, l2Key, conceptName);
    html += '<span class="kpl-count">' + stocks.length + '只</span>';
    html += '<span class="kpl-expand-btn" onclick="event.stopPropagation();_kplToggleSubtree(this)" title="展开/收起全部">&#xb1;</span>';
    html += '</div><div class="kpl-children"><div class="kpl-card-grid" data-kpl-id="' + nodeId + '"></div></div></div>';
    return html;
}

function _kplEsc(s) {
    if (!s) return '';
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ===== Tree Interaction =====

function kplToggle(el) {
    var node = el.closest('.kpl-tree-node');
    if (node) node.classList.toggle('collapsed');
}

function kplToggleL3(el) {
    var node = el.closest('.kpl-tree-node');
    if (!node) return;
    var wasCollapsed = node.classList.contains('collapsed');
    node.classList.toggle('collapsed');
    if (wasCollapsed) {
        var cardGrid = node.querySelector('.kpl-card-grid');
        if (cardGrid && !cardGrid.hasChildNodes()) {
            var nodeId = parseInt(cardGrid.getAttribute('data-kpl-id'));
            if (!isNaN(nodeId)) _kplRenderCards(cardGrid, _kplStockMap[nodeId] || []);
        }
    }
}

function _kplToggleSubtree(el) {
    var header = el.closest('.kpl-header');
    var node = header.closest('.kpl-tree-node');
    var isCollapsed = node.classList.contains('collapsed');
    if (isCollapsed) {
        // 展开本节点、所有祖先节点和所有子节点（确保祖先展开后本节点可见）
        var parent = node.parentElement;
        while (parent) {
            if (parent.classList && parent.classList.contains('kpl-tree-node') && parent.classList.contains('collapsed')) {
                parent.classList.remove('collapsed');
            }
            parent = parent.parentElement;
        }
        node.classList.remove('collapsed');
        node.querySelectorAll('.kpl-tree-node').forEach(function(n) {
            n.classList.remove('collapsed');
        });
        // 渲染所有子L3的卡片，以及本节点自身的卡片（当按钮就在L3上时）
        (node.classList.contains('kpl-node-l3') ? [node] : []).concat(
            Array.from(node.querySelectorAll('.kpl-node-l3'))
        ).forEach(function(l3) {
            var cardGrid = l3.querySelector('.kpl-card-grid');
            if (cardGrid && !cardGrid.hasChildNodes()) {
                var nodeId = parseInt(cardGrid.getAttribute('data-kpl-id'));
                if (!isNaN(nodeId)) _kplRenderCards(cardGrid, _kplStockMap[nodeId] || []);
            }
        });
    } else {
        // 收起：折叠本节点和所有子节点并清除卡片
        node.classList.add('collapsed');
        node.querySelectorAll('.kpl-tree-node').forEach(function(n) {
            n.classList.add('collapsed');
        });
        node.querySelectorAll('.kpl-card-grid').forEach(function(g) { g.innerHTML = ''; });
    }
}

function _kplGetBoardClass(code) {
    if (!code || code.length < 3) return 'np-card-board-other';
    var p3 = code.substring(0, 3);
    if (p3 === '688' || p3 === '689') return 'np-card-board-kechuang';
    if (p3 === '300' || p3 === '301') return 'np-card-board-chuangye';
    if (p3 === '600' || p3 === '601' || p3 === '603' || p3 === '605' ||
        p3 === '000' || p3 === '001' ||
        p3 === '002' || p3 === '003') return 'np-card-board-zhuban';
    return 'np-card-board-other';
}

function _kplRenderCards(cardGrid, stockNames) {
    if (!stockNames || stockNames.length === 0) {
        cardGrid.innerHTML = '<div class="empty" style="grid-column:1/-1;padding:12px;">无标的股票</div>';
        return;
    }
    var html = '';
    var codesWithName = [];
    for (var i = 0; i < stockNames.length; i++) {
        var name = stockNames[i];
        var code = _kplNameCodeMap[name] || '';
        if (code) codesWithName.push(code);
        var isHighlighted = _kplHighlightStockName && name.indexOf(_kplHighlightStockName) !== -1;
        var boardCls = _kplGetBoardClass(code);
        html += '<div class="np-card ' + boardCls + (isHighlighted ? ' kpl-stock-highlight' : '') + '" data-code="' + code + '" data-name="' + _kplEsc(name) + '" data-stock-code="' + code + '" data-stock-name="' + _kplEsc(name) + '">';
        html += '<div class="np-card-header"><div>';
        html += '<span class="np-card-code" data-code="' + code + '" data-name="' + _kplEsc(name) + '">' + (code || '') + '</span>';
        html += _watchStarHtml(code, name, _watchGetCategory(code));
        html += '<span class="np-card-name">' + _kplEsc(name) + '</span>';
        html += '</div>';
        html += '<div><span class="np-card-badge lianban">0连板</span>' + (code ? '<button class="np-enlarge-btn" onclick="event.stopPropagation();showEnlargedCardDetail(\\x27' + code + '\\x27)" title="放大卡片">\u2b36</button>' : '') + '</div>';
        html += '</div>';
        html += '<div class="np-card-badges"></div>';
        if (code) {
            html += '<div class="np-detail-placeholder" data-np-code="' + code + '"><div class="empty" style="padding:8px;">加载详情...</div></div>';
        }
        html += '</div>';
    }
    cardGrid.innerHTML = html;
    if (codesWithName.length > 0) _kplLoadCardDetails(cardGrid, codesWithName);
}

function _kplLoadCardDetails(cardGrid, codes) {
    fetch('/api/stock_detail_batch?codes=' + codes.join(',')).then(function(r) { return r.json(); }).then(function(data) {
        if (!data) return;
        // Cache detail data for reuse
        for (var code in data) { _npDetailData[code] = data[code]; }
        for (var i = 0; i < codes.length; i++) {
            var code = codes[i];
            var detail = data[code];
            if (!detail) continue;
            var placeholder = cardGrid.querySelector('.np-detail-placeholder[data-np-code="' + code + '"]');
            if (!placeholder) continue;
            var card = placeholder.closest('.np-card');
            // Use _renderCardDetailContent for rich detail content
            placeholder.innerHTML = _renderCardDetailContent(code, detail, null);
            // Update lianban badge from detail data
            var ztCount = detail.zt_count || 0;
            if (card) {
                var lianbanBadge = card.querySelector('.np-card-badge.lianban');
                if (lianbanBadge) lianbanBadge.textContent = ztCount + '连板';
            }
            // Concepts badges: show all, no limit
            if (card && detail.concepts && detail.concepts.length > 0) {
                var badgeHtml = '';
                for (var k = 0; k < detail.concepts.length; k++) {
                    badgeHtml += '<span class="np-card-badge">' + _kplEsc(detail.concepts[k]) + '</span>';
                }
                card.querySelector('.np-card-badges').innerHTML = badgeHtml;
            }
        }
    }).catch(function() {});
}

function _kplSetupCardClicks(container) {
    container.addEventListener('click', function(e) {
        var codeEl = e.target.closest('.np-card-code');
        if (codeEl) {
            var code = codeEl.getAttribute('data-code');
            var name = codeEl.getAttribute('data-name');
            if (code) {
                _kplHighlightStockName = name || '';
                deepSearchShowStock(name, code);
            }
        }
    });
}

// ===== Search =====

function _kplCollapseAll() {
    var container = document.getElementById('kplTreeContainer');
    if (!container) return;
    container.querySelectorAll('.kpl-tree-node').forEach(function(n) {
        n.classList.add('collapsed');
    });
    // Clear card grids
    container.querySelectorAll('.kpl-card-grid').forEach(function(g) { g.innerHTML = ''; });
    // 清除个股高亮
    _kplHighlightStockName = '';
}

function _kplDoSearch(query) {
    query = (query || '').trim();
    var container = document.getElementById('kplTreeContainer');
    if (!container) return;

    // Collapse everything first
    _kplCollapseAll();

    // Remove old highlights
    container.querySelectorAll('.kpl-header.highlight').forEach(function(el) { el.classList.remove('highlight'); });
    var infoBar = container.querySelector('.kpl-search-info');
    if (infoBar) infoBar.remove();

    if (!query) return;

    var data = _kplTreeData;
    if (!data) return;

    // Search through L1/L2 keys and L3 concepts/stocks
    var matches = [];
    var l1Keys = Object.keys(data);
    var lowerQuery = query.toLowerCase();
    var l1KeyIndex = {};
    for (var li = 0; li < l1Keys.length; li++) { l1KeyIndex[l1Keys[li]] = li; }
    var seenMatch = {};

    for (var li = 0; li < l1Keys.length; li++) {
        var l1Key = l1Keys[li];
        var l2Data = data[l1Key];
        var l2Keys = Object.keys(l2Data);
        // L1 key match: add all items under this L1
        var l1Matched = l1Key.toLowerCase().indexOf(lowerQuery) !== -1;

        for (var l2i = 0; l2i < l2Keys.length; l2i++) {
            var l2Key = l2Keys[l2i];
            var items = l2Data[l2Key];
            // L2 key match: add all items under this L2
            var l2Matched = l2Key.toLowerCase().indexOf(lowerQuery) !== -1;

            for (var l3i = 0; l3i < items.length; l3i++) {
                var item = items[l3i];
                var mkey = l1Key + '|' + l2Key + '|' + l3i;
                if (seenMatch[mkey]) continue;

                // L1/L2 key matched → add entire branch
                if (l1Matched || l2Matched) {
                    seenMatch[mkey] = true;
                    matches.push({l1Key: l1Key, l2Key: l2Key, l3i: l3i});
                    continue;
                }

                // Original L3 concept name match
                var conceptName = item.概念 || '';
                var stocks = item.标的 || [];
                if (conceptName.toLowerCase().indexOf(lowerQuery) !== -1) {
                    seenMatch[mkey] = true;
                    matches.push({l1Key: l1Key, l2Key: l2Key, l3i: l3i});
                    continue;
                }
                // Stock name match
                for (var si = 0; si < stocks.length; si++) {
                    if (stocks[si].indexOf(query) !== -1) {
                        seenMatch[mkey] = true;
                        matches.push({l1Key: l1Key, l2Key: l2Key, l3i: l3i});
                        break;
                    }
                }
            }
        }
    }

    if (matches.length === 0) {
        var info = document.createElement('div');
        info.className = 'kpl-search-info';
        info.innerHTML = '未找到匹配 "<strong>' + _kplEsc(query) + '</strong>"';
        container.insertBefore(info, container.firstChild);
        return;
    }

    // Show search info
    var info = document.createElement('div');
    info.className = 'kpl-search-info';
    info.innerHTML = '找到 <strong>' + matches.length + '</strong> 个匹配概念';
    container.insertBefore(info, container.firstChild);

    // 设置搜索高亮个股名（卡牌匹配时高亮显示）
    _kplHighlightStockName = query;

    // Build l1Key → l1 DOM lookup
    var l1Nodes = container.querySelectorAll('.kpl-node-l1');
    var l1DomMap = {};
    l1Nodes.forEach(function(n) {
        var label = n.querySelector('.kpl-label');
        if (label) l1DomMap[label.textContent] = n;
    });

    // Expand matched nodes
    var expanded = {};
    for (var mi = 0; mi < matches.length; mi++) {
        var m = matches[mi];
        var key = m.l1Key + '|' + m.l2Key + '|' + m.l3i;
        if (expanded[key]) continue;
        expanded[key] = true;

        // Find L1 DOM node
        var l1Node = l1DomMap[m.l1Key];
        if (!l1Node) continue;
        l1Node.classList.remove('collapsed');

        // Find L2 DOM node within L1
        var l2Nodes = l1Node.querySelectorAll(':scope > .kpl-children > .kpl-node-l2');
        var foundL2 = null;
        l2Nodes.forEach(function(n) {
            var label = n.querySelector('.kpl-label');
            if (label && label.textContent === m.l2Key) foundL2 = n;
        });
        if (!foundL2) continue;
        foundL2.classList.remove('collapsed');

        // Find L3 DOM node within L2
        var l3Nodes = foundL2.querySelectorAll(':scope > .kpl-children > .kpl-node-l3');
        var foundL3 = null;
        l3Nodes.forEach(function(n) {
            var nid = parseInt(n.getAttribute('data-kpl-id'));
            var label = n.querySelector('.kpl-label');
            if (!isNaN(nid) && label) {
                var items = _kplTreeData[m.l1Key] && _kplTreeData[m.l1Key][m.l2Key];
                var matchConcept = items && items[m.l3i] ? (items[m.l3i].概念 || '') : '';
                if (label.textContent === matchConcept) foundL3 = n;
            }
        });
        if (!foundL3) continue;
        foundL3.classList.remove('collapsed');

        // Highlight L3 header
        var header = foundL3.querySelector('.kpl-header');
        if (header) header.classList.add('highlight');

        // Render cards for this L3
        var nodeId = parseInt(foundL3.getAttribute('data-kpl-id'));
        if (!isNaN(nodeId)) {
            var cardGrid = foundL3.querySelector('.kpl-card-grid');
            if (cardGrid) _kplRenderCards(cardGrid, _kplStockMap[nodeId] || []);
        }
    }
}

// ===== 个股查询 Tab =====
var _sqSuggestTimer = null;
(function() {
    var sqInput = document.getElementById('stockQueryInput');
    if (!sqInput) return;
    sqInput.addEventListener('input', function() {
        var self = this;
        if (_sqSuggestTimer) clearTimeout(_sqSuggestTimer);
        _sqSuggestTimer = setTimeout(function() {
            var q = self.value.trim();
            var el = document.getElementById('stockQuerySuggestions');
            if (q.length < 1) { el.classList.remove('active'); return; }
            fetch('/api/stock_search?q=' + encodeURIComponent(q))
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (!data || data.length === 0) { el.classList.remove('active'); return; }
                    var html = '';
                    data.forEach(function(s) {
                        html += '<div class="suggestion-item" onclick="stockQuerySelect(\\x27' + s.code + '\\x27, \\x27' + (s.name||'').replace(/'/g, '') + '\\x27)">';
                        html += '<span><span class="sug-code">' + s.code + '</span> ' + s.name + '</span>';
                        html += '</div>';
                    });
                    el.innerHTML = html;
                    el.classList.add('active');
                })
                .catch(function() { el.classList.remove('active'); });
        }, 200);
    });
    sqInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') stockQueryDoSearch();
    });
})();

function stockQuerySelect(code, name) {
    document.getElementById('stockQuerySuggestions').classList.remove('active');
    document.getElementById('stockQueryInput').value = name || code;
    stockQueryFetch(code);
}
function stockQueryDoSearch() {
    var input = document.getElementById('stockQueryInput');
    var val = input.value.trim();
    if (!val) return;
    var codeMatch = val.match(/(\\d{6})/);
    if (codeMatch) { stockQueryFetch(codeMatch[1]); return; }
    fetch('/api/stock_search?q=' + encodeURIComponent(val))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data && data.length > 0) {
                stockQueryFetch(data[0].code, data[0].name);
            } else {
                document.getElementById('stockQueryResult').innerHTML = '<div class="empty">未找到该股票</div>';
            }
        });
}
function stockQuerySearchName(name) {
    fetch('/api/stock_search?q=' + encodeURIComponent(name))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data && data.length > 0) {
                stockQueryFetch(data[0].code);
            }
        });
}

// 联动查询点击股票名称 → 跳转到个股查询
function stockQueryGoTo(name) {
    switchTab('stockquery');
    var input = document.getElementById('stockQueryInput');
    if (input) { input.value = name; stockQueryDoSearch(); }
}
function stockQueryFetch(code) {
    var container = document.getElementById('stockQueryResult');
    container.innerHTML = '<div class="loading">加载中...</div>';
    // Ensure KPL tree is loaded
    var kplPromise;
    if (!_kplLoaded) {
        kplPromise = _cachedFetch('/api/kpl_concept_tree').then(function(data) {
            if (data && !data.error) {
                _kplTreeData = data;
                return _cachedFetch('/api/kpl_name_code_map');
            }
        }).then(function(mapData) {
            if (mapData) _kplNameCodeMap = mapData;
            _kplLoaded = true;
        });
    } else {
        kplPromise = Promise.resolve();
    }
    Promise.all([
        kplPromise,
        fetch('/api/stock_detail?code=' + encodeURIComponent(code)).then(function(r) { return r.json(); })
    ]).then(function(results) {
        var data = results[1];
        var name = data.name || '';
        _kplHighlightStockName = name;
        container.innerHTML = renderStockQueryPage(data, code, name);
    }).catch(function() {
        container.innerHTML = '<div class="empty">数据加载失败</div>';
    });
}
function renderStockQueryPage(data, code, name) {
    var h = '<div class="sq-header"><h2>' + (name || '') + ' ' + _watchStarHtml(code, name, _watchGetCategory(code)) + '</h2><span class="sq-code">' + code + '</span></div>';
    // KPL概念标签（替换同花顺）
    h += '<div class="sq-concepts"><div class="sq-concepts-label">\u5f00\u76d8\u5566\u6982\u5ff5\u6807\u7b7e</div><div>';
    if (data.kpl_concepts && data.kpl_concepts.length > 0) {
        data.kpl_concepts.forEach(function(c) {
            h += '<span class="stock-detail-tag" style="background:#2a3f5f;border-color:#4a6f9f;">' + c + '</span>';
        });
    } else {
        h += '<span style="color:#666;font-size:0.85em;">暂无概念标签</span>';
    }
    h += '</div></div>';
    // KPL涨停记录（替换同花顺涨停理由）
    h += '<div class="sq-section"><div class="sq-section-title">KPL涨停记录</div>';
    h += '<div style="max-height:300px;overflow-y:auto;">';
    h += renderKplRecords(data.kpl_records, code, name);
    h += '</div></div>';
    var tm = data.three_month || {count:0, dates:[]};
    h += '<div class="sq-section"><div class="sq-section-title">近3个月涨停：共' + tm.count + '次</div><div>';
    if (tm.dates && tm.dates.length > 0) {
        tm.dates.forEach(function(d) {
            var display = d.length === 8 ? d.slice(0,4) + '-' + d.slice(4,6) + '-' + d.slice(6,8) : d;
            h += '<span class="stock-detail-date-chip">' + display + '</span> ';
        });
    } else {
        h += '<span style="color:#666;font-size:0.85em;">近3个月无涨停</span>';
    }
    h += '</div></div>';
    // K-line + Intraday side by side
    h += '<div class="sq-kline-row">';
    h += '<div class="sq-kline-col"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;"><span style="color:#aaa;font-size:0.85em;">日K线图</span><button class="img-refresh-btn" onclick="reloadSinaImg(this)" title="重新加载">&#x27f3;</button></div>';
    h += '<img data-orig-src="' + sinaKlineImg(code) + '" src="' + sinaKlineImg(code) + '" class="ds-stock-kline-img" loading="lazy" onerror="retryImg(this)"></div>';
    h += '<div class="sq-kline-col"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;"><span style="color:#aaa;font-size:0.85em;">分时图</span><button class="img-refresh-btn" onclick="reloadSinaImg(this)" title="重新加载">&#x27f3;</button></div>';
    h += '<img data-orig-src="' + sinaMinImg(code) + '" src="' + sinaMinImg(code) + '" class="ds-stock-kline-img" loading="lazy" onerror="retryImg(this)"></div>';
    h += '</div>';
    // KPL concept tree
    h += '<div class="sq-section"><div class="sq-section-title">开盘啦题材树</div>';
    if (typeof _kplTreeData !== 'undefined' && _kplTreeData) {
        var stockName = name;
        var treeHtml = renderStockQueryKplTree(stockName);
        if (treeHtml) {
            h += treeHtml;
        } else {
            h += '<div style="color:#666;font-size:0.85em;padding:8px 0;">该股票未出现在开盘啦概念树中</div>';
        }
    } else {
        h += '<div style="color:#666;font-size:0.85em;">概念树数据未加载</div>';
    }
    h += '</div>';
    // Concept query + linkage buttons (swapped order)
    h += '<div style="text-align:center;padding:16px 0;">';
    h += '<button onclick="sqJumpToKpl(\\x27' + (name || code) + '\\x27)" style="background:#ff7043;color:#fff;border:none;padding:8px 24px;border-radius:6px;font-size:0.95em;font-weight:600;cursor:pointer;">查询概念</button>';
    h += '<button onclick="switchTab(\\x27linkage\\x27);setTimeout(function(){document.getElementById(\\x27linkageStockInput\\x27).value=\\x27' + code + '\\x27;doLinkageSearch();},100)" style="margin-left:8px;background:#00d4ff;color:#0a1628;border:none;padding:8px 24px;border-radius:6px;font-size:0.95em;font-weight:600;cursor:pointer;">查询联动</button>';
    h += '</div>';
    return h;
}
function renderKplRecords(records, code, name) {
    if (!records || records.length === 0) return '<div class="empty">\u65e0KPL\u6da8\u505c\u8bb0\u5f55</div>';
    var h = '<table><thead><tr><th>\u65e5\u671f</th><th>\u80a1\u7968</th><th>\u677f\u5757</th><th>\u8fde\u677f</th><th>\u6240\u5c5e\u6982\u5ff5</th><th>\u6da8\u505c\u539f\u56e0\u6807\u7b7e</th><th>\u539f\u56e0\u7b80\u8ff0</th></tr></thead><tbody>';
    for (var i = 0; i < records.length; i++) {
        var r = records[i];
        var date = r.date || \x27\x27;
        var stockName = r.stock_name || name || \x27\x27;
        var stockCode = r.stock_code || code || \x27\x27;
        var plateName = r.plate_name || \x27\x27;
        var lianbanDesc = r.lianban_desc || \x27\x27;
        var concepts = r.concepts || \x27\x27;
        var reasonTag = r.reason_tag || \x27\x27;
        var reasonBrief = r.reason_brief || \x27\x27;

        // \u8fde\u677fbadge
        var badgeHtml = \x27\x27;
        if (lianbanDesc) {
            var bc = \x27tag-badge\x27;
            var t = lianbanDesc.trim();
            if (t === \x27\u9996\u677f\x27) bc += \x27 shouban\x27;
            else if (t.indexOf(\x27\u4e8c\u677f\x27) >= 0 || t.indexOf(\x272\u677f\x27) >= 0) bc += \x27 liangban\x27;
            else if (t.indexOf(\x27\u4e09\u677f\x27) >= 0 || t.indexOf(\x273\u677f\x27) >= 0) bc += \x27 sanban\x27;
            else bc += \x27 gaoban\x27;
            badgeHtml = \x27<span class="\x27 + bc + \x27">\x27 + t + \x27</span>\x27;
        }

        // \u6982\u5ff5tags
        var conceptsHtml = \x27\x27;
        if (concepts) {
            var parts = concepts.split(\x27\u3001\x27);
            for (var ci = 0; ci < parts.length; ci++) {
                var cp = parts[ci].trim();
                if (cp) conceptsHtml += \x27<span class="stock-detail-tag" style="font-size:0.75em;cursor:pointer;" onclick="sqJumpToKpl(\\x27\x27 + cp.replace(/'/g, \x27\x27) + \x27\\x27)" title="\u70b9\u51fb\u641c\u7d22KPL\uff1a\x27 + cp + \x27">\x27 + cp + \x27</span> \x27;
            }
        }

        // \u539f\u56e0\u6807\u7b7e
        var tagHtml = reasonTag ? \x27<span style="display:inline-block;background:#e3f2fd;color:#1565c0;padding:1px 6px;border-radius:3px;font-size:0.75em;cursor:pointer;" onclick="sqJumpToKpl(\\x27\x27 + reasonTag.replace(/'/g, \x27\x27) + \x27\\x27)" title="\u70b9\u51fb\u641c\u7d22KPL\uff1a\x27 + reasonTag + \x27">\x27 + reasonTag + \x27</span>\x27 : \x27\x27;

        h += \x27<tr>\x27;
        h += \x27<td>\x27 + date + \x27</td>\x27;
        h += \x27<td><span class="ds-name-link" onclick="stockQueryFetch(\\x27\x27 + stockCode + \x27\\x27)">\x27 + stockName + \x27</span><span style="color:#aaa;font-size:0.75em;margin-left:4px;">\x27 + stockCode + \x27</span></td>\x27;
        h += \x27<td>\x27 + plateName + \x27</td>\x27;
        h += \x27<td>\x27 + badgeHtml + \x27</td>\x27;
        h += \x27<td>\x27 + conceptsHtml + \x27</td>\x27;
        h += \x27<td>\x27 + tagHtml + \x27</td>\x27;
        h += \x27<td style="color:#b0bec5;font-size:0.85em;">\x27 + reasonBrief + \x27</td>\x27;
        h += \x27</tr>\x27;
    }
    h += \x27</tbody></table>\x27;
    return h;
}
function sqJumpToKpl(term) {
    switchTab('kpltree');
    // 直接渲染树，无视 _kplLoaded，只检查容器是否已有渲染
    if (_kplTreeData) {
        var container = document.getElementById('kplTreeContainer');
        if (container && container.innerHTML.indexOf('kpl-wrapper') === -1) {
            _kplStockMap = {};
            _kplNodeIdx = 0;
            _kplRenderTree();
        }
    }
    var input = document.getElementById('kplSearchInput');
    if (input) {
        input.value = term;
        _kplDoSearch(term);
    }
}

// ===== ETF基金 =====
var _etfLoaded = false;
var _etfData = null;
var _etfObserver = null;

function getEtfSinaCode(code) {
    if (!code) return '';
    var c = code.toString().padStart(6, '0');
    if (c.startsWith('51') || c.startsWith('56') || c.startsWith('58')) return 'sh' + c;
    return 'sz' + c;
}
function etfKlineImg(code) { return 'https://image.sinajs.cn/newchart/daily/n/' + getEtfSinaCode(code) + '.png?' + getSinaTs(); }
function etfMinImg(code) { return 'https://image.sinajs.cn/newchart/min/n/' + getEtfSinaCode(code) + '.png?' + getSinaTs(); }

// ETF关注（自选）管理
var _watchList = JSON.parse(localStorage.getItem('etf_watch_list') || '[]');
function isWatchEtf(code) { return _watchList.indexOf(code) !== -1; }
function toggleWatchEtf(code) {
    var idx = _watchList.indexOf(code);
    if (idx === -1) _watchList.push(code);
    else _watchList.splice(idx, 1);
    localStorage.setItem('etf_watch_list', JSON.stringify(_watchList));
    // Refresh watchlist display if rendered
    renderWatchlist();
}
function renderWatchlist() {
    var wl = document.getElementById('etfWatchlist');
    if (!wl) return;
    if (!_watchList.length) { wl.innerHTML = '<div class="empty" style="padding:20px;color:#546e7a;">点击ETF卡片的星标添加到关注</div>'; return; }
    // Build map from _etfData
    var map = {};
    if (_etfData) _etfData.forEach(function(it) { map[it.code] = it; });
    var items = [];
    _watchList.forEach(function(code) {
        var it = map[code];
        if (it) items.push(it);
    });
    items.sort(function(a, b) { return b.change_pct - a.change_pct; });
    var h = '<div class="etf-watch-grid">';
    items.forEach(function(it) {
        var code = it.code || '';
        var name = it.name || '';
        var price = it.price != null ? it.price.toFixed(3) : '--';
        var chg = it.change_pct || 0;
        var chgStr = (chg > 0 ? '+' : '') + chg.toFixed(2) + '%';
        var chgClass = chg > 0 ? 'etf-change-up' : (chg < 0 ? 'etf-change-down' : 'etf-change-zero');
        var klineSrc = etfKlineImg(code);
        var minSrc = etfMinImg(code);
        h += '<div class="etf-watch-card" data-name="' + name + '" data-code="' + code + '" onclick="showEtfDetail(this)"><div class="etf-watch-header"><span class="etf-card-name" title="' + name + '">' + name + '</span><span class="etf-card-code">' + code + '</span><span class="etf-watch-star etf-watch-star-on" onclick="event.stopPropagation();toggleWatchEtf(\\x27' + code + '\\x27)" title="取消关注">\\u2605</span></div>';
        h += '<div class="etf-card-price"><span class="etf-card-price-val">' + price + '</span></div>';
        h += '<div style="margin:2px 0;"><span class="' + chgClass + '" style="font-size:0.9em;font-weight:bold;">' + chgStr + '</span></div>';
        h += '<div class="etf-charts"><div class="etf-chart-col"><div class="mini-label">\\u65E5K</div><img src="' + klineSrc + '" loading="lazy" onerror="retryImg(this,2)" style="cursor:pointer;" onclick="reloadSinaImg(this)" data-orig-src="' + klineSrc + '"></div>';
        h += '<div class="etf-chart-col"><div class="mini-label">\\u5206\\u65F6</div><img src="' + minSrc + '" loading="lazy" onerror="retryImg(this,2)" style="cursor:pointer;" onclick="reloadSinaImg(this)" data-orig-src="' + minSrc + '"></div></div></div>';
    });
    h += '</div>';
    wl.innerHTML = h;
}


function loadEtfData() {
    // Clear any existing ETF auto-refresh when re-loading
    if (_etfAutoRefreshCountdown) {
        clearInterval(_etfAutoRefreshTimer);
        clearInterval(_etfAutoRefreshCountdown);
        _etfAutoRefreshActive = false;
        _etfAutoRefreshTimer = null;
        _etfAutoRefreshCountdown = null;
        var abBtn = document.getElementById('etfAutoRefreshBtn');
        if (abBtn) { abBtn.innerHTML = '\u23f1 \u81ea\u52a8\u5237\u65b0 5\u5206\u949f'; abBtn.classList.remove('active'); }
    }
    if (_etfLoaded && _etfData) { renderEtfTab(_etfData); return; }
    var container = document.getElementById('etfContainer');
    container.innerHTML = '<div class="loading">加载ETF数据...</div>';
    fetch('/api/etf_spot').then(function(r) { return r.json(); }).then(function(data) {
        _etfData = data;
        _etfLoaded = true;
        renderEtfTab(data);
    }).catch(function(err) {
        container.innerHTML = '<div class="empty">加载ETF数据失败: ' + err + '</div>';
    });
}
function renderEtfTab(data) {
    var container = document.getElementById('etfContainer');
    if (!data || !data.length) { container.innerHTML = '<div class="empty">暂无ETF数据</div>'; return; }
    var total = data.length;
    var upCount = 0, downCount = 0, zeroCount = 0;
    // Build nested map: category -> subcategory -> items[]
    var cats = {};
    data.forEach(function(item) {
        if (item.change_pct > 0) upCount++;
        else if (item.change_pct < 0) downCount++;
        else zeroCount++;
        var cat = item.category || '\u5176\u4ed6';
        var sub = item.subcategory || '\u5176\u4ed6';
        if (!cats[cat]) cats[cat] = {};
        if (!cats[cat][sub]) cats[cat][sub] = [];
        cats[cat][sub].push(item);
    });
    // Refresh banner with stats and controls
    var h = '<div class="refresh-banner" style="display:flex;align-items:center;justify-content:center;gap:8px;flex-wrap:wrap;">';
    h += '<span>ETF\u603b\u6570 <strong>' + total + '</strong> | \u4e0a\u6da8 <strong style="color:#fff;background:#e53935;padding:1px 6px;border-radius:8px;">' + upCount + '</strong> | \u4e0b\u8dcc <strong style="color:#fff;background:#1e88e5;padding:1px 6px;border-radius:8px;">' + downCount + '</strong></span>';
    h += '<span class="rt-refresh-icon" onclick="manualRefreshEtf()" title="\u624b\u52a8\u5237\u65b0ETF\u6570\u636e" style="opacity:0.7;margin:0 4px;">\u21bb</span>';
    h += '<button class="rt-auto-refresh-btn" id="etfAutoRefreshBtn" onclick="toggleEtfAutoRefresh()">\u23f1 \u81ea\u52a8\u5237\u65b0 5\u5206\u949f</button>';
    h += '</div>';
    // Search box
    h += '<div class="etf-search-wrap"><input class="etf-search" id="etfSearch" type="text" placeholder="ETF名称或代码模糊搜索..." oninput="etfSearchFilter(this.value)"></div>';

    // ===== Section 1: ETF关注 =====
    h += '<div class="etf-section" id="etfSec1"><div class="etf-section-title"><span class="etf-section-num">1</span> ETF\\u5173\\u6ce8</div><div id="etfWatchlist"></div></div>';
    // L2 subcategory display order per L1
    var subcatOrders = {
        '\u5bbd\u57fa\u6307\u6570': ['\u79d1\u521b\u677f', '\u521b\u4e1a\u677f', '\u6caa\u6df1300', '\u4e2d\u8bc1500/1000', '\u4e0a\u8bc150/A50', '\u5176\u4ed6\u5bbd\u57fa'],
        '\u884c\u4e1a\u4e3b\u9898': ['\u82af\u7247', '\u534a\u5bfc\u4f53', '\u96c6\u6210\u7535\u8def', '\u4eba\u5de5\u667a\u80fd', '\u79d1\u6280', '\u4e92\u8054', '\u901a\u4fe1', '\u7b97\u529b', '\u8f6f\u4ef6', '\u8ba1\u7b97\u673a', '\u5927\u6570\u636e', '\u4e91\u8ba1\u7b97', '\u6570\u636e', '\u4fe1\u521b', '\u6570\u5b57', '\u4fe1\u606f', '5G', 'VR', '\u536b\u661f', '\u7269\u8054\u7f51', '\u65b0\u80fd\u6e90', '\u5149\u4f0f', '\u98ce\u7535', '\u9502\u7535', '\u7535\u6c60', '\u80fd\u6e90', '\u7164\u70ad', '\u7535\u529b', '\u77f3\u5316', '\u77f3\u6cb9', '\u5929\u7136\u6c14', '\u98df\u54c1', '\u996e\u6599', '\u767d\u9152', '\u9152', '\u533b\u836f', '\u533b\u7597', '\u751f\u7269', '\u521b\u65b0\u836f', '\u4e2d\u836f', '\u533b', '\u91d1\u878d', '\u94f6\u884c', '\u8bc1\u5238', '\u4fdd\u9669', '\u5730\u4ea7', '\u57fa\u5efa', '\u5efa\u7b51', '\u519b\u5de5', '\u56fd\u9632', '\u592e\u4f01', '\u56fd\u4f01', '\u6539\u9769', '\u56fd\u6539', '\u7ea2\u5229', '\u9f99\u5934', '\u6c7d\u8f66', '\u8f66', '\u667a\u80fd\u9a7e\u9a76', '\u81ea\u52a8\u9a7e\u9a76', '\u667a\u80fd', '\u673a\u5668\u4eba', '\u5de5\u4e1a', '\u673a\u5e8a', '\u5236\u9020', '\u519c\u4e1a', '\u517b\u6b96', '\u7267\u7272', '\u5316\u5de5', '\u94a2\u94c1', '\u6750\u6599', '\u5176\u4ed6\u884c\u4e1a'],
        '\u8de8\u5883': ['\u7f8e\u80a1', '\u6e2f\u80a1/\u4e2d\u6982', '\u5176\u4ed6\u8de8\u5883'],
    };
    // Category priority order (hide 商品/债券/货币)
    var catOrder = ['\u5bbd\u57fa\u6307\u6570', '\u884c\u4e1a\u4e3b\u9898', '\u8de8\u5883', '\u5176\u4ed6'];

    // Build sidebar navigation
    var sidebar = '<nav class="etf-sidebar" id="etfSidebar">';
    for (var sci = 0; sci < catOrder.length; sci++) {
        var scat = catOrder[sci];
        if (!cats[scat]) continue;
        var secId = 'etf-scat-' + sci;
        sidebar += '<a class="etf-sidebar-item" data-etf-section="' + secId + '" onclick="scrollToEtfSection(\\x27' + secId + '\\x27)">' + scat + '</a>';
        var sKeys = Object.keys(cats[scat]);
        // Sort L2 subKeys by best gainer (find max without modifying original array)
        sKeys.sort(function(a, b) {
            var aList = cats[scat][a] || [];
            var bList = cats[scat][b] || [];
            var aTop = -999, bTop = -999;
            for (var ai = 0; ai < aList.length; ai++) { if ((aList[ai].change_pct||0) > aTop) aTop = aList[ai].change_pct||0; }
            for (var bi = 0; bi < bList.length; bi++) { if ((bList[bi].change_pct||0) > bTop) bTop = bList[bi].change_pct||0; }
            return bTop - aTop;
        });
        for (var ssi = 0; ssi < sKeys.length; ssi++) {
            var ssn = sKeys[ssi];
            var subSecId = 'etf-scat-' + sci + '-ssub-' + ssi;
            sidebar += '<a class="etf-sidebar-subitem" data-etf-section="' + subSecId + '" onclick="scrollToEtfSection(\\x27' + subSecId + '\\x27)">' + ssn + '</a>';
        }
    }
    sidebar += '</nav>';

    // Build content
    var content = '<div class="etf-main-content">';
    for (var ci = 0; ci < catOrder.length; ci++) {
        var catName = catOrder[ci];
        var subcats = cats[catName];
        if (!subcats) continue;
        // Flatten all items for L1 summary
        var allItems = [];
        var subKeys = Object.keys(subcats);
        // Sort subcategories by best gainer descending
        subKeys.sort(function(a, b) {
            var aList = subcats[a];
            var bList = subcats[b];
            var aTop = aList.length > 0 ? (aList[0].change_pct || 0) : -999;
            var bTop = bList.length > 0 ? (bList[0].change_pct || 0) : -999;
            return bTop - aTop;
        });
        subKeys.forEach(function(sk) {
            var list = subcats[sk];
            list.sort(function(a, b) { return b.change_pct - a.change_pct; });
            allItems = allItems.concat(list);
        });
        var catUp = 0, catDown = 0;
        allItems.forEach(function(it) { if (it.change_pct > 0) catUp++; else if (it.change_pct < 0) catDown++; });
        var catId = 'etf-scat-' + ci;
        content += '<div class="etf-category" id="' + catId + '">';
        content += '<div class="etf-category-title" onclick="var g=document.getElementById(\\x27' + catId + '-body\\x27);g.style.display=g.style.display===\\x27none\\x27?\\x27\\x27:\\x27none\\x27"><span class="cat-name">' + catName + '</span><span class="cat-count">' + allItems.length + '\u53ea</span><span class="cat-up">\u2191' + catUp + '</span><span class="cat-down">\u2193' + catDown + '</span></div>';
        content += '<div id="' + catId + '-body">';
        // Render each subcategory
        for (var si = 0; si < subKeys.length; si++) {
            var subName = subKeys[si];
            var subItems = subcats[subName];
            var subId = catId + '-ssub-' + si;
            // Top 3 gainers for this subcategory
            var top3Html = '';
            var top3Count = Math.min(3, subItems.length);
            for (var ti = 0; ti < top3Count; ti++) {
                var tiItem = subItems[ti];
                var tiChg = tiItem.change_pct || 0;
                var tiName = tiItem.name || '';
                var tiCode = tiItem.code || '';
                var tiClass = tiChg >= 0 ? 'etf-change-up' : 'etf-change-down';
                top3Html += '<span class="subcat-top3-item"><span class="subcat-top3-name ' + tiClass + '">' + tiName + '(' + tiCode + ')</span><span class="subcat-top3-chg ' + tiClass + '">' + (tiChg > 0 ? '+' : '') + tiChg.toFixed(1) + '%</span></span>';
                if (ti < top3Count - 1) top3Html += '<span class="subcat-top3-sep">|</span>';
            }
            content += '<div class="etf-subcategory" id="' + subId + '">';
            content += '<div class="etf-subcategory-title" onclick="var g=document.getElementById(\\x27' + subId + '-body\\x27);g.style.display=g.style.display===\\x27none\\x27?\\x27\\x27:\\x27none\\x27"><span class="subcat-arrow">\u25b6</span><span class="subcat-name">' + subName + '</span><span class="subcat-top3">' + top3Html + '</span></div>';
            content += '<div class="etf-subcat-grid" id="' + subId + '-body" style="display:none">';
            for (var i = 0; i < subItems.length; i++) {
                var it = subItems[i];
                var code = it.code || '';
                var name = it.name || '';
                var price = it.price != null ? it.price.toFixed(3) : '--';
                var chg = it.change_pct != null ? it.change_pct : 0;
                var chgStr = (chg > 0 ? '+' : '') + chg.toFixed(2) + '%';
                var chgClass = chg > 0 ? 'etf-change-up' : (chg < 0 ? 'etf-change-down' : 'etf-change-zero');
                var klineSrc = etfKlineImg(code);
                var minSrc = etfMinImg(code);
                content += '<div class="etf-card" data-name="' + name + '" data-code="' + code + '" onclick="showEtfDetail(this)">';
                var isWatched = isWatchEtf(code);
                var starIcon = isWatched ? '\\u2605' : '\\u2606';
                var starCls = isWatched ? 'etf-watch-star-on' : '';
                content += '<div class="etf-card-header"><span class="etf-card-name" title="' + name + '">' + name + '</span><span class="etf-card-code">' + code + '</span><span class="etf-watch-star ' + starCls + '" onclick="event.stopPropagation();toggleWatchEtf(\\x27' + code + '\\x27)" title="\\u5173\\u6ce8">' + starIcon + '</span></div>';
                content += '<div class="etf-card-price"><span class="etf-card-price-val">' + price + '</span><span class="etf-card-price-unit">' + (chg > 0 ? '\u25b2' : (chg < 0 ? '\u25bc' : '\u2014')) + '</span></div>';
                content += '<div style="margin:2px 0 4px;"><span class="' + chgClass + '" style="font-size:0.9em;font-weight:bold;">' + chgStr + '</span></div>';
                content += '<div class="etf-charts">';
                content += '<div class="etf-chart-col"><div class="mini-label">\u65e5K</div><img src="' + klineSrc + '" loading="lazy" onerror="retryImg(this,2)" style="cursor:pointer;" onclick="reloadSinaImg(this)" data-orig-src="' + klineSrc + '"></div>';
                content += '<div class="etf-chart-col"><div class="mini-label">\u5206\u65f6</div><img src="' + minSrc + '" loading="lazy" onerror="retryImg(this,2)" style="cursor:pointer;" onclick="reloadSinaImg(this)" data-orig-src="' + minSrc + '"></div>';
                content += '</div>';
                content += '</div>';
            }
            content += '</div></div>';
        }
        content += '</div></div>';
    }
    content += '</div>';

    // ===== Section 2: 全部ETF分类 =====
    h += '<div class="etf-section" id="etfSec2"><div class="etf-section-title"><span class="etf-section-num">2</span> \u5168\u90e8ETF\u5206\u7c7b</div>';
    h += '<div class="etf-wrapper">' + sidebar + content + '</div></div>';

    container.innerHTML = h;
    // Render watchlist
    renderWatchlist();
    initEtfSidebar();
}
function scrollToEtfSection(sectionId) {
    var el = document.getElementById(sectionId);
    if (el) el.scrollIntoView({behavior: 'smooth', block: 'start'});
}
function initEtfSidebar() {
    if (_etfObserver) _etfObserver.disconnect();
    var sections = [];
    document.querySelectorAll('[data-etf-section]').forEach(function(item) {
        var id = item.getAttribute('data-etf-section');
        var el = document.getElementById(id);
        if (el) sections.push(el);
    });
    if (sections.length === 0) return;
    _etfObserver = new IntersectionObserver(function(entries) {
        var visibleItems = [];
        entries.forEach(function(entry) {
            if (entry.isIntersecting) {
                visibleItems.push({el: entry.target, ratio: entry.intersectionRatio});
            }
        });
        if (visibleItems.length === 0) return;
        visibleItems.sort(function(a, b) { return b.ratio - a.ratio; });
        var bestId = visibleItems[0].el.id;
        document.querySelectorAll('.etf-sidebar-item').forEach(function(item) {
            var target = item.getAttribute('data-etf-section');
            item.classList.toggle('active', target === bestId);
        });
    }, {rootMargin: '-10px 0px -15% 0px', threshold: [0, 0.1]});
    sections.forEach(function(el) { _etfObserver.observe(el); });
}

// ===== ETF auto refresh =====
var _etfAutoRefreshTimer = null;
var _etfAutoRefreshCountdown = null;
var _etfAutoRefreshRemaining = 0;
var _etfAutoRefreshActive = false;

function manualRefreshEtf() {
    var icon = document.querySelector('#tab-etf .rt-refresh-icon');
    if (!icon) return;
    icon.classList.add('spinning');
    _etfLoaded = false;
    fetch('/api/etf_spot?_t=' + Date.now())
        .then(function(r) { return r.json(); })
        .then(function(data) {
            _etfData = data;
            _etfLoaded = true;
            renderEtfTab(data);
        })
        .catch(function(e) {
            console.error('ETF手动刷新失败:', e);
            var container = document.getElementById('etfContainer');
            if (container) container.innerHTML = '<div class="empty">刷新ETF数据失败: ' + e + '</div>';
        })
        .finally(function() {
            icon.classList.remove('spinning');
        });
}

function toggleEtfAutoRefresh() {
    var btn = document.getElementById('etfAutoRefreshBtn');
    if (!btn) return;

    if (_etfAutoRefreshActive) {
        // Stop
        clearInterval(_etfAutoRefreshTimer);
        clearInterval(_etfAutoRefreshCountdown);
        _etfAutoRefreshActive = false;
        _etfAutoRefreshTimer = null;
        _etfAutoRefreshCountdown = null;
        btn.innerHTML = '\u23f1 \u81ea\u52a8\u5237\u65b0 5\u5206\u949f';
        btn.classList.remove('active');
        showToast('ETF\u81ea\u52a8\u5237\u65b0\u5df2\u505c\u6b62', 'info');
        return;
    }

    // Check A-stock trading hours (Beijing time 9:25 ~ 15:00)
    var now = new Date();
    var beijingHour = (now.getUTCHours() + 8) % 24;
    var beijingMin = now.getUTCMinutes();
    var totalMin = beijingHour * 60 + beijingMin;
    if (totalMin < 565 || totalMin >= 900) {
        showToast('\u23f0 \u975e\u4ea4\u6613\u65f6\u6bb5 (9:25~15:00)\uff0c\u81ea\u52a8\u5237\u65b0\u4e0d\u53ef\u7528', 'warning');
        return;
    }

    // Start
    _etfAutoRefreshActive = true;
    _etfAutoRefreshRemaining = 300;
    btn.classList.add('active');

    function updateBtn() {
        var m = Math.floor(_etfAutoRefreshRemaining / 60);
        var s = _etfAutoRefreshRemaining % 60;
        btn.innerHTML = '<span class="rt-pulse-dot"></span> \u81ea\u52a8\u5237\u65b0 (' + m + ':' + (s < 10 ? '0' : '') + s + ')';
    }
    updateBtn();

    _etfAutoRefreshCountdown = setInterval(function() {
        _etfAutoRefreshRemaining--;
        if (_etfAutoRefreshRemaining <= 0) {
            // Check trading hours before each refresh cycle
            var now = new Date();
            var h = (now.getUTCHours() + 8) % 24;
            var m = now.getUTCMinutes();
            var total = h * 60 + m;
            if (total < 565 || total >= 900) {
                clearInterval(_etfAutoRefreshTimer);
                clearInterval(_etfAutoRefreshCountdown);
                _etfAutoRefreshActive = false;
                _etfAutoRefreshTimer = null;
                _etfAutoRefreshCountdown = null;
                btn.innerHTML = '\u23f1 \u81ea\u52a8\u5237\u65b0 5\u5206\u949f';
                btn.classList.remove('active');
                showToast('\u23f0 \u5df2\u8fc7\u4ea4\u6613\u65f6\u6bb5\uff0cETF\u81ea\u52a8\u5237\u65b0\u5df2\u505c\u6b62', 'info');
                return;
            }
            _etfAutoRefreshRemaining = 300;
            manualRefreshEtf();
        }
        updateBtn();
    }, 1000);
}

// ETF卡片点击弹框（日K+分时纵向排列）
function showEtfDetail(el) {
    var code = el.getAttribute('data-code') || '';
    var name = el.getAttribute('data-name') || '';
    var cardPrice = el.querySelector('.etf-card-price-val');
    var cardChg = el.querySelector('.etf-change-up, .etf-change-down, .etf-change-zero');
    var price = cardPrice ? cardPrice.textContent : '--';
    var chgText = cardChg ? cardChg.textContent : '';
    var chgClass = '';
    if (cardChg) {
        if (cardChg.classList.contains('etf-change-up')) chgClass = 'etf-change-up';
        else if (cardChg.classList.contains('etf-change-down')) chgClass = 'etf-change-down';
        else chgClass = 'etf-change-zero';
    }

    var klineSrc = etfKlineImg(code);
    var minSrc = etfMinImg(code);
    var ts = Math.floor(Date.now() / 10000);

    var html = '<div class="enlarged-card-content" style="padding:12px;">';
    html += '<div class="sk-header"><span class="sk-name">' + name + '</span><span class="sk-code">' + code + '</span></div>';
    html += '<div style="margin:8px 0 12px;font-size:1.1em;">\u4ef7\u683c: <strong>' + price + '</strong> | \u6da8\u8dcc\u5e45: <strong class="' + chgClass + '">' + chgText + '</strong></div>';
    html += '<div class="concept-kline-grid">';
    html += '<div class="ds-stock-kline-section"><div class="mini-label">\u65e5K\u7ebf</div>'
         + '<img class="ds-stock-kline-img kline-img" src="' + klineSrc.split('?')[0] + '?' + ts + '" loading="lazy" onerror="retryImg(this,2)" style="cursor:pointer;" onclick="reloadSinaImg(this)" data-orig-src="' + klineSrc.split('?')[0] + '"></div>';
    html += '<div class="ds-stock-kline-section"><div class="mini-label">\u5206\u65f6\u56fe</div>'
         + '<img class="ds-stock-kline-img kline-img" src="' + minSrc.split('?')[0] + '?' + ts + '" loading="lazy" onerror="retryImg(this,2)" style="cursor:pointer;" onclick="reloadSinaImg(this)" data-orig-src="' + minSrc.split('?')[0] + '"></div>';
    html += '</div></div>';

    var modal = document.getElementById('enlargeCardModal');
    var body = document.getElementById('enlargeCardModalBody');
    body.innerHTML = html;
    modal.classList.add('active');
}

function etfSearchFilter(val) {
    var term = val.trim().toLowerCase();
    var cards = document.querySelectorAll('#etfSec2 .etf-card');
    cards.forEach(function(card) {
        var name = (card.getAttribute('data-name') || card.querySelector('.etf-card-name')?.textContent || '').toLowerCase();
        var code = (card.querySelector('.etf-card-code')?.textContent || '').toLowerCase();
        if (!term) { card.style.display = ''; return; }
        card.style.display = (name.indexOf(term) !== -1 || code.indexOf(term) !== -1) ? '' : 'none';
    });
    // Show/hide L2 sections and L1 categories
    document.querySelectorAll('#etfSec2 .etf-subcat-grid').forEach(function(grid) {
        var hiddenCards = grid.querySelectorAll('.etf-card[style*="display: none"]');
        var totalCards = grid.querySelectorAll('.etf-card').length;
        if (!term) { grid.closest('.etf-subcategory').style.display = ''; return; }
        grid.closest('.etf-subcategory').style.display = (hiddenCards.length === totalCards) ? 'none' : '';
        // Auto-expand grids with matches
        if (hiddenCards.length < totalCards) grid.style.display = '';
    });
    document.querySelectorAll('#etfSec2 .etf-category').forEach(function(cat) {
        var hiddenSubs = cat.querySelectorAll('.etf-subcategory[style*="display: none"]');
        var totalSubs = cat.querySelectorAll('.etf-subcategory').length;
        if (!term) { cat.style.display = ''; return; }
        cat.style.display = (hiddenSubs.length === totalSubs) ? 'none' : '';
    });
}
function renderStockQueryKplTree(stockName) {
    var tree = _kplTreeData;
    var nameCodeMap = _kplNameCodeMap || {};
    var html = '<div class="sq-tree-wrap">';
    var l1Keys = Object.keys(tree);
    l1Keys.forEach(function(l1Key) {
        var l2Keys = Object.keys(tree[l1Key]);
        var matchedL2s = [];
        l2Keys.forEach(function(l2Key) {
            var items = tree[l1Key][l2Key];
            var matchedItems = [];
            items.forEach(function(item) {
                if (item.标的 && item.标的.indexOf(stockName) !== -1) {
                    matchedItems.push(item);
                }
            });
            if (matchedItems.length > 0) {
                matchedL2s.push({l2Key: l2Key, items: matchedItems});
            }
        });
        if (matchedL2s.length > 0) {
            var escL1 = l1Key.replace(/'/g, '');
            html += '<div class="sq-tree-l1-header" onclick="sqJumpToKpl(\\x27' + escL1 + '\\x27)"><span class="sq-arrow">&#9660;</span><span class="sq-label">' + l1Key + '</span><span class="sq-goto">&#8599;</span></div>';
            matchedL2s.forEach(function(l2) {
                var escL2 = l2.l2Key.replace(/'/g, '');
                html += '<div class="sq-tree-l2-header" onclick="sqJumpToKpl(\\x27' + escL2 + '\\x27)"><span class="sq-label">' + l2.l2Key + '</span><span class="sq-goto">&#8599;</span></div>';
                l2.items.forEach(function(item) {
                    var cn = item.概念 || '';
                    var escCn = cn.replace(/'/g, '');
                    html += '<div class="sq-tree-l3-header" onclick="sqJumpToKpl(\\x27' + escCn + '\\x27)"><span class="sq-label">' + cn + '</span><span class="sq-goto">&#8599;</span></div>';
                    html += '<div class="sq-stock-row">';
                    if (item.标的) {
                        item.标的.forEach(function(sname) {
                            var scode = nameCodeMap[sname] || '';
                            var escName = (sname||'').replace(/'/g, '');
                            var hlCls = (_kplHighlightStockName && sname === _kplHighlightStockName) ? ' sq-stock-highlight' : '';
                            if (scode) {
                                html += '<span class="sq-stock-link' + hlCls + '" onclick="event.stopPropagation();stockQueryFetch(\\x27' + scode + '\\x27)"><span class="sq-link-icon">&#x279c;</span>' + sname + '</span>';
                            } else {
                                html += '<span class="sq-stock-link' + hlCls + '" onclick="event.stopPropagation();stockQuerySearchName(\\x27' + escName + '\\x27)">' + sname + '</span>';
                            }
                        });
                    }
                    html += '</div>';
                });
            });
        }
    });
    html += '</div>';
    return html;
}

</script>
</body>
</html>
'''


def _load_astock_name_map():
    """从 astock.csv 加载全A股名称→代码映射，名称标准化处理"""
    path = os.path.join(os.path.dirname(__file__), 'invest_logic', 'astock.csv')
    name_map = {}
    # 全角→半角映射表
    full_to_half = str.maketrans(
        'ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ'
        'ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｘｗｘｙｚ'
        '０１２３４５６７８９',
        'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        'abcdefghijklmnopqrstuxwxyz'
        '0123456789'
    )
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row['code'].strip()
            name = row['name'].strip()
            # 标准化：去空格 + 全角转半角
            name = re.sub(r'\s+', '', name)
            name = name.translate(full_to_half)
            if name and code and name not in name_map:
                name_map[name] = code
    return name_map


# Cache for Python-side KPL stock paths (stock_name → [{l1, l2, l3}])
_kpl_stock_paths_py = None

def _build_kpl_stock_paths_py():
    """Build stock_name → [{l1, l2, l3}] mapping on Python side"""
    global _kpl_stock_paths_py
    if _kpl_stock_paths_py is not None:
        return _kpl_stock_paths_py
    kpl_path = os.path.join(os.path.dirname(__file__), 'invest_logic', 'concept', 'kpl_concept_stock.json')
    try:
        with open(kpl_path, 'r', encoding='utf-8') as f:
            kpl_data = json.load(f)
    except Exception:
        _kpl_stock_paths_py = {}
        return _kpl_stock_paths_py
    result = {}
    for l1_key, l2_dict in kpl_data.items():
        for l2_key, items in l2_dict.items():
            for item in items:
                concept_name = item.get('概念', '') or ''
                stocks = item.get('标的', []) or []
                for stock_name in stocks:
                    if stock_name not in result:
                        result[stock_name] = []
                    result[stock_name].append({'l1': l1_key, 'l2': l2_key, 'l3': concept_name})
    _kpl_stock_paths_py = result
    return result


def _clean_nan(obj):
    """递归将 NaN 替换为 None（null），确保 JSON 序列化不出 NaN 非法值"""
    if isinstance(obj, float):
        return None if (obj != obj) else obj  # NaN != NaN
    elif isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_nan(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(_clean_nan(v) for v in obj)
    return obj


# ===== ETF分类 =====
_ETF_CATEGORIES = [
    ('行业主题', ['芯片', '半导体', '集成电路', '人工', 'AI', '科技', '信息', '互联', '通信', '算力', '软件', '数字', '计算机', '大数据', '云计算', '数据', '信创',
                  '5G', 'VR', '卫星', '物联网', '智能',
                  '新能源', '光伏', '风电', '锂电', '电池', '能源', '煤炭', '电力', '石化', '石油', '天然气',
                  '消费', '食品', '饮料', '白酒', '酒', '医药', '医疗', '生物', '创新药', '中药', '医',
                  '金融', '银行', '证券', '保险', '地产', '基建', '建筑',
                  '军工', '国防', '央企', '国企', '改革', '国改', '红利', '龙头',
                  '汽车', '车', '智能驾驶', '自动驾驶', '机器人', '工业', '机床', '制造',
                  '农业', '养殖', '畜牧', '化工', '钢铁', '材料',
                  '游戏', '传媒', '影视', '旅游', '零售', '家电', '电子',
                  '黄金', '稀土', '稀有', 'ESG', '环境', '环保', '水', '绿',
                  '电信', '粮食', '工程机械', '航空', '新经济', '质量', '大湾区', '粤港澳', '成渝', '油气', '低碳', '碳中和', '养老', '物流', '农牧', '交通运输', '券商']),
    ('商品', ['商品', '能源化工', '豆粕', '农产品', '生猪', '饲料', '黄金', '有色', '期货']),
    ('债券', ['国债', '政金', '地方债', '可转债', '公司债', '债', '债券']),
    ('货币', ['货币ETF', '货币']),
    ('跨境', ['纳指', '标普', '恒生', '中概', '港股', 'H股', '海外', '德国', '法国', '日本', '亚太', '全球', '纳斯达克', '道琼斯', '日经', '沙特', '巴西', '亚洲', '美国50']),
    ('宽基指数', ['上证', '沪深', '中证', '科创', '创业板', '深证', '中小板', '大盘', 'A50', 'AH股', '300', '500', '1000', '2000', '双创', '北证', '综指', '成指',
                   'MSCI', '国际通', '800', '400', '创成长', '可持续发展', '核心']),
]
def _get_sina_prefix(code):
    if code.startswith('6') or code.startswith('5'):
        return 'sh'
    return 'sz'

def _check_yangbaoyin(spot_data):
    """检测反转：昨天阴线下跌，今天阳线(现价>开盘价)
    使用Sina实时行情，每日快照(data/etf_daily_open.json)保存今日开盘价，
    次日加载昨日开盘价做精确阴线(close<open)检测。
    首次运行（无快照）使用跳空低开回升的代理逻辑。"""
    import requests as _req

    _base_dir = os.path.dirname(os.path.abspath(__file__))
    _snap_path = os.path.join(_base_dir, 'data', 'etf_daily_open.json')
    _today_str = datetime.now().strftime('%Y%m%d')

    # 1. 尝试加载昨日快照（精确阴线检测）
    yesterday_opens = {}
    snap_date = None
    if os.path.exists(_snap_path):
        try:
            with open(_snap_path, 'r') as f:
                snap = json.load(f)
                snap_date = snap.get('date', '')
                if snap_date:
                    yesterday_opens = snap.get('opens', {})
        except Exception:
            pass

    has_snapshot = bool(snap_date and snap_date != _today_str and yesterday_opens)

    # 2. 候选：今日上涨的ETF
    candidates = [item for item in spot_data if item.get('change_pct', 0) > 0]
    candidates.sort(key=lambda x: -x['change_pct'])
    top_candidates = candidates[:200]

    # 3. 分批批量获取Sina实时行情
    sina_map = {}
    batch_size = 50
    for batch_start in range(0, len(top_candidates), batch_size):
        batch = top_candidates[batch_start:batch_start + batch_size]
        symbols = ','.join([_get_sina_prefix(it['code']) + it['code'] for it in batch])
        url = f'https://hq.sinajs.cn/list={symbols}'
        try:
            r = _req.get(url, timeout=15, headers={
                'Referer': 'https://finance.sina.com.cn',
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
            })
            if r.status_code == 200:
                for line in r.text.strip().split('\n'):
                    line = line.strip()
                    if not line or not line.startswith('var hq_str_'):
                        continue
                    # 格式: var hq_str_sh589720="name,open,prev_close,current,high,low,..."
                    content = line[line.index('"')+1:line.rindex('"')]
                    parts = content.split(',')
                    if len(parts) >= 4:
                        scode = line.split('_')[2].split('=')[0]
                        raw_code = scode[2:] if len(scode) > 2 else scode
                        try:
                            today_open = float(parts[1]) if parts[1] else None
                            prev_close = float(parts[2]) if parts[2] else None
                            current = float(parts[3]) if parts[3] else None
                            if today_open and prev_close and current:
                                sina_map[raw_code] = {
                                    'open': today_open,
                                    'prev_close': prev_close,
                                    'current': current,
                                }
                        except (ValueError, IndexError):
                            pass
        except Exception:
            pass

    # 4. 保存今日开盘价快照（供次日精确检测）
    try:
        today_opens = {}
        for c, s in sina_map.items():
            today_opens[c] = s['open']
        with open(_snap_path, 'w') as f:
            json.dump({'date': _today_str, 'opens': today_opens}, f)
    except Exception:
        pass

    # 5. 检测每个候选
    result = []
    for item in top_candidates:
        code = item['code']
        sina = sina_map.get(code)
        if not sina:
            continue

        today_open = sina['open']
        prev_close = sina['prev_close']
        current = sina['current']

        if has_snapshot and code in yesterday_opens:
            # === 精确检测：使用昨日快照 ===
            yesterday_open = yesterday_opens[code]
            yesterday_close = prev_close
            # 昨天阴线: close < open
            # 今天阳线: current > today_open
            if yesterday_close < yesterday_open and current > today_open:
                result.append({
                    'code': code, 'name': item['name'],
                    'price': item['price'], 'change_pct': item['change_pct'],
                    'category': item['category'], 'subcategory': item['subcategory'],
                    'yesterday_open': yesterday_open,
                    'yesterday_close': yesterday_close,
                    'proxy': False,
                })
        else:
            # === 代理逻辑：跳空低开+回升（快照尚未就绪） ===
            gap_down_pct = (prev_close - today_open) / prev_close * 100 if prev_close > 0 else 0
            if gap_down_pct >= 0.15 and current > today_open and current > prev_close:
                result.append({
                    'code': code, 'name': item['name'],
                    'price': item['price'], 'change_pct': item['change_pct'],
                    'category': item['category'], 'subcategory': item['subcategory'],
                    'yesterday_open': round(prev_close, 4),
                    'yesterday_close': round(today_open, 4),
                    'proxy': True,
                })

    result.sort(key=lambda x: -x['change_pct'])
    return result

def _classify_etf(name):
    for cat, keywords in _ETF_CATEGORIES:
        for kw in keywords:
            if kw in name:
                return cat
    return '其他'
def _cat_order(cat):
    order = {'宽基指数': 0, '行业主题': 1, '商品': 2, '债券': 3, '货币': 4, '跨境': 5}
    return order.get(cat, 6)

_ETF_L2 = {
    '宽基指数': [
        ('科创板', ['科创', '双创', '创成长']),
        ('创业板', ['创业板']),
        ('沪深300', ['沪深300']),
        ('中证500/1000', ['500', '1000', '2000']),
        ('上证50/A50', ['上证50', 'A50']),
        ('其他宽基', []),
    ],
    '行业主题': [
        ('芯片', ['芯片']),
        ('半导体', ['半导体']),
        ('集成电路', ['集成电路']),
        ('人工智能', ['人工', 'AI']),
        ('科技', ['科技']),
        ('互联', ['互联']),
        ('通信', ['通信']),
        ('算力', ['算力']),
        ('软件', ['软件']),
        ('计算机', ['计算机']),
        ('大数据', ['大数据']),
        ('云计算', ['云计算']),
        ('数据', ['数据']),
        ('信创', ['信创']),
        ('数字', ['数字']),
        ('信息', ['信息']),
        ('5G', ['5G']),
        ('VR', ['VR']),
        ('卫星', ['卫星']),
        ('物联网', ['物联网']),
        ('新能源', ['新能源']),
        ('光伏', ['光伏']),
        ('风电', ['风电']),
        ('锂电', ['锂电']),
        ('电池', ['电池']),
        ('能源', ['能源']),
        ('煤炭', ['煤炭']),
        ('电力', ['电力']),
        ('石化', ['石化']),
        ('石油', ['石油']),
        ('天然气', ['天然气']),
        ('食品', ['食品']),
        ('饮料', ['饮料']),
        ('白酒', ['白酒']),
        ('酒', ['酒']),
        ('医药', ['医药']),
        ('医疗', ['医疗']),
        ('生物', ['生物']),
        ('创新药', ['创新药']),
        ('中药', ['中药']),
        ('医', ['医']),
        ('金融', ['金融']),
        ('银行', ['银行']),
        ('证券', ['证券']),
        ('保险', ['保险']),
        ('地产', ['地产']),
        ('基建', ['基建']),
        ('建筑', ['建筑']),
        ('军工', ['军工']),
        ('国防', ['国防']),
        ('央企', ['央企']),
        ('国企', ['国企']),
        ('改革', ['改革']),
        ('国改', ['国改']),
        ('红利', ['红利']),
        ('龙头', ['龙头']),
        ('汽车', ['汽车']),
        ('车', ['车']),
        ('智能驾驶', ['智能驾驶']),
        ('自动驾驶', ['自动驾驶']),
        ('智能', ['智能']),  # 智能驾驶等更精确匹配在前，智能靠后
        ('机器人', ['机器人']),
        ('工业', ['工业']),
        ('机床', ['机床']),
        ('制造', ['制造']),
        ('农业', ['农业']),
        ('养殖', ['养殖']),
        ('畜牧', ['畜牧']),
        ('化工', ['化工']),
        ('钢铁', ['钢铁']),
        ('材料', ['材料']),
        ('稀土/稀有金属', ['稀土', '稀有金属']),
        ('电子', ['电子']),
        ('电信', ['电信']),
        ('传媒/游戏', ['传媒', '游戏', '动漫', '文娱']),
        ('影视', ['影视']),
        ('通用航空', ['通用航空']),
        ('航天航空', ['航天', '航空', '航空航天']),
        ('黄金', ['黄金']),
        ('工程机械', ['工程机械']),
        ('碳中和/环保', ['碳中和', '低碳', '环保']),
        ('粮食/农牧', ['粮食', '农牧']),
        ('油气', ['油气']),
        ('家电', ['家电']),
        ('消费', ['消费']),  # 消费靠后，避免消费电子/消费科技被错分
        ('物流', ['物流']),
        ('旅游', ['旅游']),
        ('ESG/质量', ['ESG', '质量ETF']),
        ('其他行业', []),
    ],
    '跨境': [
        ('美股', ['纳指', '标普', '纳斯达克', '道琼斯', '美国50']),
        ('港股/中概', ['恒生', '中概', '港股', 'H股']),
        ('其他跨境', []),
    ],
}
def _classify_etf_sub(name, category):
    """返回子分类名称"""
    l2_list = _ETF_L2.get(category, [])
    for l2_name, keywords in l2_list:
        if not keywords:
            continue
        for kw in keywords:
            if kw in name:
                return l2_name
    # catch-all
    for l2_name, keywords in l2_list:
        if not keywords:
            return l2_name
    return None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # CORS headers
        cors_headers = {
            'Access-Control-Allow-Origin': '*',
        }

        if path == '/' or path == '/index.html':
            self._respond(200, HTML_PAGE.encode('utf-8'), 'text/html; charset=utf-8', cors_headers)

        elif path == '/api/concepts':
            result = finder.get_all_concept_names()
            self._respond_json(result, cors_headers)

        elif path == '/api/today_zt':
            result = _get_cached('today_zt')
            if result is None:
                result = finder.get_today_zt()
                _set_cache('today_zt', result)
            self._respond_json(result, cors_headers)

        elif path == '/api/realtime_zt':
            try:
                result = _get_zt_from_akshare()
                self._respond_json(result or [], cors_headers)
            except Exception as e:
                self._respond_json([], cors_headers)

        elif path == '/api/recent_trade_dates':
            n = int(query.get('n', ['30'])[0])
            # 合并交易日历 + CSV中有数据的日期，按倒序排列
            trade_dates = set(getattr(finder, 'all_trade_dates', []))
            csv_dates = set(_limit_rows_by_date.keys())
            all_dates = sorted(trade_dates | csv_dates, reverse=True)
            recent = all_dates[:n]
            self._respond_json(recent, cors_headers)

        elif path == '/api/history_zt_by_date':
            date_str = query.get('date', [''])[0].strip()
            if not date_str:
                self._respond_json([], cors_headers)
                return
            result = _get_cached('history_zt_' + date_str)
            if result is None:
                rows = _limit_rows_by_date.get(date_str, [])
                if rows:
                    # 从CSV获取
                    seen_codes = {}
                    result = []
                    for r in rows:
                        code = r.get('ts_code', '').replace('.SH','').replace('.SZ','').replace('.BJ','')
                        if code in seen_codes:
                            continue
                        seen_codes[code] = True
                        concepts = finder.get_stock_concepts(code)
                        lianban = _parse_chain_count(r.get('tag', ''))
                        result.append({
                            'code': code,
                            'name': r.get('name', ''),
                            'lianban': lianban,
                            'first_time': 999999,
                            'zb_count': 0,
                            'concepts': list(concepts),
                            'concept_count': len(concepts),
                            'trade_date': date_str,
                        })
                else:
                    # CSV无数据，用akshare实时拉取
                    try:
                        import akshare as ak
                        import pandas as pd
                        df = ak.stock_zt_pool_em(date=date_str)
                        if df is not None and not df.empty:
                            result = []
                            for _, row in df.iterrows():
                                code = str(int(row['代码'])).zfill(6)
                                concepts = finder.get_stock_concepts(code)
                                result.append({
                                    'code': code,
                                    'name': str(row['名称']),
                                    'lianban': int(row['连板数']) if pd.notna(row.get('连板数')) else 0,
                                    'first_time': int(row['首次封板时间']) if pd.notna(row.get('首次封板时间')) else 999999,
                                    'zb_count': int(row['炸板次数']) if pd.notna(row.get('炸板次数')) else 0,
                                    'concepts': list(concepts),
                                    'concept_count': len(concepts),
                                    'trade_date': date_str,
                                })
                            result.sort(key=lambda x: x['first_time'])
                        else:
                            result = []
                    except Exception:
                        result = []
                _set_cache('history_zt_' + date_str, result)
            self._respond_json(result, cors_headers)

        elif path == '/api/zt_word_freq_timeline':
            n = int(query.get('days', ['15'])[0])
            # 获取交易日列表（从finder获取，已含2026年所有交易日）
            trade_dates = getattr(finder, 'all_trade_dates', [])
            if not trade_dates:
                trade_dates = sorted(_limit_rows_by_date.keys())
            today_ymd = datetime.now().strftime('%Y%m%d')
            valid_dates = [d for d in trade_dates if d <= today_ymd]
            recent_dates = valid_dates[-n:] if len(valid_dates) >= n else valid_dates
            # 预加载KPL题材路径映射 (stock_name → [{l1, l2, l3}])
            kpl_paths_map = _build_kpl_stock_paths_py()
            # 构建 code→name 映射
            code_to_name = {}
            for code, name in getattr(finder, 'stock_name_map', {}).items():
                code_to_name[code] = name
            result = []
            for date_str in reversed(recent_dates):
                cache_key = 'wf_date_' + date_str
                is_today = (date_str == today_ymd)
                cached = _get_cached(cache_key, ttl=3600 if is_today else 14400)
                if cached is not None:
                    result.append(cached)
                    continue
                # 获取该日涨停股票code
                import akshare as ak
                import pandas as pd
                day_codes = set()
                try:
                    df = ak.stock_zt_pool_em(date=date_str)
                    if df is not None and not df.empty:
                        for _, row in df.iterrows():
                            day_codes.add(str(int(row['代码'])).zfill(6))
                except Exception:
                    pass
                if not day_codes:
                    # 回退：用CSV中该日的所有股票
                    for r in _limit_rows_by_date.get(date_str, []):
                        code = r.get('ts_code', '').replace('.SH','').replace('.SZ','').replace('.BJ','')
                        day_codes.add(code)
                # 统计该日涨停股的KPL题材频度（L1/L2/L3分层）
                l1_freq = {}
                l2_freq = {}
                l3_freq = {}
                for code in day_codes:
                    name = code_to_name.get(code, '')
                    if not name:
                        continue
                    paths = kpl_paths_map.get(name, [])
                    for p in paths:
                        l1 = p['l1']
                        l2 = p['l2']
                        l3 = p['l3']
                        l1_freq[l1] = l1_freq.get(l1, 0) + 1
                        l2_freq[l2] = l2_freq.get(l2, 0) + 1
                        l3_freq[l3] = l3_freq.get(l3, 0) + 1
                day_data = {
                    'date': date_str,
                    'l1': [{'tag': t, 'count': c} for t, c in sorted(l1_freq.items(), key=lambda x: -x[1])],
                    'l2': [{'tag': t, 'count': c} for t, c in sorted(l2_freq.items(), key=lambda x: -x[1])],
                    'l3': [{'tag': t, 'count': c} for t, c in sorted(l3_freq.items(), key=lambda x: -x[1])],
                }
                _set_cache(cache_key, day_data)
                result.append(day_data)
            self._respond_json(result, cors_headers)

        elif path == '/api/lianban_ladder':
            result = _get_cached('lianban_ladder')
            if result is None:
                top_n = int(query.get('top_n', ['30'])[0])
                result = finder.get_lianban_ladder(top_n)
                _set_cache('lianban_ladder', result)
            self._respond_json(result, cors_headers)

        elif path == '/api/hot_rank_100':
            result = _get_cached('hot_rank_100', ttl=60)
            if result is None:
                result = finder.get_hot_rank_100()
                _set_cache('hot_rank_100', result)
            self._respond_json(result, cors_headers)

        elif path == '/api/hot_concept_20':
            result = _get_cached('hot_concept_20', ttl=60)
            if result is None:
                result = finder.get_hot_concept_20()
                _set_cache('hot_concept_20', result)
            self._respond_json(result, cors_headers)

        elif path == '/api/search':
            q = query.get('q', [''])[0]
            if q == '':
                start_date = query.get('start_date', [None])[0]
                end_date = query.get('end_date', [None])[0]
                top_n = int(query.get('top_n', ['200'])[0])
                results = finder.get_top_stocks_by_zt(top_n, start_date, end_date)
            else:
                results = finder.search_stock(q)
            self._respond_json(results, cors_headers)

        elif path == '/api/linkage':
            stock = query.get('stock', [''])[0]
            concept = query.get('concept', [None])[0]
            min_prob = float(query.get('min_prob', ['0.12'])[0])
            filters_param = query.get('filters', [None])[0]
            filters = filters_param.split(',') if filters_param else None

            if not stock:
                self._respond_json({'error': '请输入股票代码'}, cors_headers)
            else:
                stock_code = stock.strip().zfill(6)
                try:
                    result = finder.find_stock_linkages(stock_code, concept, min_prob=min_prob, filters=filters)
                    # 添加涨停理由子概念标签
                    result['sub_tags'] = _get_stock_sub_tags(stock_code)
                    self._respond_json(result, cors_headers)
                except Exception as e:
                    self._respond_json({'error': str(e)}, cors_headers)

        elif path == '/api/kline':
            stock = query.get('stock', [''])[0]
            days = int(query.get('days', ['60'])[0])
            if not stock:
                self._respond_json({'error': '请输入股票代码'}, cors_headers)
            else:
                result = finder.get_stock_kline_summary(stock.strip().zfill(6), days=days)
                self._respond_json(result, cors_headers)

        elif path == '/api/concept_zt_stats':
            concept = query.get('concept', [''])[0]
            if not concept:
                self._respond_json({'error': '请输入概念名称'}, cors_headers)
            else:
                refresh = query.get('refresh', [None])[0]
                cache_key = 'concept_zt_stats_' + concept
                result = None if refresh else _get_cached(cache_key)
                if result is None:
                    result = finder.get_concept_zt_stats(concept)
                    _set_cache(cache_key, result)
                self._respond_json(result, cors_headers)

        elif path == '/api/concept_linkage':
            concept = query.get('concept', [''])[0]
            top_n = int(query.get('top_n', ['15'])[0])
            if not concept:
                self._respond_json({'error': '请输入概念名称'}, cors_headers)
            else:
                refresh = query.get('refresh', [None])[0]
                cache_key = 'concept_linkage_{}_{}'.format(concept, top_n)
                pairs = None if refresh else _get_cached(cache_key)
                if pairs is None:
                    pairs = finder.analyze_concept_linkages(concept, top_n=top_n)
                    _set_cache(cache_key, pairs)
                self._respond_json({'concept': concept, 'pairs': pairs}, cors_headers)

        elif path == '/api/data_status':
            result = _get_cached('data_status', ttl=30)
            if result is not None:
                self._respond_json(result, cors_headers)
                return
            try:
                import sqlite3
                db_path = 'data/stocks_kline.db'
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                # K线日期范围
                cur.execute("SELECT MIN(trade_date), MAX(trade_date) FROM kline_daily")
                kline_min, kline_max = cur.fetchone() or ('N/A', 'N/A')
                # 涨停股票数
                cur.execute("SELECT COUNT(DISTINCT stock_code) FROM kline_daily WHERE change_pct >= 9.5")
                stock_zt_count = cur.fetchone()[0] or 0
                conn.close()
                # zt_pool 天数
                zt_dir = os.path.join(os.path.dirname(__file__), 'data', 'zt_pool')
                zt_files = [f for f in os.listdir(zt_dir) if f.endswith('.csv')] if os.path.isdir(zt_dir) else []
                ds_result = {
                    'kline_min': kline_min,
                    'kline_max': kline_max,
                    'latest_display': kline_max or 'N/A',
                    'zt_pool_days': len(zt_files),
                    'zt_pool_files': sorted(zt_files)[-5:] if zt_files else [],
                    'concept_count': len(getattr(finder, 'concept_stocks', {})),
                    'stock_concept_count': len(getattr(finder, 'stock_concepts', {})),
                    'stock_zt_count': stock_zt_count,
                    'trade_days': len(getattr(finder, 'trade_dates', [])),
                }
                _set_cache('data_status', ds_result)
                self._respond_json(ds_result, cors_headers)
            except Exception as e:
                self._respond_json({'error': str(e)}, cors_headers)

        elif path == '/api/stats':
            try:
                start_date = query.get('start_date', [None])[0]
                end_date = query.get('end_date', [None])[0]
                top_n = int(query.get('top_n', ['50'])[0])
                refresh = query.get('refresh', [None])[0]
                cache_key = 'stats_{}_{}_{}'.format(start_date or 'all', end_date or 'all', top_n)
                result = None if refresh else _get_cached(cache_key)
                if result is None:
                    summary = finder.get_stats_summary(start_date, end_date)
                    top_stocks = finder.get_top_stocks_by_zt(top_n, start_date, end_date)
                    top_concepts = finder.get_top_concepts_by_zt(top_n, start_date, end_date)
                    daily_activity = finder.get_daily_zt_activity(60, start_date, end_date)
                    result = {
                        'summary': summary,
                        'top_stocks': top_stocks,
                        'top_concepts': top_concepts,
                        'daily_activity': daily_activity
                    }
                    _set_cache(cache_key, result)
                self._respond_json(result, cors_headers)
            except Exception as e:
                import traceback
                self._respond_json({'error': str(e), 'traceback': traceback.format_exc()}, cors_headers)

        elif path == '/api/stats_bucket':
            try:
                bucket_type = query.get('type', [''])[0]
                bucket = query.get('bucket', [''])[0]
                start_date = query.get('start_date', [None])[0]
                end_date = query.get('end_date', [None])[0]
                top_n = int(query.get('top_n', ['100'])[0])
                if bucket_type == 'zt':
                    result = finder.get_stocks_in_zt_bucket(bucket, start_date, end_date, top_n)
                elif bucket_type == 'lianban':
                    result = finder.get_stocks_in_lianban_bucket(bucket, start_date, end_date, top_n)
                else:
                    result = []
                self._respond_json({'type': bucket_type, 'bucket': bucket, 'stocks': result}, cors_headers)
            except Exception as e:
                self._respond_json({'error': str(e)}, cors_headers)

        elif path == '/api/hot_stocks':
            try:
                start_date = query.get('start_date', [None])[0]
                end_date = query.get('end_date', [None])[0]
                top_n = int(query.get('top_n', ['200'])[0])
                results = finder.get_hot_stocks_weighted(top_n, start_date, end_date)
                self._respond_json(results, cors_headers)
            except Exception as e:
                self._respond_json({'error': str(e)}, cors_headers)

        elif path == '/api/sniper_data':
            try:
                lookback = int(query.get('lookback', ['20'])[0])
                refresh = query.get('refresh', [''])[0]
                cache_key = f'sniper_{lookback}'
                if refresh:
                    result = _get_sniper_data(lookback)
                    _set_cache(cache_key, result)  # 刷新时也更新服务端缓存
                else:
                    result = _get_cached(cache_key, ttl=3600)
                    if result is None:
                        result = _get_sniper_data(lookback)
                        _set_cache(cache_key, result)
                self._respond_json(result, cors_headers)
            except Exception as e:
                import traceback
                self._respond_json({'error': str(e), 'traceback': traceback.format_exc()}, cors_headers)

        elif path == '/api/sector_ranking':
            try:
                import levistock as lk
                import levistock.stock.stock_fupanla_kph as kph_mod
                # 超时补丁
                def _patched_post(host, params):
                    import requests
                    r = requests.post(host, data=params, headers=kph_mod._HEADERS, timeout=30)
                    return r.json()
                kph_mod._post = _patched_post
                today_str = datetime.now().strftime('%Y-%m-%d')
                cache_key = 'sector_rank_' + today_str
                refresh = query.get('refresh', [''])[0]
                if refresh:
                    result = lk.sector_ranking_kph(date=today_str, zs_type=lk.SECTOR_SELECTED)
                    _set_cache(cache_key, result)
                else:
                    result = _get_cached(cache_key, ttl=300)
                    if result is None:
                        result = lk.sector_ranking_kph(date=today_str, zs_type=lk.SECTOR_SELECTED)
                        _set_cache(cache_key, result)
                self._respond_json(result or [], cors_headers)
            except Exception as e:
                import traceback
                self._respond_json({'error': str(e), 'traceback': traceback.format_exc()}, cors_headers)

        elif path == '/api/zt_window':
            try:
                lookback = int(query.get('lookback_days', ['15'])[0])
                top_n = int(query.get('top_n', ['50'])[0])
                result = finder.get_zt_window_stocks(lookback_days=lookback, top_per_window=top_n)
                self._respond_json(result, cors_headers)
            except Exception as e:
                import traceback
                self._respond_json({'error': str(e), 'traceback': traceback.format_exc()}, cors_headers)

        elif path == '/api/n_pattern':
            try:
                lookback = int(query.get('lookback_days', ['20'])[0])
                refresh = query.get('refresh', [None])[0]
                cache_key = f'n_pattern_{lookback}'
                result = None if refresh else _get_cached(cache_key)
                if result is None:
                    result = finder.analyze_n_pattern(lookback_days=lookback)
                    _set_cache(cache_key, result)
                self._respond_json(result, cors_headers)
            except Exception as e:
                import traceback
                self._respond_json({'error': str(e), 'traceback': traceback.format_exc()}, cors_headers)

        elif path == '/api/oscillation':
            try:
                refresh = query.get('refresh', [None])[0]
                cache_key = 'oscillation_20'
                result = None if refresh else _get_cached(cache_key)
                if result is None:
                    result = finder.analyze_oscillation_pattern(lookback_days=20)
                    _set_cache(cache_key, result)
                self._respond_json(result, cors_headers)
            except Exception as e:
                import traceback
                self._respond_json({'error': str(e), 'traceback': traceback.format_exc()}, cors_headers)

        elif path == '/api/gem_arbitrage':
            try:
                stock = query.get('stock', [''])[0]
                max_lag = int(query.get('max_lag', ['2'])[0])
                if not stock:
                    self._respond_json({'error': '请输入股票代码'}, cors_headers)
                else:
                    result = finder.find_gem_arbitrage(stock.strip().zfill(6), max_lag=max_lag)
                    self._respond_json(result, cors_headers)
            except Exception as e:
                self._respond_json({'error': str(e)}, cors_headers)

        elif path == '/api/check_update':
            import update_data_fast
            cal = update_data_fast.load_trade_calendar()
            missing = update_data_fast.get_db_missing_dates()
            latest_cal = cal[-1] if cal else 'N/A'
            # 使用北京时间
            bj_tz = timezone(timedelta(hours=8))
            bj_now = datetime.now(bj_tz)
            today = bj_now.strftime('%Y%m%d')
            is_today_trade_day = today in cal if cal else False
            now_hour = bj_now.hour
            market_open = is_today_trade_day and (now_hour >= 9 and (now_hour < 15 or (now_hour == 15 and bj_now.minute < 30)))
            market_settling = is_today_trade_day and now_hour < 17
            self._respond_json({
                'status': 'ok',
                'latest_cal_day': latest_cal,
                'today': today,
                'is_today_trade_day': is_today_trade_day,
                'market_open': market_open,
                'market_settling': market_settling,
                'missing_dates': len(missing),
                'missing_list': missing[:3],
                'msg': f"最晚数据: {latest_cal}, 缺失 {len(missing)} 天"
            }, cors_headers)

        elif path == '/api/update_data':
            global _update_in_progress
            if _update_in_progress:
                self._respond_json({'status': 'running', 'msg': _update_progress_msg}, cors_headers)
            else:
                _update_in_progress = True
                thread = threading.Thread(target=_do_data_update, daemon=True)
                thread.start()
                self._respond_json({'status': 'started', 'msg': '正在更新数据...'}, cors_headers)

        elif path == '/api/update_status':
            if _update_in_progress:
                self._respond_json({'status': 'running', 'msg': _update_progress_msg}, cors_headers)
            else:
                self._respond_json({'status': 'done', 'msg': _update_progress_msg}, cors_headers)

        elif path == '/api/abnormal_movement':
            try:
                lookback = int(query.get('lookback', ['20'])[0])
                cache_key = 'abnormal_movement_' + str(lookback)
                result = _get_cached(cache_key)
                if result is None:
                    result = _analyze_abnormal_movement(lookback)
                    _set_cache(cache_key, result)
                self._respond_json(result, cors_headers)
            except Exception as e:
                import traceback
                self._respond_json({'error': str(e), 'traceback': traceback.format_exc()}, cors_headers)

        elif path == '/api/lianban_screener':
            try:
                cache_key = 'lianban_screener'
                result = _get_cached(cache_key)
                if result is None:
                    result = _screener_lianban_stocks()
                    _set_cache(cache_key, result)
                self._respond_json(result, cors_headers)
            except Exception as e:
                import traceback
                self._respond_json({'error': str(e), 'traceback': traceback.format_exc()}, cors_headers)

        elif path == '/api/reason_search':
            try:
                q = query.get('q', [''])[0].strip()
                date_start = query.get('date_start', [None])[0]
                date_end = query.get('date_end', [None])[0]
                no_st = query.get('no_st', [None])[0]
                result = _analyze_limit_rows(q, date_start, date_end, no_st)
                self._respond_json(result, cors_headers)
            except Exception as e:
                import traceback
                self._respond_json({'error': str(e), 'traceback': traceback.format_exc(), 'results': [], 'total_hits': 0}, cors_headers)

        elif path == '/api/reason_suggest':
            q = query.get('q', [''])[0].strip()
            result = _suggest_limit_rows(q) if q else {'stocks': [], 'concepts': []}
            self._respond_json(result, cors_headers)

        elif path == '/api/kpl_reason_search':
            try:
                q = query.get('q', [''])[0].strip()
                date_start = query.get('date_start', [None])[0]
                date_end = query.get('date_end', [None])[0]
                no_st = query.get('no_st', [None])[0]
                strict = query.get('strict', [None])[0]
                result = _kpl_analyze_rows(q, date_start, date_end, no_st, strict)
                self._respond_json(result, cors_headers)
            except Exception as e:
                import traceback
                self._respond_json({'error': str(e), 'traceback': traceback.format_exc(), 'results': [], 'total_hits': 0}, cors_headers)

        elif path == '/api/kpl_update_data':
            try:
                fetch_mode = query.get('fetch', ['0'])[0] == '1'
                trade_dates = finder.trade_dates
                today_ymd = datetime.now().strftime('%Y%m%d')
                trade_dates = [d for d in trade_dates if d <= today_ymd]

                existing_fmts = set()
                zt_dir = _KPL_DATA_DIR
                if os.path.isdir(zt_dir):
                    for f in os.listdir(zt_dir):
                        if f.endswith('.json') and f not in ('index.json', 'reason_index.json'):
                            existing_fmts.add(f.replace('.json', ''))

                missing = [d for d in trade_dates if f'{d[:4]}-{d[4:6]}-{d[6:]}' not in existing_fmts]
                missing.sort()
                total_missing = len(missing)

                if total_missing == 0:
                    self._respond_json({'status': 'ok', 'total_missing': 0, 'message': '数据已是最新'}, cors_headers)
                elif not fetch_mode:
                    self._respond_json({'status': 'missing', 'total_missing': total_missing, 'message': f'缺少{total_missing}天数据'}, cors_headers)
                else:
                    missing_to_fetch = missing[-30:]
                    def _kpl_update_thread():
                        global _kpl_stock_index, _kpl_reason_index, _kpl_unique_plates, _kpl_unique_tags, _kpl_unique_concepts
                        global _kpl_day_files, _kpl_day_cache, _kpl_rows, _kpl_rows_by_date, _kpl_rows_by_stock
                        try:
                            from data.update_zt_data import fetch_day_data, save_day_json, rebuild_index
                            fetched = 0
                            for date_ymd in missing_to_fetch:
                                date_fmt = f'{date_ymd[:4]}-{date_ymd[4:6]}-{date_ymd[6:]}'
                                out_path = os.path.join(zt_dir, f'{date_fmt}.json')
                                if os.path.exists(out_path):
                                    continue
                                print(f'  [KPL更新] {date_fmt} ...', end=' ', flush=True)
                                records = fetch_day_data(date_fmt)
                                if records:
                                    save_day_json(date_fmt, records)
                                    fetched += 1
                                import time
                                time.sleep(2)
                            if fetched > 0:
                                print('  [KPL更新] 重建索引...')
                                rebuild_index()
                                _kpl_stock_index = json.load(open(os.path.join(zt_dir, 'index.json'), 'r', encoding='utf-8'))
                                _kpl_reason_index = json.load(open(os.path.join(zt_dir, 'reason_index.json'), 'r', encoding='utf-8'))
                                _kpl_day_files = sorted([f for f in os.listdir(zt_dir) if f.endswith('.json') and f not in ('index.json', 'reason_index.json')])
                                _kpl_unique_tags = {}
                                _kpl_unique_plates = {}
                                _kpl_unique_concepts = {}
                                for tag, entries in _kpl_reason_index.items():
                                    _kpl_unique_tags[tag] = len(entries)
                                    for e in entries:
                                        pn = e.get('plate_name', '')
                                        if pn:
                                            _kpl_unique_plates[pn] = _kpl_unique_plates.get(pn, 0) + 1
                                        cs = e.get('concepts', '') or ''
                                        for c in cs.split('\u3001'):
                                            c = c.strip()
                                            if c:
                                                _kpl_unique_concepts[c] = _kpl_unique_concepts.get(c, 0) + 1
                                _kpl_day_cache = {}
                                _kpl_rows = []
                                _kpl_rows_by_date = {}
                                _kpl_rows_by_stock = {}
                                print(f'  [KPL更新] 完成: 拉取 {fetched}/{len(missing_to_fetch)} 天, 共缺{total_missing}天')
                        except Exception as e:
                            import traceback
                            print(f'  [KPL更新] 失败: {e}')
                            traceback.print_exc()

                    t = threading.Thread(target=_kpl_update_thread, daemon=True)
                    t.start()
                    self._respond_json({'status': 'fetching', 'total_missing': total_missing, 'fetching': len(missing_to_fetch), 'message': f'正在获取最近{len(missing_to_fetch)}天数据(共缺{total_missing}天)'}, cors_headers)
            except Exception as e:
                import traceback
                self._respond_json({'error': str(e), 'traceback': traceback.format_exc()}, cors_headers)

        elif path == '/api/kpl_reason_suggest':
            q = query.get('q', [''])[0].strip()
            result = _kpl_suggest_rows(q) if q else {'stocks': [], 'reason_tags': [], 'plates': [], 'concepts': []}
            self._respond_json(result, cors_headers)

        elif path == '/api/kpl_stock_detail':
            code = query.get('code', [''])[0].strip()
            if not code:
                self._respond_json({'error': 'missing code'}, cors_headers)
            else:
                # 从缓存中获取该股票的所有KPL记录
                records = _kpl_rows_by_stock.get(code, [])
                records.sort(key=lambda x: x.get('date', ''), reverse=True)
                # 构建概念列表（去重）
                concepts_set = set()
                for r in records:
                    concepts_str = r.get('concepts', '') or ''
                    for c in concepts_str.split('、'):
                        c = c.strip()
                        if c:
                            concepts_set.add(c)
                # 获取同花顺概念
                ths_concepts = finder.get_stock_concepts(code)
                self._respond_json({
                    'records': records,
                    'concepts': sorted(concepts_set),
                    'ths_concepts': ths_concepts,
                    'code': code,
                    'name': records[0].get('stock_name', '') if records else '',
                }, cors_headers)

        elif path == '/api/stock_detail':
            code = query.get('code', [''])[0].strip()
            concept = query.get('concept', [''])[0].strip()
            if not code:
                self._respond_json({'error': 'missing code'}, cors_headers)
            else:
                # 过滤该股票的所有涨停理由
                limit_rows_all = []
                for r in _limit_rows:
                    r_code = (r.get('ts_code', '') or '').replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
                    if r_code == code:
                        limit_rows_all.append(r)
                limit_rows_all.sort(key=lambda x: x.get('trade_date', '') or '', reverse=True)

                # 如果指定了concept，进一步按概念过滤（lu_desc中包含概念关键词）
                limit_rows = limit_rows_all
                if concept:
                    cl = concept.lower()
                    limit_rows = [r for r in limit_rows_all if cl in ((r.get('lu_desc', '') or '').lower())]

                # 获取概念列表
                concepts = finder.get_stock_concepts(code)

                # 获取股票名称
                name = finder.get_stock_name(code)

                # KPL数据（开盘啦）—— 确保已加载
                if not _kpl_rows_by_stock:
                    _kpl_ensure_loaded()
                kpl_records = _kpl_rows_by_stock.get(code, [])
                kpl_records.sort(key=lambda x: x.get('date', ''), reverse=True)
                kpl_concepts_set = set()
                for r in kpl_records:
                    cs = r.get('concepts', '') or ''
                    for c in cs.split('、'):
                        c = c.strip()
                        if c:
                            kpl_concepts_set.add(c)
                kpl_concepts = sorted(kpl_concepts_set)

                # 近3个月统计（基于KPL数据）
                three_months_ago = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')
                three_month_dates_kpl = set()
                for r in kpl_records:
                    rd = (r.get('date', '') or '').replace('-', '')
                    if rd >= three_months_ago:
                        three_month_dates_kpl.add(rd)
                three_month_dates = sorted(three_month_dates_kpl, reverse=True)

                # 联动数据：从CSV中找出同概念下与该股票同日期涨停的其他股票
                linkage = []
                if concept:
                    cl = concept.lower()
                    # 找出该概念下所有CSV行
                    concept_rows = []
                    for r in _limit_rows:
                        if cl in ((r.get('lu_desc', '') or '').lower()):
                            concept_rows.append(r)
                    # 按日期分组
                    date_map = {}
                    for r in concept_rows:
                        d = r.get('trade_date', '') or ''
                        rc = (r.get('ts_code', '') or '').replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
                        rn = r.get('name', '') or ''
                        if d and rc:
                            date_map.setdefault(d, []).append((rc, rn))
                    # 目标股票在该概念下的涨停日期
                    target_dates = set()
                    for r in limit_rows:
                        d = r.get('trade_date', '') or ''
                        if d:
                            target_dates.add(d)
                    # 统计同日期其他股票的出现频率
                    stock_cnt = {}
                    stock_nm = {}
                    for d in target_dates:
                        if d in date_map:
                            for sc, sn in date_map[d]:
                                if sc != code:
                                    stock_cnt[sc] = stock_cnt.get(sc, 0) + 1
                                    stock_nm[sc] = sn
                    sorted_stocks = sorted(stock_cnt.items(), key=lambda x: -x[1])[:20]
                    for sc, cnt in sorted_stocks:
                        linkage.append({'stock': sc, 'name': stock_nm.get(sc, sc), 'cooccurrence': cnt})

                self._respond_json({
                    'name': name,
                    'code': code,
                    'concept': concept,
                    'concepts': concepts,
                    'limit_rows': limit_rows,
                    'kpl_concepts': kpl_concepts,
                    'kpl_records': kpl_records[:50],
                    'three_month': {
                        'count': len(three_month_dates),
                        'dates': three_month_dates
                    },
                    'linkage': linkage,
                    'total_rows': len(limit_rows_all),
                }, cors_headers)

        elif path == '/api/stock_search':
            q = query.get('q', [''])[0].strip().upper()
            results = []
            if q:
                # search by code (exact prefix match first)
                for code, name in finder.stock_name_map.items():
                    if code.startswith(q) or q in name.upper():
                        results.append({'code': code, 'name': name})
                        if len(results) >= 15:
                            break
                # if too few results from prefix, also search by name fragment
                if len(results) < 8:
                    for code, name in finder.stock_name_map.items():
                        if code not in [r['code'] for r in results]:
                            if q in code or q in name.upper():
                                results.append({'code': code, 'name': name})
                                if len(results) >= 15:
                                    break
            self._respond_json(results, cors_headers)

        elif path == '/api/stock_detail_batch':
            codes_str = query.get('codes', [''])[0].strip()
            codes = [c.strip() for c in codes_str.split(',') if c.strip()]
            cache_key = 'detail_batch_' + '_'.join(sorted(codes))
            result = _get_cached(cache_key)
            if result is None:
                # 确保KPL数据已加载
                if not _kpl_rows_by_stock:
                    _kpl_ensure_loaded()
                three_months_ago = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')
                result = {}
                for c in codes:
                    # CSV数据保留
                    rows = sorted(_limit_rows_by_code.get(c, []), key=lambda x: x.get('trade_date', '') or '', reverse=True)
                    three_month_csv_rows = [r for r in rows if (r.get('trade_date', '') or '') >= three_months_ago]
                    three_month_csv_dates = sorted(set(r.get('trade_date', '') for r in three_month_csv_rows), reverse=True)
                    # KPL数据
                    kpl_records = _kpl_rows_by_stock.get(c, [])
                    kpl_records.sort(key=lambda x: x.get('date', ''), reverse=True)
                    kpl_concepts_set = set()
                    for kr in kpl_records:
                        ks = kr.get('concepts', '') or ''
                        for kc in ks.split('、'):
                            kc = kc.strip()
                            if kc:
                                kpl_concepts_set.add(kc)
                    kpl_concepts = sorted(kpl_concepts_set)
                    # KPL-based three_month
                    three_month_dates_kpl = set()
                    for kr in kpl_records:
                        krd = (kr.get('date', '') or '').replace('-', '')
                        if krd >= three_months_ago:
                            three_month_dates_kpl.add(krd)
                    three_month_kpl = sorted(three_month_dates_kpl, reverse=True)
                    # 名称
                    name = finder.get_stock_name(c)
                    if not name and kpl_records:
                        name = kpl_records[0].get('stock_name', '')
                    result[c] = {
                        'limit_rows': rows[:20],
                        'three_month': {'count': len(three_month_csv_dates), 'dates': three_month_csv_dates},
                        'kpl_records': kpl_records[:50],
                        'kpl_concepts': kpl_concepts,
                        'three_month_kpl': {'count': len(three_month_kpl), 'dates': three_month_kpl},
                        'name': name,
                    }
                _set_cache(cache_key, result)
            self._respond_json(result, cors_headers)

        elif path == '/api/kpl_concept_tree':
            kpl_path = os.path.join(os.path.dirname(__file__), 'invest_logic', 'concept', 'kpl_concept_stock.json')
            result = _get_cached('kpl_concept_tree')
            if result is None:
                try:
                    with open(kpl_path, 'r', encoding='utf-8') as f:
                        result = json.load(f)
                    _set_cache('kpl_concept_tree', result)
                except Exception as e:
                    result = {'error': str(e)}
            self._respond_json(result, cors_headers)

        elif path == '/api/kpl_name_code_map':
            result = _get_cached('kpl_name_code_map')
            if result is None:
                # 主数据源：astock.csv（全A股，标准化名称）
                name_to_code = _load_astock_name_map()
                # 兜底补充：现有的 stock_name_map（可能包含少数 astock 没有的股票）
                for code, name in getattr(finder, 'stock_name_map', {}).items():
                    if name and name not in name_to_code:
                        name_to_code[name] = code
                # 补充：KPL原始名称标准化后匹配（如"*ST 中设"→"*ST中设"）
                kpl_path = os.path.join(os.path.dirname(__file__), 'invest_logic', 'concept', 'kpl_concept_stock.json')
                full_to_half = str.maketrans(
                    'ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ'
                    'ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｘｗｘｙｚ'
                    '０１２３４５６７８９',
                    'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                    'abcdefghijklmnopqrstuxwxyz'
                    '0123456789'
                )
                try:
                    with open(kpl_path, encoding='utf-8') as f:
                        kpl_data = json.load(f)
                    kpl_names = set()
                    def _extract_names(d):
                        if isinstance(d, dict):
                            for v in d.values():
                                _extract_names(v)
                        elif isinstance(d, list):
                            for item in d:
                                if isinstance(item, str):
                                    kpl_names.add(item)
                                else:
                                    _extract_names(item)
                    _extract_names(kpl_data)
                    for raw_name in kpl_names:
                        norm = re.sub(r'\s+', '', raw_name).translate(full_to_half)
                        if norm in name_to_code and raw_name not in name_to_code:
                            name_to_code[raw_name] = name_to_code[norm]
                except Exception:
                    pass  # KPL文件不存在或解析失败时忽略
                # 手动覆写：KPL数据中的错误名称→正确代码
                kpl_overrides = {
                    '航宇股份': '688239',  # KPL数据写成航宇股份，实为航宇科技
                }
                for raw_name, code in kpl_overrides.items():
                    if raw_name not in name_to_code:
                        name_to_code[raw_name] = code
                result = name_to_code
                _set_cache('kpl_name_code_map', result)
            self._respond_json(result, cors_headers)

        elif path == '/api/etf_spot':
            result = _get_cached('etf_spot')
            if result is None:
                try:
                    import akshare as ak
                    import pandas as pd
                    df = ak.fund_etf_spot_ths()
                    result = []
                    if df is not None and not df.empty:
                        for _, row in df.iterrows():
                            code = str(row.get('基金代码', '')).strip() if pd.notna(row.get('基金代码')) else ''
                            name = str(row.get('基金名称', '')).strip() if pd.notna(row.get('基金名称')) else ''
                            price = float(row['当前-单位净值']) if pd.notna(row.get('当前-单位净值')) else None
                            change_pct = float(row['增长率']) if pd.notna(row.get('增长率')) else 0.0
                            category = _classify_etf(name)
                            subcategory = _classify_etf_sub(name, category)
                            result.append({
                                'code': code, 'name': name, 'price': price,
                                'change_pct': change_pct, 'category': category,
                                'subcategory': subcategory,
                            })
                        result.sort(key=lambda x: (_cat_order(x['category']), -x['change_pct']))
                    _set_cache('etf_spot', result)
                except Exception as e:
                    self._respond_json({'error': str(e)}, cors_headers)
                    return
            self._respond_json(result, cors_headers)

        elif path == '/api/etf_yangbaoyin':
            result = _get_cached('etf_yangbaoyin')
            if result is None:
                try:
                    spot_data = _get_cached('etf_spot')
                    if spot_data is None:
                        self._respond_json({'error': 'no_spot_data'}, cors_headers)
                        return
                    result = _check_yangbaoyin(spot_data)
                    _set_cache('etf_yangbaoyin', result)
                except Exception as e:
                    self._respond_json({'error': str(e)}, cors_headers)
                    return
            self._respond_json(result, cors_headers)

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')

    def _respond(self, status, body, content_type='text/html; charset=utf-8', extra_headers=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _respond_json(self, data, extra_headers=None):
        body = json.dumps(_clean_nan(data), ensure_ascii=False).encode('utf-8')
        self._respond(200, body, 'application/json; charset=utf-8', extra_headers)

    def log_message(self, format, *args):
        pass


def main():
    port = 6688
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)

    hostname = os.uname().nodename if hasattr(os, 'uname') else 'localhost'
    print('=' * 50)
    print('涨停深挖 Web服务')
    print(f'本地访问: http://localhost:{port}')
    print(f'手机访问: http://{hostname}:{port}')
    print('新增: T+0同日联动 | 方向性分析 | 去重')
    print('按 Ctrl+C 停止服务')
    print('=' * 50)

    # 预热缓存：3线程并行预加载，大幅缩短预热时间
    def _warm_lianban():
        try:
            lb = finder.get_lianban_ladder(top_n=30)
            _set_cache('lianban_ladder', lb)
            print(f"[预热] 连板天梯 {len(lb)} 只")
        except Exception as e:
            print(f"[预热] lianban失败: {e}")

    def _warm_stats():
        try:
            summary = finder.get_stats_summary()
            top_stocks_100 = finder.get_top_stocks_by_zt(100)
            top_concepts_50 = finder.get_top_concepts_by_zt(50)
            daily_activity = finder.get_daily_zt_activity(60)
            # 从100条中截取，避免重复计算
            for tn in [5, 10, 20, 50]:
                key_s = 'stats_None_None_' + str(tn)
                _set_cache(key_s, {
                    'summary': summary,
                    'top_stocks': top_stocks_100[:tn],
                    'top_concepts': top_concepts_50[:tn],
                    'daily_activity': daily_activity
                })
            print("[预热] 统计摘要完成")
        except Exception as e:
            print(f"[预热] stats失败: {e}")

    def _warm_hot():
        try:
            hr = finder.get_hot_rank_100()
            _set_cache('hot_rank_100', hr)
            hc = finder.get_hot_concept_20()
            _set_cache('hot_concept_20', hc)
            print(f"[预热] 热股100+热门概念20完成")
        except Exception as e:
            print(f"[预热] hot数据失败: {e}")

    def _warm_data_status():
        try:
            import sqlite3
            db_path = 'data/stocks_kline.db'
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT MIN(trade_date), MAX(trade_date) FROM kline_daily")
            kline_min, kline_max = cur.fetchone() or ('N/A', 'N/A')
            cur.execute("SELECT COUNT(DISTINCT stock_code) FROM kline_daily WHERE change_pct >= 9.5")
            stock_zt_count = cur.fetchone()[0] or 0
            conn.close()
            zt_dir = os.path.join(os.path.dirname(__file__), 'data', 'zt_pool')
            zt_files = [f for f in os.listdir(zt_dir) if f.endswith('.csv')] if os.path.isdir(zt_dir) else []
            ds = {
                'kline_min': kline_min, 'kline_max': kline_max,
                'latest_display': kline_max or 'N/A',
                'zt_pool_days': len(zt_files),
                'zt_pool_files': sorted(zt_files)[-5:] if zt_files else [],
                'concept_count': len(getattr(finder, 'concept_stocks', {})),
                'stock_concept_count': len(getattr(finder, 'stock_concepts', {})),
                'stock_zt_count': stock_zt_count,
                'trade_days': len(getattr(finder, 'trade_dates', [])),
            }
            _set_cache('data_status', ds)
            print("[预热] data_status完成")
        except Exception as e:
            print(f"[预热] data_status失败: {e}")

    threads = [
        threading.Thread(target=_warm_lianban, daemon=True),
        threading.Thread(target=_warm_stats, daemon=True),
        threading.Thread(target=_warm_hot, daemon=True),
        threading.Thread(target=_warm_data_status, daemon=True),
    ]
    for t in threads:
        t.start()
    print("[缓存预热] 4线程并行启动...")

    server.serve_forever()


if __name__ == '__main__':
    main()
