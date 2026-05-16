"""
题材联动量化分析模块
====================
功能：
    1. 计算个股涨停后1-3日的滞后联动概率
    2. 构建联动矩阵
    3. 识别强关联题材

使用示例：
    from concept_linkage_analyzer import LinkageAnalyzer

    analyzer = LinkageAnalyzer()
    prob = analyzer.calc_lag_probability(stock_a, stock_b, lag=1, zt_records=records)
    matrix = analyzer.build_linkage_matrix(zt_records)
"""

from typing import List, Dict, Set
from datetime import datetime, timedelta
from collections import defaultdict


class LinkageAnalyzer:
    """联动分析器"""

    def __init__(self):
        self.trade_calendar = self._load_trade_calendar()

    def _load_trade_calendar(self) -> List[str]:
        """加载交易日历"""
        import os, json
        cal_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'data', 'trade_calendar_2026.json'
        )
        if os.path.exists(cal_file):
            with open(cal_file, 'r') as f:
                dates = json.load(f)
                return [d.replace('-', '') for d in dates]
        return []

    def _get_nth_trading_day_after(self, base_date: str, n: int) -> str:
        """获取基准日期后第N个交易日"""
        if not self.trade_calendar:
            # 简单向后推算
            try:
                d = datetime.strptime(str(base_date), '%Y%m%d')
                return (d + timedelta(days=n)).strftime('%Y%m%d')
            except:
                return None

        try:
            idx = self.trade_calendar.index(str(base_date))
            target_idx = idx + n
            if target_idx < len(self.trade_calendar):
                return self.trade_calendar[target_idx]
        except ValueError:
            pass

        return None

    def calc_lag_probability(self, base_stock: str, compare_stock: str,
                             lag: int, zt_records: List[Dict]) -> float:
        """
        计算滞后联动概率

        Args:
            base_stock: 基准股票代码
            compare_stock: 比较股票代码
            lag: 滞后期数 (1, 2, 3)
            zt_records: 涨停记录

        Returns:
            滞后联动概率 0.0 ~ 1.0
        """
        # 获取基准股票的涨停日期
        base_dates = sorted([
            r.get('date', '') for r in zt_records
            if r.get('stock_code') == base_stock
        ])

        if not base_dates or len(base_dates) <= lag:
            return 0.0

        # 获取比较股票的涨停日期集合
        compare_dates = set([
            r.get('date', '') for r in zt_records
            if r.get('stock_code') == compare_stock
        ])

        # 计算滞后联动次数
        linkage_count = 0
        for base_date in base_dates[:-lag]:  # 排除最后N天
            lagged_date = self._get_nth_trading_day_after(base_date, lag)
            if lagged_date and lagged_date in compare_dates:
                linkage_count += 1

        return linkage_count / (len(base_dates) - lag)

    def calc_stock_lag_probs(self, stock_code: str, other_stocks: List[str],
                             lag: int, zt_records: List[Dict]) -> Dict[str, float]:
        """
        计算某股票对其他股票的滞后联动概率

        Returns:
            {stock_code: probability}
        """
        probs = {}
        for other in other_stocks:
            if other != stock_code:
                probs[other] = self.calc_lag_probability(
                    stock_code, other, lag, zt_records
                )
        return probs

    def build_linkage_matrix(self, stock_codes: List[str], zt_records: List[Dict],
                             lag_days: List[int] = None) -> List[Dict]:
        """
        构建联动矩阵

        Args:
            stock_codes: 股票代码列表
            zt_records: 涨停记录
            lag_days: 滞后期列表，默认 [1, 2, 3]

        Returns:
            联动矩阵列表
        """
        if lag_days is None:
            lag_days = [1, 2, 3]

        matrix = []

        # 构建股票两两之间的联动概率
        for i, stock_a in enumerate(stock_codes):
            for stock_b in stock_codes[i+1:]:
                lag_probs = {}
                for lag in lag_days:
                    prob = self.calc_lag_probability(stock_a, stock_b, lag, zt_records)
                    lag_probs[f'lag{lag}_prob'] = prob

                # 计算综合强度
                strength = sum(lag_probs.values()) / len(lag_probs)

                if strength > 0:
                    matrix.append({
                        'stock_a': stock_a,
                        'stock_b': stock_b,
                        'lag1_prob': lag_probs.get('lag1_prob', 0),
                        'lag2_prob': lag_probs.get('lag2_prob', 0),
                        'lag3_prob': lag_probs.get('lag3_prob', 0),
                        'strength': round(strength, 3)
                    })

        # 按强度排序
        matrix.sort(key=lambda x: x['strength'], reverse=True)

        return matrix

    def find_strong_linkages(self, matrix: List[Dict], threshold: float = 0.5) -> List[Dict]:
        """
        找出强关联配对

        Args:
            matrix: 联动矩阵
            threshold: 强度阈值

        Returns:
            强关联配对列表
        """
        return [m for m in matrix if m['strength'] >= threshold]

    def calc_concept_linkage(self, concept_stocks: List[str], zt_records: List[Dict],
                             lag: int = 1) -> Dict:
        """
        计算概念内部股票联动性

        Returns:
            {
                "avg_prob": 0.65,
                "max_prob": 0.9,
                "strong_pairs": [(code_a, code_b, prob), ...]
            }
        """
        if len(concept_stocks) < 2:
            return {"avg_prob": 0, "max_prob": 0, "strong_pairs": []}

        pairs = []
        for i, stock_a in enumerate(concept_stocks):
            for stock_b in concept_stocks[i+1:]:
                prob = self.calc_lag_probability(stock_a, stock_b, lag, zt_records)
                if prob > 0:
                    pairs.append((stock_a, stock_b, prob))

        if not pairs:
            return {"avg_prob": 0, "max_prob": 0, "strong_pairs": []}

        probs = [p[2] for p in pairs]

        return {
            "avg_prob": round(sum(probs) / len(probs), 3),
            "max_prob": round(max(probs), 3),
            "strong_pairs": sorted(pairs, key=lambda x: x[2], reverse=True)[:10]
        }

    def identify_follow_stocks(self, dragon_code: str, all_stocks: List[str],
                               zt_records: List[Dict], lag: int = 2) -> Dict[str, float]:
        """
        识别跟风股票（龙头涨停后N日内跟涨）

        Args:
            dragon_code: 龙头股票代码
            all_stocks: 所有股票列表
            zt_records: 涨停记录
            lag: 滞后期数

        Returns:
            {stock_code: follow_prob}
        """
        follow_probs = {}

        dragon_dates = sorted([
            r.get('date', '') for r in zt_records if r.get('stock_code') == dragon_code
        ])

        for stock in all_stocks:
            if stock == dragon_code:
                continue

            stock_dates = set([
                r.get('date', '') for r in zt_records if r.get('stock_code') == stock
            ])

            linkage_count = 0
            for d in dragon_dates:
                for n in range(1, lag + 1):
                    lagged = self._get_nth_trading_day_after(d, n)
                    if lagged and lagged in stock_dates:
                        linkage_count += 1
                        break  # 找到一次即可

            if dragon_dates:
                follow_probs[stock] = round(linkage_count / len(dragon_dates), 3)

        return follow_probs


