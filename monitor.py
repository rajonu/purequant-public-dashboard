"""Read-only paper monitor for public PureQuant signals and Binance spot prices."""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SCANNER_URL = os.getenv(
    "SCANNER_SIGNALS_URL",
    "https://scanner.purequantai.xyz/api/v2/signals?actionable=true",
)
BINANCE_BASE_URL = os.getenv("BINANCE_BASE_URL", "https://data-api.binance.vision")
STATE_PATH = Path(os.getenv("PAPER_MONITOR_STATE_PATH", "/app/monitoring/paper_trades.json"))
POLL_SECONDS = max(5, int(os.getenv("PAPER_MONITOR_POLL_SECONDS", "15")))
FEE_PER_SIDE_PCT = max(0.0, float(os.getenv("PAPER_FEE_PERCENT_PER_SIDE", "0.1")))
MAX_TRADE_HOURS = max(1.0, float(os.getenv("PAPER_MAX_TRADE_HOURS", "8")))
USER_AGENT = "PureQuantPublicDashboardPaperMonitor/1.0"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def request_json(url, timeout=10):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def empty_state():
    return {
        "updated_at": None,
        "scanner_state": "disconnected",
        "scanner_error": None,
        "scanner_generated_at": None,
        "signals": [],
        "watchlist": [],
        "active_trades": [],
        "history": [],
        "fee_per_side_pct": FEE_PER_SIDE_PCT,
        "monitor_state": "starting",
        "monitor_error": None,
    }


def read_state():
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            base = empty_state()
            base.update(data)
            return base
    except (OSError, json.JSONDecodeError):
        pass
    return empty_state()


def write_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def parse_time_ms(value):
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError):
        return 0


def binance_symbol(signal):
    symbol = str(signal.get("symbol", "")).upper().replace("/", "")
    return symbol if symbol.endswith("USDT") else ""


def trade_plan(signal):
    plan = signal.get("trade_plan") or {}
    values = [plan.get(k) for k in ("entry_reference", "stop_loss", "tp1", "tp2", "tp3")]
    try:
        entry, stop, tp1, tp2, tp3 = map(float, values)
    except (TypeError, ValueError):
        return None
    direction = str(signal.get("direction") or plan.get("direction") or "LONG").upper()
    if direction not in ("LONG", "SHORT") or min(entry, stop, tp1, tp2, tp3) <= 0:
        return None
    return {"entry": entry, "initial_stop": stop, "tp1": tp1, "tp2": tp2, "tp3": tp3, "direction": direction}


def fetch_scanner():
    data = request_json(SCANNER_URL, timeout=12)
    signals = data.get("signals") if isinstance(data, dict) else None
    if not isinstance(signals, list):
        raise ValueError("Scanner response is missing its signals list")
    return data, [s for s in signals if isinstance(s, dict) and s.get("signal_id") and trade_plan(s)]


def fetch_prices(symbols=None):
    if symbols:
        # Request only monitored pairs to reduce payload and surface missing symbols clearly.
        with ThreadPoolExecutor(max_workers=min(32, len(symbols))) as pool:
            futures = {pool.submit(request_json, f"{BINANCE_BASE_URL}/api/v3/ticker/price?symbol={symbol}", 5): symbol for symbol in symbols}
            prices = {}
            errors = {}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    row = future.result()
                    prices[symbol] = float(row["price"])
                except Exception as exc:
                    errors[symbol] = str(exc)[:240]
            return prices, errors
    rows = request_json(f"{BINANCE_BASE_URL}/api/v3/ticker/price", timeout=10)
    return {r["symbol"]: float(r["price"]) for r in rows if isinstance(r, dict) and r.get("symbol") and r.get("price")}, {}


def fetch_candle_map(symbol_starts):
    """Fetch each unique symbol once per cycle, even when many signals share it."""
    results = {}
    errors = {}
    if not symbol_starts:
        return results, {}
    with ThreadPoolExecutor(max_workers=min(32, len(symbol_starts))) as pool:
        futures = {pool.submit(fetch_candles, symbol, start): symbol for symbol, start in symbol_starts.items()}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                results[symbol] = future.result()
            except Exception as exc:
                results[symbol] = []
                error = str(exc)[:240]
                # Return per-symbol errors so one unavailable pair does not hide healthy prices.
                errors[symbol] = error
    return results, errors


