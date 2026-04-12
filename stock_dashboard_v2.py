"""
股票分析报告看板 (V2版本)
=========================

功能说明:
    整合多维度数据，输出热门概念板块的涨停股分析报告

新增功能:
    1. 15日涨停板（缓存机制）
    2. 其他概念分类（不在TOP20的涨停股）
    3. 未涨停热股章节（TOP100中15日未涨停）
    4. 多概念股票章节（涵盖3+概念的股票）
    5. 交易日历获取
    6. 今日涨停看板

数据来源:
    1. adata.sentiment.hot.hot_concept_20_ths()  - 同花顺热门概念板块TOP20
    2. adata.sentiment.hot.hot_rank_100_ths()    - 同花顺热股TOP100
    3. ak.stock_zt_pool_em()                     - 涨停股池
    4. adata.stock.info.trade_calendar()         - 交易日历
    5. ../stock_analysis/ths_concept_stock_list.csv - 概念与股票对应关系

使用方法:
    python stock_dashboard_v2.py

依赖库:
    adata   - 金融数据接口
    akshare - 涨停数据
    pandas  - 数据处理
"""

import adata
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta, timezone
import warnings
import os
import json

warnings.filterwarnings('ignore')

# 获取当前脚本所在目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 数据目录结构
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
ZT_POOL_DIR = os.path.join(DATA_DIR, "zt_pool")
CONCEPTS_DIR = os.path.join(DATA_DIR, "concepts")
HOT_STOCKS_DIR = os.path.join(DATA_DIR, "hot_stocks")
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports")
ARCHIVE_DIR = os.path.join(SCRIPT_DIR, "archive")
CACHE_DIR = os.path.join(SCRIPT_DIR, "cache")

# 确保目录存在
for d in [ZT_POOL_DIR, CONCEPTS_DIR, HOT_STOCKS_DIR, REPORTS_DIR, CACHE_DIR]:
    os.makedirs(d, exist_ok=True)

# 概念股票列表（data目录下）
CONCEPT_STOCK_FILE = os.path.join(SCRIPT_DIR, "data", "ths_concept_stock_list.csv")

# 北京时间（UTC+8）
BEIJING_TZ = timezone(timedelta(hours=8))


def get_today_str():
    """获取今天的日期字符串 YYYYMMDD（北京时间）"""
    return get_beijing_now().strftime('%Y%m%d')


def get_beijing_now():
    """获取当前北京时间"""
    return datetime.now(BEIJING_TZ)


def is_trading_day(date_str=None):
    """检查指定日期是否为A股交易日
    
    Args:
        date_str: 日期字符串 YYYYMMDD，默认为今天（北京时间）
    
    Returns:
        bool: 是否为交易日
    """
    if date_str is None:
        date_str = get_beijing_now().strftime('%Y%m%d')
    
    try:
        year = int(date_str[:4])
        df = adata.stock.info.trade_calendar(year=year)
        trading_dates = set(df['日期'].astype(str).tolist())
        return date_str in trading_dates
    except Exception as e:
        print(f"  ⚠ 获取交易日历失败: {e}，使用工作日判断")
        # 备用：工作日判断（不含节假日）
        try:
            dt = datetime.strptime(date_str, '%Y%m%d')
            return dt.weekday() < 5
        except:
            return False


def should_auto_update_zt():
    """判断是否应自动更新今日涨停数据
    
    规则：
    1. 今日为A股交易日
    2. 当前北京时间在盘中（9:25后）或收盘后
    
    Returns:
        (bool, str): (是否需要更新, 今日日期字符串YYYYMMDD)
    """
    beijing_now = get_beijing_now()
    today_str = beijing_now.strftime('%Y%m%d')
    hour, minute = beijing_now.hour, beijing_now.minute
    time_str = f"{hour:02d}:{minute:02d}"
    
    # 检查是否为交易日
    if not is_trading_day(today_str):
        print(f"  ℹ 今日({today_str})非交易日，使用缓存数据")
        return False, today_str
    
    # 盘前（9:25之前）不更新
    if hour < 9 or (hour == 9 and minute < 25):
        print(f"  ℹ 今日({today_str})为交易日，尚未开盘(北京时间{time_str})，使用缓存数据")
        return False, today_str
    
    # 盘中或收盘后 → 自动更新
    if hour < 15 or (hour == 15 and minute == 0):
        status = "盘中"
    else:
        status = "收盘后"
    
    print(f"  ★ 今日({today_str})为交易日，当前{status}(北京时间{time_str})，将自动更新涨停数据")
    return True, today_str


def get_trading_dates_2026(days=15):
    """获取2026年近N个交易日期（使用交易日历）"""
    try:
        df = adata.stock.info.trade_calendar(year=2026)
        trading_dates = df['日期'].astype(str).tolist()
        # 取最新的N个
        return trading_dates[-days:] if len(trading_dates) >= days else trading_dates
    except Exception as e:
        print(f"  获取2026年交易日历失败: {e}，使用备用逻辑")
        # 备用逻辑
        dates = []
        current = datetime.now()
        while len(dates) < days:
            if current.weekday() < 5:
                dates.append(current.strftime('%Y%m%d'))
            current -= timedelta(days=1)
        return dates


def get_trading_dates(days=15):
    """获取近N个交易日期（备用逻辑）"""
    dates = []
    current = datetime.now()
    while len(dates) < days:
        if current.weekday() < 5:
            dates.append(current.strftime('%Y%m%d'))
        current -= timedelta(days=1)
    return dates


def check_zt_pool_cache(dates):
    """检查涨停池缓存，返回需要获取的日期"""
    missing_dates = []
    for date in dates:
        file_path = os.path.join(ZT_POOL_DIR, f"{date}.csv")
        if not os.path.exists(file_path):
            missing_dates.append(date)
    return missing_dates, None


def load_zt_pool_from_files(dates):
    """从分日期的文件中加载涨停数据"""
    all_data = []
    for date in dates:
        file_path = os.path.join(ZT_POOL_DIR, f"{date}.csv")
        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path)
                if len(df) > 0:
                    all_data.append(df)
            except Exception as e:
                print(f"  ⚠ 读取 {date} 数据失败: {e}")

    if all_data:
        df_all = pd.concat(all_data, ignore_index=True)
        # 统一交易日期为int类型
        df_all['交易日期'] = pd.to_numeric(df_all['交易日期'], errors='coerce').astype('Int64')
        df_all['代码'] = pd.to_numeric(df_all['代码'], errors='coerce').astype('Int64')
        return df_all
    return None


def get_zt_pool(dates, force_refresh_today=False, today_str=None):
    """
    获取涨停股池 - 从分日期文件加载

    Args:
        dates: 需要获取的日期列表
        force_refresh_today: 是否强制刷新今日数据（交易日盘中/收盘后）
        today_str: 今日日期字符串（用于强制刷新判断）
    """
    print("获取涨停股池...")

    # 检查缺失的日期
    missing_dates = check_zt_pool_cache(dates)[0]

    # 如果需要强制刷新今日数据
    if force_refresh_today and today_str and today_str in dates:
        if today_str not in missing_dates:
            # 今日数据存在，但需要强制刷新
            file_path = os.path.join(ZT_POOL_DIR, f"{today_str}.csv")
            if os.path.exists(file_path):
                os.remove(file_path)  # 删除旧文件
                missing_dates.append(today_str)
                print(f"  ★ 移除今日({today_str})旧数据，重新获取...")

    # 从文件加载已有的数据
    existing_dates = [d for d in dates if d not in missing_dates]
    df_existing = load_zt_pool_from_files(existing_dates) if existing_dates else None

    if df_existing is not None:
        print(f"  ✓ 已有数据: {len(df_existing)} 条记录 ({len(existing_dates)} 个交易日)")

    # 获取缺失的数据
    all_data = []
    if df_existing is not None:
        all_data.append(df_existing)

    for date in missing_dates:
        try:
            df = ak.stock_zt_pool_em(date=date)
            df['交易日期'] = int(date)
            # 保存到单独文件
            file_path = os.path.join(ZT_POOL_DIR, f"{date}.csv")
            df.to_csv(file_path, index=False, encoding='utf-8-sig')
            print(f"  ✓ {date}: {len(df)} 只 (已保存)")
            all_data.append(df)
        except Exception as e:
            print(f"  ✗ {date}: 获取失败 ({e})")

    if all_data:
        df_all = pd.concat(all_data, ignore_index=True)
        df_all['交易日期'] = pd.to_numeric(df_all['交易日期'], errors='coerce').astype('Int64')
        df_all['代码'] = pd.to_numeric(df_all['代码'], errors='coerce').astype('Int64')
        df_all = df_all.drop_duplicates(subset=['代码', '交易日期'], keep='last')
        print(f"  总计: {len(df_all)} 条记录")
        return df_all
    return None


