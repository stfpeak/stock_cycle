#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时盯盘页面服务（默认 9999 端口，存在证书时为 HTTPS）。

只保留题材风向页的四个模块（自上而下）：
  1. 精选板块强度 · Top10细分题材卡片
  2. 今日涨停时间轴（9:25~15:00）
  3. 涨停原因标签轨迹
  4. 细分题材晋级（4日连续观察 · 题材为主 · 按涨停时间）

实现方式：不复制业务代码。本服务
  - 从主服务（默认 http://127.0.0.1:6688）取回主页面 HTML，去掉其启动链与本页不用的启动请求，
    并把 static/watch.css、watch_traj.js、watch.js 内联进去（少 3 次请求），由 watch.js 复用页面里已有的渲染函数组装四个模块；
  - 把 /api/* 等其余请求反向代理到主服务。

性能（不改变任何功能）：
  - 所有文本类响应（HTML / JSON / JS / CSS）按 Accept-Encoding 做 gzip，体积降到约 1/8；
  - 热点接口（板块强度/时间轴、标签轨迹、板块排行、热股榜）做内存缓存：请求直接命中内存，
    盘中由后台线程按 TTL 主动刷新（只刷新近期有人访问的接口），所有访客共用一份，上游负载与访客数无关；
  - HTML 带 ETag，重复访问返回 304；空闲 keep-alive 连接 75s 后回收。

环境变量：WATCH_PORT（默认 9999）、WATCH_UPSTREAM（默认 http://127.0.0.1:6688）、
WATCH_CERT / WATCH_KEY（TLS 证书与私钥；默认找 watch/certs/server.crt 与 server.key，两者都存在则自动启用 HTTPS）。
"""
import gzip
import hashlib
import os
import re
import ssl
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit, unquote, parse_qsl, urlencode

import requests
from requests.adapters import HTTPAdapter

PORT = int(os.environ.get('WATCH_PORT', '9999'))
UPSTREAM = os.environ.get('WATCH_UPSTREAM', 'http://127.0.0.1:6688').rstrip('/')
_HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(_HERE, 'static')
STATIC_PREFIX = '/watch/static/'
_CERT_DIR = os.path.join(_HERE, 'certs')
CERT_FILE = os.environ.get('WATCH_CERT') or os.path.join(_CERT_DIR, 'server.crt')
KEY_FILE = os.environ.get('WATCH_KEY') or os.path.join(_CERT_DIR, 'server.key')

PAGE_TTL = 30                      # 主页面 HTML 缓存秒数（页面是静态模板，数据走 /api）
ASSETS = ('watch.css', 'watch_traj.js', 'watch.js')   # 注入顺序：样式 → 轨迹渲染器 → 页面组装
GZIP_MIN = 1200                    # 小于该字节数不压缩

_session = requests.Session()
_session.mount('http://', HTTPAdapter(pool_connections=4, pool_maxsize=32))

# 主页面末尾的启动链：默认打开「盯盘」页签 + 预取全部页签 + 急切加载 KPL 数据。
# 盯盘页不需要这些重型请求，整段剔除（主页面改动导致匹配不到时会告警并保留原样）。
_STARTUP_RE = re.compile(r"switchTab\('kpllevel'\);.*?_loadKplDataEager\(\);", re.S)
# 本页不用的启动请求（概念联想词、开盘啦热门标签、数据状态/更新检查）：去掉后少 4 次请求，
# 也不再和关键数据请求抢浏览器的 6 条并发连接。逐条匹配，匹配不到只告警。
_TRIM_RULES = [
    ("概念联想词", "fetch('/api/concepts').then(function(r) { return r.json(); }).then(function(names) {\n    conceptNames = names || [];\n});", ""),
    ("开盘啦热门标签", "    loadKplTopTags();\n});\n\nfunction selectKplSuggestStock", "});\n\nfunction selectKplSuggestStock"),
    ("数据状态/更新检查", "loadDataStatus();\ncheckDataStatus();\n", ""),
]
_HOP_HEADERS = {'connection', 'keep-alive', 'transfer-encoding', 'content-encoding',
                'content-length', 'server', 'date', 'proxy-authenticate', 'te', 'trailers', 'upgrade'}
_TEXT_TYPES = ('text/', 'application/json', 'application/javascript')

# 可缓存的热点接口：路径 → (盘中 TTL 秒, 非盘中 TTL 秒)
# TTL 取值不小于上游同接口的缓存时长，保证后台刷新时上游确实重算，而不是原样返回旧结果。
CACHE_ROUTES = {
    '/api/theme_wind_strength': (15, 300),
    '/api/ladder_trajectory': (16, 120),
    '/api/sector_ranking': (25, 300),
    '/api/hot_rank_100': (60, 600),
}
HOT_WINDOW = 180                   # 近 180s 内有人访问过的接口才会被后台主动刷新


def _log(msg):
    sys.stderr.write('[watch %s] %s\n' % (time.strftime('%H:%M:%S'), msg))
    sys.stderr.flush()


def _gzip(data, level=6):
    return gzip.compress(data, compresslevel=level, mtime=0)


def _is_text(ctype):
    return any((ctype or '').startswith(t) for t in _TEXT_TYPES)


def _bj_trading_now():
    """北京时间工作日 9:15~15:05（不含节假日判断，仅用于决定是否主动刷新，误判无副作用）。"""
    now = datetime.now(timezone(timedelta(hours=8)))
    if now.weekday() >= 5:
        return False
    m = now.hour * 60 + now.minute
    return 9 * 60 + 15 <= m <= 15 * 60 + 5


# ============================== 主页面 ==============================

_page_lock = threading.Lock()
_page = {'raw': None, 'gz': None, 'etag': None, 'ts': 0.0, 'sig': None}


def _asset_sig():
    sig = []
    for name in ASSETS:
        try:
            st = os.stat(os.path.join(STATIC_DIR, name))
            sig.append((name, st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((name, 0, 0))
    return tuple(sig)


def _read_asset(name):
    with open(os.path.join(STATIC_DIR, name), 'r', encoding='utf-8') as fh:
        return fh.read().replace('</script', '<\\/script').replace('</style', '<\\/style')


def _build_page(html):
    html, n = _STARTUP_RE.subn('/* watch: 原启动链已移除 */', html, count=1)
    if not n:
        _log('警告：主页面启动链未匹配，将加载全部页签数据，请检查 _STARTUP_RE')
    for label, old, new in _TRIM_RULES:
        if old in html:
            html = html.replace(old, new, 1)
        else:
            _log('警告：未找到「%s」启动请求，已保留（请检查 _TRIM_RULES）' % label)
    html = re.sub(r'<title>.*?</title>', '<title>实时盯盘</title>', html, count=1, flags=re.S)
    inject = '<style>%s</style><script>%s</script><script>%s</script>' % (
        _read_asset('watch.css'), _read_asset('watch_traj.js'), _read_asset('watch.js'))
    idx = html.rfind('</body>')
    return html[:idx] + inject + html[idx:] if idx >= 0 else html + inject