def fetch_candles(symbol, start_ms):
    query = urlencode({"symbol": symbol, "interval": "1m", "startTime": max(0, start_ms), "limit": 100})
    rows = request_json(f"{BINANCE_BASE_URL}/api/v3/klines?{query}", timeout=5)
    return rows if isinstance(rows, list) else []


def pct_return(direction, entry, price):
    raw = ((price - entry) / entry) * 100
    return raw if direction == "LONG" else -raw


def close_trade(state, trade, status, exit_price, timestamp):
    plan = trade["plan"]
    gross = pct_return(plan["direction"], plan["entry"], exit_price)
    net = gross - (2 * FEE_PER_SIDE_PCT)
    state["history"].insert(0, {
        "signal_id": trade["signal_id"],
        "pair": trade["symbol"],
        "direction": "BUY" if plan["direction"] == "LONG" else "SELL",
        "status": status,
        "pnl_pct": round(net, 4),
        "gross_pnl_pct": round(gross, 4),
        "entry_price": plan["entry"],
        "exit_price": round(float(exit_price), 12),
        "exit_time": timestamp,
    })
    state["history"] = state["history"][:100]


def close_unfilled(state, watch, timestamp):
    state["history"].insert(0, {
        "signal_id": watch["signal_id"],
        "pair": watch["symbol"],
        "direction": "BUY" if watch["plan"]["direction"] == "LONG" else "SELL",
        "status": "NOT ENTERED",
        "pnl_pct": 0.0,
        "gross_pnl_pct": 0.0,
        "entry_price": watch["plan"]["entry"],
        "exit_price": None,
        "exit_time": timestamp,
    })
    state["history"] = state["history"][:100]


def candle_level_hits(trade, high, low):
    plan = trade["plan"]
    long_side = plan["direction"] == "LONG"
    stop = float(trade.get("stop_price", plan["initial_stop"]))
    stop_hit = low <= stop if long_side else high >= stop
    targets = [plan["tp1"], plan["tp2"], plan["tp3"]]
    hit_targets = [t for t in targets if (high >= t if long_side else low <= t)]
    return stop_hit, hit_targets


def process_trade_candle(state, trade, candle, is_new_entry=False):
    open_ms, _, high_s, low_s, close_s, _, close_ms = candle[:7]
    high, low, close = float(high_s), float(low_s), float(close_s)
    timestamp = datetime.fromtimestamp(int(close_ms) / 1000, timezone.utc).isoformat()
    stop_hit, targets = candle_level_hits(trade, high, low)
    plan = trade["plan"]
    breakeven_armed = bool(trade.get("breakeven_armed"))

    # If one minute candle crosses both sides, record the adverse side first.
    if stop_hit:
        stop_price = float(trade.get("stop_price", plan["initial_stop"]))
        status = "BREAKEVEN" if breakeven_armed and abs(stop_price - plan["entry"]) < 1e-12 else "SL"
        close_trade(state, trade, status, stop_price, timestamp)
        return "closed"

    if 0 in targets and not breakeven_armed:
        trade["breakeven_armed"] = True
        trade["stop_price"] = plan["entry"]
        breakeven_armed = True
        # If the same one-minute bar also returned to entry, use the conservative
        # break-even exit because the order of those touches cannot be known.
        returned_to_entry = low <= plan["entry"] if plan["direction"] == "LONG" else high >= plan["entry"]
        if returned_to_entry:
            close_trade(state, trade, "BREAKEVEN", plan["entry"], timestamp)
            return "closed"

    if 1 in targets:
        trade["tp2_reached"] = True

    if 2 in targets:
        close_trade(state, trade, "TP", plan["tp3"], timestamp)
        return "closed"

    trade["current_price"] = close
    trade["live_gross_pnl_pct"] = round(pct_return(plan["direction"], plan["entry"], close), 4)
    trade["live_net_pnl_pct"] = round(trade["live_gross_pnl_pct"] - 2 * FEE_PER_SIDE_PCT, 4)
    trade["last_bar_open_ms"] = int(open_ms)
    trade["last_price_at"] = timestamp
    return "open"


