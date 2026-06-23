#!/usr/bin/env python3
"""
ESTRATEGIA — Engulfing en Extremos de 31 Velas (multi-activo)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Estrategia definida por Hicham — activos: BTC-USD, TSLA, QQQ

PATRÓN EN MÍNIMO DE 31 VELAS → LARGO:
  1. La vela toca el MÍNIMO de las últimas 31 velas
  2. Engulle el cuerpo de la vela anterior (cuerpo ≥ 2× anterior)
  3. Deja MECHA en la parte baja (aunque sea pequeña — rechaza el mínimo)
  4. RSI14 < 40 (confirma que hay sobreventa real antes del rebote)
  5. Siguiente vela CONFIRMA cambio de tendencia (cierra más alto)
  ➜ Entrada al cierre de la confirmación

PATRÓN EN MÁXIMO DE 31 VELAS → CORTO:
  Exactamente al revés.
  RSI14 > 60  |  mecha superior  |  confirmación cierra más bajo

FILTRO SP500 CORRELACIÓN:
  - Para acciones (TSLA, QQQ): SPY debe estar sobre MM200 para largos
  - Para crypto (BTC): filtro opcional según correlación rolling 60 días

SL  : 1.5%  fijo
TP  : 4.5%  fijo  →  Ratio 3:1
Risk: 1% del capital por operación
CB  : circuit breaker si pérdida mensual > 7%
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import json
import warnings
warnings.filterwarnings("ignore")

# ─── CONFIGURACIÓN ────────────────────────────────────────────
CAPITAL_INICIAL = 500.0
RIESGO_CAPITAL  = 0.01      # 1% capital en riesgo por operación
SL_PCT          = 0.015     # Stop Loss  1.5% fijo
TP_PCT          = 0.045     # Take Profit 4.5% fijo  →  ratio 3:1
VENTANA_31      = 31        # lookback para detectar extremos
CUERPO_RATIO    = 1.5       # cuerpo actual ≥ 1.5× anterior (engulfing claro)
MAX_PERD_MES    = 0.07      # circuit breaker mensual
RSI_LARGO_MAX   = 40        # RSI14 ANTERIOR < 40 para señal larga (antes del rebote)
RSI_CORTO_MIN   = 60        # RSI14 ANTERIOR > 60 para señal corta (antes de la caída)
INICIO          = "2015-01-01"
FIN             = datetime.now().strftime("%Y-%m-%d")

ACCIONES = ["TSLA", "QQQ"]
CRYPTO   = ["BTC-USD"]
TODOS    = ACCIONES + CRYPTO

# ─── UTILIDADES ───────────────────────────────────────────────

def strip_tz(idx):
    return idx.tz_localize(None) if getattr(idx, "tz", None) else idx

def rsi_n(s, n):
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    p = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - (100 / (1 + g / p.replace(0, np.nan)))

def macd_hist(s, fast=12, slow=26, sig=9):
    m  = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    sg = m.ewm(span=sig,  adjust=False).mean()
    return m - sg

def cargar(ticker):
    try:
        df = yf.download(ticker, start=INICIO, end=FIN,
                         interval="1d", progress=False, auto_adjust=True)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df.dropna()
        df.index = strip_tz(df.index)
        if len(df) < 250:
            return None
        df["rsi14"]     = rsi_n(df["Close"], 14)
        df["rsi14_ant"] = df["rsi14"].shift(1)  # RSI14 del día ANTERIOR (antes del rebote)
        df["rsi2"]      = rsi_n(df["Close"], 2)
        df["mm200"]     = df["Close"].rolling(200).mean()
        df["mm50"]      = df["Close"].rolling(50).mean()
        df["mh"]        = macd_hist(df["Close"])
        df["mh_ant"]    = df["mh"].shift(1)
        return df.dropna()
    except Exception as e:
        print(f"  ⚠️  Error cargando {ticker}: {e}")
        return None

# ─── CORRELACIÓN SP500 ────────────────────────────────────────

def calc_correlacion(df_activo, df_spy, ventana=60):
    """
    Calcula correlación rolling del activo con SP500.
    Si correlación > 0.5 → SP500 importa para filtro de dirección.
    Devuelve serie diaria de correlaciones.
    """
    ret_a   = df_activo["Close"].pct_change()
    ret_spy = df_spy["Close"].pct_change()
    # Alinear índices
    comun   = ret_a.index.intersection(ret_spy.index)
    corr    = ret_a.loc[comun].rolling(ventana).corr(ret_spy.loc[comun])
    return corr

# ─── DETECCIÓN DEL PATRÓN ─────────────────────────────────────

def detectar_señal(df, i, spy_df=None, corr_ser=None):
    """
    Detecta engulfing en extremo de 31 velas en la posición i del df.

    Parámetros adicionales:
      spy_df   : DataFrame del SPY (para filtro correlación en acciones)
      corr_ser : Serie de correlaciones rolling (activo vs SPY)

    Condiciones LARGO:
      - Low[i] ≤ min(Low, últimas 31 velas) ×1.005
      - Vela alcista: Close > Open
      - Engulfing: Open ≤ min(O1,C1)  y  Close ≥ max(O1,C1)
      - Cuerpo[i] ≥ CUERPO_RATIO × Cuerpo[i-1]
      - Mecha inferior: Open > Low  (aunque sea pequeña)
      - RSI14 < RSI_LARGO_MAX
      - Si activo correlaciona con SP500: SPY > MM200 del SPY

    Condiciones CORTO: exactamente al revés.
    """
    if i < VENTANA_31 + 1:
        return None

    fecha = df.index[i]

    O  = float(df["Open"].iloc[i]);   C  = float(df["Close"].iloc[i])
    H  = float(df["High"].iloc[i]);   L  = float(df["Low"].iloc[i])
    O1 = float(df["Open"].iloc[i-1]); C1 = float(df["Close"].iloc[i-1])
    # RSI14 del día ANTERIOR — antes de que la vela de señal empuje el RSI hacia arriba
    rsi14_ant = float(df["rsi14_ant"].iloc[i])
    mh     = float(df["mh"].iloc[i])
    mh_ant = float(df["mh_ant"].iloc[i])

    cuerpo  = abs(C - O)
    cuerpo1 = abs(C1 - O1)

    # Cuerpo anterior mínimo para evitar doji (0.2% del precio)
    if cuerpo1 < C * 0.002:
        return None

    # Condición central: cuerpo actual ≥ CUERPO_RATIO × anterior (1.5×)
    if cuerpo < CUERPO_RATIO * cuerpo1:
        return None

    # Extremos de las 31 velas anteriores
    ventana = df.iloc[i - VENTANA_31: i]
    min_31  = float(ventana["Low"].min())
    max_31  = float(ventana["High"].max())

    # Correlación SP500 en esta fecha (si disponible)
    usa_filtro_spy = False
    spy_sobre_mm200 = True  # por defecto, no bloqueamos
    if spy_df is not None and fecha in spy_df.index:
        spy_mm200 = float(spy_df["mm200"].loc[fecha]) if "mm200" in spy_df.columns else np.nan
        spy_close = float(spy_df["Close"].loc[fecha])
        if not np.isnan(spy_mm200):
            corr_val = float(corr_ser.loc[fecha]) if (corr_ser is not None and fecha in corr_ser.index) else 0
            if corr_val > 0.5:  # correlación significativa con SP500
                usa_filtro_spy = True
                spy_sobre_mm200 = spy_close > spy_mm200

    # ── SEÑAL LARGA ──────────────────────────────────────────
    if L <= min_31 * 1.005:      # toca el mínimo de 31 velas (±0.5%)
        if C <= O:                # debe ser vela alcista
            return None
        # Engulfing: la vela actual cubre el cuerpo anterior
        if O > min(C1, O1) or C < max(C1, O1):
            return None
        # Mecha inferior aunque sea pequeña
        if (O - L) <= 0:
            return None
        # RSI confirma sobreventa
        if rsi14 >= RSI_LARGO_MAX:
            return None
        # Filtro SP500: si correlación alta, mercado debe estar sano
        if usa_filtro_spy and not spy_sobre_mm200:
            return None  # SP500 bajista → no entrar largo en activos correlacionados

        # MACD: histograma negativo (presión bajista real) O girando al alza (cambio)
        # Cualquiera de las dos confirma que hay una oportunidad de rebote real
        macd_ok = (mh < 0) or (mh > mh_ant)  # bajo presión bajista O ya girando
        if not macd_ok:
            return None

        return {
            "tipo":          "LONG",
            "precio_señal":  round(C, 4),
            "rsi14":         round(rsi14, 1),
            "macd_h":        round(mh, 4),
            "macd_giro":     mh > mh_ant,
            "cuerpo_ratio":  round(cuerpo / cuerpo1, 2),
            "mecha_inf_pct": round((O - L) / C * 100, 3),
            "min_31":        round(min_31, 4),
            "corr_spy":      round(float(corr_ser.loc[fecha]) if (corr_ser is not None and fecha in corr_ser.index) else 0, 2),
            "filtro_spy":    usa_filtro_spy
        }

    # ── SEÑAL CORTA ──────────────────────────────────────────
    if H >= max_31 * 0.995:      # toca el máximo de 31 velas (±0.5%)
        if C >= O:                # debe ser vela bajista
            return None
        # Engulfing bajista
        if O < max(C1, O1) or C > min(C1, O1):
            return None
        # Mecha superior aunque sea pequeña
        if (H - O) <= 0:
            return None
        # RSI confirma sobrecompra
        if rsi14 <= RSI_CORTO_MIN:
            return None
        # Para cortos: SP500 bajista es favorable (no bloqueamos el corto si SPY baja)

        # MACD: histograma positivo (presión compradora real) O girando a la baja
        macd_ok_c = (mh > 0) or (mh < mh_ant)
        if not macd_ok_c:
            return None

        return {
            "tipo":          "SHORT",
            "precio_señal":  round(C, 4),
            "rsi14":         round(rsi14, 1),
            "macd_h":        round(mh, 4),
            "macd_giro":     mh < mh_ant,
            "cuerpo_ratio":  round(cuerpo / cuerpo1, 2),
            "mecha_sup_pct": round((H - O) / C * 100, 3),
            "max_31":        round(max_31, 4),
            "corr_spy":      round(float(corr_ser.loc[fecha]) if (corr_ser is not None and fecha in corr_ser.index) else 0, 2),
            "filtro_spy":    usa_filtro_spy
        }

    return None

# ─── BACKTEST POR ACTIVO ──────────────────────────────────────

def backtest_activo(ticker, df, spy_df, es_accion):
    """
    Ejecuta el backtest del patrón 31 velas para un activo.
    """
    # Calcular correlación con SP500
    corr_ser = None
    if spy_df is not None:
        corr_ser = calc_correlacion(df, spy_df, ventana=60)

    # Añadir MM200 al SPY si es acción
    if es_accion and spy_df is not None and "mm200" not in spy_df.columns:
        spy_df["mm200"] = spy_df["Close"].rolling(200).mean()

    capital  = CAPITAL_INICIAL / len(TODOS)
    ops      = []
    pos      = None      # posición activa
    señal    = None      # señal esperando confirmación
    perd_mes = 0.0
    mes_act  = None
    circuit  = False

    for i in range(len(df)):
        fecha = df.index[i]
        C = float(df["Close"].iloc[i])
        H = float(df["High"].iloc[i])
        L = float(df["Low"].iloc[i])

        # Reset mensual
        mes = (fecha.year, fecha.month)
        if mes != mes_act:
            mes_act  = mes
            perd_mes = 0.0
            circuit  = False

        if circuit:
            señal = None
            continue

        # ─ Gestión posición activa ─
        if pos:
            resultado = None
            pnl_cap   = 0.0

            if pos["tipo"] == "LONG":
                if L <= pos["sl"]:
                    resultado = "perdida";  pnl_cap = -RIESGO_CAPITAL
                elif H >= pos["tp"]:
                    resultado = "ganancia"; pnl_cap = RIESGO_CAPITAL * (TP_PCT / SL_PCT)
            else:
                if H >= pos["sl"]:
                    resultado = "perdida";  pnl_cap = -RIESGO_CAPITAL
                elif L <= pos["tp"]:
                    resultado = "ganancia"; pnl_cap = RIESGO_CAPITAL * (TP_PCT / SL_PCT)

            # Cierre forzado a los 20 días (swingtrading)
            dias = i - pos["i"]
            if resultado is None and dias >= 20:
                ret_r = (C - pos["entrada"]) / pos["entrada"]
                if pos["tipo"] == "SHORT":
                    ret_r = -ret_r
                pnl_cap = min(max(ret_r / SL_PCT * RIESGO_CAPITAL,
                                  -RIESGO_CAPITAL),
                              RIESGO_CAPITAL * (TP_PCT / SL_PCT))
                resultado = "ganancia" if pnl_cap > 0 else "perdida"

            if resultado:
                pnl_eur = round(capital * pnl_cap, 2)
                capital  = round(capital + pnl_eur, 2)
                if resultado == "perdida":
                    perd_mes += abs(pnl_eur)
                    if perd_mes >= (CAPITAL_INICIAL / len(TODOS)) * MAX_PERD_MES:
                        circuit = True

                ops.append({
                    "ticker":       ticker,
                    "fecha_señal":  pos["fecha_señal"],
                    "fecha_conf":   pos["fecha_conf"],
                    "fecha_salida": str(fecha.date()),
                    "tipo":         pos["tipo"],
                    "entrada":      pos["entrada"],
                    "sl":           pos["sl"],
                    "tp":           pos["tp"],
                    "rsi14":        pos["rsi14"],
                    "macd_h":       pos["macd_h"],
                    "macd_giro":    pos["macd_giro"],
                    "cuerpo_ratio": pos["cuerpo_ratio"],
                    "corr_spy":     pos["corr_spy"],
                    "resultado":    resultado,
                    "pnl_cap_pct":  round(pnl_cap * 100, 3),
                    "pnl_eur":      pnl_eur,
                    "capital":      capital,
                    "dias":         dias
                })
                pos = None
            continue

        # ─ Verificar confirmación de señal pendiente ─
        if señal:
            tipo         = señal["tipo"]
            precio_señal = señal["precio_señal"]

            confirmado = (tipo == "LONG" and C > precio_señal) or \
                         (tipo == "SHORT" and C < precio_señal)

            if confirmado:
                if tipo == "LONG":
                    sl = round(C * (1 - SL_PCT), 4)
                    tp = round(C * (1 + TP_PCT), 4)
                else:
                    sl = round(C * (1 + SL_PCT), 4)
                    tp = round(C * (1 - TP_PCT), 4)

                pos = {
                    "tipo":         tipo,
                    "entrada":      C,
                    "sl":           sl,
                    "tp":           tp,
                    "rsi14":        señal["rsi14"],
                    "macd_h":       señal.get("macd_h", 0),
                    "macd_giro":    señal.get("macd_giro", False),
                    "cuerpo_ratio": señal["cuerpo_ratio"],
                    "corr_spy":     señal["corr_spy"],
                    "fecha_señal":  señal["fecha"],
                    "fecha_conf":   str(fecha.date()),
                    "i":            i
                }
            señal = None
            continue

        # ─ Buscar nueva señal ─
        s = detectar_señal(df, i,
                           spy_df if es_accion else None,
                           corr_ser)
        if s:
            s["fecha"] = str(fecha.date())
            señal = s

    return ops, capital

# ─── MAIN ─────────────────────────────────────────────────────

def main():
    ratio = TP_PCT / SL_PCT
    print(f"\n{'='*65}")
    print(f"  BACKTEST — ENGULFING 31 VELAS  (BTC · TSLA · QQQ)")
    print(f"  Período  : {INICIO}  →  {FIN}")
    print(f"  Capital  : €{CAPITAL_INICIAL:,.0f}  repartido entre {len(TODOS)} activos")
    print(f"  Riesgo   : 1%/op  |  SL: {SL_PCT*100}%  |  TP: {TP_PCT*100}%  |  Ratio {ratio:.0f}:1")
    print(f"  Filtros  : Engulfing {CUERPO_RATIO}× + mecha (mínima) + RSI14 + conf + SP500 corr")
    print(f"{'='*65}\n")

    print("  Descargando datos...")
    spy_df = cargar("SPY")
    if spy_df is not None and "mm200" not in spy_df.columns:
        spy_df["mm200"] = spy_df["Close"].rolling(200).mean()
    datos  = {t: cargar(t) for t in TODOS}

    resultados = {}
    todas_ops  = []

    print(f"\n  {'─'*62}")
    print(f"  {'Activo':<10} {'Ops':>5} {'Win%':>7} {'Largos':>8} {'Cortos':>8} {'P&L€':>9} {'Retorno':>8}")
    print(f"  {'─'*62}")

    for ticker in TODOS:
        df = datos.get(ticker)
        if df is None:
            print(f"  ❌ {ticker:<10} sin datos suficientes")
            continue

        es_accion = ticker in ACCIONES
        ops, cap_f = backtest_activo(ticker, df, spy_df, es_accion)

        if not ops:
            print(f"  ─  {ticker:<10} sin señales (patrón no encontrado en período)")
            continue

        total  = len(ops)
        ganas  = sum(1 for o in ops if o["resultado"] == "ganancia")
        pnl    = sum(o["pnl_eur"] for o in ops)
        wr     = round(ganas / total * 100, 1)
        cap_ini= CAPITAL_INICIAL / len(TODOS)
        ret    = round(pnl / cap_ini * 100, 1)
        longs  = sum(1 for o in ops if o["tipo"] == "LONG")
        shorts = sum(1 for o in ops if o["tipo"] == "SHORT")
        wr_l   = round(sum(1 for o in ops if o["tipo"]=="LONG" and o["resultado"]=="ganancia") / max(longs,1) * 100, 0)
        wr_s   = round(sum(1 for o in ops if o["tipo"]=="SHORT" and o["resultado"]=="ganancia") / max(shorts,1) * 100, 0)

        ic = "✅" if wr >= 60 else "⚠️" if wr >= 50 else "❌"
        print(f"  {ic} {ticker:<8} {total:>6} {wr:>6.1f}%  {longs:>3}({wr_l:.0f}%)  {shorts:>3}({wr_s:.0f}%)  "
              f"€{pnl:>+7,.0f}  {ret:>+6.0f}%")

        resultados[ticker] = {
            "total": total, "ganas": ganas, "pnl": pnl,
            "cap_ini": cap_ini, "cap_fin": cap_f,
            "winrate": wr, "retorno": ret,
            "winrate_largos": wr_l, "winrate_cortos": wr_s,
            "longs": longs, "shorts": shorts
        }
        todas_ops.extend(ops)

    if not resultados:
        print("\n  Sin resultados. Las condiciones son demasiado estrictas.")
        print("  Posible ajuste: reducir CUERPO_RATIO a 1.5 o ampliar RSI_LARGO_MAX a 45")
        return

    print(f"  {'─'*62}")

    # ─ Global ─
    total_g = sum(v["total"] for v in resultados.values())
    ganas_g = sum(v["ganas"] for v in resultados.values())
    pnl_g   = sum(v["pnl"]   for v in resultados.values())
    wr_g    = round(ganas_g / total_g * 100, 1) if total_g else 0
    cap_f_g = CAPITAL_INICIAL + pnl_g
    ret_g   = round(pnl_g / CAPITAL_INICIAL * 100, 1)
    ev      = round((wr_g/100 * RIESGO_CAPITAL * ratio * 100) -
                    ((100-wr_g)/100 * RIESGO_CAPITAL * 100), 3)

    # Racha peor
    rachas, r = [], 0
    for o in sorted(todas_ops, key=lambda x: x["fecha_señal"]):
        r = r+1 if o["resultado"] == "perdida" else 0
        rachas.append(r)
    peor_r = max(rachas) if rachas else 0

    ops_mes = max(1, round(total_g / max(1, (datetime.now().year - 2015) * 12)))
    dias_m  = round(sum(o["dias"] for o in todas_ops) / total_g, 1)

    print(f"\n{'='*65}")
    print(f"  RESULTADO GLOBAL — ENGULFING 31 VELAS")
    print(f"{'='*65}")
    print(f"\n  Capital inicial   : €{CAPITAL_INICIAL:>10,.2f}")
    print(f"  Capital final     : €{cap_f_g:>10,.2f}")
    print(f"  Retorno total     : {ret_g:>+10.1f}%")
    print(f"  Operaciones total : {total_g:>10}  (~{ops_mes}/mes)")
    print(f"  Win rate global   : {wr_g:>10.1f}%")
    print(f"  Valor esperado    : {ev:>+10.3f}%  por operación")
    print(f"  Ratio TP/SL       : {ratio:.0f}:1   ({TP_PCT*100:.1f}% / {SL_PCT*100:.1f}%)")
    print(f"  Días promedio/op  : {dias_m:>10.1f}")
    print(f"  Peor racha pérd.  : {peor_r:>10} seguidas")

    print(f"\n  {'─'*55}")
    if wr_g >= 69:
        print(f"  ✅  VALIDADA — {wr_g}% WR  |  EV: {ev:+.3f}%  |  LISTA PARA BOT")
    elif wr_g >= 60:
        print(f"  ✅  VÁLIDA — {wr_g}% WR  |  EV: {ev:+.3f}%  |  Edge confirmado")
    elif wr_g >= 50:
        print(f"  ⚠️   {wr_g}% WR — rentable con ratio {ratio:.0f}:1  (EV: {ev:+.3f}%)")
    else:
        print(f"  ❌  {wr_g}% WR — sin edge estadístico")
    print(f"  {'─'*55}")

    # Comparativa
    print(f"\n  COMPARATIVA:")
    print(f"  Sistema RSI(2) confluencia (6 cond.)  : 65.9% WR  (88 ops)")
    print(f"  Sistema RSI(2) señal pura             : 69.4% WR  (985 ops)")
    print(f"  Engulfing 31 velas (este test)        : {wr_g:.1f}% WR  ({total_g} ops)")
    if wr_g >= 55:
        print(f"\n  ➜ COMBINACIÓN: fusionar ambas señales → mayor frecuencia + calidad")

    # Proyección interés compuesto
    if ev > 0 and total_g >= 10:
        print(f"\n  PROYECCIÓN INTERÉS COMPUESTO ({ops_mes} op/mes  |  Circuit -7%/mes):")
        print(f"  {'Meses':<8}{'Mediana':>10}{'Peor10%':>12}{'Mejor10%':>12}{'Retorno':>10}")
        print(f"  {'─'*52}")
        np.random.seed(42)
        for mes in [3, 6, 12, 24]:
            sims = []
            for _ in range(3000):
                c = CAPITAL_INICIAL; pm = 0.0
                for op_n in range(ops_mes * mes):
                    if op_n % ops_mes == 0: pm = 0.0
                    if pm >= CAPITAL_INICIAL * MAX_PERD_MES: continue
                    if np.random.random() < wr_g / 100:
                        c += c * RIESGO_CAPITAL * ratio
                    else:
                        l = c * RIESGO_CAPITAL; c -= l; pm += l
                sims.append(c)
            med = np.median(sims); p10 = np.percentile(sims,10); p90 = np.percentile(sims,90)
            print(f"  {mes:>2} meses   €{med:>8,.0f}    €{p10:>8,.0f}    €{p90:>8,.0f}  {(med/CAPITAL_INICIAL-1)*100:>+7.0f}%")

    # Últimas 8 operaciones
    ultimas = sorted(todas_ops, key=lambda x: x["fecha_señal"])[-8:]
    print(f"\n  ÚLTIMAS 8 OPERACIONES:")
    print(f"  {'Fecha':12} {'Tick':6} {'Tipo':6} {'Entrada':>10} {'RSI':>5} {'Cuerpo':>7} {'Corr':>5} {'Res':10} {'P&L%':>7}")
    print(f"  {'─'*78}")
    for o in ultimas:
        ic2 = "✅" if o["resultado"] == "ganancia" else "❌"
        print(f"  {o['fecha_señal']:<12} {o['ticker']:<6} {o['tipo']:<6} "
              f"${o['entrada']:>9,.2f} {o['rsi14']:>4.0f}° {o['cuerpo_ratio']:>5.1f}×  "
              f"{o['corr_spy']:>4.2f}  {ic2} {o['resultado']:<8} {o['pnl_cap_pct']:>+6.1f}%")

    # Guardar
    with open("/home/enter/trading_system/backtest_31v_resultado.json", "w") as f:
        json.dump({
            "estrategia": "Engulfing 31 velas (BTC + TSLA + QQQ)",
            "parametros": {
                "ventana": VENTANA_31, "cuerpo_ratio": CUERPO_RATIO,
                "sl_pct": SL_PCT*100, "tp_pct": TP_PCT*100, "ratio": ratio,
                "rsi14_largo_max": RSI_LARGO_MAX, "rsi14_corto_min": RSI_CORTO_MIN,
                "filtro_correlacion_spy": True
            },
            "periodo": f"{INICIO} → {FIN}",
            "capital_ini": CAPITAL_INICIAL,
            "capital_fin": round(cap_f_g, 2),
            "total": total_g, "ganas": ganas_g,
            "winrate": wr_g, "pnl_eur": round(pnl_g, 2),
            "retorno_pct": ret_g, "ev_pct": ev,
            "peor_racha": peor_r, "dias_medio": dias_m,
            "evaluacion": "VALIDADA" if wr_g >= 69 else "VALIDA" if wr_g >= 60 else "MARGINAL" if wr_g >= 50 else "AJUSTAR",
            "por_activo": resultados,
            "operaciones": todas_ops
        }, f, indent=2, default=str)

    print(f"\n  Guardado: backtest_31v_resultado.json")
    print(f"{'='*65}\n")

if __name__ == "__main__":
    main()
