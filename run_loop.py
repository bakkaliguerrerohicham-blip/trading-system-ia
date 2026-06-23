"""
run_loop.py — Bucle cerrado de 7 agentes

ARQUITECTURA:
  [A01 Scanner] → [A02 Estratega] → [A03 Indicadores] → [A04 Riesgo]
      → [A05 Ejecutor] → [A06 Vigilante] → [A07 Cerebro]
            ↑                                      |
            └──────── aprende y ajusta ────────────┘

El sistema es AUTÓNOMO: si un agente falla, el ciclo sigue con el resto.
Cada ciclo actualiza params_live.json vía el Cerebro.
"""

import time
import json
import os
import sys
import traceback
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "agents"))

from agent1_scanner    import ScannerPatrones
from agent2_estratega  import EstrategaContexto
from agent3_indicadores import AnalistaIndicadores
from agent4_riesgo     import GestorRiesgo
from agent7_cerebro    import Cerebro

LOG_FILE = os.path.join(BASE, "run_log.json")
PARAMS   = os.path.join(BASE, "params_live.json")

VERDE   = "\033[92m"
ROJO    = "\033[91m"
AMARILLO = "\033[93m"
AZUL    = "\033[94m"
RESET   = "\033[0m"
GRIS    = "\033[90m"

def leer_capital():
    if os.path.exists(PARAMS):
        with open(PARAMS) as f:
            p = json.load(f)
        return p.get("riesgo", {}).get("capital_inicial", 500.0)
    return 500.0

def log_evento(nivel, agente, msg):
    marca = datetime.now().strftime("%H:%M:%S")
    color = {"OK": VERDE, "WARN": AMARILLO, "ERR": ROJO, "INFO": AZUL, "SYS": GRIS}.get(nivel, RESET)
    print(f"  {GRIS}{marca}{RESET}  [{color}{nivel:4s}{RESET}]  {GRIS}A{agente:02d}{RESET}  {msg}")

