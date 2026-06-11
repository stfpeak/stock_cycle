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
        # 迁移修复：确保UNIQUE约束存在，清理历史重复数据
        self._migrate_schema()

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

    def _migrate_schema(self):
        """迁移修复：确保UNIQUE约束存在，清理重复数据"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # 检查当前表是否有UNIQUE约束
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='kline_daily'")
            row = cursor.fetchone()
            if row and 'UNIQUE' not in row[0]:
                print("检测到kline_daily表缺少UNIQUE约束，正在迁移修复...")
                # 重建表：去重 + 加UNIQUE约束
                cursor.executescript("""
                    CREATE TABLE kline_daily_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stock_code TEXT NOT NULL,
                        trade_date TEXT NOT NULL,
                        open REAL, high REAL, low REAL, close REAL,
                        volume REAL, amount REAL, change_pct REAL,
                        change_val REAL, prev_close REAL, turnover_ratio REAL,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(stock_code, trade_date)
                    );
                    INSERT OR IGNORE INTO kline_daily_new
                        (stock_code, trade_date, open, high, low, close,
                         volume, amount, change_pct, change_val, prev_close, turnover_ratio)
                    SELECT stock_code, trade_date, open, high, low, close,
                           volume, amount, change_pct, change_val, prev_close, turnover_ratio
                    FROM kline_daily;
                    DROP TABLE kline_daily;
                    ALTER TABLE kline_daily_new RENAME TO kline_daily;
                    CREATE INDEX IF NOT EXISTS idx_kline_stock ON kline_daily(stock_code);
                    CREATE INDEX IF NOT EXISTS idx_kline_date ON kline_daily(trade_date);
                    CREATE INDEX IF NOT EXISTS idx_kline_stock_date ON kline_daily(stock_code, trade_date);
                """)
                conn.commit()
                print("  迁移完成，重复数据已清理")
        finally:
            conn.close()

    def deduplicate(self):
        """清理kline_daily表中的重复记录，只保留每条(stock_code, trade_date)的最新一条"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM kline_daily WHERE id NOT IN (
                    SELECT MIN(id) FROM kline_daily GROUP BY stock_code, trade_date
                )
            """)
            deleted = cursor.rowcount
            conn.commit()
            if deleted > 0:
                print(f"清理了 {deleted} 条重复记录")
            return deleted
        finally:
            conn.close()

    def vacuum(self):
        """回收数据库空闲空间（压缩文件大小）"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            before = os.path.getsize(self.db_path)
            cursor.execute("VACUUM")
            conn.commit()
            after = os.path.getsize(self.db_path)
            saved = before - after
            print(f"VACUUM完成: {before/1024/1024:.0f}M → {after/1024/1024:.0f}M (节省{saved/1024/1024:.0f}M)")
            return saved
        finally:
            conn.close()

    def reclaim_space(self):
        """一键回收空间：去重 + 重建索引 + VACUUM"""
        print("=== 数据库空间回收 ===")
        before = os.path.getsize(self.db_path)
        deleted = self.deduplicate()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("REINDEX")
            conn.commit()
        finally:
            conn.close()
        saved = self.vacuum()
        print(f"回收完成: 删除{deleted}条重复, 节省{saved/1024/1024:.0f}M")
        return {'deleted': deleted, 'saved': saved}

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
    批量更新所有股票K线数据（按天批量拉取，快！）

    注意：此方法已转为按天批量拉取（pro.daily(trade_date=...)），
    单次请求获取全市场5000+只股票，比逐只更新快百倍。

    也推荐使用 update_data_fast.py 进行快速更新：
        python update_data_fast.py

    Args:
        stock_codes: 保留参数，实际忽略（按天拉取全市场）
        db: KlineDB实例
        start_date: 保留参数，忽略
        end_date: 保留参数，忽略

    Returns:
        更新统计
    """
    # 直接调用 update_data_fast 的按天批量拉取（一次API获取全市场5000+只）
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        import update_data_fast

        print("使用按天批量拉取模式（单次请求获取全市场5000+只股票）...")
        print()

        # Step 1: 扩展交易日历
        added = update_data_fast.extend_trade_calendar()

        # Step 2: 检查缺失
        missing = update_data_fast.get_db_missing_dates()

        if not missing:
            print("所有数据已是最新，无需更新")
            return {"total": 0, "success": 0, "failed": 0, "updated": 0}

        # Step 3: 按天批量拉取
        print(f"缺失 {len(missing)} 个交易日，开始拉取...")
        result = update_data_fast.fetch_and_save_missing_dates(missing, delay=0.6)

        print(f"完成! 成功: {result.get('success', 0)}/{len(missing)} 天, "
              f"新增 {result.get('records', 0)} 条记录")
        return {
            'total': len(missing),
            'success': result.get('success', 0),
            'failed': len(missing) - result.get('success', 0),
            'updated': result.get('records', 0)
        }
    except Exception as e:
        print(f"按天批量拉取出错: {e}")
        import traceback
        traceback.print_exc()
        return {"total": 0, "success": 0, "failed": 0, "updated": 0}


# ========== 测试代码 ==========

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == '--reclaim':
        db = KlineDB()
        db.reclaim_space()
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == '--info':
        db = KlineDB()
        print("=" * 60)
        print("K线数据库信息")
        print("=" * 60)
        print(f"数据库路径: {db.db_path}")
        size_mb = os.path.getsize(db.db_path) / 1024 / 1024
        print(f"文件大小: {size_mb:.0f} MB")

        conn = db._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM kline_daily")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT stock_code) FROM kline_daily")
            stocks = cursor.fetchone()[0]
            cursor.execute("SELECT MAX(trade_date) FROM kline_daily")
            last_date = cursor.fetchone()[0]
            cursor.execute("SELECT MIN(trade_date) FROM kline_daily")
            first_date = cursor.fetchone()[0]
            cursor.execute("PRAGMA freelist_count")
            freelist = cursor.fetchone()[0]

            print(f"总记录数: {total:,}")
            print(f"股票数量: {stocks}")
            print(f"日期范围: {first_date} ~ {last_date}")
            print(f"空闲页数: {freelist}  (浪费{freelist * 4096 / 1024 / 1024:.0f}M)")
        finally:
            conn.close()

        sys.exit(0)