"""
股票K线数据库模块
================
功能：
    1. 使用SQLite存储所有股票K线数据
    2. 增量更新（只补缺失数据）
    3. 交易日历管理
    4. 数据完整性检查

使用方法：
    from kline_database import KlineDB

    db = KlineDB()
    db.update_stock_kline('000001')
    db.update_all_stocks_kline()
"""

import sqlite3
import pandas as pd
import json
import os
import time
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

# 获取当前脚本所在目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(SCRIPT_DIR, "data", "stocks_kline.db")
TRADE_CALENDAR_FILE = os.path.join(SCRIPT_DIR, "data", "trade_calendar_2026.json")

# tushare token
TUSHARE_TOKEN = "598a86c768a0f939ed14066d7fb81a34aa1e4f60f47a6c147cdcba2c"


def _stock_code_to_tscode(code: str) -> str:
    """将6位股票代码转成 tushare 格式（如 000001 → 000001.SZ）"""
    code = str(code).zfill(6)
    if code.startswith('6'):
        return f"{code}.SH"
    elif code.startswith('0') or code.startswith('3'):
        return f"{code}.SZ"
    elif code.startswith('4') or code.startswith('8'):
        return f"{code}.BJ"
    return code


class KlineDB:
    """K线数据库操作类"""

    def __init__(self, db_path: str = None):
        """初始化数据库连接"""
        self.db_path = db_path or DB_FILE
        self.pro = None
        self._init_tushare()
        self._init_database()

    def _init_tushare(self):
        """初始化 tushare pro 接口"""
        try:
            import tushare as ts
            ts.set_token(TUSHARE_TOKEN)
            self.pro = ts.pro_api()
        except Exception as e:
            print(f"tushare 初始化失败: {e}")
            self.pro = None

    def fetch_by_tushare(self, stock_code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        使用 tushare pro.daily() 获取日K线数据

        Args:
            stock_code: 股票代码（6位数字）
            start_date: 开始日期，YYYYMMDD 或 YYYY-MM-DD
            end_date: 结束日期，YYYYMMDD 或 YYYY-MM-DD

        Returns:
            DataFrame，字段已映射为 save_kline_data 兼容格式
        """
        if self.pro is None:
            print("tushare 未初始化")
            return pd.DataFrame()

        # 格式化日期
        sd = start_date.replace('-', '')[:8] if start_date else None
        ed = end_date.replace('-', '')[:8] if end_date else None

        # 代码转换
        ts_code = _stock_code_to_tscode(stock_code)

        try:
            df = self.pro.daily(ts_code=ts_code, start_date=sd, end_date=ed)

            if df is None or df.empty:
                return pd.DataFrame()

            # 字段映射
            df = df.rename(columns={
                'vol': 'volume',
                'pct_chg': 'change_pct',
            })

            # trade_date 从 YYYYMMDD 转 YYYY-MM-DD
            df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d').dt.strftime('%Y-%m-%d')

            return df

        except Exception as e:
            print(f"tushare 获取 {stock_code} 失败: {e}")
            return pd.DataFrame()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_database(self):
        """初始化数据库表结构"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # 交易日历表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_calendar (
                    trade_date TEXT PRIMARY KEY,
                    is_trading_day INTEGER DEFAULT 1
                )
            """)

            # 股票列表表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stocks (
                    stock_code TEXT PRIMARY KEY,
                    stock_name TEXT,
                    list_date TEXT,
                    market TEXT
                )
            """)

            # K线数据表（完整保留adata所有字段）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS kline_daily (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    amount REAL,
                    change_pct REAL,
                    change_val REAL,
                    prev_close REAL,
                    turnover_ratio REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, trade_date)
                )
            """)

            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kline_stock ON kline_daily(stock_code)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kline_date ON kline_daily(trade_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kline_stock_date ON kline_daily(stock_code, trade_date)")

            conn.commit()
        finally:
            conn.close()

    # ========== 交易日历操作 ==========

    def load_trade_calendar(self) -> List[str]:
        """从本地文件加载交易日历"""
        if not os.path.exists(TRADE_CALENDAR_FILE):
            return []

        try:
            with open(TRADE_CALENDAR_FILE, 'r') as f:
                dates = json.load(f)
            return [d.replace('-', '') for d in dates]
        except Exception:
            return []

    def save_trade_calendar(self, dates: List[str]):
        """保存交易日历到数据库"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            for date in dates:
                cursor.execute("""
                    INSERT OR REPLACE INTO trade_calendar (trade_date, is_trading_day)
                    VALUES (?, 1)
                """, (date,))
            conn.commit()
        finally:
            conn.close()

    def get_trade_calendar(self, start_date: str = None, end_date: str = None) -> List[str]:
        """获取数据库中的交易日历"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if start_date and end_date:
                cursor.execute("""
                    SELECT trade_date FROM trade_calendar
                    WHERE trade_date >= ? AND trade_date <= ?
                    ORDER BY trade_date
                """, (start_date, end_date))
            elif start_date:
                cursor.execute("""
                    SELECT trade_date FROM trade_calendar
                    WHERE trade_date >= ?
                    ORDER BY trade_date
                """, (start_date,))
            elif end_date:
                cursor.execute("""
                    SELECT trade_date FROM trade_calendar
                    WHERE trade_date <= ?
                    ORDER BY trade_date
                """, (end_date,))
            else:
                cursor.execute("SELECT trade_date FROM trade_calendar ORDER BY trade_date")

            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    # ========== 股票列表操作 ==========

    def save_stocks(self, stocks: List[dict]):
        """保存股票列表"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            for stock in stocks:
                cursor.execute("""
                    INSERT OR REPLACE INTO stocks (stock_code, stock_name, list_date, market)
                    VALUES (?, ?, ?, ?)
                """, (
                    stock.get('code', ''),
                    stock.get('name', ''),
                    stock.get('list_date', ''),
                    stock.get('market', '')
                ))
            conn.commit()
        finally:
            conn.close()

    def get_all_stocks(self) -> List[str]:
        """获取所有股票代码"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT stock_code FROM stocks ORDER BY stock_code")
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    # ========== K线数据操作 ==========

    def save_kline_data(self, stock_code: str, df: pd.DataFrame) -> int:
        """
        保存K线数据到数据库（upsert）

        Args:
            stock_code: 股票代码
            df: K线数据DataFrame

        Returns:
            插入/更新的记录数
        """
        if df is None or df.empty:
            return 0

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            count = 0

            for _, row in df.iterrows():
                trade_date = str(row.get('trade_date', ''))[:10]
                if not trade_date:
                    continue

                cursor.execute("""
                    INSERT OR REPLACE INTO kline_daily (
                        stock_code, trade_date, open, high, low, close, volume,
                        amount, change_pct, change_val, prev_close, turnover_ratio
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    stock_code,
                    trade_date,
                    row.get('open', 0),
                    row.get('high', 0),
                    row.get('low', 0),
                    row.get('close', 0),
                    row.get('volume', 0),
                    row.get('amount', 0),
                    row.get('change_pct', 0),
                    row.get('change', 0) if 'change' in row else row.get('change_val', 0),
                    row.get('pre_close', 0),
                    row.get('turnover_ratio', 0)
                ))
                count += 1

            conn.commit()
            return count
        finally:
            conn.close()

    def get_kline_data(self, stock_code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        获取K线数据

        Args:
            stock_code: 股票代码
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            K线数据DataFrame
        """
        conn = self._get_connection()
        try:
            # 转换日期格式
            start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}" if start_date and len(start_date) == 8 else start_date
            end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if end_date and len(end_date) == 8 else end_date

            cursor = conn.cursor()

            if start_fmt and end_fmt:
                cursor.execute("""
                    SELECT * FROM kline_daily
                    WHERE stock_code = ? AND trade_date >= ? AND trade_date <= ?
                    ORDER BY trade_date
                """, (stock_code, start_fmt, end_fmt))
            elif start_fmt:
                cursor.execute("""
                    SELECT * FROM kline_daily
                    WHERE stock_code = ? AND trade_date >= ?
                    ORDER BY trade_date
                """, (stock_code, start_fmt))
            elif end_fmt:
                cursor.execute("""
                    SELECT * FROM kline_daily
                    WHERE stock_code = ? AND trade_date <= ?
                    ORDER BY trade_date
                """, (stock_code, end_fmt))
            else:
                cursor.execute("""
                    SELECT * FROM kline_daily
                    WHERE stock_code = ?
                    ORDER BY trade_date
                """, (stock_code,))

            rows = cursor.fetchall()
            if not rows:
                return pd.DataFrame()

            columns = rows[0].keys() if hasattr(rows[0], 'keys') else [desc[0] for desc in cursor.description]
            return pd.DataFrame([dict(row) for row in rows], columns=columns)
        finally:
            conn.close()

    def get_existing_dates(self, stock_code: str) -> set:
        """获取某股票已有的交易日期"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT trade_date FROM kline_daily
                WHERE stock_code = ?
            """, (stock_code,))
            return {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()

    def get_missing_dates(self, stock_code: str, all_dates: List[str]) -> List[str]:
        """计算缺失的交易日期"""
        existing = self.get_existing_dates(stock_code)
        # 转换已有日期为YYYYMMDD格式以便比较
        existing_yyyymmdd = {d.replace('-', '') for d in existing}
        return [d for d in all_dates if d not in existing_yyyymmdd]

    # ========== 数据检查 ==========

    def get_data_coverage(self) -> pd.DataFrame:
        """获取每日数据覆盖情况"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT trade_date, COUNT(*) as stock_count
                FROM kline_daily
                GROUP BY trade_date
                ORDER BY trade_date DESC
            """)
            rows = cursor.fetchall()
            return pd.DataFrame([{'trade_date': r[0], 'stock_count': r[1]} for r in rows])
        finally:
            conn.close()

    def get_stock_coverage(self, stock_code: str) -> dict:
        """获取某股票数据覆盖情况"""
        existing = self.get_existing_dates(stock_code)
        all_dates = self.load_trade_calendar()

        return {
            'stock_code': stock_code,
            'total_dates': len(all_dates),
            'existing_count': len(existing),
            'missing_count': len(all_dates) - len(existing),
            'date_range': f"{min(existing) if existing else 'N/A'} ~ {max(existing) if existing else 'N/A'}"
        }

    def repair_missing_kline(self, stock_code: str, dates: List[str]) -> int:
        """
        修复缺失的K线数据（增量更新）

        Args:
            stock_code: 股票代码
            dates: 需要补全的日期列表

        Returns:
            更新记录数
        """
        if not dates:
            return 0

        # 获取需要的数据范围
        start_date = min(dates)
        end_date = max(dates)

        # 使用 tushare 获取数据
        df = self.fetch_by_tushare(stock_code, start_date, end_date)

        if df is not None and not df.empty:
            return self.save_kline_data(stock_code, df)

        return 0

    # ========== 批量操作 ==========

    def update_stock_kline(self, stock_code: str) -> int:
        """
        更新单只股票K线数据（增量更新）

        Args:
            stock_code: 股票代码

        Returns:
            更新记录数
        """
        # 获取所有交易日
        all_dates = self.load_trade_calendar()
        if not all_dates:
            print(f"无法获取交易日历")
            return 0

        # 计算缺失日期
        missing_dates = self.get_missing_dates(stock_code, all_dates)
        if not missing_dates:
            return 0

        # 增量获取数据
        return self.repair_missing_kline(stock_code, missing_dates)


def get_zt_pool_stocks(days: int = 20) -> List[str]:
    """从涨停池获取股票代码列表"""
    import pandas as pd
    from datetime import datetime, timedelta

    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    ZT_POOL_DIR = os.path.join(SCRIPT_DIR, "data", "zt_pool")

    today_str = datetime.now().strftime('%Y%m%d')

    # 获取近N个交易日
    cache_file = os.path.join(SCRIPT_DIR, "data", 'trade_calendar_2026.json')
    trading_dates = []

    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                trading_dates = json.load(f)
            trading_dates = [d.replace('-', '') for d in trading_dates]
            trading_dates = [d for d in trading_dates if d <= today_str][::-1][:days]
        except Exception:
            pass

    if not trading_dates:
        return []

    all_codes = set()

    for date in trading_dates:
        file_path = os.path.join(ZT_POOL_DIR, f"{date}.csv")
        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path)
                if '代码' in df.columns:
                    codes = df['代码'].dropna().astype(int).astype(str).str.zfill(6)
                    all_codes.update(codes.tolist())
            except Exception:
                pass

    return sorted(list(all_codes))


def update_all_stocks_kline(stock_codes: List[str] = None, db: KlineDB = None,
                              start_date: str = None, end_date: str = None) -> dict:
    """
    批量更新所有股票K线数据（增量更新）

    Args:
        stock_codes: 股票代码列表，None则使用数据库中的所有股票
        db: KlineDB实例
        start_date: 开始日期 YYYYMMDD，默认30个交易日前
        end_date: 结束日期 YYYYMMDD，默认今天

    Returns:
        更新统计 {"total": 6000, "success": 5900, "failed": 100, "updated": 150000}
    """
    if db is None:
        db = KlineDB()

    # 获取股票列表
    if stock_codes is None:
        stock_codes = db.get_all_stocks()

    if not stock_codes:
        print("没有股票可更新")
        return {"total": 0, "success": 0, "failed": 0, "updated": 0}

    # 确定日期范围
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')
    if start_date is None:
        # 默认取近30个交易日
        trade_dates = db.load_trade_calendar()
        # 取最近30个（日期是倒序的，所以取前30个）
        if trade_dates:
            start_date = trade_dates[min(29, len(trade_dates)-1)]
        else:
            start_date = (datetime.now() - timedelta(days=45)).strftime('%Y%m%d')

    total = len(stock_codes)
    success = 0
    failed = 0
    total_updated = 0

    print(f"开始更新 {total} 只股票的K线数据 ({start_date} ~ {end_date})...")
    print("-" * 60)

    for i, code in enumerate(stock_codes):
        try:
            # 检查缺失日期
            all_dates = db.load_trade_calendar()
            missing_dates = [d for d in all_dates if d >= start_date and d <= end_date]

            # 实际检查数据库中的日期
            existing = db.get_existing_dates(code)
            existing_fmt = {d.replace('-', '') for d in existing}
            missing = [d for d in missing_dates if d not in existing_fmt]

            if not missing:
                success += 1
                continue

            # 使用 tushare 获取缺失的数据
            df = db.fetch_by_tushare(code, min(missing), max(missing))

            if df is not None and not df.empty:
                count = db.save_kline_data(code, df)
                total_updated += count
                success += 1
                status = f"✓ +{count}"
            else:
                failed += 1
                status = "✗ 无数据"

        except Exception as e:
            failed += 1
            status = f"✗ {type(e).__name__}"

        if (i + 1) % 100 == 0 or status.startswith("✗"):
            print(f"[{i+1}/{total}] {code} {status}")

        # 控制 tushare 调用频率
        if i < total - 1:
            time.sleep(0.3)

    print("-" * 60)
    print(f"完成! 成功: {success}/{total}, 失败: {failed}, 更新: {total_updated} 条")

    return {"total": total, "success": success, "failed": failed, "updated": total_updated}


# ========== 测试代码 ==========

if __name__ == "__main__":
    print("=" * 60)
    print("K线数据库测试")
    print("=" * 60)

    db = KlineDB()

    # 测试数据库路径
    print(f"数据库路径: {db.db_path}")

    # 检查数据覆盖
    coverage = db.get_data_coverage()
    print(f"\n当前数据覆盖: {len(coverage)} 个交易日")

    if not coverage.empty:
        print(f"最新数据日期: {coverage.iloc[0]['trade_date']}")
        print(f"股票数量: {coverage.iloc[0]['stock_count']}")

    print("\n测试完成!")