def get_hot_concepts():
    """获取同花顺热门概念板块TOP20"""
    print("获取热门概念板块TOP20...")
    try:
        df = adata.sentiment.hot.hot_concept_20_ths()
        # 保存到新目录
        file_path = os.path.join(CONCEPTS_DIR, "hot_concepts_latest.csv")
        df.to_csv(file_path, index=False, encoding='utf-8-sig')
        print(f"  ✓ 获取 {len(df)} 个热门概念 (已保存)")
        return df
    except Exception as e:
        print(f"  ⚠ 获取概念失败: {e}，尝试加载缓存...")
        # 尝试加载缓存
        file_path = os.path.join(CONCEPTS_DIR, "hot_concepts_latest.csv")
        if os.path.exists(file_path):
            df = pd.read_csv(file_path)
            print(f"  ✓ 加载缓存 {len(df)} 个热门概念")
            return df
        return None


def get_hot_stocks():
    """获取同花顺热股TOP100"""
    print("获取同花顺热股TOP100...")
    try:
        df = adata.sentiment.hot.hot_rank_100_ths()
        # 保存到新目录
        file_path = os.path.join(HOT_STOCKS_DIR, "hot_stocks_latest.csv")
        df.to_csv(file_path, index=False, encoding='utf-8-sig')
        print(f"  ✓ 获取 {len(df)} 只热门股 (已保存)")
        return df
    except Exception as e:
        print(f"  ⚠ 获取热股失败: {e}，尝试加载缓存...")
        # 尝试加载缓存
        file_path = os.path.join(HOT_STOCKS_DIR, "hot_stocks_latest.csv")
        if os.path.exists(file_path):
            df = pd.read_csv(file_path)
            print(f"  ✓ 加载缓存 {len(df)} 只热门股")
            return df
        return None


def load_concept_stock_list():
    """加载概念与股票对应关系"""
    if os.path.exists(CONCEPT_STOCK_FILE):
        print("加载概念股票对应关系...")
        df = pd.read_csv(CONCEPT_STOCK_FILE)
        print(f"  ✓ 加载 {len(df)} 条记录")
        return df
    print("  ✗ 概念股票文件不存在")
    return None


def build_date_rhythm(df_zt_pool, dates, stock_codes):
    """构建以日期为维度的涨停数据"""
    date_rhythm = {d: [] for d in dates}

    if df_zt_pool is None:
        return date_rhythm

    for _, row in df_zt_pool.iterrows():
        code = str(row['代码_str'])  # 使用已转换的代码字符串
        date = str(row['交易日期'])
        name = row['名称'] if '名称' in row else ''
        lianban = int(row['连板数']) if pd.notna(row['连板数']) else 1
        # 使用行中的 首次封板时间 字段（HHMMSS格式，如 92500.0 表示 09:25:00）
        first_seal_time = row['首次封板时间'] if '首次封板时间' in row else None

        if date in date_rhythm and code in stock_codes:
            date_rhythm[date].append((name, lianban, code, first_seal_time))

    return date_rhythm


def analyze_concept_stocks(df_hot_concepts, df_concept_stock, df_zt_pool, df_hot_stocks, dates):
    """分析热门概念板块下的涨停股"""
    print("分析热门概念板块涨停股...")

    # TOP20概念代码集合
    top20_codes = set(df_hot_concepts['concept_code'].astype(str).tolist())

    # 构建代码到概念的映射
    code_to_concepts = {}
    if df_concept_stock is not None:
        for _, row in df_concept_stock.iterrows():
            code = str(row['股票代码']).zfill(6)
            concept_code = str(row['概念代码'])
            if code not in code_to_concepts:
                code_to_concepts[code] = set()
            if concept_code in top20_codes:
                code_to_concepts[code].add(concept_code)

    # 辅助函数：在函数开头定义，确保在整个函数内可见
    def get_hot_rank(code):
        code_str = str(code).zfill(6)
        if df_hot_stocks is not None:
            match = df_hot_stocks[df_hot_stocks['stock_code'].astype(str).str.zfill(6) == code_str]
            if not match.empty:
                return int(match.iloc[0]['rank'])
        return 999

    def get_hot_value(code):
        code_str = str(code).zfill(6)
        if df_hot_stocks is not None:
            match = df_hot_stocks[df_hot_stocks['stock_code'].astype(str).str.zfill(6) == code_str]
            if not match.empty:
                return float(match.iloc[0]['hot_value'])
        return 0

    results = []
    other_stocks = []  # 不在TOP20的涨停股
    hot_stocks_set = set(df_hot_stocks['stock_code'].astype(str).str.zfill(6).tolist()) if df_hot_stocks is not None else set()

    # 修复：涨停池代码是float类型，需要先转为整数再转字符串，避免 '.0' 后缀问题，并zfill(6)保留前导零
    if df_zt_pool is not None:
        df_zt_pool['代码_str'] = df_zt_pool['代码'].apply(lambda x: str(int(x)).zfill(6) if pd.notna(x) else '')
        zt_stock_codes = set(df_zt_pool['代码_str'].tolist())
    else:
        zt_stock_codes = set()

    # 未涨停的热股
    not_zt_hot_stocks = []

    for _, stock in df_hot_stocks.iterrows() if df_hot_stocks is not None else []:
        code = str(stock['stock_code']).zfill(6)
        if code not in zt_stock_codes:
            not_zt_hot_stocks.append(stock)

    for _, concept in df_hot_concepts.iterrows():
        concept_code = str(concept['concept_code'])
        concept_name = concept['concept_name']
        hot_value = concept['hot_value']

        stocks_in_concept = df_concept_stock[
            df_concept_stock['概念代码'].astype(str) == concept_code
        ] if df_concept_stock is not None else pd.DataFrame()

        if stocks_in_concept.empty:
            continue

        stock_codes = set(stocks_in_concept['股票代码'].astype(str).apply(lambda x: x.zfill(6)).tolist())
        stock_name_map = dict(zip(stocks_in_concept['股票代码'].astype(str).apply(lambda x: x.zfill(6)),
                                  stocks_in_concept['股票名称']))

        if df_zt_pool is not None:
            zt_stocks = df_zt_pool[df_zt_pool['代码_str'].isin(stock_codes)]
        else:
            zt_stocks = pd.DataFrame()

        if zt_stocks.empty:
            continue

        date_rhythm = build_date_rhythm(df_zt_pool, dates, stock_codes)

        zt_count = zt_stocks.groupby('代码').agg({
            '名称': 'first',
            '连板数': 'max',
            '交易日期': 'count'
        }).reset_index()
        zt_count.columns = ['代码', '名称', '最大连板数', '涨停次数']

        def get_all_concepts(code):
            """获取股票的所有概念板块"""
            if df_concept_stock is not None:
                code_str = str(code).zfill(6)
                stock_concepts = df_concept_stock[df_concept_stock['股票代码'].astype(str).str.zfill(6) == code_str]
                return '、'.join(stock_concepts['概念名称'].tolist()[:5])  # 最多5个概念
            return '-'

        zt_count['热度排名'] = zt_count['代码'].apply(get_hot_rank)
        zt_count['热度值'] = zt_count['代码'].apply(get_hot_value)
        zt_count['所属概念'] = zt_count['代码'].apply(get_all_concepts)

        zt_count = zt_count.sort_values(
            ['热度排名', '最大连板数', '涨停次数'],
            ascending=[True, False, False]
        ).reset_index(drop=True)

        # 计算概念统计
        concept_stats = {
            'today_zt_count': 0,
            'days_15_zt_count': 0,
            'max_lianban_10d': 0,
            'multiboard_10d': 0
        }

        # 遍历 date_rhythm 计算统计（近10日）
        recent_dates = dates[:10] if len(dates) >= 10 else dates
        for d in recent_dates:
            stocks_on_date = date_rhythm.get(d, [])
            day_count = len(stocks_on_date)
            concept_stats['days_15_zt_count'] += day_count
            for name, lb, code, first_seal in stocks_on_date:
                if lb > concept_stats['max_lianban_10d']:
                    concept_stats['max_lianban_10d'] = lb
                if lb >= 2:
                    concept_stats['multiboard_10d'] += 1

        # 今日涨停（最近一个日期）
        if dates and dates[0] in date_rhythm:
            concept_stats['today_zt_count'] = len(date_rhythm[dates[0]])

        results.append({
            'concept_code': concept_code,
            'concept_name': concept_name,
            'hot_value': hot_value,
            'stocks': zt_count,
            'date_rhythm': date_rhythm,
            'stats': concept_stats
        })

    # 处理其他概念的涨停股
    if df_zt_pool is not None:
        for _, row in df_zt_pool.iterrows():
            code = str(row['代码_str'])  # 使用已转换的代码字符串（已zfill(6)）
            # 检查是否在TOP20概念中
            concepts = code_to_concepts.get(code, set())
            if not concepts:
                # 不在任何TOP20概念中
                name = row['名称']
                date = str(row['交易日期'])
                lianban = int(row['连板数']) if pd.notna(row['连板数']) else 1

                # 查找该股票所属的所有概念（非TOP20）
                all_concepts = []
                if df_concept_stock is not None:
                    stock_concepts = df_concept_stock[
                        df_concept_stock['股票代码'].astype(str).str.zfill(6) == code
                    ]
                    all_concepts = stock_concepts['概念名称'].tolist()[:3]  # 取前3个

                other_stocks.append({
                    'code': code,
                    'name': name,
                    'date': date,
                    'lianban': lianban,
                    'concepts': all_concepts
                })

    # 找出涵盖3个及以上TOP20概念的股票
    multi_concept_stocks = {}
    for code, concepts in code_to_concepts.items():
        if len(concepts) >= 3:
            if df_zt_pool is not None:
                stock_zt = df_zt_pool[df_zt_pool['代码_str'] == code]
                if not stock_zt.empty:
                    zt_count = len(stock_zt)
                    max_lianban = int(stock_zt['连板数'].max()) if pd.notna(stock_zt['连板数'].max()) else 1
                    name = stock_zt.iloc[0]['名称']

                    concept_names = []
                    for _, concept in df_hot_concepts.iterrows():
                        if str(concept['concept_code']) in concepts:
                            concept_names.append(concept['concept_name'])

                    hot_rank = get_hot_rank(code)
                    hot_val = get_hot_value(code)

                    if code not in multi_concept_stocks:
                        multi_concept_stocks[code] = {
                            'code': code,
                            'name': name,
                            'zt_count': zt_count,
                            'max_lianban': max_lianban,
                            'hot_rank': hot_rank,
                            'hot_value': hot_val,
                            'concepts': concept_names
                        }

    # 构建连板天梯数据 - 按日期展示2板及以上
    ladder_data = {}  # {日期: [(股票名, 连板数, 概念名称, 热度排名), ...]}
    for d in dates:
        ladder_data[d] = []

    if df_zt_pool is not None:
        # 获取TOP20概念名称映射
        top20_names = dict(zip(df_hot_concepts['concept_code'].astype(str),
                              df_hot_concepts['concept_name']))

        for _, row in df_zt_pool.iterrows():
            code = str(row['代码_str'])  # 使用已转换的代码字符串
            date = str(row['交易日期'])
            name = row['名称']
            lianban = int(row['连板数']) if pd.notna(row['连板数']) else 1

            # 只展示2板及以上
            if lianban >= 2 and date in ladder_data:
                # 获取概念
                stock_concepts = code_to_concepts.get(code, set())
                concept_names = []
                for c in stock_concepts:
                    if c in top20_names:
                        concept_names.append(top20_names[c])
                if not concept_names:
                    # 非TOP20概念
                    if df_concept_stock is not None:
                        other = df_concept_stock[df_concept_stock['股票代码'].astype(str).str.zfill(6) == code]
                        if not other.empty:
                            concept_names = other['概念名称'].tolist()[:2]

                hot_rank = get_hot_rank(code)
                concept_str = ','.join(concept_names[:3]) if concept_names else '-'
                ladder_data[date].append((name, lianban, concept_str, hot_rank, code))

        # 排序：按连板数降序，热度排名升序
        for d in ladder_data:
            ladder_data[d] = sorted(ladder_data[d], key=lambda x: (-x[1], x[3]))

    return {
        'top20_concepts': results,
        'other_stocks': other_stocks,
        'not_zt_hot_stocks': not_zt_hot_stocks,
        'multi_concept_stocks': list(multi_concept_stocks.values()),
        'ladder_data': ladder_data,
        'code_to_concepts': code_to_concepts
    }


