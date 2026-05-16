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
import math
import glob
import argparse

warnings.filterwarnings('ignore')

# 获取当前脚本所在目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 数据目录结构
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
ZT_POOL_DIR = os.path.join(DATA_DIR, "zt_pool")
HOT_DIR = os.path.join(DATA_DIR, "hot")  # 统一热点数据目录
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports")
ARCHIVE_DIR = os.path.join(SCRIPT_DIR, "archive")
CACHE_DIR = os.path.join(SCRIPT_DIR, "cache")

# 确保目录存在
for d in [ZT_POOL_DIR, HOT_DIR, REPORTS_DIR, CACHE_DIR]:
    os.makedirs(d, exist_ok=True)

# 概念股票列表（data目录下）
CONCEPT_STOCK_FILE = os.path.join(SCRIPT_DIR, "data", "ths_concept_stock_list.csv")

# 概念-股票映射目录（三个平台）
CONCEPT_STOCK_DIR = os.path.join(SCRIPT_DIR, "data", "concept_stock")
CLS_CONCEPT_FILE = os.path.join(CONCEPT_STOCK_DIR, "cls_concept_stock.json")
KPL_CONCEPT_FILE = os.path.join(CONCEPT_STOCK_DIR, "kpl_concept_stock.json")
THS_CONCEPT_FILE = os.path.join(CONCEPT_STOCK_DIR, "ths_concept_stock.json")

# 北京时间（UTC+8）
BEIJING_TZ = timezone(timedelta(hours=8))


def get_today_str():
    """获取今天的日期字符串 YYYYMMDD（北京时间）"""
    return get_beijing_now().strftime('%Y%m%d')


def get_beijing_now():
    """获取当前北京时间（假设系统时间已设为北京时区）"""
    return datetime.now()


def is_trading_day(date_str=None):
    """检查指定日期是否为A股交易日

    Args:
        date_str: 日期字符串 YYYYMMDD，默认为今天（北京时间）

    Returns:
        bool: 是否为交易日
    """
    if date_str is None:
        date_str = get_beijing_now().strftime('%Y%m%d')

    # 1. 尝试从本地缓存读取
    cache_file = os.path.join(DATA_DIR, 'trade_calendar_2026.json')
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                trading_dates = json.load(f)
            trading_dates = set([d.replace('-', '') for d in trading_dates])
            return date_str in trading_dates
        except Exception:
            pass

    # 2. 尝试从API获取
    try:
        year = int(date_str[:4])
        df = adata.stock.info.trade_calendar(year=year)
        df_trading = df[df['trade_status'] == 1]
        trading_dates = set(df_trading['trade_date'].astype(str).tolist())
        # 保存到本地缓存
        with open(cache_file, 'w') as f:
            json.dump(df_trading['trade_date'].astype(str).tolist(), f)
        return date_str in trading_dates
    except Exception as e:
        print(f"  ⚠ 获取交易日历失败: {e}，使用工作日判断")
        # 3. 备用：工作日判断（不含节假日）
        try:
            dt = datetime.strptime(date_str, '%Y%m%d')
            return dt.weekday() < 5
        except:
            return False


def get_latest_JYGS_ZT_image(static_path="static"):
    """获取最新的韭研公社涨停简图

    Returns:
        tuple: (image_path, image_date) or (None, None) if no image found
    """
    JYGS_ZT_dir = "data/JYGS_ZT"
    if not os.path.exists(JYGS_ZT_dir):
        return None, None

    # 找到所有png文件
    png_files = glob.glob(os.path.join(JYGS_ZT_dir, "*.png"))
    if not png_files:
        return None, None

    # 按文件名（日期）排序，找到最新的
    png_files.sort(key=lambda x: os.path.basename(x), reverse=True)
    latest_file = png_files[0]
    date_str = os.path.basename(latest_file).replace('.png', '')

    # 根据static_path确定图片路径
    # static_path="static" (最新报告在根目录): 图片在 data/JYGS_ZT/ -> "data/JYGS_ZT/"
    # static_path="../../static" (归档报告在reports/YYYYMMDD/): 图片在 ../../../data/JYGS_ZT/
    if static_path == "static":
        image_path = "data/JYGS_ZT/" + date_str + ".png"
    else:
        image_path = "../../../data/JYGS_ZT/" + date_str + ".png"

    return image_path, date_str


def should_auto_update_zt(target_date=None):
    """判断是否应自动更新今日涨停数据

    规则：
    1. 目标日期为A股交易日
    2. 当前北京时间在盘中（9:25后）或收盘后

    Args:
        target_date: 目标日期字符串 YYYYMMDD，默认为今天（北京时间）

    Returns:
        (bool, str): (是否需要更新, 目标日期字符串YYYYMMDD)
    """
    beijing_now = get_beijing_now()
    if target_date is None:
        today_str = beijing_now.strftime('%Y%m%d')
    else:
        today_str = target_date
    hour, minute = beijing_now.hour, beijing_now.minute
    time_str = f"{hour:02d}:{minute:02d}"

    # 检查目标日期是否为交易日
    if not is_trading_day(today_str):
        print(f"  ℹ {today_str}非交易日，使用缓存数据")
        return False, today_str

    # 盘前（9:25之前）不更新
    if hour < 9 or (hour == 9 and minute < 25):
        print(f"  ℹ {today_str}为交易日，尚未开盘(北京时间{time_str})，使用缓存数据")
        return False, today_str
    
    # 盘中或收盘后 → 自动更新
    if hour < 15 or (hour == 15 and minute == 0):
        status = "盘中"
    else:
        status = "收盘后"
    
    print(f"  ★ 今日({today_str})为交易日，当前{status}(北京时间{time_str})，将自动更新涨停数据")
    return True, today_str


def get_trading_dates_2026(days=15):
    """获取近N个交易日期（从今天往前数，优先使用本地缓存）"""
    today_str = get_beijing_now().strftime('%Y%m%d')

    # 1. 尝试从本地缓存读取
    cache_file = os.path.join(DATA_DIR, 'trade_calendar_2026.json')
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                trading_dates = json.load(f)
            trading_dates = [d.replace('-', '') for d in trading_dates]
            # 只取今天及之前的日期，并反转（从最新开始）
            trading_dates = [d for d in trading_dates if d <= today_str][::-1]
            if len(trading_dates) >= days:
                return trading_dates[:days]
            return trading_dates
        except Exception:
            pass

    # 2. 尝试从API获取
    try:
        df = adata.stock.info.trade_calendar(year=2026)
        df_trading = df[df['trade_status'] == 1]
        trading_dates = df_trading['trade_date'].astype(str).tolist()
        trading_dates = [d.replace('-', '') for d in trading_dates]
        # 只取今天及之前的日期，并反转（从最新开始）
        trading_dates = [d for d in trading_dates if d <= today_str][::-1]
        # 保存到本地缓存（保存原始顺序）
        cache_data = [d for d in df_trading['trade_date'].astype(str).tolist()]
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f)
        return trading_dates[:days] if len(trading_dates) >= days else trading_dates
    except Exception as e:
        print(f"  获取2026年交易日历失败: {e}，使用备用逻辑")
        # 3. 备用逻辑
        dates = []
        current = datetime.now()
        while len(dates) < days:
            if current.weekday() < 5:
                dates.append(current.strftime('%Y%m%d'))
            current -= timedelta(days=1)
        return dates


def get_actual_latest_date(dates):
    """获取实际最新的日期（考虑当前时间是否开盘）
    如果当前时间在9:25之前，返回dates[0]（已修正为实际数据的最新日期）
    """
    beijing_now = get_beijing_now()
    today_str = beijing_now.strftime('%Y%m%d')
    hour, minute = beijing_now.hour, beijing_now.minute

    # dates已经是实际数据日期列表，dates[0]是最新日期
    return dates[0] if dates else today_str


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
                    # 用文件名日期覆盖交易日期，确保一致性
                    df['交易日期'] = int(date)
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


