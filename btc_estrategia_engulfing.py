"""
Estrategia BTC — Engulfing 31 velas + MACD
Producto a vender: señal algorítmica para Bitcoin

REGLA LONG:
  1. El máximo de las últimas 31 velas forma un nuevo alto
  2. La vela actual deja mecha hacia arriba
  3. El cuerpo de la vela actual ENVUELVE el cuerpo de la anterior (bullish engulfing)
  4. MACD histograma positivo (o cruzando hacia positivo)
  → Entrada en la apertura de la SIGUIENTE vela
  → SL: por debajo de la mecha (mínimo de la vela engulfing)
  → TP: SL × 4 (ratio 4:1)

REGLA SHORT (inversa):
  1. El mínimo de las últimas 31 velas forma un nuevo mínimo
  2. La vela actual deja mecha hacia abajo
  3. El cuerpo de la vela actual ENVUELVE el cuerpo de la anterior (bearish engulfing)
  4. MACD histograma negativo
  → Entrada en SHORT en la apertura de la siguiente vela
  → SL: por encima de la mecha (máximo de la vela engulfing)
  → TP: SL × 4
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────
#  PARÁMETROS
# ─────────────────────────────────────────────────────────────────────
TICKER        = "BTC-USD"
PERIODO_VELAS = 31       # máximo/mínimo de cuántas velas atrás
RATIO_TP      = 4.0      # TP = 4 × distancia al SL
RIESGO_PCT    = 0.01     # 1% del capital por operación
CAPITAL       = 500.0    # euros / dólares iniciales
INTERVALO     = "1d"     # velas diarias (también funciona en 4h para más señales)


# ─────────────────────────────────────────────────────────────────────
#  FUNCIONES AUXILIARES
# ─────────────────────────────────────────────────────────────────────
def macd_hist(serie: pd.Series, fast=12, slow=26, sig=9) -> pd.Series:
    m = serie.ewm(span=fast, adjust=False).mean() - serie.ewm(span=slow, adjust=False).mean()
    return m - m.ewm(span=sig, adjust=False).mean()


def es_bullish_engulfing(df: pd.DataFrame, i: int) -> bool:
    """La vela i envuelve la vela i-1 al alza."""
    if i < 1:
        return False
    o_prev = df["Open"].iloc[i-1]
    c_prev = df["Close"].iloc[i-1]
    o_cur  = df["Open"].iloc[i]
    c_cur  = df["Close"].iloc[i]
    cuerpo_prev = abs(c_prev - o_prev)
    if cuerpo_prev == 0:
        return False
    # Vela actual bajó más que el cuerpo anterior y subió más (envuelve)
    return (c_cur > max(o_prev, c_prev)) and (o_cur < min(o_prev, c_prev))


def es_bearish_engulfing(df: pd.DataFrame, i: int) -> bool:
    """La vela i envuelve la vela i-1 a la baja."""
    if i < 1:
        return False
    o_prev = df["Open"].iloc[i-1]
    c_prev = df["Close"].iloc[i-1]
    o_cur  = df["Open"].iloc[i]
    c_cur  = df["Close"].iloc[i]
    cuerpo_prev = abs(c_prev - o_prev)
    if cuerpo_prev == 0:
        return False
    return (c_cur < min(o_prev, c_prev)) and (o_cur > max(o_prev, c_prev))


# ─────────────────────────────────────────────────────────────────────
#  BACKTEST
# ─────────────────────────────────────────────────────────────────────
def backtest_engulfing(ticker=TICKER, periodo="5y", intervalo=INTERVALO):
    print(f"\n  Descargando {ticker}...")
    df = yf.download(ticker, period=periodo, interval=intervalo,
                     progress=False, auto_adjust=True)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df = df.dropna().copy()

    df["macd_h"]   = macd_hist(df["Close"])
    df["max_31"]   = df["High"].rolling(PERIODO_VELAS).max().shift(1)
    df["min_31"]   = df["Low"].rolling(PERIODO_VELAS).min().shift(1)
    df = df.dropna()

    capital_actual = CAPITAL
    operaciones    = []
    en_posicion    = False
    posicion       = {}

    for i in range(1, len(df)):
        row  = df.iloc[i]
        prev = df.iloc[i - 1]

        if en_posicion:
            # Comprobar si toca SL o TP
            p = posicion
            if p["tipo"] == "long":
                if row["Low"] <= p["sl"]:
                    pnl = -p["riesgo"]
                    capital_actual += pnl
                    operaciones.append({**p, "resultado": "perdida", "pnl": pnl,
                                        "salida": float(p["sl"]), "fecha_salida": str(df.index[i])})
                    en_posicion = False
                elif row["High"] >= p["tp"]:
                    pnl = p["riesgo"] * RATIO_TP
                    capital_actual += pnl
                    operaciones.append({**p, "resultado": "ganada", "pnl": pnl,
                                        "salida": float(p["tp"]), "fecha_salida": str(df.index[i])})
                    en_posicion = False
            else:  # short
                if row["High"] >= p["sl"]:
                    pnl = -p["riesgo"]
                    capital_actual += pnl
                    operaciones.append({**p, "resultado": "perdida", "pnl": pnl,
                                        "salida": float(p["sl"]), "fecha_salida": str(df.index[i])})
                    en_posicion = False
                elif row["Low"] <= p["tp"]:
                    pnl = p["riesgo"] * RATIO_TP
                    capital_actual += pnl
                    operaciones.append({**p, "resultado": "ganada", "pnl": pnl,
                                        "salida": float(p["tp"]), "fecha_salida": str(df.index[i])})
                    en_posicion = False
            continue

        precio = float(row["Open"])  # entrada en apertura de vela siguiente a la señal

        # ── SEÑAL LONG ──────────────────────────────────────────────
        if (prev["High"] >= float(prev["max_31"])         # nuevo máximo 31 velas
                and es_bullish_engulfing(df, i - 1)       # engulfing en vela señal
                and float(prev["macd_h"]) > 0             # MACD positivo
                and not en_posicion):

            sl_precio = float(prev["Low"])    # SL bajo la mecha de la vela señal
            dist_sl   = abs(precio - sl_precio)
            if dist_sl < precio * 0.001:      # evitar SL triviales
                continue
            tp_precio = precio + dist_sl * RATIO_TP
            riesgo    = capital_actual * RIESGO_PCT

            en_posicion = True
            posicion = {
                "tipo": "long", "ticker": ticker,
                "entrada": precio, "sl": sl_precio, "tp": tp_precio,
                "riesgo": riesgo, "capital_al_entrar": capital_actual,
                "fecha_entrada": str(df.index[i]),
                "macd_h_señal": float(prev["macd_h"])
            }

        # ── SEÑAL SHORT ─────────────────────────────────────────────
        elif (prev["Low"] <= float(prev["min_31"])        # nuevo mínimo 31 velas
                and es_bearish_engulfing(df, i - 1)       # bearish engulfing
                and float(prev["macd_h"]) < 0             # MACD negativo
                and not en_posicion):

            sl_precio = float(prev["High"])   # SL sobre la mecha de la vela señal
            dist_sl   = abs(sl_precio - precio)
            if dist_sl < precio * 0.001:
                continue
            tp_precio = precio - dist_sl * RATIO_TP
            riesgo    = capital_actual * RIESGO_PCT

            en_posicion = True
            posicion = {
                "tipo": "short", "ticker": ticker,
                "entrada": precio, "sl": sl_precio, "tp": tp_precio,
                "riesgo": riesgo, "capital_al_entrar": capital_actual,
                "fecha_entrada": str(df.index[i]),
                "macd_h_señal": float(prev["macd_h"])
            }

    # ── RESULTADOS ───────────────────────────────────────────────────
    if not operaciones:
        print("  Sin operaciones en el período analizado.")
        return

    total   = len(operaciones)
    ganadas = sum(1 for o in operaciones if o["resultado"] == "ganada")
    pnl     = sum(o["pnl"] for o in operaciones)

    long_ops   = [o for o in operaciones if o["tipo"] == "long"]
    short_ops  = [o for o in operaciones if o["tipo"] == "short"]
    long_wr    = sum(1 for o in long_ops  if o["resultado"] == "ganada") / len(long_ops)  if long_ops  else 0
    short_wr   = sum(1 for o in short_ops if o["resultado"] == "ganada") / len(short_ops) if short_ops else 0

    # Racha perdedora máxima
    racha_max = racha_actual = 0
    for o in operaciones:
        if o["resultado"] == "perdida":
            racha_actual += 1
            racha_max = max(racha_max, racha_actual)
        else:
            racha_actual = 0

    print(f"\n{'═'*55}")
    print(f"  BACKTEST: {ticker}  Engulfing 31 + MACD  ({periodo} · {intervalo})")
    print(f"{'═'*55}")
    print(f"  Capital inicial     : ${CAPITAL:,.2f}")
    print(f"  Capital final       : ${capital_actual:,.2f}")
    print(f"  Retorno total       : {(capital_actual/CAPITAL-1)*100:+.2f}%")
    print(f"  P&L neto            : ${pnl:+.2f}")
    print(f"{'─'*55}")
    print(f"  Operaciones totales : {total}")
    print(f"  Ganadas / Perdidas  : {ganadas} / {total - ganadas}")
    print(f"  WinRate GLOBAL      : {ganadas/total*100:.1f}%")
    print(f"  WinRate LONG        : {long_wr*100:.1f}%  ({len(long_ops)} ops)")
    print(f"  WinRate SHORT       : {short_wr*100:.1f}%  ({len(short_ops)} ops)")
    print(f"{'─'*55}")
    print(f"  Ratio TP/SL         : {RATIO_TP}:1")
    print(f"  Riesgo por op       : {RIESGO_PCT*100}%")
    print(f"  Racha perdedora max : {racha_max} seguidas")
    print(f"  Break-even WR       : {1/(1+RATIO_TP)*100:.1f}%  (20% con ratio 4:1)")
    print(f"{'─'*55}")
    print(f"  Últimas 5 operaciones:")
    for o in operaciones[-5:]:
        emoji = "✓" if o["resultado"] == "ganada" else "✗"
        print(f"    {emoji} {o['tipo'].upper():5s}  @${o['entrada']:,.0f}  "
              f"→ ${o['salida']:,.0f}  {o['resultado']}  "
              f"{'+'if o['pnl']>0 else ''}{o['pnl']:.2f}$")
    print(f"{'═'*55}\n")

    return {
        "capital_final": capital_actual,
        "pnl": pnl,
        "total": total,
        "winrate": ganadas / total,
        "long_winrate": long_wr,
        "short_winrate": short_wr,
        "racha_perdedora_max": racha_max
    }


if __name__ == "__main__":
    print("  Estrategia: Engulfing 31 velas + MACD — BTC-USD")
    print("  Patrón: máximo/mínimo de 31 velas + vela envolvente + MACD")
    print("  Long Y Short — Ratio 4:1 — 1% riesgo por op")
    resultado = backtest_engulfing("BTC-USD", periodo="5y", intervalo="1d")