if __name__ == "__main__":
    print("=" * 60)
    print("联动分析测试")
    print("=" * 60)

    analyzer = LinkageAnalyzer()

    # 测试数据
    test_records = [
        {'stock_code': '000001', 'date': '20260401'},
        {'stock_code': '000002', 'date': '20260402'},  # 000001 T+1联动
        {'stock_code': '000001', 'date': '20260405'},
        {'stock_code': '000003', 'date': '20260407'},  # 000001 T+2联动
        {'stock_code': '000001', 'date': '20260410'},
        {'stock_code': '000002', 'date': '20260412'},  # 000001 T+2联动
    ]

    print("\n测试涨停记录:")
    for r in test_records:
        print(f"  {r['date']}: {r['stock_code']}")

    # 测试滞后联动概率
    prob_1 = analyzer.calc_lag_probability('000001', '000002', lag=1, zt_records=test_records)
    prob_2 = analyzer.calc_lag_probability('000001', '000002', lag=2, zt_records=test_records)

    print(f"\n000001对000002的滞后联动概率:")
    print(f"  T+1: {prob_1:.2%}")
    print(f"  T+2: {prob_2:.2%}")

    # 测试联动矩阵
    stocks = ['000001', '000002', '000003']
    matrix = analyzer.build_linkage_matrix(stocks, test_records, lag_days=[1, 2])

    print(f"\n联动矩阵:")
    for m in matrix:
        print(f"  {m['stock_a']} <-> {m['stock_b']}: strength={m['strength']:.2%}")

    print("\n测试完成!")
