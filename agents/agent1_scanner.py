import json
import os
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List

BASE   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAMS = os.path.join(BASE, "params_live.json")

def _cargar_params():
    if os.path.exists(PARAMS):
        with open(PARAMS) as f:
            return json.load(f)
    return {}

@dataclass
class Patron:
    tipo: str
    direccion: str
    fuerza: float
    precio_actual: float
    soporte: float
    resistencia: float
    descripcion: str
    ticker: str
    timeframe: str
    timestamp: str

# Activos v6 — cargados desde params_live.json (Cerebro los ajusta dinámicamente)
def _get_tickers() -> List[str]:
    p = _cargar_params()
    activos = p.get("activos", {})
    todos = (
        activos.get("acciones", []) +
        activos.get("indices", []) +
        activos.get("commodities", []) +
        activos.get("crypto", [])
    )
    return todos if todos else ["NVDA", "TSLA", "AMZN", "SPY", "GLD"]

def _get_umbral_rsi2() -> float:
    return _cargar_params().get("umbrales", {}).get("rsi2_entrada", 8.0)

def _get_umbral_stoch() -> float:
    return _cargar_params().get("umbrales", {}).get("stoch_entrada", 25.0)

ACCIONES = ["NVDA", "TSLA", "AMZN", "SPY", "GLD"]
CRYPTO   = []


class ScannerPatrones:
    def __init__(self):
        # Recarga activos y umbrales en cada ciclo (el Cerebro los puede haber actualizado)
        self.tickers    = _get_tickers()
        self.rsi2_umbral = _get_umbral_rsi2()
        self.stk_umbral  = _get_umbral_stoch()

    def obtener_datos(self, ticker, periodo="60d", intervalo="1d"):
        try:
            df = yf.download(ticker, period=periodo, interval=intervalo,
                             progress=False, auto_adjust=True)
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df = df.dropna()
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            return df
        except Exception as e:
            return pd.DataFrame()

    def _rsi(self, serie, n=2):
        d = serie.diff()
        g = d.clip(lower=0).rolling(n).mean()
        p = (-d.clip(upper=0)).rolling(n).mean()
        return 100 - (100 / (1 + g / p.replace(0, np.nan)))

    def _stoch_k(self, df, k=14):
        low_k  = df["Low"].rolling(k).min()
        high_k = df["High"].rolling(k).max()
        return 100 * (df["Close"] - low_k) / (high_k - low_k).replace(0, np.nan)

    def _macd_hist(self, serie, fast=12, slow=26, sig=9):
        m = serie.ewm(span=fast, adjust=False).mean() - serie.ewm(span=slow, adjust=False).mean()
        return m - m.ewm(span=sig, adjust=False).mean()

    def obtener_filtro_mercado(self, ticker):
        """SPY para acciones, BTC-USD para crypto — filtro de mercado sano."""
        filtro_ticker = "SPY" if ticker in ACCIONES else "BTC-USD"
        df = self.obtener_datos(filtro_ticker, periodo="400d")
        if df.empty:
            return None
        df["mm200"] = df["Close"].rolling(200).mean()
        return df.dropna()

    def escanear_ticker(self, ticker):
        df = self.obtener_datos(ticker, periodo="400d")
        if df.empty or len(df) < 220:
            return None

        df = df.copy()
        df["mm50"]   = df["Close"].rolling(50).mean()
        df["mm200"]  = df["Close"].rolling(200).mean()
        df["rsi2"]   = self._rsi(df["Close"], 2)
        df["stk_k"]  = self._stoch_k(df)
        df["macd_h"] = self._macd_hist(df["Close"])
        df["vol_med"] = df["Volume"].rolling(20).mean()
        df = df.dropna()

        if len(df) < 5:
            return None

        row = df.iloc[-1]
        precio  = float(row["Close"])
        mm50    = float(row["mm50"])
        mm200   = float(row["mm200"])
        rsi2    = float(row["rsi2"])
        stk_k   = float(row["stk_k"])
        macd_h  = float(row["macd_h"])
        vol     = float(row["Volume"])
        vol_med = float(row["vol_med"])

        # F1: Mercado sano
        filtro_df = self.obtener_filtro_mercado(ticker)
        if filtro_df is None or filtro_df.empty:
            return None
        f_row   = filtro_df.iloc[-1]
        f_mm200 = float(f_row["mm200"])
        f_precio = float(f_row["Close"])
        if pd.isna(f_mm200) or f_precio < f_mm200:
            return None

        # F2: Tendencia activo
        if pd.isna(mm50) or pd.isna(mm200):
            return None
        if precio <= mm200 or precio <= mm50 or mm50 <= mm200:
            return None

        # F3: RSI(2) sobreventa extrema — umbral ajustado por Cerebro
        if pd.isna(rsi2) or rsi2 >= self.rsi2_umbral:
            return None

        # F4: Stochastic sobreventa — umbral ajustado por Cerebro
        if pd.isna(stk_k) or stk_k >= self.stk_umbral:
            return None

        # F5: MACD histograma negativo
        if pd.isna(macd_h) or macd_h >= 0:
            return None

        # F6: Volumen > media
        if vol_med == 0 or vol < vol_med:
            return None

        fuerza = round(min(1.0, 0.3 + (self.rsi2_umbral - rsi2) / self.rsi2_umbral * 0.4 +
                           (self.stk_umbral - stk_k) / self.stk_umbral * 0.3), 2)

        soporte     = round(float(df["Low"].tail(20).min()), 2)
        resistencia = round(float(df["High"].tail(20).max()), 2)

        return Patron(
            tipo="confluencia_v5",
            direccion="long",
            fuerza=fuerza,
            precio_actual=round(precio, 2),
            soporte=soporte,
            resistencia=resistencia,
            descripcion=f"RSI2={rsi2:.1f} Stoch={stk_k:.1f} MACD_h={macd_h:.4f} Vol>med",
            ticker=ticker,
            timeframe="1d",
            timestamp=datetime.now().isoformat()
        )

    def escanear_todos(self):
        resultados = []
        for t in self.tickers:
            p = self.escanear_ticker(t)
            if p:
                resultados.append(p)
        return resultados
