"""Fuentes gratuitas de datos. Yahoo Finance mediante yfinance; solo datos públicos."""
from __future__ import annotations
import pandas as pd
import yfinance as yf

UNIVERSE = {
    "Cripto": ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "ADA-USD", "LINK-USD", "LTC-USD"],
    "Acciones": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "KO", "AMD", "TSLA"],
    "ETF": ["SPY", "QQQ", "IWM", "EFA", "EEM", "GLD", "TLT", "XLK"],
}

def fetch_history(ticker: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    data = yf.download(ticker, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
    if data is None or data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    out = data[cols].copy()
    out.index = pd.to_datetime(out.index)
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    # El universo MVP usa cotizaciones en USD. Convertimos OHLC a EUR usando
    # EURUSD=X (USD por EUR), alineado por fecha, para que el libro virtual sea coherente.
    if ticker != "EURUSD=X":
        try:
            fx = yf.download("EURUSD=X", period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
            if isinstance(fx.columns, pd.MultiIndex):
                fx.columns = fx.columns.get_level_values(0)
            if not fx.empty and "Close" in fx.columns:
                fx.index = pd.to_datetime(fx.index)
                if getattr(fx.index, "tz", None) is not None:
                    fx.index = fx.index.tz_localize(None)
                rate = fx["Close"].reindex(out.index).ffill()
                # Precio EUR = precio USD / (USD por EUR). No se convierte el volumen.
                valid = rate.notna() & (rate > 0)
                out = out.loc[valid].copy()
                rate = rate.loc[valid]
                for col in ["Open", "High", "Low", "Close"]:
                    out[col] = out[col] / rate
        except Exception:
            # No se finge conversión: si FX falla, se devuelve vacío y el escáner lo omitirá.
            return pd.DataFrame()
    return out

def fetch_universe(markets: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
    result = {}
    for market in markets:
        for ticker in UNIVERSE.get(market, []):
            try:
                df = fetch_history(ticker, period=period)
                if not df.empty and len(df) >= 80:
                    result[ticker] = df
            except Exception:
                continue
    return result