def get_page():
    now = time.time()
    sig = _asset_sig()
    with _page_lock:
        if _page['raw'] is not None and now - _page['ts'] < PAGE_TTL and _page['sig'] == sig:
            return _page
        r = _session.get(UPSTREAM + '/', timeout=30)
        r.raise_for_status()
        r.encoding = 'utf-8'
        raw = _build_page(r.text).encode('utf-8')
        etag = '"%s"' % hashlib.md5(raw).hexdigest()
        if etag != _page['etag']:
            _page['gz'] = _gzip(raw, 9)
        _page.update(raw=raw, etag=etag, ts=now, sig=sig)
        return _page


# ============================== 热点接口缓存 ==============================

class ApiCache(object):
    """GET 热点接口的内存缓存（命中直接返回已压缩好的字节）+ 盘中后台主动刷新 + 过期先返回旧值并异步刷新。"""

    def __init__(self):
        self.entries = {}            # key → entry
        self.lock = threading.Lock()
        self.key_locks = {}          # key → Lock（单飞：同一接口同一时刻只回源一次）
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.inflight = set()

    @staticmethod
    def make_key(path, query):
        pairs = sorted((k, v) for k, v in parse_qsl(query, keep_blank_values=True) if k != '_t')   # _t 是浏览器防缓存参数
        return path + ('?' + urlencode(pairs) if pairs else '')

    @staticmethod
    def ttl(path):
        live, idle = CACHE_ROUTES[path]
        return live if _bj_trading_now() else idle

    def _key_lock(self, key):
        with self.lock:
            return self.key_locks.setdefault(key, threading.Lock())

    def _fetch(self, key):
        r = _session.get(UPSTREAM + key, timeout=120)
        ctype = r.headers.get('Content-Type', 'application/octet-stream')
        body = r.content
        entry = {'status': r.status_code, 'ctype': ctype, 'raw': body, 'ts': time.time(),
                 'last_access': time.time(), 'gz': _gzip(body) if _is_text(ctype) and len(body) >= GZIP_MIN else None}
        # 上游 200 且不是 {"error":...} 才缓存；错误响应原样返回但不进缓存，避免把故障固化
        ok = r.status_code == 200 and not body[:12].lstrip().startswith(b'{"error"')
        if ok:
            old = self.entries.get(key)
            entry['last_access'] = old['last_access'] if old else entry['ts']
            self.entries[key] = entry
        return entry, ok

    def _refresh_async(self, key):
        with self.lock:
            if key in self.inflight:
                return
            self.inflight.add(key)

        def run():
            try:
                with self._key_lock(key):
                    self._fetch(key)
            except Exception as exc:
                _log('后台刷新失败 %s: %s' % (key[:80], exc))
            finally:
                with self.lock:
                    self.inflight.discard(key)
        self.pool.submit(run)

    def get(self, path, query):
        key = self.make_key(path, query)
        ttl = self.ttl(path)
        now = time.time()
        e = self.entries.get(key)
        if e and now - e['ts'] < ttl:
            e['last_access'] = now
            return e
        if e and now - e['ts'] < ttl * 4:
            e['last_access'] = now        # 过期不久：先返回旧值，同时异步刷新（访客永远不用等回源）
            self._refresh_async(key)
            return e
        with self._key_lock(key):          # 缺失或过旧：同步回源（单飞）
            e = self.entries.get(key)
            if e and time.time() - e['ts'] < ttl:
                e['last_access'] = time.time()
                return e
            e, _ok = self._fetch(key)
            e['last_access'] = time.time()
            return e

    def refresher(self):
        """盘中：近 HOT_WINDOW 秒内有人访问的接口，到 TTL 就后台刷新，访客读到的永远是新鲜数据。"""
        while True:
            time.sleep(1)
            try:
                if not _bj_trading_now():
                    continue
                now = time.time()
                for key, e in list(self.entries.items()):
                    path = key.split('?', 1)[0]
                    if path in CACHE_ROUTES and now - e['last_access'] < HOT_WINDOW and now - e['ts'] >= self.ttl(path):
                        self._refresh_async(key)
            except Exception as exc:
                _log('刷新线程异常: %s' % exc)


