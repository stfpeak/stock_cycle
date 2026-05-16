"""
涨停板分类逻辑模块
=================
功能：
    1. 从涨停池分析近20日涨停股票
    2. 对涨停股票进行6种分类：
        一: 3连板及以上
        二: 2连板
        三: 近30交易日仅1次涨停
        四: 正常非连续涨停
        五: 近5交易日炸板
        六: 创业板/科创版近5日最大涨幅>10%

使用方法：
    python zt_classifier.py
"""

import pandas as pd
import json
import os
from datetime import datetime, timedelta
import sys

# 获取当前脚本所在目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 数据目录
ZT_POOL_DIR = os.path.join(SCRIPT_DIR, "data", "zt_pool")
KLINE_DATA_DIR = os.path.join(SCRIPT_DIR, "data", "kline_data")
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports")

# 创业板/科创版代码前缀
GEM_MARKET_CODES = {'300', '301', '688'}


def get_beijing_now():
    """获取当前北京时间"""
    return datetime.now()


def get_today_str():
    """获取今天的日期字符串 YYYYMMDD"""
    return get_beijing_now().strftime('%Y%m%d')


def get_trading_dates_around(days=30):
    """获取近N个交易日期"""
    today_str = get_today_str()

    # 尝试从本地缓存读取
    cache_file = os.path.join(SCRIPT_DIR, "data", 'trade_calendar_2026.json')
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                trading_dates = json.load(f)
            trading_dates = [d.replace('-', '') for d in trading_dates]
            trading_dates = [d for d in trading_dates if d <= today_str][::-1]
            if len(trading_dates) >= days:
                return trading_dates[:days]
        except Exception:
            pass

    # 尝试从API获取
    try:
        import adata
        df = adata.stock.info.trade_calendar(year=2026)
        df_trading = df[df['trade_status'] == 1]
        trading_dates = df_trading['trade_date'].astype(str).tolist()
        trading_dates = [d.replace('-', '') for d in trading_dates]
        trading_dates = [d for d in trading_dates if d <= today_str][::-1]
        return trading_dates[:days] if len(trading_dates) >= days else trading_dates
    except Exception as e:
        print(f"获取交易日历失败: {e}")
        # 备用逻辑：工作日
        dates = []
        current = datetime.now()
        while len(dates) < days:
            if current.weekday() < 5:
                dates.append(current.strftime('%Y%m%d'))
            current -= timedelta(days=1)
        return dates


def load_zt_pool_data(dates):
    """
    加载涨停池数据

    Args:
        dates: 日期列表

    Returns:
        DataFrame: 涨停池数据
    """
    all_data = []

    for date in dates:
        file_path = os.path.join(ZT_POOL_DIR, f"{date}.csv")
        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path)
                df['交易日期'] = int(date)
                all_data.append(df)
            except Exception as e:
                print(f"读取 {date} 数据失败: {e}")

    if all_data:
        df = pd.concat(all_data, ignore_index=True)
        df['代码'] = pd.to_numeric(df['代码'], errors='coerce').astype('Int64')
        df['代码_str'] = df['代码'].apply(lambda x: str(int(x)).zfill(6) if pd.notna(x) else '')
        return df

    return None


def is_gem_or_star(code):
    """判断是否为创业板或科创版"""
    code_str = str(code)
    return code_str.startswith('300') or code_str.startswith('301') or code_str.startswith('688')


