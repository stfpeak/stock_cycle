"""
题材分析报告生成模块
====================
功能：
    1. 生成JSON结构化分析结果
    2. 生成HTML可视化报告

使用示例：
    from concept_report_generator import ReportGenerator

    generator = ReportGenerator()
    generator.generate_json_report(waves, linkage_matrix, echelon, output_dir)
    generator.generate_html_report(waves, linkage_matrix, echelon, output_file)
"""

import os
import json
from datetime import datetime
from typing import List, Dict, Optional


class ReportGenerator:
    """报告生成器"""

    def __init__(self):
        self.report_date = datetime.now().strftime('%Y%m%d')
        self.report_time = datetime.now().strftime('%H:%M:%S')

    def generate_json_report(self, concept_name: str, waves: List[Dict],
                            linkage_matrix: List[Dict], echelon_data: Dict,
                            output_dir: str = None) -> str:
        """
        生成JSON结构化报告

        Returns:
            输出文件路径
        """
        if output_dir is None:
            output_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'data', 'analysis_output'
            )

        os.makedirs(output_dir, exist_ok=True)

        report = {
            'analysis_date': self.report_date,
            'generated_at': self.report_time,
            'concept_name': concept_name,
            'total_waves': len(waves),
            'waves': waves,
            'linkage_matrix': linkage_matrix[:50],  # 只保留前50强关联
            'echelon': echelon_data
        }

        output_file = os.path.join(output_dir, f'wave_analysis_{concept_name}_{self.report_date}.json')

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        return output_file

    def generate_html_report(self, concept_name: str, top20_concepts: List[Dict],
                           waves_data: Dict, linkage_matrix: List[Dict],
                           output_file: str = None) -> str:
        """
        生成HTML可视化报告

        Returns:
            输出文件路径
        """
        if output_file is None:
            output_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'reports'
            )
            os.makedirs(output_dir, exist_ok=True)
            output_file = os.path.join(output_dir, f'top20_concept_analysis_{self.report_date}.html')

        # 生成HTML内容
        html = self._build_html_content(concept_name, top20_concepts, waves_data, linkage_matrix)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html)

        return output_file

    def _build_html_content(self, concept_name: str, top20_concepts: List[Dict],
                           waves_data: Dict, linkage_matrix: List[Dict]) -> str:
        """构建HTML内容"""

        # Top20概念表格行
        top20_rows = ""
        for i, c in enumerate(top20_concepts[:20], 1):
            waves_info = waves_data.get(c['name'], {})
            wave_count = waves_info.get('wave_count', 0)
            stock_count = c.get('stock_count', 0)

            top20_rows += f"""
            <tr>
                <td>{i}</td>
                <td>{c['name']}</td>
                <td>{stock_count}</td>
                <td>{wave_count}</td>
                <td><span class="badge">{wave_count}轮</span></td>
            </tr>
            """

        # 联动矩阵表格行
        matrix_rows = ""
        for m in linkage_matrix[:30]:
            matrix_rows += f"""
            <tr>
                <td>{m.get('stock_a', '')}</td>
                <td>{m.get('stock_b', '')}</td>
                <td>{m.get('lag1_prob', 0):.1%}</td>
                <td>{m.get('lag2_prob', 0):.1%}</td>
                <td>{m.get('lag3_prob', 0):.1%}</td>
                <td><span class="strength">{(m.get('strength', 0)):.1%}</span></td>
            </tr>
            """

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{concept_name} - 题材联动分析报告</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #1a1a2e; color: #eee; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{ color: #00d4ff; border-bottom: 2px solid #00d4ff; padding-bottom: 10px; }}
        h2 {{ color: #ff6b6b; margin-top: 30px; }}
        .header-info {{ background: #16213e; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ background: #0f3460; color: #00d4ff; }}
        tr:hover {{ background: #16213e; }}
        .badge {{ background: #e94560; padding: 3px 8px; border-radius: 4px; font-size: 12px; }}
        .strength {{ background: #00d4ff; color: #1a1a2e; padding: 3px 8px; border-radius: 4px; font-weight: bold; }}
        .section {{ background: #16213e; border-radius: 8px; padding: 20px; margin: 20px 0; }}
        .chart-placeholder {{ background: #0f3460; height: 200px; border-radius: 8px; display: flex; align-items: center; justify-content: center; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>概念题材联动分析报告</h1>
        <div class="header-info">
            <p><strong>报告日期:</strong> {self.report_date}</p>
            <p><strong>生成时间:</strong> {self.report_time}</p>
            <p><strong>分析范围:</strong> 同花顺Top20题材 · 近365天数据</p>
        </div>

        <div class="section">
            <h2>📊 Top20 热门题材概览</h2>
            <table>
                <thead>
                    <tr>
                        <th>排名</th>
                        <th>题材名称</th>
                        <th>成分股数量</th>
                        <th>炒作轮次</th>
                        <th>状态</th>
                    </tr>
                </thead>
                <tbody>
                    {top20_rows}
                </tbody>
            </table>
        </div>

        <div class="section">
            <h2>🔗 联动矩阵 (Top 30)</h2>
            <table>
                <thead>
                    <tr>
                        <th>股票A</th>
                        <th>股票B</th>
                        <th>T+1联动</th>
                        <th>T+2联动</th>
                        <th>T+3联动</th>
                        <th>综合强度</th>
                    </tr>
                </thead>
                <tbody>
                    {matrix_rows}
                </tbody>
            </table>
        </div>

        <div class="section">
            <h2>📈 炒作周期分析</h2>
            <div class="chart-placeholder">
                炒作周期可视化图表（需要ECharts支持）
            </div>
        </div>
    </div>
</body>
</html>"""

        return html

    def generate_batch_reports(self, top20_concepts: List[Dict],
                                all_waves: Dict, all_matrix: Dict,
                                output_dir: str = None) -> List[str]:
        """
        批量生成报告

        Returns:
            输出文件列表
        """
        if output_dir is None:
            output_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'reports', f'concept_analysis_{self.report_date}'
            )

        os.makedirs(output_dir, exist_ok=True)

        output_files = []

        for concept in top20_concepts:
            name = concept['name']
            waves = all_waves.get(name, [])
            matrix = all_matrix.get(name, [])

            echelon_data = {
                'dragon_tier': [],
                'follow_tier': [],
                'supplementary_tier': []
            }

            # 为每个周期生成梯队数据
            for wave in waves:
                wave_stocks = wave.get('stocks', [])
                # 添加角色识别后的梯队
                echelon_data[f'wave_{wave["wave_id"]}'] = wave_stocks

            json_file = self.generate_json_report(name, waves, matrix, echelon_data, output_dir)
            output_files.append(json_file)

        return output_files


if __name__ == "__main__":
    print("=" * 60)
    print("报告生成测试")
    print("=" * 60)

    generator = ReportGenerator()

    # 测试数据
    top20 = [
        {'name': '商业航天', 'stock_count': 45},
        {'name': '卫星导航', 'stock_count': 38},
        {'name': '军工', 'stock_count': 120},
    ]

    waves = [
        {
            'wave_id': 1,
            'start_date': '20260401',
            'end_date': '20260408',
            'duration_days': 6,
            'stock_count': 12,
            'stocks': ['000001', '000002', '000003']
        }
    ]

    matrix = [
        {'stock_a': '000001', 'stock_b': '000002', 'lag1_prob': 0.72, 'lag2_prob': 0.55, 'lag3_prob': 0.35, 'strength': 0.54}
    ]

    echelon = {
        'dragon_tier': [{'stock_code': '000001', 'role': '龙头'}],
        'follow_tier': [{'stock_code': '000002', 'role': '跟风'}],
        'supplementary_tier': []
    }

    # 生成HTML报告
    html_file = generator.generate_html_report('商业航天', top20, {}, matrix)
    print(f"\nHTML报告已生成: {html_file}")

    # 生成JSON报告
    json_file = generator.generate_json_report('商业航天', waves, matrix, echelon)
    print(f"JSON报告已生成: {json_file}")

    print("\n测试完成!")
