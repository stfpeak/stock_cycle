"""
题材数据获取模块
================
功能：
    1. 获取同花顺top20热门题材
    2. 获取概念成分股
    3. 获取近365天日K数据
    4. 涨停标记（主板10%/创业板科创20%）
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kline_database import KlineDB


class ConceptDataFetcher:
    """题材数据获取器"""

    ZT_THRESHOLD_MAIN = 9.8
    ZT_THRESHOLD_GEM = 19.5
    GEM_CODES = {'300', '301', '688'}

    def __init__(self, db_path: str = None):
        self.db = KlineDB(db_path)
        self._load_ths_concepts()

    def _load_ths_concepts(self):
        """加载同花顺概念数据"""
        concept_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'data', 'concept_stock', 'ths_concept_stock.json'
        )

        if os.path.exists(concept_file):
            with open(concept_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.ths_concepts = data.get('forward', {})
        else:
            self.ths_concepts = {}

        print(f"加载了 {len(self.ths_concepts)} 个同花顺概念")

    def _normalize_stock_code(self, code: str) -> str:
        """标准化股票代码为6位数字格式"""
        code = code.lower()
        if code.startswith('sh') or code.startswith('sz'):
            code = code[2:]
        code = code.zfill(6)
        return code

    def get_ths_top20_concepts(self) -> List[Dict]:
        """获取同花顺top20热门题材"""
        try:
            import adata
            df = adata.sentiment.hot.hot_concept_20_ths()

            if df is not None and not df.empty:
                concepts = []
                for _, row in df.iterrows():
                    # 正确获取 concept_name 字段
                    concept_name = row.get('concept_name', row.get('concept', ''))
                    stock_count = len(self.get_concept_stocks(concept_name))
                    concepts.append({
                        'name': concept_name,
                        'stock_count': stock_count
                    })
                return concepts[:20]

        except Exception as e:
            print(f"获取同花顺top20失败: {e}")

        return self._get_local_top20_concepts()

    def _get_local_top20_concepts(self) -> List[Dict]:
        """从本地数据获取前20个概念（按股票数量排序）"""
        concepts = []
        for name, stocks in self.ths_concepts.items():
            concepts.append({
                'name': name,
                'stock_count': len(stocks)
            })
        concepts.sort(key=lambda x: x['stock_count'], reverse=True)
        return concepts[:20]

    def get_concept_stocks(self, concept_name: str) -> List[str]:
        """获取概念成分股"""
        stocks = self.ths_concepts.get(concept_name, [])

        codes = []
        for stock in stocks:
            code = stock.get('code', '')
            normalized = self._normalize_stock_code(code)
            codes.append(normalized)

        return codes

    def get_all_concept_names(self) -> List[str]:
        """获取所有概念名称"""
        return list(self.ths_concepts.keys())

    def _is_gem_stock(self, stock_code: str) -> bool:
        """判断是否为创业板/科创版股票"""
        code_str = str(stock_code)
        return code_str.startswith('300') or code_str.startswith('301') or code_str.startswith('688')

    def fetch_kline_from_db(self, stock_code: str, start_date: str = None, end_date: str = None) -> List[Dict]:
        """从数据库获取K线数据"""
        df = self.db.get_kline_data(stock_code, start_date, end_date)

        if df is None or df.empty:
            return []

        klines = []
        for _, row in df.iterrows():
            klines.append({
                'date': row.get('trade_date', ''),
                'open': row.get('open', 0),
                'high': row.get('high', 0),
                'low': row.get('low', 0),
                'close': row.get('close', 0),
                'volume': row.get('volume', 0),
                'prev_close': row.get('prev_close', 0),
                'change_pct': row.get('change_pct', 0)
            })
        return klines

    def fetch_kline_from_api(self, stock_code: str, days: int = 365) -> List[Dict]:
        """从API获取K线数据（使用 tushare）"""
        try:
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')

            df = self.db.fetch_by_tushare(stock_code, start_date, end_date)

            if df is None or df.empty:
                return []

            klines = []
            for _, row in df.iterrows():
                trade_date = str(row.get('trade_date', ''))[:10]
                prev_close = row.get('pre_close', 0)
                close = row.get('close', 0)
                change_pct = 0
                if prev_close and prev_close > 0:
                    change_pct = (close - prev_close) / prev_close * 100

                klines.append({
                    'date': trade_date.replace('-', ''),
                    'open': row.get('open', 0),
                    'high': row.get('high', 0),
                    'low': row.get('low', 0),
                    'close': close,
                    'volume': row.get('volume', 0),
                    'prev_close': prev_close,
                    'change_pct': change_pct
                })
            return klines

        except Exception as e:
            print(f"获取 {stock_code} K线数据失败: {e}")
            return []

    def mark_zt_stocks(self, klines: List[Dict]) -> List[Dict]:
        """涨停标记"""
        marked = []
        for kline in klines:
            date = kline.get('date', '')
            high = kline.get('high', 0)
            close = kline.get('close', 0)
            prev_close = kline.get('prev_close', 0)

            max_rise_pct = 0
            if prev_close and prev_close > 0:
                max_rise_pct = (high - prev_close) / prev_close * 100

            rise_pct = 0
            if prev_close and prev_close > 0:
                rise_pct = (close - prev_close) / prev_close * 100

            is_zt = False
            zt_type = ''

            if prev_close > 0 and close >= prev_close * 1.098:
                is_zt = True
                zt_type = 'zt'
            elif prev_close > 0 and close >= prev_close * 1.195:
                is_zt = True
                zt_type = 'zt_gem'

            is_zaban = False
            if max_rise_pct >= 9.5 and rise_pct < max_rise_pct - 3:
                is_zaban = True
                if is_zt:
                    zt_type = 'zaban'
                else:
                    zt_type = 'zaban_only'

            kline['is_zt'] = is_zt
            kline['zt_type'] = zt_type
            kline['max_rise_pct'] = round(max_rise_pct, 2)
            kline['rise_pct'] = round(rise_pct, 2)
            marked.append(kline)

        return marked

    def get_zt_records(self, stock_code: str, days: int = 365) -> List[Dict]:
        """获取股票的涨停记录"""
        klines = self.fetch_kline_from_db(stock_code)
        if not klines:
            klines = self.fetch_kline_from_api(stock_code, days)

        marked = self.mark_zt_stocks(klines)
        zt_records = [k for k in marked if k['is_zt']]

        return zt_records

    def batch_get_zt_records(self, stock_codes: List[str], days: int = 365) -> Dict[str, List[Dict]]:
        """批量获取股票涨停记录"""
        results = {}

        def fetch_one(code):
            return code, self.get_zt_records(code, days)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_one, code): code for code in stock_codes}
            for future in as_completed(futures):
                code, records = future.result()
                results[code] = records

        return results

    def get_concept_zt_records(self, concept_name: str, days: int = 365) -> List[Dict]:
        """获取概念所有股票的涨停记录"""
        stock_codes = self.get_concept_stocks(concept_name)

        if not stock_codes:
            return []

        all_records = []
        for code in stock_codes:
            records = self.get_zt_records(code, days)
            for rec in records:
                rec['stock_code'] = code
                all_records.append(rec)

        all_records.sort(key=lambda x: x['date'])
        return all_records

    def get_concept_summary(self, concept_name: str) -> Dict:
        """获取概念摘要信息"""
        stock_codes = self.get_concept_stocks(concept_name)
        zt_records = self.get_concept_zt_records(concept_name)

        if not zt_records:
            return {
                "name": concept_name,
                "stock_count": len(stock_codes),
                "zt_count": 0,
                "zt_stock_count": 0,
                "first_zt_date": None,
                "latest_zt_date": None
            }

        zt_stocks = set(r['stock_code'] for r in zt_records)

        return {
            "name": concept_name,
            "stock_count": len(stock_codes),
            "zt_count": len(zt_records),
            "zt_stock_count": len(zt_stocks),
            "first_zt_date": zt_records[0]['date'] if zt_records else None,
            "latest_zt_date": zt_records[-1]['date'] if zt_records else None
        }


if __name__ == "__main__":
    print("=" * 60)
    print("题材数据获取测试")
    print("=" * 60)

    fetcher = ConceptDataFetcher()

    print("\n1. 获取同花顺top20题材:")
    top20 = fetcher.get_ths_top20_concepts()
    for i, c in enumerate(top20[:10], 1):
        print(f"  {i}. {c['name']} ({c['stock_count']}只股票)")

    if top20:
        concept_name = top20[0]['name']
        print(f"\n2. 获取'{concept_name}'成分股:")
        stocks = fetcher.get_concept_stocks(concept_name)
        print(f"  共 {len(stocks)} 只股票")
        print(f"  前5只: {stocks[:5]}")

        print(f"\n3. 获取涨停记录:")
        records = fetcher.get_concept_zt_records(concept_name, days=365)
        print(f"  涨停记录数: {len(records)}")

    print("\n测试完成!")
