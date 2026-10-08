#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时盯盘页面服务（默认 9999 端口）。

只保留题材风向页的四个模块（自上而下）：
  1. 精选板块强度 · Top10细分题材卡片
  2. 今日涨停时间轴（9:25~15:00）
  3. 涨停原因标签轨迹
  4. 细分题材晋级（4日连续观察 · 题材为主 · 按涨停时间）

实现方式：不复制业务代码。本服务
  - 启动时/定时从主服务（默认 http://127.0.0.1:6688）取回主页面 HTML，
    去掉其启动链并注入 static/watch.css + static/watch.js，由 watch.js 复用页面里已有的渲染函数组装四个模块；
  - 把 /api/* 等其余请求原样反向代理到主服务（数据、缓存、盘中刷新都沿用主服务）。
所以页面本身在 watch/static/ 下独立开发；数据口径变化仍在主服务里改。

环境变量：WATCH_PORT（默认 9999）、WATCH_UPSTREAM（默认 http://127.0.0.1:6688）、
WATCH_CERT / WATCH_KEY（TLS 证书与私钥；默认找 watch/certs/server.crt 与 server.key，两者都存在则自动启用 HTTPS）。
"""
import os
import re
import ssl
import sys
import time
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit, unquote

import requests

PORT = int(os.environ.get('WATCH_PORT', '9999'))
UPSTREAM = os.environ.get('WATCH_UPSTREAM', 'http://127.0.0.1:6688').rstrip('/')
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
STATIC_PREFIX = '/watch/static/'
_CERT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'certs')
CERT_FILE = os.environ.get('WATCH_CERT') or os.path.join(_CERT_DIR, 'server.crt')
KEY_FILE = os.environ.get('WATCH_KEY') or os.path.join(_CERT_DIR, 'server.key')
PAGE_TTL = 30          # 主页面 HTML 缓存秒数（页面是静态模板，数据走 /api）

_session = requests.Session()
_page_lock = threading.Lock()
_page_cache = {'html': None, 'ts': 0.0}

# 主页面末尾的启动链：默认打开「盯盘」页签 + 预取全部页签 + 急切加载 KPL 数据。
# 盯盘页不需要这些重型请求，整段剔除（主页面改动导致匹配不到时会告警并保留原样）。
_STARTUP_RE = re.compile(r"switchTab\('kpllevel'\);.*?_loadKplDataEager\(\);", re.S)
_HOP_HEADERS = {'connection', 'keep-alive', 'transfer-encoding', 'content-encoding',
                'content-length', 'server', 'date', 'proxy-authenticate', 'te', 'trailers', 'upgrade'}


def _log(msg):
    sys.stderr.write('[watch %s] %s\n' % (time.strftime('%H:%M:%S'), msg))
    sys.stderr.flush()


def _build_page(html):
    html, n = _STARTUP_RE.subn('/* watch: 原启动链已移除 */', html, count=1)
    if not n:
        _log('警告：主页面启动链未匹配，将加载全部页签数据，请检查 _STARTUP_RE')
    html = re.sub(r'<title>.*?</title>', '<title>实时盯盘</title>', html, count=1, flags=re.S)
    inject = ('<link rel="stylesheet" href="%swatch.css">'
              '<script src="%swatch_traj.js"></script><script src="%swatch.js"></script>') % (
        STATIC_PREFIX, STATIC_PREFIX, STATIC_PREFIX)
    idx = html.rfind('</body>')
    return html[:idx] + inject + html[idx:] if idx >= 0 else html + inject


def get_page():
    now = time.time()
    with _page_lock:
        if _page_cache['html'] is not None and now - _page_cache['ts'] < PAGE_TTL:
            return _page_cache['html']
        r = _session.get(UPSTREAM + '/', timeout=30)
        r.raise_for_status()
        r.encoding = 'utf-8'
        _page_cache['html'] = _build_page(r.text).encode('utf-8')
        _page_cache['ts'] = now
        return _page_cache['html']


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass   # 代理请求量大，静默；错误走 _log

    def _send(self, status, body, ctype, extra=None):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or []):
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _static(self, path):
        name = os.path.basename(unquote(path[len(STATIC_PREFIX):]))
        full = os.path.join(STATIC_DIR, name)
        if not name or not os.path.isfile(full):
            return self._send(404, b'not found', 'text/plain; charset=utf-8')
        ctype = {'.js': 'application/javascript', '.css': 'text/css'}.get(
            os.path.splitext(name)[1], 'application/octet-stream')
        with open(full, 'rb') as fh:
            self._send(200, fh.read(), ctype + '; charset=utf-8')

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
                 and k.lower() != 'content-type' and k.lower() != 'cache-control']
        self._send(r.status_code, r.content, r.headers.get('Content-Type', 'application/octet-stream'), extra)

    def _handle(self):
        path = urlsplit(self.path).path
        try:
            if path in ('/', '/index.html') and self.command in ('GET', 'HEAD'):
                return self._send(200, get_page(), 'text/html; charset=utf-8')
            if path.startswith(STATIC_PREFIX) and self.command in ('GET', 'HEAD'):
                return self._static(path)
            if path == '/healthz':
                return self._send(200, b'ok', 'text/plain; charset=utf-8')
            return self._proxy()
        except requests.RequestException as exc:
            _log('取主页面失败: %s' % exc)
            self._send(502, ('主服务 %s 不可达：%s\n请先启动 stock_linkage_simple.py（6688）' % (UPSTREAM, exc)).encode('utf-8'),
                       'text/plain; charset=utf-8')
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = do_POST = do_HEAD = _handle


class _Server(ThreadingHTTPServer):
    daemon_threads = True

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
    _log('实时盯盘服务已启动 %s://0.0.0.0:%d  上游=%s' % (scheme, PORT, UPSTREAM))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
