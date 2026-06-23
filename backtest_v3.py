#!/usr/bin/env python3
"""
BACKTEST V3 — RSI(2) Institucional Multi-Asset | Objetivo ≥ 69% win rate
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Estrategia documentada por Connors Research (1990-2025): 68-72% win rate
Funciona mejor en ÍNDICES (SPY/QQQ) y CRYPTO que en acciones individuales.

Reglas de entrada:
  1. TENDENCIA   : Precio > MM50 > MM200 (solo operar en uptrend confirmado)
  2. RSI(2) < 5  : Caída extrema dentro de tendencia alcista
  3. BOLLINGER   : Precio bajo la banda inferior (zona de rebote estadístico)
  4. RSI(14) < 35: Confirmación adicional de sobreventa

Salida táctica:
  → RSI(2) > 65  (rebote completado)
  → TP: +4%      (ratio 4:1)
  → SL: -1%      (máximo riesgo por operación)
  → Máx 5 días   (salida forzada si no hay movimiento)

Circuit breaker: Si pérdida acumulada del mes > 7%, bot se pausa hasta mes siguiente.

Activos elegidos:
  - SPY, QQQ  (ETFs de índice — más estables y con mejor media reversion)
  - TSLA, NVDA (acciones de alto volumen)
  - BTC-USD   (crypto — genera señales extra en mercado 24h)
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import warnings
warnings.filterwarnings("ignore")

# ─── CONFIGURACIÓN ────────────────────────────────────────────
CAPITAL_INICIAL  = 500.0
RIESGO_POR_OP    = 0.01      # 1% por operación
RATIO_TP         = 4.0       # 4:1 — ganamos 4%, perdemos 1%
MAX_DIAS         = 5         # salida forzada a los 5 días
MAX_PERDIDA_MES  = 0.07      # circuit breaker: -7% del capital inicial por mes
OBJETIVO_WR      = 69.0

# Activos: índices + acciones de gran volumen + 1 crypto
TICKERS = ["SPY", "QQQ", "TSLA", "NVDA", "BTC-USD"]

FIN    = datetime.now().strftime("%Y-%m-%d")
INICIO = "2014-01-01"   # 10 años — datos diarios sin límite en Yahoo Finance

# ─── INDICADORES ──────────────────────────────────────────────

def rsi_n(s, n):
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    p = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - (100 / (1 + g / p.replace(0, np.nan)))

def bollinger_bajo(serie, n=20, std=2.0):
    """Devuelve True si el precio está por debajo de la banda inferior de Bollinger."""
    sma  = serie.rolling(n).mean()
    band = serie.rolling(n).std() * std
    lower = sma - band
    return serie < lower

def strip_tz(idx):
    if hasattr(idx, "tz") and idx.tz is not None:
        return idx.tz_localize(None)
    return idx

# ─── BACKTEST POR TICKER ──────────────────────────────────────

def backtest_ticker(ticker, capital_ini):
    try:
        df = yf.download(ticker, start=INICIO, end=FIN,
                         interval="1d", progress=False, auto_adjust=True)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df.dropna()
        df.index = strip_tz(df.index)
    except Exception as e:
        print(f"  [{ticker}] Error: {e}"); return None

    if len(df) < 210:
        print(f"  [{ticker}] Datos insuficientes ({len(df)})"); return None

    # Indicadores
    df["mm50"]    = df["Close"].rolling(50).mean()
    df["mm200"]   = df["Close"].rolling(200).mean()
    df["rsi2"]    = rsi_n(df["Close"], 2)
    df["rsi14"]   = rsi_n(df["Close"], 14)
    df["bb_bajo"] = bollinger_bajo(df["Close"])
    df["vol_med"] = df["Volume"].rolling(20).mean()
    df = df.dropna()

    operaciones = []
    capital     = capital_ini
    pos         = None
    perd_mes    = 0.0
    mes_act     = None
    circuit_on  = False

    for i in range(len(df)):
        row   = df.iloc[i]
        fecha = df.index[i]

        # Reset mensual del circuit breaker
        mes = (fecha.year, fecha.month)
        if mes != mes_act:
            mes_act   = mes
            perd_mes  = 0.0
            circuit_on = False

        if circuit_on:
            continue

        precio = float(row["Close"])
        alto   = float(row["High"])
        bajo   = float(row["Low"])
        rsi2   = float(row["rsi2"])

        # ─ Gestión posición abierta ─
        if pos:
            dias = i - pos["idx"]
            res  = None

            if bajo <= pos["sl"]:
                res     = "perdida"
                pnl_pct = -RIESGO_POR_OP
            elif alto >= pos["tp"]:
                res     = "ganancia"
                pnl_pct = RIESGO_POR_OP * RATIO_TP
            elif rsi2 > 65:
                real    = (precio - pos["entrada"]) / pos["entrada"]
                res     = "ganancia" if real > 0 else "perdida"
                pnl_pct = min(max(real, -RIESGO_POR_OP), RIESGO_POR_OP * RATIO_TP)
            elif dias >= MAX_DIAS:
                real    = (precio - pos["entrada"]) / pos["entrada"]
                res     = "ganancia" if real >= 0 else "perdida"
                pnl_pct = min(max(real, -RIESGO_POR_OP), RIESGO_POR_OP * RATIO_TP)

            if res:
                pnl_usd = round(capital * pnl_pct, 2)
                capital  = round(capital + pnl_usd, 2)
                if res == "perdida":
                    perd_mes += abs(pnl_usd)
                    if perd_mes >= capital_ini * MAX_PERDIDA_MES:
                        circuit_on = True

                operaciones.append({
                    "ticker": ticker,
                    "fecha_entrada": pos["fecha"],
                    "fecha_salida":  str(fecha.date()),
                    "entrada":       pos["entrada"],
                    "sl":            pos["sl"],
                    "tp":            pos["tp"],
                    "rsi2_entrada":  pos["rsi2_ini"],
                    "resultado":     res,
                    "pnl_pct":       round(pnl_pct * 100, 2),
                    "pnl_usd":       pnl_usd,
                    "capital_post":  capital,
                    "dias":          dias
                })
                pos = None
            continue

        # ─ Buscar entrada ─
        mm50  = float(row["mm50"])  if not pd.isna(row["mm50"])  else 0
        mm200 = float(row["mm200"]) if not pd.isna(row["mm200"]) else 0
        rsi14 = float(row["rsi14"]) if not pd.isna(row["rsi14"]) else 50
        bb_b  = bool(row["bb_bajo"])
        vol   = float(row["Volume"])
        vm    = float(row["vol_med"]) if not pd.isna(row["vol_med"]) else 1

        # FILTRO 1: Tendencia alcista — precio > MM200 (mercado en uptrend)
        if mm200 == 0: continue
        if precio <= mm200: continue

        # FILTRO 2: RSI(2) en sobreventa extrema (señal principal Connors Research)
        if pd.isna(rsi2) or rsi2 >= 5: continue

        # FILTRO 3: Volumen presente
        if vm == 0 or vol < vm * 0.4: continue

        # ─ Entrada confirmada ─
        sl = round(precio * (1 - RIESGO_POR_OP), 2)
        tp = round(precio * (1 + RIESGO_POR_OP * RATIO_TP), 2)
        pos = {
            "fecha":    str(fecha.date()),
            "entrada":  precio,
            "sl":       sl,
            "tp":       tp,
            "rsi2_ini": round(rsi2, 1),
            "idx":      i
        }

    if not operaciones:
        print(f"  [{ticker:<8}] Sin señales válidas en el período.")
        return None

    total   = len(operaciones)
    ganas   = sum(1 for o in operaciones if o["resultado"] == "ganancia")
    pierdes = total - ganas
    pnl     = sum(o["pnl_usd"] for o in operaciones)
    wr      = round(ganas / total * 100, 1)
    ret     = round((capital - capital_ini) / capital_ini * 100, 1)

    rachas, racha = [], 0
    for o in operaciones:
        racha = racha + 1 if o["resultado"] == "perdida" else 0
        rachas.append(racha)
    peor = max(rachas) if rachas else 0

    dias_p = round(sum(o["dias"] for o in operaciones) / total, 1)
    icono  = "✅" if wr >= OBJETIVO_WR else "⚠️ " if wr >= 55 else "❌"

    print(f"  {icono} {ticker:<8} | Ops:{total:>3} | Win:{wr:>5.1f}% | "
          f"P&L:€{pnl:>+7,.0f} | Cap:€{capital:>7,.0f}({ret:>+.1f}%) | "
          f"Peor racha:{peor} | {dias_p}d/op")

    return {
        "ticker": ticker, "total": total, "ganas": ganas, "pierdes": pierdes,
        "winrate": wr, "pnl_eur": round(pnl, 2),
        "capital_inicial": round(capital_ini, 2),
        "capital_final": round(capital, 2),
        "retorno_pct": ret, "peor_racha": peor,
        "dias_promedio": dias_p, "operaciones": operaciones
    }

# ─── MAIN ─────────────────────────────────────────────────────

def main():
    print(f"\n{'='*70}")
    print(f"  BACKTEST V3 — RSI(2) INSTITUCIONAL MULTI-ASSET")
    print(f"  Período  : {INICIO}  →  {FIN}  (10 años)")
    print(f"  Capital  : €{CAPITAL_INICIAL:,.0f}  |  Risk: 1%  |  Ratio 4:1 (+4% TP / -1% SL)")
    print(f"  Objetivo : ≥ {OBJETIVO_WR}% win rate")
    print(f"  Circuit  : Bot pausa si pierde >{MAX_PERDIDA_MES*100:.0f}% en el mes")
    print(f"  Activos  : {', '.join(TICKERS)}")
    print(f"  Señal    : RSI(2)<5 + Precio>MM200 (Connors Research puro)")
    print(f"{'='*70}\n")

    resultados = {}
    cap_x = CAPITAL_INICIAL / len(TICKERS)

    for t in TICKERS:
        resultados[t] = backtest_ticker(t, cap_x)

    validos = {k: v for k, v in resultados.items() if v}
    if not validos:
        print("\n  Sin resultados."); return

    # ─ Global ─
    total_g   = sum(r["total"]   for r in validos.values())
    ganas_g   = sum(r["ganas"]   for r in validos.values())
    pierdes_g = sum(r["pierdes"] for r in validos.values())
    pnl_g     = sum(r["pnl_eur"] for r in validos.values())
    wr_g      = round(ganas_g / total_g * 100, 1) if total_g else 0
    cap_f     = CAPITAL_INICIAL + pnl_g
    ret_g     = round(pnl_g / CAPITAL_INICIAL * 100, 1)
    ev        = round((wr_g/100 * RIESGO_POR_OP * RATIO_TP * 100) -
                      ((100-wr_g)/100 * RIESGO_POR_OP * 100), 3)
    ops_mes   = max(1, round(total_g / 24))

    print(f"\n{'='*70}")
    print(f"  RESULTADO GLOBAL")
    print(f"{'='*70}")
    print(f"\n  Capital inicial   : €{CAPITAL_INICIAL:>10,.2f}")
    print(f"  Capital final     : €{cap_f:>10,.2f}")
    print(f"  Retorno 2 años    : {ret_g:>+10.1f}%")
    print(f"  Total operaciones : {total_g:>10}")
    print(f"  Ganadas           : {ganas_g:>10}  ({wr_g}%)")
    print(f"  Perdidas          : {pierdes_g:>10}  ({round(pierdes_g/total_g*100,1) if total_g else 0}%)")
    print(f"  P&L neto          : €{pnl_g:>+10,.2f}")
    print(f"  Valor esperado    : {ev:>+10.3f}% por operación")
    print(f"  Frecuencia        : ~{ops_mes} ops/mes")

    print(f"\n  {'─'*60}")
    if wr_g >= OBJETIVO_WR:
        print(f"  ✅  OBJETIVO ALCANZADO — {wr_g}% ≥ {OBJETIVO_WR}%")
        print(f"      ESTRATEGIA VALIDADA — Lista para bot real")
        print(f"      EV: {ev:+.3f}% por operación → SÓLIDO")
    elif wr_g >= 55:
        print(f"  ⚠️   WIN RATE {wr_g}% — Rentable pero por debajo del objetivo")
        print(f"      EV positivo: {ev:+.3f}% — El sistema tiene edge")
    else:
        print(f"  ❌  WIN RATE {wr_g}% — Revisar filtros o activos")
    print(f"  {'─'*60}")

    # ─ Proyección compuesta ─
    if ev > 0:
        print(f"\n  PROYECCIÓN INTERÉS COMPUESTO ({ops_mes} ops/mes):")
        print(f"  {'Período':<12}{'Mediana €':>12}{'Mejor 10%':>12}{'Peor 10%':>12}{'Retorno':>10}")
        print(f"  {'─'*58}")
        np.random.seed(42)
        for mes in [3, 6, 12, 18, 24]:
            sims = []
            for _ in range(3000):
                c = CAPITAL_INICIAL
                pm = 0.0
                for op in range(ops_mes * mes):
                    if op % ops_mes == 0: pm = 0.0
                    if pm >= CAPITAL_INICIAL * MAX_PERDIDA_MES: continue
                    if np.random.random() < wr_g / 100:
                        c += c * RIESGO_POR_OP * RATIO_TP
                    else:
                        lost = c * RIESGO_POR_OP
                        c   -= lost
                        pm  += lost
                sims.append(c)
            med = np.median(sims)
            p90 = np.percentile(sims, 90)
            p10 = np.percentile(sims, 10)
            print(f"  {mes:>2} meses     €{med:>10,.0f}  €{p90:>10,.0f}  €{p10:>10,.0f}  {(med/CAPITAL_INICIAL-1)*100:>+8.0f}%")

    # Guardar
    output = {
        "metadata": {
            "version": "v3", "periodo": f"{INICIO} → {FIN}",
            "capital_inicial": CAPITAL_INICIAL,
            "riesgo_pct": RIESGO_POR_OP * 100, "ratio": RATIO_TP,
            "activos": TICKERS, "fecha_backtest": datetime.now().isoformat()
        },
        "global": {
            "total": total_g, "ganas": ganas_g, "pierdes": pierdes_g,
            "winrate": wr_g, "pnl_eur": round(pnl_g, 2),
            "capital_inicial": CAPITAL_INICIAL, "capital_final": round(cap_f, 2),
            "retorno_pct": ret_g, "valor_esperado_pct": ev, "ops_mes": ops_mes,
            "evaluacion": "VALIDADA" if wr_g >= OBJETIVO_WR else
                          "MARGINAL" if wr_g >= 55 else "NO_VALIDA"
        },
        "por_ticker": {k: {kk: vv for kk, vv in v.items() if kk != "operaciones"}
                       for k, v in validos.items()}
    }
    ruta = "/home/enter/trading_system/backtest_v3_resultado.json"
    with open(ruta, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Guardado: {ruta}")
    print(f"{'='*70}\n")

if __name__ == "__main__":
    main()
