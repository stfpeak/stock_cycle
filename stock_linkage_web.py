#!/usr/bin/env python3
"""
股票联动查询 Web服务 V4
=======================
启动方式：python stock_linkage_web.py
访问地址：http://localhost:5000

新增特性（V4）：
    1. 股票名称模糊搜索 + 自动补全
    2. 整合K线数据库，更长时间的涨停检测
    3. K线图可视化
    4. 概念级别联动分析
    5. 数据源标识（涨停池/数据库）
"""

import os
import json
import math
from datetime import datetime
from typing import List, Dict, Optional

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stock_linkage_finder import StockLinkageFinder

app = FastAPI(title="股票联动查询 V4")

finder = None


def get_finder():
    global finder
    if finder is None:
        finder = StockLinkageFinder()
        print("股票联动查找器 V4 已初始化")
    return finder


# ========== API ==========

@app.get("/api/search")
async def search_stocks(q: str = ""):
    """搜索股票（代码或名称）"""
    if not q or len(q.strip()) < 1:
        return JSONResponse([])
    results = get_finder().search_stock(q.strip())
    return JSONResponse(results)


@app.get("/api/linkage")
async def get_linkage(stock: str = "", concept: str = None, min_prob: float = 0.12):
    """查询股票联动"""
    if not stock:
        return JSONResponse({"error": "请输入股票代码"})
    try:
        stock_code = stock.strip().zfill(6)
        result = get_finder().find_stock_linkages(stock_code, concept, min_prob=min_prob)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.get("/api/kline")
async def get_kline(stock: str = "", days: int = 90):
    """获取股票K线数据"""
    if not stock:
        return JSONResponse({"error": "请输入股票代码"})
    try:
        stock_code = stock.strip().zfill(6)
        result = get_finder().get_stock_kline_summary(stock_code, days=days)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.get("/api/concept_zt_stats")
async def concept_zt_stats(concept: str = ""):
    """获取概念涨停统计"""
    if not concept:
        return JSONResponse({"error": "请输入概念名称"})
    try:
        result = get_finder().get_concept_zt_stats(concept)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.get("/api/concept_linkage")
async def concept_linkage(concept: str = "", top_n: int = 20):
    """获取概念内联动关系"""
    if not concept:
        return JSONResponse({"error": "请输入概念名称"})
    try:
        pairs = get_finder().analyze_concept_linkages(concept, top_n=top_n)
        return JSONResponse({"concept": concept, "pairs": pairs})
    except Exception as e:
        return JSONResponse({"error": str(e)})


