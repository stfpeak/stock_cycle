"""
题材炒作周期检测模块
====================
功能：自动划分题材多轮炒作周期

使用示例：
    from concept_cycle_detector import CycleDetector

    detector = CycleDetector()
    waves = detector.detect_cycle_waves(zt_records, gap_threshold=3)
"""

from typing import List, Dict, Set
from datetime import datetime, timedelta


class CycleDetector:
    """炒作周期检测器"""

    DEFAULT_GAP_THRESHOLD = 3  # 交易日间隔超过3天则划分新周期

    def __init__(self, gap_threshold: int = None):
        self.gap_threshold = gap_threshold or self.DEFAULT_GAP_THRESHOLD

    def detect_cycle_waves(self, zt_records: List[Dict], gap_threshold: int = None) -> List[Dict]:
        """
        识别题材的多轮炒作周期

        Args:
            zt_records: 涨停记录列表
            gap_threshold: 间隔阈值（默认3个交易日）

        Returns:
            周期列表
        """
        threshold = gap_threshold or self.gap_threshold

        if not zt_records:
            return []

        # 1. 按日期排序
        sorted_records = sorted(zt_records, key=lambda x: x.get('date', ''))

        # 2. 获取所有涨停日期（去重）
        all_zt_dates = sorted(set(r.get('date', '') for r in sorted_records))

        if not all_zt_dates:
            return []

        # 3. 划分周期
        waves = []
        current_wave = {
            'wave_id': 1,
            'start_date': all_zt_dates[0],
            'end_date': all_zt_dates[0],
            'stocks': set(),
            'dates': []
        }

        for i, date in enumerate(all_zt_dates):
            # 计算与上一个日期的间隔
            if i > 0:
                gap = self._calc_trading_days(all_zt_dates[i-1], date)
                if gap > threshold:
                    # 新周期开始
                    waves.append(self._finalize_wave(current_wave))
                    current_wave = {
                        'wave_id': len(waves) + 1,
                        'start_date': date,
                        'end_date': date,
                        'stocks': set(),
                        'dates': []
                    }

            current_wave['dates'].append(date)

            # 添加当日涨停的股票
            day_stocks = [r.get('stock_code', '') for r in sorted_records if r.get('date') == date]
            current_wave['stocks'].update(day_stocks)
            current_wave['end_date'] = date

        # 添加最后一轮
        if current_wave['dates']:
            waves.append(self._finalize_wave(current_wave))

        return waves

    def _calc_trading_days(self, date1: str, date2: str) -> int:
        """计算两个日期之间的交易日数"""
        try:
            d1 = datetime.strptime(str(date1), '%Y%m%d')
            d2 = datetime.strptime(str(date2), '%Y%m%d')
            return (d2 - d1).days
        except:
            return 0

    def _finalize_wave(self, wave: Dict) -> Dict:
        """完成周期信息"""
        return {
            'wave_id': wave['wave_id'],
            'start_date': wave['start_date'],
            'end_date': wave['end_date'],
            'duration_days': len(wave['dates']),
            'stock_count': len(wave['stocks']),
            'stocks': list(wave['stocks']),
            'zt_dates': wave['dates']
        }

    def build_wave_stocks(self, wave: Dict, zt_records: List[Dict]) -> List[Dict]:
        """
        构建周期内的股票列表（含首次涨停日期）

        Args:
            wave: 周期信息
            zt_records: 所有涨停记录

        Returns:
            [{stock_code, first_zt_date, ...}]
        """
        wave_stocks = []
        wave_stock_codes = set(wave['stocks'])

        for code in wave_stock_codes:
            # 找到该股票在本周期内的首次涨停日期
            stock_zt_dates = [
                r.get('date', '') for r in zt_records
                if r.get('stock_code') == code and r.get('date') in wave['zt_dates']
            ]

            if stock_zt_dates:
                wave_stocks.append({
                    'stock_code': code,
                    'first_zt_date': min(stock_zt_dates),
                    'zt_count_in_wave': len(stock_zt_dates),
                    'zt_dates': sorted(stock_zt_dates)
                })

        # 按首次涨停日期排序
        wave_stocks.sort(key=lambda x: x['first_zt_date'])

        return wave_stocks

    def get_wave_timeline(self, wave: Dict, zt_records: List[Dict]) -> List[Dict]:
        """
        获取周期内的涨停时间线

        Returns:
            [{date: "20260401", stocks: [{code, time}, ...]}, ...]
        """
        timeline = []

        for date in wave['zt_dates']:
            day_stocks = [
                r.get('stock_code', '') for r in zt_records
                if r.get('date') == date and r.get('stock_code') in wave['stocks']
            ]

            timeline.append({
                'date': date,
                'stock_count': len(day_stocks),
                'stocks': day_stocks
            })

        return timeline


if __name__ == "__main__":
    print("=" * 60)
    print("炒作周期检测测试")
    print("=" * 60)

    detector = CycleDetector(gap_threshold=3)

    # 模拟涨停记录
    test_records = [
        {'stock_code': '000001', 'date': '20260401'},
        {'stock_code': '000002', 'date': '20260401'},
        {'stock_code': '000001', 'date': '20260402'},
        {'stock_code': '000003', 'date': '20260402'},
        {'stock_code': '000004', 'date': '20260408'},  # 间隔超过3天
        {'stock_code': '000005', 'date': '20260409'},
        {'stock_code': '000004', 'date': '20260410'},
    ]

    print("\n测试涨停记录:")
    for r in test_records:
        print(f"  {r['date']}: {r['stock_code']}")

    waves = detector.detect_cycle_waves(test_records, gap_threshold=3)

    print(f"\n检测到 {len(waves)} 轮炒作:")
    for wave in waves:
        print(f"\n  第{wave['wave_id']}轮:")
        print(f"    起止日期: {wave['start_date']} ~ {wave['end_date']}")
        print(f"    持续天数: {wave['duration_days']}")
        print(f"    涨停股票: {wave['stocks']}")

    print("\n测试完成!")