def generate_markdown(analysis_result, df_hot_concepts, df_zt_pool, dates, df_concept_stock=None):
    """生成Markdown报告"""
    today = datetime.now().strftime('%Y年%m月%d日')
    today_date = dates[0] if dates else get_today_str()
    today_date_int = int(today_date) if today_date else None

    md = f"""# 股票分析报告

**生成时间**: {today}

---

## 数据来源

- 同花顺热门概念板块TOP20
- 同花顺热股TOP100
- 东方财富涨停股池15日（缓存机制）
- 同花顺概念股票对应关系

---

"""

    # ========== 1. 连板天梯 ==========
    dates_with_ladder = [d for d in dates if analysis_result['ladder_data'].get(d, [])]

    md += f"""## 连板天梯

> 近15交易日2板及以上涨停，按日期横向展示

"""

    for d in dates_with_ladder:
        date_stocks = analysis_result['ladder_data'].get(d, [])
        if date_stocks:
            md += f"**{d[4:]}日** | "
            stock_tags = []
            for name, lb, concepts, hot_rank, code in date_stocks:
                board_tag = get_board_tag(code)
                if lb >= 3:
                    lb_tag = "3板+"
                elif lb == 2:
                    lb_tag = "2板"
                else:
                    lb_tag = "首板"
                stock_tags.append(f"{name}[{lb_tag}{board_tag}]")
            md += " ".join(stock_tags) + "\n"

    md += "\n---\n\n"

    # ========== 2. 连板矩阵 ==========
    top20_concept_names = [r['concept_name'] for r in analysis_result['top20_concepts']]
    recent_6_dates = dates_with_ladder[:6] if dates_with_ladder else dates[:6]

    md += "## 连板矩阵\n\n"
    md += "> 近6交易日2板及以上涨停，概念x日期分布\n\n"

    # 表头
    date_headers = " | ".join([d[4:]+"日" for d in recent_6_dates])
    md += "| 概念 | " + date_headers + " |\n"
    md += "|------|" + "|".join(['---' for _ in recent_6_dates]) + "|\n"

    # 构建矩阵数据
    code_to_concepts = analysis_result.get('code_to_concepts', {})
    top20_names = dict(zip(df_hot_concepts['concept_code'].astype(str), df_hot_concepts['concept_name'])) if df_hot_concepts is not None else {}

    matrix_data = {}
    for concept in top20_concept_names:
        matrix_data[concept] = {}
        for d in recent_6_dates:
            matrix_data[concept][d] = []

    for d in recent_6_dates:
        date_stocks = analysis_result['ladder_data'].get(d, [])
        for name, lb, concepts, hot_rank, code in date_stocks:
            stock_concepts = code_to_concepts.get(code, set())
            for concept in top20_concept_names:
                if concept in concepts or any(top20_names.get(c) == concept for c in stock_concepts):
                    all_concepts = []
                    if df_concept_stock is not None:
                        stock_rows = df_concept_stock[df_concept_stock['股票代码'].astype(str) == code]
                        all_concepts = stock_rows['概念名称'].tolist()[:3]
                    matrix_data[concept][d].append((name, lb, code))

    for concept in top20_concept_names:
        row = f"| **{concept}** |"
        for d in recent_6_dates:
            stocks_in_cell = matrix_data[concept].get(d, [])
            if stocks_in_cell:
                cell_content = ", ".join([f"{name}({lb}板)" for name, lb, code in stocks_in_cell])
                row += f" {cell_content} |"
            else:
                row += " - |"
        md += row + "\n"

    md += "\n---\n\n"

    # ========== 3. 今日涨停看板 ==========
    today_zt_df = df_zt_pool[df_zt_pool['交易日期'] == today_date_int] if df_zt_pool is not None else pd.DataFrame()
    today_zt_count = len(today_zt_df)

    concept_stocks_map = {}
    no_concept_stocks = []

    if not today_zt_df.empty:
        for _, row in today_zt_df.iterrows():
            code = str(row['代码_str'])  # 使用已转换的代码字符串
            name = row['名称']
            lianban = int(row['连板数']) if pd.notna(row['连板数']) else 1

            stock_concepts = code_to_concepts.get(code, set())
            concept_names = [top20_names.get(c, c) for c in stock_concepts if c in top20_names]

            if concept_names:
                for cn in concept_names[:3]:
                    if cn not in concept_stocks_map:
                        concept_stocks_map[cn] = []
                    concept_stocks_map[cn].append((name, code, lianban))
            else:
                no_concept_stocks.append((name, code, lianban))

    md += f"""## 今日涨停看板

> {today_date[4:]}日 | 共 {today_zt_count} 只涨停

"""

    sorted_concepts = sorted(concept_stocks_map.items(), key=lambda x: -len(x[1]))
    for concept_name, stocks in sorted_concepts:
        stock_list = []
        for name, code, lianban in stocks:
            board_tag = get_board_tag(code)
            if lianban >= 3:
                lb_tag = "3板+"
            elif lianban == 2:
                lb_tag = "2板"
            else:
                lb_tag = "首板"
            stock_list.append(f"{name}[{lb_tag}{board_tag}]")
        md += f"### {concept_name} ({len(stocks)})\n\n"
        md += " | ".join(stock_list) + "\n\n"

    if no_concept_stocks:
        stock_list = []
        for name, code, lianban in no_concept_stocks:
            board_tag = get_board_tag(code)
            if lianban >= 3:
                lb_tag = "3板+"
            elif lianban == 2:
                lb_tag = "2板"
            else:
                lb_tag = "首板"
            stock_list.append(f"{name}[{lb_tag}{board_tag}]")
        md += f"### 其他 ({len(no_concept_stocks)})\n\n"
        md += " | ".join(stock_list) + "\n\n"

    md += "---\n\n"

    # ========== 4. 热门概念板块一览 ==========
    df_hot_concepts['hot_value_num'] = pd.to_numeric(df_hot_concepts['hot_value'], errors='coerce')
    concepts_sorted = df_hot_concepts.sort_values('hot_value_num', ascending=False).reset_index(drop=True)

    md += f"""## 热门概念板块一览

> 按热度值排序（数值越大越靠前）

| 排名 | 概念名称 | 热度值 | 标签 |
|------|----------|--------|------|
"""

    for i, row in concepts_sorted.iterrows():
        hot_val = float(row['hot_value']) if row['hot_value'] else 0
        md += f"| {i+1} | {row['concept_name']} | {hot_val:,.0f} | {row['hot_tag']} |\n"

    md += "\n---\n\n"

    # ========== 5. TOP20概念题材 ==========
    md += """## 热门概念板块详情

"""

    for result in analysis_result['top20_concepts']:
        if result['stocks'].empty:
            continue

        md += f"""### {result['concept_name']}

- 热度: {float(result['hot_value'] or 0):,.0f} | 涨停: {len(result['stocks'])}只

"""

        # 涨停节奏
        md += "**涨停节奏**\n\n"
        date_rhythm = result['date_rhythm']
        rhythm_lines = {}
        for d in dates:
            stocks_on_date = date_rhythm.get(d, [])
            if stocks_on_date:
                stocks_sorted = sorted(stocks_on_date, key=lambda x: -x[1])
                for name, lb, code, first_seal in stocks_sorted:
                    if lb >= 3:
                        lb_tag = "3板+"
                    elif lb == 2:
                        lb_tag = "2板"
                    else:
                        lb_tag = "首板"
                    board_tag = get_board_tag(code)
                    if d not in rhythm_lines:
                        rhythm_lines[d] = []
                    rhythm_lines[d].append(f"{name}[{lb_tag}{board_tag}]")

        # 按日期输出
        for d in dates:
            if d in rhythm_lines:
                md += f"- **{d[4:]}日**: {' '.join(rhythm_lines[d])}\n"
        md += "\n"

        # 股票表格
        md += f"| 代码 | 名称 | 连板 | 涨停 | 概念板块 |\n"
        md += f"|------|------|------|------|----------|\n"
        for _, stock in result['stocks'].iterrows():
            code = format_code(stock['代码'])
            lb = int(stock['最大连板数']) if pd.notna(stock['最大连板数']) else 1
            board_tag = get_board_tag(code)
            concepts_str = stock.get('所属概念', '-')
            md += f"| {code} | {stock['名称']}{board_tag} | {lb}板 | {stock['涨停次数']}次 | {concepts_str} |\n"
        md += "\n---\n\n"

    # 汇总
    total_zt = sum(len(r['stocks']) for r in analysis_result['top20_concepts'])
    md += f"""## 汇总统计

- 热门概念板块数: {len(analysis_result['top20_concepts'])}
- TOP20涨停股票总数: {total_zt} 只
- 其他概念涨停股: {len(analysis_result['other_stocks'])} 只
- 未涨停热股: {len(analysis_result['not_zt_hot_stocks'])} 只
- 多概念股票: {len(analysis_result['multi_concept_stocks'])} 只
- 分析时段: {dates[-1]} 至 {dates[0]}
- 今日涨停: {today_zt_count} 只

---

*报告由股票分析系统自动生成*
"""

    return md


