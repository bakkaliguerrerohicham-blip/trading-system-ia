"""
Filtro VIX — El mejor trader del mundo no opera en pánico.
VIX > 30: mercado en fear, reducir tamaño.
VIX > 40: mercado en pánico, STOP total de nuevas entradas.
"""
import yfinance as yf
import logging

logger = logging.getLogger("vix_filter")

VIX_PRECAUCION = 25.0
VIX_STOP       = 35.0

def get_vix() -> float:
    try:
        df = yf.download("^VIX", period="2d", interval="1d", progress=False, auto_adjust=True)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return float(df["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"VIX no disponible: {e}")
        return 20.0  # valor neutral si falla

def evaluar_vix() -> dict:
    vix = get_vix()

    if vix >= VIX_STOP:
        return {
            "vix": round(vix, 2),
            "nivel": "PANICO",
            "operar": False,
            "reducir_size": True,
            "factor_size": 0.0,
            "mensaje": f"VIX={vix:.1f} — PÁNICO de mercado. Sin nuevas entradas."
        }
    elif vix >= VIX_PRECAUCION:
        factor = 1.0 - ((vix - VIX_PRECAUCION) / (VIX_STOP - VIX_PRECAUCION)) * 0.6
        return {
            "vix": round(vix, 2),
            "nivel": "PRECAUCION",
            "operar": True,
            "reducir_size": True,
            "factor_size": round(factor, 2),
            "mensaje": f"VIX={vix:.1f} — Precaución: tamaño reducido a {factor*100:.0f}%"
        }
    else:
        return {
            "vix": round(vix, 2),
            "nivel": "NORMAL",
            "operar": True,
            "reducir_size": False,
            "factor_size": 1.0,
            "mensaje": f"VIX={vix:.1f} — Mercado en calma. Operar normal."
        }
