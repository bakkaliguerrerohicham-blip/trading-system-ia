import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import json

CAPITAL_INICIAL = 10000.0
RIESGO_POR_OP   = 0.01
RATIO_TP_SL     = 2.0
TICKERS         = ["TSLA", "NVDA", "ES=F"]
INICIO          = "2023-06-01"
FIN             = "2025-06-01"

print(f"\n{'='*55}")
print(f"  BACKTESTING 2 AÑOS — Jun 2023 → Jun 2025")
print(f"  Capital: ${CAPITAL_INICIAL:,.0f} | Riesgo: 1% | Ratio: 1:2")
print(f"{'='*55}\n")

resumen_por_ticker = {}
resultados_globales = []

for ticker in TICKERS:
    print(f"Descargando {ticker}...", end="", flush=True)
    try:
        df = yf.download(ticker, start=INICIO, end=FIN, interval="1d", progress=False, auto_adjust=True)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df.dropna()
        print(f" {len(df)} velas")
    except Exception as e:
        print(f" ERROR: {e}")
        continue

    if len(df) < 100:
        print(f"  Datos insuficientes, saltando.")
        continue

    df = df.copy()
    df['ema9']  = df['Close'].ewm(span=9).mean()
    df['ema21'] = df['Close'].ewm(span=21).mean()
    df['ema50'] = df['Close'].ewm(span=50).mean()
    delta = df['Close'].diff()
    g = delta.clip(lower=0).rolling(14).mean()
    p = (-delta.clip(upper=0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + g / p.replace(0, np.nan)))
    macd = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
    df['macd_hist'] = macd - macd.ewm(span=9).mean()
    df['vol_med'] = df['Volume'].rolling(20).mean()
    df = df.dropna()

    operaciones = []
    capital = CAPITAL_INICIAL

    for i in range(50, len(df)-1):
        row    = df.iloc[i]
        precio = float(row['Close'])
        rsi    = float(row['rsi'])
        e9, e21, e50 = float(row['ema9']), float(row['ema21']), float(row['ema50'])
        mhist  = float(row['macd_hist'])
        vol    = float(row['Volume'])
        vmed   = float(row['vol_med'])

        cl = sum([precio>e9>e21>e50, 40<=rsi<=65, mhist>0, vol>vmed*1.2])
        cs = sum([precio<e9<e21<e50, 35<=rsi<=60, mhist<0, vol>vmed*1.2])

        if cl >= 3:   dir_op = "long"
        elif cs >= 3: dir_op = "short"
        else:         continue

        soporte     = float(df['Low'].iloc[i-10:i].min())
        resistencia = float(df['High'].iloc[i-10:i].max())
        buf = precio * 0.002

        if dir_op == "long":
            sl = soporte - buf
            tp = precio + (precio - sl) * RATIO_TP_SL
        else:
            sl = resistencia + buf
            tp = precio - (sl - precio) * RATIO_TP_SL

        dist_sl = abs(precio - sl)
        if dist_sl == 0 or abs(precio-tp)/dist_sl < 1.8:
            continue

        riesgo_usd = capital * RIESGO_POR_OP
        resultado = "neutral"
        resultado_usd = 0
        duracion = 0

        for j in range(i+1, min(i+20, len(df))):
            h = float(df['High'].iloc[j])
            l = float(df['Low'].iloc[j])
            duracion += 1
            if dir_op == "long":
                if l <= sl:  resultado="perdida";  resultado_usd=-riesgo_usd; break
                if h >= tp:  resultado="ganancia"; resultado_usd=riesgo_usd*RATIO_TP_SL; break
            else:
                if h >= sl:  resultado="perdida";  resultado_usd=-riesgo_usd; break
                if l <= tp:  resultado="ganancia"; resultado_usd=riesgo_usd*RATIO_TP_SL; break

        capital += resultado_usd
        operaciones.append({
            "ticker": ticker, "fecha": str(df.index[i].date()),
            "dir": dir_op, "precio": round(precio,2),
            "resultado": resultado, "usd": round(resultado_usd,2),
            "duracion": duracion, "capital": round(capital,2)
        })

    if not operaciones:
        print(f"  Sin señales.")
        continue

    total   = len(operaciones)
    ganas   = sum(1 for o in operaciones if o['resultado']=="ganancia")
    pierdes = sum(1 for o in operaciones if o['resultado']=="perdida")
    ganancia_total = sum(o['usd'] for o in operaciones)
    winrate = round(ganas/total*100,1)
    retorno = round((CAPITAL_INICIAL+ganancia_total-CAPITAL_INICIAL)/CAPITAL_INICIAL*100,1)

    peor_racha = racha = 0
    for o in operaciones:
        if o['resultado']=="perdida": racha+=1; peor_racha=max(peor_racha,racha)
        else: racha=0

    resumen_por_ticker[ticker] = {
        "total":total,"ganas":ganas,"pierdes":pierdes,
        "winrate":winrate,"ganancia_total":round(ganancia_total,2),
        "retorno_pct":retorno,"peor_racha":peor_racha,
        "operaciones":operaciones
    }
    resultados_globales.extend(operaciones)
    print(f"  {total} operaciones | Win rate: {winrate}% | P&L: ${ganancia_total:+,.0f} | Retorno: {retorno:+.1f}%")