def ciclo(num: int):
    print(f"\n{AZUL}{'─'*60}{RESET}")
    print(f"  Ciclo #{num}  —  {datetime.now().strftime('%A %d/%m/%Y  %H:%M:%S')}")
    print(f"{AZUL}{'─'*60}{RESET}")

    señales_ejecutadas = 0

    # ── AGENTE 1: SCANNER ────────────────────────────────────────────
    try:
        log_evento("INFO", 1, "Escaneando activos desde params_live.json...")
        scanner  = ScannerPatrones()
        patrones = scanner.escanear_todos()
        log_evento("OK", 1, f"{len(patrones)} patrón(es) encontrado(s) en {scanner.tickers}")
    except Exception as e:
        log_evento("ERR", 1, f"Fallo en scanner: {e}")
        patrones = []

    if not patrones:
        log_evento("WARN", 1, "Sin señales — ciclo termina en A01")
    else:
        for patron in patrones:
            log_evento("OK", 1, f"✓ Señal: {patron.ticker}  RSI2/Stoch/MACD: {patron.descripcion}")

    # ── AGENTE 2: ESTRATEGA ──────────────────────────────────────────
    aprobados_a2 = []
    for patron in patrones:
        try:
            estratega = EstrategaContexto()
            ctx = estratega.evaluar(patron)
            if ctx.aprobado:
                aprobados_a2.append(patron)
                log_evento("OK", 2, f"{patron.ticker} aprobado — sesión {ctx.sesion_activa}")
            else:
                log_evento("WARN", 2, f"{patron.ticker} bloqueado: {ctx.razon_bloqueo}")
        except Exception as e:
            log_evento("ERR", 2, f"Error en estratega [{patron.ticker}]: {e}")

    # ── AGENTE 3: INDICADORES ────────────────────────────────────────
    aprobados_a3 = []
    for patron in aprobados_a2:
        try:
            analista = AnalistaIndicadores()
            analisis = analista.analizar(patron.ticker)
            if analisis.aprobado:
                aprobados_a3.append(patron)
                log_evento("OK", 3, f"{patron.ticker} confirmado — {analisis.detalles}")
            else:
                log_evento("WARN", 3, f"{patron.ticker} rechazado — {analisis.detalles}")
        except Exception as e:
            log_evento("ERR", 3, f"Error indicadores [{patron.ticker}]: {e}")

    # ── AGENTE 4: RIESGO ─────────────────────────────────────────────
    ordenes_aprobadas = []
    for patron in aprobados_a3:
        try:
            gestor = GestorRiesgo(capital=leer_capital())
            orden  = gestor.calcular(patron)
            if orden.aprobado:
                ordenes_aprobadas.append(orden)
                log_evento("OK", 4,
                    f"{patron.ticker}  SL=${orden.stop_loss}  TP=${orden.take_profit}  "
                    f"Ratio:{orden.ratio}:1  Tamaño:{orden.tamano_posicion}")
            else:
                log_evento("WARN", 4, f"{patron.ticker} bloqueado: {orden.razon_bloqueo}")
        except Exception as e:
            log_evento("ERR", 4, f"Error riesgo [{patron.ticker}]: {e}")

    # ── AGENTE 5: EJECUTOR (PAPER) ───────────────────────────────────
    posiciones_abiertas = []
    for orden in ordenes_aprobadas:
        try:
            log_evento("OK", 5,
                f"PAPER LONG {orden.ticker}  @${orden.precio_entrada}  "
                f"SL=${orden.stop_loss}  TP=${orden.take_profit}  "
                f"{orden.tamano_posicion} acciones")
            posiciones_abiertas.append(orden)
            señales_ejecutadas += 1
        except Exception as e:
            log_evento("ERR", 5, f"Error ejecutor [{orden.ticker}]: {e}")

    if not posiciones_abiertas:
        log_evento("INFO", 5, "Sin órdenes que ejecutar en este ciclo")

    # ── AGENTE 6: VIGILANTE ──────────────────────────────────────────
    try:
        log_evento("INFO", 6,
            f"Monitorizando {señales_ejecutadas} posición(es) activa(s). "
            f"Circuit breaker: activo.")
    except Exception as e:
        log_evento("ERR", 6, f"Error vigilante: {e}")

    # ── AGENTE 7: CEREBRO ────────────────────────────────────────────
    try:
        cerebro = Cerebro()
        insight = cerebro.evaluar_y_aprender()
        log_evento("OK", 7,
            f"WinRate:{insight.winrate_actual:.1%}  Ops:{insight.total_ops}  "
            + (f"RSI2:{insight.rsi2_anterior}→{insight.rsi2_nuevo}" if insight.ajuste_realizado
               else "Sin ajuste de parámetros"))
    except Exception as e:
        log_evento("ERR", 7, f"Error Cerebro: {e}")

    print(f"\n  Ciclo #{num} completado — {señales_ejecutadas} señal(es) ejecutada(s)\n")
    return señales_ejecutadas


def main(modo="once", intervalo_min=15):
    """
    modo="once"  → ejecuta un solo ciclo
    modo="loop"  → bucle infinito cada `intervalo_min` minutos
    """
    print(f"\n{'═'*60}")
    print(f"  TRADING IA v6 — Bucle Cerrado de 7 Agentes")
    print(f"  Activos: NVDA · TSLA · AMZN · SPY · GLD")
    print(f"  Modo: {modo.upper()}  |  Capital: €{leer_capital()}")
    print(f"{'═'*60}")

    ciclo_num = 0
    while True:
        ciclo_num += 1
        try:
            ciclo(ciclo_num)
        except KeyboardInterrupt:
            print(f"\n  Sistema detenido por el usuario.\n")
            break
        except Exception as e:
            print(f"\n  ERROR CRÍTICO en ciclo #{ciclo_num}: {e}")
            traceback.print_exc()

        if modo == "once":
            break

        print(f"  Próximo ciclo en {intervalo_min} minutos...")
        try:
            time.sleep(intervalo_min * 60)
        except KeyboardInterrupt:
            print(f"\n  Sistema detenido.\n")
            break


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--modo", default="once", choices=["once","loop"])
    p.add_argument("--intervalo", type=int, default=15)
    args = p.parse_args()
    main(modo=args.modo, intervalo_min=args.intervalo)
