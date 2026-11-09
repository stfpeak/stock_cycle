"""
更新涨停数据系统 - 获取近10个交易日数据，按天保存JSON，全量重建索引

用法:  python update_zt_data.py

输出:
  zt_data/YYYY-MM-DD.json          每天涨停数据（数组）
  zt_data/index.json               股票索引: stock_code → {stock_name, dates[]}
  zt_data/reason_index.json        原因索引: reason_tag → [{date, stock_code, ...}]
"""
import levistock as lk
import requests
import json
import os
import time
from datetime import datetime, timedelta

# 超时补丁
import levistock.stock.stock_fupanla_kph as kph_mod
def patched_post(host, params):
    r = requests.post(host, data=params, headers=kph_mod._HEADERS, timeout=30)
    return r.json()
kph_mod._post = patched_post

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "zt_data")

def ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def clean(val):
    return str(val).replace("\r\n", "").replace("\n", "").replace("\r", "").strip()

def get_reason_brief(detail):
    """从 reason_detail 提取简短描述（分号前的内容）"""
    if not detail:
        return ""
    detail = clean(detail)
    # 取第一个分号或换行前的内容
    for sep in ["；", ";", "\n"]:
        idx = detail.find(sep)
        if idx > 0:
            return detail[:idx].strip()
    return detail[:80] if len(detail) > 80 else detail

def enrich_first_times(records, date_fmt):
    """用 akshare 历史涨停池为每条记录补充首次封板时间 first_time（HHMMSS int，无则 999999）。
    失败/无数据不阻断（保留原记录）。akshare 不可用时由服务端运行时回写路径兜底（_kpl_patch_dayfile_first_times）。"""
    try:
        import akshare as ak
        import pandas as pd
        df = ak.stock_zt_pool_em(date=date_fmt.replace("-", ""))
        ft = {}
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                code = str(int(row["代码"])).zfill(6)
                v = int(row["首次封板时间"]) if pd.notna(row.get("首次封板时间")) else 999999
                if 0 < v < 999999:
                    ft[code] = v
        if ft:
            hit = 0
            for rec in records:
                code = str(rec.get("stock_code", "")).zfill(6)
                if code in ft:
                    rec["first_time"] = ft[code]
                    hit += 1
            if hit:
                print(f"  akshare补充涨停时间 {hit}/{len(records)}")
                return True
    except Exception as e:
        print(f"  涨停时间补充失败(忽略): {e}")
    return False


def fetch_day_data(date_fmt, enrich=True, attempts=3):
    """获取单日涨停数据，返回记录列表（附 akshare first_time 封板时间，供时间轴稳定显示）"""
    data = None
    for attempt in range(attempts):
        try:
            data = lk.get_his_limit_resumption(date=date_fmt, st=500, index=0)
            break
        except Exception as e:
            print(f"  超时({attempt+1}): {e}", end=" ", flush=True)
            time.sleep(3)

    if not data:
        print("  → 跳过（无数据）")
        return []

    zt_count = data.get("nums", {}).get("ZT", 0)
    records = []
    for plate in data.get("list", []):
        plate_code = plate.get("ZSCode", "")
        plate_name = plate.get("ZSName", "")
        for s in plate.get("StockList", []):
            while len(s) < 18:
                s.append("")
            reason_detail = clean(s[17]) if len(s) > 17 else ""
            reason_tag = clean(s[16]) if len(s) > 16 else ""
            record = {
                "date": date_fmt,
                "plate_code": plate_code,
                "plate_name": plate_name,
                "stock_code": s[0],
                "stock_name": s[1],
                "lianban_desc": s[9] if len(s) > 9 else "",
                "lianban_count": int(s[10]) if len(s) > 10 and str(s[10]).isdigit() else 1,
                "concepts": clean(s[11]) if len(s) > 11 else "",
                "reason_tag": reason_tag,
                "reason_brief": get_reason_brief(reason_detail),
                "reason_detail": reason_detail,
            }
            records.append(record)

    # 附 akshare 首次封板时间 first_time（无则 999999），供今日涨停时间轴稳定排序/标注
    if enrich:
        enrich_first_times(records, date_fmt)
    for rec in records:
        rec.setdefault("first_time", 999999)

    print(f"  涨停{zt_count} 记录{len(records)}")
    return records

def save_day_json(date_fmt, records):
    """保存单日数据到 JSON 文件"""
    filepath = os.path.join(DATA_DIR, f"{date_fmt}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  已保存: {filepath}")
    return filepath

def rebuild_index():
    """遍历所有日JSON，全量重建 index.json 和 reason_index.json"""
    print("\n=== 全量重建索引 ===")

    index = {}        # stock_code → {stock_name, dates: set}
    reason_index = {} # reason_tag → [{date, stock_code, stock_name, plate_name, reason_brief}]

    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith(".json") or fname in ("index.json", "reason_index.json"):
            continue

        date_str = fname.replace(".json", "")
        filepath = os.path.join(DATA_DIR, fname)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                records = json.load(f)
        except Exception as e:
            print(f"  跳过 {fname}: {e}")
            continue

        for rec in records:
            code = rec.get("stock_code", "")
            name = rec.get("stock_name", "")
            tag = rec.get("reason_tag", "")

            # 股票索引
            if code:
                if code not in index:
                    index[code] = {"stock_name": name, "dates": []}
                if date_str not in index[code]["dates"]:
                    index[code]["dates"].append(date_str)

            # 原因索引
            if tag:
                entry = {
                    "date": date_str,
                    "stock_code": code,
                    "stock_name": name,
                    "plate_name": rec.get("plate_name", ""),
                    "reason_brief": rec.get("reason_brief", ""),
                }
                reason_index.setdefault(tag, []).append(entry)

    # 写 index.json
    idx_path = os.path.join(DATA_DIR, "index.json")
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"  index.json: {len(index)} 只股票")

    # 写 reason_index.json
    ridx_path = os.path.join(DATA_DIR, "reason_index.json")
    with open(ridx_path, "w", encoding="utf-8") as f:
        json.dump(reason_index, f, ensure_ascii=False, indent=2)
    print(f"  reason_index.json: {len(reason_index)} 个原因标签")

def main():
    ensure_dir()

    # 获取最近10个交易日
    all_days = lk.get_trade_days(n=30)
    today_str = datetime.now().strftime("%Y%m%d")
    trade_days = [d for d in all_days if d <= today_str][-10:]

    print(f"交易日: {[f'{d[:4]}-{d[4:6]}-{d[6:]}' for d in trade_days]}")
    print()

    for date_ymd in trade_days:
        date_fmt = f"{date_ymd[:4]}-{date_ymd[4:6]}-{date_ymd[6:]}"
        out_path = os.path.join(DATA_DIR, f"{date_fmt}.json")

        # 如果文件已存在则跳过（防止重复请求）
        if os.path.exists(out_path):
            print(f"  {date_fmt} 已存在，跳过")
            continue

        print(f"  {date_fmt} ...", end=" ", flush=True)
        records = fetch_day_data(date_fmt)
        if records:
            save_day_json(date_fmt, records)
        time.sleep(2)  # 请求间隔

    # 全量重建索引
    rebuild_index()
    print("\n完成!")


if __name__ == "__main__":
    main()