# ─── RESUMEN FINAL ────────────────────────────────────
print(f"\n{'='*55}")
print(f"  RESUMEN FINAL")
print(f"{'='*55}")

if not resultados_globales:
    print("  Sin datos suficientes.")
else:
    total_g    = len(resultados_globales)
    ganas_g    = sum(1 for o in resultados_globales if o['resultado']=="ganancia")
    pierdes_g  = sum(1 for o in resultados_globales if o['resultado']=="perdida")
    ganancia_g = sum(o['usd'] for o in resultados_globales)
    winrate_g  = round(ganas_g/total_g*100,1)
    cap_final  = CAPITAL_INICIAL + ganancia_g
    retorno_g  = round((cap_final-CAPITAL_INICIAL)/CAPITAL_INICIAL*100,1)
    dur_media  = round(sum(o['duracion'] for o in resultados_globales)/total_g,1)

    print(f"\n  Capital inicial:     ${CAPITAL_INICIAL:>10,.0f}")
    print(f"  Capital final:       ${cap_final:>10,.0f}")
    print(f"  Retorno 2 años:      {retorno_g:>+10.1f}%")
    print(f"  Total operaciones:   {total_g:>10}")
    print(f"  Ganadas:             {ganas_g:>10} ({winrate_g}%)")
    print(f"  Perdidas:            {pierdes_g:>10} ({round(pierdes_g/total_g*100,1)}%)")
    print(f"  P&L neto:            ${ganancia_g:>+10,.0f}")
    print(f"  Duración media:      {dur_media:>10} días")

    print(f"\n  {'─'*45}")
    print(f"  {'TICKER':<10} {'OPS':>5} {'WIN%':>7} {'P&L':>10} {'RETORNO':>9}")
    print(f"  {'─'*45}")
    for t, r in resumen_por_ticker.items():
        print(f"  {t:<10} {r['total']:>5} {r['winrate']:>6.1f}% ${r['ganancia_total']:>+8,.0f} {r['retorno_pct']:>+8.1f}%")
    print(f"  {'─'*45}")

    # Advertencia si win rate bajo
    if winrate_g < 40:
        print(f"\n  ⚠️  Win rate bajo ({winrate_g}%). Revisar parámetros antes de operar en real.")
    elif winrate_g >= 50:
        print(f"\n  ✅ Win rate sólido ({winrate_g}%) con ratio 1:2 — sistema viable.")

    # Guardar resultados
    with open("/home/enter/trading_system/backtest_resultado.json","w") as f:
        json.dump({"global":{"total":total_g,"ganas":ganas_g,"pierdes":pierdes_g,
            "winrate":winrate_g,"ganancia":round(ganancia_g,2),
            "capital_final":round(cap_final,2),"retorno_pct":retorno_g},
            "por_ticker":resumen_por_ticker}, f, indent=2, default=str)
    print(f"\n  Resultados guardados en backtest_resultado.json")

print(f"{'='*55}\n")
