"""Broker virtual persistente SQLite. Nunca transmite órdenes a un bróker."""
import json, sqlite3, time
from pathlib import Path

DB_PATH = Path(__file__).with_name("paper_trading.sqlite3")

class PaperBroker:
    def __init__(self, initial_cash=500.0, commission=0.001, slippage=0.001, db_path=DB_PATH):
        self.db_path = str(db_path)
        self.commission, self.slippage = commission, slippage
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), cash REAL, initial_cash REAL)")
            db.execute("CREATE TABLE IF NOT EXISTS positions (ticker TEXT PRIMARY KEY, units REAL, entry REAL, stop REAL, target REAL, entry_fee REAL, opened TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, ticker TEXT, side TEXT, units REAL, price REAL, fee REAL, pnl REAL, reason TEXT)")
            row = db.execute("SELECT id FROM state WHERE id=1").fetchone()
            if row is None:
                db.execute("INSERT INTO state VALUES (1, ?, ?)", (initial_cash, initial_cash))
    def _db(self): return sqlite3.connect(self.db_path)
    def state(self):
        with self._db() as db:
            cash, initial = db.execute("SELECT cash, initial_cash FROM state WHERE id=1").fetchone()
            positions = db.execute("SELECT ticker, units, entry, stop, target, entry_fee, opened FROM positions").fetchall()
            trades = db.execute("SELECT ts,ticker,side,units,price,fee,pnl,reason FROM trades ORDER BY id DESC LIMIT 200").fetchall()
        return {"cash":cash,"initial_cash":initial,"positions":positions,"trades":trades}
    def buy(self, ticker, price, atr, equity, risk_fraction=.01, max_position_fraction=.30, max_positions=4):
        if price <= 0 or atr <= 0: return False, "Precio/ATR inválido"
        with self._db() as db:
            cash, initial = db.execute("SELECT cash,initial_cash FROM state WHERE id=1").fetchone()
            if db.execute("SELECT 1 FROM positions WHERE ticker=?",(ticker,)).fetchone(): return False,"Ya existe posición"
            count = db.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
            if count >= max_positions: return False,"Máximo de posiciones alcanzado"
            fill = price * (1+self.slippage); stop = fill - 2*atr; target = fill + 6*atr
            risk_units = equity*risk_fraction/(fill-stop)
            cap_units = equity*max_position_fraction/fill
            cash_units = cash/(fill*(1+self.commission))
            units = min(risk_units,cap_units,cash_units)
            if units*fill < 5: return False,"Posición demasiado pequeña"
            fee = units*fill*self.commission
            db.execute("UPDATE state SET cash=cash-? WHERE id=1",(units*fill+fee,))
            db.execute("INSERT INTO positions VALUES (?,?,?,?,?,?,datetime('now'))",(ticker,units,fill,stop,target,fee))
            db.execute("INSERT INTO trades(ts,ticker,side,units,price,fee,pnl,reason) VALUES(datetime('now'),?,?,?,?,?,?,?)",(ticker,"BUY",units,fill,fee,0,"signal"))
            return True, f"Compra virtual {ticker}: {units:.6f} unidades"
    def sell(self,ticker,price,reason="signal"):
        with self._db() as db:
            row=db.execute("SELECT units,entry,entry_fee FROM positions WHERE ticker=?",(ticker,)).fetchone()
            if not row: return False,"No hay posición"
            units,entry,entry_fee=row; fill=price*(1-self.slippage); gross=units*fill; fee=gross*self.commission
            pnl=(fill-entry)*units-entry_fee-fee
            db.execute("UPDATE state SET cash=cash+? WHERE id=1",(gross-fee,))
            db.execute("DELETE FROM positions WHERE ticker=?",(ticker,))
            db.execute("INSERT INTO trades(ts,ticker,side,units,price,fee,pnl,reason) VALUES(datetime('now'),?,?,?,?,?,?,?)",(ticker,"SELL",units,fill,fee,pnl,reason))
            return True,f"Venta virtual {ticker}: P/L neto {pnl:.2f} € ({reason})"
    def reset(self, initial_cash=500):
        with self._db() as db:
            db.execute("DELETE FROM positions"); db.execute("DELETE FROM trades")
            db.execute("UPDATE state SET cash=?,initial_cash=? WHERE id=1",(initial_cash,initial_cash))