_cache = ApiCache()


# ============================== HTTP 处理 ==============================

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    timeout = 75                      # 空闲 keep-alive 连接回收，避免线程堆积

    def log_message(self, fmt, *args):
        pass   # 代理请求量大，静默；错误走 _log

    def _wants_gzip(self):
        return 'gzip' in (self.headers.get('Accept-Encoding') or '')

    def _send(self, status, body, ctype, extra=None, gz=None, cache='no-store'):
        """gz 为预先压缩好的字节；未提供时，文本类大响应按需压缩。"""
        headers = list(extra or [])
        if self._wants_gzip() and _is_text(ctype) and len(body) >= GZIP_MIN:
            body = gz if gz is not None else _gzip(body, 4)
            headers.append(('Content-Encoding', 'gzip'))
        if _is_text(ctype):
            headers.append(('Vary', 'Accept-Encoding'))
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', cache)
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _not_modified(self, etag):
        self.send_response(304)
        self.send_header('ETag', etag)
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def _index(self):
        page = get_page()
        if self.headers.get('If-None-Match') == page['etag']:
            return self._not_modified(page['etag'])
        self._send(200, page['raw'], 'text/html; charset=utf-8', [('ETag', page['etag'])], gz=page['gz'], cache='no-cache')

    def _static(self, path):
        name = os.path.basename(unquote(path[len(STATIC_PREFIX):]))
        full = os.path.join(STATIC_DIR, name)
        if not name or not os.path.isfile(full):
            return self._send(404, b'not found', 'text/plain; charset=utf-8')
        st = os.stat(full)
        etag = '"%x-%x"' % (st.st_mtime_ns, st.st_size)
        if self.headers.get('If-None-Match') == etag:
            return self._not_modified(etag)
        ctype = {'.js': 'application/javascript', '.css': 'text/css'}.get(
            os.path.splitext(name)[1], 'application/octet-stream')
        with open(full, 'rb') as fh:
            self._send(200, fh.read(), ctype + '; charset=utf-8', [('ETag', etag)], cache='no-cache')

    def _cached_api(self, path, query):
        e = _cache.get(path, query)
        self._send(e['status'], e['raw'], e['ctype'], gz=e['gz'])

    def _proxy(self):
        body = None
        length = int(self.headers.get('Content-Length') or 0)
        if length:
            body = self.rfile.read(length)
        headers = {}
        for k in ('Content-Type', 'Accept', 'User-Agent'):
            if self.headers.get(k):
                headers[k] = self.headers[k]
        try:
            r = _session.request(self.command, UPSTREAM + self.path, data=body, headers=headers,
                                 timeout=120, allow_redirects=False)
        except requests.RequestException as exc:
            _log('上游请求失败 %s: %s' % (self.path, exc))
            return self._send(502, ('主服务 %s 不可达：%s' % (UPSTREAM, exc)).encode('utf-8'),
                              'text/plain; charset=utf-8')
        extra = [(k, v) for k, v in r.headers.items() if k.lower() not in _HOP_HEADERS
                 and k.lower() not in ('content-type', 'cache-control', 'etag', 'vary')]
        self._send(r.status_code, r.content, r.headers.get('Content-Type', 'application/octet-stream'), extra)

    def _handle(self):
        parts = urlsplit(self.path)
        path = parts.path
        try:
            if path in ('/', '/index.html') and self.command in ('GET', 'HEAD'):
                return self._index()
            if path.startswith(STATIC_PREFIX) and self.command in ('GET', 'HEAD'):
                return self._static(path)
            if path == '/healthz':
                return self._send(200, b'ok', 'text/plain; charset=utf-8')
            if path in CACHE_ROUTES and self.command in ('GET', 'HEAD'):
                return self._cached_api(path, parts.query)
            return self._proxy()
        except requests.RequestException as exc:
            _log('取上游数据失败 %s: %s' % (path, exc))
            self._send(502, ('主服务 %s 不可达：%s\n请先启动 stock_linkage_simple.py（6688）' % (UPSTREAM, exc)).encode('utf-8'),
                       'text/plain; charset=utf-8')
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    do_GET = do_POST = do_HEAD = _handle


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128

    def handle_error(self, request, client_address):
        # 扫描器/明文 HTTP 请求打到 HTTPS 端口会触发握手失败，属正常噪声，不打印堆栈
        if isinstance(sys.exc_info()[1], (ssl.SSLError, ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def main():
    server = _Server(('0.0.0.0', PORT), Handler)
    scheme = 'http'
    if os.path.isfile(CERT_FILE) and os.path.isfile(KEY_FILE):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(CERT_FILE, KEY_FILE)
        # 握手放到处理线程里做，避免慢客户端/扫描器卡住 accept 循环
        server.socket = ctx.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
        scheme = 'https'
    threading.Thread(target=_cache.refresher, name='api-refresher', daemon=True).start()
    _log('实时盯盘服务已启动 %s://0.0.0.0:%d  上游=%s' % (scheme, PORT, UPSTREAM))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
