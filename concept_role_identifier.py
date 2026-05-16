"""
题材角色识别模块
================
功能：识别启动龙头、发酵跟风、补涨标的

使用示例：
    from concept_role_identifier import RoleIdentifier

    identifier = RoleIdentifier()
    roles = identifier.identify_wave_roles(wave_stocks, wave_start_date)
"""

from typing import List, Dict, Optional
from datetime import datetime


class RoleIdentifier:
    """角色识别器"""

    # 龙头阈值：最早涨停的1-2只
    DRAGON_COUNT = 2
    # 跟风阈值：龙头后5个交易日内涨停
    FOLLOW_DAYS_THRESHOLD = 5
    # 补涨阈值：炒作后期（>5天后）首次涨停
    SUPPLEMENTARY_DAYS_THRESHOLD = 5

    def identify_wave_roles(self, wave_stocks: List[Dict],
                            wave_start_date: str) -> List[Dict]:
        """
        识别周期内股票角色

        Args:
            wave_stocks: 周期内股票列表（含first_zt_date）
            wave_start_date: 周期起始日期

        Returns:
            [{stock_code, role, first_zt_date, lag_days}, ...]
        """
        if not wave_stocks:
            return []

        # 计算每只股票的首次涨停相对天数
        for stock in wave_stocks:
            stock['lag_days'] = self._calc_lag_days(wave_start_date, stock['first_zt_date'])

        # 识别龙头：最早涨停的1-2只
        sorted_by_time = sorted(wave_stocks, key=lambda x: (x['first_zt_date'], x['lag_days']))

        dragons = []
        follows = []
        supplementaries = []

        for stock in sorted_by_time:
            lag = stock.get('lag_days', 0)

            if len(dragons) < self.DRAGON_COUNT:
                stock['role'] = '龙头'
                dragons.append(stock)
            elif lag <= self.FOLLOW_DAYS_THRESHOLD:
                stock['role'] = '跟风'
                follows.append(stock)
            else:
                stock['role'] = '补涨'
                supplementaries.append(stock)

        return sorted_by_time

    def _calc_lag_days(self, start_date: str, target_date: str) -> int:
        """计算起始日期到目标日期的交易日数（简化版）"""
        try:
            d1 = datetime.strptime(str(start_date), '%Y%m%d')
            d2 = datetime.strptime(str(target_date), '%Y%m%d')
            return max(0, (d2 - d1).days)
        except:
            return 0

    def identify_dragon(self, wave_stocks: List[Dict]) -> List[Dict]:
        """识别龙头股票"""
        return [s for s in wave_stocks if s.get('role') == '龙头']

    def identify_follow(self, wave_stocks: List[Dict]) -> List[Dict]:
        """识别跟风股票"""
        return [s for s in wave_stocks if s.get('role') == '跟风']

    def identify_supplementary(self, wave_stocks: List[Dict]) -> List[Dict]:
        """识别补涨标的"""
        return [s for s in wave_stocks if s.get('role') == '补涨']

    def rank_echelon(self, wave_stocks: List[Dict]) -> Dict:
        """
        梯队排序

        Returns:
            {
                "dragon_tier": [...],
                "follow_tier": [...],
                "supplementary_tier": [...]
            }
        """
        return {
            'dragon_tier': self.identify_dragon(wave_stocks),
            'follow_tier': self.identify_follow(wave_stocks),
            'supplementary_tier': self.identify_supplementary(wave_stocks)
        }

    def get_echelon_summary(self, wave_stocks: List[Dict]) -> Dict:
        """获取梯队汇总"""
        dragons = self.identify_dragon(wave_stocks)
        follows = self.identify_follow(wave_stocks)
        supplementaries = self.identify_supplementary(wave_stocks)

        return {
            'total_stocks': len(wave_stocks),
            'dragon_count': len(dragons),
            'follow_count': len(follows),
            'supplementary_count': len(supplementaries),
            'dragon_codes': [s['stock_code'] for s in dragons],
            'follow_codes': [s['stock_code'] for s in follows],
            'supplementary_codes': [s['stock_code'] for s in supplementaries]
        }


if __name__ == "__main__":
    print("=" * 60)
    print("角色识别测试")
    print("=" * 60)

    identifier = RoleIdentifier()

    # 模拟周期股票
    wave_stocks = [
        {'stock_code': '000001', 'first_zt_date': '20260401'},
        {'stock_code': '000002', 'first_zt_date': '20260401'},
        {'stock_code': '000003', 'first_zt_date': '20260403'},
        {'stock_code': '000004', 'first_zt_date': '20260405'},
        {'stock_code': '000005', 'first_zt_date': '20260412'},
    ]

    print("\n周期股票:")
    for s in wave_stocks:
        print(f"  {s['stock_code']}: {s['first_zt_date']}")

    roles = identifier.identify_wave_roles(wave_stocks, '20260401')

    print("\n角色识别结果:")
    for r in roles:
        print(f"  {r['stock_code']}: role={r['role']}, lag_days={r['lag_days']}")

    summary = identifier.get_echelon_summary(roles)
    print(f"\n梯队汇总:")
    print(f"  龙头: {summary['dragon_count']}只 - {summary['dragon_codes']}")
    print(f"  跟风: {summary['follow_count']}只 - {summary['follow_codes']}")
    print(f"  补涨: {summary['supplementary_count']}只 - {summary['supplementary_codes']}")

    print("\n测试完成!")
