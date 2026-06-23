import yfinance as yf
import os, requests
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

@dataclass
class EstadoTrade:
    ticker: str
    direccion: str
    precio_entrada: float
    stop_loss: float
    take_profit: float
    precio_actual: float
    pnl_actual: float
    estado: str
    accion: str
    motivo: str

class VigianteTrade:
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN","")
    CHAT = os.environ.get("TELEGRAM_CHAT_ID","")

    def telegram(self, msg):
        if not self.TOKEN: return
        try: requests.post(f"https://api.telegram.org/bot{self.TOKEN}/sendMessage", data={"chat_id":self.CHAT,"text":f"📊 {msg}"}, timeout=5)
        except: pass

    def precio_actual(self, ticker):
        try:
            df = yf.download(ticker, period="1d", interval="1m", progress=False, auto_adjust=True)
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            return round(float(df['Close'].iloc[-1]),2) if not df.empty else None
        except: return None

    def vigilar(self, pos):
        ticker, dir, entrada, sl, tp = pos['ticker'], pos['direccion'], pos['precio_entrada'], pos['stop_loss'], pos['take_profit']
        precio = self.precio_actual(ticker)
        if not precio:
            return EstadoTrade(ticker,dir,entrada,sl,tp,entrada,0,"activo","mantener","Sin precio disponible")
        pnl = round(((precio-entrada)/entrada*100) if dir=="long" else ((entrada-precio)/entrada*100), 2)
        if (dir=="long" and precio>=tp) or (dir=="short" and precio<=tp):
            self.telegram(f"✅ TP ALCANZADO {ticker} +{pnl}%")
            return EstadoTrade(ticker,dir,entrada,sl,tp,precio,pnl,"tp_alcanzado","cerrar","Take profit alcanzado")
        if (dir=="long" and precio<=sl) or (dir=="short" and precio>=sl):
            self.telegram(f"🔴 SL ALCANZADO {ticker} {pnl}%")
            return EstadoTrade(ticker,dir,entrada,sl,tp,precio,pnl,"sl_alcanzado","cerrar","Stop loss alcanzado")
        return EstadoTrade(ticker,dir,entrada,sl,tp,precio,pnl,"activo","mantener",f"PnL: {pnl:+.2f}%")

    def vigilar_todas(self, posiciones):
        return [self.vigilar(p) for p in posiciones]
