#!/usr/bin/env python3
"""
ESCULTOR — Quitando lo que sobra hasta que aparezca la estrategia pura.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Solo dos reglas:
  ENTRAR  → RSI(2) cae por debajo de 5 mientras el precio está sobre MM200
  SALIR   → RSI(2) sube por encima de 65  (el mercado rebotó)

Sin TP fijo. Sin SL fijo. Sin filtros extra.
Solo la señal pura — para saber cuánto vale antes de añadir nada.

Después de medir la señal pura añadimos:
  - Gestión de riesgo (SL/TP)
  - Circuit breaker mensual
  - Niveles psicológicos como filtro de calidad
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import json
import warnings
warnings.filterwarnings("ignore")

INICIO   = "2014-01-01"
FIN      = datetime.now().strftime("%Y-%m-%d")
TICKERS  = ["SPY", "QQQ", "TSLA", "NVDA", "BTC-USD"]

def rsi_n(s, n):
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    p = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - (100 / (1 + g / p.replace(0, np.nan)))

def strip_tz(idx):
    return idx.tz_localize(None) if getattr(idx, "tz", None) else idx

def analizar(ticker):
    df = yf.download(ticker, start=INICIO, end=FIN,
                     interval="1d", progress=False, auto_adjust=True)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df = df.dropna()
    df.index = strip_tz(df.index)
    if len(df) < 210: return None

    df["mm200"] = df["Close"].rolling(200).mean()
    df["rsi2"]  = rsi_n(df["Close"], 2)
    df = df.dropna()

    resultados = []
    en_trade   = False
    entrada    = 0.0
    fecha_ini  = ""

    for i in range(len(df)):
        precio = float(df["Close"].iloc[i])
        rsi2   = float(df["rsi2"].iloc[i])
        mm200  = float(df["mm200"].iloc[i])
        fecha  = str(df.index[i].date())

        if en_trade:
            if rsi2 > 65:                        # salida — RSI recuperado
                ret = (precio - entrada) / entrada * 100
                resultados.append({
                    "entrada": round(entrada, 2),
                    "salida":  round(precio, 2),
                    "ret_pct": round(ret, 2),
                    "gana":    ret > 0,
                    "dias":    i - idx_entrada
                })
                en_trade = False
        else:
            if rsi2 < 5 and precio > mm200:      # señal pura
                en_trade   = True
                entrada    = precio
                fecha_ini  = fecha
                idx_entrada = i

    if not resultados: return None

    total  = len(resultados)
    ganas  = sum(1 for r in resultados if r["gana"])
    wr     = round(ganas / total * 100, 1)
    ret_m  = round(sum(r["ret_pct"] for r in resultados) / total, 2)
    ret_g  = round(sum(r["ret_pct"] for r in resultados if r["gana"]) / max(ganas,1), 2)
    ret_p  = round(sum(r["ret_pct"] for r in resultados if not r["gana"]) / max(total-ganas,1), 2)
    dias_m = round(sum(r["dias"] for r in resultados) / total, 1)

    icono  = "✅" if wr >= 69 else "⚠️ " if wr >= 55 else "❌"
    print(f"  {icono} {ticker:<8} | Ops:{total:>4} | Win:{wr:>5.1f}% | "
          f"Ret.medio:{ret_m:>+5.2f}% | "
          f"Cuando gana:{ret_g:>+5.2f}% | Cuando pierde:{ret_p:>+5.2f}% | "
          f"{dias_m:.0f}d/op")

    return {"ticker": ticker, "total": total, "ganas": ganas,
            "winrate": wr, "ret_medio_pct": ret_m,
            "ret_ganadora": ret_g, "ret_perdedora": ret_p,
            "dias_medio": dias_m, "resultados": resultados}

def main():
    print(f"\n{'='*70}")
    print(f"  EL ESCULTOR — Estrategia pura sin adornos")
    print(f"  Período : {INICIO}  →  {FIN}  (10+ años)")
    print(f"  Señal   : Entrar cuando RSI(2) < 5  AND  Precio > MM200")
    print(f"  Salida  : RSI(2) > 65  (sin TP ni SL — señal desnuda)")
    print(f"  Activos : {', '.join(TICKERS)}")
    print(f"{'='*70}\n")

    datos = {}
    for t in TICKERS:
        datos[t] = analizar(t)

    validos = {k: v for k, v in datos.items() if v}
    if not validos: return

    total_g  = sum(v["total"] for v in validos.values())
    ganas_g  = sum(v["ganas"] for v in validos.values())
    wr_g     = round(ganas_g / total_g * 100, 1)

    print(f"\n{'='*70}")
    print(f"  SEÑAL PURA — win rate sin gestión de riesgo")
    print(f"  Total operaciones : {total_g}")
    print(f"  Win rate global   : {wr_g}%")

    mejor = max(validos.values(), key=lambda v: v["winrate"])
    print(f"\n  Mejor activo      : {mejor['ticker']} → {mejor['winrate']}% win rate")
    print(f"  Retorno medio por op: {mejor['ret_medio_pct']:+.2f}%")
    print(f"  Cuando gana, gana : {mejor['ret_ganadora']:+.2f}% de media")
    print(f"  Cuando pierde, pierde: {mejor['ret_perdedora']:+.2f}% de media")

    print(f"\n  {'─'*60}")
    if wr_g >= 69:
        print(f"  ✅  ÁNGEL ENCONTRADO — {wr_g}% win rate en señal pura")
        print(f"      Ahora añadimos gestión de riesgo sin romperlo")
    elif wr_g >= 55:
        print(f"  ⚠️   Señal en {wr_g}% — buena base, seguimos quitando")
    else:
        print(f"  ❌  {wr_g}% — seguimos quitando impurezas")
    print(f"  {'─'*60}")

    # Guardar solo lo esencial
    with open("/home/enter/trading_system/escultor_resultado.json", "w") as f:
        json.dump({k: {kk: vv for kk, vv in v.items() if kk != "resultados"}
                   for k, v in validos.items()}, f, indent=2)

    print(f"\n  Siguiente paso según resultado:")
    print(f"    Si win rate ≥ 69% → añadir SL/TP sin romper la señal")
    print(f"    Si win rate < 69% → añadir UN solo filtro más y medir de nuevo")
    print(f"{'='*70}\n")

if __name__ == "__main__":
    main()