def detect_zaban_from_kline(kline_data, dates_5d):
    """
    从K线数据检测炸板

    炸板定义：日内曾涨停但又打开（收盘价 < 涨停价）
    通过K线判断：最高价 == 涨停价附近（涨幅接近10%或20%），但收盘价明显低于涨停价

    Args:
        kline_data: K线数据字典
        dates_5d: 近5个交易日日期列表

    Returns:
        bool: 是否炸板
    """
    if not kline_data or 'klines' not in kline_data:
        return False

    klines = kline_data['klines']
    if not klines:
        return False

    for kline in klines:
        date = kline.get('date', '')
        # 转换日期格式以便比较
        date_compare = date.replace('-', '')
        if date_compare not in dates_5d:
            continue

        close = kline.get('close', 0)
        high = kline.get('high', 0)
        open_price = kline.get('open', 0)

        if close <= 0 or high <= 0:
            continue

        # 计算日内最大涨幅
        prev_close = kline.get('prev_close', close)
        if prev_close <= 0:
            prev_close = open_price if open_price > 0 else close

        max_rise_pct = (high - prev_close) / prev_close * 100 if prev_close > 0 else 0

        # 炸板条件：日内曾涨停（最高价涨幅>9%），但收盘涨幅明显小于涨停
        rise_pct = (close - prev_close) / prev_close * 100 if prev_close > 0 else 0

        # 判断是否为涨停附近（主板10%，创业板/科创版20%）
        if max_rise_pct >= 9.5:
            # 最高价接近涨停，但收盘涨幅远小于最高涨幅
            if rise_pct < max_rise_pct - 3:  # 收盘涨幅比最高涨幅小3%以上
                return True

    return False


def detect_10pct_rise_from_kline(kline_data, dates_5d):
    """
    从K线数据检测创业板/科创版近5日最大涨幅>10%

    Args:
        kline_data: K线数据字典
        dates_5d: 近5个交易日日期列表

    Returns:
        bool: 是否最大涨幅>10%
    """
    if not kline_data or 'klines' not in kline_data:
        return False

    klines = kline_data['klines']
    if not klines:
        return False

    for kline in klines:
        date = kline.get('date', '')
        date_compare = date.replace('-', '')
        if date_compare not in dates_5d:
            continue

        high = kline.get('high', 0)
        open_price = kline.get('open', 0)

        if high <= 0:
            continue

        # 使用开盘价作为参考（更接近"盘中"概念）
        prev_close = kline.get('prev_close', open_price)
        if prev_close <= 0:
            prev_close = open_price

        max_rise_pct = (high - prev_close) / prev_close * 100 if prev_close > 0 else 0

        if max_rise_pct > 10:
            return True

    return False