# ========== HTML ==========

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>股票联动查询 V4</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    min-height: 100vh;
    color: #eee;
}
.container { max-width: 1200px; margin: 0 auto; padding: 20px; }
h1 {
    color: #00d4ff;
    text-align: center;
    margin: 25px 0 5px 0;
    font-size: 2.2em;
}
.subtitle { text-align: center; color: #666; margin-bottom: 25px; font-size: 0.9em; }

/* Search */
.search-box {
    background: #16213e;
    border-radius: 12px;
    padding: 25px 30px;
    margin: 15px 0;
    box-shadow: 0 8px 25px rgba(0,0,0,0.3);
}
.input-row { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; }
.input-item { flex: 1; min-width: 180px; position: relative; }
label { display: block; margin-bottom: 6px; color: #00d4ff; font-size: 0.9em; }
input[type="text"] {
    width: 100%;
    padding: 11px 14px;
    border: 2px solid #0f3460;
    border-radius: 8px;
    background: #1a1a2e;
    color: #eee;
    font-size: 15px;
    transition: border-color 0.3s;
}
input[type="text"]:focus { border-color: #00d4ff; outline: none; }

/* Search Suggestions */
.suggestions {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    background: #16213e;
    border: 1px solid #0f3460;
    border-radius: 0 0 8px 8px;
    max-height: 300px;
    overflow-y: auto;
    z-index: 1000;
    display: none;
    box-shadow: 0 8px 20px rgba(0,0,0,0.5);
}
.suggestions.active { display: block; }
.suggestion-item {
    padding: 10px 14px;
    cursor: pointer;
    border-bottom: 1px solid #0f3460;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.suggestion-item:hover { background: #0f3460; }
.suggestion-item .code { color: #00d4ff; font-weight: bold; }
.suggestion-item .name { margin-left: 10px; }
.suggestion-item .meta { color: #888; font-size: 0.85em; }

button {
    padding: 11px 28px;
    background: linear-gradient(135deg, #00d4ff 0%, #0066cc 100%);
    border: none;
    border-radius: 8px;
    color: #fff;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s;
    white-space: nowrap;
}
button:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(0,212,255,0.3); }
button:disabled { background: #555; cursor: not-allowed; transform: none; box-shadow: none; }
.btn-secondary {
    background: linear-gradient(135deg, #0f3460, #1a1a2e);
    border: 1px solid #00d4ff;
    font-weight: 400;
}

/* Tab Navigation */
.tabs { display: flex; gap: 0; margin: 15px 0; }
.tab {
    padding: 10px 24px;
    background: #1a1a2e;
    border: 1px solid #0f3460;
    cursor: pointer;
    color: #888;
    font-size: 0.95em;
    transition: all 0.2s;
}
.tab:first-child { border-radius: 8px 0 0 8px; }
.tab:last-child { border-radius: 0 8px 8px 0; }
.tab.active { background: #0f3460; color: #00d4ff; border-color: #00d4ff; }
.tab-content { display: none; }
.tab-content.active { display: block; }

/* Result cards */
.result {
    background: #16213e;
    border-radius: 12px;
    padding: 25px;
    margin: 15px 0;
    box-shadow: 0 8px 25px rgba(0,0,0,0.3);
}
.stock-header {
    display: flex;
    align-items: center;
    gap: 15px;
    margin-bottom: 15px;
    padding-bottom: 12px;
    border-bottom: 1px solid #333;
    flex-wrap: wrap;
}
.code-badge {
    background: #e94560;
    padding: 6px 14px;
    border-radius: 15px;
    font-weight: bold;
    font-size: 1.1em;
}
.stock-name { font-size: 1.4em; color: #00d4ff; font-weight: 600; }
.stock-meta { color: #888; font-size: 0.9em; }

.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.8em;
    margin: 2px;
}
.badge-pool { background: #0f3460; border: 1px solid #00d4ff; color: #00d4ff; }
.badge-db { background: #1a3a1a; border: 1px solid #00ff88; color: #00ff88; }
.badge-concept {
    background: #16213e;
    border: 1px solid #666;
    color: #aaa;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.85em;
    margin: 2px;
    display: inline-block;
}
.badge-concept.primary { border-color: #00d4ff; color: #00d4ff; }

.section-title { color: #ff6b6b; margin: 20px 0 10px 0; font-size: 1.15em; }

/* Table */
table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 0.9em; }
th {
    background: #0f3460;
    color: #00d4ff;
    padding: 10px 12px;
    text-align: left;
    position: sticky;
    top: 0;
}
td { padding: 8px 12px; border-bottom: 1px solid #333; }
tr:hover { background: #1a1a2e; }
tr.clickable { cursor: pointer; }
tr.clickable:hover { background: #0f3460; }

/* Probability bars */
.prob-cell { display: flex; align-items: center; gap: 6px; }
.prob-bar { width: 60px; height: 16px; background: #0f3460; border-radius: 3px; overflow: hidden; }
.prob-fill { height: 100%; border-radius: 3px; transition: width 0.5s; }
.prob-fill.t1 { background: linear-gradient(90deg, #e94560, #ff6b6b); }
.prob-fill.t2 { background: linear-gradient(90deg, #ffc107, #ff9800); }
.prob-fill.t3 { background: linear-gradient(90deg, #00bcd4, #00d4ff); }
.prob-fill.strength { background: linear-gradient(90deg, #00d4ff, #00ff88); }

/* K-line chart */
.kline-container { position: relative; width: 100%; height: 350px; margin: 10px 0; }
.kline-container canvas { width: 100%; height: 100%; }

/* Peak dates */
.peak-list { display: flex; flex-wrap: wrap; gap: 8px; }
.peak-item {
    background: #0f3460;
    border: 1px solid #ff6b6b;
    padding: 6px 14px;
    border-radius: 8px;
    font-size: 0.9em;
}
.peak-item .date { color: #ff6b6b; }
.peak-item .count { color: #00d4ff; font-weight: bold; }

/* Error/Loading/Empty */
.loading { text-align: center; padding: 40px; color: #888; }
.spinner {
    display: inline-block;
    width: 40px;
    height: 40px;
    border: 4px solid #333;
    border-top-color: #00d4ff;
    border-radius: 50%;
    animation: spin 1s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.error {
    background: rgba(233, 69, 96, 0.15);
    border: 1px solid #e94560;
    border-radius: 8px;
    padding: 15px;
    margin: 10px 0;
    color: #e94560;
}
.empty-state { text-align: center; padding: 50px 20px; color: #666; }
.empty-state .icon { font-size: 3em; display: block; margin-bottom: 15px; }

/* Linkage events */
.events-list { margin-top: 8px; font-size: 0.85em; color: #888; }
.event-item { display: inline-block; margin: 2px 6px 2px 0; }

/* Quick stock list */
.quick-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 15px; }
.quick-stock {
    background: #1a1a2e;
    border: 1px solid #333;
    padding: 8px 14px;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;
}
.quick-stock:hover { border-color: #00d4ff; background: #0f3460; }
.quick-stock .qs-code { color: #00d4ff; font-weight: bold; }
.quick-stock .qs-name { color: #aaa; margin-left: 6px; }
.quick-stock .qs-zt { color: #ff6b6b; margin-left: 6px; font-size: 0.85em; }

@media (max-width: 768px) {
    .input-row { flex-direction: column; }
    .container { padding: 10px; }
    .stock-header { flex-direction: column; align-items: flex-start; }
}
</style>
</head>
<body>
<div class="container">
    <h1>股票联动查询</h1>
    <p class="subtitle">基于涨停池 + K线数据库双源分析 | 历史涨停检测回溯至2026-01-05</p>

    <div class="search-box">
        <div class="input-row">
            <div class="input-item">
                <label>股票代码或名称</label>
                <input type="text" id="stockInput" placeholder="如: 600396 或 华电辽能" autocomplete="off">
                <div class="suggestions" id="suggestions"></div>
            </div>
            <div class="input-item">
                <label>限定概念（可选）</label>
                <input type="text" id="conceptInput" placeholder="如: 绿色电力 或留空">
            </div>
            <div style="display: flex; gap: 8px; align-items: flex-end;">
                <button onclick="doSearch()" id="searchBtn">查询联动</button>
                <button class="btn-secondary" onclick="switchTab('concept')">概念分析</button>
            </div>
        </div>
    </div>

    <!-- Tabs -->
    <div class="tabs">
        <div class="tab active" onclick="switchTab('linkage')">联动查询</div>
        <div class="tab" onclick="switchTab('concept')">概念分析</div>
        <div class="tab" onclick="switchTab('hot')">热门涨停股</div>
    </div>

    <!-- Tab: Linkage Query -->
    <div class="tab-content active" id="tab-linkage">
        <div id="resultContainer">
            <div class="empty-state">
                <span class="icon">🔍</span>
                <p>输入股票代码或名称开始查询</p>
                <p style="font-size: 0.85em; margin-top: 8px; color: #555;">
                    例如：600396（华电辽能）、000021、688256、金山
                </p>
            </div>
        </div>
    </div>

    <!-- Tab: Concept Analysis -->
    <div class="tab-content" id="tab-concept">
        <div class="search-box">
            <div class="input-row">
                <div class="input-item">
                    <label>概念名称</label>
                    <input type="text" id="conceptQueryInput" placeholder="如: 存储芯片、绿色电力">
                </div>
                <div style="display: flex; align-items: flex-end;">
                    <button onclick="doConceptSearch()">分析概念</button>
                </div>
            </div>
        </div>
        <div id="conceptResult"></div>
    </div>

    <!-- Tab: Hot Stocks -->
    <div class="tab-content" id="tab-hot">
        <div id="hotStocksContainer">
            <div class="loading"><div class="spinner"></div><p>加载热门涨停股...</p></div>
        </div>
    </div>
</div>

<script>
// ========== Global State ==========
let currentTab = 'linkage';
let currentStockData = null;

// ========== Tab Switching ==========
function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => {
        if (t.textContent.includes(tab === 'linkage' ? '联动' : tab === 'concept' ? '概念' : '热门')) {
            t.classList.add('active');
        }
    });
    document.getElementById('tab-' + tab).classList.add('active');

    if (tab === 'hot' && !document.getElementById('hotStocksContainer').querySelector('.result')) {
        loadHotStocks();
    }
}

// ========== Search Suggestions ==========
let suggestTimer = null;
document.getElementById('stockInput').addEventListener('input', function() {
    clearTimeout(suggestTimer);
    const q = this.value.trim();
    if (q.length < 1) {
        document.getElementById('suggestions').classList.remove('active');
        return;
    }
    suggestTimer = setTimeout(() => {
        fetch('/api/search?q=' + encodeURIComponent(q))
            .then(r => r.json())
            .then(data => {
                renderSuggestions(data);
            });
    }, 200);
});

document.addEventListener('click', function(e) {
    if (!e.target.closest('.input-item')) {
        document.getElementById('suggestions').classList.remove('active');
    }
});

function renderSuggestions(items) {
    const el = document.getElementById('suggestions');
    if (!items || items.length === 0) {
        el.classList.remove('active');
        return;
    }
    let html = '';
    items.slice(0, 12).forEach(item => {
        html += '<div class="suggestion-item" onclick="selectStock(\'' + item.code + '\', \'' + item.name + '\')">';
        html += '<span><span class="code">' + item.code + '</span><span class="name">' + item.name + '</span></span>';
        html += '<span class="meta">涨停' + item.zt_count + '次 | ' + item.concept_count + '概念</span>';
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

// ========== Main Search ==========
function doSearch() {
    const raw = document.getElementById('stockInput').value.trim();
    const concept = document.getElementById('conceptInput').value.trim();

    if (!raw) { alert('请输入股票代码或名称'); return; }

    // Extract stock code
    let stock = raw;
    const codeMatch = raw.match(/(\\d{6})/);
    if (codeMatch) stock = codeMatch[1];

    switchTab('linkage');

    const container = document.getElementById('resultContainer');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p style="margin-top:15px;">正在查询联动数据...</p></div>';

    let url = '/api/linkage?stock=' + encodeURIComponent(stock);
    if (concept) url += '&concept=' + encodeURIComponent(concept);
    url += '&min_prob=0.10';

    fetch(url)
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                container.innerHTML = '<div class="error">' + data.error + '</div>';
                return;
            }
            currentStockData = data;
            renderLinkageResult(data);
            loadKlineChart(stock);
        })
        .catch(e => {
            container.innerHTML = '<div class="error">请求失败: ' + e.message + '</div>';
        });
}

function renderLinkageResult(data) {
    const container = document.getElementById('resultContainer');

    // Header
    let html = '<div class="result">';
    html += '<div class="stock-header">';
    html += '<span class="code-badge">' + data.stock_code + '</span>';
    html += '<span class="stock-name">' + (data.stock_name || data.stock_code) + '</span>';
    html += '<span class="stock-meta">历史涨停 <strong style="color:#ff6b6b">' + (data.base_zt_count || 0) + '</strong> 次</span>';

    if (data.data_source) {
        html += '<span class="badge badge-pool">涨停池 ' + (data.data_source.zt_pool_count || 0) + '次</span>';
        html += '<span class="badge badge-db">数据库 ' + (data.data_source.db_count || 0) + '次</span>';
    }
    html += '</div>';

    // Concepts
    if (data.concepts && data.concepts.length > 0) {
        html += '<div style="margin-bottom: 15px;">';
        data.concepts.forEach(function(c) {
            html += '<span class="badge-concept primary">' + c + '</span>';
        });
        html += '</div>';
    }

    // ZT dates
    if (data.base_zt_dates && data.base_zt_dates.length > 0) {
        html += '<div style="margin-bottom: 15px;">';
        html += '<span style="color: #888; font-size: 0.9em;">涨停日期: </span>';
        data.base_zt_dates.forEach(function(d) {
            html += '<span style="background:#1a1a2e; padding: 2px 8px; border-radius: 4px; margin: 2px; font-size: 0.85em; border:1px solid #333;">' + d + '</span>';
        });
        html += '</div>';
    }

    // K-line chart
    html += '<h3 class="section-title">K线图（近90日）</h3>';
    html += '<div class="kline-container"><canvas id="klineCanvas"></canvas></div>';

    // No linkages
    if (!data.linkages || data.linkages.length === 0) {
        html += '<div class="empty-state"><p>未找到联动股票</p>';
        html += '<p style="color: #666; font-size: 0.85em;">需要历史涨停次数 ≥ 2 次才能计算联动</p></div></div>';
        container.innerHTML = html;
        return;
    }

    // Linkage table - group by concept
    const grouped = {};
    data.linkages.forEach(function(link) {
        const c = link.concept || '未知';
        if (!grouped[c]) grouped[c] = [];
        grouped[c].push(link);
    });

    const conceptNames = Object.keys(grouped).sort((a, b) => grouped[b].length - grouped[a].length);

    html += '<h3 class="section-title">联动股票（按概念分组，共 ' + data.linkages.length + ' 只）</h3>';

    conceptNames.forEach(function(concept) {
        const links = grouped[concept];
        html += '<div style="margin-bottom: 25px;">';
        html += '<h4 style="color: #00d4ff; margin-bottom: 8px;">' + concept + ' <span style="color:#888;font-weight:normal;font-size:0.9em">(' + links.length + '只)</span></h4>';
        html += '<table>';
        html += '<tr><th>代码</th><th>名称</th><th>T+1</th><th>T+2</th><th>T+3</th><th>综合</th><th>联动次数</th><th>自身ZT</th><th style="width:180px">联动事件</th></tr>';

        links.slice(0, 10).forEach(function(link) {
            const l1p = (link.lag1_prob * 100).toFixed(0);
            const l2p = (link.lag2_prob * 100).toFixed(0);
            const l3p = (link.lag3_prob * 100).toFixed(0);
            const sp = (link.strength * 100).toFixed(0);
            const events = link.linkage_events || [];

            html += '<tr class="clickable" onclick="selectStock(\'' + link.linked_stock + '\',\'' + link.linked_name + '\')">';
            html += '<td><strong>' + link.linked_stock + '</strong></td>';
            html += '<td>' + link.linked_name + '</td>';
            html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t1" style="width:' + l1p + '%"></div></div><span>' + l1p + '%</span></div></td>';
            html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t2" style="width:' + l2p + '%"></div></div><span>' + l2p + '%</span></div></td>';
            html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t3" style="width:' + l3p + '%"></div></div><span>' + l3p + '%</span></div></td>';
            html += '<td><strong style="color:#00ff88">' + sp + '%</strong></td>';
            html += '<td>' + events.length + '</td>';
            html += '<td>' + (link.linked_zt_count || 0) + '</td>';
            html += '<td style="font-size:0.8em; color: #888;">';
            events.slice(-3).forEach(function(evt) {
                html += '<span class="event-item">' + evt.base_date + '→T+' + evt.lag + ' ' + evt.linked_date + '</span><br>';
            });
            html += '</td></tr>';
        });

        if (links.length > 10) {
            html += '<tr><td colspan="9" style="text-align:center;color:#888;">...还有 ' + (links.length - 10) + ' 只联动股票</td></tr>';
        }
        html += '</table></div>';
    });

    html += '</div>';
    container.innerHTML = html;

    // Draw chart if data loaded
    if (window.klineChartData) {
        drawKlineChart(window.klineChartData);
    }
}

// ========== K-line Chart (Canvas) ==========
let klineChartData = null;

function loadKlineChart(stockCode) {
    fetch('/api/kline?stock=' + encodeURIComponent(stockCode) + '&days=90')
        .then(r => r.json())
        .then(data => {
            if (data.klines && data.klines.length > 0) {
                klineChartData = data;
                drawKlineChart(data);
            }
        });
}

function drawKlineChart(data) {
    const canvas = document.getElementById('klineCanvas');
    if (!canvas) return;

    const klines = data.klines;
    const ztDates = new Set(data.zt_dates || []);

    canvas.width = canvas.parentElement.clientWidth;
    canvas.height = 350;
    const ctx = canvas.getContext('2d');
    const W = canvas.width;
    const H = canvas.height;

    if (klines.length < 2) return;

    ctx.clearRect(0, 0, W, H);

    // Calculate ranges
    let minPrice = Infinity, maxPrice = -Infinity;
    let maxVol = 0;
    klines.forEach(k => {
        if (k.low < minPrice) minPrice = k.low;
        if (k.high > maxPrice) maxPrice = k.high;
        if (k.volume > maxVol) maxVol = k.volume;
    });
    const priceRange = maxPrice - minPrice || 1;
    minPrice -= priceRange * 0.05;
    maxPrice += priceRange * 0.05;

    // Layout
    const margin = { top: 10, right: 20, bottom: 40, left: 55 };
    const chartW = W - margin.left - margin.right;
    const chartH = H - margin.top - margin.bottom;
    const priceH = chartH * 0.65;
    const volH = chartH * 0.25;
    const gap = 10;

    const candleW = Math.max(3, Math.min(15, chartW / klines.length * 0.7));
    const spacing = chartW / klines.length;

    // Draw price area background
    ctx.fillStyle = '#111827';
    ctx.fillRect(margin.left, margin.top, chartW, priceH);

    // Grid lines
    ctx.strokeStyle = '#1a2740';
    ctx.lineWidth = 0.5;
    const gridLines = 5;
    for (let i = 0; i <= gridLines; i++) {
        const y = margin.top + (priceH / gridLines) * i;
        ctx.beginPath();
        ctx.moveTo(margin.left, y);
        ctx.lineTo(margin.left + chartW, y);
        ctx.stroke();

        // Price labels
        const price = maxPrice - (priceRange * 1.1) * (i / gridLines);
        ctx.fillStyle = '#666';
        ctx.font = '10px monospace';
        ctx.textAlign = 'right';
        ctx.fillText(price.toFixed(2), margin.left - 5, y + 3);
    }

    // Draw candlesticks
    klines.forEach((k, i) => {
        const x = margin.left + i * spacing + spacing / 2;
        const isZT = ztDates.has(k.date);

        const openY = margin.top + (maxPrice - k.open) / (maxPrice - minPrice) * priceH;
        const closeY = margin.top + (maxPrice - k.close) / (maxPrice - minPrice) * priceH;
        const highY = margin.top + (maxPrice - k.high) / (maxPrice - minPrice) * priceH;
        const lowY = margin.top + (maxPrice - k.low) / (maxPrice - minPrice) * priceH;

        const isGreen = k.close >= k.open;
        const bodyTop = isGreen ? closeY : openY;
        const bodyH = Math.max(1, Math.abs(closeY - openY));

        // Wick
        ctx.strokeStyle = isGreen ? '#ef4444' : '#22c55e';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, highY);
        ctx.lineTo(x, lowY);
        ctx.stroke();

        // Body
        if (isZT) {
            ctx.fillStyle = '#ff00ff';
            ctx.strokeStyle = '#ff00ff';
        } else {
            ctx.fillStyle = isGreen ? '#ef4444' : '#22c55e';
            ctx.strokeStyle = isGreen ? '#ef4444' : '#22c55e';
        }
        ctx.lineWidth = 1;
        ctx.fillRect(x - candleW / 2, bodyTop, candleW, bodyH);
        ctx.strokeRect(x - candleW / 2, bodyTop, candleW, bodyH);
    });

    // Volume area
    const volTop = margin.top + priceH + gap;
    ctx.fillStyle = '#111827';
    ctx.fillRect(margin.left, volTop, chartW, volH);

    klines.forEach((k, i) => {
        const x = margin.left + i * spacing + spacing / 2;
        const isGreen = k.close >= k.open;
        const volRatio = k.volume / maxVol;
        const barH = volRatio * volH;

        ctx.fillStyle = isGreen ? 'rgba(239,68,68,0.4)' : 'rgba(34,197,94,0.4)';
        ctx.fillRect(x - candleW / 2, volTop + volH - barH, candleW, barH);
    });

    // Date labels (every ~15 days)
    ctx.fillStyle = '#666';
    ctx.font = '10px monospace';
    ctx.textAlign = 'center';
    const step = Math.max(1, Math.floor(klines.length / 6));
    for (let i = 0; i < klines.length; i += step) {
        const x = margin.left + i * spacing + spacing / 2;
        const dateStr = klines[i].date;
        ctx.fillText(dateStr.slice(4, 6) + '/' + dateStr.slice(6, 8), x, H - 5);
    }

    // Legend
    ctx.fillStyle = '#ff00ff';
    ctx.fillRect(W - 100, 5, 8, 8);
    ctx.fillStyle = '#888';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('涨停日', W - 88, 13);
}

window.addEventListener('resize', function() {
    if (klineChartData) drawKlineChart(klineChartData);
});

// ========== Concept Analysis ==========
function doConceptSearch() {
    const concept = document.getElementById('conceptQueryInput').value.trim();
    if (!concept) { alert('请输入概念名称'); return; }

    const container = document.getElementById('conceptResult');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p>分析中...</p></div>';

    Promise.all([
        fetch('/api/concept_zt_stats?concept=' + encodeURIComponent(concept)).then(r => r.json()),
        fetch('/api/concept_linkage?concept=' + encodeURIComponent(concept) + '&top_n=20').then(r => r.json())
    ]).then(([stats, linkage]) => {
        renderConceptResult(stats, linkage);
    }).catch(e => {
        container.innerHTML = '<div class="error">请求失败: ' + e.message + '</div>';
    });
}

function renderConceptResult(stats, linkage) {
    const container = document.getElementById('conceptResult');

    if (!stats || stats.total_stocks === 0) {
        container.innerHTML = '<div class="result"><div class="empty-state"><p>概念不存在或无数据</p></div></div>';
        return;
    }

    let html = '<div class="result">';

    // Summary
    html += '<div class="stock-header">';
    html += '<span class="stock-name">' + stats.concept + '</span>';
    html += '<span class="stock-meta">成分股: <strong>' + stats.total_stocks + '</strong> 只</span>';
    html += '<span class="stock-meta">有涨停记录: <strong style="color:#ff6b6b">' + stats.zt_stock_count + '</strong> 只</span>';
    html += '</div>';

    // Peak dates
    if (stats.peak_dates && stats.peak_dates.length > 0) {
        html += '<div style="margin-bottom: 15px;">';
        html += '<span style="color: #888; font-size: 0.9em;">峰值涨停日: </span>';
        html += '<div class="peak-list" style="display:inline-flex;">';
        stats.peak_dates.slice(0, 8).forEach(function(p) {
            html += '<span class="peak-item"><span class="date">' + p.date + '</span> <span class="count">' + p.count + '股涨停</span></span>';
        });
        html += '</div></div>';
    }

    // Top ZT stocks in concept
    html += '<h3 class="section-title">概念内涨停股票 (Top 15)</h3>';
    html += '<table><tr><th>代码</th><th>名称</th><th>涨停次数</th><th>首次涨停</th><th>最近涨停</th><th>涨停日期</th></tr>';
    stats.zt_stocks.slice(0, 15).forEach(function(s) {
        html += '<tr class="clickable" onclick="selectStock(\'' + s.code + '\',\'' + s.name + '\')">';
        html += '<td><strong>' + s.code + '</strong></td><td>' + s.name + '</td>';
        html += '<td style="color:#ff6b6b;font-weight:bold">' + s.zt_count + '</td>';
        html += '<td>' + s.first_zt + '</td><td>' + s.last_zt + '</td>';
        html += '<td style="font-size:0.8em;color:#888;">' + s.dates.slice(-6).join(', ') + '</td>';
        html += '</tr>';
    });
    html += '</table>';

    // Linkage pairs
    if (linkage && linkage.pairs && linkage.pairs.length > 0) {
        html += '<h3 class="section-title">概念内最强联动对 (Top 20)</h3>';
        html += '<table><tr><th>股票A</th><th>名称A</th><th style="text-align:center">→</th><th>股票B</th><th>名称B</th><th>T+1</th><th>T+2</th><th>T+3</th><th>综合</th></tr>';
        linkage.pairs.forEach(function(p) {
            const l1 = (p.lag1_prob * 100).toFixed(0);
            const l2 = (p.lag2_prob * 100).toFixed(0);
            const l3 = (p.lag3_prob * 100).toFixed(0);
            const sp = (p.strength * 100).toFixed(0);
            html += '<tr class="clickable" onclick="selectStock(\'' + p.stock_a + '\',\'' + p.name_a + '\')">';
            html += '<td><strong>' + p.stock_a + '</strong></td><td>' + p.name_a + '</td>';
            html += '<td style="text-align:center;color:#00d4ff">→</td>';
            html += '<td><strong>' + p.stock_b + '</strong></td><td>' + p.name_b + '</td>';
            html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t1" style="width:' + l1 + '%"></div></div><span>' + l1 + '%</span></div></td>';
            html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t2" style="width:' + l2 + '%"></div></div><span>' + l2 + '%</span></div></td>';
            html += '<td><div class="prob-cell"><div class="prob-bar"><div class="prob-fill t3" style="width:' + l3 + '%"></div></div><span>' + l3 + '%</span></div></td>';
            html += '<td><strong style="color:#00ff88">' + sp + '%</strong></td>';
            html += '</tr>';
        });
        html += '</table>';
    }

    html += '</div>';
    container.innerHTML = html;
}

// ========== Hot Stocks ==========
function loadHotStocks() {
    const container = document.getElementById('hotStocksContainer');

    // Collect top ZT stocks
    fetch('/api/search?q=').then(r => r.json()).then(data => {
        if (!data || data.length === 0) {
            container.innerHTML = '<div class="result"><div class="empty-state"><p>暂无数据</p></div></div>';
            return;
        }

        // Show top 30 stocks by ZT count
        const sorted = data.sort((a, b) => b.zt_count - a.zt_count).slice(0, 30);

        let html = '<div class="result"><h3 class="section-title">涨停最多的股票 (Top 30)</h3>';
        html += '<div class="quick-list">';
        sorted.forEach(function(s) {
            html += '<div class="quick-stock" onclick="selectStock(\'' + s.code + '\',\'' + s.name + '\')">';
            html += '<span class="qs-code">' + s.code + '</span>';
            html += '<span class="qs-name">' + s.name + '</span>';
            html += '<span class="qs-zt">涨停' + s.zt_count + '次</span>';
            html += '</div>';
        });
        html += '</div></div>';
        container.innerHTML = html;
    });
}

// ========== Enter key ==========
document.getElementById('stockInput').addEventListener('keypress', function(e) {
    if (e.key === 'Enter') {
        document.getElementById('suggestions').classList.remove('active');
        doSearch();
    }
});
document.getElementById('conceptInput').addEventListener('keypress', function(e) {
    if (e.key === 'Enter') doSearch();
});
document.getElementById('conceptQueryInput').addEventListener('keypress', function(e) {
    if (e.key === 'Enter') doConceptSearch();
});
</script>
</body>
</html>
"""


@app.get("/")
async def home():
    return HTMLResponse(content=HTML_PAGE)


if __name__ == "__main__":
    print("=" * 60)
    print("股票联动查询 Web服务 V4")
    print("访问地址: http://localhost:5000")
    print("新增: 双源涨停检测 | 名称模糊搜索 | K线图 | 概念分析")
    print("按 Ctrl+C 停止")
    print("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="info")
