#!/usr/bin/env python3
"""
股票联动查找器 V5
================
功能：基于历史涨停数据（涨停池CSV + K线数据库），找出与某只股票有联动关系的其他股票

V5 改进：
    1. T+0 同日涨停联动检测
    2. 联动方向性分析（A→B vs B→A）
    3. 去重：同只股票跨概念只出现一次
    4. 更强的联动概率计算

使用方式：
    python stock_linkage_finder.py [股票代码] [概念名称]

示例：
    python stock_linkage_finder.py 000021 存储芯片
    python stock_linkage_finder.py 603045
"""

import os
import json
import threading
import time
from datetime import datetime, timedelta
from typing import List, Dict, Set, Optional, Tuple
from collections import defaultdict
import pandas as pd

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from concept_data_fetcher import ConceptDataFetcher
from kline_database import KlineDB


class StockLinkageFinder:
    """股票联动查找器 V5"""

    # 非题材概念关键词——排除政策/财报/指数类概念，只保留题材概念（如半导体、PCB等）
    NON_THEMATIC_KEYWORDS = {
        '国企改革', '央企改革', '中字头', '同花顺', '预增',
        '高股息', '回购增持', '沪股通', '深股通', '融资融券',
        '证金持股', 'ST板块', '摘帽', '次新股', '出海50',
        '新质50', '果指数', '漂亮100', '中国AI', '中特估',
        '专精特新', '人民币贬值', '举牌',
    }

    @classmethod
    def is_thematic_concept(cls, name: str) -> bool:
        """判断是否为题材概念（排除国企改革、业绩预增等非题材概念）"""
        for kw in cls.NON_THEMATIC_KEYWORDS:
            if kw in name:
                return False
        return True

    def __init__(self):
        self.fetcher = ConceptDataFetcher()
        self.db = KlineDB()
        self._build_concept_stock_map()
        self._load_trade_calendar()
        self._load_zt_pool_data()
        self._load_zt_from_db()
        self._merge_zt_data()
        # 启动后台线程自动补全K线数据
        self._check_and_auto_update()

    def _build_concept_stock_map(self):
        """构建概念-股票映射（只加载题材概念，排除非题材概念）"""
        self.concept_stocks = {}       # {concept_name: set(stock_codes)}
        self.stock_concepts = defaultdict(set)  # {stock_code: set(concept_names)}
        self.stock_name_map = {}       # {stock_code: stock_name}
        self.all_concept_stocks = {}   # 保留原始完整映射（备查）

        for concept_name, stocks in self.fetcher.ths_concepts.items():
            # 跳过非题材概念（国企改革、业绩预增等）
            if not self.is_thematic_concept(concept_name):
                continue

            stock_set = set()
            for s in stocks:
                code = self.fetcher._normalize_stock_code(s.get('code', ''))
                name = s.get('name', '')
                stock_set.add(code)
                self.stock_concepts[code].add(concept_name)
                if name and code not in self.stock_name_map:
                    self.stock_name_map[code] = name
            self.concept_stocks[concept_name] = stock_set

        # 构建名称到代码的索引（用于模糊搜索）
        self.name_to_codes = defaultdict(list)
        for code, name in self.stock_name_map.items():
            self.name_to_codes[name].append(code)

        print(f"构建了 {len(self.concept_stocks)} 个题材概念，共 {len(self.stock_concepts)} 只股票")

    def _load_trade_calendar(self):
        """加载交易日历"""
        self.all_trade_dates = self.db.load_trade_calendar()
        if not self.all_trade_dates:
            # fallback: use trade_calendar_2026.json directly
            cal_file = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'data', 'trade_calendar_2026.json'
            )
            if os.path.exists(cal_file):
                with open(cal_file, 'r') as f:
                    self.all_trade_dates = [d.replace('-', '') for d in json.load(f)]

        self.all_trade_dates.sort()
        self.trade_date_set = set(self.all_trade_dates)
        print(f"加载了 {len(self.all_trade_dates)} 个交易日")

    def _load_zt_pool_data(self):
        """加载历史涨停池CSV数据（东方财富源）"""
        zt_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'data', 'zt_pool'
        )

        self.zt_pool_dates = defaultdict(set)
        self.zt_pool_records = []
        self.zt_pool_prices = defaultdict(list)  # {code: [(date, close_price, lianban, zb_count, first_time), ...]}

        if not os.path.exists(zt_dir):
            print(f"涨停池目录不存在: {zt_dir}")
            return

        csv_files = sorted([f for f in os.listdir(zt_dir) if f.endswith('.csv')])

        for fname in csv_files:
            fpath = os.path.join(zt_dir, fname)
            try:
                df = pd.read_csv(fpath)
                if '代码' not in df.columns:
                    continue

                date_str = fname.replace('.csv', '')

                for _, row in df.iterrows():
                    code = str(int(row['代码'])).zfill(6)
                    name = row.get('名称', '')
                    lianban = row.get('连板数', 0)
                    industry = row.get('所属行业', '')
                    close_price = row.get('最新价', None)
                    change_pct = row.get('涨跌幅', None)
                    zb_count = row.get('炸板次数', 0)

                    self.zt_pool_dates[code].add(date_str)

                    close_val = float(close_price) if pd.notna(close_price) else 0.0
                    zb_val = int(zb_count) if pd.notna(zb_count) else 0
                    lb_val = int(lianban) if pd.notna(lianban) else 0
                    chg_val = float(change_pct) if pd.notna(change_pct) else 0.0

                    first_time_val = int(row.get('首次封板时间', 0)) if pd.notna(row.get('首次封板时间', None)) else 0

                    self.zt_pool_prices[code].append(
                        (date_str, close_val, lb_val, zb_val, first_time_val)
                    )

                    self.zt_pool_records.append({
                        'stock_code': code,
                        'stock_name': name,
                        'trade_date': date_str,
                        'lianban': lb_val,
                        'industry': industry if pd.notna(industry) else '',
                        'close_price': close_val,
                        'change_pct': chg_val,
                        'zb_count': zb_val,
                        'first_time': first_time_val,
                        'source': 'zt_pool'
                    })

                    if name and code not in self.stock_name_map:
                        self.stock_name_map[code] = name

            except Exception:
                pass

        print(f"涨停池CSV: {len(csv_files)} 个交易日, {len(self.zt_pool_dates)} 只有涨停记录的股票")

    def _load_zt_from_db(self):
        """从K线数据库检测涨停日期（基于change_pct字段）"""
        self.db_zt_dates = defaultdict(set)

        try:
            conn = self.db._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT kd.stock_code, kd.trade_date, kd.change_pct, kd.close, s.stock_name
                FROM kline_daily kd
                LEFT JOIN stocks s ON kd.stock_code = s.stock_code
                WHERE kd.change_pct >= 9.5
                ORDER BY kd.trade_date
            """)

            GEM_PREFIXES = ('300', '301', '688')

            count = 0
            for row in cursor.fetchall():
                code = row[0]
                change_pct = float(row[2]) if row[2] else 0
                date_str = row[1].replace('-', '') if row[1] else ''
                if not date_str:
                    continue

                # 按板块区分涨停阈值：主板10%，创业板/科创板20%
                is_gem = code.startswith(GEM_PREFIXES)
                threshold = 19.5 if is_gem else 9.8
                if change_pct < threshold:
                    continue

                self.db_zt_dates[code].add(date_str)
                count += 1

                name = row[4] if len(row) > 4 and row[4] else ''
                if name and code not in self.stock_name_map:
                    self.stock_name_map[code] = name

            conn.close()
            print(f"K线数据库: {count} 条涨停记录, {len(self.db_zt_dates)} 只有涨停记录的股票")

        except Exception as e:
            print(f"从数据库加载涨停数据失败: {e}")

    def _merge_zt_data(self):
        """合并涨停池CSV和数据库两个源的涨停日期"""
        self.all_zt_dates = defaultdict(set)

        for code, dates in self.zt_pool_dates.items():
            self.all_zt_dates[code].update(dates)
        for code, dates in self.db_zt_dates.items():
            self.all_zt_dates[code].update(dates)

        all_dates_in_zt = set()
        for dates in self.all_zt_dates.values():
            all_dates_in_zt.update(dates)
        self.trade_dates = sorted(all_dates_in_zt & self.trade_date_set)
        if not self.trade_dates:
            self.trade_dates = self.all_trade_dates
        # 日期→索引映射，用于O(1)的滞后日期计算
        self.trade_date_index = {d: i for i, d in enumerate(self.trade_dates)}

        print(f"合并后: {len(self.all_zt_dates)} 只有涨停记录的股票")
        print(f"交易日范围: {self.trade_dates[0]} ~ {self.trade_dates[-1]} ({len(self.trade_dates)}天)")
        # 数据变更后清空依赖数据的内部缓存
        self._zt_filter_cache = None

    # ========== 查询接口 ==========

    def search_stock(self, query: str) -> List[Dict]:
        """
        模糊搜索股票（支持代码或名称）

        Returns:
            [{"code": "000021", "name": "深科技", "concepts": [...], "zt_count": 5}, ...]
        """
        query = query.strip()

        results = []
        seen = set()

        # 按代码匹配
        for code, names in self.stock_concepts.items():
            if not code or code == 'nan':
                continue
            if query in str(code):
                name = self.stock_name_map.get(code, code)
                key = code
                if key not in seen:
                    seen.add(key)
                    zt_dates = sorted(self.all_zt_dates.get(code, set()))
                    results.append({
                        'code': code,
                        'name': name,
                        'concepts': sorted(names)[:10],
                        'concept_count': len(names),
                        'zt_count': len(zt_dates),
                        'zt_dates': zt_dates[-5:] if len(zt_dates) > 5 else zt_dates,
                        'last_zt_date': zt_dates[-1] if zt_dates else ''
                    })

        # 按名称模糊匹配
        for name, codes in self.name_to_codes.items():
            if query in name:
                for code in codes:
                    if code not in seen:
                        seen.add(code)
                        concepts = self.stock_concepts.get(code, set())
                        zt_dates = sorted(self.all_zt_dates.get(code, set()))
                        results.append({
                            'code': code,
                            'name': name,
                            'concepts': sorted(concepts)[:10],
                            'concept_count': len(concepts),
                            'zt_count': len(zt_dates),
                            'zt_dates': zt_dates[-5:] if len(zt_dates) > 5 else zt_dates,
                            'last_zt_date': zt_dates[-1] if zt_dates else ''
                        })

        results.sort(key=lambda x: x['zt_count'], reverse=True)
        return results[:20]

    def get_stock_concepts(self, stock_code: str) -> List[str]:
        """获取股票所属概念"""
        stock_code = str(stock_code).zfill(6)
        return list(self.stock_concepts.get(stock_code, set()))

    def get_concept_stocks(self, concept_name: str) -> List[str]:
        """获取概念成分股"""
        return list(self.concept_stocks.get(concept_name, set()))

    def get_stock_zt_dates(self, stock_code: str) -> List[str]:
        """获取股票的所有涨停日期（合并zt_pool + DB两个源，按时间排序）"""
        stock_code = str(stock_code).zfill(6)
        return sorted(self.all_zt_dates.get(stock_code, set()))

    def get_stock_zt_dates_detail(self, stock_code: str) -> Dict:
        """
        获取股票的涨停日期详情（含两个源的信息）
        """
        stock_code = str(stock_code).zfill(6)
        pool_dates = sorted(self.zt_pool_dates.get(stock_code, set()))
        db_dates = sorted(self.db_zt_dates.get(stock_code, set()))
        all_dates = sorted(self.all_zt_dates.get(stock_code, set()))

        return {
            'all_dates': all_dates,
            'zt_pool_dates': pool_dates,
            'db_dates': db_dates,
            'total_count': len(all_dates),
            'pool_count': len(pool_dates),
            'db_count': len(db_dates)
        }

    def get_stock_name(self, stock_code: str) -> str:
        """获取股票名称"""
        stock_code = str(stock_code).zfill(6)
        return self.stock_name_map.get(stock_code, stock_code)

    def get_all_concept_names(self) -> List[str]:
        """获取所有概念名称"""
        return sorted(self.concept_stocks.keys())

    def get_today_zt(self) -> List[Dict]:
        """获取最新交易日的涨停股票列表（含连板数、首次封板时间、概念标签）

        Returns:
            [{code, name, lianban, zb_count, first_time, concepts, concept_count, trade_date}, ...]
            按首次封板时间升序排列（越早涨停越靠前）
        """
        if not self.trade_dates:
            return []
        latest_date = self.trade_dates[-1]

        result = []
        for code, dates in self.all_zt_dates.items():
            if latest_date not in dates:
                continue

            # 获取连板数、炸板数和首次封板时间
            lianban = 1
            zb_count = 0
            first_time = 999999
            price_records = self.zt_pool_prices.get(code, [])
            # 尝试精确匹配最新交易日；若失败则降级使用最近CSV记录中的封板时间
            found_exact = False
            fallback_first_time = 999999
            if price_records:
                for rec in price_records:
                    if rec[0] == latest_date:
                        lianban = rec[2] or 1
                        zb_count = rec[3] or 0
                        first_time = rec[4] if len(rec) > 4 and rec[4] else 999999
                        found_exact = True
                        break
                # 未精确匹配时，取最后一条CSV记录的封板时间作为降级
                if not found_exact:
                    latest_rec = price_records[-1]  # 假定已按日期升序
                    fallback_first_time = latest_rec[4] if len(latest_rec) > 4 and latest_rec[4] else 999999
                    first_time = fallback_first_time

            concepts = list(self.get_stock_concepts(code))
            result.append({
                'code': code,
                'name': self.get_stock_name(code),
                'lianban': lianban,
                'zb_count': zb_count,
                'first_time': first_time,
                'concepts': concepts,
                'concept_count': len(concepts),
                'trade_date': latest_date,
            })

        # 按首次封板时间升序（越早涨停越靠前），无时间数据的排在最后
        result.sort(key=lambda x: x['first_time'])
        return result

    def get_hot_rank_100(self) -> List[Dict]:
        """获取同花顺热股Top100

        Returns:
            [{rank, code, name, change_pct, hot_value, pop_tag, concepts}, ...]
        """
        try:
            import adata
            df = adata.sentiment.hot.hot_rank_100_ths()
            if df is None or df.empty:
                return []
            result = []
            for _, row in df.iterrows():
                code = str(row.get('stock_code', '')).zfill(6)
                concepts = str(row.get('concept_tag', ''))
                result.append({
                    'rank': int(row.get('rank', 0)),
                    'code': code,
                    'name': str(row.get('short_name', '')),
                    'change_pct': float(row.get('change_pct', 0)),
                    'hot_value': int(float(str(row.get('hot_value', 0)).replace(',', ''))) if pd.notna(row.get('hot_value', 0)) else 0,
                    'pop_tag': str(row.get('pop_tag', '')) if pd.notna(row.get('pop_tag', '')) else '',
                    'concepts': [c.strip() for c in concepts.split(';') if c.strip()],
                })
            return result
        except Exception as e:
            print(f"获取同花顺热股Top100失败: {e}")
            return []

    def get_hot_concept_20(self) -> List[Dict]:
        """获取同花顺热门概念板块Top20

        Returns:
            [{rank, concept_code, concept_name, change_pct, hot_value, hot_tag}, ...]
        """
        try:
            import adata
            df = adata.sentiment.hot.hot_concept_20_ths()
            if df is None or df.empty:
                return []
            result = []
            for _, row in df.iterrows():
                result.append({
                    'rank': int(row.get('rank', 0)),
                    'concept_code': str(row.get('concept_code', '')),
                    'concept_name': str(row.get('concept_name', '')),
                    'change_pct': float(row.get('change_pct', 0)),
                    'hot_value': int(float(str(row.get('hot_value', 0)).replace(',', ''))) if pd.notna(row.get('hot_value', 0)) else 0,
                    'hot_tag': str(row.get('hot_tag', '')) if pd.notna(row.get('hot_tag', '')) else '',
                })
            return result
        except Exception as e:
            print(f"获取同花顺热门概念板块Top20失败: {e}")
            return []

    def get_lianban_ladder(self, top_n: int = 30, date_end: str = None) -> List[Dict]:
        """获取连续涨停天数排行（连板天梯）

        从最新交易日往前追溯，计算每只股票的连续涨停天数。

        Args:
            top_n: 返回前N只
            date_end: 截止日期(YYYYMMDD或YYYY-MM-DD)。传入时仅统计该日及之前，
                      天梯的"最新交易日"取 trade_dates 中 ≤ date_end 的最近一天。

        Returns:
            [{code, name, consecutive_lianban, zt_count, concepts}, ...]
            按连续涨停天数降序排列
        """
        if not self.trade_dates:
            return []
        if date_end:
            de = str(date_end).replace('-', '')
            eligible = [d for d in self.trade_dates if d <= de]
            if not eligible:
                return []           # date_end 早于全部有涨停的交易日
            latest_date = eligible[-1]
        else:
            latest_date = self.trade_dates[-1]   # 默认行为不变

        # 筛选最新交易日有涨停的股票
        candidates = []
        for code, dates in self.all_zt_dates.items():
            if latest_date not in dates:
                continue
            candidates.append(code)

        ladder = []
        for code in candidates:
            zt_dates = sorted(self.all_zt_dates[code])
            if date_end:
                zt_dates = [d for d in zt_dates if d <= latest_date]
            if not zt_dates:
                continue

            # 从最新日往前追溯连续涨停（使用完整交易日历，避免gap误判）
            consecutive = 0
            zt_set = set(zt_dates)
            for d in reversed(self.all_trade_dates):
                if d not in self.trade_date_set:
                    continue  # 跳过非交易日
                if d in zt_set:
                    consecutive += 1
                elif consecutive > 0:
                    break  # 连续涨停中断
                # 未开始计数时遇到非ZT日，继续往前

            concepts = self.get_stock_concepts(code)
            ladder.append({
                'code': code,
                'name': self.get_stock_name(code),
                'consecutive_lianban': consecutive,
                'zt_count': len(zt_dates),
                'concepts': concepts[:8],
                'concept_count': len(concepts),
            })

        ladder.sort(key=lambda x: x['consecutive_lianban'], reverse=True)
        return ladder[:top_n]

    def get_concept_zt_stats(self, concept_name: str, rhythm_days: int = 20) -> Dict:
        """获取概念内涨停统计，含近N日涨停节奏（含连板和板块信息）"""
        stock_codes = self.get_concept_stocks(concept_name)
        if not stock_codes:
            return {'concept': concept_name, 'total_stocks': 0, 'zt_stocks': []}

        # 板块中文标签映射
        _BOARD_LABEL = {'gem': '创', 'star': '科', 'bj': '北', 'main': '主'}

        # 构建每只股票的ZT日期set和sorted list
        stock_zt_sets = {}
        stock_zt_lists = {}
        zt_stocks = []
        for code in stock_codes:
            dates = self.get_stock_zt_dates(code)
            if dates:
                name = self.get_stock_name(code)
                stock_zt_sets[code] = set(dates)
                stock_zt_lists[code] = sorted(dates)
                zt_stocks.append({
                    'code': code,
                    'name': name,
                    'board': _BOARD_LABEL.get(self._get_board(code), '主'),
                    'zt_count': len(dates),
                    'first_zt': dates[0],
                    'last_zt': dates[-1],
                })

        zt_stocks.sort(key=lambda x: x['zt_count'], reverse=True)

        # 计算概念整体涨停热力（每日涨停股票数）
        daily_zt_count = defaultdict(int)
        for s in zt_stocks:
            for d in stock_zt_lists[s['code']]:
                daily_zt_count[d] += 1

        peak_dates = sorted(daily_zt_count.items(), key=lambda x: x[1], reverse=True)[:10]

        # --- 涨停节奏：最近 rhythm_days 个交易日（含连板和板块） ---
        recent_dates = self.trade_dates[-rhythm_days:] if len(self.trade_dates) >= rhythm_days else self.trade_dates

        # 提前计算每只股票每个ZT日期的连板数
        stock_lianban = {}
        for code in stock_zt_lists:
            dates_list = stock_zt_lists[code]
            zt_set = stock_zt_sets[code]
            stock_lianban[code] = {}
            for d in dates_list:
                lb = 1
                curr = d
                while True:
                    prev = self._get_lagged_date(curr, -1)
                    if prev and prev in zt_set:
                        lb += 1
                        curr = prev
                    else:
                        break
                stock_lianban[code][d] = lb

        # 额外获取创业板/科创板股票的大涨数据（涨幅≥10%但未涨停）
        gem_star_codes = [c for c in stock_codes if c.startswith(('300', '301', '688'))]
        gem_stock_names = {}
        gem_strong_rise = {}  # {code: {date: change_pct}}
        if gem_star_codes and len(recent_dates) >= 2:
            try:
                conn = self.db._get_connection()
                cursor = conn.cursor()
                start_fmt = f"{recent_dates[0][:4]}-{recent_dates[0][4:6]}-{recent_dates[0][6:8]}"
                end_fmt = f"{recent_dates[-1][:4]}-{recent_dates[-1][4:6]}-{recent_dates[-1][6:8]}"
                placeholders = ','.join(['?'] * len(gem_star_codes))
                cursor.execute(f"""
                    SELECT kd.stock_code, kd.trade_date, kd.change_pct, s.stock_name
                    FROM kline_daily kd
                    LEFT JOIN stocks s ON kd.stock_code = s.stock_code
                    WHERE kd.stock_code IN ({placeholders})
                      AND kd.trade_date >= ? AND kd.trade_date <= ?
                """, gem_star_codes + [start_fmt, end_fmt])
                for row in cursor.fetchall():
                    code = row[0]
                    d = row[1].replace('-', '')
                    change_pct = float(row[2]) if row[2] is not None else 0
                    name = row[3] if row[3] else ''
                    if change_pct >= 10:
                        if code not in gem_strong_rise:
                            gem_strong_rise[code] = {}
                        gem_strong_rise[code][d] = change_pct
                    if name:
                        gem_stock_names[code] = name
                conn.close()
            except Exception:
                pass

        daily_rhythm = []
        for d in recent_dates:
            count = daily_zt_count.get(d, 0)
            stocks_today = []
            if count > 0:
                for s in zt_stocks:
                    code = s['code']
                    if d in stock_zt_sets.get(code, set()):
                        lb = stock_lianban.get(code, {}).get(d, 1)
                        stocks_today.append({
                            'code': code,
                            'name': s['name'],
                            'board': _BOARD_LABEL.get(self._get_board(code), '主'),
                            'lianban': lb,
                            'change_pct': 19.9 if lb > 1 else None,
                            'is_limit_up': True,
                        })
            # 额外添加创业板/科创板大涨股票（涨幅≥10%但未达涨停阈值）
            for code in gem_star_codes:
                if d in gem_strong_rise.get(code, {}):
                    if d in stock_zt_sets.get(code, set()):
                        continue  # 已通过涨停逻辑添加
                    pct = gem_strong_rise[code][d]
                    name = gem_stock_names.get(code, self.stock_name_map.get(code, code))
                    board_en = self._get_board(code)
                    stocks_today.append({
                        'code': code,
                        'name': name,
                        'board': _BOARD_LABEL.get(board_en, '主'),
                        'board_en': board_en,
                        'lianban': 0,
                        'change_pct': round(pct, 1),
                        'is_limit_up': False,
                    })
            count = len(stocks_today)
            daily_rhythm.append({
                'date': d,
                'count': count,
                'display_date': d[4:6] + d[6:8] + '日',
                'stocks': stocks_today,
            })

        # 日期越近排在前面
        daily_rhythm.reverse()

        return {
            'concept': concept_name,
            'total_stocks': len(stock_codes),
            'zt_stock_count': len(zt_stocks),
            'zt_stocks': zt_stocks,
            'peak_dates': [{'date': d, 'count': c} for d, c in peak_dates],
            'daily_rhythm': daily_rhythm,
        }

    # ========== 联动计算 ==========

    def _get_lagged_date(self, base_date: str, lag: int) -> Optional[str]:
        """计算滞后N天的交易日期（lag=0返回当日）O(1)字典查找"""
        idx = self._get_trade_day_index(base_date)
        if idx is None:
            return None
        target_idx = idx + lag
        if 0 <= target_idx < len(self.trade_dates):
            return self.trade_dates[target_idx]
        return None

    def _compute_linkage_probs(self, base_zt_dates: List[str],
                                other_zt_set: Set[str],
                                lags: List[int]) -> Tuple[Dict[int, float], List[Dict]]:
        """
        计算在指定lags下的联动概率和事件详情

        分母 = 基准股票涨停日中有足够距离观测该 lag 的天数
        分子 = 其中另一个股票也在相应日期涨停的天数

        Returns:
            (probs: {lag: probability}, events: [{base_date, lag, linked_date}])
        """
        probs = {}
        all_events = []

        for lag in lags:
            count = 0
            valid_days = 0  # 能观测到该lag的有效基准日数
            events = []

            for base_date in base_zt_dates:
                lagged_date = self._get_lagged_date(base_date, lag)
                if lagged_date is None:
                    continue  # 无法观测到该lag，跳过
                valid_days += 1
                if lagged_date in other_zt_set:
                    count += 1
                    events.append({
                        'base_date': base_date,
                        'lag': lag,
                        'linked_date': lagged_date
                    })

            denominator = max(valid_days, 1)
            probs[lag] = round(count / denominator, 3)
            all_events.extend(events)

        return probs, all_events

    def _build_zt_filter_cache(self) -> Dict[str, Dict]:
        """
        预计算所有股票的4种涨停过滤状态（结果缓存到self._zt_filter_cache）

        N15:   近15个交易日内有涨停
        N15F:  近15日内有涨停，且之前15日(第16~30个交易日)无涨停
        N10ZB: 近10个交易日内有涨停炸板
        N10ZBF:近10日内有涨停炸板，且近15日无涨停（新起势的炸板）

        Returns:
            {code: {'n15': bool, 'n15f': bool, 'n10zb': bool, 'n10zbf': bool}}
        """
        if hasattr(self, '_zt_filter_cache') and self._zt_filter_cache is not None:
            return self._zt_filter_cache

        if not self.trade_dates or len(self.trade_dates) < 15:
            self._zt_filter_cache = {}
            return {}

        cache = {}
        td = self.trade_dates

        # N15 / N15F 窗口
        n15_window = set(td[-15:])                                    # 近15日
        n15f_prev_window = set(td[-30:-15]) if len(td) >= 30 else set()  # 之前15日（第16~30）

        # N10ZB / N10ZBF 窗口
        n10_window = set(td[-10:]) if len(td) >= 10 else set(td)      # 近10日

        # Build {code: set(date)} for zb_count > 0 from zt_pool_records
        zb_records = defaultdict(set)  # {code: set(dates_with_zb)}
        for rec in self.zt_pool_records:
            if rec.get('zb_count', 0) > 0:
                zb_records[rec['stock_code']].add(rec['trade_date'])

        for code, zt_dates_set in self.all_zt_dates.items():
            n15 = bool(zt_dates_set & n15_window)
            n15f = n15 and not bool(zt_dates_set & n15f_prev_window)
            n10zb = bool(zb_records.get(code, set()) & n10_window)
            n10zbf = n10zb and not n15  # 新起势的炸板：有炸板但近15日无涨停

            cache[code] = {
                'n15': n15,
                'n15f': n15f,
                'n10zb': n10zb,
                'n10zbf': n10zbf,
            }

        self._zt_filter_cache = cache
        return cache

    def find_stock_linkages(self, stock_code: str, concept_name: str = None,
                            max_lag: int = 3, min_prob: float = 0.15,
                            filters: List[str] = None) -> Dict:
        """
        查找某只股票的历史联动股票（V5：支持T+0、方向性、去重）

        Returns:
            {
                "stock_code": "000021",
                "stock_name": "深科技",
                "concepts": ["存储芯片", "芯片概念"],
                "base_zt_count": 5,
                "base_zt_dates": [...],
                "data_source": {"zt_pool_count": 3, "db_count": 5},
                "linkages": [
                    {
                        "linked_stock": "000001",
                        "linked_name": "...",
                        "shared_concepts": ["概念A", "概念B"],
                        "prob_t0": 0.3, "prob_t1": 0.5, "prob_t2": 0.4, "prob_t3": 0.3,
                        "strength": 0.375,
                        "total_zt_count": 5,
                        "linked_zt_count": 8,
                        "linkage_events": [...]
                    }
                ],
                "direction_a_to_b": {...},
                "direction_b_to_a": {...}
            }
        """
        stock_code = str(stock_code).zfill(6)
        stock_name = self.get_stock_name(stock_code)

        # 获取该股票所属的概念
        all_concepts = self.get_stock_concepts(stock_code)
        if concept_name:
            concepts = [c for c in all_concepts if c == concept_name]
        else:
            concepts = all_concepts

        if not concepts:
            return {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "concepts": [],
                "base_zt_count": 0,
                "base_zt_dates": [],
                "linkages": [],
                "direction_a_to_b": {},
                "direction_b_to_a": {}
            }

        # 获取基准股票的涨停日期
        base_zt_dates = self.get_stock_zt_dates(stock_code)
        zt_detail = self.get_stock_zt_dates_detail(stock_code)

        if len(base_zt_dates) < 2:
            return {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "concepts": concepts,
                "base_zt_count": len(base_zt_dates),
                "base_zt_dates": base_zt_dates,
                "data_source": {
                    "zt_pool_count": zt_detail['pool_count'],
                    "db_count": zt_detail['db_count']
                },
                "linkages": [],
                "direction_a_to_b": {},
                "direction_b_to_a": {}
            }

        print(f"股票 {stock_code}({stock_name}) 历史涨停 {len(base_zt_dates)} 次")
        print(f"  涨停池源: {zt_detail['pool_count']}次, 数据库源: {zt_detail['db_count']}次")

        # ========== 方向 A→B ==========
        # 对每个同概念股票，计算联动概率
        # 使用字典按股票代码去重，收集所有共享概念
        linked_stocks_map = {}  # {other_code: linkage_info}

        lags = [0, 1, 2, 3] if max_lag >= 0 else list(range(1, max_lag + 1))

        for concept in concepts:
            concept_stock_codes = self.get_concept_stocks(concept)

            for other_code in concept_stock_codes:
                if other_code == stock_code:
                    continue

                other_zt_dates = set(self.get_stock_zt_dates(other_code))
                if not other_zt_dates:
                    continue

                # 如果已存在，追加共享概念
                if other_code in linked_stocks_map:
                    linked_stocks_map[other_code]['shared_concepts'].append(concept)
                    continue

                # 计算 A→B 联动概率
                probs, events = self._compute_linkage_probs(
                    base_zt_dates, other_zt_dates, lags
                )

                # 综合强度（T0+T1+T2+T3的均值，或有效lag的均值）
                valid_probs = [probs.get(l, 0) for l in lags]
                strength = round(sum(valid_probs) / len(valid_probs), 3)

                max_prob = max(valid_probs)

                # 也计算反向 B→A
                rev_probs, _ = self._compute_linkage_probs(
                    sorted(other_zt_dates), set(base_zt_dates), lags
                )

                linked_stocks_map[other_code] = {
                    'linked_stock': other_code,
                    'linked_name': self.get_stock_name(other_code),
                    'shared_concepts': [concept],
                    'prob_t0': probs.get(0, 0),
                    'prob_t1': probs.get(1, 0),
                    'prob_t2': probs.get(2, 0),
                    'prob_t3': probs.get(3, 0),
                    'strength': strength,
                    'total_zt_count': len(base_zt_dates),
                    'linked_zt_count': len(other_zt_dates),
                    'linkage_events': events,
                    # 反向方向
                    'reverse_prob_t0': rev_probs.get(0, 0),
                    'reverse_prob_t1': rev_probs.get(1, 0),
                    'reverse_prob_t2': rev_probs.get(2, 0),
                    'reverse_prob_t3': rev_probs.get(3, 0),
                    'reverse_strength': round(sum(rev_probs.get(l, 0) for l in lags) / len(lags), 3),
                }

        # 过滤
        all_linkages = [v for v in linked_stocks_map.values()
                        if max(v['prob_t0'], v['prob_t1'], v['prob_t2'], v['prob_t3']) >= min_prob]

        all_linkages.sort(key=lambda x: x['strength'], reverse=True)

        # ========== 涨停过滤 (N15/N15F/N10ZB/N10ZBF) ==========
        zt_filter_cache = self._build_zt_filter_cache()
        # Always attach filter_info to every linkage for frontend display
        for link in all_linkages:
            code = link['linked_stock']
            link['filter_info'] = zt_filter_cache.get(code, {})
        # Apply filter if requested
        if filters:
            filtered = []
            for link in all_linkages:
                info = link.get('filter_info', {})
                if any(info.get(f.lower(), False) for f in filters):
                    filtered.append(link)
            all_linkages = filtered

        # ========== 方向 A→B 整体统计 ==========
        direction_a_to_b = {
            'total_linked_stocks': len(all_linkages),
            'strong_linkages': len([l for l in all_linkages if l['strength'] >= 0.3])
        }

        # ========== 方向 B→A 整体统计 ==========
        direction_b_to_a = {
            'total_linked_stocks': len(all_linkages),
            'strong_linkages': len([l for l in all_linkages if l['reverse_strength'] >= 0.3])
        }

        return {
            'stock_code': stock_code,
            'stock_name': stock_name,
            'concepts': concepts,
            'base_zt_count': len(base_zt_dates),
            'base_zt_dates': base_zt_dates,
            'data_source': {
                'zt_pool_count': zt_detail['pool_count'],
                'db_count': zt_detail['db_count']
            },
            'linkages': all_linkages,
            'direction_a_to_b': direction_a_to_b,
            'direction_b_to_a': direction_b_to_a
        }

    def print_linkage_report(self, result: Dict):
        """打印联动报告（V5：支持T+0、去重、方向性）"""
        print(f"\n{'='*85}")
        print(f"股票联动分析报告: {result['stock_code']} {result['stock_name']}")
        print(f"所属概念: {', '.join(result['concepts'])}")
        print(f"历史涨停次数: {result['base_zt_count']}")
        if 'data_source' in result:
            ds = result['data_source']
            print(f"  数据源: 涨停池{ds['zt_pool_count']}次 + 数据库{ds['db_count']}次")
        print('='*85)

        if not result['linkages']:
            print("未找到联动股票（可能是涨停次数不足或无历史联动）")
            return

        print(f"\n{'股票代码':<10} {'股票名称':<12} {'概念数':<6} {'T+0':<8} {'T+1':<8} {'T+2':<8} {'T+3':<8} {'综合':<8} {'联动次数':<8} {'自身ZT'}")
        print('-' * 85)

        for link in result['linkages'][:30]:
            event_count = len(link['linkage_events'])
            concept_count = len(link['shared_concepts'])
            print(f"{link['linked_stock']:<10} {link['linked_name']:<12} "
                  f"{concept_count:<6} "
                  f"{link['prob_t0']:.0%}    {link['prob_t1']:.0%}    {link['prob_t2']:.0%}    {link['prob_t3']:.0%}    "
                  f"{link['strength']:.0%}    {event_count:<8} {link['linked_zt_count']}")

        # 按概念分组 - 去重后展示
        print("\n" + "=" * 85)
        print("按概念分组 - 联动股票详情（去重）")
        print("=" * 85)

        concept_groups = defaultdict(list)
        for link in result['linkages']:
            for concept in link['shared_concepts']:
                concept_groups[concept].append(link)

        for concept, links in concept_groups.items():
            print(f"\n【{concept}】({len(links)}只联动股票)")
            for link in links[:10]:
                events_str = f"{len(link['linkage_events'])}次联动"
                rev_strength = link.get('reverse_strength', 0)
                print(f"  → {link['linked_stock']} {link['linked_name']}: "
                      f"T+0={link['prob_t0']:.0%} T+1={link['prob_t1']:.0%} T+2={link['prob_t2']:.0%} T+3={link['prob_t3']:.0%} "
                      f"({events_str}, 反向={rev_strength:.0%})")

                if len(link['linkage_events']) <= 8:
                    for evt in link['linkage_events']:
                        label = f"T+{evt['lag']}" if evt['lag'] > 0 else "T+0"
                        print(f"      {evt['base_date']}涨停 -> {label} {evt['linked_date']}涨停")

    def analyze_concept_linkages(self, concept_name: str, top_n: int = 30) -> List[Dict]:
        """分析概念内所有股票的联动关系，找出最强的联动对（V5：支持T+0、方向性）"""
        stock_codes = self.get_concept_stocks(concept_name)

        if not stock_codes:
            return []

        print(f"\n分析概念【{concept_name}】({len(stock_codes)}只股票)的联动关系...")

        zt_stocks = [(c, self.get_stock_zt_dates(c)) for c in stock_codes if self.get_stock_zt_dates(c)]
        print(f"  其中 {len(zt_stocks)} 只股票有涨停记录")

        if len(zt_stocks) < 2:
            return []

        all_pairs = []
        lags = [0, 1, 2, 3]

        for i, (code_a, base_zt_a) in enumerate(zt_stocks):
            if len(base_zt_a) < 2:
                continue

            for code_b, zt_b in zt_stocks[i+1:]:
                other_zt_dates = set(zt_b)

                probs_a_to_b, _ = self._compute_linkage_probs(base_zt_a, other_zt_dates, lags)
                probs_b_to_a, _ = self._compute_linkage_probs(
                    sorted(other_zt_dates), set(base_zt_a), lags
                )

                avg_prob_a_to_b = round(sum(probs_a_to_b.get(l, 0) for l in lags) / len(lags), 3)

                if avg_prob_a_to_b >= 0.15:
                    all_pairs.append({
                        'stock_a': code_a,
                        'name_a': self.get_stock_name(code_a),
                        'stock_b': code_b,
                        'name_b': self.get_stock_name(code_b),
                        'concept': concept_name,
                        'prob_t0': probs_a_to_b.get(0, 0),
                        'lag1_prob': probs_a_to_b.get(1, 0),
                        'lag2_prob': probs_a_to_b.get(2, 0),
                        'lag3_prob': probs_a_to_b.get(3, 0),
                        'strength': avg_prob_a_to_b,
                        'prob_b_to_a_t0': probs_b_to_a.get(0, 0),
                        'lag1_prob_b_to_a': probs_b_to_a.get(1, 0),
                        'lag2_prob_b_to_a': probs_b_to_a.get(2, 0),
                        'lag3_prob_b_to_a': probs_b_to_a.get(3, 0),
                        'strength_b_to_a': round(sum(probs_b_to_a.get(l, 0) for l in lags) / len(lags), 3),
                        'zt_count_a': len(base_zt_a),
                        'zt_count_b': len(other_zt_dates)
                    })

        all_pairs.sort(key=lambda x: x['strength'], reverse=True)
        return all_pairs[:top_n]

    def print_concept_linkage_report(self, concept_name: str):
        """打印概念联动报告"""
        pairs = self.analyze_concept_linkages(concept_name)

        if not pairs:
            print(f"\n概念【{concept_name}】没有找到足够的联动关系")
            return

        print(f"\n{'='*80}")
        print(f"概念【{concept_name}】联动分析报告")
        print(f"{'='*80}")
        print(f"\nTop {len(pairs)} 最强联动股票对:")
        print(f"\n{'股票A':<10} {'名称A':<12} {'->':<4} {'股票B':<10} {'名称B':<12} {'T+0':<8} {'T+1':<8} {'T+2':<8} {'T+3':<8} {'综合':<8}")
        print('-' * 95)

        for p in pairs:
            print(f"{p['stock_a']:<10} {p['name_a']:<12} ->  {p['stock_b']:<10} {p['name_b']:<12} "
                  f"{p['prob_t0']:.0%}    {p['lag1_prob']:.0%}    {p['lag2_prob']:.0%}    {p['lag3_prob']:.0%}    {p['strength']:.0%}")

    # ========== 统计分析 ==========

    def _filter_zt_dates_by_range(self, start_date: str = None, end_date: str = None) -> Dict[str, set]:
        """按日期范围过滤all_zt_dates"""
        if not start_date and not end_date:
            return self.all_zt_dates
        filtered = {}
        for code, dates in self.all_zt_dates.items():
            fd = set()
            for d in dates:
                if start_date and d < start_date:
                    continue
                if end_date and d > end_date:
                    continue
                fd.add(d)
            if fd:
                filtered[code] = fd
        return filtered

    def get_stats_summary(self, start_date: str = None, end_date: str = None) -> Dict:
        """获取整体统计摘要"""
        zt_data = self._filter_zt_dates_by_range(start_date, end_date)
        all_stocks_with_zt = set(zt_data.keys())

        total_zt_events = 0
        stock_zt_counts = []
        for code, dates in zt_data.items():
            total_zt_events += len(dates)
            stock_zt_counts.append({'code': code, 'name': self.get_stock_name(code), 'count': len(dates)})

        # 按照涨停次数分桶
        buckets = {'1次': 0, '2-3次': 0, '4-6次': 0, '7-10次': 0, '11-20次': 0, '20次以上': 0}
        for s in stock_zt_counts:
            c = s['count']
            if c == 1: buckets['1次'] += 1
            elif c <= 3: buckets['2-3次'] += 1
            elif c <= 6: buckets['4-6次'] += 1
            elif c <= 10: buckets['7-10次'] += 1
            elif c <= 20: buckets['11-20次'] += 1
            else: buckets['20次以上'] += 1

        # 日期范围
        all_dates = set()
        for dates in zt_data.values():
            all_dates.update(dates)
        sorted_dates = sorted(all_dates)

        # 额外维度：连板统计
        lianban_counts = {'1板': 0, '2板': 0, '3板': 0, '4板': 0, '5板+': 0}
        for code, dates in zt_data.items():
            sd = sorted(dates)
            lb = 1
            for i in range(1, len(sd)):
                if self._get_trade_day_diff(sd[i-1], sd[i]) <= 1:
                    lb += 1
                else:
                    if lb == 1: lianban_counts['1板'] += 1
                    elif lb == 2: lianban_counts['2板'] += 1
                    elif lb == 3: lianban_counts['3板'] += 1
                    elif lb == 4: lianban_counts['4板'] += 1
                    else: lianban_counts['5板+'] += 1
                    lb = 1
            if lb == 1: lianban_counts['1板'] += 1
            elif lb == 2: lianban_counts['2板'] += 1
            elif lb == 3: lianban_counts['3板'] += 1
            elif lb == 4: lianban_counts['4板'] += 1
            else: lianban_counts['5板+'] += 1

        # 概念热度排名（涨停股票最多的概念）
        concept_zt_ranks = []
        for cn, ss in self.concept_stocks.items():
            zsc = sum(1 for c in ss if c in zt_data and zt_data[c])
            if zsc > 0:
                concept_zt_ranks.append({'concept': cn, 'zt_stock_count': zsc})
        concept_zt_ranks.sort(key=lambda x: x['zt_stock_count'], reverse=True)
        top_concepts_by_zs = [c['concept'] for c in concept_zt_ranks[:5]]

        return {
            'total_stocks_with_zt': len(all_stocks_with_zt),
            'total_stocks_in_system': len(self.stock_concepts),
            'total_concepts': len(self.concept_stocks),
            'total_zt_events': total_zt_events,
            'daily_zt_distribution': buckets,
            'lianban_distribution': lianban_counts,
            'date_range': {
                'start': sorted_dates[0] if sorted_dates else '',
                'end': sorted_dates[-1] if sorted_dates else '',
                'total_days': len(sorted_dates)
            }
        }

    def _get_trade_day_diff(self, d1: str, d2: str) -> int:
        """估算两个交易日的间隔（交易日数）"""
        try:
            # 如果在交易日历中，用索引差
            if hasattr(self, 'trade_dates') and self.trade_dates:
                if d1 in self.trade_dates and d2 in self.trade_dates:
                    i1 = self._get_trade_day_index(d1)
                    i2 = self._get_trade_day_index(d2)
                    return abs(i2 - i1)
        except:
            pass
        # fallback: 自然日差值
        from datetime import datetime
        dt1 = datetime.strptime(d1, '%Y%m%d')
        dt2 = datetime.strptime(d2, '%Y%m%d')
        return abs((dt2 - dt1).days)

    def get_top_stocks_by_zt(self, top_n: int = 30,
                              start_date: str = None, end_date: str = None) -> List[Dict]:
        """获取涨停次数最多的股票"""
        zt_data = self._filter_zt_dates_by_range(start_date, end_date)
        stock_list = []
        for code, dates in zt_data.items():
            stock_list.append({
                'code': code,
                'name': self.get_stock_name(code),
                'zt_count': len(dates),
                'concept_count': len(self.stock_concepts.get(code, set())),
                'last_zt': sorted(dates)[-1] if dates else ''
            })
        stock_list.sort(key=lambda x: x['zt_count'], reverse=True)
        return stock_list[:top_n]

    def get_hot_stocks_weighted(self, top_n: int = 200,
                                 start_date: str = None, end_date: str = None) -> List[Dict]:
        """获取涨停股票加权综合评分（次数40% + 近期热度60% + 概念标签）

        Returns:
            [{
                'code', 'name', 'zt_count', 'last_zt', 'first_zt',
                'weighted_score', 'recency_score',
                'concepts': [...], 'concept_count': N,
                'date_range_text': '250219~260515'
            }]
        """
        zt_data = self._filter_zt_dates_by_range(start_date, end_date)

        # 参考日期
        if end_date:
            ref_date = datetime.strptime(end_date, '%Y%m%d')
        else:
            ref_date = datetime.strptime(self.trade_dates[-1], '%Y%m%d') if self.trade_dates else datetime.now()

        stock_list = []
        for code, dates in zt_data.items():
            sorted_dates = sorted(dates)
            if not sorted_dates:
                continue
            zt_count = len(sorted_dates)
            first_zt = sorted_dates[0]
            last_zt = sorted_dates[-1]

            # recency_score: 最近涨停距离参考日越近越高
            try:
                last_dt = datetime.strptime(last_zt, '%Y%m%d')
                days_diff = (ref_date - last_dt).days
                recency_score = max(0, 100 - days_diff * 3)  # 每远1天减3分
            except Exception:
                recency_score = 50

            weighted_score = round(zt_count * 0.4 + recency_score * 0.6, 1)

            # 日期范围简写
            date_range_text = first_zt[2:] + '~' + last_zt[2:]

            stock_list.append({
                'code': code,
                'name': self.get_stock_name(code),
                'zt_count': zt_count,
                'last_zt': last_zt,
                'first_zt': first_zt,
                'weighted_score': weighted_score,
                'recency_score': round(recency_score, 1),
                'concepts': list(self.stock_concepts.get(code, set()))[:5],
                'concept_count': len(self.stock_concepts.get(code, set())),
                'date_range_text': date_range_text,
            })

        stock_list.sort(key=lambda x: x['weighted_score'], reverse=True)
        return stock_list[:top_n]

    def get_top_concepts_by_zt(self, top_n: int = 30,
                                start_date: str = None, end_date: str = None) -> List[Dict]:
        """获取涨停活跃度最高的概念"""
        zt_data = self._filter_zt_dates_by_range(start_date, end_date)
        concept_list = []
        for concept_name, stocks in self.concept_stocks.items():
            total_zt = 0
            zt_stock_count = 0
            for code in stocks:
                dates = zt_data.get(code, set())
                if dates:
                    total_zt += len(dates)
                    zt_stock_count += 1
            concept_list.append({
                'concept': concept_name,
                'total_stocks': len(stocks),
                'zt_stock_count': zt_stock_count,
                'total_zt_events': total_zt,
                'avg_zt_per_stock': round(total_zt / max(len(stocks), 1), 1)
            })
        concept_list.sort(key=lambda x: x['total_zt_events'], reverse=True)
        return concept_list[:top_n]

    def get_daily_zt_activity(self, days: int = 60,
                               start_date: str = None, end_date: str = None) -> List[Dict]:
        """获取每日涨停股票数量（按交易日）"""
        zt_data = self._filter_zt_dates_by_range(start_date, end_date)
        daily_count = defaultdict(int)
        for code, dates in zt_data.items():
            for d in dates:
                daily_count[d] += 1

        sorted_dates = sorted(daily_count.keys())
        if start_date:
            sorted_dates = [d for d in sorted_dates if d >= start_date]
        if end_date:
            sorted_dates = [d for d in sorted_dates if d <= end_date]
        if days and not start_date and not end_date:
            sorted_dates = sorted_dates[-days:] if len(sorted_dates) > days else sorted_dates

        result = []
        for d in sorted_dates:
            result.append({
                'date': d,
                'zt_count': daily_count[d]
            })

        return result

    def get_stocks_in_zt_bucket(self, bucket_key: str,
                                 start_date: str = None, end_date: str = None,
                                 top_n: int = 100) -> List[Dict]:
        """获取涨停次数分布中某个桶的股票详情"""
        zt_data = self._filter_zt_dates_by_range(start_date, end_date)
        stock_list = []
        for code, dates in zt_data.items():
            count = len(dates)
            in_bucket = False
            if bucket_key == '1次' and count == 1:
                in_bucket = True
            elif bucket_key == '2-3次' and 2 <= count <= 3:
                in_bucket = True
            elif bucket_key == '4-6次' and 4 <= count <= 6:
                in_bucket = True
            elif bucket_key == '7-10次' and 7 <= count <= 10:
                in_bucket = True
            elif bucket_key == '11-20次' and 11 <= count <= 20:
                in_bucket = True
            elif bucket_key == '20次以上' and count > 20:
                in_bucket = True
            if in_bucket:
                stock_list.append({
                    'code': code,
                    'name': self.get_stock_name(code),
                    'zt_count': count,
                    'concepts': list(self.stock_concepts.get(code, set()))[:5],
                    'last_zt': sorted(dates)[-1]
                })
        stock_list.sort(key=lambda x: x['zt_count'], reverse=True)
        return stock_list[:top_n]

    def get_stocks_in_lianban_bucket(self, bucket_key: str,
                                      start_date: str = None, end_date: str = None,
                                      top_n: int = 100) -> List[Dict]:
        """获取连板分布中某个桶的股票详情"""
        zt_data = self._filter_zt_dates_by_range(start_date, end_date)
        stock_list = []
        for code, dates in zt_data.items():
            sd = sorted(dates)
            max_lb = 1
            cur_lb = 1
            for i in range(1, len(sd)):
                if self._get_trade_day_diff(sd[i-1], sd[i]) <= 1:
                    cur_lb += 1
                    max_lb = max(max_lb, cur_lb)
                else:
                    cur_lb = 1
            in_bucket = False
            if bucket_key == '1板' and max_lb == 1:
                in_bucket = True
            elif bucket_key == '2板' and max_lb == 2:
                in_bucket = True
            elif bucket_key == '3板' and max_lb == 3:
                in_bucket = True
            elif bucket_key == '4板' and max_lb == 4:
                in_bucket = True
            elif bucket_key == '5板+' and max_lb >= 5:
                in_bucket = True
            if in_bucket:
                # 找连板日期序列
                cur_dates = [sd[0]]
                best_dates = []
                for i in range(1, len(sd)):
                    if self._get_trade_day_diff(sd[i-1], sd[i]) <= 1:
                        cur_dates.append(sd[i])
                        if len(cur_dates) >= max_lb:
                            best_dates = list(cur_dates)
                    else:
                        if len(cur_dates) > len(best_dates):
                            best_dates = list(cur_dates)
                        cur_dates = [sd[i]]
                if len(cur_dates) > len(best_dates):
                    best_dates = cur_dates

                stock_list.append({
                    'code': code,
                    'name': self.get_stock_name(code),
                    'max_lianban': max_lb,
                    'lianban_dates': best_dates[-max_lb:] if best_dates else sd[-max_lb:],
                    'lianban_end_date': best_dates[-1] if best_dates else (sd[-1] if sd else ''),
                    'concepts': list(self.stock_concepts.get(code, set()))[:5]
                })
        stock_list.sort(key=lambda x: (x['max_lianban'], x['lianban_end_date']), reverse=True)
        return stock_list[:top_n]

    def get_concept_daily_heatmap(self, top_concepts: int = 10, days: int = 30) -> Dict:
        """
        获取概念每日涨停热度矩阵

        Returns:
            {
                "concepts": ["概念A", "概念B", ...],
                "dates": ["20260401", "20260402", ...],
                "matrix": [[0, 1, 2, ...], [...], ...]
            }
        """
        # 先找最活跃的概念
        top_concepts_data = self.get_top_concepts_by_zt(top_concepts * 2)[:top_concepts]
        concept_names = [c['concept'] for c in top_concepts_data]

        # 获取最近days天的涨停日期
        all_dates = set()
        for d in self.trade_dates:
            all_dates.add(d)
        sorted_dates = sorted(all_dates)
        recent_dates = sorted_dates[-days:] if len(sorted_dates) > days else sorted_dates

        # 构建矩阵
        matrix = []
        for concept_name in concept_names:
            stocks = self.concept_stocks.get(concept_name, set())
            row = []
            for d in recent_dates:
                # 该概念在该日期涨停的股票数量
                count = 0
                for code in stocks:
                    if d in self.all_zt_dates.get(code, set()):
                        count += 1
                row.append(count)
            matrix.append(row)

        return {
            'concepts': concept_names,
            'dates': recent_dates,
            'matrix': matrix
        }

    # ========== 涨停回调买入推荐 ==========

    def recommend_pullback_stocks(self, lookback_days: int = 15, top_n: int = 30) -> List[Dict]:
        """
        推荐涨停后回调买入的股票

        策略：
        1. 筛选近 lookback_days 个交易日有涨停的股票
        2. 分析每只股票的回调状态（连板数、回调天数、回调幅度、量价关系）
        3. 评分并排序，推荐回调企稳的股票

        Returns:
            [{
                "code": "000001",
                "name": "...",
                "recent_zt_dates": [...],
                "last_zt_date": "...",
                "zt_count": 5,
                "max_lianban": 3,
                "pullback_days": 2,
                "pullback_depth_pct": 3.5,
                "current_close": 12.5,
                "volume_ratio": 0.6,
                "ma5_support": True,
                "concepts": [...],
                "pullback_score": 85,
                "heat_score": 75,
                "total_score": 81,
                "buy_advice": "回调至MA5附近，缩量企稳后可介入"
            }]
        """
        # 获取最近交易日
        if len(self.trade_dates) < lookback_days + 5:
            lookback_days = max(len(self.trade_dates) - 5, 5)

        recent_trade_dates = self.trade_dates[-lookback_days:]  # 观察窗口
        lookback_start = recent_trade_dates[0]
        min_kline_dates = max(20, lookback_days + 10)

        # 用于分析的最后交易日（最近有 K 线数据的交易日）
        last_trade_date = self.trade_dates[-1]

        # 1. 找到观察窗口内有涨停的股票
        candidate_stocks = {}  # {code: zt_dates_in_window}
        for code, all_dates in self.all_zt_dates.items():
            zt_in_window = [d for d in all_dates if d >= lookback_start and d <= last_trade_date]
            if len(zt_in_window) >= 1:
                candidate_stocks[code] = sorted(zt_in_window)

        print(f"近{lookback_days}天有涨停的候选股票: {len(candidate_stocks)}只")

        # 2. 从数据库批量获取K线数据（单次批量查询替代逐条查询）
        conn = None
        kline_batch = {}  # {code: [{date, open, high, low, close, volume}, ...]}
        try:
            conn = self.db._get_connection()
            cursor = conn.cursor()

            # 计算K线查询起始日期：从 lookback_start 再往前推10天
            kline_start = max(0, self._get_trade_day_index(lookback_start) - 10)
            kline_start_date = self.trade_dates[kline_start]
            start_date_str = f"{kline_start_date[:4]}-{kline_start_date[4:6]}-{kline_start_date[6:]}"

            codes = list(candidate_stocks.keys())
            # SQLite变量数限制约999，分批查询每批500
            batch_size = 500
            for batch_start in range(0, len(codes), batch_size):
                batch_codes = codes[batch_start:batch_start + batch_size]
                placeholders = ','.join(['?'] * len(batch_codes))
                cursor.execute(f"""
                    SELECT stock_code, trade_date, open, high, low, close, volume, change_pct
                    FROM kline_daily
                    WHERE stock_code IN ({placeholders}) AND trade_date >= ?
                    ORDER BY stock_code, trade_date
                """, batch_codes + [start_date_str])
                for row in cursor.fetchall():
                    code = row[0]
                    d = row[1].replace('-', '') if row[1] else ''
                    kline = {
                        'date': d,
                        'open': float(row[2]),
                        'high': float(row[3]),
                        'low': float(row[4]),
                        'close': float(row[5]),
                        'volume': float(row[6]),
                        'change_pct': float(row[7]) if row[7] else 0
                    }
                    if code not in kline_batch:
                        kline_batch[code] = []
                    kline_batch[code].append(kline)
        except Exception as e:
            print(f"批量查询K线失败: {e}")
        finally:
            if conn:
                conn.close()

        print(f"有K线数据的候选股票: {len(kline_batch)}只")

        # 3. 分析每只股票的回调状态
        # 先查询概念热度
        concept_heat = {}
        for concept_name, stocks in self.concept_stocks.items():
            heat = 0
            for code in stocks:
                if code in candidate_stocks:
                    heat += len(candidate_stocks[code])
            if heat > 0:
                concept_heat[concept_name] = heat
        # 归一化
        max_concept_heat = max(concept_heat.values()) if concept_heat else 1

        recommendations = []

        for code, zt_dates in candidate_stocks.items():
            if code not in kline_batch:
                continue

            klines = kline_batch[code]
            if len(klines) < 5:
                continue

            # 最新K线数据
            latest = klines[-1]
            current_close = latest['close']
            last_zt_date = zt_dates[-1]

            # 找到最近涨停日在K线数据中的位置
            zt_kline_indices = [i for i, k in enumerate(klines) if k['date'] in zt_dates]

            if not zt_kline_indices:
                continue

            last_zt_idx = zt_kline_indices[-1]

            # --- 计算连板情况 ---
            # 简单检测：在最近涨停中找连续涨停
            max_lianban = 1
            current_lianban = 1
            for i in range(len(zt_dates) - 1, 0, -1):
                d1 = zt_dates[i]
                d2 = zt_dates[i-1]
                # 检查是否连续交易日
                idx1 = self._get_trade_day_index(d1)
                idx2 = self._get_trade_day_index(d2)
                if idx1 is not None and idx2 is not None:
                    if idx1 - idx2 == 1:
                        current_lianban += 1
                        max_lianban = max(max_lianban, current_lianban)
                    else:
                        current_lianban = 1
                else:
                    current_lianban = 1

            # --- 计算回调天数 ---
            pullback_days = len(klines) - last_zt_idx - 1

            # 如果还在涨停中（pullback_days = 0），跳过
            if pullback_days <= 0:
                continue

            # --- 计算回调幅度 ---
            # 从最近 N 天高点到当前价
            recent_high = max(k['high'] for k in klines[last_zt_idx:])
            pullback_depth_pct = round((recent_high - current_close) / recent_high * 100, 2)

            # 如果回调太深（超过12%），可能趋势已坏
            if pullback_depth_pct > 12:
                continue

            # --- 计算成交量萎缩比例 ---
            # 涨停期间（涨停日及前2天）的平均成交量
            zt_vol_start = max(0, last_zt_idx - 2)
            zt_vol_end = min(len(klines), last_zt_idx + 1)
            zt_avg_vol = sum(k['volume'] for k in klines[zt_vol_start:zt_vol_end]) / max(zt_vol_end - zt_vol_start, 1)

            # 最近2天的平均成交量
            recent_vol_start = max(0, len(klines) - 3)
            recent_avg_vol = sum(k['volume'] for k in klines[recent_vol_start:]) / max(len(klines) - recent_vol_start, 1)

            volume_ratio = round(recent_avg_vol / max(zt_avg_vol, 0.01), 2) if zt_avg_vol > 0 else 1.0

            # --- 均线位置 ---
            # 计算MA5和MA10
            if len(klines) >= 5:
                ma5 = sum(k['close'] for k in klines[-5:]) / 5
            else:
                ma5 = current_close

            if len(klines) >= 10:
                ma10 = sum(k['close'] for k in klines[-10:]) / 10
            else:
                ma10 = current_close

            above_ma5 = current_close >= ma5
            above_ma10 = current_close >= ma10
            distance_to_ma5_pct = round((current_close - ma5) / ma5 * 100, 2) if ma5 > 0 else 0
            distance_to_ma10_pct = round((current_close - ma10) / ma10 * 100, 2) if ma10 > 0 else 0

            # --- 概念热度 ---
            codes_concepts = self.stock_concepts.get(code, set())
            concept_heat_score = 0
            hot_concepts = []
            for c in codes_concepts:
                h = concept_heat.get(c, 0)
                if h > 0:
                    concept_heat_score += h
                    hot_concepts.append((c, h))

            hot_concepts.sort(key=lambda x: x[1], reverse=True)
            concept_heat_norm = min(concept_heat_score / max_concept_heat, 1.0) if max_concept_heat > 0 else 0

            # ===== 综合评分 =====

            # 回调质量评分 (0-100)
            # 1. 回调天数评分: 1-3天最佳, 4-5天次之, >5天递减
            timing_score = max(0, 100 - abs(pullback_days - 2) * 25)

            # 2. 回调幅度评分: 2-6%最佳
            if 2 <= pullback_depth_pct <= 6:
                depth_score = 100
            elif pullback_depth_pct < 2:
                depth_score = max(0, pullback_depth_pct / 2 * 80)  # <2%可能还没调到位
            else:  # >6%
                depth_score = max(0, 100 - (pullback_depth_pct - 6) * 15)

            # 3. 量价评分: 缩量好（volume_ratio < 0.7）
            if volume_ratio <= 0.7:
                volume_score = 100
            elif volume_ratio <= 1.0:
                volume_score = 70
            elif volume_ratio <= 1.5:
                volume_score = 40
            else:
                volume_score = 10

            # 4. 均线支撑评分
            if above_ma5:
                ma_score = 80 + max(0, 20 - abs(distance_to_ma5_pct) * 5)  # 接近MA5最好
            elif above_ma10:
                ma_score = 50
            else:
                ma_score = max(0, 30 - abs(distance_to_ma10_pct) * 3)

            # 5. 动量评分（连板数越高越好）
            momentum_score = min(max_lianban * 25, 100)

            pullback_score = (
                depth_score * 0.30 +
                timing_score * 0.20 +
                volume_score * 0.20 +
                ma_score * 0.15 +
                momentum_score * 0.15
            )

            # 热度评分 (0-100)
            zt_heat = min(len(zt_dates) * 20, 100)
            heat_score = (
                zt_heat * 0.40 +
                concept_heat_norm * 100 * 0.30 +
                momentum_score * 0.30
            )

            # 总分: 回调质量 60% + 热度 40%
            total_score = round(pullback_score * 0.60 + heat_score * 0.40, 1)

            # --- 买点建议 ---
            buy_advice = self._generate_buy_advice(
                pullback_days, pullback_depth_pct, volume_ratio,
                above_ma5, above_ma10, distance_to_ma5_pct,
                distance_to_ma10_pct, max_lianban, pullback_score
            )

            recommendations.append({
                'code': code,
                'name': self.get_stock_name(code),
                'recent_zt_dates': zt_dates,
                'last_zt_date': last_zt_date,
                'zt_count': len(zt_dates),
                'max_lianban': max_lianban,
                'pullback_days': pullback_days,
                'pullback_depth_pct': pullback_depth_pct,
                'current_close': current_close,
                'volume_ratio': volume_ratio,
                'above_ma5': above_ma5,
                'above_ma10': above_ma10,
                'distance_to_ma5': distance_to_ma5_pct,
                'hot_concepts': [c for c, _ in hot_concepts[:3]],
                'pullback_score': round(pullback_score, 1),
                'heat_score': round(heat_score, 1),
                'total_score': total_score,
                'buy_advice': buy_advice
            })

        # 按总分排序
        recommendations.sort(key=lambda x: x['total_score'], reverse=True)
        print(f"推荐结果: {len(recommendations)}只")
        return recommendations[:top_n]

    def _generate_buy_advice(self, pullback_days, depth_pct, vol_ratio,
                              above_ma5, above_ma10, dist_ma5, dist_ma10,
                              lianban, score) -> str:
        """生成买入建议"""
        parts = []

        if lianban >= 4:
            parts.append(f"强势{max(3, lianban)}连板后回调")
        elif lianban >= 2:
            parts.append(f"{lianban}连板后回调")
        else:
            parts.append("涨停后回调")

        # 回调天数
        if 1 <= pullback_days <= 2:
            parts.append(f"回调{pullback_days}天")
        else:
            parts.append(f"回调{pullback_days}天")

        # 回调深度
        if 2 <= depth_pct <= 5:
            parts.append(f"深度{depth_pct:.1f}%适中")
        elif depth_pct < 2:
            parts.append(f"深度{depth_pct:.1f}%较浅")
        else:
            parts.append(f"深度{depth_pct:.1f}%偏深")

        # 量价
        if vol_ratio < 0.6:
            parts.append("缩量明显企稳")
        elif vol_ratio < 0.9:
            parts.append("缩量调整中")

        # 均线
        if above_ma5 and dist_ma5 > -2:
            if dist_ma5 < 1:
                parts.append("回踩MA5附近")
            else:
                parts.append(f"站上MA5 ({dist_ma5:+.1f}%)")
        elif not above_ma5 and above_ma10:
            parts.append(f"破MA5, 关注MA10支撑 ({dist_ma10:+.1f}%)")
        elif not above_ma10:
            parts.append(f"破MA10 ({dist_ma10:+.1f}%), 谨慎")

        # 最终建议
        if score >= 75:
            parts.append("⭐ 推荐关注")
        elif score >= 60:
            parts.append("可观察")
        else:
            parts.append("一般关注")

        return "，".join(parts)

    # ========== N字战法分析 ==========

    def _get_board(self, code: str) -> str:
        """确定股票所属板块"""
        if code.startswith(('300', '301')):
            return 'gem'
        elif code.startswith('688'):
            return 'star'
        elif code.startswith(('4', '8')):
            return 'bj'
        else:
            return 'main'

    def analyze_n_pattern(self, lookback_days: int = 20) -> Dict:
        """
        N字战法分析：涨停后回调识别二波主升机会

        按回调深度分类 -> 按板块分组 -> 每个股票含K线数据

        Returns:
            {
                'categories': {
                    '0-2': {'name': '涨停回调0~2%', 'main_board': [...], 'gem': [...], 'star': [...], 'bj': []},
                    '2-5': {...}, '5-8': {...}, '8-10': {...}, '10+': {...}
                },
                'alerts': {'zha_ban': [...], 'gem_alert': [...]},
                'update_time': '...'
            }
        """
        if len(self.trade_dates) < lookback_days + 5:
            lookback_days = max(len(self.trade_dates) - 5, 10)

        recent_trade_dates = self.trade_dates[-lookback_days:]
        lookback_start = recent_trade_dates[0]
        last_trade_date = recent_trade_dates[-1]

        # 1. 找到观察窗口内有涨停的股票
        candidate_stocks = {}
        for code, all_dates in self.all_zt_dates.items():
            zt_in_window = [d for d in all_dates if d >= lookback_start and d <= last_trade_date]
            if zt_in_window:
                candidate_stocks[code] = sorted(zt_in_window)

        print(f"N字战法: 近{lookback_days}天有涨停的候选股票: {len(candidate_stocks)}只")

        if not candidate_stocks:
            return self._empty_n_pattern_result()

        # 2. 批量获取K线数据（单次批量查询替代逐条查询）
        conn = None
        kline_batch = {}
        try:
            conn = self.db._get_connection()
            cursor = conn.cursor()

            kline_start_idx = max(0, self._get_trade_day_index(lookback_start) - 30)
            kline_start_date = self.trade_dates[kline_start_idx]
            start_date_str = f"{kline_start_date[:4]}-{kline_start_date[4:6]}-{kline_start_date[6:]}"

            codes = list(candidate_stocks.keys())
            # SQLite变量数限制约999，分批查询每批500
            batch_size = 500
            for batch_start in range(0, len(codes), batch_size):
                batch_codes = codes[batch_start:batch_start + batch_size]
                placeholders = ','.join(['?'] * len(batch_codes))
                cursor.execute(f"""
                    SELECT stock_code, trade_date, open, high, low, close, volume, change_pct
                    FROM kline_daily
                    WHERE stock_code IN ({placeholders}) AND trade_date >= ?
                    ORDER BY stock_code, trade_date
                """, batch_codes + [start_date_str])
                for row in cursor.fetchall():
                    code = row[0]
                    d = row[1].replace('-', '') if row[1] else ''
                    kline = {
                        'date': d,
                        'open': float(row[2]),
                        'high': float(row[3]),
                        'low': float(row[4]),
                        'close': float(row[5]),
                        'volume': float(row[6]),
                        'change_pct': float(row[7]) if row[7] else 0
                    }
                    if code not in kline_batch:
                        kline_batch[code] = []
                    kline_batch[code].append(kline)
        except Exception as e:
            print(f"N字战法: 批量查询K线失败: {e}")
        finally:
            if conn:
                conn.close()

        print(f"N字战法: 有K线数据的候选股票: {len(kline_batch)}只")

        # 3. 整理炸板索引: {code: {date: zb_count}}
        zb_index = defaultdict(dict)
        for rec in self.zt_pool_records:
            if rec['zb_count'] > 0:
                zb_index[rec['stock_code']][rec['trade_date']] = rec['zb_count']

        # 4. 分析每只股票
        # 初始化分类
        cat_keys = ['tld', '0-2', '2-5', '5-8', '8-10', '10+']
        categories = {}
        for ck in cat_keys:
            categories[ck] = {
                'name': self._get_category_name(ck),
                'main_board': [], 'gem': [], 'star': [], 'bj': []
            }

        alerts_zhaban_list = []
        alerts_gem_list = []

        for code, zt_dates in candidate_stocks.items():
            if code not in kline_batch:
                continue

            klines = kline_batch[code]
            if len(klines) < 5:
                continue

            # 从kline数据构建日期->索引映射
            kline_date_map = {k['date']: i for i, k in enumerate(klines)}

            # 找出连板链（从最后一个涨停往前）
            last_zt_date = zt_dates[-1]
            if last_zt_date not in kline_date_map:
                continue

            # 反向检测连板链
            lianban_chain = [last_zt_date]
            for i in range(len(zt_dates) - 2, -1, -1):
                d1 = zt_dates[i]
                d2 = zt_dates[i + 1]
                idx1 = self._get_trade_day_index(d1)
                idx2 = self._get_trade_day_index(d2)
                if idx1 is not None and idx2 is not None and idx2 - idx1 == 1:
                    lianban_chain.insert(0, d1)
                else:
                    break

            first_zt_date = lianban_chain[0]
            lianban_count = len(lianban_chain)

            # 找连板首日在前一天的K线位置（获取base_price）
            first_zt_idx = kline_date_map.get(first_zt_date, -1)
            if first_zt_idx <= 0:
                continue
            # base = 连板首日前一天的收盘价
            prev_day_idx = first_zt_idx - 1
            base_price = klines[prev_day_idx]['close']

            # top = 连板最后一天收盘价
            last_zt_idx = kline_date_map.get(last_zt_date, -1)
            if last_zt_idx < 0:
                continue
            top_price = klines[last_zt_idx]['close']

            # top_high = 连板期间最高价
            chain_high = max(
                klines[kline_date_map[d]]['high']
                for d in lianban_chain if d in kline_date_map
            )

            # 最高涨停日最高价（单独保留）
            last_zt_high = klines[last_zt_idx]['high']

            # 检查炸板
            zb_count = zb_index.get(code, {}).get(last_zt_date, 0)
            has_zha_ban = zb_count > 0

            # 回调区间：连板最后一天之后的所有K线
            pullback_klines = klines[last_zt_idx + 1:]
            if not pullback_klines:
                continue

            # 回调区间最低价
            pullback_low = min(k['low'] for k in pullback_klines)

            # M = 最大回调百分比
            max_pullback_pct = round((top_price - pullback_low) / top_price * 100, 1)

            # N = 当前回调百分比
            current_close = pullback_klines[-1]['close']
            current_pullback_pct = round((top_price - current_close) / top_price * 100, 1)

            # 量缩比
            # 涨停期间（涨停日及前2天）平均成交量
            zt_vol_start = max(0, last_zt_idx - 2)
            zt_avg_vol = sum(
                k['volume'] for k in klines[zt_vol_start:last_zt_idx + 1]
            ) / max(last_zt_idx + 1 - zt_vol_start, 1)

            recent_avg_vol = sum(
                k['volume'] for k in pullback_klines[-3:]
            ) / max(len(pullback_klines[-3:]), 1)

            volume_ratio = round(
                recent_avg_vol / max(zt_avg_vol, 0.01), 2
            ) if zt_avg_vol > 0 else 1.0

            # === N+W 双底形态检测 ===
            is_nw_pattern = False
            nw_m2_price = 0
            nw_recovery_high = 0
            nw_recovery_pct = 0
            if len(pullback_klines) >= 5:
                # 定位M点（回调期最低价位置）
                m_idx = min(range(len(pullback_klines)), key=lambda i: pullback_klines[i]['low'])
                m_price = pullback_klines[m_idx]['low']
                # M点后至少有3根K线
                if m_idx + 3 < len(pullback_klines):
                    # 找M点后反弹高点
                    post_m = pullback_klines[m_idx + 1:]
                    recovery_high = max(k['high'] for k in post_m)
                    recovery_pct = (recovery_high - m_price) / m_price * 100
                    if recovery_pct >= 5:
                        # 反弹高点位置
                        rh_idx = m_idx + 1 + max(range(len(post_m)), key=lambda i: post_m[i]['high'])
                        # 反弹高点后查找M2
                        after_rh = pullback_klines[rh_idx + 1:] if rh_idx + 1 < len(pullback_klines) else []
                        if after_rh:
                            m2_price = min(k['low'] for k in after_rh)
                            m2_diff = abs(m2_price - m_price) / m_price * 100
                            if m2_diff <= 2:
                                is_nw_pattern = True
                                nw_m2_price = round(m2_price, 2)
                                nw_recovery_high = round(recovery_high, 2)
                                nw_recovery_pct = round(recovery_pct, 1)

            # 计算MA5/MA10
            if len(klines) >= 5:
                ma5 = round(sum(k['close'] for k in klines[-5:]) / 5, 2)
            else:
                ma5 = current_close

            if len(klines) >= 10:
                ma10 = round(sum(k['close'] for k in klines[-10:]) / 10, 2)
            else:
                ma10 = current_close

            is_oscillation = ma10 <= current_close <= ma5 * 1.02 or (
                current_close >= ma10 * 0.98 and current_close <= ma5 * 1.03
            )
            above_ma5 = current_close >= ma5
            above_ma10 = current_close >= ma10

            # 分类 (TLD优先)
            is_tld = False
            is_tld_shouban = False
            pullback_trading_days = len(pullback_klines)
            # TLD: 回调幅度按涨幅回撤比计算（60%+ = 回撤了涨幅的60%以上）
            rally_range = max(top_price - base_price, 0.01)
            pullback_retrace_max = (top_price - pullback_low) / rally_range * 100
            pullback_retrace_current = (top_price - current_close) / rally_range * 100
            if 2 <= pullback_trading_days <= 4 and (pullback_retrace_max >= 60 or pullback_retrace_current >= 60):
                is_tld = True
                # 首版检测：前20个交易日无涨停
                twenty_days_before = self._get_n_trade_days_before(last_zt_date, 20)
                has_prior_zt = any(d < last_zt_date and d >= twenty_days_before for d in zt_dates)
                if not has_prior_zt:
                    is_tld_shouban = True

            if is_tld:
                cat_key = 'tld'
            elif current_pullback_pct < 2:
                cat_key = '0-2'
            elif current_pullback_pct < 5:
                cat_key = '2-5'
            elif current_pullback_pct < 8:
                cat_key = '5-8'
            elif current_pullback_pct < 10:
                cat_key = '8-10'
            else:
                cat_key = '10+'

            # 特殊标记
            is_lianban2plus = lianban_count >= 2 and max_pullback_pct <= 50

            board = self._get_board(code)

            # 获取概念
            concepts = sorted(self.stock_concepts.get(code, set()))

            # 构建card数据
            card = {
                'code': code,
                'name': self.get_stock_name(code),
                'board': board,
                'concepts': concepts,
                'lianban_count': lianban_count,
                'is_lianban2plus': is_lianban2plus,
                'is_tld': is_tld,
                'is_tld_shouban': is_tld_shouban,
                'zt_dates': zt_dates,
                'last_zt_date': last_zt_date,
                'base_price': round(base_price, 2),
                'top_price': round(top_price, 2),
                'top_high': round(chain_high, 2),
                'max_pullback_pct': max_pullback_pct,
                'current_pullback_pct': current_pullback_pct,
                'current_close': round(current_close, 2),
                'volume_ratio': volume_ratio,
                'ma5': ma5,
                'ma10': ma10,
                'is_oscillation': is_oscillation,
                'above_ma5': above_ma5,
                'above_ma10': above_ma10,
                'has_zha_ban': has_zha_ban,
                'zb_count': zb_count,
                'is_nw_pattern': is_nw_pattern,
                'nw_m2_price': nw_m2_price,
                'nw_recovery_high': nw_recovery_high,
                'nw_recovery_pct': nw_recovery_pct,
                'pullback_low': round(pullback_low, 2),
                'klines': self._build_np_klines(klines, kline_date_map, zt_dates),
            }

            board_key = 'main_board' if board == 'main' else board
            categories[cat_key][board_key].append(card)

            # === 炸板异动检测 ===
            if has_zha_ban:
                # 炸板前15个交易日无涨停
                zt_set = set(zt_dates)
                has_recent_zt_before_zhqi = any(
                    d < last_zt_date and d >= self._get_n_trade_days_before(last_zt_date, 15)
                    for d in zt_set if d != last_zt_date
                )
                if not has_recent_zt_before_zhqi:
                    alerts_zhaban_list.append({
                        'code': code,
                        'name': self.get_stock_name(code),
                        'board': board,
                        'last_zt_date': last_zt_date,
                        'zb_count': zb_count,
                        'top_high': round(last_zt_high, 2),
                        'base_price': round(base_price, 2),
                        'concepts': concepts,
                        'current_pullback_pct': current_pullback_pct,
                        'klines': self._build_np_klines(klines, kline_date_map, zt_dates),
                    })

            # === 创业板/科创板异动检测 ===
            if board in ('gem', 'star'):
                # 近10日有一天涨幅>10%
                recent_klines = [k for k in klines if k['date'] >= self._get_n_trade_days_before(last_trade_date, 10)]
                has_big_rise = any(k['change_pct'] >= 10 for k in recent_klines)
                if has_big_rise and current_pullback_pct > 2:
                    alerts_gem_list.append({
                        'code': code,
                        'name': self.get_stock_name(code),
                        'board': board,
                        'last_zt_date': last_zt_date,
                        'current_pullback_pct': current_pullback_pct,
                        'concepts': concepts,
                        'lianban_count': lianban_count,
                        'klines': klines,
                    })

        # === N字战法新模式：阳线回调 + 三连阴回调 ===
        yang_pattern_stocks = []
        three_yin_pattern_stocks = []

        for code, zt_dates in candidate_stocks.items():
            if code not in kline_batch:
                continue
            klines = kline_batch[code]
            if len(klines) < 5:
                continue

            # 过滤近15个交易日内的涨停
            recent_start = self._get_n_trade_days_before(last_trade_date, 15)
            recent_zt = [d for d in zt_dates if d >= recent_start and d <= last_trade_date]
            if not recent_zt:
                continue

            last_zt = recent_zt[-1]

            # 在klines中找last_zt的位置
            kline_date_map = {k['date']: i for i, k in enumerate(klines)}
            idx = kline_date_map.get(last_zt)
            if idx is None:
                continue

            zt_close = klines[idx]['close']

            # 涨停前日收盘价（用于价格范围约束）
            if idx == 0:
                continue
            pre_zt_close = klines[idx - 1]['close']

            # 涨停日后K线
            after = klines[idx + 1:]
            if not after:
                continue  # 刚涨停，无回调

            # 价格范围约束
            after_high_max = max(k['high'] for k in after)
            after_low_min = min(k['low'] for k in after)

            if after_high_max > zt_close * 1.10:
                continue  # 涨停后冲太高
            if after_low_min < pre_zt_close:
                continue  # 跌破涨停前日收盘价（回补缺口）

            last = klines[-1]
            last_change_pct = last['change_pct']
            board = self._get_board(code)
            concepts = sorted(self.stock_concepts.get(code, set()))

            # 模式1: 阳线回调 - 涨停后阴线回调 + 最后一根阳线企稳
            if last['close'] > last['open'] and 0 < last_change_pct < 5:
                # 涨停日后到阳线之前至少有一根阴线（回调）
                middle_klines = after[:-1]  # 排除最后阳线本身
                if not middle_klines or not any(k['close'] < k['open'] for k in middle_klines):
                    continue  # 无阴线回调，跳过
                yang_pattern_stocks.append({
                    'code': code,
                    'name': self.get_stock_name(code),
                    'board': board,
                    'concepts': concepts,
                    'last_zt_date': last_zt,
                    'recent_zt_count': len(recent_zt),
                    'change_pct': round(last_change_pct, 2),
                    'close': round(last['close'], 2),
                    'open': round(last['open'], 2),
                    'klines': self._build_np_klines(klines, kline_date_map, zt_dates),
                })

            # 模式2: 三连阴回调 - 最后连续3根阴线
            if len(klines) >= 3:
                last_3 = klines[-3:]
                if all(k['close'] < k['open'] for k in last_3):
                    three_yin_pattern_stocks.append({
                        'code': code,
                        'name': self.get_stock_name(code),
                        'board': board,
                        'concepts': concepts,
                        'last_zt_date': last_zt,
                        'recent_zt_count': len(recent_zt),
                        'change_pct': round(last_change_pct, 2),
                        'close': round(last['close'], 2),
                        'open': round(last['open'], 2),
                        'klines': self._build_np_klines(klines, kline_date_map, zt_dates),
                    })

        # 按change_pct升序排列
        yang_pattern_stocks.sort(key=lambda x: x['change_pct'])
        three_yin_pattern_stocks.sort(key=lambda x: x['change_pct'])

        # 各类别内按连板数排序
        for ck in cat_keys:
            for bk in ['main_board', 'gem', 'star', 'bj']:
                categories[ck][bk].sort(key=lambda x: (-x['lianban_count'], x['current_pullback_pct']))

        # 炸板异动按回调深度排序
        alerts_zhaban_list.sort(key=lambda x: x['current_pullback_pct'])
        alerts_gem_list.sort(key=lambda x: x['current_pullback_pct'])

        update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        result = {
            'categories': categories,
            'alerts': {
                'zha_ban': alerts_zhaban_list,
                'gem_alert': alerts_gem_list,
            },
            'yang_pattern': yang_pattern_stocks,
            'three_yin_pattern': three_yin_pattern_stocks,
            'update_time': update_time,
            'summary': {
                'total_stocks': sum(
                    len(categories[ck][bk])
                    for ck in cat_keys
                    for bk in ['main_board', 'gem', 'star', 'bj']
                ),
                'candidate_count': len(candidate_stocks),
                'kline_count': len(kline_batch),
                'tld_count': len(categories['tld']['main_board']) + len(categories['tld']['gem']) + len(categories['tld']['star']) + len(categories['tld']['bj']),
                'tld_shouban_count': sum(
                    1 for bk in ['main_board', 'gem', 'star', 'bj']
                    for c in categories['tld'][bk] if c.get('is_tld_shouban')
                ),
                'nw_count': sum(
                    1 for ck in cat_keys for bk in ['main_board', 'gem', 'star', 'bj']
                    for c in categories[ck][bk] if c.get('is_nw_pattern')
                ),
                'yang_pattern_count': len(yang_pattern_stocks),
                'three_yin_pattern_count': len(three_yin_pattern_stocks),
            }
        }

        print(f"N字战法: 分析完成, 共{result['summary']['total_stocks']}只股票")
        return result

    def _get_category_name(self, key: str) -> str:
        """获取分类名称"""
        names = {
            'tld': '屠龙刀战法 (60%+深度回调)',
            '0-2': '涨停回调0~2% (浅调)',
            '2-5': '涨停回调2~5% (正常回调)',
            '5-8': '涨停回调5~8% (深度回调)',
            '8-10': '涨停回调8~10% (深调)',
            '10+': '涨停回调10%+ (超跌)',
        }
        return names.get(key, key)

    def _get_trade_day_index(self, date_str: str) -> Optional[int]:
        """O(1)获取交易日索引"""
        idx = self.trade_date_index.get(date_str)
        if idx is None:
            idx = self.trade_date_index.get(str(date_str))
        return idx

    def _get_n_trade_days_before(self, date_str: str, n: int) -> str:
        """获取指定交易日之前的第N个交易日"""
        idx = self._get_trade_day_index(date_str)
        if idx is not None:
            target = max(0, idx - n)
            return self.trade_dates[target]
        from datetime import datetime, timedelta
        dt = datetime.strptime(date_str, '%Y%m%d')
        return (dt - timedelta(days=n * 1.5)).strftime('%Y%m%d')

    def find_gem_arbitrage(self, stock_code: str, max_lag: int = 2) -> Dict:
        """
        创业板/科创板套利检测：主板涨停 → 同概念创业板/科创板涨幅>10%联动
        Args:
            stock_code: 主板股票代码
            max_lag: 最大滞后天数（T+0 ~ T+max_lag）
        Returns:
            {stock_code, stock_name, total_pairs, pairs: [{main_stock, main_name, gem_stock, gem_name,
             gem_board, zt_date, main_zt_date, lag, gain_pct, close_price, concept}, ...]}
        """
        stock_code = str(stock_code).zfill(6)
        board = self._get_board(stock_code)
        if board != 'main':
            return {'stock_code': stock_code, 'stock_name': self.get_stock_name(stock_code),
                    'total_pairs': 0, 'pairs': [], 'error': '非主板股票，不适用套利检测'}

        concepts = self.stock_concepts.get(stock_code, set())
        if not concepts:
            return {'stock_code': stock_code, 'stock_name': self.get_stock_name(stock_code),
                    'total_pairs': 0, 'pairs': [], 'error': '无概念数据'}

        main_zt_dates = sorted(self.all_zt_dates.get(stock_code, set()))
        if not main_zt_dates:
            return {'stock_code': stock_code, 'stock_name': self.get_stock_name(stock_code),
                    'total_pairs': 0, 'pairs': [], 'error': '近79日无涨停记录'}

        # 收集同概念下所有创业板/科创板股票
        gem_star_candidates = set()
        concept_map = {}  # {gem_stock: [shared_concepts]}
        for concept in concepts:
            c_stocks = self.concept_stocks.get(concept, set())
            for c in c_stocks:
                if self._get_board(c) in ('gem', 'star'):
                    gem_star_candidates.add(c)
                    if c not in concept_map:
                        concept_map[c] = []
                    concept_map[c].append(concept)

        if not gem_star_candidates:
            return {'stock_code': stock_code, 'stock_name': self.get_stock_name(stock_code),
                    'total_pairs': 0, 'pairs': [], 'error': '该概念下无创业板/科创板股票'}

        # 构建gem/star股票涨停日期索引（从已合并数据）
        for c in gem_star_candidates:
            _ = self.all_zt_dates.get(c, set())  # 确保已加载

        # 查询K线数据获取精确涨幅
        pairs = []
        seen_pairs = set()

        try:
            conn = self.db._get_connection()
            cursor = conn.cursor()

            for gem_code in gem_star_candidates:
                gem_board = self._get_board(gem_code)
                gem_name = self.get_stock_name(gem_code)
                shared_concepts = concept_map.get(gem_code, [])

                for zt_date in main_zt_dates:
                    # 检查T+0到T+max_lag
                    zt_idx = self._get_trade_day_index(zt_date)
                    if zt_idx is None:
                        continue

                    for lag in range(max_lag + 1):
                        check_idx = zt_idx + lag
                        if check_idx >= len(self.trade_dates):
                            break
                        check_date = self.trade_dates[check_idx]

                        # 去重：同一创业板股票在同一日期只保留一条记录
                        pair_key = (gem_code, check_date)
                        if pair_key in seen_pairs:
                            continue
                        seen_pairs.add(pair_key)

                        # 从DB查询该日涨幅（DB日期格式YYYY-MM-DD）
                        db_date = check_date[:4] + '-' + check_date[4:6] + '-' + check_date[6:]
                        cursor.execute(
                            "SELECT change_pct, close FROM kline_daily "
                            "WHERE stock_code = ? AND trade_date = ?",
                            (gem_code, db_date)
                        )
                        row = cursor.fetchone()
                        if not row:
                            continue

                        change_pct = float(row[0]) if row[0] else 0
                        close_price = float(row[1]) if row[1] else 0

                        # 创业板/科创板涨幅>10%视为有效联动
                        threshold = 10.0
                        if change_pct >= threshold:
                            pairs.append({
                                'main_stock': stock_code,
                                'main_name': self.get_stock_name(stock_code),
                                'gem_stock': gem_code,
                                'gem_name': gem_name,
                                'gem_board': gem_board,
                                'zt_date': check_date,
                                'main_zt_date': zt_date,
                                'lag': lag,
                                'gain_pct': round(change_pct, 2),
                                'close_price': round(close_price, 2),
                                'concept': shared_concepts[0] if shared_concepts else '',
                                'all_concepts': shared_concepts,
                            })

            conn.close()
        except Exception as e:
            print(f"创业板/科创板套利查询失败: {e}")

        # 按滞后天数排序，相同滞后按涨幅降序
        pairs.sort(key=lambda x: (x['lag'], -x['gain_pct']))

        return {
            'stock_code': stock_code,
            'stock_name': self.get_stock_name(stock_code),
            'total_pairs': len(pairs),
            'pairs': pairs,
        }

    # ========== 震荡企稳模式检测 ==========

    def analyze_oscillation_pattern(self, lookback_days: int = 20) -> Dict:
        """
        震荡企稳模式检测：连板后回调震荡起二波

        检测条件：
        1. 最近20个交易日内有连续2个及以上涨停
        2. 无A杀（回调最低价不低于第一个涨停板K线的中位价）
        3. 从回调低点至今至少有5个交易日的震荡期
        4. 震荡区间价差不超过15%，未跌破回调低点
        5. 成交量相对连板期明显萎缩（量缩比 < 0.8）

        Returns:
            {
                'stocks': [{code, name, concepts, lianban_count, lianban_dates,
                            last_zt_date, peak_price, pullback_low, max_pullback_pct,
                            osc_high, osc_low, osc_range_pct, osc_days,
                            volume_shrink_ratio, above_ma5, above_ma10,
                            stabilization_score, klines}, ...],
                'summary': {total: N, candidate_count: M},
                'update_time': 'YYYY-MM-DD HH:MM:SS'
            }
        """
        if len(self.trade_dates) < lookback_days + 5:
            lookback_days = max(len(self.trade_dates) - 5, 10)

        recent_trade_dates = self.trade_dates[-lookback_days:]
        lookback_start = recent_trade_dates[0]
        last_trade_date = recent_trade_dates[-1]

        # 1. 找到观察窗口内有涨停的股票
        candidate_stocks = {}
        for code, all_dates in self.all_zt_dates.items():
            zt_in_window = [d for d in all_dates if d >= lookback_start and d <= last_trade_date]
            if zt_in_window:
                candidate_stocks[code] = sorted(zt_in_window)

        print(f"震荡企稳: 近{lookback_days}天有涨停的候选股票: {len(candidate_stocks)}只")

        if not candidate_stocks:
            return {'stocks': [], 'summary': {'total': 0, 'candidate_count': 0},
                    'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

        # 2. 批量获取K线数据
        conn = None
        kline_batch = {}
        try:
            conn = self.db._get_connection()
            cursor = conn.cursor()

            kline_start_idx = max(0, self._get_trade_day_index(lookback_start) - 30)
            kline_start_date = self.trade_dates[kline_start_idx]
            start_date_str = f"{kline_start_date[:4]}-{kline_start_date[4:6]}-{kline_start_date[6:]}"

            codes = list(candidate_stocks.keys())
            batch_size = 500
            for batch_start in range(0, len(codes), batch_size):
                batch_codes = codes[batch_start:batch_start + batch_size]
                placeholders = ','.join(['?'] * len(batch_codes))
                cursor.execute(f"""
                    SELECT stock_code, trade_date, open, high, low, close, volume, change_pct
                    FROM kline_daily
                    WHERE stock_code IN ({placeholders}) AND trade_date >= ?
                    ORDER BY stock_code, trade_date
                """, batch_codes + [start_date_str])
                for row in cursor.fetchall():
                    code = row[0]
                    d = row[1].replace('-', '') if row[1] else ''
                    kline = {
                        'date': d,
                        'open': float(row[2]),
                        'high': float(row[3]),
                        'low': float(row[4]),
                        'close': float(row[5]),
                        'volume': float(row[6]),
                        'change_pct': float(row[7]) if row[7] else 0
                    }
                    if code not in kline_batch:
                        kline_batch[code] = []
                    kline_batch[code].append(kline)
        except Exception as e:
            print(f"震荡企稳: 批量查询K线失败: {e}")
        finally:
            if conn:
                conn.close()

        print(f"震荡企稳: 有K线数据的候选股票: {len(kline_batch)}只")

        # 3. 分析每只股票
        results = []

        for code, zt_dates in candidate_stocks.items():
            if code not in kline_batch:
                continue

            klines = kline_batch[code]
            if len(klines) < 10:
                continue

            # 构建日期→索引映射
            kline_date_map = {k['date']: i for i, k in enumerate(klines)}

            # 检测连板链（从最后一个涨停往前）
            last_zt_date = zt_dates[-1]
            if last_zt_date not in kline_date_map:
                continue

            lianban_chain = [last_zt_date]
            for i in range(len(zt_dates) - 2, -1, -1):
                d1 = zt_dates[i]
                d2 = zt_dates[i + 1]
                idx1 = self._get_trade_day_index(d1)
                idx2 = self._get_trade_day_index(d2)
                if idx1 is not None and idx2 is not None and idx2 - idx1 == 1:
                    lianban_chain.insert(0, d1)
                else:
                    break

            first_zt_date = lianban_chain[0]
            lianban_count = len(lianban_chain)

            # 条件1: 连续2个及以上涨停
            if lianban_count < 2:
                continue

            # 连板期间最高价
            first_zt_idx = kline_date_map.get(first_zt_date, -1)
            last_zt_idx = kline_date_map.get(last_zt_date, -1)
            if last_zt_idx < 0 or first_zt_idx < 0:
                continue

            chain_high = max(
                klines[kline_date_map[d]]['high']
                for d in lianban_chain if d in kline_date_map
            )

            # 连板最后一天收盘价（视为阶段性顶价）
            top_price = klines[last_zt_idx]['close']

            # 回调区间：连板最后一天之后的所有K线
            pullback_klines = klines[last_zt_idx + 1:]
            if not pullback_klines:
                continue

            # 回调最低价
            pullback_low = min(k['low'] for k in pullback_klines)

            # 最大回调幅度（从顶到低）
            max_pullback_pct = round((top_price - pullback_low) / top_price * 100, 1)

            # 第一个涨停板的K线中位价 = (high + low) / 2
            first_zt_kline = klines[first_zt_idx]
            first_zt_midpoint = (first_zt_kline['high'] + first_zt_kline['low']) / 2

            # 条件2: 无A杀 —— 回调最低价不低于第一个涨停板K线的中位价
            # 如果跌回到起涨点附近，说明资金已放弃，不算企稳形态
            if pullback_low < first_zt_midpoint * 0.98:
                continue

            # 找到回调低点对应的K线索引（在pullback_klines中）
            low_idx_in_pullback = -1
            for i, k in enumerate(pullback_klines):
                if k['low'] == pullback_low:
                    low_idx_in_pullback = i
                    break
            if low_idx_in_pullback < 0:
                continue

            # 震荡期：回调低点之后的所有K线
            oscillation_klines = pullback_klines[low_idx_in_pullback + 1:]

            # 条件3: 震荡期至少5根K线
            if len(oscillation_klines) < 5:
                continue

            # 震荡区间最高/最低
            osc_high = max(k['high'] for k in oscillation_klines)
            osc_low = min(k['low'] for k in oscillation_klines)

            # 震荡区间范围（%）
            osc_low_price = pullback_low  # 震荡区间下限=回调低点
            osc_range_pct = round((osc_high - osc_low_price) / osc_low_price * 100, 1)

            # 条件4: 震荡区间不超过15%，且未跌破回调低点
            if osc_range_pct > 15:
                continue
            if osc_low < pullback_low * 0.995:
                continue

            # 量缩比计算
            zt_vol_start = max(0, last_zt_idx - 2)
            zt_avg_vol = sum(
                k['volume'] for k in klines[zt_vol_start:last_zt_idx + 1]
            ) / max(last_zt_idx + 1 - zt_vol_start, 1)

            # 震荡期平均成交量
            osc_avg_vol = sum(
                k['volume'] for k in oscillation_klines
            ) / max(len(oscillation_klines), 1)

            volume_shrink_ratio = round(
                osc_avg_vol / max(zt_avg_vol, 0.01), 2
            ) if zt_avg_vol > 0 else 1.0

            # 条件5: 量缩比 < 0.8
            if volume_shrink_ratio >= 0.8:
                continue

            # 均线位置
            current_close = oscillation_klines[-1]['close']
            n_klines = len(klines)
            last_idx = n_klines - 1

            # 计算MA5/MA10
            ma5 = sum(klines[j]['close'] for j in range(max(0, last_idx - 4), last_idx + 1)) / min(5, last_idx + 1)
            ma10 = sum(klines[j]['close'] for j in range(max(0, last_idx - 9), last_idx + 1)) / min(10, last_idx + 1)

            above_ma5 = current_close >= ma5 * 0.97  # 在MA5附近
            above_ma10 = current_close >= ma10 * 0.97

            # 综合评分
            # a) 震荡质量 (35分)
            osc_quality_score = 0
            # 震荡区间越小分越高
            range_factor = max(0, 1 - osc_range_pct / 15)  # 0~1
            osc_quality_score += range_factor * 15
            # 震荡天数越长越好
            days_factor = min(1, len(oscillation_klines) / 15)  # 0~1
            osc_quality_score += days_factor * 20

            # b) 量缩程度 (25分)
            shrink_factor = max(0, 1 - volume_shrink_ratio / 0.8)  # 0~1
            vol_score = shrink_factor * 25

            # c) 均线支撑 (20分)
            ma_score = 0
            if above_ma5:
                ma_score += 12
            if above_ma10:
                ma_score += 8

            # d) 连板高度 (20分)
            lianban_score = min(lianban_count / 5, 1) * 20  # 5连板满分

            stabilization_score = round(osc_quality_score + vol_score + ma_score + lianban_score, 1)

            # 构建K线数据（含均线、涨停标记）
            zt_set = set(zt_dates)
            np_klines = self._build_np_klines(klines, kline_date_map, zt_dates)

            # 震荡天数（交易日数）
            osc_days = len(oscillation_klines)

            # 距离上次涨停的天数
            days_since_last_zt = self._get_trade_day_diff(last_zt_date, last_trade_date)

            results.append({
                'code': code,
                'name': self.stock_name_map.get(code, ''),
                'concepts': list(self.stock_concepts.get(code, []))[:8],
                'lianban_count': lianban_count,
                'lianban_dates': lianban_chain,
                'last_zt_date': last_zt_date,
                'days_since_last_zt': days_since_last_zt,
                'peak_price': round(chain_high, 2),
                'first_zt_midpoint': round(first_zt_midpoint, 2),
                'pullback_low': round(pullback_low, 2),
                'max_pullback_pct': max_pullback_pct,
                'current_close': round(current_close, 2),
                'osc_high': round(osc_high, 2),
                'osc_low': round(osc_low, 2),
                'osc_range_pct': osc_range_pct,
                'osc_days': osc_days,
                'volume_shrink_ratio': volume_shrink_ratio,
                'above_ma5': above_ma5,
                'above_ma10': above_ma10,
                'ma5': round(ma5, 2),
                'ma10': round(ma10, 2),
                'stabilization_score': stabilization_score,
                'klines': np_klines,
            })

        # 按评分降序排列
        results.sort(key=lambda x: -x['stabilization_score'])

        print(f"震荡企稳: 符合条件的股票: {len(results)}只")

        return {
            'stocks': results,
            'summary': {
                'total': len(candidate_stocks),
                'candidate_count': len(results),
            },
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    def _build_np_klines(self, klines: List[Dict],
                          kline_date_map: Dict[str, int],
                          zt_dates: List[str]) -> List[Dict]:
        """构建N字战法卡片用的K线数据（含均线、涨停标记）"""
        zt_set = set(zt_dates)
        result = []
        n = len(klines)
        for i, k in enumerate(klines):
            # 计算滚动MA5/MA10/volMA5
            ma5 = round(sum(klines[j]['close'] for j in range(max(0, i - 4), i + 1)) / min(5, i + 1), 2) if i >= 0 else k['close']
            ma10 = round(sum(klines[j]['close'] for j in range(max(0, i - 9), i + 1)) / min(10, i + 1), 2) if i >= 0 else k['close']
            vol_ma5 = round(sum(klines[j]['volume'] for j in range(max(0, i - 4), i + 1)) / min(5, i + 1), 2) if i >= 0 else k['volume']

            result.append({
                'date': k['date'],
                'open': round(k['open'], 2),
                'high': round(k['high'], 2),
                'low': round(k['low'], 2),
                'close': round(k['close'], 2),
                'volume': round(k['volume'], 2),
                'change_pct': round(k['change_pct'], 2),
                'is_zt': k['date'] in zt_set,
                'ma5': ma5,
                'ma10': ma10,
                'volume_ma5': vol_ma5,
            })
        return result

    def _empty_n_pattern_result(self) -> Dict:
        """返回空的N字战法结果"""
        cat_keys = ['0-2', '2-5', '5-8', '8-10', '10+']
        categories = {}
        for ck in cat_keys:
            categories[ck] = {
                'name': self._get_category_name(ck),
                'main_board': [], 'gem': [], 'star': [], 'bj': []
            }
        return {
            'categories': categories,
            'alerts': {'zha_ban': [], 'gem_alert': []},
            'yang_pattern': [],
            'three_yin_pattern': [],
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'summary': {'total_stocks': 0, 'candidate_count': 0, 'kline_count': 0, 'yang_pattern_count': 0, 'three_yin_pattern_count': 0}
        }

    # ========== 15日涨停板窗口查询 ==========

    def get_zt_window_stocks(self, lookback_days: int = 15, top_per_window: int = 9999) -> Dict:
        """获取最近N个交易日内有涨停的股票，按涨停日期远近分组，含K线数据

        Returns:
            windows: {
                'hot': [{code, name, zt_count, zt_dates, last_zt_date, days_ago, concepts, klines}, ...],
                'warm': [...],
                'cool': [...],
                'cold': [...],
            }
        """
        if not self.trade_dates or len(self.trade_dates) < lookback_days:
            return {'hot': [], 'warm': [], 'cool': [], 'cold': []}

        last_date = self.trade_dates[-1]
        lookback_start = self.trade_dates[-lookback_days]

        # 收集窗口内的候选股票
        candidates = {}
        for code, all_dates in self.all_zt_dates.items():
            zt_in_window = [d for d in all_dates if d >= lookback_start and d <= last_date]
            if not zt_in_window:
                continue
            sorted_dates = sorted(zt_in_window)
            last_zt = sorted_dates[-1]
            days_ago = self._get_trade_day_diff(last_zt, last_date)
            candidates[code] = {
                'code': code,
                'name': self.stock_name_map.get(code, ''),
                'zt_count': len(sorted_dates),
                'zt_dates': sorted_dates,
                'last_zt_date': last_zt,
                'days_ago': days_ago,
                'concepts': list(self.stock_concepts.get(code, []))[:8],  # 最多8个概念
                'board': self._get_board(code),
            }

        # 按天数分窗
        windows = {
            'hot': [],   # 1-3日
            'warm': [],  # 4-5日
            'cool': [],  # 6-10日
            'cold': [],  # 11-15日
        }

        for code, info in candidates.items():
            days = info['days_ago']
            if days <= 3:
                windows['hot'].append(info)
            elif days <= 5:
                windows['warm'].append(info)
            elif days <= 10:
                windows['cool'].append(info)
            else:
                windows['cold'].append(info)

        # 每组按涨停次数降序
        for key in windows:
            windows[key].sort(key=lambda x: -x['zt_count'])

        # 截取上限
        for key in windows:
            windows[key] = windows[key][:top_per_window]

        # ====== 批量获取K线数据（30个交易日） ======
        all_codes = []
        for key in windows:
            for s in windows[key]:
                all_codes.append(s['code'])

        if all_codes and hasattr(self, 'db') and hasattr(self.db, 'db_path'):
            try:
                import sqlite3
                conn = sqlite3.connect(self.db.db_path)
                cursor = conn.cursor()
                # 取最近35个交易日的起始日期
                kline_start_raw = self.trade_dates[-min(35, len(self.trade_dates))]
                kline_start = f"{kline_start_raw[:4]}-{kline_start_raw[4:6]}-{kline_start_raw[6:8]}"
                placeholders = ','.join(['?'] * len(all_codes))
                cursor.execute(
                    f"SELECT stock_code, trade_date, open, high, low, close, volume, change_pct "
                    f"FROM kline_daily WHERE stock_code IN ({placeholders}) AND trade_date >= ? "
                    f"ORDER BY stock_code, trade_date",
                    all_codes + [kline_start]
                )
                rows = cursor.fetchall()
                conn.close()
                # 按股票分组
                raw_by_code = {}
                for row in rows:
                    code = row[0]
                    if code not in raw_by_code:
                        raw_by_code[code] = []
                    raw_by_code[code].append({
                        'date': row[1].replace('-', ''),
                        'open': float(row[2]), 'high': float(row[3]),
                        'low': float(row[4]), 'close': float(row[5]),
                        'volume': float(row[6]), 'change_pct': float(row[7]) if row[7] else 0,
                    })
                # 计算均线和涨停标记并格式化
                klines_by_code = {}
                for code, klines_raw in raw_by_code.items():
                    zt_set = set(candidates[code]['zt_dates'])
                    computed = []
                    n = len(klines_raw)
                    for i, k in enumerate(klines_raw):
                        ma5 = round(sum(klines_raw[j]['close'] for j in range(max(0, i - 4), i + 1)) / min(5, i + 1), 2)
                        ma10 = round(sum(klines_raw[j]['close'] for j in range(max(0, i - 9), i + 1)) / min(10, i + 1), 2)
                        computed.append({
                            'date': k['date'], 'open': round(k['open'], 2),
                            'high': round(k['high'], 2), 'low': round(k['low'], 2),
                            'close': round(k['close'], 2), 'volume': round(k['volume'], 2),
                            'change_pct': round(k['change_pct'], 2),
                            'is_zt': k['date'] in zt_set,
                            'ma5': ma5, 'ma10': ma10,
                        })
                    klines_by_code[code] = computed
                # 附加到各股票
                for key in windows:
                    for s in windows[key]:
                        s['klines'] = klines_by_code.get(s['code'], [])
            except Exception:
                # K线数据可选，获取失败不影响主体数据
                pass

        return windows

    # ========== K线数据查询 ==========

    def get_stock_kline_summary(self, stock_code: str, days: int = 60) -> Dict:
        """获取股票K线摘要（用于图表展示）"""
        stock_code = str(stock_code).zfill(6)
        today_str = datetime.now().strftime('%Y%m%d')

        df = self.db.get_kline_data(stock_code, start_date=None, end_date=today_str)
        if df is None or df.empty:
            return {'stock_code': stock_code, 'klines': [], 'zt_dates': []}

        zt_dates = set(self.get_stock_zt_dates(stock_code))

        klines = []
        for _, row in df.iterrows():
            date_str = str(row.get('trade_date', ''))[:10].replace('-', '')
            klines.append({
                'date': date_str,
                'open': float(row.get('open', 0)),
                'high': float(row.get('high', 0)),
                'low': float(row.get('low', 0)),
                'close': float(row.get('close', 0)),
                'volume': float(row.get('volume', 0)),
                'change_pct': float(row.get('change_pct', 0)),
                'is_zt': date_str in zt_dates
            })

        klines.sort(key=lambda x: x['date'])

        return {
            'stock_code': stock_code,
            'stock_name': self.get_stock_name(stock_code),
            'klines': klines[-days:],
            'zt_dates': sorted(zt_dates)[-days:]
        }

    # ========== K线数据自动补全 ==========

    def _check_and_auto_update(self):
        """检测K线数据是否缺失，后台按天批量自动补全（快）"""
        if not getattr(self.db, 'pro', None):
            return  # tushare未初始化，跳过

        thread = threading.Thread(target=self._auto_update_kline_batch, daemon=True)
        thread.start()

    def _auto_update_kline_batch(self):
        """后台：扩展日历→检查缺失→按天批量拉取（一次API获取全市场5000+只）"""
        try:
            # 动态导入避免循环依赖
            from importlib import import_module
            script_dir = os.path.dirname(os.path.abspath(__file__))
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)
            import update_data_fast

            # Step 1: 扩展交易日历
            added = update_data_fast.extend_trade_calendar()
            if added > 0:
                print(f"K线自动补全: 交易日历新增 {added} 天")

            # Step 2: 检查缺失
            missing = update_data_fast.get_db_missing_dates()
            if not missing:
                return  # 已是最新

            print(f"K线自动补全: 缺失 {len(missing)} 个交易日, 按天批量拉取中...")

            # Step 3: 按天批量拉取（0.6秒/天，远快于逐只股票）
            result = update_data_fast.fetch_and_save_missing_dates(missing, delay=0.6)

            # Step 4: 重载内存数据
            self._load_trade_calendar()
            self._load_zt_from_db()
            self._merge_zt_data()

            print(f"K线自动补全完成: 拉取 {result.get('success', 0)}/{len(missing)} 天,"
                  f" 新增 {result.get('records', 0)} 条记录")
        except Exception as e:
            print(f"K线自动补全出错: {e}")


def main():
    """主入口"""
    import sys

    finder = StockLinkageFinder()

    if len(sys.argv) > 1:
        query = sys.argv[1]

        if query.isdigit() or (len(query) == 6 and query.isdigit()):
            stock_code = query.zfill(6)
        else:
            results = finder.search_stock(query)
            if results:
                print(f"\n搜索 '{query}' 结果:")
                for r in results:
                    print(f"  {r['code']} {r['name']} 涨停{r['zt_count']}次 概念{r['concept_count']}个")
                    print(f"    概念: {', '.join(r['concepts'][:5])}")
                    if r['zt_dates']:
                        print(f"    最近涨停: {', '.join(r['zt_dates'])}")
                if len(results) == 1:
                    stock_code = results[0]['code']
                else:
                    print(f"\n找到 {len(results)} 个匹配，请使用代码查询")
                    return
            else:
                print(f"未找到与 '{query}' 匹配的股票")
                return

        concept_name = sys.argv[2] if len(sys.argv) > 2 else None

        print(f"\n查找股票 {stock_code} 的联动股票...")
        if concept_name:
            print(f"限定概念: {concept_name}")

        result = finder.find_stock_linkages(stock_code, concept_name, min_prob=0.15)
        finder.print_linkage_report(result)

        # 保存结果
        output_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'data', 'analysis_output'
        )
        os.makedirs(output_dir, exist_ok=True)

        output_file = os.path.join(output_dir, f'linkage_{stock_code}_{datetime.now().strftime("%Y%m%d")}.json')
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {output_file}")

    else:
        # 示例演示
        print("\n" + "=" * 80)
        print("股票联动查找器 V5 - 示例演示")
        print("=" * 80)

        test_cases = [
            ('603045', '芯片概念'),
            ('600396', '绿色电力'),
            ('300843', 'PCB概念'),
        ]

        for stock_code, concept in test_cases:
            zt_dates = finder.get_stock_zt_dates(stock_code)
            if len(zt_dates) < 2:
                print(f"\n{stock_code} 涨停次数不足，跳过...")
                continue

            print(f"\n\n{'#'*80}")
            name = finder.get_stock_name(stock_code)
            print(f"示例：{stock_code} {name}（{concept}）")
            zt_detail = finder.get_stock_zt_dates_detail(stock_code)
            print(f"  历史涨停日期: {zt_dates}")
            print(f"  涨停池源: {zt_detail['pool_count']}次, 数据库源: {zt_detail['db_count']}次")
            print('#'*80)

            result = finder.find_stock_linkages(stock_code, concept, min_prob=0.15)
            finder.print_linkage_report(result)


if __name__ == "__main__":
    main()
