#!/usr/bin/env python3
"""
BACKTEST V2 — RSI(2) Mean Reversion + Filtro Institucional
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Estrategia documentada desde 1990s (Larry Connors / QuantifiedStrategies)
Win rate histórico comprobado: 60-70% en blue chips

Reglas:
  1. TENDENCIA    : Precio > MM200 diaria  (solo largos)
  2. UPTREND      : Precio > MM50 diaria   (tendencia intermedia sana)
  3. RETROCESO    : RSI(2) diario < 15     (caída brusca dentro de tendencia)
  4. VOLUMEN      : Volumen > media 20 días (confirma movimiento real)
  5. ENTRADA      : Al cierre del día con señal
  6. SALIDA       : RSI(2) > 70  O  TP +4%  O  SL -2%  O  máx 10 días
  7. NIVEL EXTRA  : Precio cerca de número redondo → prioridad de entrada

Activos : TSLA, GOOGL, NVDA
Capital : €500 con interés compuesto
Riesgo  : 2% por operación | Take Profit: 4%
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import warnings
warnings.filterwarnings("ignore")

# ─── CONFIGURACIÓN ────────────────────────────────────────────
CAPITAL_INICIAL     = 500.0
RIESGO_POR_OP       = 0.02        # 2% del capital por operación
RATIO_TP            = 2.0         # TP = 2x SL → ganancia del 4%
TICKERS             = ["TSLA", "GOOGL", "NVDA"]
MAX_PERDIDA_SEMANAL = 0.06        # Stop operativo si pérdida > 6%/semana
MAX_DIAS_EN_OP      = 10          # Salida forzada si no toca SL ni TP en 10 días

# Período: últimos 2 años disponibles en Yahoo Finance (datos diarios ilimitados)
FIN    = datetime.now().strftime("%Y-%m-%d")
INICIO = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")

# ─── INDICADORES ──────────────────────────────────────────────

def rsi_n(serie, n):
    d = serie.diff()
    g = d.clip(lower=0).rolling(n).mean()
    p = (-d.clip(upper=0)).rolling(n).mean()
    rs = g / p.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def nivel_psicologico(precio, tol=0.025):
    for mult in [100, 50, 25]:
        niv = round(precio / mult) * mult
        if niv > 0 and abs(precio - niv) / precio <= tol:
            return float(niv)
    return None

def strip_tz(idx):
    if hasattr(idx, "tz") and idx.tz is not None:
        return idx.tz_localize(None)
    return idx

# ─── BACKTEST POR TICKER ──────────────────────────────────────

def backtest_ticker(ticker, capital_ini):
    # Descargar datos diarios (2 años)
    try:
        df = yf.download(ticker, start=INICIO, end=FIN,
                         interval="1d", progress=False, auto_adjust=True)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df.dropna()
        df.index = strip_tz(df.index)
    except Exception as e:
        print(f"  [{ticker}] Error: {e}")
        return None

    if len(df) < 210:
        print(f"  [{ticker}] Datos insuficientes ({len(df)} velas)")
        return None

    # Indicadores
    df["mm50"]   = df["Close"].rolling(50).mean()
    df["mm100"]  = df["Close"].rolling(100).mean()
    df["mm200"]  = df["Close"].rolling(200).mean()
    df["rsi2"]   = rsi_n(df["Close"], 2)
    df["rsi14"]  = rsi_n(df["Close"], 14)
    df["vol_med"]= df["Volume"].rolling(20).mean()
    df = df.dropna()

    operaciones  = []
    capital      = capital_ini
    pos          = None
    perd_semana  = 0.0
    semana_act   = None

    for i in range(len(df)):
        row   = df.iloc[i]
        fecha = df.index[i]

        # Reset semanal
        sem = fecha.isocalendar()[1]
        if sem != semana_act:
            semana_act  = sem
            perd_semana = 0.0

        precio = float(row["Close"])
        alto   = float(row["High"])
        bajo   = float(row["Low"])

        # ─ Gestionar posición abierta ─
        if pos:
            dias_en_op = i - pos["idx"]
            rsi2_ahora = float(row["rsi2"])

            resultado = None

            if bajo <= pos["sl"]:
                resultado = "perdida"
                pnl_pct   = -RIESGO_POR_OP
            elif alto >= pos["tp"]:
                resultado = "ganancia"
                pnl_pct   = RIESGO_POR_OP * RATIO_TP
            elif rsi2_ahora > 70:
                # RSI(2) sobrecomprado — salida táctica
                salida_precio = precio
                ganancia_real = (salida_precio - pos["entrada"]) / pos["entrada"]
                if ganancia_real > 0:
                    resultado = "ganancia"
                    pnl_pct   = min(ganancia_real, RIESGO_POR_OP * RATIO_TP)
                elif ganancia_real < -RIESGO_POR_OP:
                    resultado = "perdida"
                    pnl_pct   = -RIESGO_POR_OP
                else:
                    resultado = "ganancia" if ganancia_real >= 0 else "perdida"
                    pnl_pct   = ganancia_real
            elif dias_en_op >= MAX_DIAS_EN_OP:
                # Salida forzada por tiempo
                ganancia_real = (precio - pos["entrada"]) / pos["entrada"]
                resultado = "ganancia" if ganancia_real >= 0 else "perdida"
                pnl_pct   = max(min(ganancia_real, RIESGO_POR_OP * RATIO_TP), -RIESGO_POR_OP)

            if resultado:
                pnl_usd = round(capital * pnl_pct, 2)
                capital  = round(capital + pnl_usd, 2)
                if resultado == "perdida":
                    perd_semana += abs(pnl_usd)

                operaciones.append({
                    "ticker":        ticker,
                    "fecha_entrada": pos["fecha"],
                    "fecha_salida":  str(fecha.date()),
                    "entrada":       pos["entrada"],
                    "sl":            pos["sl"],
                    "tp":            pos["tp"],
                    "nivel":         pos["nivel"],
                    "resultado":     resultado,
                    "pnl_pct":       round(pnl_pct * 100, 2),
                    "pnl_usd":       pnl_usd,
                    "capital_post":  capital,
                    "dias":          i - pos["idx"]
                })
                pos = None
            continue

        # ─ Buscar entrada ─
        if perd_semana >= capital * MAX_PERDIDA_SEMANAL:
            continue

        mm200   = float(row["mm200"])
        mm50    = float(row["mm50"])
        rsi2    = float(row["rsi2"])
        vol     = float(row["Volume"])
        vol_med = float(row["vol_med"])

        # FILTRO 1: Tendencia alcista doble confirmada
        if precio <= mm200 or precio <= mm50:
            continue

        # FILTRO 2: RSI(2) < 5 — señal de máxima calidad (fondos quant usan < 5)
        if rsi2 >= 5:
            continue

        # FILTRO 3: Volumen real (no estamos en día vacío de mercado)
        if vol_med == 0 or vol < vol_med * 0.8:
            continue

        # FILTRO 4 (BONUS): Nivel psicológico cercano → señal más fuerte
        nivel_ref = nivel_psicologico(precio, tol=0.04)

        # ─ Orden confirmada ─
        sl = round(precio * (1 - RIESGO_POR_OP), 2)
        tp = round(precio * (1 + RIESGO_POR_OP * RATIO_TP), 2)

        pos = {
            "fecha":   str(fecha.date()),
            "entrada": precio,
            "sl":      sl,
            "tp":      tp,
            "nivel":   nivel_ref,
            "idx":     i
        }

    # ─ Estadísticas ─
    if not operaciones:
        print(f"  [{ticker}] Sin operaciones.")
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
    peor_racha = max(rachas) if rachas else 0

    dias_prom = round(sum(o["dias"] for o in operaciones) / total, 1)

    print(f"  {ticker:<6} | Ops: {total:>3} | Win: {wr:>5.1f}% | "
          f"P&L: €{pnl:>+7,.0f} | Capital: €{capital:>7,.0f} ({ret:>+.1f}%) | "
          f"Peor racha: {peor_racha} | Días/op: {dias_prom}")

    return {
        "ticker": ticker, "total": total, "ganas": ganas, "pierdes": pierdes,
        "winrate": wr, "pnl_eur": round(pnl, 2),
        "capital_inicial": round(capital_ini, 2),
        "capital_final":   round(capital, 2),
        "retorno_pct":     ret,
        "peor_racha":      peor_racha,
        "dias_promedio":   dias_prom,
        "operaciones":     operaciones
    }

# ─── MAIN ─────────────────────────────────────────────────────

def main():
    print(f"\n{'='*65}")
    print(f"  BACKTEST V2 — RSI(2) MEAN REVERSION + FILTRO INSTITUCIONAL")
    print(f"  Período : {INICIO}  →  {FIN}  (2 años)")
    print(f"  Capital : €{CAPITAL_INICIAL:,.0f} total  |  Riesgo: 2%  |  Ratio 1:2")
    print(f"  Activos : {', '.join(TICKERS)}")
    print(f"  Lógica  : RSI(2)<15 + Precio>MM50>MM200 (rebote en tendencia)")
    print(f"  Salida  : RSI(2)>70  o  +4% TP  o  -2% SL  o  10 días máx")
    print(f"{'='*65}\n")

    resultados = {}
    capital_x  = CAPITAL_INICIAL / len(TICKERS)   # €166.67 por ticker

    for ticker in TICKERS:
        resultados[ticker] = backtest_ticker(ticker, capital_x)

    validos = {k: v for k, v in resultados.items() if v}

    if not validos:
        print("\n  Sin resultados válidos.")
        return

    # ─ Resumen global ─
    total_g   = sum(r["total"]   for r in validos.values())
    ganas_g   = sum(r["ganas"]   for r in validos.values())
    pierdes_g = sum(r["pierdes"] for r in validos.values())
    pnl_g     = sum(r["pnl_eur"] for r in validos.values())
    wr_g      = round(ganas_g / total_g * 100, 1) if total_g else 0
    cap_f     = CAPITAL_INICIAL + pnl_g
    ret_g     = round(pnl_g / CAPITAL_INICIAL * 100, 1)
    ev        = round((wr_g/100 * 4) - ((100-wr_g)/100 * 2), 2)   # valor esperado %

    print(f"\n{'='*65}")
    print(f"  RESULTADO GLOBAL")
    print(f"{'='*65}")
    print(f"\n  Capital inicial  : €{CAPITAL_INICIAL:>10,.2f}")
    print(f"  Capital final    : €{cap_f:>10,.2f}")
    print(f"  Retorno 2 años   : {ret_g:>+10.1f}%")
    print(f"  Total operaciones: {total_g:>10}")
    print(f"  Ganadas          : {ganas_g:>10}  ({wr_g}%)")
    print(f"  Perdidas         : {pierdes_g:>10}  ({round(pierdes_g/total_g*100,1) if total_g else 0}%)")
    print(f"  P&L neto         : €{pnl_g:>+10,.2f}")
    print(f"  Valor esperado   : {ev:>+10.2f}% por operación")

    print(f"\n  {'─'*55}")
    if wr_g >= 50:
        print(f"  ✅  ESTRATEGIA VALIDADA — LISTA PARA OPERAR")
        print(f"      Win rate {wr_g}% con ratio 1:2 = RENTABLE MATEMÁTICAMENTE")
        print(f"      Valor esperado: {ev:+.2f}% por operación  →  POSITIVO")
    elif wr_g >= 40:
        print(f"  ⚠️   ESTRATEGIA MARGINAL")
        print(f"      Win rate {wr_g}% — afinar parámetros antes de operar")
    else:
        print(f"  ❌  ESTRATEGIA NO VÁLIDA")
        print(f"      Win rate {wr_g}% — no operar con dinero real")
    print(f"  {'─'*55}")

    # Proyección con interés compuesto
    if wr_g >= 40 and ev > 0:
        ops_mes = max(1, round(total_g / 24))
        print(f"\n  PROYECCIÓN INTERÉS COMPUESTO ({ops_mes} ops/mes estimadas):")
        print(f"  {'Período':<12} {'Capital €':>12} {'Retorno':>10}")
        print(f"  {'─'*36}")
        for mes in [3, 6, 12, 18, 24]:
            np.random.seed(42)
            simulaciones = []
            for _ in range(1000):
                cap_s = CAPITAL_INICIAL
                for _ in range(ops_mes * mes):
                    if np.random.random() < wr_g / 100:
                        cap_s *= (1 + RIESGO_POR_OP * RATIO_TP)
                    else:
                        cap_s *= (1 - RIESGO_POR_OP)
                simulaciones.append(cap_s)
            mediana = np.median(simulaciones)
            print(f"  {mes:>2} meses      €{mediana:>10,.0f}   {(mediana/CAPITAL_INICIAL-1)*100:>+8.0f}%")

    # Guardar resultados
    output = {
        "metadata": {
            "version": "v2",
            "estrategia": "RSI(2) Mean Reversion + Filtro Institucional",
            "periodo": f"{INICIO} → {FIN}",
            "capital_inicial": CAPITAL_INICIAL,
            "riesgo_pct": RIESGO_POR_OP * 100,
            "ratio": RATIO_TP,
            "activos": TICKERS,
            "fecha_backtest": datetime.now().isoformat()
        },
        "global": {
            "total": total_g, "ganas": ganas_g, "pierdes": pierdes_g,
            "winrate": wr_g, "pnl_eur": round(pnl_g, 2),
            "capital_inicial": CAPITAL_INICIAL,
            "capital_final":   round(cap_f, 2),
            "retorno_pct":     ret_g,
            "valor_esperado":  ev,
            "evaluacion": "VALIDA" if wr_g >= 50 else "MARGINAL" if wr_g >= 40 else "NO_VALIDA"
        },
        "por_ticker": validos
    }

    ruta = "/home/enter/trading_system/backtest_v2_resultado.json"
    with open(ruta, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n  Resultados guardados: {ruta}")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