def format_code(code):
    """格式化股票代码为6位完整代码"""
    code_str = str(code)
    if len(code_str) < 6:
        code_str = code_str.zfill(6)
    return code_str


def get_board_tag(code):
    """获取板块标签"""
    code_str = format_code(code)
    if len(code_str) >= 2:
        prefix = code_str[:2]
        if prefix in ['00', '60']:
            return '主'
        elif prefix == '30':
            return '创'
        elif prefix == '68':
            return '科'
    return ''


def get_board_tag_html(code, separator=' '):
    """获取带颜色的板块标签HTML
    
    Args:
        code: 股票代码
        separator: 标签前的分隔符，默认空格
    
    Returns:
        HTML字符串，如 " <span class='board-inline board-zhu'>主</span>"
    """
    board = get_board_tag(code)
    if not board:
        return ''
    css_class = {'主': 'board-zhu', '创': 'board-chuang', '科': 'board-ke'}.get(board, '')
    return f"{separator}<span class='board-inline {css_class}'>{board}</span>"


def format_seal_time(t):
    """Format first seal time (HHMMSS format like 92500.0 -> '09:25:00')"""
    if t is None:
        return ''
    try:
        s = str(int(t)).zfill(6)  # pad to 6 digits: "092500"
        return f"{s[:2]}:{s[2:4]}:{s[4:]}"  # "09:25:00"
    except (ValueError, TypeError):
        return ''


