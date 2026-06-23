import yfinance as yf
import pandas as pd
import numpy as np
from dataclasses import dataclass

@dataclass
class AnalisisIndicadores:
    rsi_ok: bool
    macd_ok: bool
    ema_ok: bool
    volumen_ok: bool
    stoch_ok: bool
    confirmaciones: int
    aprobado: bool
    rsi_valor: float
    macd_valor: float
    detalles: str

# Umbrales validados en backtest v5
RSI2_UMBRAL = 8
STK_UMBRAL  = 25


class AnalistaIndicadores:
    """
    Estrategia v5: Mean Reversion con confluencia en sobreventa extrema.
    RSI(2) < 8 + Stochastic < 25 + MACD negativo + Volumen > media.
    Dirección siempre LONG (compra en caída dentro de tendencia alcista).
    """
    MINIMO_CONFIRMACIONES = 4  # todas deben cumplirse

    def _rsi(self, serie, n=2):
        d = serie.diff()
        g = d.clip(lower=0).rolling(n).mean()
        p = (-d.clip(upper=0)).rolling(n).mean()
        rs = g / p.replace(0, np.nan)
        return round(float((100 - 100 / (1 + rs)).iloc[-1]), 2)

    def _macd_hist(self, serie, fast=12, slow=26, sig=9):
        m = serie.ewm(span=fast).mean() - serie.ewm(span=slow).mean()
        h = m - m.ewm(span=sig).mean()
        return round(float(m.iloc[-1]), 4), round(float(h.iloc[-1]), 4)

    def _stoch_k(self, df, k=14):
        low_k  = df["Low"].rolling(k).min()
        high_k = df["High"].rolling(k).max()
        pct    = 100 * (df["Close"] - low_k) / (high_k - low_k).replace(0, np.nan)
        return round(float(pct.iloc[-1]), 2)

    def analizar(self, ticker, direccion="long"):
        try:
            df = yf.download(ticker, period="60d", interval="1d",
                             progress=False, auto_adjust=True)
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df = df.dropna()
        except Exception as e:
            return AnalisisIndicadores(False, False, False, False, False, 0, False, 0, 0, f"Error: {e}")

        if len(df) < 30:
            return AnalisisIndicadores(False, False, False, False, False, 0, False, 0, 0, "Datos insuficientes")

        rsi   = self._rsi(df["Close"], 2)
        macd_v, hist_v = self._macd_hist(df["Close"])
        stk   = self._stoch_k(df)

        df2     = df.copy()
        df2["e9"]  = df2["Close"].ewm(span=9).mean()
        df2["e21"] = df2["Close"].ewm(span=21).mean()
        df2["e50"] = df2["Close"].ewm(span=50).mean()
        precio  = float(df2["Close"].iloc[-1])
        e9, e21, e50 = float(df2["e9"].iloc[-1]), float(df2["e21"].iloc[-1]), float(df2["e50"].iloc[-1])

        # Señales de sobreventa extrema en uptrend
        rsi_ok  = rsi < RSI2_UMBRAL
        stk_ok  = stk < STK_UMBRAL
        macd_ok = hist_v < 0               # negativo = caída real, mejor rebote
        ema_ok  = precio > e9 or precio > e21  # aún dentro de estructura alcista
        vol_ok  = float(df["Volume"].iloc[-1]) > float(df["Volume"].tail(20).mean())

        confs = sum([rsi_ok, stk_ok, macd_ok, ema_ok, vol_ok])
        detalles = (
            f"RSI2:{rsi}({'✓' if rsi_ok else '✗'}) "
            f"Stoch:{stk}({'✓' if stk_ok else '✗'}) "
            f"MACD_h:{hist_v}({'✓' if macd_ok else '✗'}) "
            f"EMA({'✓' if ema_ok else '✗'}) "
            f"Vol({'✓' if vol_ok else '✗'})"
        )
        return AnalisisIndicadores(
            rsi_ok, macd_ok, ema_ok, vol_ok, stk_ok,
            confs, confs >= self.MINIMO_CONFIRMACIONES,
            rsi, macd_v, detalles
        )
