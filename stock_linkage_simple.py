#!/usr/bin/env python3
"""
股票联动查询 - 简化版Web服务 V5
使用Python内置http.server，无依赖问题
启动: python stock_linkage_simple.py
访问: http://localhost:5001
"""

import os
import sys
import json
from urllib.parse import parse_qs, urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stock_linkage_finder import StockLinkageFinder

# 全局finder
print("正在初始化股票联动查找器 V5 ...")
finder = StockLinkageFinder()
print("初始化完成!")

HTML_PAGE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>股票联动查询 V5</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    min-height: 100vh;
    color: #eee;
    padding: 20px;
}
.container { max-width: 96vw; margin: 0 auto; }
h1 { color: #00d4ff; text-align: center; margin: 20px 0 5px 0; font-size: 2em; }
.sub { text-align: center; color: #666; margin-bottom: 20px; font-size: 0.85em; }

.search-box {
    background: #16213e;
    border-radius: 12px;
    padding: 20px 25px;
    margin: 15px 0;
}
.input-row { display: flex; gap: 12px; flex-wrap: wrap; }
.input-item { flex: 1; min-width: 180px; position: relative; }
label { display: block; margin-bottom: 5px; color: #00d4ff; font-size: 0.9em; }
input[type=text] {
    width: 100%;
    padding: 10px 14px;
    border: 2px solid #0f3460;
    border-radius: 8px;
    background: #1a1a2e;
    color: #eee;
    font-size: 15px;
}
input:focus { border-color: #00d4ff; outline: none; }

/* Search Suggestions */
.suggestions {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    background: #16213e;
    border: 1px solid #0f3460;
    border-radius: 0 0 8px 8px;
    max-height: 280px;
    overflow-y: auto;
    z-index: 1000;
    display: none;
    box-shadow: 0 8px 20px rgba(0,0,0,0.5);
}
.suggestions.active { display: block; }
.suggestion-item {
    padding: 9px 12px;
    cursor: pointer;
    border-bottom: 1px solid #0f3460;
    display: flex;
    justify-content: space-between;
}
.suggestion-item:hover { background: #0f3460; }
.sug-code { color: #00d4ff; font-weight: bold; }
.sug-meta { color: #888; font-size: 0.85em; }

button {
    padding: 10px 26px;
    background: linear-gradient(135deg, #00d4ff, #0066cc);
    border: none;
    border-radius: 8px;
    color: #fff;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
}
button:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(0,212,255,0.3); }
button:disabled { background: #555; cursor: not-allowed; }
.btn-con { background: #0f3460; border: 1px solid #00d4ff; font-weight: 400; margin-left: 8px; }

/* Tabs */
.tabs { display: flex; gap: 0; margin: 15px 0; }
.tab {
    padding: 9px 20px;
    background: #1a1a2e;
    border: 1px solid #0f3460;
    cursor: pointer;
    color: #888;
    font-size: 0.9em;
}
.tab:first-child { border-radius: 8px 0 0 8px; }
.tab:last-child { border-radius: 0 8px 8px 0; }
.tab.active { background: #0f3460; color: #00d4ff; border-color: #00d4ff; }
.tab-content { display: none; }
.tab-content.active { display: block; }

/* Result */
.result {
    background: #16213e;
    border-radius: 12px;
    padding: 20px;
    margin: 15px 0;
}
.stock-info {
    display: flex;
    align-items: center;
    gap: 15px;
    margin-bottom: 15px;
    padding-bottom: 12px;
    border-bottom: 1px solid #333;
    flex-wrap: wrap;
}
.code-badge { background: #e94560; padding: 6px 14px; border-radius: 15px; font-weight: bold; }
.stock-name { font-size: 1.3em; color: #00d4ff; font-weight: 600; }
.zt-count { color: #888; }
.badge { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 0.8em; margin: 2px; }
.badge-pool { background: #0f3460; border: 1px solid #00d4ff; color: #00d4ff; }
.badge-db { background: #1a3a1a; border: 1px solid #00ff88; color: #00ff88; }
.tag {
    display: inline-block;
    background: #0f3460;
    border: 1px solid #00d4ff;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.85em;
    margin: 2px;
}
.zt-date-tag {
    display: inline-block;
    background: #1a1a2e;
    padding: 2px 8px;
    border-radius: 4px;
    margin: 2px;
    font-size: 0.85em;
    border: 1px solid #333;
}

table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 0.9em; }
th { background: #0f3460; color: #00d4ff; padding: 10px; text-align: left; }
th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { background: #1a4a7a; }
td { padding: 8px 10px; border-bottom: 1px solid #333; }
tr:hover { background: #1a1a2e; }
tr.clickable { cursor: pointer; }
tr.clickable:hover { background: #0f3460; }

/* Sort controls */
.sort-bar { display: flex; align-items: center; gap: 6px; margin: 10px 0; flex-wrap: wrap; }
.sort-label { color: #888; font-size: 0.85em; margin-right: 4px; }
.sort-btn {
    padding: 4px 12px;
    border: 1px solid #0f3460;
    border-radius: 6px;
    background: #1a1a2e;
    color: #aaa;
    cursor: pointer;
    font-size: 0.85em;
    transition: all 0.2s;
}
.sort-btn:hover { border-color: #00d4ff; color: #00d4ff; }
.sort-btn.active { background: #0f3460; border-color: #00d4ff; color: #00d4ff; }
.sort-btn.asc::after { content: ' ▲'; font-size: 0.7em; }
.sort-btn.desc::after { content: ' ▼'; font-size: 0.7em; }
.top-n-badge {
    display: inline-block;
    background: #e94560;
    color: #fff;
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 0.8em;
    margin-left: 8px;
}

.prob-cell { display: flex; align-items: center; gap: 6px; }
.prob-bar { width: 60px; height: 16px; background: #0f3460; border-radius: 3px; overflow: hidden; }
.prob-fill { height: 100%; }
.prob-fill.t0 { background: linear-gradient(90deg, #ff6b6b, #ff0022); }
.prob-fill.t1 { background: linear-gradient(90deg, #e94560, #ff6b6b); }
.prob-fill.t2 { background: linear-gradient(90deg, #ffc107, #ff9800); }
.prob-fill.t3 { background: linear-gradient(90deg, #00bcd4, #00d4ff); }

.strength { color: #00ff88; font-weight: bold; }
.empty { text-align: center; padding: 50px; color: #666; }
.loading { text-align: center; padding: 50px; color: #888; }
.error { background: rgba(233,69,96,0.2); border: 1px solid #e94560; padding: 15px; border-radius: 8px; color: #e94560; }
h3 { color: #ff6b6b; margin: 15px 0 8px; }

/* Concept tabs */
.concept-tabs { display: flex; flex-wrap: wrap; gap: 4px; margin: 10px 0; }
.concept-tab {
    padding: 4px 12px;
    border: 1px solid #0f3460;
    border-radius: 14px;
    background: #1a1a2e;
    color: #aaa;
    cursor: pointer;
    font-size: 0.82em;
    transition: all 0.2s;
}
.concept-tab:hover { border-color: #00d4ff; color: #00d4ff; }
.concept-tab.active { background: #0f3460; border-color: #00d4ff; color: #00d4ff; }
.concept-section { margin-bottom: 20px; }
.concept-section h4 { color: #ff9800; margin-bottom: 6px; font-size: 1em; display: inline; }
.section-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.show-all-btn {
    font-size: 0.78em;
    color: #00d4ff;
    cursor: pointer;
    padding: 2px 10px;
    border: 1px solid #00d4ff;
    border-radius: 10px;
    background: transparent;
    transition: all 0.2s;
}
.show-all-btn:hover { background: #0f3460; }

/* Event details row */
.event-row td { padding: 8px 12px; background: #1a1a2e; border-bottom: 1px solid #0f3460; }
.event-header { margin-bottom: 6px; display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
.dir-label { color: #888; font-size: 0.85em; }
.stock-a { color: #00d4ff; font-weight: bold; font-size: 0.85em; }
.stock-b { color: #ff6b6b; font-weight: bold; font-size: 0.85em; }
.dir-sep { color: #333; margin: 0 4px; font-size: 0.8em; }
.dir-item { color: #aaa; font-size: 0.82em; }
.event-timeline { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; margin-top: 4px; font-size: 0.85em; }
.event-tag {
    display: inline-flex;
    align-items: center;
    background: #0f3460;
    border-radius: 4px;
    padding: 2px 6px;
    gap: 2px;
    font-size: 0.82em;
}
.evt-a { color: #00d4ff; font-weight: bold; }
.evt-arrow { color: #555; margin: 0 1px; }
.evt-b { color: #ff6b6b; font-weight: bold; }
.evt-lag { color: #ff9800; font-size: 0.75em; margin-left: 2px; padding: 0 3px; background: #1a1a2e; border-radius: 2px; }

.quick-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 15px; }
.quick-stock {
    background: #1a1a2e;
    border: 1px solid #333;
    padding: 8px 14px;
    border-radius: 8px;
    cursor: pointer;
}
.quick-stock:hover { border-color: #00d4ff; background: #0f3460; }
.qs-code { color: #00d4ff; font-weight: bold; }
.qs-name { color: #aaa; margin-left: 6px; }
.qs-zt { color: #ff6b6b; margin-left: 6px; font-size: 0.85em; }

.peak-list { display: flex; flex-wrap: wrap; gap: 8px; }
.peak-item { background: #0f3460; border: 1px solid #ff6b6b; padding: 5px 12px; border-radius: 8px; font-size: 0.85em; }
.peak-date { color: #ff6b6b; }
.peak-count { color: #00d4ff; font-weight: bold; }

/* Stats Tab */
.stat-cards { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }
.stat-card {
    background: #1a1a2e;
    border: 1px solid #0f3460;
    border-radius: 10px;
    padding: 15px 20px;
    min-width: 140px;
    flex: 1;
}
.stat-card .stat-label { color: #888; font-size: 0.85em; }
.stat-card .stat-value { color: #00d4ff; font-size: 1.8em; font-weight: bold; }
.stat-card .stat-value.red { color: #ff6b6b; }
.stat-card .stat-value.green { color: #00ff88; }

.filter-bar {
    display: flex; gap: 14px; align-items: flex-end;
    flex-wrap: wrap; margin-bottom: 18px;
    background: linear-gradient(135deg, #1a1a3e, #0f3460);
    padding: 16px 22px; border-radius: 14px;
    border: 1px solid rgba(0,212,255,0.15);
}
.filter-bar label { color: #aaa; font-size: 0.82em; letter-spacing: 0.5px; }
.filter-bar input[type=date] {
    background: #1a1a2e; border: 1px solid #0f3460;
    color: #00d4ff; padding: 8px 12px; border-radius: 8px;
    font-size: 0.9em; outline: none;
    transition: border-color 0.2s;
}
.filter-bar input[type=date]:focus { border-color: #00d4ff; }
.filter-bar .btn {
    background: linear-gradient(135deg, #00d4ff, #0099cc);
    color: #1a1a2e; border: none; padding: 8px 22px;
    border-radius: 8px; cursor: pointer; font-weight: bold;
    font-size: 0.9em; transition: transform 0.1s, opacity 0.2s;
}
.filter-bar .btn:hover { opacity: 0.9; transform: translateY(-1px); }

.chart-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 18px;
    margin-bottom: 22px;
}
.chart-box {
    background: #16213e;
    border-radius: 12px;
    padding: 15px 18px;
    margin-bottom: 15px;
}
.chart-grid .chart-box { margin-bottom: 0; }
.chart-box h4 { color: #00d4ff; margin-bottom: 10px; font-size: 1em; }
.chart-box canvas { max-height: 500px; height: 420px !important; }

/* Distribution bucket buttons */
.dist-section { margin-bottom: 20px; }
.dist-section h4 { color: #ff6b6b; margin-bottom: 10px; font-size: 1em; }
.bucket-bar {
    display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px;
}
.bucket-btn {
    padding: 8px 16px; border-radius: 8px; cursor: pointer;
    font-size: 0.9em; font-weight: bold; text-align: center;
    background: #0f3460; color: #aaa; border: 1px solid transparent;
    transition: all 0.2s; user-select: none;
}
.bucket-btn:hover { background: #1a4a8a; color: #eee; }
.bucket-btn.active {
    background: #00d4ff; color: #1a1a2e; border-color: #00d4ff;
    box-shadow: 0 0 12px rgba(0,212,255,0.3);
}

/* Bucket detail table */
.bucket-detail {
    background: #1a1a2e; border-radius: 10px; padding: 12px;
    margin-top: 8px; display: none; max-height: 400px; overflow-y: auto;
}
.bucket-detail.active { display: block; }
.bucket-detail table { width: 100%; border-collapse: collapse; }
.bucket-detail th {
    background: #0f3460; color: #888; padding: 6px 8px;
    text-align: left; font-size: 0.82em; position: sticky; top: 0; z-index: 1;
}
.bucket-detail td {
    padding: 5px 8px; border-bottom: 1px solid #0f3460;
    font-size: 0.85em;
}
.bucket-detail tr.clickable { cursor: pointer; }
.bucket-detail tr.clickable:hover { background: #16213e; }
.concept-badge {
    display: inline-block; background: #0f3460; color: #00d4ff;
    padding: 1px 6px; border-radius: 4px; font-size: 0.82em; margin: 1px 2px;
}

/* Stats hot stocks section */
.hot-section { margin-top: 15px; }
.hot-section h4 { color: #ff6b6b; margin-bottom: 10px; font-size: 1em; }
.hot-section table { width: 100%; border-collapse: collapse; }
.hot-section th {
    background: #0f3460; color: #888; padding: 7px 10px;
    text-align: left; font-size: 0.85em;
}
.hot-section td {
    padding: 6px 10px; border-bottom: 1px solid #0f3460; font-size: 0.88em;
}
.hot-section tr.clickable { cursor: pointer; }
.hot-section tr.clickable:hover { background: #16213e; }

/* Score badge colors */
.score-badge {
    display: inline-block; padding: 2px 10px; border-radius: 10px;
    font-weight: bold; font-size: 0.85em; min-width: 36px; text-align: center;
}
.score-high { background: rgba(255, 60, 60, 0.25); color: #ff6b6b; }
.score-mid { background: rgba(255, 193, 7, 0.2); color: #ffc107; }
.score-low { background: rgba(0, 212, 255, 0.15); color: #00d4ff; }

.stats-section { margin-bottom: 25px; }
.stats-section h3 { color: #ff6b6b; margin-bottom: 12px; font-size: 1.1em; }

/* Recommend Tab */
.rec-section { margin-bottom: 20px; }
.rec-card {
    background: #16213e;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 10px;
    border-left: 4px solid #00d4ff;
    cursor: pointer;
}
.rec-card:hover { border-color: #ff6b6b; }
.rec-card.top { border-left-color: #e94560; }
.rec-card.good { border-left-color: #ffc107; }
.rec-card.normal { border-left-color: #0f3460; }
.rec-header { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.rec-code { font-size: 1.1em; font-weight: bold; color: #00d4ff; }
.rec-name { font-size: 1.1em; color: #eee; }
.rec-score { font-size: 1.2em; font-weight: bold; color: #00ff88; margin-left: auto; }
.rec-score.high { color: #e94560; font-size: 1.4em; }
.rec-score.mid { color: #ffc107; }
.rec-tags { display: flex; gap: 6px; flex-wrap: wrap; margin: 6px 0; }
.rec-tag {
    background: #1a1a2e;
    border: 1px solid #333;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.78em;
    color: #aaa;
}
.rec-tag.zt { border-color: #e94560; color: #ff6b6b; }
.rec-tag.heat { border-color: #ffc107; color: #ffc107; }
.rec-tag.pullback { border-color: #00d4ff; color: #00d4ff; }
.rec-advice { background: #1a1a2e; padding: 8px 12px; border-radius: 6px; margin-top: 6px; font-size: 0.85em; color: #ddd; }
.rec-advice .star { color: #ffc107; }

/* N字战法 页面样式 */
.np-section { margin-bottom: 25px; }
.np-section h3 { color: #00d4ff; margin-bottom: 15px; font-size: 1.1em; display: flex; align-items: center; gap: 10px; }
.np-section .count-badge { background: #0f3460; color: #00d4ff; padding: 2px 10px; border-radius: 10px; font-size: 0.8em; }

.np-board-section { margin-bottom: 20px; }
.np-board-header {
    display: flex; align-items: center; gap: 8px; margin-bottom: 10px;
    padding: 6px 12px; border-radius: 8px; font-size: 0.9em; font-weight: bold;
}
.np-board-header.main { background: #1a3a5c; color: #4fc3f7; }
.np-board-header.gem { background: #3a1a3a; color: #f48fb1; }
.np-board-header.star { background: #1a3a1a; color: #81c784; }
.np-board-header.bj { background: #3a3a1a; color: #ffd54f; }

.np-card-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    justify-content: center;
    margin-bottom: 20px;
}
.np-card {
    width: 480px;
    flex-shrink: 0;
    border-radius: 12px;
    padding: 14px;
    border: 1px solid #0f3460;
    transition: border-color 0.2s;
    position: relative;
}
.np-card:hover { border-color: #00d4ff; }
.np-card.star-card { border-left: 3px solid #ffc107; }
.np-card.tld-card { border-left: 4px solid #e94560; background: linear-gradient(135deg, #1a1a2e, #2a1020); }
.np-card.tld-shouban-card { border-left: 4px solid #ff6b6b; background: linear-gradient(135deg, #1a1a2e, #301515); }
.np-card.nw-card { border-left: 4px solid #ff5722; background: linear-gradient(135deg, #1a1a2e, #2a1a10); }
.np-card .tld-badge { background: rgba(233, 69, 96, 0.25); color: #e94560; border: 1px solid #e94560; padding: 2px 8px; border-radius: 4px; font-size: 0.78em; font-weight: bold; margin-left: 4px; }
.np-card .tld-shouban-badge { background: rgba(255, 107, 107, 0.25); color: #ff6b6b; border: 1px solid #ff6b6b; padding: 2px 8px; border-radius: 4px; font-size: 0.78em; font-weight: bold; margin-left: 4px; animation: pulse-red 1.5s ease-in-out infinite; }
.np-card .nw-badge { background: rgba(255, 87, 34, 0.2); color: #ff5722; border: 1px solid #ff5722; padding: 2px 8px; border-radius: 4px; font-size: 0.78em; font-weight: bold; margin-left: 4px; }
@keyframes pulse-red { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
.np-card-header {
    display: flex; justify-content: space-between; align-items: flex-start;
    margin-bottom: 8px;
}
.np-card-code { font-size: 1.1em; font-weight: bold; color: #00d4ff; cursor: pointer; }
.np-card-code:hover { text-decoration: underline; }
.np-card-name { font-size: 0.9em; color: #ddd; margin-left: 6px; }
.np-card-badges { display: flex; gap: 4px; flex-wrap: wrap; margin: 4px 0; }
.np-card-badge {
    background: #0f3460; padding: 2px 8px; border-radius: 4px;
    font-size: 0.78em; color: #aaa;
}
.np-card-badge.lianban { background: rgba(255, 193, 7, 0.15); color: #ffc107; border-color: #ffc107; }
.np-card-badge.alert { background: rgba(255, 60, 60, 0.15); color: #ff6b6b; border-color: #ff6b6b; }
.np-card-badge.oscillation { background: rgba(0, 212, 255, 0.15); color: #00d4ff; border-color: #00d4ff; }

.np-metrics {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 4px;
    margin: 8px 0;
    font-size: 0.82em;
}
.np-metric { text-align: center; padding: 4px; background: #0f3460; border-radius: 6px; }
.np-metric .label { color: #888; font-size: 0.78em; }
.np-metric .value { color: #ddd; font-weight: bold; }
.np-metric .value.positive { color: #ff6b6b; }
.np-metric .value.negative { color: #81c784; }

.np-nw-metrics {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 4px;
    margin: 6px 0 8px 0;
    font-size: 0.82em;
}

.np-kline-container { margin: 8px 0; position: relative; }
.np-kline-container canvas { width: 100%; height: 200px; border-radius: 6px; background: #1a1a2e; }
.np-kline-toggle {
    background: #0f3460; color: #aaa; border: none; padding: 4px 12px;
    border-radius: 4px; cursor: pointer; font-size: 0.78em;
    margin-top: 4px;
}
.np-kline-toggle:hover { background: #1a4a8a; color: #eee; }

.arb-btn {
    background: linear-gradient(135deg, #ff9800, #e94560); color: #fff; border: none;
    padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 0.85em; font-weight: bold;
    transition: transform 0.2s, box-shadow 0.2s;
}
.arb-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(233, 69, 96, 0.4); }

.np-alert-card {
    background: #1a1a2e; border-radius: 10px; padding: 12px;
    margin-bottom: 8px; border-left: 3px solid #e94560;
}
.np-alert-card.gem { border-left-color: #f48fb1; }
.np-alert-card.zha_ban { border-left-color: #ff9800; }

.np-cat-header {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 16px; background: #0f3460; border-radius: 10px;
    margin-bottom: 12px; cursor: pointer; user-select: none;
}
.np-cat-header:hover { background: #1a4a8a; }
.np-cat-header .cat-icon { font-size: 1.2em; }
.np-cat-header .cat-name { font-weight: bold; font-size: 0.95em; }
.np-cat-header .cat-count { color: #888; font-size: 0.85em; }
.np-cat-header .cat-arrow { margin-left: auto; color: #666; transition: transform 0.2s; }
.np-cat-header.collapsed .cat-arrow { transform: rotate(-90deg); }

/* Pullback progress bar */
.np-pullback-bar {
    height: 6px; background: #0f3460; border-radius: 3px; margin: 6px 0; overflow: hidden;
}
.np-pullback-fill { height: 100%; border-radius: 3px; }
.np-pullback-fill.shallow { background: linear-gradient(90deg, #81c784, #4caf50); }
.np-pullback-fill.normal { background: linear-gradient(90deg, #4caf50, #ffc107); }
.np-pullback-fill.deep { background: linear-gradient(90deg, #ffc107, #ff9800); }
.np-pullback-fill.severe { background: linear-gradient(90deg, #ff9800, #ff6b6b); }
.np-pullback-fill.extreme { background: linear-gradient(90deg, #ff6b6b, #e94560); }

.np-update-time { text-align: center; color: #666; font-size: 0.85em; padding: 10px; }

/* N字战法 UI Enhancements: sidebar, filters, grid toggle, back-to-top */
.np-wrapper {
    display: flex;
    align-items: flex-start;
    gap: 18px;
}
.np-sidebar {
    position: sticky;
    top: 20px;
    width: 130px;
    flex-shrink: 0;
    background: rgba(15,52,96,0.55);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border-radius: 12px;
    border: 1px solid rgba(0,212,255,0.12);
    padding: 8px 0;
    z-index: 10;
}
.np-sidebar-item {
    display: block;
    padding: 7px 12px;
    font-size: 0.78em;
    color: #888;
    cursor: pointer;
    transition: all 0.2s;
    border-left: 3px solid transparent;
    text-decoration: none;
    line-height: 1.3;
}
.np-sidebar-item:hover { color: #ddd; background: rgba(0,212,255,0.05); }
.np-sidebar-item.active {
    color: #00d4ff;
    border-left-color: #00d4ff;
    background: rgba(0,212,255,0.08);
}
.np-main-content {
    flex: 1;
    min-width: 0;
}
.np-back-top {
    text-align: center;
    padding: 6px;
    font-size: 0.8em;
    color: #555;
    cursor: pointer;
    transition: color 0.2s;
    border-top: 1px solid rgba(255,255,255,0.04);
    margin-top: 4px;
}
.np-back-top:hover { color: #00d4ff; }

/* Filter bar */
.np-filter-bar {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 16px;
    padding: 10px 14px;
    background: rgba(15,52,96,0.35);
    border-radius: 10px;
    border: 1px solid rgba(0,212,255,0.08);
}
.np-filter-bar .fl { color: #888; font-size: 0.8em; }
.np-filter-input {
    background: #0f3460; color: #ddd;
    border: 1px solid rgba(0,212,255,0.2); border-radius: 6px;
    padding: 5px 10px; font-size: 0.82em; outline: none; min-width: 160px;
}
.np-filter-input:focus { border-color: #00d4ff; }
.np-filter-cb {
    display: flex; align-items: center; gap: 3px;
    font-size: 0.8em; color: #aaa; cursor: pointer;
    padding: 3px 8px; background: rgba(15,52,96,0.5); border-radius: 5px;
}
.np-filter-cb:hover { color: #ddd; }
.np-filter-cb input { accent-color: #00d4ff; margin: 0; }

/* Grid column toggle */
.np-grid-tog {
    display: flex; gap: 3px; align-items: center; margin-left: auto;
}
.np-grid-tog button {
    background: #0f3460; color: #888;
    border: 1px solid rgba(0,212,255,0.12); padding: 3px 9px;
    border-radius: 4px; cursor: pointer; font-size: 0.76em; transition: all 0.2s;
}
.np-grid-tog button:hover { color: #ddd; border-color: #00d4ff; }
.np-grid-tog button.active {
    color: #00d4ff; border-color: #00d4ff; background: rgba(0,212,255,0.1);
}

/* K-line modal overlay */
.kline-modal-overlay {
    display: none; position: fixed; z-index: 1000;
    left: 0; top: 0; width: 100%; height: 100%;
    background: rgba(0,0,0,0.7); backdrop-filter: blur(4px);
}
.kline-modal-overlay.active { display: flex; align-items: center; justify-content: center; }
.kline-modal {
    background: #16213e; border-radius: 16px; border: 1px solid #0f3460;
    width: 90%; max-width: 900px; max-height: 90vh; overflow-y: auto;
    padding: 24px; position: relative;
}
.kline-modal-close {
    position: absolute; top: 12px; right: 16px;
    color: #888; font-size: 1.5em; cursor: pointer;
    transition: color 0.2s;
}
.kline-modal-close:hover { color: #ff6b6b; }
.kline-modal h3 { color: #00d4ff; margin: 0 0 8px 0; }
.kline-modal .np-metrics { grid-template-columns: repeat(4, 1fr); }
.kline-modal .np-card-badges { margin: 8px 0; }
</style>
</head>
<body>
<div class="container">
    <h1>📊 A股题材轮动分析系统</h1>
    <p class="sub">N字战法·涨停回调 | T+0同日联动 | 双源涨停检测 | 方向性分析 | 概念轮动</p>
    <p class="sub" style="font-size:0.75em;color:#555;margin-top:2px;">K线数据: 2026-01-05 ~ 2026-05-15 | 涨停池: 45个交易日 | 概念: 358个题材</p>

    <div class="search-box">
        <div class="input-row">
            <div class="input-item">
                <label>股票代码或名称</label>
                <input type="text" id="stockInput" placeholder="如: 600396 或 华电辽能" autocomplete="off">
                <div class="suggestions" id="suggestions"></div>
            </div>
            <div class="input-item">
                <label>限定概念（可选）</label>
                <input type="text" id="conceptInput" placeholder="如: 绿色电力">
            </div>
            <div style="display: flex; align-items: flex-end;">
                <button onclick="doSearch()">查询联动</button>
            </div>
        </div>
    </div>

    <div class="tabs">
        <div class="tab active" onclick="switchTab('npattern')">N字战法</div>
        <div class="tab" onclick="switchTab('linkage')">联动查询</div>
        <div class="tab" onclick="switchTab('concept')">概念分析</div>
        <div class="tab" onclick="switchTab('recommend')">🔥 推荐</div>
        <div class="tab" onclick="switchTab('stats')">📈 统计</div>
    </div>

    <div class="tab-content active" id="tab-npattern">
        <div id="npatternContainer"><div class="loading">加载N字战法分析中...</div></div>
    </div>
    <div class="tab-content" id="tab-linkage">
        <div id="resultContainer">
            <div class="empty">🔍 输入股票代码或名称开始查询</div>
        </div>
    </div>
    <div class="tab-content" id="tab-concept">
        <div class="search-box">
            <div class="input-row">
                <div class="input-item" style="position:relative;">
                    <label>概念名称</label>
                    <input type="text" id="conceptQueryInput" placeholder="如: 存储芯片、绿色电力" autocomplete="off">
                    <div class="suggestions" id="conceptSuggestions"></div>
                </div>
                <div style="display: flex; align-items: flex-end;">
                    <button onclick="doConceptSearch()">分析概念</button>
                </div>
            </div>
        </div>
        <div id="conceptResult"><div class="empty">输入概念名称进行分析</div></div>
    </div>
    <div class="tab-content" id="tab-recommend">
        <div id="recommendContainer"><div class="loading">分析候选股票中...</div></div>
    </div>
    <div class="tab-content" id="tab-stats">
        <div id="statsContainer"><div class="loading">加载统计中...</div></div>
    </div>
</div>

<div id="klineModal" class="kline-modal-overlay" onclick="if(event.target===this)closeKlineModal()">
    <div class="kline-modal" id="klineModalContent">
        <span class="kline-modal-close" onclick="closeKlineModal()">&times;</span>
        <h3 id="klineModalTitle">Loading...</h3>
        <div id="klineModalBadges" class="np-card-badges"></div>
        <div id="klineModalMetrics" class="np-metrics"></div>
        <div id="klineModalCanvas" style="margin-top:12px;"><canvas id="klineModalChart" height="280"></canvas></div>
    </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js"></script>
<script>
Chart.register(ChartDataLabels);

var currentTab = 'npattern';

// Tab switching
function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    if (tab === 'npattern') document.querySelectorAll('.tab')[0].classList.add('active');
    else if (tab === 'linkage') document.querySelectorAll('.tab')[1].classList.add('active');
    else if (tab === 'concept') document.querySelectorAll('.tab')[2].classList.add('active');
    else if (tab === 'recommend') document.querySelectorAll('.tab')[3].classList.add('active');
    else if (tab === 'stats') document.querySelectorAll('.tab')[4].classList.add('active');
    document.getElementById('tab-' + tab).classList.add('active');

    if (tab === 'npattern') loadNPattern();
    if (tab === 'stats') loadStats();
    if (tab === 'recommend') loadRecommend();
    if (tab === 'concept') loadTopConcepts();
}

// Search suggestions
var suggestTimer = null;
document.getElementById('stockInput').addEventListener('input', function() {
    clearTimeout(suggestTimer);
    var q = this.value.trim();
    if (q.length < 1) { document.getElementById('suggestions').classList.remove('active'); return; }
    suggestTimer = setTimeout(function() {
        fetch('/api/search?q=' + encodeURIComponent(q))
            .then(r => r.json())
            .then(renderSuggestions);
    }, 200);
});

// Concept autocomplete
var conceptNames = [];
fetch('/api/concepts').then(function(r) { return r.json(); }).then(function(names) {
    conceptNames = names || [];
});

// Close both suggestions when clicking outside
document.addEventListener('click', function(e) {
    if (!e.target.closest('.input-item')) {
        document.getElementById('suggestions').classList.remove('active');
        var cs = document.getElementById('conceptSuggestions');
        if (cs) cs.classList.remove('active');
    }
});

document.getElementById('conceptQueryInput').addEventListener('input', function() {
    var q = this.value.trim().toLowerCase();
    var el = document.getElementById('conceptSuggestions');
    if (q.length < 1 || conceptNames.length === 0) {
        el.classList.remove('active');
        return;
    }
    var matches = conceptNames.filter(function(n) { return n.toLowerCase().indexOf(q) !== -1; }).slice(0, 12);
    if (matches.length === 0) { el.classList.remove('active'); return; }
    var html = '';
    matches.forEach(function(name) {
        html += '<div class="suggestion-item" data-suggest-concept="' + name + '">';
        html += '<span>' + name + '</span>';
        html += '</div>';
    });
    el.innerHTML = html;
    el.classList.add('active');
});

function renderSuggestions(items) {
    var el = document.getElementById('suggestions');
    if (!items || items.length === 0) { el.classList.remove('active'); return; }
    var html = '';
    items.slice(0, 10).forEach(function(item) {
        html += '<div class="suggestion-item" data-code="' + item.code + '" data-name="' + item.name + '">';
        html += '<span><span class="sug-code">' + item.code + '</span> ' + item.name + '</span>';
        html += '<span class="sug-meta">涨停' + item.zt_count + '次 | ' + item.concept_count + '概念</span>';
        html += '</div>';
    });
    el.innerHTML = html;
    el.classList.add('active');
}

function selectStock(code, name) {
    document.getElementById('stockInput').value = code + ' (' + name + ')';
    document.getElementById('suggestions').classList.remove('active');
    doSearch();
}

// Global event delegation for stock rows, concept tabs, sortable headers, and show-all
document.addEventListener('click', function(e) {
    var showBtn = e.target.closest('[data-show-section]');
    if (showBtn) {
        var section = showBtn.getAttribute('data-show-section');
        if (section === 'linkage') {
            window._showAllLinkage = !(window._showAllLinkage);
        } else if (section === 'concept') {
            window._showAllConcept = !(window._showAllConcept);
        } else if (section === 'hot') {
            window._showAllHot = !(window._showAllHot);
        } else if (section === 'stats') {
            window._showAllStats = !(window._showAllStats);
        }
        // Re-render current view
        if (currentTab === 'linkage') renderSortedLinkages();
        else if (currentTab === 'concept') doConceptSearch();
        else if (currentTab === 'hot') loadHotStocks();
        else if (currentTab === 'stats') loadStats();
        return;
    }
    var bucketBtn = e.target.closest('[data-bucket]');
    if (bucketBtn) {
        var bType = bucketBtn.getAttribute('data-bucket');
        var bKey = bucketBtn.getAttribute('data-bucket-key');
        // Highlight this button, un-highlight others in same bar
        var bar = bucketBtn.closest('.bucket-bar');
        if (bar) bar.querySelectorAll('.bucket-btn').forEach(function(b) { b.classList.remove('active'); });
        bucketBtn.classList.add('active');
        _currentBucketType = bType;
        _currentBucketKey = bKey;
        // Get current date params
        var sd = document.getElementById('statsStartDate') ? document.getElementById('statsStartDate').value : '';
        var ed = document.getElementById('statsEndDate') ? document.getElementById('statsEndDate').value : '';
        var params = [];
        if (sd) params.push('start_date=' + sd.replace(/-/g, ''));
        if (ed) params.push('end_date=' + ed.replace(/-/g, ''));
        var paramStr = params.length ? '&' + params.join('&') : '';
        loadBucketDetail(bType, bKey, paramStr);
        return;
    }
    var conceptTab = e.target.closest('[data-concept]');
    if (conceptTab) {
        var concept = conceptTab.getAttribute('data-concept');
        selectConcept(concept);
        return;
    }
    var conceptSuggest = e.target.closest('[data-suggest-concept]');
    if (conceptSuggest) {
        var conceptName = conceptSuggest.getAttribute('data-suggest-concept');
        document.getElementById('conceptQueryInput').value = conceptName;
        document.getElementById('conceptSuggestions').classList.remove('active');
        doConceptSearch();
        return;
    }
    var header = e.target.closest('th[data-sort]');
    if (header) {
        var field = header.getAttribute('data-sort');
        toggleSort(field);
        return;
    }
    var el = e.target.closest('[data-code]');
    if (el) {
        var code = el.getAttribute('data-code');
        var name = el.getAttribute('data-name');
        if (code) {
            if (currentTab === 'npattern') {
                selectStock(code, name || code);
            } else {
                showStockCard(code, name || code);
            }
        }
        return;
    }
    var klineBtn = e.target.closest('[data-kline-id]');
    if (klineBtn) {
        var klineId = klineBtn.getAttribute('data-kline-id');
        toggleNpKline(klineId);
        return;
    }
});

// Main search
function doSearch() {
    var raw = document.getElementById('stockInput').value.trim();
    var concept = document.getElementById('conceptInput').value.trim();
    if (!raw) { alert('请输入股票代码或名称'); return; }

    var stock = raw;
    var codeMatch = raw.match(/(\\d{6})/);
    if (codeMatch) stock = codeMatch[1];

    switchTab('linkage');

    var container = document.getElementById('resultContainer');
    container.innerHTML = '<div class="loading">查询中...</div>';

    var url = '/api/linkage?stock=' + encodeURIComponent(stock);
    if (concept) url += '&concept=' + encodeURIComponent(concept);
    url += '&min_prob=0.10';

    fetch(url).then(r => r.json()).then(renderLinkageResult).catch(function(e) {
        container.innerHTML = '<div class="error">请求失败</div>';
    });
}

function renderLinkageResult(data) {
    var container = document.getElementById('resultContainer');
    if (data.error) { container.innerHTML = '<div class="error">' + data.error + '</div>'; return; }

    if (!data.linkages || data.linkages.length === 0) {
        var html = '<div class="result"><div class="stock-info">';
        html += '<span class="code-badge">' + data.stock_code + '</span>';
        html += '<span class="stock-name">' + (data.stock_name || data.stock_code) + '</span>';
        html += '<span class="zt-count">涨停 <strong style="color:#ff6b6b">' + (data.base_zt_count || 0) + '</strong> 次</span>';
        if (data.base_zt_dates && data.base_zt_dates.length > 0) {
            html += '<div style="margin-top:8px;">';
            data.base_zt_dates.forEach(function(d) { html += '<span class="zt-date-tag">' + d + '</span>'; });
            html += '</div>';
        }
        html += '</div><div class="empty">未找到联动股票（涨停次数需≥2）</div></div>';
        container.innerHTML = html;
        return;
    }

    // Store data globally for sorting
    window._linkageData = data.linkages || [];
    window._currentSortField = 'strength';
    window._currentSortOrder = 'desc';
    window._currentStockCode = data.stock_code;
    window._currentStockName = data.stock_name || data.stock_code;
    window._currentConcepts = data.concepts || [];
    window._currentBaseZtCount = data.base_zt_count || 0;
    window._currentDataSource = data.data_source;
    window._currentBaseZtDates = data.base_zt_dates || [];
    window._currentDirectionA = data.direction_a_to_b;

    container.innerHTML = '<div class="loading">排序中...</div>';
    renderSortedLinkages();
}

function renderSortedLinkages() {
    var data = window._linkageData;
    if (!data || data.length === 0) return;

    var sortField = window._currentSortField || 'strength';
    var sortOrder = window._currentSortOrder || 'desc';

    // Build concept groups (deduplicated)
    var grouped = {};
    data.forEach(function(link) {
        var concepts = link.shared_concepts || [link.concept || '未知'];
        concepts.forEach(function(c) {
            if (!grouped[c]) grouped[c] = [];
            var exists = grouped[c].some(function(x) { return x.linked_stock === link.linked_stock; });
            if (!exists) grouped[c].push(link);
        });
    });
    var conceptNames = Object.keys(grouped);
    // If a concept was previously selected, validate it still exists
    var selectedConcept = window._selectedConcept;
    if (selectedConcept && selectedConcept !== '全部' && grouped[selectedConcept]) {
        // keep it
    } else {
        window._selectedConcept = '全部';
        selectedConcept = '全部';
    }

    var html = '<div class="result"><div class="stock-info">';
    html += '<span class="code-badge">' + window._currentStockCode + '</span>';
    html += '<span class="stock-name">' + window._currentStockName + '</span>';
    html += '<span class="zt-count">涨停 <strong style="color:#ff6b6b">' + (window._currentBaseZtCount || 0) + '</strong> 次</span>';
    if (window._currentDataSource) {
        html += '<span class="badge badge-pool">涨停池 ' + (window._currentDataSource.zt_pool_count || 0) + '次</span>';
        html += '<span class="badge badge-db">数据库 ' + (window._currentDataSource.db_count || 0) + '次</span>';
    }
    html += '</div>';

    // ZT dates
    if (window._currentBaseZtDates && window._currentBaseZtDates.length > 0) {
        html += '<div style="margin-bottom: 15px;"><span style="color: #888; font-size: 0.9em;">涨停日期: </span>';
        window._currentBaseZtDates.forEach(function(d) { html += '<span class="zt-date-tag">' + d + '</span>'; });
        html += '</div>';
    }

    // Concepts
    if (window._currentConcepts && window._currentConcepts.length > 0) {
        html += '<div style="margin-bottom: 10px;">';
        window._currentConcepts.forEach(function(c) { html += '<span class="tag">' + c + '</span>'; });
        html += '</div>';
    }

    if (!data || data.length === 0) {
        html += '<div class="empty">未找到联动股票（涨停次数需≥2）</div></div>';
        document.getElementById('resultContainer').innerHTML = html;
        return;
    }

    // Directionality summary
    if (window._currentDirectionA) {
        html += '<div style="margin-bottom: 12px; display: flex; gap: 15px; flex-wrap: wrap;">';
        html += '<span class="badge badge-pool">A\u2192B 联动股票: ' + window._currentDirectionA.total_linked_stocks + '只</span>';
        html += '<span class="badge badge-db">强联动(\u226530%): ' + window._currentDirectionA.strong_linkages + '只</span>';
        html += '</div>';
    }

    // Concept tabs
    var sortedNames = conceptNames.slice().sort(function(a, b) { return grouped[b].length - grouped[a].length; });
    html += '<div class="concept-tabs">';
    var allActive = selectedConcept === '全部' ? ' active' : '';
    html += '<span class="concept-tab' + allActive + '" data-concept="全部">全部 (' + data.length + ')</span>';
    sortedNames.forEach(function(c) {
        var active = selectedConcept === c ? ' active' : '';
        html += '<span class="concept-tab' + active + '" data-concept="' + c + '">' + c + ' (' + grouped[c].length + ')</span>';
    });
    html += '</div>';

    // Sort arrow helper
    function sortArrow(field) {
        if (sortField !== field) return '';
        return sortOrder === 'desc' ? ' \u25BC' : ' \u25B2';
    }

    // Render tables
    var conceptsToShow = selectedConcept === '全部' ? sortedNames : [selectedConcept];
    conceptsToShow.forEach(function(concept) {
        var links = grouped[concept];
        // Sort within this concept
        var sorted = links.slice().sort(function(a, b) {
            var va = a[sortField] !== undefined ? a[sortField] : 0;
            var vb = b[sortField] !== undefined ? b[sortField] : 0;
            return sortOrder === 'desc' ? vb - va : va - vb;
        });
        var showAll = window._showAllLinkage || false;
        var limit = showAll ? sorted.length : 15;
        var topData = sorted.slice(0, limit);
        var hiddenCount = sorted.length - limit;

        html += '<div class="concept-section">';
        html += '<div class="section-header">';
        html += '<h4>' + concept + ' (' + sorted.length + '只)</h4>';
        if (sorted.length > 15) {
            var btnText = showAll ? '收起' : '显示全部';
            html += '<span class="show-all-btn" data-show-section="linkage">' + btnText + '</span>';
        }
        html += '</div>';
        html += '<table>';
        html += '<tr><th>#</th><th>代码</th><th>名称</th>';
        html += '<th data-sort="prob_t0" class="sortable">T+0' + sortArrow('prob_t0') + '</th>';
        html += '<th data-sort="prob_t1" class="sortable">T+1' + sortArrow('prob_t1') + '</th>';
        html += '<th data-sort="prob_t2" class="sortable">T+2' + sortArrow('prob_t2') + '</th>';
        html += '<th data-sort="prob_t3" class="sortable">T+3' + sortArrow('prob_t3') + '</th>';
        html += '<th data-sort="strength" class="sortable">综合' + sortArrow('strength') + '</th>';
        html += '<th>联动次数</th><th>自身ZT</th></tr>';

        topData.forEach(function(link, idx) {
            var l0 = (link.prob_t0 * 100).toFixed(0);
            var l1 = (link.prob_t1 * 100).toFixed(0);
            var l2 = (link.prob_t2 * 100).toFixed(0);
            var l3 = (link.prob_t3 * 100).toFixed(0);
            var sp = (link.strength * 100).toFixed(0);
            var events = link.linkage_events || [];

            html += '<tr class="clickable" data-code="' + link.linked_stock + '" data-name="' + link.linked_name + '">';
            html += '<td style="color:#888;">' + (idx + 1) + '</td>';
            html += '<td><strong>' + link.linked_stock + '</strong></td><td>' + link.linked_name + '</td>';
            html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t0" style="width:' + l0 + '%"></div></div><span>' + l0 + '%</span></div></td>';
            html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t1" style="width:' + l1 + '%"></div></div><span>' + l1 + '%</span></div></td>';
            html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t2" style="width:' + l2 + '%"></div></div><span>' + l2 + '%</span></div></td>';
            html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t3" style="width:' + l3 + '%"></div></div><span>' + l3 + '%</span></div></td>';
            html += '<td><strong style="color:#00ff88">' + sp + '%</strong></td>';
            html += '<td>' + events.length + '</td><td>' + (link.linked_zt_count || 0) + '</td>';
            html += '</tr>';

            // Event details row
            if (events.length > 0) {
                var stockName = window._currentStockName || 'A';
                var linkedName = link.linked_name || 'B';
                html += '<tr class="event-row"><td colspan="11">';
                // Direction & reverse probability
                html += '<div class="event-header">';
                html += '<span class="dir-label">方向:</span> ';
                html += '<span class="stock-a">' + stockName + '</span>';
                html += '<span style="color:#888;margin:0 4px;">\u2192</span>';
                html += '<span class="stock-b">' + linkedName + '</span>';
                html += '<span class="dir-sep">|</span>';
                html += '<span class="dir-item">正向(A涨\u2192B涨): <b style="color:#00d4ff">' + sp + '%</b></span>';
                if (link.reverse_strength !== undefined) {
                    var revStr = (link.reverse_strength * 100).toFixed(0);
                    html += '<span class="dir-sep">|</span>';
                    html += '<span class="dir-item">反向(B涨\u2192A涨): <b style="color:#ffc107">' + revStr + '%</b></span>';
                }
                html += '</div>';

                // Event timeline
                html += '<div class="event-timeline">';
                html += '<span style="color:#888;margin-right:6px;">联动记录:</span>';
                events.slice(-5).forEach(function(evt) {
                    var lagLabel = evt.lag > 0 ? 'T+' + evt.lag : 'T+0';
                    var baseShort = evt.base_date.slice(2);
                    var linkedShort = evt.linked_date.slice(2);
                    html += '<span class="event-tag">';
                    html += '<span class="evt-a">' + baseShort + '</span>';
                    html += '<span class="evt-arrow">\u2192</span>';
                    html += '<span class="evt-b">' + linkedShort + '</span>';
                    html += '<span class="evt-lag">' + lagLabel + '</span>';
                    html += '</span> ';
                });
                if (events.length > 5) html += '<span style="color:#666;font-size:0.85em;">...等' + events.length + '次</span>';
                html += '</div>';
                html += '</td></tr>';
            }
        });
        html += '</table></div>';
    });

    // Gem/Star arbitrage button at bottom (only for main board stocks)
    var sc = window._currentStockCode || '';
    if (!sc.startsWith('3') && !sc.startsWith('688') && !sc.startsWith('4') && !sc.startsWith('8') && sc.length === 6) {
        html += '<div style="margin-top: 16px; border-top: 1px solid rgba(255,152,0,0.3); padding-top: 12px;">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
        html += '<button class="arb-btn" onclick="loadGemArbitrage(&#39;' + sc + '&#39;)">\u7B5B\u67E5\u521B\u4E1A\u677F/\u79D1\u521B\u677F\u5957\u5229\u673A\u4F1A</button>';
        html += '<span style="color:#888;font-size:0.85em;">\u540C\u6982\u5FF5\u4E0B\u521B\u4E1A\u677F/\u79D1\u521B\u677F >10% \u6DA8\u5E45\u8054\u52A8</span>';
        html += '</div>';
        html += '<div id="gemArbitrageContainer"></div>';
        html += '</div>';
    }

    html += '</div>';
    document.getElementById('resultContainer').innerHTML = html;
}

function toggleSort(field) {
    if (window._currentSortField === field) {
        window._currentSortOrder = window._currentSortOrder === 'desc' ? 'asc' : 'desc';
    } else {
        window._currentSortField = field;
        window._currentSortOrder = 'desc';
    }
    renderSortedLinkages();
}

function selectConcept(concept) {
    window._selectedConcept = concept;
    renderSortedLinkages();
}

// Concept analysis

// Concept analysis
function doConceptSearch() {
    var concept = document.getElementById('conceptQueryInput').value.trim();
    if (!concept) { alert('请输入概念名称'); return; }

    var container = document.getElementById('conceptResult');
    container.innerHTML = '<div class="loading">分析中...</div>';

    Promise.all([
        fetch('/api/concept_zt_stats?concept=' + encodeURIComponent(concept)).then(r => r.json()),
        fetch('/api/concept_linkage?concept=' + encodeURIComponent(concept) + '&top_n=50').then(r => r.json())
    ]).then(function(results) {
        var stats = results[0], linkage = results[1];
        if (!stats || stats.total_stocks === 0) {
            container.innerHTML = '<div class="result"><div class="empty">概念不存在或无数据</div></div>';
            return;
        }

        var html = '<div class="result"><div class="stock-info">';
        html += '<span class="stock-name">' + (stats.concept || concept) + '</span>';
        html += '<span class="zt-count">成分股: <strong>' + stats.total_stocks + '</strong>只, 有涨停: <strong style="color:#ff6b6b">' + stats.zt_stock_count + '</strong>只</span>';
        html += '</div>';

        if (stats.peak_dates && stats.peak_dates.length > 0) {
            html += '<div style="margin-bottom: 10px;"><span style="color: #888;">峰值涨停日: </span>';
            html += '<div class="peak-list" style="display:inline-flex;">';
            stats.peak_dates.slice(0, 6).forEach(function(p) {
                html += '<span class="peak-item"><span class="peak-date">' + p.date + '</span> <span class="peak-count">' + p.count + '股</span></span>';
            });
            html += '</div></div>';
        }

        var showAllConcept = window._showAllConcept || false;
        var ztLimit = showAllConcept ? (stats.zt_stocks || []).length : 15;
        var ztHidden = (stats.zt_stocks || []).length - ztLimit;
        html += '<div class="section-header"><h3>涨停股票</h3>';
        if ((stats.zt_stocks || []).length > 15) {
            html += '<span class="show-all-btn" data-show-section="concept">' + (showAllConcept ? '收起' : '显示全部') + '</span>';
        }
        html += '<span style="font-weight:normal;font-size:0.85em;color:#888;margin-left:auto;">共' + (stats.zt_stocks || []).length + '只</span></div>';
        html += '<table><tr><th>代码</th><th>名称</th><th>涨停次数</th><th>最近涨停</th></tr>';
        stats.zt_stocks.slice(0, ztLimit).forEach(function(s) {
            html += '<tr class="clickable" data-code="' + s.code + '" data-name="' + s.name + '">';
            html += '<td><strong>' + s.code + '</strong></td><td>' + s.name + '</td>';
            html += '<td style="color:#ff6b6b;font-weight:bold">' + s.zt_count + '</td><td>' + s.last_zt + '</td></tr>';
        });
        html += '</table>';

        if (linkage && linkage.pairs && linkage.pairs.length > 0) {
            var pairLimit = showAllConcept ? linkage.pairs.length : 15;
            html += '<div class="section-header"><h3>最强联动对</h3>';
            if (linkage.pairs.length > 15) {
                html += '<span class="show-all-btn" data-show-section="concept">' + (showAllConcept ? '收起' : '显示全部') + '</span>';
            }
            html += '<span style="font-weight:normal;font-size:0.85em;color:#888;margin-left:auto;">共' + linkage.pairs.length + '对</span></div>';
            html += '<table><tr><th>股票A</th><th>名称A</th><th>→</th><th>股票B</th><th>名称B</th><th>T+0</th><th>T+1</th><th>T+2</th><th>T+3</th><th>综合</th></tr>';
            linkage.pairs.slice(0, pairLimit).forEach(function(p) {
                var t0 = (p.prob_t0 * 100).toFixed(0);
                var t1 = (p.lag1_prob * 100).toFixed(0);
                var t2 = (p.lag2_prob * 100).toFixed(0);
                var t3 = (p.lag3_prob * 100).toFixed(0);
                html += '<tr class="clickable" data-code="' + p.stock_a + '" data-name="' + p.name_a + '">';
                html += '<td><strong>' + p.stock_a + '</strong></td><td>' + p.name_a + '</td>';
                html += '<td style="text-align:center;color:#00d4ff">→</td>';
                html += '<td><strong>' + p.stock_b + '</strong></td><td>' + p.name_b + '</td>';
                html += '<td>' + t0 + '%</td>';
                html += '<td>' + t1 + '%</td>';
                html += '<td>' + t2 + '%</td>';
                html += '<td>' + t3 + '%</td>';
                html += '<td><strong style="color:#00ff88">' + (p.strength * 100).toFixed(0) + '%</strong></td></tr>';
            });
            html += '</table>';
        }

        html += '</div>';
        container.innerHTML = html;
    });
}

// Hot stocks
// Stats page
var statsCharts = [];
var _currentBucketType = '';
var _currentBucketKey = '';

function loadStats() {
    var container = document.getElementById('statsContainer');
    container.innerHTML = '<div class="loading">加载统计中...</div>';

    // Destroy previous charts
    statsCharts.forEach(function(c) { if (c) c.destroy(); });
    statsCharts = [];

    // Read date filter values from UI
    var sd = document.getElementById('statsStartDate') ? document.getElementById('statsStartDate').value : '';
    var ed = document.getElementById('statsEndDate') ? document.getElementById('statsEndDate').value : '';
    // Default: last 90 days on first load
    if (!sd && !document.getElementById('statsStartDate')) {
        var d = new Date();
        d.setDate(d.getDate() - 90);
        sd = d.toISOString().slice(0, 10);
    }
    var params = [];
    if (sd) params.push('start_date=' + sd.replace(/-/g, ''));
    if (ed) params.push('end_date=' + ed.replace(/-/g, ''));
    var paramStr = params.length ? '?' + params.join('&') : '';
    var bucketParamStr = params.length ? '&' + params.join('&') : '';
    var statsUrl = '/api/stats' + paramStr;

    fetch(statsUrl).then(function(r) { return r.json(); }).then(function(data) {
        if (!data || data.error) {
            container.innerHTML = '<div class="error">统计数据加载失败</div>';
            return;
        }

        var html = '<div class="result">';

        // ---- Date filter bar ----
        var defaultStart = sd || '';
        if (!defaultStart) {
            var d = new Date();
            d.setDate(d.getDate() - 90);
            defaultStart = d.toISOString().slice(0, 10);
        }
        var defaultEnd = ed || data.summary.date_range.end || '';
        if (defaultStart && defaultStart.indexOf('-') === -1 && defaultStart.length === 8) {
            defaultStart = defaultStart.slice(0,4) + '-' + defaultStart.slice(4,6) + '-' + defaultStart.slice(6,8);
        }
        if (defaultEnd && defaultEnd.indexOf('-') === -1 && defaultEnd.length === 8) {
            defaultEnd = defaultEnd.slice(0,4) + '-' + defaultEnd.slice(4,6) + '-' + defaultEnd.slice(6,8);
        }
        html += '<div class="filter-bar">';
        html += '<div><label>开始日期</label><br><input type="date" id="statsStartDate" value="' + defaultStart + '"></div>';
        html += '<div><label>结束日期</label><br><input type="date" id="statsEndDate" value="' + defaultEnd + '"></div>';
        html += '<button class="btn" id="statsFilterBtn">更新统计</button>';
        html += '</div>';

        // ---- Summary cards ----
        html += '<div class="stat-cards">';
        html += '<div class="stat-card"><div class="stat-label">涨停股票</div><div class="stat-value red">' + data.summary.total_stocks_with_zt + '</div></div>';
        html += '<div class="stat-card"><div class="stat-label">涨停事件</div><div class="stat-value">' + data.summary.total_zt_events + '</div></div>';
        html += '<div class="stat-card"><div class="stat-label">交易日</div><div class="stat-value" style="font-size:1.2em;">' + data.summary.date_range.start.slice(2) + '~' + data.summary.date_range.end.slice(2) + '</div></div>';
        html += '<div class="stat-card"><div class="stat-label">题材概念</div><div class="stat-value green">' + data.summary.total_concepts + '</div></div>';
        html += '</div>';

        // ---- Chart grid: Top 50 stocks + Top 50 concepts (2-col) ----
        html += '<div class="chart-grid">';
        html += '<div class="chart-box"><h4>涨停次数最多股票 Top 50 <span style="color:#888;font-size:0.8em;font-weight:normal;">（点击跳转）</span></h4><canvas id="chartTopStocks"></canvas></div>';
        html += '<div class="chart-box"><h4>涨停活跃概念 Top 50 <span style="color:#888;font-size:0.8em;font-weight:normal;">（点击跳转）</span></h4><canvas id="chartTopConcepts"></canvas></div>';
        html += '</div>';

        // ---- Chart: Daily activity (full width) ----
        html += '<div class="chart-box"><h4>每日涨停股票数</h4><canvas id="chartDaily"></canvas></div>';

        // ---- 连板分布 (clickable buttons) ----
        var lianban = data.summary.lianban_distribution || {};
        var lbLabels = Object.keys(lianban);
        html += '<div class="dist-section"><h4>连板分布</h4>';
        html += '<div class="bucket-bar" data-bucket-type="lianban">';
        lbLabels.forEach(function(k) {
            var active = (_currentBucketType === 'lianban' && _currentBucketKey === k) ? ' active' : '';
            html += '<span class="bucket-btn' + active + '" data-bucket="lianban" data-bucket-key="' + k + '">' + k + ': ' + lianban[k] + '</span>';
        });
        html += '</div>';
        html += '<div class="bucket-detail' + (_currentBucketType === 'lianban' ? ' active' : '') + '" id="bucketDetailLianban"></div>';
        html += '</div>';

        // ---- 涨停次数分布 (clickable buttons) ----
        var dist = data.summary.daily_zt_distribution || {};
        var distLabels = Object.keys(dist);
        html += '<div class="dist-section"><h4>涨停次数分布</h4>';
        html += '<div class="bucket-bar" data-bucket-type="zt">';
        distLabels.forEach(function(k) {
            var active = (_currentBucketType === 'zt' && _currentBucketKey === k) ? ' active' : '';
            html += '<span class="bucket-btn' + active + '" data-bucket="zt" data-bucket-key="' + k + '">' + k + ': ' + dist[k] + '</span>';
        });
        html += '</div>';
        html += '<div class="bucket-detail' + (_currentBucketType === 'zt' ? ' active' : '') + '" id="bucketDetailZt"></div>';
        html += '</div>';

        // ---- 热门涨停股票 (at bottom) ----
        html += '<div class="hot-section">';
        html += '<div class="section-header" style="margin-bottom:8px;">';
        html += '<h4>热门涨停股票</h4>';
        var showAllHot = window._showAllHot || false;
        html += '<span class="show-all-btn" data-show-section="hot">' + (showAllHot ? '收起' : '显示全部') + '</span>';
        html += '</div>';
        html += '<div id="statsHotContainer"><div class="loading" style="padding:10px;">加载中...</div></div>';
        html += '</div>';

        html += '</div>';
        container.innerHTML = html;

        // Wire up filter button
        document.getElementById('statsFilterBtn').addEventListener('click', function() {
            loadStats();
        });

        // ===== Chart 1: Top stocks (horizontal bar) =====
        var topStocks = data.top_stocks || [];
        if (topStocks.length > 0) {
            var ctx1 = document.getElementById('chartTopStocks').getContext('2d');
            statsCharts.push(new Chart(ctx1, {
                type: 'bar',
                data: {
                    labels: topStocks.map(function(s) { return s.code + ' ' + s.name; }),
                    datasets: [{
                        label: '涨停次数',
                        data: topStocks.map(function(s) { return s.zt_count; }),
                        backgroundColor: topStocks.map(function(s) {
                            var c = s.zt_count;
                            return c >= 15 ? '#e94560' : c >= 10 ? '#ffc107' : c >= 5 ? '#00d4ff' : '#0f3460';
                        }),
                        borderRadius: 4
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false, indexAxis: 'y',
                    onClick: function(e, elements) {
                        if (elements.length > 0) {
                            var idx = elements[0].index;
                            var stock = topStocks[idx];
                            if (stock) selectStock(stock.code, stock.name);
                        }
                    },
                    plugins: {
                        legend: { display: false },
                        datalabels: { anchor: 'end', align: 'end', color: '#eee', font: { size: 9 }, formatter: function(v) { return v + '次'; } }
                    },
                    scales: {
                        x: { grid: { color: '#333' }, ticks: { color: '#888' } },
                        y: { grid: { display: false }, ticks: { color: '#aaa', font: { size: 9 } } }
                    }
                }
            }));
        }

        // ===== Chart 2: Top concepts (horizontal bar) =====
        var topConcepts = data.top_concepts || [];
        if (topConcepts.length > 0) {
            var ctx2 = document.getElementById('chartTopConcepts').getContext('2d');
            statsCharts.push(new Chart(ctx2, {
                type: 'bar',
                data: {
                    labels: topConcepts.map(function(s) { return s.concept; }),
                    datasets: [{
                        label: '涨停事件',
                        data: topConcepts.map(function(s) { return s.total_zt_events; }),
                        backgroundColor: topConcepts.map(function(s) {
                            var c = s.total_zt_events;
                            return c >= 100 ? '#e94560' : c >= 50 ? '#ffc107' : c >= 20 ? '#00d4ff' : '#0f3460';
                        }),
                        borderRadius: 4
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false, indexAxis: 'y',
                    onClick: function(e, elements) {
                        if (elements.length > 0) {
                            var idx = elements[0].index;
                            var concept = topConcepts[idx];
                            if (concept) {
                                switchTab('concept');
                                var ci = document.getElementById('conceptQueryInput');
                                if (ci) { ci.value = concept.concept; }
                                setTimeout(function() { doConceptSearch(); }, 50);
                            }
                        }
                    },
                    plugins: {
                        legend: { labels: { color: '#888', font: { size: 10 } } },
                        datalabels: {
                            anchor: 'end', align: 'end', color: '#eee', font: { size: 8 },
                            formatter: function(v, ctx) {
                                var idx = ctx.dataIndex;
                                var sc = topConcepts[idx] ? topConcepts[idx].zt_stock_count : 0;
                                return v + '次/' + sc + '股';
                            }
                        }
                    },
                    scales: {
                        x: { grid: { color: '#333' }, ticks: { color: '#888' } },
                        y: { grid: { display: false }, ticks: { color: '#aaa', font: { size: 9 } } }
                    }
                }
            }));
        }

        // ===== Chart 3: Daily activity =====
        var dailyData = data.daily_activity || [];
        if (dailyData.length > 0) {
            var ctx3 = document.getElementById('chartDaily').getContext('2d');
            statsCharts.push(new Chart(ctx3, {
                type: 'line',
                data: {
                    labels: dailyData.map(function(d) { return d.date.slice(4); }),
                    datasets: [{
                        label: '涨停股票数',
                        data: dailyData.map(function(d) { return d.zt_count; }),
                        borderColor: '#00d4ff',
                        backgroundColor: 'rgba(0,212,255,0.1)',
                        fill: true, tension: 0.3, pointRadius: 2, pointHitRadius: 10
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { labels: { color: '#888' } }, datalabels: { display: false } },
                    scales: {
                        x: { grid: { color: '#333' }, ticks: { color: '#888', font: { size: 9 } } },
                        y: { grid: { color: '#333' }, ticks: { color: '#888' } }
                    }
                }
            }));
        }

        // ===== Load hot stocks =====
        loadStatsHotStocks(paramStr);

        // ===== Already loaded bucket content if needed =====
        if (_currentBucketType && _currentBucketKey) {
            loadBucketDetail(_currentBucketType, _currentBucketKey, bucketParamStr);
        }

    }).catch(function(e) {
        container.innerHTML = '<div class="error">统计加载失败: ' + e.message + '</div>';
    });
}

// Load hot stocks section at bottom of stats
function loadStatsHotStocks(paramStr) {
    var container = document.getElementById('statsHotContainer');
    if (!container) return;
    var url = '/api/hot_stocks?top_n=200' + (paramStr ? paramStr.replace('?', '&') : '');
    fetch(url).then(function(r) { return r.json(); }).then(function(data) {
        if (!data || data.length === 0) {
            container.innerHTML = '<div class="empty">暂无数据</div>';
            return;
        }
        var showAllHot = window._showAllHot || false;
        var limit = showAllHot ? data.length : 30;
        var sorted = data.slice(0, limit);

        function scoreClass(sc) {
            if (sc >= 70) return 'score-high';
            if (sc >= 40) return 'score-mid';
            return 'score-low';
        }
        var html = '<table><tr><th>#</th><th>代码</th><th>名称</th><th>涨停</th><th>综合评分</th><th>题材概念</th><th>时间周期</th><th>最近涨停</th></tr>';
        sorted.forEach(function(s, i) {
            var concepts = s.concepts || [];
            var conceptHtml = concepts.slice(0, 3).map(function(c) {
                return '<span class="concept-badge">' + c + '</span>';
            }).join(' ');
            if (concepts.length > 3) {
                conceptHtml += ' <span style="color:#888;font-size:0.8em;">+' + (concepts.length - 3) + '</span>';
            }
            html += '<tr class="clickable" data-code="' + s.code + '" data-name="' + s.name + '">';
            html += '<td style="color:#888;">' + (i+1) + '</td>';
            html += '<td><strong>' + s.code + '</strong></td>';
            html += '<td>' + (s.name || '') + '</td>';
            html += '<td style="color:#ff6b6b;font-weight:bold;">' + s.zt_count + '次</td>';
            html += '<td><span class="score-badge ' + scoreClass(s.weighted_score) + '">' + s.weighted_score + '</span></td>';
            html += '<td>' + conceptHtml + '</td>';
            html += '<td style="color:#888;font-size:0.85em;">' + (s.date_range_text || '') + '</td>';
            html += '<td>' + (s.last_zt || '') + '</td></tr>';
        });
        html += '</table>';
        if (data.length > limit) {
            html += '<div style="text-align:center;color:#666;padding:6px;font-size:0.85em;">共' + data.length + '只，显示' + limit + '只</div>';
        }
        container.innerHTML = html;
    }).catch(function() {
        if (container) container.innerHTML = '<div class="error">加载失败</div>';
    });
}

// Fetch and display bucket detail
function loadBucketDetail(type, key, paramStr) {
    var containerId = type === 'lianban' ? 'bucketDetailLianban' : 'bucketDetailZt';
    var container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '<div class="loading" style="padding:8px;">加载中...</div>';
    container.classList.add('active');

    fetch('/api/stats_bucket?type=' + type + '&bucket=' + encodeURIComponent(key) + (paramStr || '') + '&top_n=100')
        .then(function(r) { return r.json(); }).then(function(data) {
        var stocks = data.stocks || [];
        if (stocks.length === 0) {
            container.innerHTML = '<div style="color:#888;padding:8px;font-size:0.85em;">无数据</div>';
            return;
        }
        var html = '<table><tr><th>#</th><th>代码</th><th>名称</th>';
        if (type === 'lianban') {
            html += '<th>最大连板</th><th>最近连板日期</th><th>连板日期</th>';
        } else {
            html += '<th>涨停次数</th><th>最近涨停</th>';
        }
        html += '<th>题材概念</th></tr>';
        stocks.forEach(function(s, i) {
            html += '<tr class="clickable" data-code="' + s.code + '" data-name="' + s.name + '">';
            html += '<td style="color:#888;">' + (i+1) + '</td>';
            html += '<td><strong>' + s.code + '</strong></td>';
            html += '<td>' + (s.name || '') + '</td>';
            if (type === 'lianban') {
                html += '<td style="color:#ffc107;">' + s.max_lianban + '板</td>';
                html += '<td style="color:#ff6b6b;">' + (s.lianban_end_date || '') + '</td>';
                html += '<td>' + (s.lianban_dates || []).slice(-3).join(', ') + '</td>';
            } else {
                html += '<td style="color:#ff6b6b;font-weight:bold;">' + s.zt_count + '次</td>';
                html += '<td>' + (s.last_zt || '') + '</td>';
            }
            html += '<td>';
            (s.concepts || []).forEach(function(c) {
                html += '<span class="concept-badge">' + c + '</span> ';
            });
            html += '</td></tr>';
        });
        html += '</table>';
        container.innerHTML = html;
    }).catch(function() {
        container.innerHTML = '<div class="error">加载失败</div>';
    });
}

// Recommend page
function loadRecommend() {
    var container = document.getElementById('recommendContainer');
    container.innerHTML = '<div class="loading">分析候选股票中（约30秒）...</div>';

    fetch('/api/recommend?top_n=30').then(function(r) { return r.json(); }).then(function(data) {
        if (!data || data.error || !data.recommendations || data.recommendations.length === 0) {
            container.innerHTML = '<div class="result"><div class="empty">暂无推荐结果</div></div>';
            return;
        }

        var html = '<div class="result">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;">';
        html += '<h3 style="color:#ff6b6b;margin:0;">🔥 涨停回调买入推荐 Top ' + data.recommendations.length + '</h3>';
        html += '<span style="color:#888;font-size:0.85em;">共分析' + data.total_candidates + '只候选股票</span>';
        html += '</div>';
        html += '<p style="color:#888;font-size:0.85em;margin-bottom:12px;">策略：涨停后缩量回调至均线附近，连板强度高，概念热度活跃</p>';

        data.recommendations.forEach(function(r, i) {
            var cls = i < 5 ? 'top' : i < 15 ? 'good' : 'normal';
            var scCls = r.total_score >= 80 ? 'high' : r.total_score >= 65 ? 'mid' : '';
            var rankCls = i < 3 ? 'style="color:#ffc107;font-weight:bold;"' : 'style="color:#888;"';

            html += '<div class="rec-card ' + cls + '" data-code="' + r.code + '" data-name="' + r.name + '">';
            html += '<div class="rec-header">';
            html += '<span ' + rankCls + '>#' + (i+1) + '</span>';
            html += '<span class="rec-code">' + r.code + '</span>';
            html += '<span class="rec-name">' + r.name + '</span>';
            html += '<span class="rec-score ' + scCls + '">' + r.total_score + '</span>';
            html += '</div>';

            // Tags
            html += '<div class="rec-tags">';
            html += '<span class="rec-tag zt">涨停' + r.zt_count + '次</span>';
            html += '<span class="rec-tag zt">' + r.max_lianban + '连板</span>';
            html += '<span class="rec-tag pullback">回调' + r.pullback_days + '天</span>';
            html += '<span class="rec-tag pullback">深度' + r.pullback_depth_pct.toFixed(1) + '%</span>';
            html += '<span class="rec-tag">量比' + r.volume_ratio.toFixed(2) + '</span>';
            html += '<span class="rec-tag">评分' + r.pullback_score.toFixed(0) + '</span>';
            html += '<span class="rec-tag heat">热度' + r.heat_score.toFixed(0) + '</span>';
            if (r.hot_concepts) {
                r.hot_concepts.forEach(function(c) {
                    html += '<span class="rec-tag">' + c + '</span>';
                });
            }
            html += '</div>';

            // ZT dates
            html += '<div style="font-size:0.8em;color:#666;margin:4px 0;">';
            html += '涨停: ';
            (r.recent_zt_dates || []).slice(-5).forEach(function(d) {
                html += '<span style="color:#ff6b6b;margin-right:4px;">' + d + '</span>';
            });
            html += '</div>';

            // Advice
            html += '<div class="rec-advice">';
            if (r.total_score >= 80) html += '<span class="star">⭐ </span>';
            else if (r.total_score >= 70) html += '<span class="star">✦ </span>';
            html += r.buy_advice;
            html += '</div>';

            html += '</div>';
        });

        html += '</div>';
        container.innerHTML = html;
    }).catch(function(e) {
        container.innerHTML = '<div class="result"><div class="error">推荐加载失败: ' + e.message + '</div></div>';
    });
}

// ========== 创业板/科创板套利 ==========
function loadGemArbitrage(stockCode) {
    var container = document.getElementById('gemArbitrageContainer');
    if (!container) return;
    container.innerHTML = '<div class="loading" style="padding:8px;">查询创业板/科创板套利机会...</div>';

    fetch('/api/gem_arbitrage?stock=' + stockCode + '&max_lag=2')
        .then(function(r) { return r.json(); }).then(function(data) {
        if (data.error) {
            container.innerHTML = '<div style="color:#e94560;padding:8px;font-size:0.85em;">' + data.error + '</div>';
            return;
        }
        if (!data.pairs || data.pairs.length === 0) {
            container.innerHTML = '<div style="color:#888;padding:8px;font-size:0.85em;">未发现创业板/科创板套利机会</div>';
            return;
        }

        // Group by concept
        var grouped = {};
        data.pairs.forEach(function(p) {
            var c = p.concept || '未知';
            if (!grouped[c]) grouped[c] = [];
            // Dedup by gem_stock+date within concept group
            var exists = grouped[c].some(function(x) { return x.gem_stock === p.gem_stock && x.zt_date === p.zt_date; });
            if (!exists) grouped[c].push(p);
        });
        var conceptNames = Object.keys(grouped).sort(function(a, b) { return grouped[b].length - grouped[a].length; });

        var html = '<div style="margin-top:10px;padding:12px;background:#1a1a2e;border-radius:10px;border:1px solid #ff9800;">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
        html += '<strong style="color:#ff9800;">创业板/科创板套利 (' + data.stock_name + ', 共' + data.total_pairs + '次联动)</strong>';
        html += '</div>';

        // Concept filter tabs
        html += '<div class="concept-tabs" style="margin-bottom:10px;" id="arbConceptTabs">';
        html += '<span class="concept-tab active" data-arb-concept="">全部 (' + data.total_pairs + ')</span>';
        conceptNames.forEach(function(c) {
            html += '<span class="concept-tab" data-arb-concept="' + c.replace(/"/g, '') + '">' + c + ' (' + grouped[c].length + ')</span>';
        });
        html += '</div>';

        // Store data for filtering
        window._arbData = data;
        window._arbGrouped = grouped;
        window._arbConceptNames = conceptNames;
        window._arbContainer = container;
        window._arbHtmlTemplate = html;
        container.innerHTML = html + '<div id="arbTablesContainer"></div>';
        window._arbSelectedConcept = null;
        // Event delegation for concept tab clicks
        var arbTabs = document.getElementById('arbConceptTabs');
        if (arbTabs && !arbTabs._hasListener) {
            arbTabs._hasListener = true;
            arbTabs.addEventListener('click', function(e) {
                var tab = e.target.closest('.concept-tab[data-arb-concept]');
                if (tab) {
                    window._arbSelectedConcept = tab.getAttribute('data-arb-concept') || null;
                    renderGemArbitrageContent();
                }
            });
        }
        renderGemArbitrageContent();
    }).catch(function(e) {
        container.innerHTML = '<div style="color:#e94560;padding:8px;font-size:0.85em;">查询失败: ' + e.message + '</div>';
    });
}

function renderGemArbitrageContent() {
    var container = window._arbContainer;
    if (!container) return;
    var grouped = window._arbGrouped || {};
    var selectedConcept = window._arbSelectedConcept;
    var conceptNames = window._arbConceptNames || [];

    // Update tab active states
    var tabs = container.querySelectorAll('.concept-tab[data-arb-concept]');
    tabs.forEach(function(t) {
        var tc = t.getAttribute('data-arb-concept') || '';
        if (tc === (selectedConcept || '')) {
            t.classList.add('active');
        } else {
            t.classList.remove('active');
        }
    });

    var conceptsToShow = selectedConcept ? [selectedConcept] : conceptNames;
    var tablesHtml = '';
    var totalPairs = 0;

    conceptsToShow.forEach(function(concept) {
        var pairs = grouped[concept] || [];
        if (pairs.length === 0) return;

        tablesHtml += '<div style="margin-top:10px;">';
        tablesHtml += '<div class="section-header"><h4 style="color:#ff9800;">' + concept + ' (' + pairs.length + '只)</h4></div>';
        tablesHtml += '<table style="font-size:0.85em;">';
        tablesHtml += '<tr><th>#</th><th>代码</th><th>名称</th><th>板块</th><th>日期</th><th>滞后</th><th>涨幅</th><th>收盘价</th></tr>';

        pairs.forEach(function(p, i) {
            var lagLabel = p.lag === 0 ? '同日' : 'T+' + p.lag;
            var gainCls = p.gain_pct >= 15 ? ' style="color:#ff6b6b;font-weight:bold;"' : (p.gain_pct >= 10 ? ' style="color:#ff9800;font-weight:bold;"' : ' style="color:#81c784;"');
            var boardLabel = p.gem_board === 'gem' ? '创业板' : '科创板';
            var boardCls = p.gem_board === 'gem' ? ' style="color:#f48fb1;"' : ' style="color:#81c784;"';
            tablesHtml += '<tr' + (i % 2 === 0 ? '' : ' style="background:rgba(255,255,255,0.02);"') + '>';
            tablesHtml += '<td style="color:#888;">' + (totalPairs + i + 1) + '</td>';
            tablesHtml += '<td><strong style="color:#00d4ff;">' + p.gem_stock + '</strong></td>';
            tablesHtml += '<td>' + p.gem_name + '</td>';
            tablesHtml += '<td' + boardCls + '>' + boardLabel + '</td>';
            tablesHtml += '<td>' + p.zt_date + '</td>';
            tablesHtml += '<td>' + lagLabel + '</td>';
            tablesHtml += '<td' + gainCls + '>' + p.gain_pct.toFixed(2) + '%</td>';
            tablesHtml += '<td>' + p.close_price.toFixed(2) + '</td>';
            tablesHtml += '</tr>';
        });
        tablesHtml += '</table></div>';
        totalPairs += pairs.length;
    });

    var tablesContainer = document.getElementById('arbTablesContainer');
    if (!tablesContainer) {
        // If container doesn't exist, create it
        var div = document.createElement('div');
        div.id = 'arbTablesContainer';
        container.appendChild(div);
        tablesContainer = div;
    }
    tablesContainer.innerHTML = tablesHtml || '<div style="color:#888;padding:8px;">该概念下无数据</div>';
}

// Enter key
document.getElementById('stockInput').addEventListener('keypress', function(e) {
    if (e.key === 'Enter') { document.getElementById('suggestions').classList.remove('active'); doSearch(); }
});
document.getElementById('conceptInput').addEventListener('keypress', function(e) { if (e.key === 'Enter') doSearch(); });
document.getElementById('conceptQueryInput').addEventListener('keypress', function(e) { if (e.key === 'Enter') doConceptSearch(); });

// ===== N字战法 =====
var _npData = null;
var _npCatKeys = ['tld', '0-2', '2-5', '5-8', '8-10', '10+'];
var _npCatLabels = {'tld': '屠龙刀战法', '0-2': '0~2%', '2-5': '2~5%', '5-8': '5~8%', '8-10': '8~10%', '10+': '10%+'};
var _npGridCols = 2;
var _npObserver = null;
var _ztWindowData = null;  // cached zt_window data

// Sidebar nav items (excluding alert — added separately)
var _npSidebarItems = [
    {key: 'tld', label: '屠龙刀战法'},
    {key: '0-2', label: '0~2%'},
    {key: '2-5', label: '2~5%'},
    {key: '5-8', label: '5~8%'},
    {key: '8-10', label: '8~10%'},
    {key: '10+', label: '10%+'},
    {key: 'alert', label: '额外关注'},
    {key: 'zt', label: '15日涨停'}
];

function loadNPattern() {
    var container = document.getElementById('npatternContainer');
    container.innerHTML = '<div class="loading">分析N字战法候选股票中...</div>';

    fetch('/api/n_pattern').then(function(r) { return r.json(); }).then(function(data) {
        if (!data || data.error || !data.categories) {
            container.innerHTML = '<div class="result"><div class="error">分析失败</div></div>';
            return;
        }

        _npData = data;

        // --- Summary bar ---
        var html = '<div class="result" id="np-nav-top">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;">';
        html += '<h3 style="color:#ff6b6b;margin:0;">N字战法·涨停回调分析</h3>';
        html += '<span style="color:#888;font-size:0.85em;">共' + data.summary.total_stocks + '只股票 | 候选' + data.summary.candidate_count + '只</span>';
        html += '</div>';

        // Strategy description
        html += '<p style="color:#888;font-size:0.85em;margin-bottom:12px;">策略：涨停连板后回调企稳，识别二波主升机会。按回调深度分类，⭐标记为高连板+无大跌异动标的</p>';

        // Alert badges (above wrapper)
        if (data.alerts) {
            var alertBar = [];
            if (data.alerts.zha_ban && data.alerts.zha_ban.length > 0) alertBar.push('炸板异动 ' + data.alerts.zha_ban.length + '只');
            if (data.alerts.gem_alert && data.alerts.gem_alert.length > 0) alertBar.push('创业板/科创板异动 ' + data.alerts.gem_alert.length + '只');
            if (alertBar.length > 0) {
                html += '<div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">';
                alertBar.forEach(function(t) { html += '<span class="badge badge-pool">' + t + '</span>'; });
                html += '</div>';
            }
        }

        // --- Sidebar + Main content wrapper ---
        html += '<div class="np-wrapper">';

        // Sidebar nav
        html += '<nav class="np-sidebar" id="npSidebar">';
        _npSidebarItems.forEach(function(item) {
            var targetId = item.key === 'alert' ? 'np-section-alert' : 'np-section-' + item.key;
            html += '<a class="np-sidebar-item" data-np-section="' + targetId + '" onclick="scrollToNpSection(\\'' + targetId + '\\')">' + item.label + '</a>';
        });
        html += '</nav>';

        // Main content (built by helper so filter can re-render)
        html += '<div class="np-main-content" id="np-main-content">';
        html += renderNpFilterBar();
        html += '<div id="np-cat-results">';
        html += renderNpResults(data);
        html += '</div>';
        html += '</div>'; // .np-main-content

        html += '</div>'; // .np-wrapper

        // Update time
        if (data.update_time) {
            html += '<div class="np-update-time">更新时间: ' + data.update_time + '</div>';
        }

        html += '</div>'; // .result
        container.innerHTML = html;

        // Default collapse all categories
        setTimeout(function() {
            document.querySelectorAll('.np-cat-header').forEach(function(h) {
                if (!h.classList.contains('collapsed')) {
                    h.classList.add('collapsed');
                    var body = h.nextElementSibling;
                    if (body) body.style.display = 'none';
                }
            });
        }, 50);

        // Render all kline canvases
        setTimeout(function() {
            _npCatKeys.forEach(function(ck) {
                var cat = data.categories[ck];
                if (!cat) return;
                ['main_board', 'gem', 'star', 'bj'].forEach(function(bk) {
                    (cat[bk] || []).forEach(function(stock) {
                        renderNpKline('npk_' + stock.code, stock.klines);
                    });
                });
            });
            // Render alert klines
            if (data.alerts) {
                (data.alerts.zha_ban || []).concat(data.alerts.gem_alert || []).forEach(function(s) {
                    if (s.klines) renderNpKline('npk_' + s.code + '_alert', s.klines);
                });
            }
            // Render hot concept buttons
            renderNpHotConceptButtons();
            // Init sidebar IntersectionObserver
            initNpSidebar();

            // Load 15日涨停板 data after N-pattern sections are rendered
            loadNpZtWindow();
        }, 150);

    }).catch(function(e) {
        container.innerHTML = '<div class="result"><div class="error">加载失败: ' + e.message + '</div></div>';
    });
}

// Render the filter bar (separate from results so filter doesn't clear itself)
function renderNpFilterBar() {
    var html = '<div class="np-filter-bar">';
    html += '<span class="fl">概念</span>';
    html += '<input class="np-filter-input" id="npFilterConcept" placeholder="多概念用逗号分隔" oninput="filterNPattern()">';
    html += '<label class="np-filter-cb"><input type="checkbox" id="npFilterNW" onchange="filterNPattern()"> N+W</label>';
    html += '<label class="np-filter-cb"><input type="checkbox" id="npFilterTldSb" onchange="filterNPattern()"> 首版屠龙</label>';
    html += '<label class="np-filter-cb"><input type="checkbox" id="npFilterTld" onchange="filterNPattern()"> 屠龙刀</label>';
    html += '<span class="np-grid-tog">';
    html += '<button' + (_npGridCols === 2 ? ' class="active"' : '') + ' onclick="setNpGridCols(2)" data-cols="2">2列</button>';
    html += '<button' + (_npGridCols === 4 ? ' class="active"' : '') + ' onclick="setNpGridCols(4)" data-cols="4">4列</button>';
    html += '<button' + (_npGridCols === 6 ? ' class="active"' : '') + ' onclick="setNpGridCols(6)" data-cols="6">6列</button>';
    html += '</span>';
    html += '</div>';
    // Hot concept quick-select container
    html += '<div id="npHotConceptBar" style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:12px;"></div>';
    return html;
}

// Render the results area (categories + alerts)
function renderNpResults(data) {
    data = data || _npData;
    if (!data) return '';

    var html = '';

    // Count totals (for display)
    var allCount = 0;
    _npCatKeys.forEach(function(ck) {
        var cat = data.categories[ck];
        if (!cat) return;
        allCount += (cat.main_board || []).length + (cat.gem || []).length + (cat.star || []).length + (cat.bj || []).length;
    });
    html += '<div class="np-filter-count" id="npFilterCount" style="color:#666;font-size:0.82em;margin-bottom:10px;">共 ' + allCount + ' 只</div>';

    // Categories
    _npCatKeys.forEach(function(ck) {
        html += renderNpCategory(data.categories[ck], ck);
    });

    // Alerts section
    html += renderNpAlertSection(data);

    // 15日涨停板 section placeholder (content filled by loadNpZtWindow)
    html += '<div id="np-ztwindow-section"></div>';

    return html;
}

// Render alert section using np-card style (with collapsible header + show-all)
function renderNpAlertSection(data) {
    if (!data.alerts || (data.alerts.zha_ban.length === 0 && data.alerts.gem_alert.length === 0)) return '';

    var totalAlert = data.alerts.zha_ban.length + data.alerts.gem_alert.length;
    var INIT_SHOW = 10;

    var html = '<div class="np-section" id="np-section-alert">';
    html += '<div class="np-cat-header" onclick="toggleNpCategory(this)" data-np-cat="alert">';
    html += '<span class="cat-icon">⚠</span>';
    html += '<span class="cat-name">额外关注</span>';
    html += '<span class="cat-count">' + totalAlert + '只</span>';
    html += '<span class="cat-arrow">▼</span>';
    html += '</div>';
    html += '<div class="np-cat-body" id="np-cat-body-alert">';

    html += _renderAlertBoard(data.alerts.zha_ban, 'zha_ban', '炸板异动', 'main', INIT_SHOW);
    html += _renderAlertBoard(data.alerts.gem_alert, 'gem_alert', '创业板/科创板异动', 'gem', INIT_SHOW);

    html += '<div class="np-back-top" onclick="scrollToNpSection(\\'np-nav-top\\')">↑ 回到顶部</div>';
    html += '</div></div>'; // .np-cat-body, .np-section
    return html;
}

function _renderAlertBoard(stocks, typeKey, boardLabel, boardCls, initShow) {
    if (!stocks || stocks.length === 0) return '';
    var total = stocks.length;
    var needsToggle = total > initShow;
    var boardId = 'alert-board-' + typeKey;

    var html = '<div class="np-board-section" id="' + boardId + '">';
    html += '<div class="np-board-header ' + boardCls + '">' + boardLabel + ' (' + total + '只)</div>';
    // First batch
    html += '<div class="np-card-grid" id="alert-grid-' + typeKey + '">';
    for (var i = 0; i < Math.min(initShow, total); i++) {
        html += renderAlertNpCard(stocks[i], typeKey);
    }
    html += '</div>';
    // Hidden extras
    if (needsToggle) {
        html += '<div class="np-card-grid" id="alert-grid-extra-' + typeKey + '" style="display:none;">';
        for (var i = initShow; i < total; i++) {
            html += renderAlertNpCard(stocks[i], typeKey);
        }
        html += '</div>';
        html += '<div class="np-show-toggle" style="text-align:center;margin:8px 0;">';
        html += '<button class="arb-btn" style="padding:6px 18px;font-size:0.85em;" onclick="toggleAlertBoard(\\'' + typeKey + '\\')" id="alert-btn-' + typeKey + '">显示全部 (' + total + '只)</button>';
        html += '</div>';
    }
    html += '</div>';
    return html;
}

// Toggle show-all for alert board section
function toggleAlertBoard(typeKey) {
    var extraGrid = document.getElementById('alert-grid-extra-' + typeKey);
    var btn = document.getElementById('alert-btn-' + typeKey);
    if (!extraGrid || !btn) return;
    var isHidden = extraGrid.style.display === 'none';
    extraGrid.style.display = isHidden ? '' : 'none';
    // Get total from button label
    var match = btn.textContent.match(/\d+/);
    var total = match ? parseInt(match[0]) : 0;
    btn.textContent = isHidden ? '收起' : '显示全部 (' + total + '只)';

    // Render klines for newly visible cards
    if (isHidden) {
        extraGrid.querySelectorAll('canvas').forEach(function(canvas) {
            var code = canvas.id.replace('npk_', '').replace('_alert', '');
            var sec = document.getElementById(canvas.id.replace('npk_', '').replace('_alert', ''));
            // Look up kline data - scan alerts for matching code
            if (window._npData && window._npData.alerts) {
                var allAlerts = (window._npData.alerts.zha_ban || []).concat(window._npData.alerts.gem_alert || []);
                for (var si = 0; si < allAlerts.length; si++) {
                    if (allAlerts[si].code === code && allAlerts[si].klines) {
                        renderNpKline(canvas.id, allAlerts[si].klines);
                        break;
                    }
                }
            }
        });
        initNpSidebar();
    }
}

// Render a single alert stock as np-card format
function renderAlertNpCard(s, type) {
    var borderCls = type === 'zha_ban' ? ' tld-card' : '';
    var html = '<div class="np-card' + borderCls + '" data-code="' + s.code + '" data-name="' + s.name + '">';
    html += '<div class="np-card-header">';
    html += '<div>';
    html += '<span class="np-card-code" data-code="' + s.code + '" data-name="' + s.name + '">' + s.code + '</span>';
    html += '<span class="np-card-name">' + s.name + '</span>';
    html += '</div>';
    if (type === 'zha_ban') {
        html += '<span class="np-card-badge alert">炸板' + s.zb_count + '次</span></div>';
    } else {
        var boardLabel = s.board === 'gem' ? '创业板' : '科创板';
        var boardColor = s.board === 'gem' ? 'rgba(244,143,177,0.15);color:#f48fb1' : 'rgba(129,199,132,0.15);color:#81c784';
        html += '<span class="np-card-badge lianban" style="background:' + boardColor + '">' + boardLabel + '</span></div>';
    }

    // Concepts
    html += '<div class="np-card-badges">';
    (s.concepts || []).forEach(function(c) { html += '<span class="np-card-badge">' + c + '</span>'; });
    html += '</div>';

    // Metrics
    html += '<div class="np-metrics">';
    if (type === 'zha_ban') {
        html += '<div class="np-metric"><div class="label">涨停日</div><div class="value">' + (s.last_zt_date || '-') + '</div></div>';
        html += '<div class="np-metric"><div class="label">回调</div><div class="value positive">' + (s.current_pullback_pct != null ? s.current_pullback_pct.toFixed(1) + '%' : '-') + '</div></div>';
        html += '<div class="np-metric"><div class="label">封板价</div><div class="value">' + (s.top_high || '-') + '</div></div>';
        html += '<div class="np-metric"><div class="label">基准</div><div class="value">' + (s.base_price != null ? s.base_price.toFixed(2) : '-') + '</div></div>';
    } else {
        html += '<div class="np-metric"><div class="label">涨停日</div><div class="value">' + (s.last_zt_date || '-') + '</div></div>';
        html += '<div class="np-metric"><div class="label">连板</div><div class="value">' + (s.lianban_count || 0) + '板</div></div>';
        html += '<div class="np-metric"><div class="label">回调</div><div class="value positive">' + (s.current_pullback_pct != null ? s.current_pullback_pct.toFixed(1) + '%' : '-') + '</div></div>';
        html += '<div class="np-metric"><div class="label">' + (s.board === 'gem' ? '创业板' : '科创板') + '</div><div class="value" style="color:#888;">异动</div></div>';
    }
    html += '</div>';

    // Pullback bar
    if (s.current_pullback_pct != null) {
        var pbPct = Math.min(s.current_pullback_pct / 15 * 100, 100);
        var fc = 'normal';
        if (s.current_pullback_pct >= 8) fc = 'severe';
        else if (s.current_pullback_pct >= 5) fc = 'deep';
        else if (s.current_pullback_pct >= 2) fc = 'normal';
        html += '<div class="np-pullback-bar"><div class="np-pullback-fill ' + fc + '" style="width:' + pbPct + '%"></div></div>';
    }

    // K-line canvas
    var canvasId = 'npk_' + s.code + '_alert';
    html += '<div class="np-kline-container">';
    html += '<canvas id="' + canvasId + '" height="200"></canvas>';
    html += '</div>';
    html += '<button class="np-kline-toggle" data-kline-id="' + canvasId + '">收起K线</button>';

    html += '</div>';
    return html;
}

function renderNpCategory(cat, catKey) {
    if (!cat) return '';
    var total = (cat.main_board || []).length + (cat.gem || []).length + (cat.star || []).length + (cat.bj || []).length;
    if (total === 0) return '';

    // Icon/color for categories
    var catIcons = {'tld': '🔪', '0-2': '🟢', '2-5': '🟡', '5-8': '🟠', '8-10': '🔴', '10+': '⛔'};
    var icon = catIcons[catKey] || '📊';

    var html = '<div class="np-section" id="np-section-' + catKey + '">';
    html += '<div class="np-cat-header" onclick="toggleNpCategory(this)" data-np-cat="' + catKey + '">';
    html += '<span class="cat-icon">' + icon + '</span>';
    html += '<span class="cat-name">' + cat.name + '</span>';
    html += '<span class="cat-count">' + total + '只</span>';
    html += '<span class="cat-arrow">▼</span>';
    html += '</div>';

    html += '<div class="np-cat-body" id="np-cat-body-' + catKey + '">';

    var boards = [
        {key: 'main_board', label: '主板', cls: 'main'},
        {key: 'gem', label: '创业板', cls: 'gem'},
        {key: 'star', label: '科创板', cls: 'star'},
        {key: 'bj', label: '北交所', cls: 'bj'}
    ];

    boards.forEach(function(board) {
        var stocks = cat[board.key] || [];
        if (stocks.length === 0) return;

        html += '<div class="np-board-section">';
        html += '<div class="np-board-header ' + board.cls + '">' + board.label + ' (' + stocks.length + '只)</div>';
        html += '<div class="np-card-grid">';

        stocks.forEach(function(s, i) {
            var starCls = s.is_lianban2plus ? ' star-card' : '';
            var tldCls = s.is_tld_shouban ? ' tld-shouban-card' : (s.is_tld ? ' tld-card' : '');
            var nwCls = s.is_nw_pattern ? ' nw-card' : '';
            html += '<div class="np-card' + starCls + tldCls + nwCls + '">';

            // Header: code, name, badges
            html += '<div class="np-card-header">';
            html += '<div>';
            html += '<span class="np-card-code" data-code="' + s.code + '" data-name="' + s.name + '">' + s.code + '</span>';
            html += '<span class="np-card-name">' + s.name + '</span>';
            if (s.is_lianban2plus) html += '<span style="margin-left:4px;color:#ffc107;">⭐</span>';
            if (s.is_oscillation) html += '<span style="margin-left:4px;color:#00d4ff;font-size:0.85em;">⟳</span>';
            if (s.has_zha_ban) html += '<span style="margin-left:4px;color:#ff9800;font-size:0.85em;">⚠</span>';
            if (s.is_tld_shouban) html += '<span class="tld-shouban-badge">首版屠龙</span>';
            else if (s.is_tld) html += '<span class="tld-badge">屠龙刀</span>';
            if (s.is_nw_pattern) html += '<span class="nw-badge">N+W双底</span>';
            html += '</div>';
            html += '<div><span class="np-card-badge lianban">' + s.lianban_count + '连板</span></div>';
            html += '</div>';

            // Concepts badges (全部展示)
            html += '<div class="np-card-badges">';
            var concepts = s.concepts || [];
            concepts.forEach(function(c) {
                html += '<span class="np-card-badge">' + c + '</span>';
            });
            html += '</div>';

            // Metrics row
            html += '<div class="np-metrics">';
            html += '<div class="np-metric"><div class="label">基准</div><div class="value">' + s.base_price.toFixed(2) + '</div></div>';
            html += '<div class="np-metric"><div class="label">连板顶</div><div class="value">' + s.top_price.toFixed(2) + '</div></div>';
            html += '<div class="np-metric"><div class="label">最大回调</div><div class="value positive">' + s.max_pullback_pct.toFixed(1) + '%</div></div>';
            html += '<div class="np-metric"><div class="label">当前回调</div><div class="value positive">' + s.current_pullback_pct.toFixed(1) + '%</div></div>';
            html += '</div>';

            // Pullback progress bar
            var pullbarPct = Math.min(s.current_pullback_pct / 15 * 100, 100);
            var fillCls = 'shallow';
            if (s.current_pullback_pct >= 8) fillCls = 'severe';
            else if (s.current_pullback_pct >= 5) fillCls = 'deep';
            else if (s.current_pullback_pct >= 2) fillCls = 'normal';
            html += '<div class="np-pullback-bar"><div class="np-pullback-fill ' + fillCls + '" style="width:' + pullbarPct + '%"></div></div>';

            // NW double-bottom metrics
            if (s.is_nw_pattern) {
                html += '<div class="np-nw-metrics">';
                html += '<div class="np-nw-metric" style="text-align:center;"><div class="label">M点价格</div><div class="value" style="color:#ff5722;">' + (s.pullback_low ? s.pullback_low.toFixed(2) : '-') + '</div></div>';
                html += '<div class="np-nw-metric" style="text-align:center;"><div class="label">M2价格</div><div class="value" style="color:#ff9800;">' + (s.nw_m2_price ? s.nw_m2_price.toFixed(2) : '-') + '</div></div>';
                html += '<div class="np-nw-metric" style="text-align:center;"><div class="label">反弹%</div><div class="value" style="color:#81c784;">' + (s.nw_recovery_pct ? s.nw_recovery_pct.toFixed(1) + '%' : '-') + '</div></div>';
                html += '<div class="np-nw-metric" style="text-align:center;"><div class="label">M-M2收敛</div><div class="value" style="color:#00d4ff;">确认</div></div>';
                html += '</div>';
            }

            // K-line canvas
            var canvasIdNp = 'npk_' + s.code;
            html += '<div class="np-kline-container">';
            html += '<canvas id="' + canvasIdNp + '" height="200"></canvas>';
            html += '</div>';
            html += '<button class="np-kline-toggle" data-kline-id="' + canvasIdNp + '">收起K线</button>';

            html += '</div>'; // .np-card
        });

        html += '</div></div>'; // .np-card-grid, .np-board-section
    });

    // Back to top
    html += '<div class="np-back-top" onclick="scrollToNpSection(\\'np-nav-top\\')">↑ 回到顶部</div>';

    html += '</div></div>'; // .np-cat-body, .np-section
    return html;
}

function toggleNpCategory(el) {
    el.classList.toggle('collapsed');
    var body = el.nextElementSibling;
    if (body) {
        body.style.display = body.style.display === 'none' ? '' : 'none';
    }
}

function toggleNpKline(canvasId) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    var container = canvas.parentElement;
    var btn = container.nextElementSibling;
    if (canvas.style.display === 'none') {
        canvas.style.display = '';
        btn.textContent = '收起K线';
    } else {
        canvas.style.display = 'none';
        btn.textContent = '展开K线';
    }
}

// Scroll to N-section
function scrollToNpSection(sectionId) {
    var el = document.getElementById(sectionId);
    if (el) el.scrollIntoView({behavior: 'smooth', block: 'start'});
}

// Filter N-pattern stocks
function filterNPattern() {
    var conceptVal = (document.getElementById('npFilterConcept').value || '').trim();
    var filterNW = document.getElementById('npFilterNW').checked;
    var filterTldSb = document.getElementById('npFilterTldSb').checked;
    var filterTld = document.getElementById('npFilterTld').checked;

    var selectedConcepts = conceptVal ? conceptVal.split(',').map(function(s) { return s.trim(); }).filter(function(s) { return s; }) : [];

    // Check if any filter is active
    var hasFilter = selectedConcepts.length > 0 || filterNW || filterTldSb || filterTld;

    // Deep-clone data for filtered rendering
    var data = _npData;
    if (!data) return;

    // Create a filtered copy of categories
    var filteredData = {categories: {}, alerts: data.alerts, summary: data.summary, update_time: data.update_time};

    var filteredTotal = 0;
    _npCatKeys.forEach(function(ck) {
        var origCat = data.categories[ck];
        if (!origCat || (!origCat.name)) return;

        var newCat = {name: origCat.name};
        var boards = ['main_board', 'gem', 'star', 'bj'];
        boards.forEach(function(bk) {
            var origStocks = origCat[bk] || [];
            var filtered = origStocks;
            if (hasFilter) {
                filtered = origStocks.filter(function(s) {
                    // Concept filter
                    if (selectedConcepts.length > 0) {
                        var matchesConcept = false;
                        (s.concepts || []).forEach(function(c) {
                            selectedConcepts.forEach(function(sc) {
                                if (c.indexOf(sc) !== -1) matchesConcept = true;
                            });
                        });
                        if (!matchesConcept) return false;
                    }
                    // NW filter
                    if (filterNW && !s.is_nw_pattern) return false;
                    // TLD shouban filter
                    if (filterTldSb && !s.is_tld_shouban) return false;
                    // TLD filter (includes shouban too)
                    if (filterTld && !s.is_tld && !s.is_tld_shouban) return false;
                    return true;
                });
            }
            newCat[bk] = filtered;
            filteredTotal += filtered.length;
        });
        filteredData.categories[ck] = newCat;
    });

    // Update count
    var countEl = document.getElementById('npFilterCount');
    if (countEl) countEl.textContent = (hasFilter ? '过滤后 ' : '共 ') + filteredTotal + ' 只';

    // Re-render results area (filter bar stays intact)
    var resultsEl = document.getElementById('np-cat-results');
    if (resultsEl) {
        resultsEl.innerHTML = renderNpResults(filteredData);
        // Re-render K-lines
        setTimeout(function() {
            _npCatKeys.forEach(function(ck) {
                var cat = filteredData.categories[ck];
                if (!cat) return;
                ['main_board', 'gem', 'star', 'bj'].forEach(function(bk) {
                    (cat[bk] || []).forEach(function(stock) {
                        renderNpKline('npk_' + stock.code, stock.klines);
                    });
                });
            });
            // Render alert klines
            var alertData = filteredData.alerts;
            if (alertData) {
                (alertData.zha_ban || []).concat(alertData.gem_alert || []).forEach(function(s) {
                    if (s.klines) renderNpKline('npk_' + s.code + '_alert', s.klines);
                });
            }
            // Collapse categories
            document.querySelectorAll('.np-cat-header:not(.collapsed)').forEach(function(h) {
                h.classList.add('collapsed');
                var body = h.nextElementSibling;
                if (body) body.style.display = 'none';
            });
        }, 100);
    }
}

// Set grid columns (card width stays fixed, centered layout)
function setNpGridCols(n) {
    _npGridCols = n;
    // Update button active state only
    document.querySelectorAll('.np-grid-tog button').forEach(function(b) {
        b.classList.toggle('active', parseInt(b.getAttribute('data-cols')) === n);
    });
    // Card size stays fixed at 480px; centering handles layout naturally
}

// Helper to find kline data for a canvas ID
function _getKlineDataForCanvas(canvasId) {
    if (!_npData) return null;
    var prefix = 'npk_';
    if (canvasId.indexOf(prefix) !== 0) return null;
    var code = canvasId.slice(prefix.length);
    var found = null;
    _npCatKeys.forEach(function(ck) {
        if (found) return;
        var cat = _npData.categories[ck];
        if (!cat) return;
        ['main_board', 'gem', 'star', 'bj'].forEach(function(bk) {
            if (found) return;
            (cat[bk] || []).forEach(function(s) {
                if (s.code === code) found = s.klines || null;
            });
        });
    });
    return found;
}

// Init sidebar IntersectionObserver
function initNpSidebar() {
    // Disconnect previous observer
    if (_npObserver) _npObserver.disconnect();

    var sections = [];
    _npSidebarItems.forEach(function(item) {
        var id = item.key === 'alert' ? 'np-section-alert' : 'np-section-' + item.key;
        var el = document.getElementById(id);
        if (el) sections.push(el);
    });

    if (sections.length === 0) return;

    _npObserver = new IntersectionObserver(function(entries) {
        var visibleItems = [];
        entries.forEach(function(entry) {
            if (entry.isIntersecting) {
                visibleItems.push({el: entry.target, ratio: entry.intersectionRatio});
            }
        });
        if (visibleItems.length === 0) return;
        // Pick the one with highest intersection ratio
        visibleItems.sort(function(a, b) { return b.ratio - a.ratio; });
        var bestId = visibleItems[0].el.id;
        // Update sidebar
        document.querySelectorAll('.np-sidebar-item').forEach(function(item) {
            var target = item.getAttribute('data-np-section');
            item.classList.toggle('active', target === bestId);
        });
    }, {rootMargin: '-10px 0px -15% 0px', threshold: [0, 0.1]});

    sections.forEach(function(el) { _npObserver.observe(el); });
}

// ===== 15日涨停板 Section =====
function renderNpZtWindow(ztData) {
    if (!ztData) return '';
    var sections = [
        {key: 'hot', label: '3日狙击', icon: '🔴'},
        {key: 'warm', label: '5日蓄势', icon: '🟠'},
        {key: 'cool', label: '10日潜伏', icon: '🟡'},
        {key: 'cold', label: '15日余波', icon: '🟢'}
    ];
    var total = 0;
    var secCounts = {};
    sections.forEach(function(s) {
        var count = (ztData[s.key] || []).length;
        total += count;
        secCounts[s.key] = count;
    });
    if (total === 0) return '<div class="empty">暂无数据</div>';

    var INIT_SHOW = 50;

    var html = '<div class="np-section" id="np-section-zt">';
    html += '<div class="np-cat-header" onclick="toggleNpCategory(this)" data-np-cat="zt">';
    html += '<span class="cat-icon">📅</span>';
    html += '<span class="cat-name">15日涨停板</span>';
    html += '<span class="cat-count">' + total + '只</span>';
    html += '<span class="cat-arrow">▼</span>';
    html += '</div>';
    html += '<div class="np-cat-body" id="np-cat-body-zt">';

    sections.forEach(function(sec) {
        var stocks = ztData[sec.key] || [];
        if (stocks.length === 0) return;
        var needsToggle = stocks.length > INIT_SHOW;
        var showCount = needsToggle ? INIT_SHOW : stocks.length;
        html += '<div class="np-board-section" id="zt-section-' + sec.key + '">';
        html += '<div class="np-board-header main">' + sec.icon + ' ' + sec.label + ' (' + stocks.length + '只)</div>';
        html += '<div class="np-card-grid" id="zt-grid-' + sec.key + '">';
        stocks.forEach(function(s, idx) {
            if (needsToggle && idx >= INIT_SHOW) return; // rendered separately
            html += renderNpZtCard(s);
        });
        html += '</div>';
        if (needsToggle) {
            // Hidden extra cards
            html += '<div class="np-card-grid" id="zt-grid-extra-' + sec.key + '" style="display:none;">';
            for (var i = INIT_SHOW; i < stocks.length; i++) {
                html += renderNpZtCard(stocks[i]);
            }
            html += '</div>';
            html += '<div class="np-show-toggle" style="text-align:center;margin:8px 0;">';
            html += '<button class="arb-btn" style="padding:6px 18px;font-size:0.85em;" onclick="toggleZtBoard(\\'' + sec.key + '\\')" id="zt-btn-' + sec.key + '">显示全部 (' + stocks.length + '只)</button>';
            html += '</div>';
        }
        html += '</div>'; // .np-board-section
    });

    html += '<div class="np-back-top" onclick="scrollToNpSection(\\'np-nav-top\\')">↑ 回到顶部</div>';
    html += '</div></div>';
    return html;
}

function renderNpZtCard(s) {
    var html = '<div class="np-card">';
    html += '<div class="np-card-header">';
    html += '<div>';
    html += '<span class="np-card-code" data-code="' + s.code + '" data-name="' + s.name + '">' + s.code + '</span>';
    html += '<span class="np-card-name">' + s.name + '</span>';
    html += '</div>';
    html += '<div><span class="np-card-badge lianban">' + s.zt_count + '次涨停</span></div>';
    html += '</div>';

    // Concepts badges
    html += '<div class="np-card-badges">';
    (s.concepts || []).forEach(function(c) {
        html += '<span class="np-card-badge">' + c + '</span>';
    });
    html += '</div>';

    // Metrics row
    html += '<div class="np-metrics">';
    html += '<div class="np-metric"><div class="label">最近涨停</div><div class="value">' + s.last_zt_date + '</div></div>';
    html += '<div class="np-metric"><div class="label">距今日</div><div class="value">' + s.days_ago + '天</div></div>';
    html += '<div class="np-metric"><div class="label">15日涨停</div><div class="value">' + s.zt_count + '次</div></div>';
    html += '</div>';

    // K-line canvas
    var canvasId = 'ztk_' + s.code;
    html += '<div class="np-kline-container">';
    html += '<canvas id="' + canvasId + '" height="200"></canvas>';
    html += '</div>';
    html += '<button class="np-kline-toggle" data-kline-id="' + canvasId + '">收起K线</button>';

    html += '</div>';
    return html;
}

// Toggle show-all for zt board section
function toggleZtBoard(secKey) {
    var extraGrid = document.getElementById('zt-grid-extra-' + secKey);
    var btn = document.getElementById('zt-btn-' + secKey);
    if (!extraGrid || !btn) return;
    var isHidden = extraGrid.style.display === 'none';
    extraGrid.style.display = isHidden ? '' : 'none';
    var total = parseInt(btn.textContent.match(/\d+/)) || 0;
    btn.textContent = isHidden ? '收起' : '显示全部 (' + total + '只)';

    // If expanding and klines not rendered yet, render them
    if (isHidden) {
        var extraCards = extraGrid.querySelectorAll('.np-card');
        extraCards.forEach(function(card) {
            var canvas = card.querySelector('canvas');
            if (!canvas) return;
            var code = null;
            var codeEl = card.querySelector('.np-card-code');
            if (codeEl) code = codeEl.getAttribute('data-code');
            if (code && window._ztWindowData) {
                // Find klines for this stock
                var ztData = window._ztWindowData;
                var secKeys = ['hot', 'warm', 'cool', 'cold'];
                for (var si = 0; si < secKeys.length; si++) {
                    var stocks = ztData[secKeys[si]] || [];
                    for (var sj = 0; sj < stocks.length; sj++) {
                        if (stocks[sj].code === code && stocks[sj].klines) {
                            renderNpKline(canvas.id, stocks[sj].klines);
                            si = secKeys.length;
                            break;
                        }
                    }
                }
            }
        });
        initNpSidebar();
    }
}

function renderNpKline(canvasId, klines) {
    var canvas = document.getElementById(canvasId);
    if (!canvas || !klines || klines.length < 2) return;

    var ctx = canvas.getContext('2d');
    var W = canvas.width = canvas.clientWidth || 480;
    var H = canvas.height = 200;
    var pad = { top: 12, bottom: 28, left: 10, right: 10 };
    var plotW = W - pad.left - pad.right;
    var n = klines.length;

    // Find price range
    var minP = Infinity, maxP = -Infinity;
    klines.forEach(function(k) {
        if (k.low < minP) minP = k.low;
        if (k.high > maxP) maxP = k.high;
    });
    var padP = (maxP - minP) * 0.1 || minP * 0.02;
    minP -= padP;
    maxP += padP;
    var pRange = maxP - minP || 1;

    function px(idx) { return pad.left + (idx / (n - 1)) * plotW; }
    function py(price) { return pad.top + (1 - (price - minP) / pRange) * (H - pad.top - pad.bottom); }
    function clamp(v, mn, mx) { return Math.max(mn, Math.min(mx, v)); }

    // Clear
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(0, 0, W, H);

    var barWidth = Math.max(1, plotW / n * 0.6);
    var halfBar = barWidth / 2;

    // Grid lines
    ctx.strokeStyle = '#2a2a3e';
    ctx.lineWidth = 0.5;
    for (var i = 0; i <= 4; i++) {
        var y = pad.top + (H - pad.top - pad.bottom) * i / 4;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(W - pad.right, y);
        ctx.stroke();
    }

    // Draw MA5 and MA10
    function drawMA(key, color) {
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        var started = false;
        klines.forEach(function(k, idx) {
            var val = k[key];
            if (val === undefined || val === null || val === 0) return;
            var x = px(idx);
            var y = py(val);
            if (!started) { ctx.moveTo(x, y); started = true; }
            else { ctx.lineTo(x, y); }
        });
        ctx.stroke();
    }
    drawMA('ma5', '#4fc3f7');
    drawMA('ma10', '#ff9800');

    // Draw candlesticks
    klines.forEach(function(k, idx) {
        var x = px(idx);
        var isRed = k.close >= k.open;
        ctx.fillStyle = isRed ? '#e94560' : '#00ff88';
        ctx.strokeStyle = isRed ? '#e94560' : '#00ff88';
        ctx.lineWidth = 1;

        // High-low line
        var yHigh = py(k.high);
        var yLow = py(k.low);
        ctx.beginPath();
        ctx.moveTo(x, yHigh);
        ctx.lineTo(x, yLow);
        ctx.stroke();

        // Body
        var yOpen = py(k.open);
        var yClose = py(k.close);
        var topY = Math.min(yOpen, yClose);
        var botY = Math.max(yOpen, yClose);
        var bodyH = Math.max(botY - topY, 1);
        ctx.fillRect(x - halfBar, topY, barWidth, bodyH);

        // Purple marker for ZT days
        if (k.is_zt) {
            ctx.fillStyle = 'rgba(156, 39, 176, 0.5)';
            ctx.fillRect(x - halfBar, py(k.high) - 4, barWidth, 4);
            ctx.fillStyle = '#9c27b0';
            ctx.beginPath();
            ctx.arc(x, py(k.high) - 6, 3, 0, Math.PI * 2);
            ctx.fill();
        }
    });

    // X-axis labels
    ctx.fillStyle = '#888';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'center';
    var labelStep = Math.max(1, Math.floor(n / 6));
    for (var i = 0; i < n; i += labelStep) {
        var dateStr = klines[i].date || '';
        var shortDate = dateStr.slice(4);
        ctx.fillText(shortDate, px(i), H - 6);
    }
}

// ===== Hot Concept Quick-Select for N-pattern =====
function renderNpHotConceptButtons() {
    if (!_npData) return;
    var conceptCount = {};
    var catKeys = _npCatKeys;
    catKeys.forEach(function(ck) {
        var cat = _npData.categories[ck];
        if (!cat) return;
        ['main_board', 'gem', 'star', 'bj'].forEach(function(bk) {
            (cat[bk] || []).forEach(function(s) {
                (s.concepts || []).forEach(function(c) {
                    conceptCount[c] = (conceptCount[c] || 0) + 1;
                });
            });
        });
    });
    var sorted = Object.keys(conceptCount).sort(function(a, b) {
        return conceptCount[b] - conceptCount[a];
    }).slice(0, 30);
    var el = document.getElementById('npHotConceptBar');
    if (!el) return;
    el.innerHTML = '<span style="color:#888;font-size:0.8em;margin-right:4px;line-height:28px;">热门:</span>';
    var curVal = (document.getElementById('npFilterConcept').value || '').trim();
    var selectedSet = {};
    if (curVal) {
        curVal.split(',').forEach(function(v) { selectedSet[v.trim()] = true; });
    }
    sorted.forEach(function(c) {
        var isSelected = selectedSet[c] || false;
        var btn = document.createElement('span');
        btn.style.cssText = 'padding:3px 10px;border-radius:12px;font-size:0.78em;cursor:pointer;transition:all 0.2s;' +
            (isSelected ? 'background:#00d4ff;color:#0a0a1a;' : 'background:#0f3460;color:#aaa;');
        btn.textContent = c;
        btn.onclick = function() {
            var input = document.getElementById('npFilterConcept');
            if (!input) return;
            var val = (input.value || '').trim();
            var parts = val ? val.split(',').map(function(v) { return v.trim(); }).filter(function(v) { return v; }) : [];
            var idx = parts.indexOf(c);
            if (idx >= 0) {
                parts.splice(idx, 1);
            } else {
                parts.push(c);
            }
            input.value = parts.join(',');
            filterNPattern();
        };
        el.appendChild(btn);
    });
}

// ===== Load 15日涨停板 Data =====
function loadNpZtWindow() {
    fetch('/api/zt_window?top_n=9999').then(function(r) { return r.json(); }).then(function(ztData) {
        if (!ztData || ztData.error) return;
        _ztWindowData = ztData;
        var ztSection = document.getElementById('np-ztwindow-section');
        if (!ztSection) return;
        ztSection.innerHTML = renderNpZtWindow(ztData);

        // Render klines for visible cards (first 50 per section)
        setTimeout(function() {
            var secKeys = ['hot', 'warm', 'cool', 'cold'];
            secKeys.forEach(function(key) {
                var grid = document.getElementById('zt-grid-' + key);
                if (!grid) return;
                grid.querySelectorAll('canvas').forEach(function(canvas) {
                    var code = canvas.id.replace('ztk_', '');
                    var stocks = ztData[key] || [];
                    for (var i = 0; i < stocks.length; i++) {
                        if (stocks[i].code === code && stocks[i].klines) {
                            renderNpKline(canvas.id, stocks[i].klines);
                            break;
                        }
                    }
                });
            });
        }, 100);

        // Collapse by default
        setTimeout(function() {
            var header = ztSection.querySelector('.np-cat-header');
            if (header && !header.classList.contains('collapsed')) {
                header.classList.add('collapsed');
                var body = header.nextElementSibling;
                if (body) body.style.display = 'none';
            }
        }, 50);
        // Re-init sidebar observer to include new section
        initNpSidebar();
    }).catch(function(e) {
        console.error('15日涨停板加载失败:', e);
    });
}

// ===== K-line Modal =====
// ===== Stock Card Popup (replaces old K-line modal) =====
function showStockCard(code, name) {
    var modal = document.getElementById('klineModal');
    var titleEl = document.getElementById('klineModalTitle');
    var badgesEl = document.getElementById('klineModalBadges');
    var metricsEl = document.getElementById('klineModalMetrics');
    var canvasContainer = document.getElementById('klineModalCanvas');

    // Show loading
    titleEl.textContent = code + ' ' + name + ' - 加载中...';
    badgesEl.innerHTML = '';
    metricsEl.innerHTML = '<div style="color:#888;padding:8px;">正在获取数据...</div>';
    canvasContainer.innerHTML = '';
    modal.classList.add('active');

    // Fetch kline + stock info in parallel
    Promise.all([
        fetch('/api/kline?stock=' + code + '&days=120').then(function(r) { return r.json(); }),
        fetch('/api/search?q=' + code).then(function(r) { return r.json(); })
    ]).then(function(results) {
        var klineData = results[0];
        var searchData = results[1];
        var klines = (klineData && klineData.klines) || [];
        var stockName = (klineData && klineData.stock_name) || name;

        // Find stock info from search results
        var stockInfo = null;
        if (searchData && Array.isArray(searchData)) {
            for (var si = 0; si < searchData.length; si++) {
                if (searchData[si].code === code) {
                    stockInfo = searchData[si];
                    break;
                }
            }
        }

        titleEl.textContent = code + ' ' + stockName;

        // Concept badges
        badgesEl.innerHTML = '';
        var concepts = (stockInfo && stockInfo.concepts) || [];
        if (concepts.length > 0) {
            concepts.forEach(function(c) {
                var span = document.createElement('span');
                span.className = 'np-card-badge';
                span.textContent = c;
                badgesEl.appendChild(span);
            });
        }

        // Metrics: show what we have from search + kline data
        metricsEl.innerHTML = '';
        var ztCount = (stockInfo && stockInfo.zt_count) || 0;
        var ztDates = (klineData && klineData.zt_dates) || [];
        var lastZt = (stockInfo && stockInfo.last_zt_date) || (ztDates.length > 0 ? ztDates[ztDates.length - 1] : '-');
        var ztDateStr = ztDates.slice(-3).join(' ') || lastZt;

        var metricItems = [
            {label: '涨停次数', value: ztCount + '次'},
            {label: '最近涨停', value: ztDateStr},
            {label: 'K线天数', value: klines.length + '天'},
            {label: '概念数', value: (stockInfo && stockInfo.concept_count || concepts.length) + '个'},
        ];
        metricItems.forEach(function(item) {
            var div = document.createElement('div');
            div.className = 'np-metric';
            div.innerHTML = '<div class="label">' + item.label + '</div><div class="value">' + item.value + '</div>';
            metricsEl.appendChild(div);
        });

        // K-line canvas
        canvasContainer.innerHTML = '<canvas id="klineModalChart" height="280" style="width:100%;"></canvas>';
        if (klines.length >= 2) {
            setTimeout(function() {
                renderNpKline('klineModalChart', klines);
            }, 50);
        } else {
            canvasContainer.innerHTML = '<div style="color:#888;padding:12px;text-align:center;">K线数据不足（仅' + klines.length + '条）</div>';
        }

        // Action buttons — remove old button container first, then add new one
        var oldBtnDiv = document.getElementById('stockCardBtnDiv');
        if (oldBtnDiv) oldBtnDiv.parentNode.removeChild(oldBtnDiv);
        var btnDiv = document.createElement('div');
        btnDiv.id = 'stockCardBtnDiv';
        btnDiv.style.cssText = 'margin-top: 12px; display: flex; gap: 10px; justify-content: center;';
        var navBtn = document.createElement('button');
        navBtn.textContent = '📊 查询联动';
        navBtn.className = 'arb-btn';
        navBtn.style.cssText = 'padding:8px 20px;font-size:0.9em;';
        navBtn.onclick = function() {
            closeKlineModal();
            document.getElementById('stockInput').value = code + ' ' + stockName;
            doSearch();
        };
        btnDiv.appendChild(navBtn);
        metricsEl.parentNode.appendChild(btnDiv);

    }).catch(function(err) {
        titleEl.textContent = code + ' ' + name;
        badgesEl.innerHTML = '';
        metricsEl.innerHTML = '<div style="color:#e94560;padding:12px;">数据加载失败: ' + err.message + '</div>';
        canvasContainer.innerHTML = '';
    });
}

function closeKlineModal() {
    document.getElementById('klineModal').classList.remove('active');
}

// ===== Concept Top20 auto-load =====
var _loadedTopConcepts = false;
function loadTopConcepts() {
    var container = document.getElementById('conceptResult');
    if (!_loadedTopConcepts) {
        container.innerHTML = '<div class="loading">加载热门概念...</div>';
    }
    fetch('/api/stats?top_n=20').then(function(r) { return r.json(); }).then(function(data) {
        if (!data || !data.top_concepts) {
            container.innerHTML = '<div class="empty">输入概念名称进行分析</div>';
            return;
        }
        _loadedTopConcepts = true;
        var topConcepts = data.top_concepts || [];
        var html = '<div class="result" id="topConceptsContainer">';
        html += '<h3 style="color:#00d4ff;margin-bottom:12px;">热门概念 Top 20</h3>';
        html += '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px;">';
        topConcepts.forEach(function(c) {
            var ztCnt = c.zt_stock_count || 0;
            var stkCnt = c.total_stocks || 0;
            html += '<span class="badge badge-pool top-concept-btn" data-concept="' + c.concept.replace(/"/g, '') + '" style="cursor:pointer;font-size:0.9em;padding:6px 14px;">' + c.concept + ' <span style="color:#ff6b6b;">' + ztCnt + '只涨停</span> <span style="color:#888;font-size:0.8em;">/ ' + stkCnt + '股</span></span>';
        });
        html += '</div>';
        html += '<p style="color:#666;font-size:0.85em;">点击概念查看详情，或在搜索框中输入概念名称</p>';
        html += '</div>';
        container.innerHTML = html;
    }).catch(function(e) {
        container.innerHTML = '<div class="empty">输入概念名称进行分析</div>';
    });
}

// Global click delegation for top concept badges
if (!window._topConceptListener) {
    window._topConceptListener = true;
    document.addEventListener('click', function(e) {
        var btn = e.target.closest('.top-concept-btn');
        if (btn) {
            var concept = btn.getAttribute('data-concept');
            if (concept) {
                document.getElementById('conceptQueryInput').value = concept;
                doConceptSearch();
            }
        }
    });
}
loadNPattern();
</script>
</body>
</html>
'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # CORS headers
        cors_headers = {
            'Access-Control-Allow-Origin': '*',
        }

        if path == '/' or path == '/index.html':
            self._respond(200, HTML_PAGE.encode('utf-8'), 'text/html; charset=utf-8', cors_headers)

        elif path == '/api/concepts':
            result = finder.get_all_concept_names()
            self._respond_json(result, cors_headers)

        elif path == '/api/search':
            q = query.get('q', [''])[0]
            if q == '':
                start_date = query.get('start_date', [None])[0]
                end_date = query.get('end_date', [None])[0]
                top_n = int(query.get('top_n', ['200'])[0])
                results = finder.get_top_stocks_by_zt(top_n, start_date, end_date)
            else:
                results = finder.search_stock(q)
            self._respond_json(results, cors_headers)

        elif path == '/api/linkage':
            stock = query.get('stock', [''])[0]
            concept = query.get('concept', [None])[0]
            min_prob = float(query.get('min_prob', ['0.12'])[0])

            if not stock:
                self._respond_json({'error': '请输入股票代码'}, cors_headers)
            else:
                stock_code = stock.strip().zfill(6)
                try:
                    result = finder.find_stock_linkages(stock_code, concept, min_prob=min_prob)
                    self._respond_json(result, cors_headers)
                except Exception as e:
                    self._respond_json({'error': str(e)}, cors_headers)

        elif path == '/api/kline':
            stock = query.get('stock', [''])[0]
            days = int(query.get('days', ['60'])[0])
            if not stock:
                self._respond_json({'error': '请输入股票代码'}, cors_headers)
            else:
                result = finder.get_stock_kline_summary(stock.strip().zfill(6), days=days)
                self._respond_json(result, cors_headers)

        elif path == '/api/concept_zt_stats':
            concept = query.get('concept', [''])[0]
            if not concept:
                self._respond_json({'error': '请输入概念名称'}, cors_headers)
            else:
                result = finder.get_concept_zt_stats(concept)
                self._respond_json(result, cors_headers)

        elif path == '/api/concept_linkage':
            concept = query.get('concept', [''])[0]
            top_n = int(query.get('top_n', ['15'])[0])
            if not concept:
                self._respond_json({'error': '请输入概念名称'}, cors_headers)
            else:
                pairs = finder.analyze_concept_linkages(concept, top_n=top_n)
                self._respond_json({'concept': concept, 'pairs': pairs}, cors_headers)

        elif path == '/api/stats':
            try:
                start_date = query.get('start_date', [None])[0]
                end_date = query.get('end_date', [None])[0]
                top_n = int(query.get('top_n', ['50'])[0])
                summary = finder.get_stats_summary(start_date, end_date)
                top_stocks = finder.get_top_stocks_by_zt(top_n, start_date, end_date)
                top_concepts = finder.get_top_concepts_by_zt(top_n, start_date, end_date)
                daily_activity = finder.get_daily_zt_activity(60, start_date, end_date)
                self._respond_json({
                    'summary': summary,
                    'top_stocks': top_stocks,
                    'top_concepts': top_concepts,
                    'daily_activity': daily_activity
                }, cors_headers)
            except Exception as e:
                import traceback
                self._respond_json({'error': str(e), 'traceback': traceback.format_exc()}, cors_headers)

        elif path == '/api/stats_bucket':
            try:
                bucket_type = query.get('type', [''])[0]
                bucket = query.get('bucket', [''])[0]
                start_date = query.get('start_date', [None])[0]
                end_date = query.get('end_date', [None])[0]
                top_n = int(query.get('top_n', ['100'])[0])
                if bucket_type == 'zt':
                    result = finder.get_stocks_in_zt_bucket(bucket, start_date, end_date, top_n)
                elif bucket_type == 'lianban':
                    result = finder.get_stocks_in_lianban_bucket(bucket, start_date, end_date, top_n)
                else:
                    result = []
                self._respond_json({'type': bucket_type, 'bucket': bucket, 'stocks': result}, cors_headers)
            except Exception as e:
                self._respond_json({'error': str(e)}, cors_headers)

        elif path == '/api/hot_stocks':
            try:
                start_date = query.get('start_date', [None])[0]
                end_date = query.get('end_date', [None])[0]
                top_n = int(query.get('top_n', ['200'])[0])
                results = finder.get_hot_stocks_weighted(top_n, start_date, end_date)
                self._respond_json(results, cors_headers)
            except Exception as e:
                self._respond_json({'error': str(e)}, cors_headers)

        elif path == '/api/recommend':
            try:
                top_n = int(query.get('top_n', ['30'])[0])
                recs = finder.recommend_pullback_stocks(lookback_days=15, top_n=top_n)
                self._respond_json({
                    'total_candidates': len(recs),
                    'recommendations': recs
                }, cors_headers)
            except Exception as e:
                import traceback
                self._respond_json({'error': str(e), 'traceback': traceback.format_exc()}, cors_headers)

        elif path == '/api/zt_window':
            try:
                lookback = int(query.get('lookback_days', ['15'])[0])
                top_n = int(query.get('top_n', ['50'])[0])
                result = finder.get_zt_window_stocks(lookback_days=lookback, top_per_window=top_n)
                self._respond_json(result, cors_headers)
            except Exception as e:
                import traceback
                self._respond_json({'error': str(e), 'traceback': traceback.format_exc()}, cors_headers)

        elif path == '/api/n_pattern':
            try:
                lookback = int(query.get('lookback_days', ['20'])[0])
                result = finder.analyze_n_pattern(lookback_days=lookback)
                self._respond_json(result, cors_headers)
            except Exception as e:
                import traceback
                self._respond_json({'error': str(e), 'traceback': traceback.format_exc()}, cors_headers)

        elif path == '/api/gem_arbitrage':
            try:
                stock = query.get('stock', [''])[0]
                max_lag = int(query.get('max_lag', ['2'])[0])
                if not stock:
                    self._respond_json({'error': '请输入股票代码'}, cors_headers)
                else:
                    result = finder.find_gem_arbitrage(stock.strip().zfill(6), max_lag=max_lag)
                    self._respond_json(result, cors_headers)
            except Exception as e:
                self._respond_json({'error': str(e)}, cors_headers)

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')

    def _respond(self, status, body, content_type='text/html; charset=utf-8', extra_headers=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _respond_json(self, data, extra_headers=None):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self._respond(200, body, 'application/json; charset=utf-8', extra_headers)

    def log_message(self, format, *args):
        pass


def main():
    port = 5001
    server = HTTPServer(('0.0.0.0', port), Handler)

    print('=' * 50)
    print('股票联动查询 Web服务 V5')
    print('访问地址: http://localhost:5001')
    print('新增: T+0同日联动 | 方向性分析 | 去重')
    print('按 Ctrl+C 停止服务')
    print('=' * 50)

    server.serve_forever()


if __name__ == '__main__':
    main()