def classify_stocks(df_zt_pool, dates_20d, dates_30d, dates_5d):
    """
    分类涨停股票

    分类标准:
    一: 3连板及以上 (lianban >= 3)
    二: 2连板 (lianban == 2)
    三: 近30交易日仅1次涨停 (zt_count == 1)
    四: 正常非连续涨停 (其他)
    五: 近5交易日炸板 (zaban)
    六: 创业板/科创版近5日最大涨幅>10% (盘中最高)

    Args:
        df_zt_pool: 涨停池数据
        dates_20d: 近20个交易日日期列表
        dates_30d: 近30个交易日日期列表
        dates_5d: 近5个交易日日期列表

    Returns:
        dict: 分类结果
    """
    categories = {
        'lianban_3_plus': [],   # 3连板+
        'lianban_2': [],        # 2连板
        'single_zt': [],        # 仅1次涨停
        'normal': [],           # 正常非连续
        'zaban_5d': [],         # 近5日炸板
        'chuangke_10pct': []    # 创业板/科创版10%+
    }

    stocks_info = {}  # {code: {name, zt_dates, max_lianban, ...}}

    if df_zt_pool is None:
        return categories, stocks_info

    # 近30日有涨停的股票
    df_30d = df_zt_pool[df_zt_pool['交易日期'].astype(str).str.zfill(6).isin(dates_30d)]

    # 按股票代码分组分析
    grouped = df_30d.groupby('代码_str')

    for code, group in grouped:
        if not code or len(code) != 6:
            continue

        name = group['名称'].iloc[0] if '名称' in group.columns else code
        zt_dates = sorted(group['交易日期'].astype(str).tolist())

        # 最大连板数
        max_lianban = group['连板数'].max() if '连板数' in group.columns else 1

        # 涨停次数
        zt_count = len(group)

        # 近20日涨停记录（用于判断是否在近20日内）
        zt_dates_20d = [d for d in zt_dates if d in dates_20d]

        # 只分析近20日有涨停的股票
        if not zt_dates_20d:
            continue

        # 炸板检测
        is_zaban = False
        if code in stocks_info and stocks_info[code].get('kline_data'):
            is_zaban = detect_zaban_from_kline(stocks_info[code]['kline_data'], dates_5d)

        # 创业板/科创版10%检测
        is_10pct = False
        if is_gem_or_star(code):
            if code in stocks_info and stocks_info[code].get('kline_data'):
                is_10pct = detect_10pct_rise_from_kline(stocks_info[code]['kline_data'], dates_5d)

        # 构建股票信息
        stock_info = {
            'name': name,
            'code': code,
            'zt_dates': zt_dates,
            'zt_dates_20d': zt_dates_20d,
            'max_lianban': max_lianban,
            'zt_count': zt_count,
            'is_zaban': is_zaban,
            'is_10pct': is_10pct,
            'lianban_records': []  # 每次涨停的连板数记录
        }

        for _, row in group.iterrows():
            lb = int(row['连板数']) if pd.notna(row.get('连板数')) else 1
            stock_info['lianban_records'].append({
                'date': str(row['交易日期']),
                'lianban': lb,
                'first_seal': str(row.get('首次封板时间', ''))
            })

        stocks_info[code] = stock_info

        # 分类
        if max_lianban >= 3:
            categories['lianban_3_plus'].append(code)
        elif max_lianban == 2:
            categories['lianban_2'].append(code)
        elif zt_count == 1:
            categories['single_zt'].append(code)
        else:
            categories['normal'].append(code)

        if is_zaban:
            if code not in categories['zaban_5d']:
                categories['zaban_5d'].append(code)

        if is_10pct:
            if code not in categories['chuangke_10pct']:
                categories['chuangke_10pct'].append(code)

    return categories, stocks_info


def build_category_stocks_list(categories, stocks_info):
    """
    构建每个分类的股票详情列表

    Args:
        categories: 分类字典
        stocks_info: 股票信息字典

    Returns:
        dict: 每个分类的股票详情列表
    """
    result = {}

    category_names = {
        'lianban_3_plus': '3连板+',
        'lianban_2': '2连板',
        'single_zt': '仅1次涨停',
        'normal': '正常非连续',
        'zaban_5d': '近5日炸板',
        'chuangke_10pct': '创业板/科创版10%+'
    }

    for cat_key, codes in categories.items():
        stocks_list = []
        for code in codes:
            if code in stocks_info:
                info = stocks_info[code]
                stocks_list.append({
                    'code': code,
                    'name': info['name'],
                    'max_lianban': info['max_lianban'],
                    'zt_count': info['zt_count'],
                    'zt_dates': info['zt_dates'],
                    'zt_dates_20d': info['zt_dates_20d'],
                    'is_gem_or_star': is_gem_or_star(code),
                    'kline_file': f"data/kline_data/{code}.json"
                })

        # 排序：按近20日涨停日期排序
        stocks_list.sort(key=lambda x: (x['zt_dates_20d'][0] if x['zt_dates_20d'] else '', x['code']))

        result[cat_key] = {
            'name': category_names.get(cat_key, cat_key),
            'count': len(stocks_list),
            'stocks': stocks_list
        }

    return result


def load_kline_data_safe(code):
    """
    安全加载K线数据

    Args:
        code: 股票代码

    Returns:
        dict: K线数据或None
    """
    file_path = os.path.join(KLINE_DATA_DIR, f"{code}.json")
    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def enrich_stocks_with_kline(stocks_info, dates_5d):
    """
    为股票信息补充K线数据并检测炸板和10%涨幅

    Args:
        stocks_info: 股票信息字典
        dates_5d: 近5个交易日日期列表

    Returns:
        dict: 更新后的股票信息
    """
    for code in stocks_info:
        kline_data = load_kline_data_safe(code)
        if kline_data:
            stocks_info[code]['kline_data'] = kline_data

            # 检测炸板
            is_zaban = detect_zaban_from_kline(kline_data, dates_5d)
            stocks_info[code]['is_zaban'] = is_zaban

            # 检测创业板/科创版10%
            if is_gem_or_star(code):
                is_10pct = detect_10pct_rise_from_kline(kline_data, dates_5d)
                stocks_info[code]['is_10pct'] = is_10pct

    return stocks_info


