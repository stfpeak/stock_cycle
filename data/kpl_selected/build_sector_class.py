#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把开盘红「精选板块 × 成分股」每日 CSV（stocks_YYYY-MM-DD.csv，可多日）建成查询库 data/kpl_selected/sector_class.db。

用法: python3 build_sector_class.py [stocks_*.csv ...]（默认读本目录全部 stocks_*.csv）
表：
  stock(code, name, last_date)                       股票信息（名称取最近一次出现）
  stock_plate(code, name, plate_id, plate_name, tags, first_date, last_date, cur)
                                                      股票×板块（一只股票多个板块）；cur=1 表示在最新一期快照里仍属该板块
  stock_tag(code, tag)                                股票×tags（一只股票多个 tag，各期快照取并集）
  plate_info(plate_id, plate_name, stock_count)      板块在最新快照里的成分股数
  tag_home(tag, plate_name, coverage, n)             标签的「归属板块」——带该标签的股票里 ≥80% 都在该板块（标签至少 5 只股票），
                                                      如 固态电池 → 锂电池；覆盖率相同取成分股更少的板块
涨停分类（/api/zt_classify）与个股查询（/api/sq_*）都读这个库。
"""
import csv, glob, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def split_tags(s):
    return [t.strip() for t in (s or '').replace(',', '、').split('、') if t.strip()]


def main():
    files = sorted(sys.argv[1:] or glob.glob(os.path.join(HERE, 'stocks_*.csv')))
    if not files:
        sys.exit('找不到 stocks_*.csv')
    plate_rows, stock, tags = {}, {}, {}
    latest_date = None
    for src in files:                                   # 日期升序，后者覆盖前者
        with open(src, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                code, d = str(r['code']).strip().zfill(6), r['date']
                latest_date = max(latest_date or d, d)
                key = (code, r['plate_id'])
                old = plate_rows.get(key)
                plate_rows[key] = [code, (r.get('name') or '').strip(), r['plate_id'], r['plate_name'],
                                   (r.get('tags') or '').strip(), old[5] if old else d, d]
                if (r.get('name') or '').strip():
                    stock[code] = ((r.get('name') or '').strip(), d)
                for t in split_tags(r.get('tags')):          # 各期 tags 取并集（最近一期的排前面，旧的追加在后）
                    if t not in tags.setdefault(code, []):
                        tags[code].append(t)
    db = os.path.join(HERE, 'sector_class.db')
    tmp = db + '.tmp'
    if os.path.exists(tmp):
        os.remove(tmp)
    conn = sqlite3.connect(tmp)
    conn.executescript('''
        CREATE TABLE stock (code TEXT PRIMARY KEY, name TEXT, last_date TEXT);
        CREATE TABLE stock_plate (code TEXT, name TEXT, plate_id TEXT, plate_name TEXT, tags TEXT,
                                  first_date TEXT, last_date TEXT, cur INTEGER, PRIMARY KEY (code, plate_id));
        CREATE INDEX idx_sp_plate ON stock_plate(plate_id);
        CREATE INDEX idx_sp_name ON stock_plate(plate_name);
        CREATE TABLE stock_tag (code TEXT, tag TEXT, PRIMARY KEY (code, tag));
        CREATE INDEX idx_st_tag ON stock_tag(tag);
        CREATE TABLE plate_info (plate_id TEXT PRIMARY KEY, plate_name TEXT, stock_count INTEGER);
        CREATE TABLE tag_home (tag TEXT PRIMARY KEY, plate_name TEXT, coverage REAL, n INTEGER);
        CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);''')
    conn.executemany('INSERT INTO stock VALUES (?,?,?)', [(c, n, d) for c, (n, d) in stock.items()])
    conn.executemany('INSERT INTO stock_plate VALUES (?,?,?,?,?,?,?,?)',
                     [v[:6] + [v[6], 1 if v[6] == latest_date else 0] for v in plate_rows.values()])
    conn.executemany('INSERT INTO stock_tag VALUES (?,?)', [(c, t) for c, ts in tags.items() for t in dict.fromkeys(ts)])
    conn.execute('INSERT INTO plate_info SELECT plate_id, plate_name, COUNT(*) FROM stock_plate WHERE cur=1 GROUP BY plate_id')
    # 标签归属板块（按各股当前板块统计）
    cur_plates, size = {}, {}
    for code, pn in conn.execute('SELECT code, plate_name FROM stock_plate WHERE cur=1'):
        cur_plates.setdefault(code, set()).add(pn)
        size[pn] = size.get(pn, 0) + 1
    tag_codes = {}
    for code, ts in tags.items():
        if code in cur_plates:
            for t in set(ts):
                tag_codes.setdefault(t, set()).add(code)
    homes = []
    for t, cs in tag_codes.items():
        if len(cs) < 5:
            continue
        cnt = {}
        for c in cs:
            for pn in cur_plates[c]:
                cnt[pn] = cnt.get(pn, 0) + 1
        pn, k = min(cnt.items(), key=lambda kv: (-kv[1], size.get(kv[0], 0), kv[0]))
        if k / len(cs) >= 0.8:
            homes.append((t, pn, round(k / len(cs), 3), len(cs)))
    conn.executemany('INSERT INTO tag_home VALUES (?,?,?,?)', homes)
    conn.execute("INSERT INTO meta VALUES ('sources', ?)", (','.join(os.path.basename(f) for f in files),))
    conn.execute("INSERT INTO meta VALUES ('latest_date', ?)", (latest_date,))
    conn.commit()
    conn.close()
    os.replace(tmp, db)
    print('已生成 %s：%d 日快照，%d 只股票，%d 条 股票×板块（当前 %d），%d 个标签归属' % (
        db, len(files), len(stock), len(plate_rows), sum(1 for v in plate_rows.values() if v[6] == latest_date), len(homes)))


if __name__ == '__main__':
    main()
