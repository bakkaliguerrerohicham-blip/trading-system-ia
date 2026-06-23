from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

@dataclass
class ContextoMercado:
    sesion_activa: str
    tendencia_dia: str
    riesgo_macro: bool
    razon_bloqueo: Optional[str]
    aprobado: bool
    hora_utc: str


class EstrategaContexto:
    # Ventanas horarias de riesgo macro (±30 min)
    HORAS_PELIGRO = [(13, 30), (14, 0), (15, 0), (18, 0)]

    # Activos validados v5 y sus sesiones óptimas
    SESIONES_OPTIMAS = {
        "SPY":     ["ny"],
        "QQQ":     ["ny"],
        "NVDA":    ["ny"],
        "BTC-USD": ["ny", "europa", "asia"],  # crypto: 24h, cualquier sesión
    }

    def sesion_activa(self, hora):
        if 0 <= hora < 8:    return "asia"
        elif 8 <= hora < 13: return "europa"
        elif 13 <= hora < 22: return "ny"
        return "sin_sesion"

    def detectar_riesgo_macro(self, ahora):
        hora, minuto = ahora.hour, ahora.minute
        for h, m in self.HORAS_PELIGRO:
            if hora == h and abs(minuto - m) <= 30:
                return True, f"Posible evento macro {h}:{m:02d} UTC"
        if ahora.weekday() == 4 and hora >= 19:
            return True, "Viernes tarde — liquidez reducida"
        return False, None

    def evaluar(self, patron):
        ahora  = datetime.now(timezone.utc)
        sesion = self.sesion_activa(ahora.hour)

        riesgo_macro, razon_macro = self.detectar_riesgo_macro(ahora)
        if riesgo_macro:
            return ContextoMercado(sesion, patron.direccion, True, razon_macro,
                                   False, ahora.strftime("%H:%M UTC"))

        optimas = self.SESIONES_OPTIMAS.get(patron.ticker, ["ny"])
        if sesion not in optimas:
            return ContextoMercado(sesion, patron.direccion, False,
                                   f"Sesión {sesion} no óptima para {patron.ticker}",
                                   False, ahora.strftime("%H:%M UTC"))

        return ContextoMercado(sesion, patron.direccion, False, None,
                               True, ahora.strftime("%H:%M UTC"))
