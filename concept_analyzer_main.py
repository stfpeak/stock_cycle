#!/usr/bin/env python3
"""
题材联动量化分析 - 主程序
=========================
功能：
    1. 获取同花顺top20题材
    2. 分析近365天日K数据，标记涨停
    3. 划分题材炒作周期
    4. 构建涨停轮动梯队
    5. 计算滞后联动概率
    6. 识别龙头/跟风/补涨
    7. 生成分析报告

使用：
    python concept_analyzer_main.py
"""

import os
import sys
import json
from datetime import datetime, timedelta
from typing import List, Dict

# 追加导入路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from concept_data_fetcher import ConceptDataFetcher
from concept_cycle_detector import CycleDetector
from concept_linkage_analyzer import LinkageAnalyzer
from concept_role_identifier import RoleIdentifier
from concept_report_generator import ReportGenerator


class ConceptAnalyzer:
    """题材联动分析器主类"""

    def __init__(self):
        self.fetcher = ConceptDataFetcher()
        self.cycle_detector = CycleDetector(gap_threshold=3)
        self.linkage_analyzer = LinkageAnalyzer()
        self.role_identifier = RoleIdentifier()
        self.report_gen = ReportGenerator()

        self.top20_concepts = []
        self.analysis_results = {}

    def run_full_analysis(self, concept_names: List[str] = None, days: int = 365) -> Dict:
        """
        运行完整分析流程

        Args:
            concept_names: 概念名称列表，None则使用top20
            days: 分析天数

        Returns:
            分析结果字典
        """
        print("=" * 60)
        print("题材联动量化分析")
        print("=" * 60)

        # 1. 获取top20题材
        if concept_names is None:
            self.top20_concepts = self.fetcher.get_ths_top20_concepts()
        else:
            self.top20_concepts = [{'name': n} for n in concept_names]

        print(f"\n获取到 {len(self.top20_concepts)} 个题材")
        for i, c in enumerate(self.top20_concepts[:5], 1):
            print(f"  {i}. {c['name']}")

        all_results = {}

        # 2. 分析每个题材
        for concept in self.top20_concepts:
            name = concept['name']
            print(f"\n{'='*50}")
            print(f"分析题材: {name}")
            print('='*50)

            try:
                result = self.analyze_single_concept(name, days)
                all_results[name] = result
                print(f"  炒作周期: {len(result.get('waves', []))}轮")
                print(f"  涨停股票: {result.get('zt_stock_count', 0)}只")
            except Exception as e:
                print(f"  分析失败: {e}")
                all_results[name] = {'error': str(e)}

        # 3. 生成汇总报告
        self._generate_summary_report(all_results)

        return all_results

    def analyze_single_concept(self, concept_name: str, days: int = 365) -> Dict:
        """
        分析单个题材

        Returns:
            {
                "waves": [...],
                "linkage_matrix": [...],
                "echelon": {...}
            }
        """
        # 获取涨停记录
        print(f"  获取涨停记录...")
        zt_records = self.fetcher.get_concept_zt_records(concept_name, days)

        if not zt_records:
            print(f"  无涨停记录")
            return {'waves': [], 'linkage_matrix': [], 'echelon': {}, 'zt_stock_count': 0}

        zt_stock_count = len(set(r.get('stock_code', '') for r in zt_records))
        print(f"  涨停记录: {len(zt_records)}条, 涨停股票: {zt_stock_count}只")

        # 划分炒作周期
        print(f"  划分炒作周期...")
        waves = self.cycle_detector.detect_cycle_waves(zt_records)

        # 为每个周期添加详细信息
        for wave in waves:
            wave_stocks = self.cycle_detector.build_wave_stocks(wave, zt_records)

            # 识别角色
            if wave_stocks:
                roles = self.role_identifier.identify_wave_roles(wave_stocks, wave['start_date'])
                wave['wave_stocks'] = roles
                wave['summary'] = self.role_identifier.get_echelon_summary(roles)

        print(f"  检测到 {len(waves)} 轮炒作")

        # 构建联动矩阵
        print(f"  构建联动矩阵...")
        stock_codes = list(set(r.get('stock_code', '') for r in zt_records))
        linkage_matrix = self.linkage_analyzer.build_linkage_matrix(stock_codes, zt_records)

        # 构建梯队
        all_wave_stocks = []
        for wave in waves:
            all_wave_stocks.extend(wave.get('wave_stocks', []))

        echelon = self.role_identifier.rank_echelon(all_wave_stocks) if all_wave_stocks else {
            'dragon_tier': [],
            'follow_tier': [],
            'supplementary_tier': []
        }

        # 生成报告
        self.report_gen.generate_json_report(concept_name, waves, linkage_matrix, echelon)

        return {
            'waves': waves,
            'linkage_matrix': linkage_matrix,
            'echelon': echelon,
            'zt_stock_count': zt_stock_count,
            'zt_records_count': len(zt_records)
        }

    def _generate_summary_report(self, all_results: Dict):
        """生成汇总报告"""
        summary = {
            'report_date': datetime.now().strftime('%Y%m%d'),
            'report_time': datetime.now().strftime('%H:%M:%S'),
            'concept_count': len(all_results),
            'concepts': []
        }

        for name, result in all_results.items():
            if 'error' in result:
                continue

            waves = result.get('waves', [])
            linkage = result.get('linkage_matrix', [])

            concept_info = {
                'name': name,
                'wave_count': len(waves),
                'zt_stock_count': result.get('zt_stock_count', 0),
                'strong_linkage_count': len([m for m in linkage if m.get('strength', 0) >= 0.5])
            }
            summary['concepts'].append(concept_info)

        # 保存汇总报告
        output_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'data', 'analysis_output'
        )
        os.makedirs(output_dir, exist_ok=True)

        summary_file = os.path.join(output_dir, f'summary_{datetime.now().strftime("%Y%m%d")}.json')
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        print(f"\n汇总报告已生成: {summary_file}")

        # 生成HTML总览报告
        self._generate_html_summary(summary, all_results)

    def _generate_html_summary(self, summary: Dict, all_results: Dict):
        """生成HTML汇总报告"""
        # 构建Top20表格
        rows = ""
        for i, c in enumerate(summary['concepts'][:20], 1):
            rows += f"""
            <tr>
                <td>{i}</td>
                <td>{c['name']}</td>
                <td>{c['zt_stock_count']}</td>
                <td>{c['wave_count']}</td>
                <td>{c['strong_linkage_count']}</td>
            </tr>
            """

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>题材联动分析总览</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 20px; background: #1a1a2e; color: #eee; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{ color: #00d4ff; border-bottom: 2px solid #00d4ff; padding-bottom: 10px; }}
        h2 {{ color: #ff6b6b; margin-top: 30px; }}
        .header-info {{ background: #16213e; padding: 15px; border-radius: 8px; margin-bottom: 20px; display: flex; gap: 30px; }}
        .stat {{ text-align: center; }}
        .stat-value {{ font-size: 32px; color: #00d4ff; font-weight: bold; }}
        .stat-label {{ color: #888; font-size: 14px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ background: #0f3460; color: #00d4ff; }}
        tr:hover {{ background: #16213e; }}
        .badge {{ background: #e94560; padding: 3px 8px; border-radius: 4px; font-size: 12px; }}
        .section {{ background: #16213e; border-radius: 8px; padding: 20px; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>同花顺Top20题材联动分析报告</h1>
        <div class="header-info">
            <div class="stat">
                <div class="stat-value">{summary['report_date'][:8]}</div>
                <div class="stat-label">报告日期</div>
            </div>
            <div class="stat">
                <div class="stat-value">{summary['concept_count']}</div>
                <div class="stat-label">分析题材数</div>
            </div>
        </div>

        <div class="section">
            <h2>Top20 题材概览</h2>
            <table>
                <thead>
                    <tr>
                        <th>排名</th>
                        <th>题材名称</th>
                        <th>涨停股票数</th>
                        <th>炒作轮次</th>
                        <th>强关联数</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>"""

        output_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'reports'
        )
        os.makedirs(output_dir, exist_ok=True)

        html_file = os.path.join(output_dir, f'top20_concept_summary_{summary["report_date"]}.html')
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"HTML总览报告已生成: {html_file}")


def main():
    """主入口"""
    analyzer = ConceptAnalyzer()

    # 运行完整分析
    results = analyzer.run_full_analysis()

    print("\n" + "=" * 60)
    print("分析完成!")
    print("=" * 60)

    return results


if __name__ == "__main__":
    main()