def run_cycle(state):
    now = now_iso()
    scanner_ok = False
    try:
        payload, signals = fetch_scanner()
        state["signals"] = signals
        state["scanner_state"] = "connected"
        state["scanner_error"] = None
        state["scanner_generated_at"] = payload.get("generated_at")
        state["scanner_last_success_at"] = now
        scanner_ok = True
    except Exception as exc:
        state["scanner_state"] = "degraded" if state.get("scanner_last_success_at") else "disconnected"
        state["scanner_error"] = str(exc)[:240]
        signals = state.get("signals", [])

    # A scanner can emit a fresh signal_id every minute for the same market.
    # Paper monitoring therefore keeps only the oldest open entry per symbol.
    active = {}
    active_symbols = set()
    for trade in sorted(state.get("active_trades", []), key=lambda t: t.get("opened_at", "")):
        sid = trade.get("signal_id")
        symbol = binance_symbol(trade.get("signal") or {"symbol": trade.get("symbol", "")})
        if sid and symbol and symbol not in active_symbols:
            active[sid] = trade
            active_symbols.add(symbol)

    watchlist = {}
    watched_symbols = set()
    for watch in sorted(state.get("watchlist", []), key=lambda w: w.get("created_at", "")):
        sid = watch.get("signal_id")
        symbol = binance_symbol(watch.get("signal") or {"symbol": watch.get("symbol", "")})
        if sid and symbol and symbol not in active_symbols and symbol not in watched_symbols:
            watchlist[sid] = watch
            watched_symbols.add(symbol)
    closed_ids = {h["signal_id"] for h in state.get("history", [])}

    for signal in signals:
        sid = signal["signal_id"]
        if sid in watchlist or sid in active or sid in closed_ids:
            if sid in watchlist:
                watchlist[sid]["signal"] = signal
            continue
        symbol = binance_symbol(signal)
        if symbol and (symbol in active_symbols or symbol in watched_symbols):
            continue
        timing = signal.get("timing") or {}
        created_ms = parse_time_ms(timing.get("created_at")) or int(time.time() * 1000)
        # Ignore the signal's partial creation minute so earlier price action cannot count as an entry.
        first_full_bar = ((created_ms // 60000) + 1) * 60000
        watchlist[sid] = {
            "signal_id": sid,
            "symbol": signal.get("symbol", ""),
            "signal": signal,
            "plan": trade_plan(signal),
            "expires_at": timing.get("expires_at"),
            "created_at": timing.get("created_at") or now,
            "first_full_bar_ms": first_full_bar,
            "last_bar_open_ms": first_full_bar - 60000,
        }
        if symbol:
            watched_symbols.add(symbol)

    needed = {binance_symbol(w["signal"]) for w in watchlist.values()}
    needed.update(binance_symbol(t["signal"]) for t in active.values())
    needed.discard("")
    prices = {}
    try:
        prices, price_errors = fetch_prices(sorted(needed))
        if price_errors:
            state["market_state"] = "degraded"
            state["market_error"] = next(iter(price_errors.values()))
        else:
            state["market_state"] = "connected"
            state["market_error"] = None
        if prices:
            state["market_last_success_at"] = now
    except Exception as exc:
        state["market_state"] = "degraded" if state.get("market_last_success_at") else "disconnected"
        state["market_error"] = str(exc)[:240]

    symbol_starts = {}
    for watch in watchlist.values():
        symbol = binance_symbol(watch["signal"])
        if symbol:
            start = int(watch["last_bar_open_ms"]) + 60000
            symbol_starts[symbol] = min(start, symbol_starts.get(symbol, start))
    for trade in active.values():
        symbol = binance_symbol(trade["signal"])
        if symbol:
            start = int(trade["last_bar_open_ms"]) + 60000
            symbol_starts[symbol] = min(start, symbol_starts.get(symbol, start))
    errors = {}
    candle_map, errors = fetch_candle_map(symbol_starts)
    if errors:
        state["market_state"] = "degraded"
        state["market_error"] = next(iter(errors.values()))
    elif candle_map or prices:
        state["market_state"] = "connected"
        state["market_error"] = None
        state["market_last_success_at"] = now

    for sid, watch in list(watchlist.items()):
        symbol = binance_symbol(watch["signal"])
        plan = watch["plan"]
        candles = candle_map.get(symbol, [])

        for candle in candles:
            open_ms = int(candle[0])
            close_ms = int(candle[6])
            if open_ms < int(watch["first_full_bar_ms"]) or close_ms > int(time.time() * 1000):
                continue
            high, low, close = float(candle[2]), float(candle[3]), float(candle[4])
            entry = plan["entry"]
            touched = low <= entry <= high
            watch["last_bar_open_ms"] = open_ms
            if not touched:
                continue

            signal = watch["signal"]
            trade = {
                "signal_id": sid,
                "symbol": watch["symbol"],
                "signal": signal,
                "plan": plan,
                "opened_at": datetime.fromtimestamp(open_ms / 1000, timezone.utc).isoformat(),
                "current_price": prices.get(symbol, close),
                "stop_price": plan["initial_stop"],
                "breakeven_armed": False,
                "tp2_reached": False,
                "last_bar_open_ms": open_ms,
            }
            active[sid] = trade
            active_symbols.add(symbol)
            del watchlist[sid]
            outcome = process_trade_candle(state, trade, candle, is_new_entry=True)
            if outcome == "closed":
                del active[sid]
            break

        if sid in watchlist and watch["expires_at"] and parse_time_ms(watch["expires_at"]) <= int(time.time() * 1000):
            close_unfilled(state, watch, now)
            del watchlist[sid]

    for sid, trade in list(active.items()):
        symbol = binance_symbol(trade["signal"])
        candles = candle_map.get(symbol, [])
        closed = False
        for candle in candles:
            if int(candle[0]) <= int(trade["last_bar_open_ms"]) or int(candle[6]) > int(time.time() * 1000):
                continue
            if process_trade_candle(state, trade, candle) == "closed":
                del active[sid]
                closed = True
                break
        if closed:
            continue
        opened_ms = parse_time_ms(trade.get("opened_at"))
        age_ms = int(time.time() * 1000) - opened_ms if opened_ms else 0
        if age_ms >= MAX_TRADE_HOURS * 60 * 60 * 1000:
            # Time exits require a recent market observation; never close at an old quote.
            last_price_ms = parse_time_ms(trade.get("last_price_at"))
            has_fresh_price = symbol in prices
            has_fresh_candle = int(time.time() * 1000) - int(trade.get("last_bar_open_ms", 0)) <= 5 * 60 * 1000
            if has_fresh_price:
                exit_price = prices[symbol]
                exit_time = now
            elif has_fresh_candle:
                exit_price = float(trade.get("current_price", 0))
                exit_time = trade.get("last_price_at") or now
            else:
                exit_price = None
            if exit_price and (has_fresh_price or (last_price_ms and int(time.time() * 1000) - last_price_ms <= 5 * 60 * 1000)):
                close_trade(state, trade, "TIMEOUT", exit_price, exit_time)
                del active[sid]
                continue
        if symbol in prices:
            current = prices[symbol]
            trade["current_price"] = current
            gross = pct_return(trade["plan"]["direction"], trade["plan"]["entry"], current)
            trade["live_gross_pnl_pct"] = round(gross, 4)
            trade["live_net_pnl_pct"] = round(gross - 2 * FEE_PER_SIDE_PCT, 4)
            trade["last_price_at"] = now

    state["watchlist"] = list(watchlist.values())
    state["active_trades"] = list(active.values())
    state["updated_at"] = now
    state["monitor_state"] = "running"
    state["monitor_error"] = None
    state["fee_per_side_pct"] = FEE_PER_SIDE_PCT
    return state


def main():
    state = read_state()
    while True:
        try:
            state = run_cycle(state)
            write_state(state)
        except Exception as exc:
            state["monitor_state"] = "degraded"
            state["monitor_error"] = str(exc)[:240]
            state["updated_at"] = now_iso()
            try:
                write_state(state)
            except OSError:
                pass
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
