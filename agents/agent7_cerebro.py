"""
Agente 7 — Cerebro (Feedback Learning Loop)

Es el último eslabón del ciclo. Tras cada operación cerrada:
1. Lee el historial completo (trade_log.json)
2. Analiza qué umbrales generaron mejores resultados
3. Ajusta los parámetros automáticamente (params_live.json)
4. El Scanner (A01) y los demás leen esos parámetros en el próximo ciclo

Esto convierte el sistema en un bucle cerrado de aprendizaje continuo.
"""

import json
import os
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADE_LOG  = os.path.join(BASE, "trade_log.json")
PARAMS     = os.path.join(BASE, "params_live.json")
CEREBRO_LOG = os.path.join(BASE, "cerebro_historial.json")


@dataclass
class InsightCerebro:
    ajuste_realizado: bool
    rsi2_anterior: float
    rsi2_nuevo: float
    stoch_anterior: float
    stoch_nuevo: float
    winrate_actual: float
    total_ops: int
    razon: str
    timestamp: str


class Cerebro:
    """
    Aprende de los resultados y ajusta los parámetros del sistema.
    Cada vez que hay suficientes operaciones nuevas, analiza y optimiza.
    """

    def __init__(self):
        self.params    = self._leer_params()
        self.trade_log = self._leer_log()

    def _leer_params(self):
        if os.path.exists(PARAMS):
            with open(PARAMS) as f:
                return json.load(f)
        return {}

    def _leer_log(self):
        if os.path.exists(TRADE_LOG):
            with open(TRADE_LOG) as f:
                return json.load(f)
        return {"operaciones": [], "resumen": {}}

    def _guardar_params(self):
        self.params["_ultima_actualizacion"] = datetime.now().isoformat()
        self.params["_actualizaciones"] = self.params.get("_actualizaciones", 0) + 1
        with open(PARAMS, "w") as f:
            json.dump(self.params, f, indent=2, ensure_ascii=False)

    def _guardar_insight(self, insight: InsightCerebro):
        historial = []
        if os.path.exists(CEREBRO_LOG):
            try:
                with open(CEREBRO_LOG) as f:
                    historial = json.load(f)
            except:
                historial = []
        historial.append(asdict(insight))
        with open(CEREBRO_LOG, "w") as f:
            json.dump(historial, f, indent=2, ensure_ascii=False)

    def analizar_umbrales(self, ops: List[Dict]) -> Dict:
        """
        Divide las operaciones en grupos según el RSI2 de entrada
        y compara winrates para encontrar el umbral óptimo.
        """
        buckets = {
            "rsi2_0_3":  {"ganadas": 0, "total": 0},
            "rsi2_3_5":  {"ganadas": 0, "total": 0},
            "rsi2_5_8":  {"ganadas": 0, "total": 0},
        }

        for op in ops:
            r = op.get("rsi2_entrada", 99)
            ganada = op.get("resultado") == "ganada"
            if r < 3:
                k = "rsi2_0_3"
            elif r < 5:
                k = "rsi2_3_5"
            else:
                k = "rsi2_5_8"
            buckets[k]["total"] += 1
            if ganada:
                buckets[k]["ganadas"] += 1

        return {
            k: {"winrate": v["ganadas"] / v["total"] if v["total"] > 0 else 0, **v}
            for k, v in buckets.items()
        }

    def calcular_rsi2_optimo(self, analisis: Dict) -> float:
        """
        Si el bloque rsi2_0_3 tiene winrate > 10pp sobre rsi2_5_8,
        baja el umbral (más exigente). Si no hay diferencia, sube ligeramente.
        """
        wr_bajo  = analisis.get("rsi2_0_3", {}).get("winrate", 0)
        wr_medio = analisis.get("rsi2_3_5", {}).get("winrate", 0)
        wr_alto  = analisis.get("rsi2_5_8", {}).get("winrate", 0)

        umbral_actual = self.params["umbrales"]["rsi2_entrada"]
        ajuste_max    = self.params["aprendizaje"]["ajuste_max_rsi2"]

        # Si RSI muy bajo da mejores resultados → bajar umbral
        if wr_bajo > wr_alto + 0.10 and analisis["rsi2_0_3"]["total"] >= 3:
            nuevo = max(3.0, umbral_actual - 1.0)
            return round(min(nuevo, umbral_actual), 1)

        # Si no hay diferencia significativa → mantener o subir ligeramente
        if wr_alto > 0 and wr_alto >= wr_bajo - 0.05:
            nuevo = min(10.0, umbral_actual + 0.5)
            return round(min(nuevo, umbral_actual + ajuste_max), 1)

        return umbral_actual

    def actualizar_estadisticas(self, ops: List[Dict]):
        """Actualiza el bloque estadísticas_actuales en params_live.json"""
        total    = len(ops)
        ganadas  = sum(1 for o in ops if o.get("resultado") == "ganada")
        perdidas = total - ganadas
        pnl      = sum(o.get("pnl_usd", 0) for o in ops)

        # PnL por activo
        por_activo: Dict[str, Dict] = {}
        for op in ops:
            t = op.get("ticker", "?")
            if t not in por_activo:
                por_activo[t] = {"ganadas": 0, "total": 0, "pnl": 0}
            por_activo[t]["total"] += 1
            por_activo[t]["pnl"]   += op.get("pnl_usd", 0)
            if op.get("resultado") == "ganada":
                por_activo[t]["ganadas"] += 1

        for t in por_activo:
            d = por_activo[t]
            d["winrate"] = round(d["ganadas"] / d["total"], 3) if d["total"] else 0

        mejor  = max(por_activo, key=lambda t: por_activo[t]["winrate"], default=None)
        peor   = min(por_activo, key=lambda t: por_activo[t]["winrate"], default=None)

        # PnL del mes actual
        mes_actual = datetime.now().strftime("%Y-%m")
        pnl_mes = sum(
            o.get("pnl_usd", 0) for o in ops
            if o.get("fecha_salida", "")[:7] == mes_actual
        )

        self.params["estadisticas_actuales"] = {
            "total_operaciones": total,
            "ganadas":           ganadas,
            "perdidas":          perdidas,
            "winrate":           round(ganadas / total, 4) if total else 0.0,
            "pnl_total":         round(pnl, 2),
            "pnl_mes":           round(pnl_mes, 2),
            "mejor_activo":      mejor,
            "peor_activo":       peor,
            "por_activo":        por_activo
        }

    def evaluar_y_aprender(self) -> InsightCerebro:
        ops = self.trade_log.get("operaciones", [])
        min_ops = self.params.get("aprendizaje", {}).get("min_ops_para_ajuste", 5)

        rsi2_ant  = self.params["umbrales"]["rsi2_entrada"]
        stoch_ant = self.params["umbrales"]["stoch_entrada"]

        # Actualizar siempre las estadísticas
        self.actualizar_estadisticas(ops)

        if len(ops) < min_ops:
            self._guardar_params()
            insight = InsightCerebro(
                ajuste_realizado=False,
                rsi2_anterior=rsi2_ant, rsi2_nuevo=rsi2_ant,
                stoch_anterior=stoch_ant, stoch_nuevo=stoch_ant,
                winrate_actual=self.params["estadisticas_actuales"]["winrate"],
                total_ops=len(ops),
                razon=f"Solo {len(ops)} ops — mínimo {min_ops} para ajustar parámetros",
                timestamp=datetime.now().isoformat()
            )
            self._guardar_insight(insight)
            return insight

        # Analizar y ajustar umbrales
        analisis   = self.analizar_umbrales(ops)
        rsi2_nuevo = self.calcular_rsi2_optimo(analisis)

        # Ajuste Stochastic: si stoch < 15 tiene mejor WR que stoch 15-25, bajar
        ops_stoch_bajo = [o for o in ops if o.get("stoch_entrada", 99) < 15]
        ops_stoch_alto = [o for o in ops if 15 <= o.get("stoch_entrada", 99) < 25]

        stoch_nuevo = stoch_ant
        if len(ops_stoch_bajo) >= 3 and len(ops_stoch_alto) >= 3:
            wr_stoch_bajo = sum(1 for o in ops_stoch_bajo if o.get("resultado") == "ganada") / len(ops_stoch_bajo)
            wr_stoch_alto = sum(1 for o in ops_stoch_alto if o.get("resultado") == "ganada") / len(ops_stoch_alto)
            if wr_stoch_bajo > wr_stoch_alto + 0.10:
                stoch_nuevo = max(15.0, stoch_ant - 2.0)

        ajuste = (rsi2_nuevo != rsi2_ant) or (stoch_nuevo != stoch_ant)

        if ajuste:
            self.params["umbrales"]["rsi2_entrada"]  = rsi2_nuevo
            self.params["umbrales"]["stoch_entrada"] = stoch_nuevo

        self._guardar_params()

        winrate = self.params["estadisticas_actuales"]["winrate"]
        razon = (
            f"WR={winrate:.1%} con {len(ops)} ops. "
            + (f"RSI2: {rsi2_ant}→{rsi2_nuevo}. " if rsi2_nuevo != rsi2_ant else "RSI2 sin cambio. ")
            + (f"Stoch: {stoch_ant}→{stoch_nuevo}." if stoch_nuevo != stoch_ant else "Stoch sin cambio.")
        )

        insight = InsightCerebro(
            ajuste_realizado=ajuste,
            rsi2_anterior=rsi2_ant, rsi2_nuevo=rsi2_nuevo,
            stoch_anterior=stoch_ant, stoch_nuevo=stoch_nuevo,
            winrate_actual=winrate,
            total_ops=len(ops),
            razon=razon,
            timestamp=datetime.now().isoformat()
        )
        self._guardar_insight(insight)
        return insight


