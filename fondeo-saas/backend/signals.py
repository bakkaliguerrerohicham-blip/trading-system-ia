"""
Motor de señales — genera la señal de cobertura 3x4.
Usa datos de precio reales vía yfinance o ccxt si están disponibles,
si no, usa lógica basada en ATR simulado para no bloquear el sistema.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from datetime import datetime, timezone
from typing import Optional
import math

# Intenta importar yfinance para precios reales
try:
    import yfinance as yf
    YFINANCE_OK = True
except ImportError:
    YFINANCE_OK = False


ACTIVOS_SOPORTADOS = {
    "BTC":    {"yf": "BTC-USD",   "pip": 1.0,   "atr_pct": 3.0},
    "XAUUSD": {"yf": "GC=F",      "pip": 0.1,   "atr_pct": 0.8},
    "US100":  {"yf": "NQ=F",      "pip": 0.25,  "atr_pct": 1.2},
    "EURUSD": {"yf": "EURUSD=X",  "pip": 0.0001,"atr_pct": 0.4},
}


def precio_actual(activo: str) -> Optional[float]:
    cfg = ACTIVOS_SOPORTADOS.get(activo)
    if not cfg or not YFINANCE_OK:
        return None
    try:
        t = yf.Ticker(cfg["yf"])
        hist = t.history(period="1d", interval="5m")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def calcular_atr(activo: str, precio: float) -> float:
    cfg = ACTIVOS_SOPORTADOS.get(activo, {})
    return precio * (cfg.get("atr_pct", 1.0) / 100)


def generar_senal(activo: str = "BTC", ratio: float = 4.0, riesgo_pct: float = 1.0) -> dict:
    """
    Devuelve los parámetros de la señal para LONG y SHORT simultáneos.
    Con ratio 4:1: TP = 4 × SL desde la entrada.
    """
    precio = precio_actual(activo)
    live   = precio is not None
    if not live:
        # Precios de referencia para operar sin conexión
        refs = {"BTC": 67000.0, "XAUUSD": 2350.0, "US100": 19500.0, "EURUSD": 1.085}
        precio = refs.get(activo, 100.0)

    atr = calcular_atr(activo, precio)
    sl_dist = round(atr * 0.5, 2)
    tp_dist = round(sl_dist * ratio, 2)

    return {
        "activo":       activo,
        "precio":       round(precio, 4),
        "precio_live":  live,
        "ratio":        ratio,
        "riesgo_pct":   riesgo_pct,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "long": {
            "entrada": round(precio, 4),
            "sl":      round(precio - sl_dist, 4),
            "tp":      round(precio + tp_dist, 4),
            "brokers": ["Broker A — Cuenta 1", "Broker A — Cuenta 2"],
        },
        "short": {
            "entrada": round(precio, 4),
            "sl":      round(precio + sl_dist, 4),
            "tp":      round(precio - tp_dist, 4),
            "brokers": ["Broker B — Cuenta 1", "Broker C — Cuenta 1"],
        },
        "instruccion": (
            f"Abre LONG en Broker A (x2) y SHORT en Broker B y C "
            f"al mismo tiempo. SL a {sl_dist:.2f} puntos, TP a {tp_dist:.2f} puntos. "
            f"Con ratio {ratio}:1 y riesgo {riesgo_pct}%, 2 trades ganadores = objetivo cumplido."
        ),
        "nota_tiempo_sin_limite": (
            "Sin límite de tiempo: si el mercado no tiene dirección hoy, NO operes. "
            "Espera a que el ATR supere el 1.5% diario antes de entrar."
        ),
    }


def evaluar_estado_par(pnl_a: float, pnl_b: float, target: float, dd_max: float) -> dict:
    """Evalúa el estado de un par y da la acción recomendada."""
    ganadora = "A" if pnl_a >= pnl_b else "B"
    perdedora = "B" if ganadora == "A" else "A"
    pnl_g = pnl_a if ganadora == "A" else pnl_b
    pnl_p = pnl_b if ganadora == "A" else pnl_a
    dd_consumido_pct = abs(pnl_p) / dd_max * 100 if pnl_p < 0 else 0

    if pnl_g >= target:
        accion = "APROBADA — cuenta ganadora superó el objetivo"
        fase = "fondeado"
    elif dd_consumido_pct >= 40:
        accion = f"PAUSAR cuenta {perdedora} — drawdown al {dd_consumido_pct:.0f}%"
        fase = "riesgo"
    elif dd_consumido_pct >= 20:
        accion = f"ALERTA — cuenta {perdedora} consume el {dd_consumido_pct:.0f}% del DD"
        fase = "alerta"
    else:
        accion = "OPERAR — ambas cuentas dentro de límites seguros"
        fase = "activa"

    return {
        "ganadora":        ganadora,
        "perdedora":       perdedora,
        "pnl_ganadora":    pnl_g,
        "pnl_perdedora":   pnl_p,
        "dd_consumido_pct": round(dd_consumido_pct, 1),
        "accion":          accion,
        "fase":            fase,
        "progreso_pct":    round(min(100, (pnl_g / target) * 100), 1) if pnl_g > 0 else 0,
    }