def get_zt_pool(dates, force_refresh_today=False, today_str=None, skip_fetch=False):
    """
    获取涨停股池 - 从分日期文件加载

    Args:
        dates: 需要获取的日期列表
        force_refresh_today: 是否强制刷新今日数据（交易日盘中/收盘后）
        today_str: 今日日期字符串（用于强制刷新判断）
        skip_fetch: 是否跳过获取缺失数据（市场未开盘时为True）
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

    # 如果市场未开盘，跳过获取缺失数据
    if skip_fetch and missing_dates:
        print(f"  ℹ 市场未开盘，跳过获取 {len(missing_dates)} 个缺失日期")

    # 获取缺失的数据
    all_data = []
    if df_existing is not None:
        all_data.append(df_existing)

    if not skip_fetch:
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
        # 保存到统一热点目录
        file_path = os.path.join(HOT_DIR, "hot_concepts_latest.csv")
        df.to_csv(file_path, index=False, encoding='utf-8-sig')
        print(f"  ✓ 获取 {len(df)} 个热门概念 (已保存)")
        return df
    except Exception as e:
        print(f"  ⚠ 获取概念失败: {e}，尝试加载缓存...")
        # 尝试加载缓存
        file_path = os.path.join(HOT_DIR, "hot_concepts_latest.csv")
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
        # 保存到统一热点目录
        file_path = os.path.join(HOT_DIR, "hot_stocks_latest.csv")
        df.to_csv(file_path, index=False, encoding='utf-8-sig')
        print(f"  ✓ 获取 {len(df)} 只热门股 (已保存)")
        return df
    except Exception as e:
        print(f"  ⚠ 获取热股失败: {e}，尝试加载缓存...")
        # 尝试加载缓存
        file_path = os.path.join(HOT_DIR, "hot_stocks_latest.csv")
        if os.path.exists(file_path):
            df = pd.read_csv(file_path)
            print(f"  ✓ 加载缓存 {len(df)} 只热门股")
            return df
        return None


def integrate_hot_data(df_hot_concepts, df_hot_stocks, df_concept_stock):
    """整合热门概念和热门股票到结构化JSON

    Args:
        df_hot_concepts: 热门概念 DataFrame
        df_hot_stocks: 热门股票 DataFrame
        df_concept_stock: 概念股票映射 DataFrame

    Returns:
        dict: 整合后的结构化数据
    """
    print("整合热点数据...")

    # 获取TOP20概念代码集合
    top20_codes = set(df_hot_concepts['concept_code'].astype(str).tolist())

    # 建立股票代码到概念的映射
    stock_to_concepts = {}
    if df_concept_stock is not None:
        for _, row in df_concept_stock.iterrows():
            code = str(row['股票代码']).zfill(6)
            concept_code = str(row['概念代码'])
            if code not in stock_to_concepts:
                stock_to_concepts[code] = set()
            if concept_code in top20_codes:
                stock_to_concepts[code].add(concept_code)

    # 构建结果结构
    result = {
        "date": get_today_str(),
        "generated_at": datetime.now().strftime("%H:%M:%S"),
        "concept_count": len(df_hot_concepts),
        "stock_count": len(df_hot_stocks),
        "concepts": [],  # 每个概念及其分类的股票
        "unclassified_stocks": []  # 未分类到TOP20的股票
    }

    # 按热度值排序概念
    df_sorted = df_hot_concepts.copy()
    df_sorted['hot_value_num'] = pd.to_numeric(df_sorted['hot_value'], errors='coerce')
    df_sorted = df_sorted.sort_values('hot_value_num', ascending=False).reset_index(drop=True)

    # 处理每个概念
    for _, concept_row in df_sorted.iterrows():
        concept_code = str(concept_row['concept_code'])

        # 找出属于该概念的股票
        stocks_in_concept = []
        for _, stock_row in df_hot_stocks.iterrows():
            code = str(stock_row['stock_code']).zfill(6)
            if code in stock_to_concepts and concept_code in stock_to_concepts[code]:
                stocks_in_concept.append({
                    "code": code,
                    "name": str(stock_row['short_name']),
                    "rank": int(stock_row['rank']),
                    "hot_value": float(stock_row['hot_value']),
                    "change_pct": float(stock_row['change_pct']) if pd.notna(stock_row['change_pct']) else 0.0,
                    "pop_tag": str(stock_row['pop_tag']) if pd.notna(stock_row['pop_tag']) else ""
                })

        # 按热度排名排序
        stocks_in_concept.sort(key=lambda x: x['rank'])

        result["concepts"].append({
            "code": concept_code,
            "name": str(concept_row['concept_name']),
            "hot_value": float(concept_row['hot_value']),
            "change_pct": float(concept_row['change_pct']) if pd.notna(concept_row['change_pct']) else 0.0,
            "hot_tag": str(concept_row['hot_tag']) if pd.notna(concept_row['hot_tag']) else "",
            "stock_count": len(stocks_in_concept),
            "stocks": stocks_in_concept
        })

    # 处理未分类到TOP20的股票
    classified_codes = set()
    for concept_data in result["concepts"]:
        for stock in concept_data["stocks"]:
            classified_codes.add(stock["code"])

    for _, stock_row in df_hot_stocks.iterrows():
        code = str(stock_row['stock_code']).zfill(6)
        if code not in classified_codes:
            result["unclassified_stocks"].append({
                "code": code,
                "name": str(stock_row['short_name']),
                "rank": int(stock_row['rank']),
                "hot_value": float(stock_row['hot_value']),
                "change_pct": float(stock_row['change_pct']) if pd.notna(stock_row['change_pct']) else 0.0,
                "pop_tag": str(stock_row['pop_tag']) if pd.notna(stock_row['pop_tag']) else "",
                "concept_tag": str(stock_row['concept_tag']) if pd.notna(stock_row['concept_tag']) else ""
            })

    # 保存到JSON文件
    output_path = os.path.join(HOT_DIR, "hot_data_combined.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  ✓ 整合数据已保存: {output_path}")

    return result


def load_concept_stock_list():
    """加载概念与股票对应关系"""
    if os.path.exists(CONCEPT_STOCK_FILE):
        print("加载概念股票对应关系...")
        df = pd.read_csv(CONCEPT_STOCK_FILE)
        print(f"  ✓ 加载 {len(df)} 条记录")
        return df
    print("  ✗ 概念股票文件不存在")
    return None


def load_all_concept_data():
    """加载三个平台的概念-股票映射数据

    Returns:
        dict: {
            'cls': {'forward': {...}, 'reverse': {...}},
            'kpl': {'forward': {...}},  # 开盘啦只有forward
            'ths': {'forward': {...}, 'reverse': {...}}
        }
    """
    print("加载三个平台概念数据...")
    result = {}

    # 财联社
    if os.path.exists(CLS_CONCEPT_FILE):
        try:
            with open(CLS_CONCEPT_FILE, 'r', encoding='utf-8') as f:
                result['cls'] = json.load(f)
            print(f"  ✓ 财联社概念: {len(result['cls'].get('forward', {}))} 个主概念")
        except Exception as e:
            print(f"  ⚠ 财联社概念加载失败: {e}")
            result['cls'] = {'forward': {}, 'reverse': {}}
    else:
        print(f"  ℹ 财联社概念文件不存在: {CLS_CONCEPT_FILE}")
        result['cls'] = {'forward': {}, 'reverse': {}}

    # 开盘啦
    if os.path.exists(KPL_CONCEPT_FILE):
        try:
            with open(KPL_CONCEPT_FILE, 'r', encoding='utf-8') as f:
                result['kpl'] = json.load(f)
            print(f"  ✓ 开盘啦概念: {len(result['kpl'].get('forward', {}))} 个主概念")
        except Exception as e:
            print(f"  ⚠ 开盘啦概念加载失败: {e}")
            result['kpl'] = {'forward': {}}
    else:
        print(f"  ℹ 开盘啦概念文件不存在: {KPL_CONCEPT_FILE}")
        result['kpl'] = {'forward': {}}

    # 同花顺
    if os.path.exists(THS_CONCEPT_FILE):
        try:
            with open(THS_CONCEPT_FILE, 'r', encoding='utf-8') as f:
                result['ths'] = json.load(f)
            print(f"  ✓ 同花顺概念: {len(result['ths'].get('forward', {}))} 个主概念")
        except Exception as e:
            print(f"  ⚠ 同花顺概念加载失败: {e}")
            result['ths'] = {'forward': {}, 'reverse': {}}
    else:
        print(f"  ℹ 同花顺概念文件不存在: {THS_CONCEPT_FILE}")
        result['ths'] = {'forward': {}, 'reverse': {}}

    return result


def build_stock_to_concepts_index(concept_data):
    """构建股票名称到概念的索引

    Args:
        concept_data: load_all_concept_data() 返回的数据

    Returns:
        dict: {
            'stock_name': {
                'cls': ['概念1', '概念2', ...],  # 财联社概念列表
                'kpl': [{'concept': '主概念', 'sub': ['细分1', '细分2']}, ...],  # 开盘啦概念
                'ths': [['概念1', '细分1'], ['概念2', '细分2'], ...]  # 同花顺概念
            },
            ...
        }
    """
    print("构建股票→概念索引...")
    stock_to_concepts = {}

    # 财联社 - 使用reverse映射
    cls_reverse = concept_data.get('cls', {}).get('reverse', {})
    for stock_name, concepts in cls_reverse.items():
        if stock_name not in stock_to_concepts:
            stock_to_concepts[stock_name] = {'cls': [], 'kpl': [], 'ths': []}
        stock_to_concepts[stock_name]['cls'] = concepts if isinstance(concepts, list) else [concepts]

    # 开盘啦 - 遍历forward构建索引
    kpl_forward = concept_data.get('kpl', {}).get('forward', {})
    for main_concept, sub_data in kpl_forward.items():
        if isinstance(sub_data, dict):
            # 子概念结构: {主概念::细分: [stocks], ...}
            for sub_concept, stocks in sub_data.items():
                for stock in stocks:
                    if isinstance(stock, dict):
                        stock_name = stock.get('name', '')
                    else:
                        stock_name = stock
                    if stock_name:
                        if stock_name not in stock_to_concepts:
                            stock_to_concepts[stock_name] = {'cls': [], 'kpl': [], 'ths': []}
                        # 找到该股票已有的kpl概念
                        existing = stock_to_concepts[stock_name]['kpl']
                        # 检查是否已有该主概念
                        found = False
                        for item in existing:
                            if item['concept'] == main_concept:
                                if sub_concept not in item['sub']:
                                    item['sub'].append(sub_concept)
                                found = True
                                break
                        if not found:
                            existing.append({'concept': main_concept, 'sub': [sub_concept]})
        elif isinstance(sub_data, list):
            # 直接是股票列表
            for stock in sub_data:
                if isinstance(stock, dict):
                    stock_name = stock.get('name', '')
                else:
                    stock_name = stock
                if stock_name:
                    if stock_name not in stock_to_concepts:
                        stock_to_concepts[stock_name] = {'cls': [], 'kpl': [], 'ths': []}
                    existing = stock_to_concepts[stock_name]['kpl']
                    found = False
                    for item in existing:
                        if item['concept'] == main_concept:
                            found = True
                            break
                    if not found:
                        existing.append({'concept': main_concept, 'sub': []})

    # 同花顺 - 遍历forward构建索引（THS没有reverse映射）
    ths_forward = concept_data.get('ths', {}).get('forward', {})
    for main_concept, sub_data in ths_forward.items():
        if isinstance(sub_data, dict):
            # 二级结构: {主概念: {细分: [stocks]}}
            for sub_concept, stocks in sub_data.items():
                for stock in stocks:
                    if isinstance(stock, dict):
                        stock_name = stock.get('name', '')
                    else:
                        stock_name = stock
                    if stock_name:
                        if stock_name not in stock_to_concepts:
                            stock_to_concepts[stock_name] = {'cls': [], 'kpl': [], 'ths': []}
                        # 格式: [[concept, sub], ...]
                        existing = stock_to_concepts[stock_name]['ths']
                        found = False
                        for item in existing:
                            if item[0] == main_concept:
                                found = True
                                break
                        if not found:
                            existing.append([main_concept, sub_concept])
        elif isinstance(sub_data, list):
            # 直接是股票列表: [{name, code}, ...]
            for stock in sub_data:
                if isinstance(stock, dict):
                    stock_name = stock.get('name', '')
                else:
                    stock_name = stock
                if stock_name:
                    if stock_name not in stock_to_concepts:
                        stock_to_concepts[stock_name] = {'cls': [], 'kpl': [], 'ths': []}
                    existing = stock_to_concepts[stock_name]['ths']
                    found = False
                    for item in existing:
                        if item[0] == main_concept:
                            found = True
                            break
                    if not found:
                        existing.append([main_concept, ''])

    print(f"  ✓ 索引了 {len(stock_to_concepts)} 只股票的概念信息")
    return stock_to_concepts


def build_concept_to_stocks_index(concept_data):
    """构建概念到股票的索引（用于弹框查询）

    Returns:
        dict: {
            'cls': {'概念名': ['股票1', '股票2', ...], ...},
            'kpl': {'主概念::细分': ['股票1', ...], ...},
            'ths': {'概念名': ['股票1', ...], ...}
        }
    """
    print("构建概念→股票索引...")
    concept_to_stocks = {'cls': {}, 'kpl': {}, 'ths': {}}

    # 财联社 - 遍历forward
    cls_forward = concept_data.get('cls', {}).get('forward', {})
    for main_concept, sub_data in cls_forward.items():
        if isinstance(sub_data, dict):
            for sub_concept, stocks in sub_data.items():
                full_name = f"{main_concept}::{sub_concept}"
                # 财联社股票是字符串名称
                concept_to_stocks['cls'][full_name] = stocks if isinstance(stocks, list) else [stocks]
                # 也添加主概念
                if main_concept not in concept_to_stocks['cls']:
                    concept_to_stocks['cls'][main_concept] = []
                for s in stocks:
                    if s not in concept_to_stocks['cls'][main_concept]:
                        concept_to_stocks['cls'][main_concept].append(s)
        elif isinstance(sub_data, list):
            concept_to_stocks['cls'][main_concept] = sub_data

    # 开盘啦 - 遍历forward
    kpl_forward = concept_data.get('kpl', {}).get('forward', {})
    for main_concept, sub_data in kpl_forward.items():
        if isinstance(sub_data, dict):
            for sub_concept, stocks in sub_data.items():
                full_name = f"{main_concept}::{sub_concept}"
                stock_names = [s.get('name') if isinstance(s, dict) else s for s in stocks]
                concept_to_stocks['kpl'][full_name] = stock_names
            # 主概念下的所有股票
            all_stocks = []
            for stocks in sub_data.values():
                for s in stocks:
                    name = s.get('name') if isinstance(s, dict) else s
                    if name and name not in all_stocks:
                        all_stocks.append(name)
            if all_stocks:
                concept_to_stocks['kpl'][main_concept] = all_stocks
        elif isinstance(sub_data, list):
            stock_names = [s.get('name') if isinstance(s, dict) else s for s in sub_data]
            concept_to_stocks['kpl'][main_concept] = stock_names

    # 同花顺 - 遍历forward
    ths_forward = concept_data.get('ths', {}).get('forward', {})
    for main_concept, sub_data in ths_forward.items():
        if isinstance(sub_data, dict):
            # 二级结构：{主概念: {细分: [stocks]}}
            for sub_concept, stocks in sub_data.items():
                full_name = f"{main_concept}::{sub_concept}"
                # 提取股票名称（可能是对象或字符串）
                stock_names = [s.get('name') if isinstance(s, dict) else s for s in stocks]
                concept_to_stocks['ths'][full_name] = stock_names
                # 添加到主概念
                if main_concept not in concept_to_stocks['ths']:
                    concept_to_stocks['ths'][main_concept] = []
                for s in stock_names:
                    if s not in concept_to_stocks['ths'][main_concept]:
                        concept_to_stocks['ths'][main_concept].append(s)
        elif isinstance(sub_data, list):
            # 直接是股票列表：[{name, code}, ...]
            stock_names = [s.get('name') if isinstance(s, dict) else s for s in sub_data]
            concept_to_stocks['ths'][main_concept] = stock_names

    # 汇总各平台概念数量
    for src in ['cls', 'kpl', 'ths']:
        print(f"  ✓ {src}: {len(concept_to_stocks[src])} 个概念")

    return concept_to_stocks


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

    # 找到实际最新的日期（考虑当前时间是否开盘）
    today_date = get_actual_latest_date(dates)
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


def generate_html(analysis_result, df_hot_concepts, df_zt_pool, dates, df_concept_stock=None, archives=None, static_path="static"):
    """生成HTML报告
    Args:
        static_path: CSS/JS静态资源路径，相对于HTML文件位置
    """
    today = datetime.now().strftime('%Y年%m月%d日')
    archives = archives or []

    # 找到实际最新的日期（考虑当前时间是否开盘）
    today_date = get_actual_latest_date(dates)
    today_date_int = int(today_date) if today_date else None
    # 用于归档过滤的今日日期
    today_str = datetime.now().strftime('%Y%m%d')

    # 共享数据
    code_to_concepts = analysis_result.get('code_to_concepts', {})
    top20_names = dict(zip(df_hot_concepts['concept_code'].astype(str), df_hot_concepts['concept_name'])) if df_hot_concepts is not None else {}

    # 加载三个平台的概念数据并构建索引
    concept_data = load_all_concept_data()
    stock_to_concepts = build_stock_to_concepts_index(concept_data)  # 股票→概念
    concept_to_stocks = build_concept_to_stocks_index(concept_data)  # 概念→股票

    # 序列化概念→股票数据供前端使用
    concept_to_stocks_json = json.dumps(concept_to_stocks, ensure_ascii=False)

    # 构建15日涨停股票名称集合（用于概念弹框标记）
    # 注意：概念数据中使用股票名称而非代码，所以用名称匹配
    zt_15d_names = set()
    for date_stocks in analysis_result.get('ladder_data', {}).values():
        for stock in date_stocks:
            if isinstance(stock, (list, tuple)) and len(stock) >= 1:
                name = stock[0]  # [name, lianban, concepts, hot_rank, code]
                if name:
                    zt_15d_names.add(name.strip())
    zt_15d_names_json = json.dumps(list(zt_15d_names), ensure_ascii=False)

    # 获取最新韭研公社涨停简图
    JYGS_ZT_image_path, JYGS_ZT_image_date = get_latest_JYGS_ZT_image(static_path)

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

    ladder_section = f"""<div class="rhythm-grid">{ladder_html}</div>
        <div class="legend">
            <span class="item"><span class="dot lb-1"></span>首板</span>
            <span class="item"><span class="dot lb-2"></span>2板</span>
            <span class="item"><span class="dot lb-3"></span>3板+</span>
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

    matrix_section = f"""<table class="matrix-table">{matrix_html}</table>"""

    # ========== 2. 今日涨停看板（4列布局）==========
    today_zt_df = df_zt_pool[df_zt_pool['交易日期'] == today_date_int] if df_zt_pool is not None else pd.DataFrame()
    today_zt_count = len(today_zt_df)

    # 按连板数降序排序
    if not today_zt_df.empty:
        today_zt_df = today_zt_df.sort_values('连板数', ascending=False)

    # 生成4列布局HTML
    today_board_items = ""
    today_board_items += '<div class="today-board-4col">'
    today_board_items += '<div class="today-col-header">'
    today_board_items += '<div class="today-col-cell col-stock">涨停股票</div>'
    today_board_items += '<div class="today-col-cell col-cls">财联社</div>'
    today_board_items += '<div class="today-col-cell col-kpl">开盘啦</div>'
    today_board_items += '<div class="today-col-cell col-ths">同花顺</div>'
    today_board_items += '</div>'

    if not today_zt_df.empty:
        for _, row in today_zt_df.iterrows():
            code = str(row['代码_str'])
            name = row['名称']
            lianban = int(row['连板数']) if pd.notna(row['连板数']) else 1

            if lianban >= 3:
                lb_class, lb_tag = "lb-3", "3+"
            elif lianban == 2:
                lb_class, lb_tag = "lb-2", "2板"
            else:
                lb_class, lb_tag = "lb-1", "首板"

            # 获取该股票在三个平台的概念
            concepts_info = stock_to_concepts.get(name, {'cls': [], 'kpl': [], 'ths': []})
            cls_concepts = concepts_info.get('cls', [])
            kpl_concepts = concepts_info.get('kpl', [])
            ths_concepts = concepts_info.get('ths', [])

            today_board_items += '<div class="today-stock-row">'

            # 第1列：涨停股票
            today_board_items += f'<div class="today-col-cell col-stock">'
            today_board_items += f'<div class="today-stock-item {lb_class}" onclick="openKLineModal(\'{code}\', \'{name}\')">'
            today_board_items += f'<span class="today-stock-name">{name}</span>'
            today_board_items += f'<span class="today-stock-lb">{lb_tag}</span>'
            today_board_items += f'</div></div>'

            # 第2列：财联社概念
            today_board_items += '<div class="today-col-cell col-cls">'
            if cls_concepts:
                for concept in cls_concepts[:8]:  # 最多显示8个
                    today_board_items += f'<span class="concept-tag" onclick="openConceptModal(\'cls\', \'{concept}\')">{concept}</span>'
            else:
                today_board_items += '<span class="concept-empty">-</span>'
            today_board_items += '</div>'

            # 第3列：开盘啦概念
            today_board_items += '<div class="today-col-cell col-kpl">'
            if kpl_concepts:
                for item in kpl_concepts[:5]:  # 最多显示5个主概念
                    main_concept = item.get('concept', '')
                    sub_concepts = item.get('sub', [])
                    if main_concept:
                        today_board_items += f'<span class="concept-tag kpl-main" onclick="openConceptModal(\'kpl\', \'{main_concept}\')">{main_concept}</span>'
                    for sub in sub_concepts[:3]:  # 每个主概念最多3个细分
                        today_board_items += f'<span class="concept-tag kpl-sub" onclick="openConceptModal(\'kpl\', \'{main_concept}\', \'{sub}\')">{sub}</span>'
            else:
                today_board_items += '<span class="concept-empty">-</span>'
            today_board_items += '</div>'

            # 第4列：同花顺概念
            today_board_items += '<div class="today-col-cell col-ths">'
            if ths_concepts:
                for concept_arr in ths_concepts[:8]:  # 最多显示8个
                    if isinstance(concept_arr, list):
                        concept_name = concept_arr[0] if len(concept_arr) > 0 else ''
                        sub_name = concept_arr[1] if len(concept_arr) > 1 else ''
                        if sub_name:
                            today_board_items += f'<span class="concept-tag" onclick="openConceptModal(\'ths\', \'{concept_name}\', \'{sub_name}\')">{concept_name}::{sub_name}</span>'
                        else:
                            today_board_items += f'<span class="concept-tag" onclick="openConceptModal(\'ths\', \'{concept_name}\')">{concept_name}</span>'
                    else:
                        today_board_items += f'<span class="concept-tag" onclick="openConceptModal(\'ths\', \'{concept_arr}\')">{concept_arr}</span>'
            else:
                today_board_items += '<span class="concept-empty">-</span>'
            today_board_items += '</div>'

            today_board_items += '</div>'  # end today-stock-row

    today_board_items += '</div>'  # end today-board-4col
    today_board_section = f"""<div class="today-board">{today_board_items}</div>"""

    # ========== 3. 热门概念(TOP20)/股票(TOP100) - 可展开展示 ==========
    # 加载整合后的热点数据
    hot_data_path = os.path.join(HOT_DIR, "hot_data_combined.json")
    hot_data = None
    if os.path.exists(hot_data_path):
        with open(hot_data_path, 'r', encoding='utf-8') as f:
            hot_data = json.load(f)

    concepts_html = ""
    unclassified_html = ""

    if hot_data and hot_data.get('concepts'):
        # 识别市场主线（今日涨停>=2 且 热度值>5000的概念）
        main_themes = []
        for concept in hot_data['concepts']:
            stats = {}
            for result in analysis_result['top20_concepts']:
                if result['concept_code'] == concept['code']:
                    stats = result.get('stats', {})
                    break
            today_zt = stats.get('today_zt_count', 0)
            hot_val = concept.get('hot_value', 0)
            if today_zt >= 2 and hot_val > 5000:
                main_themes.append({
                    'name': concept['name'],
                    'today_zt': today_zt,
                    'hot_value': hot_val
                })
        main_themes = sorted(main_themes, key=lambda x: (-x['today_zt'], -x['hot_value']))[:3]

        # 生成主线HTML
        main_themes_html = ""
        if main_themes:
            theme_items = ""
            for mt in main_themes:
                theme_items += f"<span class='main-theme-tag'>{mt['name']}({mt['today_zt']}只)</span>"
            main_themes_html = f"<div class='main-themes'><span class='main-themes-label'>🚀 市场主线：</span>{theme_items}</div>"

        # 未分类股票区域
        if hot_data.get('unclassified_stocks'):
            unclassified = hot_data['unclassified_stocks']
            unclassified_count = len(unclassified)
            unclassified_items = ""
            for s in unclassified:
                change_str = f"{s['change_pct']:+.2f}%" if s['change_pct'] else ""
                change_cls = "up" if s.get('change_pct', 0) > 0 else "down" if s.get('change_pct', 0) < 0 else ""
                pop_tag = s.get('pop_tag', '') or ""
                unclassified_items += f"""<tr onclick="openKLineModal('{s['code']}', '{s['name']}')">
                    <td class="hs-rank">{s['rank']}</td>
                    <td class="hs-name">{s['name']}</td>
                    <td class="hs-code">{s['code']}</td>
                    <td class="hs-hot">{s['hot_value']:,.0f}</td>
                    <td class="hs-change {change_cls}">{change_str}</td>
                    <td class="hs-pop">{pop_tag}</td>
                </tr>"""
            unclassified_html = f"""
            <div class="hot-section-accordion">
                <div class="hot-section-header" onclick="toggleHotSection('unclassified')">
                    <span class="hot-section-title">🔥 未分类热股 TOP100</span>
                    <span class="hot-section-count">({unclassified_count}只)</span>
                    <span class="expand-icon" id="icon-unclassified">▼</span>
                </div>
                <div class="hot-section-content" id="hot-content-unclassified">
                    <table class="hot-stocks-table">
                        <thead>
                            <tr>
                                <th class="hs-col-rank">排名</th>
                                <th class="hs-col-name">名称</th>
                                <th class="hs-col-code">代码</th>
                                <th class="hs-col-hot">热度值</th>
                                <th class="hs-col-change">涨跌</th>
                                <th class="hs-col-pop">人气标签</th>
                            </tr>
                        </thead>
                        <tbody>
                            {unclassified_items}
                        </tbody>
                    </table>
                </div>
            </div>"""

        # 生成每个概念的可展开卡片
        concepts = hot_data['concepts']
        concept_accordions = ""
        for idx, concept in enumerate(concepts):
            concept_id = f"concept-{idx}"
            hot_val = concept.get('hot_value', 0)
            stock_count = concept.get('stock_count', 0)
            hot_tag = concept.get('hot_tag', '')

            # 构建股票列表
            stock_rows = ""
            for s in concept.get('stocks', []):
                change_str = f"{s['change_pct']:+.2f}%" if s['change_pct'] else ""
                change_cls = "up" if s.get('change_pct', 0) > 0 else "down" if s.get('change_pct', 0) < 0 else ""
                pop_tag = s.get('pop_tag', '') or ""
                board_tag = get_board_tag(s['code'])
                board_html = f"<span class='board-inline board-{board_tag}'>{board_tag}</span>" if board_tag else ""
                stock_rows += f"""<tr onclick="openKLineModal('{s['code']}', '{s['name']}')">
                    <td class="hs-rank">{s['rank']}</td>
                    <td class="hs-name">{s['name']}{board_html}</td>
                    <td class="hs-code">{s['code']}</td>
                    <td class="hs-hot">{s['hot_value']:,.0f}</td>
                    <td class="hs-change {change_cls}">{change_str}</td>
                    <td class="hs-pop">{pop_tag}</td>
                </tr>"""

            concept_accordions += f"""<div class="hot-section-accordion">
                <div class="hot-section-header" onclick="toggleHotSection('{concept_id}')">
                    <span class="hot-section-rank">{idx+1}</span>
                    <span class="hot-section-title">{concept['name']}</span>
                    <span class="hot-section-hot">{hot_val:,.0f}</span>
                    <span class="hot-section-count">({stock_count}只)</span>
                    <span class="hot-section-tag">{hot_tag}</span>
                    <span class="expand-icon" id="icon-{concept_id}">▼</span>
                </div>
                <div class="hot-section-content" id="hot-content-{concept_id}">
                    <table class="hot-stocks-table">
                        <thead>
                            <tr>
                                <th class="hs-col-rank">排名</th>
                                <th class="hs-col-name">名称</th>
                                <th class="hs-col-code">代码</th>
                                <th class="hs-col-hot">热度值</th>
                                <th class="hs-col-change">涨跌</th>
                                <th class="hs-col-pop">人气标签</th>
                            </tr>
                        </thead>
                        <tbody>
                            {stock_rows}
                        </tbody>
                    </table>
                </div>
            </div>"""

        concepts_html = concept_accordions

    else:
        # 备用：简单的概念列表
        df_hot_concepts['hot_value_num'] = pd.to_numeric(df_hot_concepts['hot_value'], errors='coerce')
        concepts_sorted = df_hot_concepts.sort_values('hot_value_num', ascending=False).reset_index(drop=True)

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

        main_themes_html = ""

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
        # 先收集每个股票的所有涨停日期和最大连板数
        stock_zt_info = {}  # {code: {'dates': set(), 'max_lianban': int}}
        for d in dates:
            stocks_on_date = date_rhythm.get(d, [])
            for name, lb, code, first_seal in stocks_on_date:
                if code not in stock_zt_info:
                    stock_zt_info[code] = {'name': name, 'dates': [], 'max_lianban': 0, 'first_seals': {}}
                stock_zt_info[code]['dates'].append(d)
                if lb > stock_zt_info[code]['max_lianban']:
                    stock_zt_info[code]['max_lianban'] = lb
                # 记录首次封板时间用于排序
                if d not in stock_zt_info[code]['first_seals']:
                    stock_zt_info[code]['first_seals'][d] = first_seal

        # 构建看板数据，按日期ASC + 首封ASC排序
        board_stocks = []
        for code, info in stock_zt_info.items():
            # 按日期和首次封板时间排序
            info['dates'].sort(key=lambda d: (d, info['first_seals'].get(d) or ''))
            board_stocks.append({
                'name': info['name'],
                'code': code,
                'lianban': info['max_lianban'],
                'zt_count': len(info['dates']),
                'zt_dates': info['dates'],  # 所有涨停日期列表
                'date': info['dates'][0] if info['dates'] else '',  # 首次涨停日期
                'first_seal': info['first_seals'].get(info['dates'][0]) if info['dates'] else None
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
        other_section = f"""<table class="data-table">
            <thead><tr><th>股票代码</th><th>股票名称</th><th>涨停日期</th><th>连板</th><th>所有概念</th></tr></thead>
            <tbody>{other_rows}</tbody>
        </table>"""

    # ========== 6. 未涨停热股 ==========
    not_zt_section = ""
    if analysis_result['not_zt_hot_stocks']:
        not_zt_rows = ""
        for stock in analysis_result['not_zt_hot_stocks']:
            hot_val = float(stock['hot_value']) if isinstance(stock['hot_value'], (int, float)) else 0
            code = format_code(stock['stock_code'])
            not_zt_rows += f"<tr><td>{stock['rank']}</td><td>{code}</td><td class='clickable-name' onclick=\"openKLineModal('{code}', '{stock['short_name']}')\">{stock['short_name']}</td><td>{hot_val:,.0f}</td><td>{stock['pop_tag']}</td></tr>"
        not_zt_section = f"""<table class="data-table">
            <thead><tr><th>排名</th><th>股票代码</th><th>股票名称</th><th>热度值</th><th>人气标签</th></tr></thead>
            <tbody>{not_zt_rows}</tbody>
        </table>"""

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
        multi_section = f"""<table class="data-table">
            <thead><tr><th>股票代码</th><th>股票名称</th><th>涨停次数</th><th>最大连板</th><th>热度排名</th><th>热度值</th><th>涵盖概念</th></tr></thead>
            <tbody>{multi_rows}</tbody>
        </table>"""

    # ========== 8. 韭研公社涨停简图 ==========
    JYGS_ZT_section = ""
    if JYGS_ZT_image_path and JYGS_ZT_image_date:
        date_display = f"{JYGS_ZT_image_date[4:6]}-{JYGS_ZT_image_date[6:8]}"
        JYGS_ZT_section = f"""<div class="section-block">
            <h2 class="section-title">🔥 涨停简图</h2>
            <p class="section-desc">韭研公社涨停简图 | {date_display}日</p>
            <div class="JYGS_ZT-image-wrapper">
                <img src="{JYGS_ZT_image_path}" alt="涨停简图 {date_display}" class="JYGS_ZT-image" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
                <div class="JYGS_ZT-fallback" style="display:none; text-align:center; padding:40px; color:#999;">图片加载失败，请刷新重试</div>
            </div>
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
    <link rel="stylesheet" href="{static_path}/css/dashboard.css">
    <style>
        body {{ padding: 0; margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f6fa; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px 30px; }}
        .header {{ background: #fff; border-radius: 12px; padding: 20px 25px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
        .header-title {{ font-size: 1.6em; color: #1a365d; margin-bottom: 8px; font-weight: 600; }}
        .header-subtitle {{ color: #718096; font-size: 0.95em; margin-bottom: 15px; }}
        .header-controls {{ display: flex; gap: 12px; align-items: center; }}
        #archive-select {{ padding: 8px 12px; font-size: 0.95em; border: 1px solid #e2e8f0; border-radius: 6px; background: #fff; color: #2d3748; cursor: pointer; min-width: 180px; }}
        #archive-select:hover {{ border-color: #4299e1; }}
        .stats {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 15px; margin-bottom: 25px; }}
        .stat-card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 18px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.04); }}
        .stat-value {{ font-size: 1.8em; font-weight: bold; color: #2b6cb0; }}
        .stat-label {{ color: #718096; font-size: 0.85em; margin-top: 5px; }}
        .section-block {{ background: #fff; border-radius: 12px; padding: 20px 25px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
        .section-title {{ font-size: 1.3em; color: #2d3748; margin: 0 0 15px 0; padding-left: 12px; border-left: 4px solid #4299e1; font-weight: 600; }}
        .section-desc {{ color: #718096; font-size: 0.9em; margin-bottom: 15px; }}
        .footer {{ text-align: center; padding: 20px; color: #a0aec0; font-size: 0.85em; }}
        .concept-stocks-preview {{ font-size: 0.8em; color: #718096; margin-top: 5px; }}
        .concept-stocks-preview .stock-count {{ background: #edf2f7; padding: 2px 6px; border-radius: 4px; margin-right: 5px; }}
        .concept-stocks-preview .stock-list {{ display: block; margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .unclassified-section {{ background: #fff5f5; border: 1px solid #fed7d7; border-radius: 8px; padding: 12px 15px; margin-bottom: 15px; }}
        .unclassified-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
        .unclassified-title {{ font-weight: 600; color: #c53030; }}
        .unclassified-count {{ color: #718096; font-size: 0.9em; }}
        .unclassified-stocks {{ color: #4a5568; font-size: 0.9em; line-height: 1.5; }}
        /* 热门概念/股票展开区域 */
        .hot-section-accordion {{ border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 8px; overflow: hidden; width: 100%; box-sizing: border-box; }}
        .hot-section-header {{ display: table; width: 100%; table-layout: fixed; padding: 12px 15px; background: #f7fafc; cursor: pointer; transition: background 0.2s; box-sizing: border-box; }}
        .hot-section-header:hover {{ background: #edf2f7; }}
        .hot-section-header > * {{ display: table-cell; vertical-align: middle; padding: 0 5px; }}
        .hot-section-rank {{ background: #4299e1; color: #fff; width: 32px; height: 32px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 0.75em; font-weight: bold; flex-shrink: 0; text-align: center; }}
        .hot-section-title {{ font-weight: 600; color: #2d3748; text-align: left; min-width: 120px; }}
        .hot-section-hot {{ color: #e53e3e; font-weight: 600; text-align: right; min-width: 80px; }}
        .hot-section-count {{ color: #718096; font-size: 0.85em; text-align: center; min-width: 50px; }}
        .hot-section-tag {{ font-size: 0.7em; color: #a0aec0; background: #edf2f7; padding: 2px 8px; border-radius: 4px; text-align: left; min-width: 80px; }}
        .expand-icon {{ color: #718096; font-size: 0.8em; text-align: right; width: 30px; }}
        .hot-section-content {{ display: none; background: #fff; border-top: 1px solid #e2e8f0; padding: 10px 15px; width: 100%; box-sizing: border-box; }}
        .hot-section-content.open {{ display: block; }}
        .hot-stocks-table {{ width: 100%; border-collapse: collapse; table-layout: auto; font-size: 0.9em; }}
        .hot-stocks-table th {{ background: #f7fafc; padding: 10px 15px; color: #718096; font-weight: 600; text-align: left; border-bottom: 2px solid #e2e8f0; white-space: nowrap; }}
        .hot-stocks-table th.hs-col-rank {{ text-align: center; white-space: nowrap; }}
        .hot-stocks-table th.hs-col-name {{ white-space: nowrap; }}
        .hot-stocks-table th.hs-col-code {{ white-space: nowrap; }}
        .hot-stocks-table th.hs-col-hot {{ text-align: right; white-space: nowrap; }}
        .hot-stocks-table th.hs-col-change {{ text-align: right; white-space: nowrap; }}
        .hot-stocks-table th.hs-col-pop {{ white-space: nowrap; }}
        .hot-stocks-table td {{ padding: 10px 15px; border-bottom: 1px solid #f0f0f0; cursor: pointer; white-space: nowrap; }}
        .hot-stocks-table tr:hover {{ background: #f7fafc; }}
        .hot-stocks-table td.hs-rank {{ color: #718096; text-align: center; white-space: nowrap; }}
        .hot-stocks-table td.hs-name {{ font-weight: 600; color: #2d3748; white-space: nowrap; }}
        .hot-stocks-table td.hs-code {{ color: #a0aec0; font-family: monospace; white-space: nowrap; }}
        .hot-stocks-table td.hs-hot {{ color: #e53e3e; font-weight: 600; text-align: right; white-space: nowrap; }}
        .hot-stocks-table td.hs-change {{ text-align: right; }}
        .hot-stocks-table td.hs-change.up {{ color: #e53e3e; font-weight: 600; }}  /* 涨-红色 */
        .hot-stocks-table td.hs-change.down {{ color: #38a169; font-weight: 600; }}  /* 跌-绿色 */
        .hot-stocks-table td.hs-pop {{ color: #718096; font-size: 0.85em; }}
    </style>
    <script src="{static_path}/js/app.js?v=2026041803"></script>
    <script>
    // 预加载概念→股票映射数据，供弹框使用
    var PRELOADED_CONCEPT_TO_STOCKS = {concept_to_stocks_json};
    // 15日涨停股票名称集合（用于概念弹框标记）
    var ZT_15D_NAMES = new Set({zt_15d_names_json});

    function toggleHotSection(id) {{
        var content = document.getElementById('hot-content-' + id);
        var icon = document.getElementById('icon-' + id);
        if (content.classList.contains('open')) {{
            content.classList.remove('open');
            icon.textContent = '▼';
        }} else {{
            content.classList.add('open');
            icon.textContent = '▲';
        }}
    }}
    </script>
    <script>
    // 交易日16:30自动刷新（北京时间）
    (function(){
        function getNextRefreshTime() {
            var now = new Date();
            var beijingOffset = 8 * 60 * 60 * 1000;
            var today = new Date(now.getTime() + beijingOffset);
            var targetHour = 16, targetMin = 30;
            var targetToday = new Date(today.getFullYear(), today.getMonth(), today.getDate(), targetHour, targetMin, 0);
            targetToday = new Date(targetToday.getTime() - beijingOffset);
            if (now < targetToday) return targetToday;
            // 明天16:30
            var tomorrow = new Date(targetToday);
            tomorrow.setDate(tomorrow.getDate() + 1);
            return tomorrow;
        }
        setTimeout(function(){ location.reload(); }, getNextRefreshTime() - new Date());
    })();
    </script>
</head>
<body>
    <div class="container">
        <!-- 头部信息 -->
        <div class="header">
            <div class="header-title">📈 股票走势分析</div>
            <div class="header-subtitle">{today} | 分析时段: {dates[-1]} 至 {dates[0]}</div>
            <div class="header-controls">
                <select id="archive-select" onchange="loadArchive(this.value)">
                    <option value="">选择查看归档...</option>
                    <option value="report_latest.html" selected>最新报告</option>
                    {archive_options}
                </select>
            </div>
        </div>

        <!-- 统计卡片 -->
        <div class="stats">
            <div class="stat-card"><div class="stat-value">{len(analysis_result['top20_concepts'])}</div><div class="stat-label">热门概念板块</div></div>
            <div class="stat-card"><div class="stat-value">{total_zt}</div><div class="stat-label">TOP20涨停股</div></div>
            <div class="stat-card"><div class="stat-value">{len(analysis_result['other_stocks'])}</div><div class="stat-label">其他概念涨停</div></div>
            <div class="stat-card"><div class="stat-value">{len(analysis_result['not_zt_hot_stocks'])}</div><div class="stat-label">未涨停热股</div></div>
            <div class="stat-card"><div class="stat-value">{today_zt_count}</div><div class="stat-label">今日涨停</div></div>
        </div>

        <!-- 连板天梯 -->
        <div class="section-block">
            <h2 class="section-title">🏆 连板天梯</h2>
            <p class="section-desc">近15交易日2板及以上涨停，按日期横向展示</p>
            {ladder_section}
        </div>

        <!-- 连板矩阵 -->
        <div class="section-block">
            <h2 class="section-title">📈 连板矩阵</h2>
            <p class="section-desc">近6交易日2板及以上涨停，概念x日期分布</p>
            {matrix_section}
        </div>

        <!-- 今日涨停看板 -->
        <div class="section-block">
            <h2 class="section-title">⚡ 今日涨停看板</h2>
            <p class="section-desc">{today_date[4:]}日 | 共 {today_zt_count} 只涨停</p>
            {today_board_section}
        </div>

        <!-- 韭研公社涨停简图 -->
        {JYGS_ZT_section}

        <!-- 热门概念板块/股票一览 -->
        <div class="section-block">
            <h2 class="section-title">🔥 热门概念(TOP20)/股票(TOP100)</h2>
            {main_themes_html}
            {unclassified_html}
            {concepts_html}
        </div>

        <!-- TOP20概念题材详情 -->
        <div class="section-block">
            <h2 class="section-title">📋 TOP20概念题材</h2>
            <p class="section-desc">点击展开各概念详情 | 按热度值排序</p>
            <div style="margin-bottom: 15px; display: flex; gap: 10px;">
                <button class="toggle-all-btn tab-btn" data-action="toggle-all" style="background: #4299e1; color: #fff; border-radius: 6px; padding: 8px 16px;">📖 一键展开全部</button>
                <button class="toggle-trend-btn tab-btn" data-action="toggle-trend" style="background: #38a169; color: #fff; border-radius: 6px; padding: 8px 16px;">📈 一键展开走势看板</button>
            </div>
            {concept_details}
        </div>

        <!-- 其他概念涨停股 -->
        <div class="section-block">
            <h2 class="section-title">📦 其他概念涨停股</h2>
            <p class="section-desc">不在TOP20热门板块中的涨停股</p>
            {other_section}
        </div>

        <!-- 未涨停热股 -->
        <div class="section-block">
            <h2 class="section-title">❄️ 未涨停热股</h2>
            <p class="section-desc">同花顺热股TOP100中，15日内未涨停的股票</p>
            {not_zt_section}
        </div>

        <!-- 多概念股票 -->
        <div class="section-block">
            <h2 class="section-title">🎯 多概念股票</h2>
            <p class="section-desc">涵盖TOP20热门板块3个及以上概念的股票</p>
            {multi_section}
        </div>

        <div class="footer">
            <p>报告由股票分析系统自动生成 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
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
            </div>
            <div class="modal-body">
                <img id="kline-img" src="" alt="K线图加载中...">
            </div>
        </div>
    </div>

    <!-- 概念弹窗 -->
    <div id="concept-modal" class="modal-overlay" onclick="closeConceptModal()">
        <div class="modal-content concept-modal-content" onclick="event.stopPropagation()">
            <div class="modal-header">
                <h3 id="concept-modal-title">概念详情</h3>
                <span class="close-btn" onclick="closeConceptModal()">&times;</span>
            </div>
            <div class="modal-body">
                <div id="concept-modal-stocks" class="concept-modal-stocks"></div>
            </div>
        </div>
    </div>
</body>
</html>"""

    return html


def save_report(markdown_content, html_content_archive, html_content_latest, dates):
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
        f.write(html_content_archive)
    print(f"  ✓ HTML报告: {html_file}")

    # 最新报告（兼容旧链接）
    latest_md = os.path.join(SCRIPT_DIR, "report_latest.md")
    latest_html = os.path.join(SCRIPT_DIR, "report_latest.html")

    with open(latest_md, 'w', encoding='utf-8') as f:
        f.write(markdown_content)
    with open(latest_html, 'w', encoding='utf-8') as f:
        f.write(html_content_latest)
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


def get_available_json_archives():
    """获取已有JSON文件的归档列表"""
    json_dir = os.path.join(REPORTS_DIR, "data")
    if not os.path.exists(json_dir):
        return []
    archives = []
    for f in os.listdir(json_dir):
        if f.endswith('.json') and f[:8].isdigit() and len(f) == 13:
            archives.append(f[:8])
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


def convert_nan_to_none(obj):
    """Recursively convert NaN and infinity values to None for JSON serialization"""
    if isinstance(obj, dict):
        return {k: convert_nan_to_none(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_nan_to_none(item) for item in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj


def save_report_json(analysis_result, df_hot_concepts, df_zt_pool, dates, df_concept_stock,
                     today_str, today_zt_count, JYGS_ZT_image_path, JYGS_ZT_image_date, archives):
    """生成JSON数据文件"""

    # 加载三个平台的概念数据并构建索引
    concept_data = load_all_concept_data()
    stock_to_concepts = build_stock_to_concepts_index(concept_data)  # 股票→概念
    concept_to_stocks = build_concept_to_stocks_index(concept_data)  # 概念→股票

    # 构建 hot_concepts 列表
    hot_concepts_list = []
    if df_hot_concepts is not None:
        for _, row in df_hot_concepts.iterrows():
            hot_concepts_list.append({
                'code': str(row['concept_code']),
                'name': row['concept_name'],
                'hot_value': float(row['hot_value']) if pd.notna(row['hot_value']) else 0
            })

    # 构建 top20_concepts 结构
    top20_concepts = []
    for result in analysis_result['top20_concepts']:
        # 从 date_rhythm 计算 zt_dates
        date_rhythm = result.get('date_rhythm', {})
        zt_dates = [d for d, stocks in date_rhythm.items() if stocks]

        # 将 stocks DataFrame 转换为列表
        stocks_list = []
        if not result['stocks'].empty:
            for _, stock in result['stocks'].iterrows():
                stocks_list.append({
                    'code': str(stock['代码']),
                    'name': stock['名称'],
                    'max_lianban': int(stock['最大连板数']) if pd.notna(stock['最大连板数']) else 1,
                    'zt_count': int(stock['涨停次数']) if pd.notna(stock['涨停次数']) else 1,
                    'hot_rank': int(stock['热度排名']) if '热度排名' in stock and pd.notna(stock['热度排名']) else 999,
                    'hot_value': float(stock['热度值']) if '热度值' in stock and pd.notna(stock['热度值']) else 0,
                    'concepts': stock['所属概念'] if '所属概念' in stock else '-'
                })

        concept_data = {
            'concept_code': result['concept_code'],
            'concept_name': result['concept_name'],
            'hot_value': float(result['hot_value']) if result['hot_value'] else 0,
            'stats': result.get('stats', {}),
            'stocks': stocks_list,
            'zt_dates': zt_dates
        }
        top20_concepts.append(concept_data)

    # ladder 数据直接来自 analysis_result['ladder_data']
    ladder_data = analysis_result.get('ladder_data', {})

    # 构建 matrix 数据（近6交易日 x 概念）
    top20_concept_names = [r['concept_name'] for r in analysis_result['top20_concepts']]
    dates_with_ladder = [d for d in dates if ladder_data.get(d, [])]
    recent_6_dates = dates_with_ladder[:6] if dates_with_ladder else dates[:6]

    code_to_concepts = analysis_result.get('code_to_concepts', {})
    top20_names = dict(zip(df_hot_concepts['concept_code'].astype(str), df_hot_concepts['concept_name'])) if df_hot_concepts is not None else {}

    matrix_data = {}
    for concept in top20_concept_names:
        matrix_data[concept] = {}
        for d in recent_6_dates:
            matrix_data[concept][d] = []

    for d in recent_6_dates:
        date_stocks = ladder_data.get(d, [])
        for name, lb, concepts_str, hot_rank, code in date_stocks:
            # Convert numpy types to native Python types for JSON serialization
            name = str(name) if hasattr(name, 'item') else name
            lb = int(lb) if hasattr(lb, 'item') else lb
            stock_concepts = code_to_concepts.get(code, set())
            for concept in top20_concept_names:
                if concept in concepts_str or any(top20_names.get(c) == concept for c in stock_concepts):
                    all_concepts = []
                    if df_concept_stock is not None:
                        stock_rows = df_concept_stock[df_concept_stock['股票代码'].astype(str).str.zfill(6) == code]
                        all_concepts = stock_rows['概念名称'].tolist()[:3]
                    matrix_data[concept][d].append({
                        'name': name,
                        'code': code,
                        'lianban': lb,
                        'concepts': ','.join(all_concepts)
                    })

    # 构建 today_board 数据
    today_date = get_actual_latest_date(dates)
    today_date_int = int(today_date) if today_date else None

    today_zt_df = df_zt_pool[df_zt_pool['交易日期'] == today_date_int] if df_zt_pool is not None else pd.DataFrame()

    # 收集所有涨停股票的概念信息（来自三个平台）
    today_board_stocks = []  # 所有涨停股票列表
    stock_concepts_map = {}  # code -> {cls: [], kpl: [], ths: []}

    if not today_zt_df.empty:
        for _, row in today_zt_df.iterrows():
            code = str(row['代码_str'])
            name = row['名称']
            lianban = int(row['连板数']) if pd.notna(row['连板数']) else 1

            # 获取该股票在三个平台的概念
            concepts_info = stock_to_concepts.get(name, {'cls': [], 'kpl': [], 'ths': []})
            stock_concepts_map[code] = concepts_info

            today_board_stocks.append({
                'name': name,
                'code': code,
                'lianban': lianban,
                'cls_concepts': concepts_info.get('cls', []),
                'kpl_concepts': concepts_info.get('kpl', []),
                'ths_concepts': concepts_info.get('ths', [])
            })

    # 构建 concept_groups（保持原有TOP20概念分组逻辑）
    concept_stocks_map = {}
    no_concept_stocks = []

    for stock in today_board_stocks:
        code = stock['code']
        name = stock['name']
        lianban = stock['lianban']

        stock_concepts = code_to_concepts.get(code, set())
        concept_names = [top20_names.get(c, c) for c in stock_concepts if c in top20_names]

        if concept_names:
            for cn in concept_names[:3]:
                if cn not in concept_stocks_map:
                    concept_stocks_map[cn] = []
                concept_stocks_map[cn].append({'name': name, 'code': code, 'lianban': lianban})
        else:
            no_concept_stocks.append({'name': name, 'code': code, 'lianban': lianban})

    # 按概念内股票数排序
    sorted_concepts = sorted(concept_stocks_map.items(), key=lambda x: -len(x[1]))
    concept_groups = []
    for concept_name, stocks in sorted_concepts:
        concept_groups.append({'concept_name': concept_name, 'stocks': stocks})
    if no_concept_stocks:
        concept_groups.append({'concept_name': '其他', 'stocks': no_concept_stocks})

    today_board_data = {
        'date': today_date,
        'count': len(today_zt_df),
        'concept_groups': concept_groups,  # 修复：使用数组结构匹配JS
        'stocks': today_board_stocks  # 所有股票的详细信息（含三个平台概念）
    }

    # 转换 not_zt_hot_stocks (pandas Series 列表) 为普通列表
    not_zt_hot_stocks_serializable = []
    for stock in analysis_result['not_zt_hot_stocks']:
        if hasattr(stock, 'to_dict'):
            not_zt_hot_stocks_serializable.append(stock.to_dict())
        else:
            not_zt_hot_stocks_serializable.append(stock)

    # 转换 multi_concept_stocks 中的 numpy 类型
    multi_concept_stocks_serializable = []
    for stock in analysis_result['multi_concept_stocks']:
        stock_dict = {}
        for k, v in stock.items():
            if hasattr(v, 'item'):  # numpy type
                stock_dict[k] = v.item()
            else:
                stock_dict[k] = v
        multi_concept_stocks_serializable.append(stock_dict)

    # 转换 other_stocks 中的 numpy 类型
    other_stocks_serializable = []
    for stock in analysis_result['other_stocks']:
        stock_dict = {}
        for k, v in stock.items():
            if hasattr(v, 'item'):  # numpy type
                stock_dict[k] = v.item()
            else:
                stock_dict[k] = v
        other_stocks_serializable.append(stock_dict)

    data = {
        "date": today_str,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stats": {
            "concept_count": len(analysis_result['top20_concepts']),
            "top20_zt_count": sum(len(r['stocks']) for r in analysis_result['top20_concepts']),
            "other_zt_count": len(other_stocks_serializable),
            "not_zt_hot_count": len(not_zt_hot_stocks_serializable),
            "today_zt_count": today_zt_count
        },
        "dates": dates,
        "hot_concepts": hot_concepts_list,
        "top20_concepts": top20_concepts,
        "other_stocks": other_stocks_serializable,
        "not_zt_hot_stocks": not_zt_hot_stocks_serializable,
        "multi_concept_stocks": multi_concept_stocks_serializable,
        "today_board": today_board_data,
        "concept_to_stocks": concept_to_stocks,  # 概念→股票映射，用于弹框查询
        "ladder": ladder_data,
        "matrix": matrix_data,
        "JYGS_ZT_image": JYGS_ZT_image_path,
        "JYGS_ZT_date": JYGS_ZT_image_date,
        "archives": [a for a in archives if a != today_str]  # 排除当前日期
    }

    # 保存到 reports/data/YYYYMMDD.json
    json_dir = os.path.join(REPORTS_DIR, "data")
    os.makedirs(json_dir, exist_ok=True)
    json_path = os.path.join(json_dir, f"{today_str}.json")

    try:
        # Convert NaN and infinity values to None for valid JSON
        data = convert_nan_to_none(data)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  ✓ JSON数据: {json_path}")
        return json_path
    except Exception as e:
        print(f"  ✗ JSON保存失败: {e}")
        return None


def generate_template_html():
    """生成静态模板HTML（从report_latest.html提取）"""
    import shutil
    src = os.path.join(SCRIPT_DIR, "report_latest.html")
    dst = os.path.join(SCRIPT_DIR, "report_template.html")
    if os.path.exists(src):
        shutil.copy(src, dst)
        print(f"  ✓ 模板已生成: {dst}")
    else:
        print(f"  ✗ 源文件不存在: {src}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='股票分析报告看板 V2')
    parser.add_argument('--html', action='store_true', help='生成完整HTML报告（代替JSON）')
    parser.add_argument('--template', action='store_true', help='生成静态模板HTML')
    args = parser.parse_args()

    if args.template:
        generate_template_html()
        return

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
    # 注意：如果今天是非交易日，仍然需要补全历史缺失数据
    auto_update, today_str = should_auto_update_zt()
    # 如果今天不是交易日但有缺失数据需要补全，仍然应该获取
    missing_dates_exist = len(check_zt_pool_cache(dates)[0]) > 0
    should_fetch = auto_update or missing_dates_exist
    df_zt_pool = get_zt_pool(dates, force_refresh_today=auto_update, today_str=today_str, skip_fetch=not should_fetch)

    # 从实际数据中获取日期列表（排除没有数据的日期）
    if df_zt_pool is not None and len(df_zt_pool) > 0:
        actual_dates = sorted(df_zt_pool['交易日期'].dropna().unique().tolist(), reverse=True)
        actual_dates = [str(int(d)) for d in actual_dates]
        if len(actual_dates) > 0:
            dates = actual_dates
            print(f"  ✓ 实际数据日期: {dates[-1]} 至 {dates[0]}")

    # 概念股票数据使用缓存（不自动更新，需手动触发 update_data.py --concepts）
    df_concept_stock = load_concept_stock_list()

    # 整合热点数据（概念TOP20 + 股票TOP100）
    hot_data = integrate_hot_data(df_hot_concepts, df_hot_stocks, df_concept_stock)

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

    # 获取现有归档列表（只包含有JSON文件的日期）
    archives = get_available_json_archives()

    # 计算今日涨停数量
    today_date = get_actual_latest_date(dates)
    today_date_int = int(today_date) if today_date else None
    today_zt_df = df_zt_pool[df_zt_pool['交易日期'] == today_date_int] if df_zt_pool is not None else pd.DataFrame()
    today_zt_count = len(today_zt_df)

    # 获取韭研公社简图
    JYGS_ZT_image_path, JYGS_ZT_image_date = get_latest_JYGS_ZT_image("static")

    if args.html:
        # 生成完整HTML报告
        print("模式: 生成HTML报告")
        markdown_content = generate_markdown(analysis_result, df_hot_concepts, df_zt_pool, dates, df_concept_stock)
        html_content_archive = generate_html(analysis_result, df_hot_concepts, df_zt_pool, dates, df_concept_stock, archives, static_path="../../static")
        html_content_latest = generate_html(analysis_result, df_hot_concepts, df_zt_pool, dates, df_concept_stock, archives, static_path="static")
        archives = save_report(markdown_content, html_content_archive, html_content_latest, dates)
        print(f"  ✓ 共有 {len(archives)} 个归档文件")
    else:
        # 默认生成JSON数据文件
        print("模式: 生成JSON数据")
        # 使用实际最新交易日（而非"今天"的日期）
        latest_trading_date = dates[0] if dates else today_str
        json_path = save_report_json(
            analysis_result, df_hot_concepts, df_zt_pool, dates, df_concept_stock,
            latest_trading_date, today_zt_count, JYGS_ZT_image_path, JYGS_ZT_image_date, archives
        )
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