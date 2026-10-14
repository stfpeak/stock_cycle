"""watch_server._is_trading_day_today：9:25 前上游返回上一交易日，不能被缓存成"今天休市"。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'watch'))
import watch_server as w  # noqa: E402


class _Resp:
    status_code = 200

    def __init__(self, v):
        self.v = v

    def json(self):
        return self.v


def _run(h, mi, upstream):
    class D(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 10, 14, h, mi, tzinfo=tz)
    w.datetime = D
    w._trading_day_cache['try'] = 0.0
    w._session.get = lambda *a, **k: _Resp(upstream)
    return w._is_trading_day_today()


def test_not_latched_before_open():
    w._trading_day_cache.update(date=None, ok=False)
    assert _run(9, 20, ['2026-10-13']) is True          # 9:25 前：按工作日处理且不定论
    assert w._trading_day_cache['date'] is None
    assert _run(9, 26, ['2026-10-14']) is True          # 9:25 后上游返回今天：定论为交易日
    assert w._trading_day_cache['ok'] is True


def test_holiday_latched_after_930():
    w._trading_day_cache.update(date=None, ok=False)
    assert _run(9, 31, ['2026-10-13']) is False
    assert w._trading_day_cache['date'] == '2026-10-14'