def generate_html(analysis_result, df_hot_concepts, df_zt_pool, dates, df_concept_stock=None, archives=None):
    """生成HTML报告"""
    today = datetime.now().strftime('%Y年%m月%d日')
    today_date = dates[0] if dates else get_today_str()
    today_date_int = int(today_date) if today_date else None
    today_str = datetime.now().strftime('%Y%m%d')
    archives = archives or []

    # 共享数据
    code_to_concepts = analysis_result.get('code_to_concepts', {})
    top20_names = dict(zip(df_hot_concepts['concept_code'].astype(str), df_hot_concepts['concept_name'])) if df_hot_concepts is not None else {}

    # ========== 1. 连板天梯（第一章节，日期横排）==========
    ladder_html = ""
    # 只获取有连板股票的日期
    dates_with_ladder = [d for d in dates if analysis_result['ladder_data'].get(d, [])]

    for d in dates_with_ladder:
        date_stocks = analysis_result['ladder_data'].get(d, [])
        if date_stocks:
            date_label = f"{d[4:]}日"
            stocks_html = ""
            for name, lb, concepts, hot_rank, code in date_stocks:
                if lb >= 3:
                    lb_class, lb_tag = "lb-3", "3板+"
                elif lb == 2:
                    lb_class, lb_tag = "lb-2", "2板"
                else:
                    lb_class, lb_tag = "lb-1", "首板"
                board_tag_html = get_board_tag_html(code)
                stocks_html += f"""<div class="rhythm-item" data-stock="{name}">
                    <div class="stock-block {lb_class}" onclick="openKLineModal('{code}', '{name}')">
                        <span class="name">{name}</span>
                        <span class="lb-tag">{lb_tag}{board_tag_html}</span>
                    </div>
                </div>"""

            ladder_html += f"""<div class="rhythm-date">
                <div class="rhythm-header">{date_label}</div>
                <div class="rhythm-content">{stocks_html}</div>
            </div>"""

    ladder_section = f"""<div class="section">
            <h2 class="section-title">连板天梯</h2>
            <p class="section-desc">近15交易日2板及以上涨停，按日期横向展示</p>
            <div class="rhythm-grid">{ladder_html}</div>
            <div class="legend">
                <span class="item"><span class="dot lb-1"></span>首板</span>
                <span class="item"><span class="dot lb-2"></span>2板</span>
                <span class="item"><span class="dot lb-3"></span>3板+</span>
            </div>
        </div>"""

    # ========== 1.5 连板矩阵表（近6交易日 x 概念）==========
    top20_concept_names = [r['concept_name'] for r in analysis_result['top20_concepts']]
    recent_6_dates = dates_with_ladder[:6] if dates_with_ladder else dates[:6]

    # 构建矩阵：{concept: {date: [(name, concepts, code), ...]}}
    matrix_data = {}
    for concept in top20_concept_names:
        matrix_data[concept] = {}
        for d in recent_6_dates:
            matrix_data[concept][d] = []

    for d in recent_6_dates:
        date_stocks = analysis_result['ladder_data'].get(d, [])
        for name, lb, concepts, hot_rank, code in date_stocks:
            # 找出该股票所属的TOP20概念
            stock_concepts = code_to_concepts.get(code, set())
            for concept in top20_concept_names:
                if concept in concepts or any(top20_names.get(c) == concept for c in stock_concepts):
                    all_concepts = []
                    if df_concept_stock is not None:
                        stock_rows = df_concept_stock[df_concept_stock['股票代码'].astype(str) == code]
                        all_concepts = stock_rows['概念名称'].tolist()[:3]
                    matrix_data[concept][d].append((name, ','.join(all_concepts), code, lb))

    # 生成矩阵HTML
    matrix_html = "<tr><th class='matrix-date'>概念</th>"
    for d in recent_6_dates:
        matrix_html += f"<th class='matrix-date'>{d[4:]}日</th>"
    matrix_html += "</tr>"

    for concept in top20_concept_names:
        matrix_html += f"<tr><td class='matrix-concept'>{concept}</td>"
        for d in recent_6_dates:
            stocks_in_cell = matrix_data[concept].get(d, [])
            cell_content = ""
            for name, concepts_str, code, lb in stocks_in_cell:
                board_tag_html = get_board_tag_html(code, separator='')
                lb_class = "lb-3" if lb >= 3 else ("lb-2" if lb == 2 else "lb-1")
                lb_display = f"({lb}板)" if lb >= 2 else ""
                cell_content += f"<div class='matrix-stock' onclick=\"openKLineModal('{code}', '{name}')\"><span class='{lb_class}'>{name}{lb_display}</span>{board_tag_html}<span class='matrix-concepts'>{concepts_str}</span></div>"
            matrix_html += f"<td class='matrix-cell'>{cell_content}</td>"
        matrix_html += "</tr>"

    matrix_section = f"""<div class="section">
            <h2 class="section-title">连板矩阵</h2>
            <p class="section-desc">近6交易日2板及以上涨停，概念x日期分布</p>
            <table class="matrix-table">{matrix_html}</table>
        </div>"""

    # ========== 2. 今日涨停看板（按概念分组）==========
    today_zt_df = df_zt_pool[df_zt_pool['交易日期'] == today_date_int] if df_zt_pool is not None else pd.DataFrame()
    today_zt_count = len(today_zt_df)

    top20_names = dict(zip(df_hot_concepts['concept_code'].astype(str), df_hot_concepts['concept_name'])) if df_hot_concepts is not None else {}
    code_to_concepts = analysis_result.get('code_to_concepts', {})

    # 按概念分组
    concept_stocks_map = {}  # {concept_name: [(name, code, lianban, zt_count), ...]}
    no_concept_stocks = []

    if not today_zt_df.empty:
        for _, row in today_zt_df.iterrows():
            code = str(row['代码_str'])  # 使用已转换的代码字符串
            name = row['名称']
            lianban = int(row['连板数']) if pd.notna(row['连板数']) else 1
            zt_count_15d = len(df_zt_pool[df_zt_pool['代码_str'] == code]) if df_zt_pool is not None else 1

            stock_concepts = code_to_concepts.get(code, set())
            concept_names = [top20_names.get(c, c) for c in stock_concepts if c in top20_names]

            if concept_names:
                for cn in concept_names[:3]:  # 每个股票最多显示3个概念
                    if cn not in concept_stocks_map:
                        concept_stocks_map[cn] = []
                    concept_stocks_map[cn].append((name, code, lianban, zt_count_15d))
            else:
                no_concept_stocks.append((name, code, lianban, zt_count_15d))

    # 生成HTML - 按概念排序显示
    today_board_items = ""
    # 按概念内股票数排序
    sorted_concepts = sorted(concept_stocks_map.items(), key=lambda x: -len(x[1]))
    for concept_name, stocks in sorted_concepts:
        stock_items = ""
        for name, code, lianban, zt_count in stocks:
            if lianban >= 3:
                lb_class, lb_tag = "lb-3", "3板+"
            elif lianban == 2:
                lb_class, lb_tag = "lb-2", "2板"
            else:
                lb_class, lb_tag = "lb-1", "首板"
            board_tag_html = get_board_tag_html(code)
            stock_items += f"""<div class="today-stock-item" onclick="openKLineModal('{code}', '{name}')">
                <div class="today-stock-name">{name}</div>
                <div class="today-stock-info">
                    <span class="today-lb {lb_class}">{lb_tag}{board_tag_html}</span>
                </div>
            </div>"""
        today_board_items += f"""<div class="today-concept-group">
            <div class="today-concept-name">{concept_name} <span class="today-concept-count">({len(stocks)})</span></div>
            <div class="today-concept-stocks">{stock_items}</div>
        </div>"""

    # 添加无概念股票
    if no_concept_stocks:
        stock_items = ""
        for name, code, lianban, zt_count in no_concept_stocks:
            if lianban >= 3:
                lb_class, lb_tag = "lb-3", "3板+"
            elif lianban == 2:
                lb_class, lb_tag = "lb-2", "2板"
            else:
                lb_class, lb_tag = "lb-1", "首板"
            board_tag_html = get_board_tag_html(code)
            stock_items += f"""<div class="today-stock-item" onclick="openKLineModal('{code}', '{name}')">
                <div class="today-stock-name">{name}</div>
                <div class="today-stock-info">
                    <span class="today-lb {lb_class}">{lb_tag}{board_tag_html}</span>
                </div>
            </div>"""
        today_board_items += f"""<div class="today-concept-group">
            <div class="today-concept-name">其他 <span class="today-concept-count">({len(no_concept_stocks)})</span></div>
            <div class="today-concept-stocks">{stock_items}</div>
        </div>"""

    today_board_section = f"""<div class="section">
            <h2 class="section-title">今日涨停看板</h2>
            <p class="section-desc">{today_date[4:]}日 | 共 {today_zt_count} 只涨停</p>
            <div class="today-board">{today_board_items}</div>
        </div>"""

    # ========== 3. 热门概念板块一览（2列10行，按热度值排序）==========
    df_hot_concepts['hot_value_num'] = pd.to_numeric(df_hot_concepts['hot_value'], errors='coerce')
    concepts_sorted = df_hot_concepts.sort_values('hot_value_num', ascending=False).reset_index(drop=True)
    concepts_html = ""

    # 识别市场主线
    main_themes = []
    for result in analysis_result['top20_concepts']:
        stats = result.get('stats', {})
        today_zt = stats.get('today_zt_count', 0)
        hot_val = float(result['hot_value'] or 0)
        if today_zt >= 2 and hot_val > 5000:
            main_themes.append({
                'name': result['concept_name'],
                'today_zt': today_zt,
                'hot_value': hot_val,
                'max_lianban': stats.get('max_lianban_10d', 0)
            })
    main_themes = sorted(main_themes, key=lambda x: (-x['today_zt'], -x['hot_value']))[:3]

    # 生成主线HTML
    main_themes_html = ""
    if main_themes:
        theme_items = ""
        for mt in main_themes:
            theme_items += f"<span class='main-theme-tag'>{mt['name']}({mt['today_zt']}只)</span>"
        main_themes_html = f"<div class='main-themes'><span class='main-themes-label'>🚀 市场主线：</span>{theme_items}</div>"

    # ========== 市场投资逻辑（从action JSON加载）==========
    action_data_path = os.path.join(DATA_DIR, f"action_{today_date}.json")
    market_logic_html = ""
    if os.path.exists(action_data_path):
        try:
            with open(action_data_path, 'r', encoding='utf-8') as f:
                action_data = json.load(f)
            sectors = action_data.get('sectors', [])
            if sectors:
                sector_cards = ""
                for sector in sectors:
                    theme = sector.get('theme', '')
                    theme_short = theme[:80] + '...' if len(theme) > 80 else theme
                    sector_cards += f"""
                    <div class="market-sector-card">
                        <div class="market-sector-header">
                            <span class="market-sector-name">{sector['name']}</span>
                            <span class="market-sector-count">{sector['count']}只</span>
                        </div>
                        <div class="market-sector-theme">📌 {theme_short}</div>
                    </div>"""
                market_logic_html = f"""
                <div class="market-logic-section">
                    <div class="market-logic-grid">{sector_cards}</div>
                </div>"""
        except Exception as e:
            market_logic_html = f"<p>加载市场逻辑数据失败: {str(e)}</p>"

    for i in range(0, min(20, len(concepts_sorted)), 2):
        row_cells = ""
        for j in range(2):
            if i + j < len(concepts_sorted):
                row = concepts_sorted.iloc[i + j]
                hot_val = float(row['hot_value']) if row['hot_value'] else 0
                row_cells += f"""<div class="concept-card">
                <div class="concept-rank">{(i+j+1)}</div>
                <div class="concept-info">
                    <div class="concept-name">{row['concept_name']}</div>
                    <div class="concept-hot">{hot_val:,.0f}</div>
                </div>
                <div class="concept-tag">{row['hot_tag']}</div>
            </div>"""
            else:
                row_cells += "<div class='concept-card empty'></div>"
        concepts_html += f"<div class='concept-row'>{row_cells}</div>"

    # ========== 4. TOP20概念题材（原始设计：日期+色块）==========
    concept_details = ""
    for result in analysis_result['top20_concepts']:
        if result['stocks'].empty:
            continue

        date_rhythm = result['date_rhythm']

        # 涨停节奏 - 原始设计：日期块 + 股票色块，日期横排
        rhythm_html = ""
        for d in dates:
            stocks_on_date = date_rhythm.get(d, [])
            if stocks_on_date:
                stocks_sorted = sorted(stocks_on_date, key=lambda x: -x[1])
                date_label = f"{d[4:]}日"
                stocks_html = ""
                for name, lb, code, first_seal in stocks_sorted:
                    if lb >= 3:
                        lb_class, lb_tag = "lb-3", "3板+"
                    elif lb == 2:
                        lb_class, lb_tag = "lb-2", "2板"
                    else:
                        lb_class, lb_tag = "lb-1", "首板"
                    board_tag_html = get_board_tag_html(code)
                    stocks_html += f"""<div class="rhythm-item" data-stock="{name}">
                        <div class="stock-block {lb_class}" onclick="openKLineModal('{code}', '{name}')">
                            <span class="name">{name}</span>
                            <span class="lb-tag">{lb_tag}{board_tag_html}</span>
                        </div>
                    </div>"""

                rhythm_html += f"""<div class="rhythm-date">
                    <div class="rhythm-header">{date_label}</div>
                    <div class="rhythm-content">{stocks_html}</div>
                </div>"""

        # 涨停股票列表
        stock_rows = ""
        for _, stock in result['stocks'].iterrows():
            code = format_code(stock['代码'])
            lb = int(stock['最大连板数']) if pd.notna(stock['最大连板数']) else 1
            board_tag_html = get_board_tag_html(code)
            stock_rows += f"""<tr>
                <td class="code">{code}</td>
                <td class="name clickable-name" onclick="openKLineModal('{code}', '{stock['名称']}')">{stock['名称']}{board_tag_html}</td>
                <td class="lianban">{lb}板</td>
                <td class="count">{stock['涨停次数']}次</td>
                <td class="concepts">{stock.get('所属概念', '-')}</td>
            </tr>"""

        # 构建趋势看板数据 (按日期ASC + 首封ASC排序)
        board_stocks = []
        for d in dates:
            stocks_on_date = date_rhythm.get(d, [])
            for name, lb, code, first_seal in stocks_on_date:
                board_stocks.append({
                    'name': name,
                    'code': code,
                    'lianban': lb,
                    'date': d,
                    'first_seal': first_seal,
                    'seal_display': format_seal_time(first_seal)
                })
        board_stocks.sort(key=lambda x: (x['date'], x['first_seal'] or ''))
        board_stocks_json = json.dumps(board_stocks, ensure_ascii=False)

        concept_stats = result.get('stats', {})
        today_zt = concept_stats.get('today_zt_count', 0)
        days_15_zt = concept_stats.get('days_15_zt_count', 0)
        max_lianban = concept_stats.get('max_lianban_10d', 0)
        multiboard = concept_stats.get('multiboard_10d', 0)

        concept_id = result['concept_code'].replace('.', '_')
        concept_details += f"""<div class="concept-accordion">
            <div class="concept-header" onclick="toggleConcept('{concept_id}')">
                <div class="concept-header-left">
                    <span class="concept-name">{result['concept_name']}</span>
                    <span class="concept-hot">热度: {float(result['hot_value'] or 0):,.0f}</span>
                </div>
                <div class="concept-header-stats">
                    <span class="h-stat">今日涨停: <strong>{today_zt}只</strong></span>
                    <span class="h-stat">15日涨停: <strong>{days_15_zt}只</strong></span>
                    <span class="h-stat">最高: <strong>{max_lianban}板</strong></span>
                    <span class="h-stat">多板: <strong>{multiboard}次</strong></span>
                </div>
                <span class="expand-icon" id="icon-{concept_id}">▼</span>
            </div>
            <div class="concept-content" id="concept-content-{concept_id}">
                <div class="rhythm-section">
                    <div class="rhythm-title">涨停节奏</div>
                    <div class="rhythm-grid">{rhythm_html}</div>
                    <div class="legend">
                        <span class="item"><span class="dot lb-1"></span>首板</span>
                        <span class="item"><span class="dot lb-2"></span>2板</span>
                        <span class="item"><span class="dot lb-3"></span>3板+</span>
                    </div>
                </div>
                <div style="padding: 10px 0;">
                    <button class="tab-btn" id="btn-{concept_id}" onclick="toggleTrendBoard('{concept_id}')">📈 查看走势看板</button>
                </div>
                <script type="application/json" id="concept-stocks-{concept_id}">{board_stocks_json}</script>
                <div class="concept-trend-board" id="board-{concept_id}" style="display:none;">
                    <div class="trend-board-header">
                        <h4>📈 {result['concept_name']} 涨停股走势看板（近15日）</h4>
                        <button class="close-btn" onclick="toggleTrendBoard('{concept_id}')">✕</button>
                    </div>
                    <div class="trend-board-grid" id="grid-{concept_id}">
                        <!-- 由 renderTrendBoardCards() 动态渲染 -->
                    </div>
                </div>
                <table class="stock-table">
                    <thead><tr><th>代码</th><th>名称</th><th>连板</th><th>涨停</th><th>概念板块</th></tr></thead>
                    <tbody>{stock_rows}</tbody>
                </table>
            </div>
        </div>"""

    # ========== 5. 非TOP20概念涨停股 ==========
    other_section = ""
    if analysis_result['other_stocks']:
        other_rows = ""
        for stock in analysis_result['other_stocks']:
            concepts_str = ','.join(stock['concepts']) if stock['concepts'] else '-'
            lb = stock.get('lianban', 1)
            if lb >= 3:
                lb_text = "3板+"
            elif lb == 2:
                lb_text = "2板"
            else:
                lb_text = "首板"
            code = format_code(stock['code'])
            other_rows += f"<tr><td>{code}</td><td class='clickable-name' onclick=\"openKLineModal('{code}', '{stock['name']}')\">{stock['name']}</td><td>{stock['date'][4:]}日</td><td>{lb_text}</td><td>{concepts_str}</td></tr>"
        other_section = f"""<div class="section">
            <h2 class="section-title">其他概念涨停股</h2>
            <p class="section-desc">不在TOP20热门板块中的涨停股</p>
            <table class="data-table">
                <thead><tr><th>股票代码</th><th>股票名称</th><th>涨停日期</th><th>连板</th><th>所有概念</th></tr></thead>
                <tbody>{other_rows}</tbody>
            </table>
        </div>"""

    # ========== 6. 未涨停热股 ==========
    not_zt_section = ""
    if analysis_result['not_zt_hot_stocks']:
        not_zt_rows = ""
        for stock in analysis_result['not_zt_hot_stocks']:
            hot_val = float(stock['hot_value']) if isinstance(stock['hot_value'], (int, float)) else 0
            code = format_code(stock['stock_code'])
            not_zt_rows += f"<tr><td>{stock['rank']}</td><td>{code}</td><td class='clickable-name' onclick=\"openKLineModal('{code}', '{stock['short_name']}')\">{stock['short_name']}</td><td>{hot_val:,.0f}</td><td>{stock['pop_tag']}</td></tr>"
        not_zt_section = f"""<div class="section">
            <h2 class="section-title">未涨停热股</h2>
            <p class="section-desc">同花顺热股TOP100中，15日内未涨停的股票</p>
            <table class="data-table">
                <thead><tr><th>排名</th><th>股票代码</th><th>股票名称</th><th>热度值</th><th>人气标签</th></tr></thead>
                <tbody>{not_zt_rows}</tbody>
            </table>
        </div>"""

    # ========== 7. 多概念股票 ==========
    multi_section = ""
    if analysis_result['multi_concept_stocks']:
        multi_rows = ""
        for stock in sorted(analysis_result['multi_concept_stocks'], key=lambda x: x['hot_rank']):
            rank_display = stock['hot_rank'] if stock['hot_rank'] < 999 else '-'
            hot_display = f"{float(stock['hot_value']):,.0f}" if isinstance(stock['hot_value'], (int, float)) and stock['hot_value'] > 0 else '-'
            concepts_str = ','.join(stock['concepts'][:5])
            code = format_code(stock['code'])
            multi_rows += f"<tr><td>{code}</td><td class='clickable-name' onclick=\"openKLineModal('{code}', '{stock['name']}')\">{stock['name']}</td><td>{stock['zt_count']}</td><td>{stock['max_lianban']}</td><td>{rank_display}</td><td>{hot_display}</td><td>{concepts_str}</td></tr>"
        multi_section = f"""<div class="section">
            <h2 class="section-title">多概念股票</h2>
            <p class="section-desc">涵盖TOP20热门板块3个及以上概念的股票</p>
            <table class="data-table">
                <thead><tr><th>股票代码</th><th>股票名称</th><th>涨停次数</th><th>最大连板</th><th>热度排名</th><th>热度值</th><th>涵盖概念</th></tr></thead>
                <tbody>{multi_rows}</tbody>
            </table>
        </div>"""

    total_zt = sum(len(r['stocks']) for r in analysis_result['top20_concepts'])

    # 生成归档下拉选项（用于日期选择器）
    archive_options = ""
    for date in archives:
        if date != today_str:  # 排除今天的归档（就是当前报告）
            display_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            archive_options += f"<option value='{date}'>{display_date}</option>"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="referrer" content="no-referrer">
    <title>热门概念板块涨停股分析报告 V2 - {today}</title>
    <link rel="stylesheet" href="static/css/dashboard.css">
    <style>
        /* Minimal inline styles - main styles moved to static/css/dashboard.css */
        body {{ padding: 30px; }}
        .container {{ padding: 30px; }}
        .header-controls {{ margin: 15px 0; }}
        #archive-select {{ padding: 8px 12px; font-size: 0.95em; border: 1px solid #e2e8f0; border-radius: 6px; background: #fff; color: #2d3748; cursor: pointer; min-width: 180px; }}
        #archive-select:hover {{ border-color: #4299e1; }}
        .stats {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 15px; margin-bottom: 30px; }}
        .stat-card {{ background: #f7fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px; text-align: center; }}
        .stat-value {{ font-size: 2em; font-weight: bold; color: #2b6cb0; }}
        .stat-label {{ color: #718096; font-size: 0.9em; margin-top: 5px; }}
        .section-title {{ font-size: 1.4em; color: #2d3748; margin: 30px 0 15px; padding-left: 12px; border-left: 4px solid #4299e1; font-weight: 600; }}
        .section-desc {{ color: #718096; font-size: 0.9em; margin-bottom: 15px; }}
        .concept-section {{ border: 1px solid #e2e8f0; border-radius: 10px; margin: 15px 0; padding: 20px; }}
        .concept-title {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #e2e8f0; }}
        .concept-title .name {{ font-size: 1.3em; color: #2b6cb0; font-weight: 600; }}
    </style>
    <script src="static/js/app.js"></script>
</head>
<body>
    <!-- 侧边栏折叠按钮 -->
    <button class="sidebar-toggle" onclick="toggleSidebar()">◀</button>
    <!-- 左侧导航栏 -->
    <nav class="sidebar">
        <div class="sidebar-header">
            <h1>股票分析报告</h1>
            <div class="sidebar-date">{today}</div>
            <div class="sidebar-date-selector">
                <select id="report-date-select" onchange="switchReport(this.value)">
                    <option value="latest">最新报告</option>
                    {archive_options}
                </select>
            </div>
        </div>
        <ul class="nav-list">
            <!-- 主导航 Tab -->
            <li class="nav-header">📈 股票走势分析</li>
            <li class="nav-item">
                <a href="#" class="nav-link active" data-section="trend">
                    <span class="nav-icon">📊</span>
                    <span>概览</span>
                </a>
            </li>
            <li class="nav-divider"></li>
            <!-- Tab 2: 概念深度 -->
            <li class="nav-header">🔍 概念深度分析</li>
            <li class="nav-item">
                <a href="#" class="nav-link" data-section="concept-detail">
                    <span class="nav-icon">📋</span>
                    <span>概念详情</span>
                </a>
            </li>
            <li class="nav-divider"></li>
            <!-- Tab 3: 投资舆情 -->
            <li class="nav-header">📰 投资舆情</li>
            <li class="nav-item">
                <a href="#" class="nav-link" data-section="sentiment">
                    <span class="nav-icon">🔥</span>
                    <span>异动监控</span>
                </a>
            </li>
        </ul>
        <div class="sidebar-footer">
            {dates[-1]} ~ {dates[0]}
        </div>
    </nav>

    <!-- 主体内容区 -->
    <div class="main-content">
    <div class="container">
        <!-- ========== Tab 1: 股票走势分析 ========== -->
        <section id="section-trend" class="page-section active">
            <div class="tab-header">
                <h1>📈 股票走势分析</h1>
            </div>

            <!-- 总览统计 -->
            <div class="header">
                <div class="header-controls">
                    <select id="archive-select" onchange="loadArchive(this.value)">
                        <option value="">选择查看归档...</option>
                        <option value="report_latest.html" selected>最新报告</option>
                        {archive_options}
                    </select>
                    <button class="global-update-btn" onclick="updateAllData()">🔄 全部更新</button>
                </div>
                <div id="global-update-status" class="jianxi-update-status" style="display: none;"></div>
                <div class="subtitle">{today} | 分析时段: {dates[-1]} 至 {dates[0]}</div>
            </div>

            <div class="stats">
                <div class="stat-card"><div class="stat-value">{len(analysis_result['top20_concepts'])}</div><div class="stat-label">热门概念板块</div></div>
                <div class="stat-card"><div class="stat-value">{total_zt}</div><div class="stat-label">TOP20涨停股</div></div>
                <div class="stat-card"><div class="stat-value">{len(analysis_result['other_stocks'])}</div><div class="stat-label">其他概念涨停</div></div>
                <div class="stat-card"><div class="stat-value">{len(analysis_result['not_zt_hot_stocks'])}</div><div class="stat-label">未涨停热股</div></div>
                <div class="stat-card"><div class="stat-value">{today_zt_count}</div><div class="stat-label">今日涨停</div></div>
            </div>

            <!-- 连板天梯 -->
            <div class="section-block" id="block-ladder">
                <h2 class="section-title">🏆 连板天梯</h2>
                <p class="section-desc">查看近15日2板及以上涨停</p>
                {ladder_section}
            </div>

            <!-- 连板矩阵 -->
            <div class="section-block" id="block-matrix">
                <h2 class="section-title">📈 连板矩阵</h2>
                <p class="section-desc">概念x日期分布</p>
                {matrix_section}
            </div>

            <!-- 今日涨停看板 -->
            <div class="section-block" id="block-today">
                <h2 class="section-title">⚡ 今日涨停</h2>
                <p class="section-desc">查看今日涨停详情</p>
                {today_board_section}
            </div>

            <!-- 热门概念板块一览 -->
            <div class="section-block" id="block-concepts">
                <h2 class="section-title">🔥 热门概念板块一览</h2>
                {main_themes_html}
                <div class="concept-grid">
                    {concepts_html}
                </div>
            </div>

            <!-- 市场投资逻辑 -->
            <div class="section-block" id="block-market-logic">
                <h2 class="section-title">🧠 市场投资逻辑</h2>
                <p class="section-desc">韭研公社异动板块题材解析</p>
                {market_logic_html}
            </div>

            <div class="footer">
                <p>报告由股票分析系统自动生成 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
        </section>

        <!-- ========== Tab 2: 概念深度分析 ========== -->
        <section id="section-concept-detail" class="page-section">
            <div class="tab-header">
                <h1>🔍 概念深度分析</h1>
            </div>

            <!-- TOP20概念题材 -->
            <div class="section-block" id="block-details">
                <h2 class="section-title">📋 TOP20概念题材</h2>
                <p class="section-desc">点击展开各概念详情 | 按热度值排序</p>
                {concept_details}
            </div>

            <!-- 其他概念涨停股 -->
            <div class="section-block" id="block-other">
                <h2 class="section-title">📦 其他概念涨停股</h2>
                {other_section}
            </div>

            <!-- 未涨停热股 -->
            <div class="section-block" id="block-notzt">
                <h2 class="section-title">❄️ 未涨停热股</h2>
                {not_zt_section}
            </div>

            <!-- 多概念股票 -->
            <div class="section-block" id="block-multi">
                <h2 class="section-title">🎯 多概念股票</h2>
                {multi_section}
            </div>
        </section>

        <!-- ========== Tab 3: 投资舆情 ========== -->
        <section id="section-sentiment" class="page-section">
            <div class="tab-header">
                <h1>📰 投资舆情分析</h1>
            </div>

            <div class="sentiment-section">
                <h2 class="section-title">🔥 涨停简图</h2>
                <p class="section-desc">韭研公社全天涨停简图 - 识别市场主线热点</p>

                <!-- 涨停简图展示区 -->
                <div class="jianxi-container">
                    <div class="jianxi-controls">
                        <select id="jianxi-date" class="jianxi-date-select">
                            <option value="2026-04-10" selected>04月10日</option>
                        </select>
                        <button id="jianxi-update-btn" class="jianxi-update-btn" onclick="updateJianxiData()">
                            📥 更新数据
                        </button>
                        <button id="jianxi-analyze-btn" class="jianxi-analyze-btn" onclick="analyzeJianxi()">
                            🤖 AI分析
                        </button>
                        <button id="jianxi-refresh-btn" class="jianxi-refresh-btn" onclick="refreshJianxi()">
                            🔄 刷新
                        </button>
                    </div>
                    <div id="jianxi-update-status" class="jianxi-update-status" style="display: none;"></div>
                    <div class="jianxi-image-wrapper">
                        <img id="jianxi-image" class="jianxi-image"
                             src=""
                             alt="涨停简图加载中..."
                             onload="onJianxiLoad()"
                             onerror="onJianxiError()">
                        <div id="jianxi-loading" class="jianxi-loading">
                            <div class="loading-spinner"></div>
                            <span>加载中...</span>
                        </div>
                    </div>
                </div>

                <!-- 全部异动解析区 -->
                <div class="action-list-section">
                    <div class="action-list-header">
                        <h3 class="section-title">📋 全部异动解析</h3>
                        <button id="action-fetch-btn" class="jianxi-update-btn" onclick="fetchActionList()">
                            🌐 从韭研公社获取
                        </button>
                    </div>
                    <div id="action-list-status" class="jianxi-update-status" style="display: none;"></div>
                    <div id="action-list-content" class="action-list-content">
                        <p class="action-list-hint">点击上方按钮从韭研公社获取当日异动解析数据</p>
                    </div>
                </div>

                <!-- AI分析结果区 -->
                <div id="jianxi-result" class="jianxi-result" style="display: none;">
                    <h3 class="result-title">📊 AI分析结果</h3>
                    <div id="jianxi-tree" class="jianxi-tree"></div>
                    <div id="jianxi-summary" class="jianxi-summary"></div>
                </div>

                <!-- 原始iframe (可选) -->
                <details class="iframe-original">
                    <summary>📱 打开韭研公社原站（需登录）</summary>
                    <div class="iframe-container">
                        <iframe
                            src="https://www.jiuyangongshe.com/action"
                            class="sentiment-iframe"
                            frameborder="0"
                            allow="accelerometer; clipboard-read; clipboard-write; geolocation; microphone; autoplay"
                            allowfullscreen
                            sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox"
                        ></iframe>
                    </div>
                </details>

                <!-- 产业库 -->
                <div class="section-block" id="block-industry">
                    <div class="section-header-row">
                        <h3 class="section-title">🏭 产业库</h3>
                        <div class="section-actions">
                            <button class="jianxi-update-btn" onclick="fetchIndustryList()">📥 获取数据</button>
                            <a href="https://www.jiuyangongshe.com/industryChain" target="_blank" class="jianxi-update-btn">🔗 韭研公社</a>
                        </div>
                    </div>
                    <p class="section-desc">按热度排序的产业主题</p>
                    <div id="industry-list-status" class="jianxi-update-status" style="display: none;"></div>
                    <div id="industry-list-content" class="industry-list-content">
                        <p class="action-list-hint">点击"获取数据"按钮加载产业库</p>
                    </div>
                </div>

                <!-- 时间轴 -->
                <div class="section-block" id="block-timeline">
                    <div class="section-header-row">
                        <h3 class="section-title">📅 时间轴</h3>
                        <div class="section-actions">
                            <button class="jianxi-update-btn" onclick="fetchTimelineList()">📥 获取数据</button>
                            <a href="https://www.jiuyangongshe.com/timeline" target="_blank" class="jianxi-update-btn">🔗 韭研公社</a>
                        </div>
                    </div>
                    <p class="section-desc">每日重要事件时间轴</p>
                    <div id="timeline-list-status" class="jianxi-update-status" style="display: none;"></div>
                    <div id="timeline-list-content" class="timeline-list-content">
                        <p class="action-list-hint">点击"获取数据"按钮加载时间轴</p>
                    </div>
                </div>
            </div>
        </section>

    </div>
    </div>

    <!-- K线图弹窗 -->
    <div id="kline-modal" class="modal-overlay" onclick="closeKLineModal()">
        <div class="modal-content" onclick="event.stopPropagation()">
            <div class="modal-header">
                <h3 id="kline-title">股票名称</h3>
                <span class="close-btn" onclick="closeKLineModal()">&times;</span>
            </div>
            <div class="modal-tabs">
                <button class="tab-btn active" onclick="switchKLineTab('min', this)">分时</button>
                <button class="tab-btn" onclick="switchKLineTab('daily', this)">日K</button>
                <button class="tab-btn" onclick="switchKLineTab('weekly', this)">周K</button>
                <button class="tab-btn" onclick="switchKLineTab('monthly', this)">月K</button>
            </div>
            <div class="modal-body">
                <img id="kline-img" src="" alt="K线图加载中...">
            </div>
        </div>
    </div>
</body>
</html>"""

    return html


def save_report(markdown_content, html_content, dates):
    """保存报告并归档"""
    today = datetime.now().strftime('%Y%m%d')

    # 确保目录存在
    os.makedirs(REPORTS_DIR, exist_ok=True)

    # 保存到 reports/YYYYMMDD/ 目录
    report_date_dir = os.path.join(REPORTS_DIR, today)
    os.makedirs(report_date_dir, exist_ok=True)

    md_file = os.path.join(report_date_dir, "report.md")
    html_file = os.path.join(report_date_dir, "report.html")

    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(markdown_content)
    print(f"  ✓ Markdown报告: {md_file}")

    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"  ✓ HTML报告: {html_file}")

    # 最新报告（兼容旧链接）
    latest_md = os.path.join(SCRIPT_DIR, "report_latest.md")
    latest_html = os.path.join(SCRIPT_DIR, "report_latest.html")

    with open(latest_md, 'w', encoding='utf-8') as f:
        f.write(markdown_content)
    with open(latest_html, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"  ✓ 最新报告已更新")

    # 生成索引页面
    archives = get_available_archives()
    _generate_index_page(archives)

    return archives


def get_available_archives():
    """获取可用的归档列表"""
    archives = []
    if os.path.exists(REPORTS_DIR):
        for d in os.listdir(REPORTS_DIR):
            date_dir = os.path.join(REPORTS_DIR, d)
            if os.path.isdir(date_dir) and d.isdigit() and len(d) == 8:
                archives.append(d)
    archives.sort(reverse=True)
    return archives


def _generate_index_page(archives):
    """生成归档索引页面"""
    today = datetime.now().strftime('%Y年%m月%d日')

    # 构建报告列表
    reports = [{'date': '最新报告', 'file': 'report_latest.html'}]
    for date in archives:
        display_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        reports.append({'date': display_date, 'file': f'{date}/report.html'})

    report_items = ""
    for r in reports:
        report_items += f"""<li class="report-item">
            <a href="{r['file']}" class="report-link">
                <span class="report-date">{r['date']}</span>
                <span class="report-arrow">→</span>
            </a>
        </li>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>股票分析报告</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f6fa; color: #2d3748; padding: 40px; }}
        .container {{ max-width: 800px; margin: 0 auto; background: #fff; border-radius: 12px; padding: 40px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        h1 {{ font-size: 1.8em; color: #1a365d; margin-bottom: 30px; text-align: center; }}
        .report-list {{ list-style: none; }}
        .report-item {{ margin-bottom: 10px; }}
        .report-link {{ display: flex; justify-content: space-between; align-items: center; padding: 15px 20px; background: #f7fafc; border: 1px solid #e2e8f0; border-radius: 8px; text-decoration: none; color: #2d3748; transition: all 0.2s; }}
        .report-link:hover {{ background: #edf2f7; border-color: #4299e1; transform: translateX(5px); }}
        .report-date {{ font-weight: 600; }}
        .report-arrow {{ color: #4299e1; font-size: 1.2em; }}
        .footer {{ text-align: center; margin-top: 30px; color: #a0aec0; font-size: 0.9em; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>股票分析报告</h1>
        <ul class="report-list">
            {report_items}
        </ul>
        <div class="footer">
            <p>生成时间: {today}</p>
        </div>
    </div>
</body>
</html>"""

    index_path = os.path.join(REPORTS_DIR, "index.html")
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  ✓ 报告索引页已更新: {index_path}")


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("股票分析报告看板 V2")
    print("=" * 60)

    # Step 1: 获取数据
    print("\n--- Step 1: 获取数据 ---")

    df_hot_concepts = get_hot_concepts()
    df_hot_stocks = get_hot_stocks()

    # 获取近15个交易日
    dates = get_trading_dates_2026(15)
    print(f"  交易日历: {dates[-1]} 至 {dates[0]}")

    # 检查是否需要自动更新今日涨停数据
    auto_update, today_str = should_auto_update_zt()
    df_zt_pool = get_zt_pool(dates, force_refresh_today=auto_update, today_str=today_str)

    # 概念股票数据使用缓存（不自动更新，需手动触发 update_data.py --concepts）
    df_concept_stock = load_concept_stock_list()

    # Step 2: 分析数据
    print("\n--- Step 2: 分析数据 ---")
    analysis_result = analyze_concept_stocks(
        df_hot_concepts, df_concept_stock, df_zt_pool, df_hot_stocks, dates
    )
    print(f"  ✓ TOP20概念板块: {len(analysis_result['top20_concepts'])}")
    print(f"  ✓ 其他概念涨停股: {len(analysis_result['other_stocks'])}")
    print(f"  ✓ 未涨停热股: {len(analysis_result['not_zt_hot_stocks'])}")
    print(f"  ✓ 多概念股票: {len(analysis_result['multi_concept_stocks'])}")

    # Step 3: 生成报告
    print("\n--- Step 3: 生成报告 ---")

    # 获取现有归档列表
    archives = get_available_archives()

    markdown_content = generate_markdown(analysis_result, df_hot_concepts, df_zt_pool, dates, df_concept_stock)
    html_content = generate_html(analysis_result, df_hot_concepts, df_zt_pool, dates, df_concept_stock, archives)

    archives = save_report(markdown_content, html_content, dates)
    print(f"  ✓ 共有 {len(archives)} 个归档文件")

    print("\n" + "=" * 60)
    print("处理完成!")
    print("=" * 60)
    print("\n功能说明:")
    print("  • 15日涨停板: 缓存机制，缺失日期才获取")
    print("  • 其他概念: 不在TOP20的涨停股")
    print("  • 未涨停热股: TOP100中15日未涨停")
    print("  • 多概念股票: 涵盖3+TOP20概念的股票")
    print("  • 今日涨停看板: 连板天梯后显示今日涨停")
    print("=" * 60)


if __name__ == "__main__":
    main()