#!/usr/bin/env python3
"""
BACKTEST v5 — Confluencia Optimizada
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Cambios vs v4:
  - ETH-USD eliminado (54.5% WR, retorno negativo)
  - SPY añadido (escultor: 70.2% WR)
  - RSI(2) threshold: < 5 → < 8  (más señales, mantiene edge)
  - Stochastic: %K < 25 (sin cambio)
  - MACD: negativo (sin cambio — confirma sobreventa real)
  - Volumen: > media (sin cambio)

Activos: SPY, QQQ, NVDA, BTC-USD
SL: 1.5×ATR | TP: 4:1 | Circuit: -7%/mes
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import json
import warnings
warnings.filterwarnings("ignore")

CAPITAL_INICIAL = 500.0
RIESGO_CAPITAL  = 0.01
RATIO           = 4.0
ATR_MULT_SL     = 1.5
MAX_PERD_MES    = 0.07
RSI2_UMBRAL     = 8        # v4 usaba 5 — subimos para más frecuencia
STK_UMBRAL      = 25
INICIO          = "2014-01-01"
FIN             = datetime.now().strftime("%Y-%m-%d")

ACCIONES = ["SPY", "QQQ", "NVDA"]
CRYPTO   = ["BTC-USD"]
TODOS    = ACCIONES + CRYPTO


def rsi_n(s, n):
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    p = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - (100 / (1 + g / p.replace(0, np.nan)))

def stochastic(df, k=14, d=3):
    low_k  = df["Low"].rolling(k).min()
    high_k = df["High"].rolling(k).max()
    pct_k  = 100 * (df["Close"] - low_k) / (high_k - low_k).replace(0, np.nan)
    return pct_k, pct_k.rolling(d).mean()

def macd_hist(s, fast=12, slow=26, sig=9):
    m = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    return m - m.ewm(span=sig, adjust=False).mean()

def atr_14(df):
    h, l, c = df["High"], df["Low"], df["Close"].shift(1)
    tr = pd.concat([h-l, (h-c).abs(), (l-c).abs()], axis=1).max(axis=1)
    return tr.rolling(14).mean()

def strip_tz(idx):
    return idx.tz_localize(None) if getattr(idx, "tz", None) else idx

def cargar(ticker):
    try:
        df = yf.download(ticker, start=INICIO, end=FIN,
                         interval="1d", progress=False, auto_adjust=True)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df.dropna()
        df.index = strip_tz(df.index)
        if len(df) < 250:
            return None
        df["mm50"]    = df["Close"].rolling(50).mean()
        df["mm200"]   = df["Close"].rolling(200).mean()
        df["rsi2"]    = rsi_n(df["Close"], 2)
        df["stk_k"], df["stk_d"] = stochastic(df)
        df["macd_h"]  = macd_hist(df["Close"])
        df["atr14"]   = atr_14(df)
        df["vol_med"] = df["Volume"].rolling(20).mean()
        return df.dropna()
    except Exception as e:
        print(f"  ERROR cargando {ticker}: {e}")
        return None


def backtest(ticker, df, filtro_df, es_crypto=False):
    cap_ini  = CAPITAL_INICIAL / len(TODOS)
    capital  = cap_ini
    ops      = []
    pos      = None
    perd_mes = 0.0
    mes_act  = None
    circuit  = False

    for i in range(len(df)):
        fecha  = df.index[i]
        precio = float(df["Close"].iloc[i])
        alto   = float(df["High"].iloc[i])
        bajo   = float(df["Low"].iloc[i])
        rsi2   = float(df["rsi2"].iloc[i])
        mm50   = float(df["mm50"].iloc[i])
        mm200  = float(df["mm200"].iloc[i])
        stk_k  = float(df["stk_k"].iloc[i])
        mh     = float(df["macd_h"].iloc[i])
        atr    = float(df["atr14"].iloc[i])
        vol    = float(df["Volume"].iloc[i])
        vol_m  = float(df["vol_med"].iloc[i])

        mes = (fecha.year, fecha.month)
        if mes != mes_act:
            mes_act  = mes
            perd_mes = 0.0
            circuit  = False

        if circuit:
            continue

        # ─── Gestión posición abierta ───────────────────────────
        if pos:
            res = None
            if bajo <= pos["sl"]:
                res     = "perdida"
                pnl_cap = -RIESGO_CAPITAL
            elif alto >= pos["tp"]:
                res     = "ganancia"
                pnl_cap = RIESGO_CAPITAL * RATIO
            elif rsi2 > 65:
                ret_r   = (precio - pos["entrada"]) / pos["entrada"]
                pnl_cap = ret_r * (RIESGO_CAPITAL / pos["sl_pct"])
                pnl_cap = min(max(pnl_cap, -RIESGO_CAPITAL), RIESGO_CAPITAL * RATIO)
                res     = "ganancia" if ret_r > 0 else "perdida"
            if res:
                pnl_eur = round(capital * pnl_cap, 2)
                capital = round(capital + pnl_eur, 2)
                if res == "perdida":
                    perd_mes += abs(pnl_eur)
                    if perd_mes >= cap_ini * MAX_PERD_MES:
                        circuit = True
                ops.append({
                    "ticker": ticker, "fecha_e": pos["fecha"],
                    "fecha_s": str(fecha.date()), "res": res,
                    "pnl_cap_pct": round(pnl_cap * 100, 2),
                    "pnl_eur": pnl_eur, "capital": capital,
                    "dias": i - pos["i"], "sl_pct": round(pos["sl_pct"] * 100, 1)
                })
                pos = None
            continue

        # ─── Filtros de entrada ─────────────────────────────────

        # F1: Mercado sano
        if fecha not in filtro_df.index:
            continue
        f_precio = float(filtro_df["Close"].loc[fecha])
        f_mm200  = float(filtro_df["mm200"].loc[fecha])
        if pd.isna(f_mm200) or f_precio < f_mm200:
            continue

        # F2: Tendencia activo (precio > MM50 > MM200)
        if pd.isna(mm50) or pd.isna(mm200):
            continue
        if precio <= mm200 or precio <= mm50 or mm50 <= mm200:
            continue

        # F3: RSI(2) sobreventa — umbral v5 = 8
        if pd.isna(rsi2) or rsi2 >= RSI2_UMBRAL:
            continue

        # F4: Stochastic %K < 25 (sobreventa confirmada)
        if pd.isna(stk_k) or stk_k >= STK_UMBRAL:
            continue

        # F5: MACD histograma negativo (caída real, no falsa señal)
        if pd.isna(mh) or mh >= 0:
            continue

        # F6: Volumen superior a media
        if vol_m == 0 or vol < vol_m:
            continue

        # ─── Entrada ────────────────────────────────────────────
        sl_pct = min(ATR_MULT_SL * atr / precio, 0.08)
        pos = {
            "entrada": precio,
            "sl": round(precio * (1 - sl_pct), 2),
            "tp": round(precio * (1 + sl_pct * RATIO), 2),
            "sl_pct": sl_pct,
            "fecha": str(fecha.date()),
            "i": i
        }

    return ops, capital


def main():
    print(f"\n{'='*68}")
    print(f"  BACKTEST v5 — CONFLUENCIA OPTIMIZADA")
    print(f"  Período  : {INICIO}  →  {FIN}  (10+ años)")
    print(f"  Activos  : {', '.join(TODOS)}")
    print(f"  Cambios  : ETH eliminado | SPY añadido | RSI(2) < {RSI2_UMBRAL}")
    print(f"  Filtros  : Mercado sano | Tendencia | RSI(2) | Stoch | MACD | Vol")
    print(f"  SL: 1.5×ATR | TP: 4:1 | Circuit: -7%/mes")
    print(f"{'='*68}\n")

    print("  Cargando datos...")
    datos  = {t: cargar(t) for t in TODOS}
    spy_df = cargar("SPY")
    btc_df = cargar("BTC-USD")

    if spy_df is None:
        print("  ERROR: SPY no disponible")
        return

    resultados = {}
    print(f"\n  {'─'*60}")
    print(f"  {'':2}{'Activo':<10}{'Ops':>6}{'Win%':>8}{'P&L€':>10}{'Capital':>10}{'Retorno':>9}{'PeorRa':>8}")
    print(f"  {'─'*60}")

    for t in TODOS:
        df = datos.get(t)
        if df is None:
            print(f"  ❌ {t:<10} sin datos")
            continue

        filtro    = spy_df if t in ACCIONES else btc_df
        if filtro is None:
            continue

        ops, cap_f = backtest(t, df, filtro, t in CRYPTO)
        cap_ini    = CAPITAL_INICIAL / len(TODOS)

        if not ops:
            print(f"  —  {t:<10} sin señales")
            continue

        total = len(ops)
        ganas = sum(1 for o in ops if o["res"] == "ganancia")
        pnl   = sum(o["pnl_eur"] for o in ops)
        wr    = round(ganas / total * 100, 1)
        ret   = round(pnl / cap_ini * 100, 1)

        rachas, r = [], 0
        for o in ops:
            r = r + 1 if o["res"] == "perdida" else 0
            rachas.append(r)
        peor = max(rachas) if rachas else 0

        ic = "✅" if wr >= 65 else "⚠️ " if wr >= 58 else "❌"
        print(f"  {ic} {t:<8}{total:>7}{wr:>7.1f}%  €{pnl:>+8,.0f}  €{cap_f:>8,.0f}  {ret:>+7.1f}%  {peor:>6}")
        resultados[t] = {
            "total": total, "ganas": ganas, "pnl": pnl,
            "cap_ini": cap_ini, "cap_fin": cap_f,
            "winrate": wr, "retorno": ret, "peor_racha": peor
        }

    print(f"  {'─'*60}")
    if not resultados:
        return

    total_g = sum(v["total"] for v in resultados.values())
    ganas_g = sum(v["ganas"] for v in resultados.values())
    pnl_g   = sum(v["pnl"]   for v in resultados.values())
    wr_g    = round(ganas_g / total_g * 100, 1) if total_g else 0
    cap_f_g = CAPITAL_INICIAL + pnl_g
    ret_g   = round(pnl_g / CAPITAL_INICIAL * 100, 1)
    ev      = round((wr_g/100 * RIESGO_CAPITAL * RATIO * 100) - ((100-wr_g)/100 * RIESGO_CAPITAL * 100), 3)
    anos    = datetime.now().year - 2014
    ops_mes = max(1, round(total_g / (anos * 12)))

    print(f"\n{'='*68}")
    print(f"  RESULTADO GLOBAL v5")
    print(f"{'='*68}")
    print(f"  Capital inicial   : €{CAPITAL_INICIAL:>10,.2f}")
    print(f"  Capital final     : €{cap_f_g:>10,.2f}")
    print(f"  Retorno 10 años   : {ret_g:>+10.1f}%")
    print(f"  Operaciones total : {total_g:>10}  (~{ops_mes}/mes)")
    print(f"  Win rate global   : {wr_g:>10.1f}%")
    print(f"  Valor esperado    : {ev:>+10.3f}% por operación")

    print(f"\n  {'─'*55}")
    if wr_g >= 65:
        print(f"  ✅  SISTEMA VALIDADO — {wr_g}% WIN RATE")
        print(f"      Ratio 4:1 | EV: {ev:+.3f}% | LISTO PARA BOT REAL")
    elif wr_g >= 58:
        print(f"  ⚠️   Win rate {wr_g}% — edge presente, mejorable")
    else:
        print(f"  ❌  Win rate {wr_g}% — revisar filtros")
    print(f"  {'─'*55}")

    if ev > 0 and ops_mes >= 2:
        print(f"\n  PROYECCIÓN INTERÉS COMPUESTO ({ops_mes} ops/mes):")
        print(f"  {'Período':<12}{'Mediana':>10}{'Peor 10%':>12}{'Mejor 10%':>12}{'Retorno':>10}")
        print(f"  {'─'*56}")
        np.random.seed(42)
        for mes in [3, 6, 12, 18, 24]:
            sims = []
            for _ in range(3000):
                c = CAPITAL_INICIAL
                pm = 0.0
                for op in range(ops_mes * mes):
                    if op % ops_mes == 0:
                        pm = 0.0
                    if pm >= CAPITAL_INICIAL * MAX_PERD_MES:
                        continue
                    if np.random.random() < wr_g / 100:
                        c += c * RIESGO_CAPITAL * RATIO
                    else:
                        l = c * RIESGO_CAPITAL
                        c -= l
                        pm += l
                sims.append(c)
            med = np.median(sims)
            p10 = np.percentile(sims, 10)
            p90 = np.percentile(sims, 90)
            print(f"  {mes:>2} meses     €{med:>8,.0f}    €{p10:>8,.0f}    €{p90:>8,.0f}  {(med/CAPITAL_INICIAL-1)*100:>+7.0f}%")

    output = {
        "version": "v5_optimizado",
        "cambios_vs_v4": ["ETH-USD eliminado", "SPY añadido", f"RSI2 umbral: {RSI2_UMBRAL}"],
        "winrate_global": wr_g,
        "ev_pct": ev,
        "capital_ini": CAPITAL_INICIAL,
        "capital_fin": round(cap_f_g, 2),
        "retorno_pct": ret_g,
        "filtros": 6,
        "ops_mes": ops_mes,
        "activos": TODOS,
        "por_activo": resultados
    }
    with open("/home/enter/trading_system/backtest_v5_resultado.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Guardado: backtest_v5_resultado.json")
    print(f"{'='*68}\n")


if __name__ == "__main__":
    main()