def classify_zt_stocks(days_20=20, days_30=30, days_5=5):
    """
    涨停板分类主函数

    Args:
        days_20: 近20日
        days_30: 近30日
        days_5: 近5日

    Returns:
        dict: 分类结果
    """
    print("=" * 60)
    print("涨停板分类分析")
    print("=" * 60)

    # 获取交易日期
    dates_all = get_trading_dates_around(days_30)
    dates_30d = dates_all[:days_30]
    dates_20d = dates_all[:days_20]
    dates_5d = dates_all[:days_5]

    print(f"分析日期范围:")
    print(f"  近{days_30}日: {dates_30d[-1]} ~ {dates_30d[0]}")
    print(f"  近{days_20}日: {dates_20d[-1]} ~ {dates_20d[0]}")
    print(f"  近{days_5}日: {dates_5d[-1]} ~ {dates_5d[0]}")

    # 加载涨停池数据
    print("\n加载涨停池数据...")
    df_zt_pool = load_zt_pool_data(dates_30d)
    if df_zt_pool is not None:
        print(f"  加载 {len(df_zt_pool)} 条涨停记录")
    else:
        print("  未找到涨停池数据")
        return None

    # 分类
    print("\n分类涨停股票...")
    categories, stocks_info = classify_stocks(df_zt_pool, dates_20d, dates_30d, dates_5d)

    # 补充K线数据
    print("\n加载K线数据并检测炸板/10%涨幅...")
    stocks_info = enrich_stocks_with_kline(stocks_info, dates_5d)

    # 更新分类（加入炸板和10%涨幅）
    for code, info in stocks_info.items():
        if info.get('is_zaban') and code not in categories['zaban_5d']:
            categories['zaban_5d'].append(code)
        if info.get('is_10pct') and code not in categories['chuangke_10pct']:
            categories['chuangke_10pct'].append(code)

    # 构建结果
    result = {
        'date': get_today_str(),
        'generated_at': get_beijing_now().strftime('%H:%M:%S'),
        'dates_20d': dates_20d,
        'dates_30d': dates_30d,
        'dates_5d': dates_5d,
        'categories': build_category_stocks_list(categories, stocks_info),
        'stocks_info': {
            code: {
                'name': info['name'],
                'zt_dates': info['zt_dates'],
                'zt_dates_20d': info['zt_dates_20d'],
                'max_lianban': info['max_lianban'],
                'zt_count': info['zt_count'],
                'is_gem_or_star': is_gem_or_star(code),
                'kline_file': f"data/kline_data/{code}.json"
            }
            for code, info in stocks_info.items()
        }
    }

    # 打印统计
    print("\n分类统计:")
    for cat_key, cat_data in result['categories'].items():
        print(f"  {cat_data['name']}: {cat_data['count']} 只")

    # 保存结果
    os.makedirs(REPORTS_DIR, exist_ok=True)
    output_file = os.path.join(REPORTS_DIR, "zt_classified.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {output_file}")

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="涨停板分类分析")
    parser.add_argument('--days-20', type=int, default=20, help='近20日（默认20）')
    parser.add_argument('--days-30', type=int, default=30, help='近30日（默认30）')
    parser.add_argument('--days-5', type=int, default=5, help='近5日（默认5）')

    args = parser.parse_args()

    result = classify_zt_stocks(args.days_20, args.days_30, args.days_5)

    if result:
        print("\n分类完成!")
        print(f"近20日涨停股票总数: {len(result['stocks_info'])}")
    else:
        print("\n分类失败!")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
