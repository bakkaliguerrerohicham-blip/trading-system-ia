import json, os
import yfinance as yf
import numpy as np
from datetime import datetime, date
from dataclasses import dataclass
from typing import Optional

@dataclass
class OrdenCalculada:
    ticker: str
    direccion: str
    precio_entrada: float
    stop_loss: float
    take_profit: float
    tamano_posicion: float
    capital_en_riesgo: float
    ratio: float
    aprobado: bool
    razon_bloqueo: Optional[str]
    timestamp: str


class GestorRiesgo:
    # Parámetros validados en backtest v5
    RIESGO      = 0.01   # 1% capital por operación
    RATIO       = 4.0    # TP = 4×SL — validado en backtest
    ATR_MULT_SL = 1.5    # SL = 1.5×ATR(14)
    MAX_SL_PCT  = 0.08   # SL máximo: 8% del precio
    MAX_POS     = 2      # máximo 2 posiciones simultáneas
    MAX_MES_PCT = 0.07   # circuit breaker: -7% del capital en el mes

    def __init__(self, capital=10000.0, db="/tmp/trading_estado.json"):
        self.capital = capital
        self.db      = db
        self.estado  = self._cargar()

    def _cargar(self):
        if os.path.exists(self.db):
            try:
                with open(self.db) as f:
                    return json.load(f)
            except:
                pass
        return {
            "operaciones_abiertas": 0,
            "perdida_mes": 0.0,
            "mes": str(date.today().year) + "-" + str(date.today().month),
            "historial": []
        }

    def _guardar(self):
        with open(self.db, "w") as f:
            json.dump(self.estado, f, indent=2)

    def _atr14(self, ticker):
        try:
            df = yf.download(ticker, period="60d", interval="1d",
                             progress=False, auto_adjust=True)
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df = df.dropna()
            h, l, c = df["High"], df["Low"], df["Close"].shift(1)
            tr = np.concat([h-l, (h-c).abs(), (l-c).abs()], axis=1).max(axis=1)
            return float(tr.rolling(14).mean().iloc[-1])
        except:
            return None

    def calcular(self, patron, soporte=None, resistencia=None):
        mes_actual = str(date.today().year) + "-" + str(date.today().month)
        if self.estado.get("mes") != mes_actual:
            self.estado["perdida_mes"] = 0.0
            self.estado["mes"]         = mes_actual
            self._guardar()

        # Circuit breaker mensual
        if self.estado["perdida_mes"] >= self.capital * self.MAX_MES_PCT:
            return OrdenCalculada(
                patron.ticker, patron.direccion, patron.precio_actual,
                0, 0, 0, 0, 0, False,
                f"Circuit breaker: -{self.MAX_MES_PCT*100:.0f}% mes alcanzado",
                datetime.now().isoformat()
            )

        # Máximo de posiciones simultáneas
        if self.estado["operaciones_abiertas"] >= self.MAX_POS:
            return OrdenCalculada(
                patron.ticker, patron.direccion, patron.precio_actual,
                0, 0, 0, 0, 0, False,
                f"Máx {self.MAX_POS} posiciones simultáneas",
                datetime.now().isoformat()
            )

        precio = patron.precio_actual

        # SL basado en ATR(14) — igual que en el backtest validado
        atr = self._atr14(patron.ticker)
        if atr is None or atr <= 0:
            return OrdenCalculada(
                patron.ticker, patron.direccion, precio,
                0, 0, 0, 0, 0, False, "ATR no disponible",
                datetime.now().isoformat()
            )

        sl_pct = min(self.ATR_MULT_SL * atr / precio, self.MAX_SL_PCT)
        sl     = round(precio * (1 - sl_pct), 2)
        tp     = round(precio * (1 + sl_pct * self.RATIO), 2)

        dist_sl      = abs(precio - sl)
        riesgo_usd   = self.capital * self.RIESGO
        tamano       = round(riesgo_usd / dist_sl, 4) if dist_sl > 0 else 0
        ratio_real   = round(abs(precio - tp) / dist_sl, 2) if dist_sl > 0 else 0

        if tamano <= 0 or ratio_real < 3.5:
            return OrdenCalculada(
                patron.ticker, patron.direccion, precio, sl, tp, 0, 0, ratio_real,
                False, f"Ratio insuficiente: {ratio_real} (mín 3.5)",
                datetime.now().isoformat()
            )

        return OrdenCalculada(
            patron.ticker, patron.direccion, precio, sl, tp,
            tamano, round(riesgo_usd, 2), ratio_real, True, None,
            datetime.now().isoformat()
        )

    def registrar_apertura(self, orden):
        self.estado["operaciones_abiertas"] += 1
        self._guardar()

    def registrar_cierre(self, ticker, resultado_usd):
        self.estado["operaciones_abiertas"] = max(0, self.estado["operaciones_abiertas"] - 1)
        if resultado_usd < 0:
            self.estado["perdida_mes"] += abs(resultado_usd)
        self._guardar()
