import os
import json
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

# Strict allowlist of public fields (Privacy Firewall)
PUBLIC_FIELDS = {
    "schema_version",
    "net_return_pct",
    "win_rate_pct",
    "total_trades",
    "wins",
    "losses",
    "active_positions",
    "peak_net_return_pct",
    "peak_win_rate_pct",
    "updated_at",
    "active_signals",
    "closed_signals",
    "system_health",
}

FORBIDDEN_FIELDS = {
    "capital", "initial_capital", "available_cash", "trade_size",
    "trade_size_usd", "wallet", "private_key", "secret", "token",
    "api_key", "password", "trades", "closed_trades", "open_positions",
    "pnl_usd", "gross_pnl_usd", "entry_fee_usd", "exit_fee_usd", "total_fees_usd", "qty"
}

DATA_PATH = os.getenv("PUBLIC_METRICS_PATH", "/app/data/public_metrics.json")
STALE_THRESHOLD_SECONDS = 300  # 5 minutes

def load_and_validate_metrics():
    if not os.path.exists(DATA_PATH):
        return None, False, "Public metrics file not found"

    try:
        with open(DATA_PATH, "r") as f:
            raw = json.load(f)
    except Exception:
        return None, False, "Public metrics file unreadable or invalid JSON"

    if not isinstance(raw, dict):
        return None, False, "Public metrics payload must be a JSON object"

    for forbidden in FORBIDDEN_FIELDS:
        if forbidden in raw:
            return None, False, "Privacy violation detected: forbidden field present"

    for s in raw.get("closed_signals", []):
        for forbidden in FORBIDDEN_FIELDS:
            if forbidden in s:
                return None, False, "Privacy violation: closed signal contains forbidden field"

    for a in raw.get("active_signals", []):
        for forbidden in FORBIDDEN_FIELDS:
            if forbidden in a:
                return None, False, "Privacy violation: active signal contains forbidden field"

    sanitized = {k: raw[k] for k in PUBLIC_FIELDS if k in raw}

    is_stale = False
    updated_at_str = sanitized.get("updated_at")
    if updated_at_str:
        try:
            updated_at = datetime.fromisoformat(updated_at_str)
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if (now - updated_at).total_seconds() > STALE_THRESHOLD_SECONDS:
                is_stale = True
        except Exception:
            is_stale = True

    return sanitized, is_stale, None

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PureQuant AI • Public Spot Intelligence & System Terminal</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background-color: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        .card { background-color: #161b22; border: 1px solid #30363d; border-radius: 0.75rem; }
        .tab-btn.active { background-color: #1f242c; color: #58a6ff; border-bottom: 2px solid #58a6ff; }
        .tab-btn { color: #8b949e; border-bottom: 2px solid transparent; }
    </style>
</head>
<body class="min-h-screen flex flex-col p-4 md:p-6 lg:p-8">
    <!-- Header -->
    <header class="max-w-6xl mx-auto w-full flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 pb-6 border-b border-[#30363d]">
        <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-blue-600 to-emerald-400 flex items-center justify-center font-bold text-white text-lg shadow-lg shadow-blue-500/20">
                PQ
            </div>
            <div>
                <h1 class="text-xl md:text-2xl font-black text-[#58a6ff] tracking-tight">PUREQUANT AI TRADING</h1>
                <p class="text-xs text-[#8b949e]">Public Spot Intelligence & Verified System Terminal • Zero Leverage</p>
            </div>
        </div>
        <div class="flex items-center gap-4 text-xs font-semibold">
            {% set h = metrics.system_health if metrics else None %}
            {% if h and h.overall == 'operational' %}
            <span class="px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> ALL SYSTEMS OPERATIONAL
            </span>
            {% else %}
            <span class="px-3 py-1 rounded-full bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-yellow-400 animate-pulse"></span> SYSTEM DEGRADED
            </span>
            {% endif %}
            <a href="https://t.me/PureQuantAIBot" target="_blank" class="px-3 py-1 rounded-full bg-[#21262d] hover:bg-[#30363d] border border-[#30363d] text-[#58a6ff]">
                Telegram Bot ↗
            </a>
        </div>
    </header>

    <main class="max-w-6xl mx-auto w-full my-6 flex-1">
        {% if error_message %}
        <div class="card p-10 text-center border-yellow-500/30">
            <div class="text-3xl mb-3">⚠️</div>
            <h2 class="text-xl font-bold text-yellow-400">System Temporarily Unavailable</h2>
            <p class="text-sm text-[#8b949e] max-w-md mx-auto mt-2">{{ error_message }}</p>
        </div>
        {% else %}
        
        {% if is_stale %}
        <div class="mb-4 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 text-xs flex items-center justify-between">
            <span>⚠️ Telemetry Notice: Displaying last verified snapshot (Continuous health monitor syncing).</span>
            <span class="font-mono text-[11px]">{{ sync_time }} UTC</span>
        </div>
        {% endif %}

        <!-- Top Metrics Row -->
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <div class="card p-4 border-emerald-500/40">
                <div class="flex justify-between items-center">
                    <span class="text-xs font-bold text-[#8b949e] uppercase tracking-wider">Net Return</span>
                    <span class="text-[10px] font-black px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400">RECORDED</span>
                </div>
                <div id="metric-net-return" class="text-2xl font-black text-emerald-400 mt-1">
                    +{{ "%.2f"|format(metrics.net_return_pct) }}%
                </div>
                <div class="text-[11px] text-[#8b949e] mt-1">
                    All-Time Peak: +{{ "%.2f"|format(metrics.peak_net_return_pct) }}%
                </div>
            </div>

            <div class="card p-4 border-blue-500/40">
                <div class="flex justify-between items-center">
                    <span class="text-xs font-bold text-[#8b949e] uppercase tracking-wider">Win Rate</span>
                    <span class="text-[10px] font-black px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400">RECORDED</span>
                </div>
                <div id="metric-win-rate" class="text-2xl font-black text-[#58a6ff] mt-1">
                    {{ "%.1f"|format(metrics.win_rate_pct) }}%
                </div>
                <div class="text-[11px] text-[#8b949e] mt-1">
                    {{ metrics.wins }}W / {{ metrics.losses }}L • {{ metrics.total_trades }} Trades
                </div>
            </div>

            <div class="card p-4 border-yellow-500/40">
                <div class="flex justify-between items-center">
                    <span class="text-xs font-bold text-[#8b949e] uppercase tracking-wider">Active Signals</span>
                    <span class="text-[10px] font-black px-1.5 py-0.5 rounded bg-yellow-500/20 text-yellow-400">V2 SCANNER</span>
                </div>
                <div id="metric-active-count" class="text-2xl font-black text-yellow-400 mt-1">
                    {{ metrics.active_signals|length }} Ready
                </div>
                <div class="text-[11px] text-[#8b949e] mt-1">
                    Worth Opening Candidates
                </div>
            </div>

            <div class="card p-4 border-purple-500/40">
                <div class="flex justify-between items-center">
                    <span class="text-xs font-bold text-[#8b949e] uppercase tracking-wider">System Health</span>
                    {% if metrics.system_health and metrics.system_health.overall == 'operational' %}
                    <span class="text-[10px] font-black px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400">OPERATIONAL</span>
                    {% else %}
                    <span class="text-[10px] font-black px-1.5 py-0.5 rounded bg-yellow-500/20 text-yellow-400">DEGRADED</span>
                    {% endif %}
                </div>
                <div class="text-2xl font-black {% if metrics.system_health and metrics.system_health.overall == 'operational' %}text-emerald-400{% else %}text-yellow-400{% endif %} mt-1">
                    {{ metrics.system_health.modules|length if metrics.system_health else 6 }}/{{ metrics.system_health.modules|length if metrics.system_health else 6 }} Live
                </div>
                <div class="text-[11px] text-[#8b949e] mt-1">
                    Continuous Health Monitor
                </div>
            </div>
        </div>

        <!-- Navigation Tabs -->
        <div class="flex border-b border-[#30363d] mb-4">
            <button onclick="switchTab('active')" id="tab-btn-active" class="tab-btn active px-4 py-2 text-sm font-bold flex items-center gap-2">
                <span>⚡ Active Signals</span>
                <span id="badge-active-count" class="px-2 py-0.5 text-xs rounded-full bg-yellow-500/20 text-yellow-300">{{ metrics.active_signals|length }}</span>
            </button>
            <button onclick="switchTab('history')" id="tab-btn-history" class="tab-btn px-4 py-2 text-sm font-bold flex items-center gap-2">
                <span>📜 Signal History (PnL %)</span>
                <span id="badge-history-count" class="px-2 py-0.5 text-xs rounded-full bg-blue-500/20 text-blue-300">20 of {{ metrics.closed_signals|length }}</span>
            </button>
            <button onclick="switchTab('health')" id="tab-btn-health" class="tab-btn px-4 py-2 text-sm font-bold flex items-center gap-2">
                <span>🏥 System & Module Health</span>
                {% if metrics.system_health and metrics.system_health.overall == 'operational' %}
                <span class="px-2 py-0.5 text-xs rounded-full bg-emerald-500/20 text-emerald-300">Operational</span>
                {% else %}
                <span id="badge-active-count" class="px-2 py-0.5 text-xs rounded-full bg-yellow-500/20 text-yellow-300">Degraded</span>
                {% endif %}
            </button>
        </div>

        <!-- Tab 1: Active Signals -->
        <div id="tab-content-active" class="card overflow-hidden">
            {% if metrics.active_signals %}
            <div class="overflow-x-auto">
                <table class="w-full text-left text-xs">
                    <thead class="bg-[#21262d] text-[#8b949e] uppercase font-bold border-b border-[#30363d]">
                        <tr>
                            <th class="p-3">Asset</th>
                            <th class="p-3">Direction</th>
                            <th class="p-3">Score</th>
                            <th class="p-3">Setup</th>
                            <th class="p-3">Entry Ref</th>
                            <th class="p-3">TP1 / TP2 / TP3</th>
                            <th class="p-3">Stop Loss</th>
                            <th class="p-3">R:R</th>
                        </tr>
                    </thead>
                    <tbody id="active-signals-tbody" class="divide-y divide-[#30363d]">
                        {% for s in metrics.active_signals %}
                        <tr class="hover:bg-[#1c2128] transition-colors">
                            <td class="p-3 font-bold text-white flex items-center gap-2">
                                <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
                                {{ s.symbol }}
                            </td>
                            <td class="p-3">
                                <span class="px-2 py-0.5 rounded font-black text-[10px] {% if s.direction == 'LONG' %}bg-emerald-500/20 text-emerald-400{% else %}bg-red-500/20 text-red-400{% endif %}">
                                    {{ s.direction }}
                                </span>
                            </td>
                            <td class="p-3 font-mono font-bold text-[#58a6ff]">{{ s.score|int }}/100</td>
                            <td class="p-3 text-[#8b949e] font-mono">{{ s.setup }}</td>
                            <td class="p-3 font-mono text-white">${{ s.entry_reference }}</td>
                            <td class="p-3 font-mono text-emerald-400">
                                ${{ s.tp1 }} <span class="text-[#8b949e]">|</span> ${{ s.tp2 }} <span class="text-[#8b949e]">|</span> ${{ s.tp3 }}
                            </td>
                            <td class="p-3 font-mono text-red-400">${{ s.stop_loss }}</td>
                            <td class="p-3 font-mono text-purple-400">1:{{ s.risk_reward }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <div class="p-8 text-center text-[#8b949e]">
                <p class="text-sm font-semibold">No actionable signals currently meet the 95+ confluence threshold.</p>
                <p class="text-xs mt-1">PureQuant V2 Scanner is actively monitoring 198 crypto assets across Binance & Spot liquidity pools.</p>
            </div>
            {% endif %}
        </div>

        <!-- Tab 2: Signal History -->
        <div id="tab-content-history" class="card overflow-hidden hidden">
            <div class="overflow-x-auto">
                <table class="w-full text-left text-xs">
                    <thead class="bg-[#21262d] text-[#8b949e] uppercase font-bold border-b border-[#30363d]">
                        <tr>
                            <th class="p-3">Asset</th>
                            <th class="p-3">Direction</th>
                            <th class="p-3">Result</th>
                            <th class="p-3">Return (PnL %)</th>
                            <th class="p-3">Entry Price</th>
                            <th class="p-3">Exit Price</th>
                            <th class="p-3">Exit Time (UTC)</th>
                        </tr>
                    </thead>
                    <tbody id="history-signals-tbody" class="divide-y divide-[#30363d]">
                        {% for t in metrics.closed_signals[:20] %}
                        <tr class="hover:bg-[#1c2128] transition-colors">
                            <td class="p-3 font-bold text-white">{{ t.pair }}</td>
                            <td class="p-3">
                                <span class="px-2 py-0.5 rounded font-black text-[10px] {% if t.direction == 'BUY' or t.direction == 'LONG' %}bg-emerald-500/20 text-emerald-400{% else %}bg-red-500/20 text-red-400{% endif %}">
                                    {{ t.direction }}
                                </span>
                            </td>
                            <td class="p-3">
                                <span class="px-2 py-0.5 rounded font-black text-[10px] {% if 'WIN' in t.status %}bg-emerald-500/20 text-emerald-400{% else %}bg-red-500/20 text-red-400{% endif %}">
                                    {{ t.status }}
                                </span>
                            </td>
                            <td class="p-3 font-mono font-bold {% if t.pnl_pct > 0 %}text-emerald-400{% elif t.pnl_pct < 0 %}text-red-400{% else %}text-[#8b949e]{% endif %}">
                                {% if t.pnl_pct > 0 %}+{% endif %}{{ "%.2f"|format(t.pnl_pct) }}%
                            </td>
                            <td class="p-3 font-mono text-[#8b949e]">${{ t.entry_price }}</td>
                            <td class="p-3 font-mono text-white">${{ t.exit_price }}</td>
                            <td class="p-3 text-[#8b949e] font-mono text-[11px]">{{ t.exit_time }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <!-- Pagination & Load More Footer -->
            <div class="p-3.5 bg-[#161b22] border-t border-[#30363d] flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
                <div class="text-[#8b949e]">
                    Showing <span id="history-showing-range" class="font-bold text-white">1-20</span> of <span id="history-total-count" class="font-bold text-white">{{ metrics.closed_signals|length }}</span> recorded signals
                </div>
                <div class="flex items-center gap-2">
                    <button onclick="prevHistoryPage()" id="btn-history-prev" class="px-3 py-1.5 rounded bg-[#21262d] border border-[#30363d] text-[#8b949e] hover:bg-[#30363d] hover:text-white transition disabled:opacity-30 disabled:cursor-not-allowed" disabled>
                        ◀ Previous
                    </button>
                    <span id="history-page-indicator" class="px-2 font-mono text-[#8b949e]">Page 1 of 5</span>
                    <button onclick="nextHistoryPage()" id="btn-history-next" class="px-3 py-1.5 rounded bg-[#21262d] border border-[#30363d] text-[#8b949e] hover:bg-[#30363d] hover:text-white transition disabled:opacity-30 disabled:cursor-not-allowed">
                        Next ▶
                    </button>
                    <button onclick="loadMoreHistory()" id="btn-history-loadmore" class="ml-2 px-3.5 py-1.5 rounded bg-blue-600/20 border border-blue-500/30 font-bold text-blue-400 hover:bg-blue-600/30 transition">
                        Load More (+20)
                    </button>
                </div>
            </div>
        </div>

        <!-- Tab 3: System Health -->
        <div id="tab-content-health" class="card p-5 hidden">
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 pb-4 mb-4 border-b border-[#30363d]">
                <div>
                    <h2 class="text-base font-bold text-white">System Architecture & Pipeline Telemetry</h2>
                    <p class="text-xs text-[#8b949e]">Real-time liveness, network latency, and service heartbeats.</p>
                </div>
                <div class="text-xs font-mono text-[#8b949e]">
                    Checked: {{ metrics.system_health.checked_at[:19].replace('T', ' ') if metrics.system_health else sync_time }} UTC
                </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                {% if metrics.system_health and metrics.system_health.modules %}
                {% for m in metrics.system_health.modules %}
                <div class="p-4 rounded-lg bg-[#1c2128] border border-[#30363d] flex items-start justify-between">
                    <div>
                        <div class="flex items-center gap-2">
                            <span class="w-2.5 h-2.5 rounded-full {% if m.status == 'operational' %}bg-emerald-400 shadow-sm shadow-emerald-400/50{% else %}bg-yellow-400 shadow-sm shadow-yellow-400/50{% endif %}"></span>
                            <span class="font-bold text-sm text-white">{{ m.name }}</span>
                            <span class="text-[10px] px-2 py-0.5 rounded bg-[#2d333b] text-[#8b949e]">{{ m.category }}</span>
                        </div>
                        <p class="text-xs text-[#8b949e] mt-1">{{ m.detail }}</p>
                        <p class="text-[11px] text-[#58a6ff] font-mono mt-0.5">{{ m.target }}</p>
                    </div>
                    <div class="text-right">
                        <span class="px-2 py-0.5 rounded font-black text-[10px] {% if m.status == 'operational' %}bg-emerald-500/20 text-emerald-400 border border-emerald-500/30{% else %}bg-yellow-500/20 text-yellow-400 border border-yellow-500/30{% endif %}">
                            {{ m.status|upper }}
                        </span>
                        {% if m.latency_ms > 0 %}
                        <p class="text-[11px] font-mono text-[#8b949e] mt-1">{{ m.latency_ms }} ms</p>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
                {% endif %}
            </div>
        </div>

        {% endif %}
    </main>

    <footer class="max-w-6xl mx-auto w-full pt-4 border-t border-[#30363d] flex flex-col sm:flex-row justify-between items-center text-xs text-[#8b949e] gap-2">
        <div>PureQuant AI • Public Spot Intelligence & System Terminal</div>
        <div class="flex items-center gap-2">
            <span class="inline-block w-2 h-2 rounded-full {% if error_message %}bg-red-400{% elif is_stale %}bg-yellow-400{% else %}bg-emerald-400{% endif %}"></span>
            <span id="footer-sync-time">Sync: {{ sync_time }} UTC</span>
        </div>
    </footer>

    <script>
        let currentTab = 'active';

        // Pagination & Load More State for Signal History
        let cachedClosedSignals = [];
        let historyCurrentPage = 1;
        const historyPageSize = 20;
        let historyDisplayMode = 'page'; // 'page' or 'loadmore'
        let historyLoadedCount = 20;

        function renderHistoryTable() {
            const tbody = document.getElementById('history-signals-tbody');
            if (!tbody || !cachedClosedSignals || cachedClosedSignals.length === 0) return;

            const total = cachedClosedSignals.length;
            const totalPages = Math.ceil(total / historyPageSize) || 1;

            let displaySignals = [];
            let rangeStart = 1;
            let rangeEnd = 20;

            if (historyDisplayMode === 'loadmore') {
                if (historyLoadedCount > total) historyLoadedCount = total;
                displaySignals = cachedClosedSignals.slice(0, historyLoadedCount);
                rangeStart = 1;
                rangeEnd = displaySignals.length;
            } else {
                if (historyCurrentPage > totalPages) historyCurrentPage = totalPages;
                if (historyCurrentPage < 1) historyCurrentPage = 1;
                const startIdx = (historyCurrentPage - 1) * historyPageSize;
                const endIdx = startIdx + historyPageSize;
                displaySignals = cachedClosedSignals.slice(startIdx, endIdx);
                rangeStart = total > 0 ? startIdx + 1 : 0;
                rangeEnd = Math.min(endIdx, total);
            }

            let rows = '';
            displaySignals.forEach(t => {
                const dirBg = (t.direction === 'BUY' || t.direction === 'LONG') ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400';
                const statusBg = (t.status && t.status.includes('WIN')) ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400';
                const pnlClass = t.pnl_pct > 0 ? 'text-emerald-400' : (t.pnl_pct < 0 ? 'text-red-400' : 'text-[#8b949e]');
                const pnlSign = t.pnl_pct > 0 ? '+' : '';

                rows += `<tr class="hover:bg-[#1c2128] transition-colors">
                    <td class="p-3 font-bold text-white">${t.pair}</td>
                    <td class="p-3"><span class="px-2 py-0.5 rounded font-black text-[10px] ${dirBg}">${t.direction}</span></td>
                    <td class="p-3"><span class="px-2 py-0.5 rounded font-black text-[10px] ${statusBg}">${t.status}</span></td>
                    <td class="p-3 font-mono font-bold ${pnlClass}">${pnlSign}${Number(t.pnl_pct).toFixed(2)}%</td>
                    <td class="p-3 font-mono text-[#8b949e]">$${t.entry_price}</td>
                    <td class="p-3 font-mono text-white">$${t.exit_price}</td>
                    <td class="p-3 text-[#8b949e] font-mono text-[11px]">${t.exit_time}</td>
                </tr>`;
            });
            tbody.innerHTML = rows;

            // Update range counters
            const rangeEl = document.getElementById('history-showing-range');
            if (rangeEl) rangeEl.innerText = `${rangeStart}-${rangeEnd}`;
            const totalEl = document.getElementById('history-total-count');
            if (totalEl) totalEl.innerText = total;
            const badgeEl = document.getElementById('badge-history-count');
            if (badgeEl) badgeEl.innerText = `${rangeEnd - rangeStart + 1} of ${total}`;

            // Update Pagination buttons & indicator
            const prevBtn = document.getElementById('btn-history-prev');
            const nextBtn = document.getElementById('btn-history-next');
            const pageInd = document.getElementById('history-page-indicator');
            const loadMoreBtn = document.getElementById('btn-history-loadmore');

            if (pageInd) {
                pageInd.innerText = historyDisplayMode === 'loadmore' 
                    ? `Showing ${displaySignals.length} of ${total}` 
                    : `Page ${historyCurrentPage} of ${totalPages}`;
            }

            if (prevBtn) prevBtn.disabled = (historyCurrentPage <= 1 || historyDisplayMode === 'loadmore');
            if (nextBtn) nextBtn.disabled = (historyCurrentPage >= totalPages || historyDisplayMode === 'loadmore');
            if (loadMoreBtn) {
                loadMoreBtn.disabled = (rangeEnd >= total);
                loadMoreBtn.style.opacity = (rangeEnd >= total) ? '0.3' : '1';
                loadMoreBtn.innerText = (rangeEnd >= total) ? 'All Loaded' : 'Load More (+20)';
            }
        }

        function nextHistoryPage() {
            historyDisplayMode = 'page';
            historyCurrentPage++;
            renderHistoryTable();
        }

        function prevHistoryPage() {
            historyDisplayMode = 'page';
            if (historyCurrentPage > 1) {
                historyCurrentPage--;
                renderHistoryTable();
            }
        }

        function loadMoreHistory() {
            historyDisplayMode = 'loadmore';
            historyLoadedCount += 20;
            renderHistoryTable();
        }

        function switchTab(tabName) {
            currentTab = tabName;
            const tabs = ['active', 'history', 'health'];
            tabs.forEach(t => {
                const content = document.getElementById("tab-content-" + t);
                const btn = document.getElementById("tab-btn-" + t);
                if (content && btn) {
                    if (t === tabName) {
                        content.classList.remove('hidden');
                        btn.classList.add('active');
                    } else {
                        content.classList.add('hidden');
                        btn.classList.remove('active');
                    }
                }
            });
        }

        async function fetchMetricsAndUpdate() {
            try {
                const res = await fetch('/api/public/metrics');
                if (!res.ok) return;
                const data = await res.json();
                updateUI(data);
            } catch (err) {
                console.debug("Telemetry sync pending...", err);
            }
        }

        function updateUI(data) {
            if (!data) return;

            // Update top metric values if present
            const netEl = document.getElementById('metric-net-return');
            if (netEl && data.net_return_pct !== undefined) {
                netEl.innerText = (data.net_return_pct >= 0 ? '+' : '') + Number(data.net_return_pct).toFixed(2) + '%';
            }
            const winEl = document.getElementById('metric-win-rate');
            if (winEl && data.win_rate_pct !== undefined) {
                winEl.innerText = Number(data.win_rate_pct).toFixed(1) + '%';
            }
            const actCountEl = document.getElementById('metric-active-count');
            const actBadgeEl = document.getElementById('badge-active-count');
            if (data.active_signals) {
                if (actCountEl) actCountEl.innerText = data.active_signals.length + ' Ready';
                if (actBadgeEl) actBadgeEl.innerText = data.active_signals.length;
            }
            if (data.closed_signals) {
                cachedClosedSignals = data.closed_signals;
                renderHistoryTable();
            }

            // Update Active Signals Table
            const activeTableBody = document.getElementById('active-signals-tbody');
            const activeEmpty = document.getElementById('active-signals-empty');
            if (activeTableBody) {
                if (data.active_signals && data.active_signals.length > 0) {
                    if (activeEmpty) activeEmpty.classList.add('hidden');
                    activeTableBody.parentElement.parentElement.classList.remove('hidden');
                    let rows = '';
                    data.active_signals.forEach(s => {
                        const dirBg = s.direction === 'LONG' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400';
                        rows += `<tr class="hover:bg-[#1c2128] transition-colors">
                            <td class="p-3 font-bold text-white flex items-center gap-2">
                                <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                                ${s.symbol}
                            </td>
                            <td class="p-3">
                                <span class="px-2 py-0.5 rounded font-black text-[10px] ${dirBg}">
                                    ${s.direction}
                                </span>
                            </td>
                            <td class="p-3 font-mono font-bold text-[#58a6ff]">${Math.round(s.score)}/100</td>
                            <td class="p-3 text-[#8b949e] font-mono">${s.setup || ''}</td>
                            <td class="p-3 font-mono text-white">$${s.entry_reference}</td>
                            <td class="p-3 font-mono text-emerald-400">
                                $${s.tp1} <span class="text-[#8b949e]">|</span> $${s.tp2} <span class="text-[#8b949e]">|</span> $${s.tp3}
                            </td>
                            <td class="p-3 font-mono text-red-400">$${s.stop_loss}</td>
                            <td class="p-3 font-mono text-purple-400">1:${s.risk_reward}</td>
                        </tr>`;
                    });
                    activeTableBody.innerHTML = rows;
                } else {
                    activeTableBody.innerHTML = '';
                    if (activeEmpty) activeEmpty.classList.remove('hidden');
                }
            }

            // Update footer sync time
            const syncTimeEl = document.getElementById('footer-sync-time');
            if (syncTimeEl && data.updated_at) {
                syncTimeEl.innerText = 'Sync: ' + data.updated_at.slice(0, 19).replace('T', ' ') + ' UTC';
            }
        }

        // Initial load of history on page render
        fetchMetricsAndUpdate();
        setInterval(fetchMetricsAndUpdate, 5000);
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    metrics, is_stale, err = load_and_validate_metrics()
    sync_time = str(metrics.get("updated_at", ""))[:19].replace("T", " ") if metrics else "N/A"
    return render_template_string(HTML_TEMPLATE, metrics=metrics, is_stale=is_stale, error_message=err, sync_time=sync_time)

@app.route("/health")
def health():
    metrics, is_stale, err = load_and_validate_metrics()
    status = "healthy" if (metrics and not is_stale) else "degraded" if metrics else "unavailable"
    code = 200 if status in ("healthy", "degraded") else 503
    return jsonify({
        "service": "purequant-public-dashboard",
        "status": status,
        "is_stale": is_stale,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), code

@app.route("/api/public/metrics")
def public_metrics():
    metrics, is_stale, err = load_and_validate_metrics()
    if not metrics:
        return jsonify({
            "status": "error",
            "message": "Performance temporarily unavailable"
        }), 503
    return jsonify(metrics), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8060, debug=False)
