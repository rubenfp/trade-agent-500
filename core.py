"""Señales y backtesting diario. No envía órdenes reales."""
from __future__ import annotations
import numpy as np
import pandas as pd

DEFAULTS = {
    "initial_cash_eur": 500.0, "risk_per_trade": 0.01,
    "max_open_positions": 4, "max_position_fraction": 0.30,
    "commission_rate": 0.001, "slippage_rate": 0.001,
    "breakout_lookback": 20, "ema_fast": 20, "ema_slow": 50,
    "rsi_period": 14, "atr_period": 14, "stop_atr_multiple": 2.0,
    "reward_risk_target": 3.0, "minimum_score": 70,
    "max_daily_loss_fraction": 0.03, "max_drawdown_fraction": 0.12,
}


def indicators(df: pd.DataFrame, cfg: dict | None = None) -> pd.DataFrame:
    cfg = {**DEFAULTS, **(cfg or {})}
    x = df.copy().dropna(subset=["Open", "High", "Low", "Close"]).sort_index()
    close, high, low = x["Close"], x["High"], x["Low"]
    x["ema_fast"] = close.ewm(span=cfg["ema_fast"], adjust=False).mean()
    x["ema_slow"] = close.ewm(span=cfg["ema_slow"], adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/cfg["rsi_period"], adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/cfg["rsi_period"], adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    x["rsi"] = 100 - (100 / (1 + rs))
    x.loc[(loss == 0) & (gain > 0), "rsi"] = 100.0
    x.loc[(loss == 0) & (gain == 0), "rsi"] = 50.0
    prev_close = close.shift(1)
    tr = pd.concat([(high-low), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    x["atr"] = tr.rolling(cfg["atr_period"]).mean()
    x["breakout_high"] = high.shift(1).rolling(cfg["breakout_lookback"]).max()
    if "Volume" in x and x["Volume"].notna().any():
        x["volume_ratio"] = x["Volume"] / x["Volume"].rolling(20).mean().replace(0, np.nan)
    else:
        x["volume_ratio"] = np.nan
    x["return_20"] = close.pct_change(20)
    x["signal"] = (
        (x["ema_fast"] > x["ema_slow"]) &
        (close > x["ema_slow"]) &
        (close > x["breakout_high"]) &
        x["rsi"].between(50, 70) &
        (x["atr"] > 0)
    )
    # La puntuación es un filtro heurístico, no una probabilidad de ganar.
    trend = ((close / x["ema_slow"] - 1).clip(0, .10) / .10 * 30).fillna(0)
    momentum = ((x["return_20"].clip(0, .20) / .20) * 25).fillna(0)
    vol_score = (x["volume_ratio"].clip(0, 2) / 2 * 20).fillna(10)
    rr_score = pd.Series(15.0, index=x.index)
    cost_score = pd.Series(10.0, index=x.index)
    x["score"] = (trend + momentum + vol_score + rr_score + cost_score).clip(0, 100)
    return x


def make_entry(price: float, atr: float, cash: float, equity: float, cfg: dict | None = None) -> dict | None:
    cfg = {**DEFAULTS, **(cfg or {})}
    if not np.isfinite(price) or not np.isfinite(atr) or price <= 0 or atr <= 0:
        return None
    stop = price - cfg["stop_atr_multiple"] * atr
    risk_per_unit = price - stop
    risk_budget = equity * cfg["risk_per_trade"]
    units_by_risk = risk_budget / risk_per_unit
    units_by_cap = (equity * cfg["max_position_fraction"]) / (price * (1 + cfg["commission_rate"] + cfg["slippage_rate"]))
    units_by_cash = cash / (price * (1 + cfg["commission_rate"] + cfg["slippage_rate"]))
    units = max(0.0, min(units_by_risk, units_by_cap, units_by_cash))
    if units * price < 5:  # evitar posiciones diminutas con costes desproporcionados
        return None
    return {"units": float(units), "entry": float(price), "stop": float(stop),
            "target": float(price + cfg["reward_risk_target"] * risk_per_unit),
            "risk_eur": float(units * risk_per_unit)}


def backtest(df: pd.DataFrame, cfg: dict | None = None) -> dict:
    """Backtest de una serie OHLCV con ejecución al open siguiente y stop/target intradía conservador."""
    cfg = {**DEFAULTS, **(cfg or {})}
    x = indicators(df, cfg).dropna(subset=["atr", "breakout_high", "ema_slow", "rsi"])
    if len(x) < 30:
        return {"equity": pd.Series(dtype=float), "trades": pd.DataFrame(), "metrics": {"error": "No hay suficientes datos"}}
    cash = float(cfg["initial_cash_eur"])
    pos = None
    equity_curve, trades = [], []
    peak = cash
    for i in range(1, len(x)):
        row = x.iloc[i]
        prev = x.iloc[i-1]
        date = x.index[i]
        # La señal se conoce al cierre anterior; entrada en apertura actual.
        if pos:
            exit_price, reason = None, None
            # Stops con gap: si abre por debajo del stop, ejecuta al open (menos slippage).
            if row["Open"] <= pos["stop"]:
                exit_price, reason = float(row["Open"]), "stop_gap"
            elif row["Low"] <= pos["stop"]:
                exit_price, reason = pos["stop"], "stop"
            elif row["High"] >= pos["target"]:
                exit_price, reason = pos["target"], "target"
            elif row["Close"] < row["ema_slow"]:
                exit_price, reason = float(row["Close"]), "trend_exit"
            if exit_price is not None:
                fill = exit_price * (1 - cfg["slippage_rate"])
                gross = pos["units"] * fill
                fee = gross * cfg["commission_rate"]
                cash += gross - fee
                pnl = (fill - pos["entry_fill"]) * pos["units"] - pos["entry_fee"] - fee
                trades.append({"entry_date": pos["date"], "exit_date": date, "entry": pos["entry_fill"],
                               "exit": fill, "units": pos["units"], "pnl_eur": pnl, "reason": reason})
                pos = None
        if pos is None and bool(prev["signal"]) and float(prev["score"]) >= cfg["minimum_score"]:
            price = float(row["Open"])
            plan = make_entry(price, float(prev["atr"]), cash, cash, cfg)
            if plan:
                fill = price * (1 + cfg["slippage_rate"])
                cost = plan["units"] * fill
                fee = cost * cfg["commission_rate"]
                if cost + fee <= cash:
                    cash -= cost + fee
                    pos = {**plan, "units": plan["units"], "entry_fill": fill,
                           "entry_fee": fee, "date": date,
                           # Ajusta stops al precio ejecutado para incorporar slippage.
                           "stop": fill - cfg["stop_atr_multiple"] * float(prev["atr"]),
                           "target": fill + cfg["reward_risk_target"] * cfg["stop_atr_multiple"] * float(prev["atr"])}
        mark = cash + (pos["units"] * float(row["Close"]) if pos else 0)
        peak = max(peak, mark)
        equity_curve.append({"date": date, "equity": mark, "cash": cash,
                             "drawdown": mark / peak - 1 if peak else 0})
    eq = pd.DataFrame(equity_curve).set_index("date")
    t = pd.DataFrame(trades)
    final = float(eq["equity"].iloc[-1]) if len(eq) else cash
    rets = eq["equity"].pct_change().dropna() if len(eq) else pd.Series(dtype=float)
    gross_profit = t.loc[t.pnl_eur > 0, "pnl_eur"].sum() if len(t) else 0
    gross_loss = -t.loc[t.pnl_eur < 0, "pnl_eur"].sum() if len(t) else 0
    metrics = {
        "initial_cash": cfg["initial_cash_eur"], "final_equity": final,
        "net_return_pct": (final / cfg["initial_cash_eur"] - 1) * 100,
        "max_drawdown_pct": float(eq["drawdown"].min() * 100) if len(eq) else 0,
        "trades": int(len(t)), "win_rate_pct": float((t.pnl_eur > 0).mean() * 100) if len(t) else 0,
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0),
        "sharpe_annualized": float(np.sqrt(252) * rets.mean() / rets.std()) if len(rets) > 1 and rets.std() else 0,
    }
    return {"equity": eq, "trades": t, "metrics": metrics}