# ─── REGISTRO DE OPERACIÓN NUEVA ──────────────────────────────────────────────
def registrar_operacion(
    ticker: str,
    tipo: str,
    precio_entrada: float,
    precio_salida: float,
    sl: float,
    tp: float,
    tamano: float,
    rsi2_entrada: float,
    stoch_entrada: float,
    macd_hist_entrada: float,
    razon_cierre: str,
    duracion_dias: int = 1,
    version_params: str = "v6.0"
):
    """
    Llamar desde agent5_ejecutor.py cuando se cierra una posición.
    Añade la operación al log y lanza el ciclo de aprendizaje del Cerebro.
    """
    pnl_pct = round((precio_salida - precio_entrada) / precio_entrada * 100, 4)
    pnl_usd = round(tamano * (precio_salida - precio_entrada), 4)
    resultado = "ganada" if pnl_usd > 0 else "perdida"

    log = {"operaciones": [], "resumen": {}}
    if os.path.exists(TRADE_LOG):
        with open(TRADE_LOG) as f:
            log = json.load(f)

    import random, string
    op_id = "OP-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    ahora = datetime.now().isoformat()

    nueva_op = {
        "id":              op_id,
        "ticker":          ticker,
        "tipo":            tipo,
        "fecha_entrada":   (datetime.now() - timedelta(days=duracion_dias)).isoformat(),
        "fecha_salida":    ahora,
        "precio_entrada":  precio_entrada,
        "precio_salida":   precio_salida,
        "sl":              sl,
        "tp":              tp,
        "tamano":          tamano,
        "pnl_usd":         pnl_usd,
        "pnl_pct":         pnl_pct,
        "resultado":       resultado,
        "rsi2_entrada":    rsi2_entrada,
        "stoch_entrada":   stoch_entrada,
        "macd_hist_entrada": macd_hist_entrada,
        "duracion_dias":   duracion_dias,
        "razon_cierre":    razon_cierre,
        "version_params":  version_params
    }

    log["operaciones"].append(nueva_op)
    total   = len(log["operaciones"])
    ganadas = sum(1 for o in log["operaciones"] if o.get("resultado") == "ganada")
    pnl_t   = sum(o.get("pnl_usd", 0) for o in log["operaciones"])

    log["resumen"] = {
        "total": total, "ganadas": ganadas,
        "perdidas": total - ganadas,
        "winrate": round(ganadas / total, 4),
        "pnl_total": round(pnl_t, 4)
    }

    with open(TRADE_LOG, "w") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    # Lanzar ciclo de aprendizaje automáticamente
    cerebro = Cerebro()
    return cerebro.evaluar_y_aprender()


if __name__ == "__main__":
    print("=" * 55)
    print(" AGENTE 7 — CEREBRO · Ciclo de aprendizaje")
    print("=" * 55)
    c = Cerebro()
    insight = c.evaluar_y_aprender()
    print(f"\n  Operaciones analizadas : {insight.total_ops}")
    print(f"  WinRate actual         : {insight.winrate_actual:.1%}")
    print(f"  RSI2 umbral            : {insight.rsi2_anterior} → {insight.rsi2_nuevo}")
    print(f"  Stoch umbral           : {insight.stoch_anterior} → {insight.stoch_nuevo}")
    print(f"  Ajuste realizado       : {'SÍ' if insight.ajuste_realizado else 'NO'}")
    print(f"\n  Razón: {insight.razon}")
    print("=" * 55)
