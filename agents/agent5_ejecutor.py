import json, os
from datetime import datetime
from dataclasses import dataclass, asdict

@dataclass
class ResultadoEjecucion:
    ok: bool
    order_id: str
    ticker: str
    direccion: str
    precio_entrada: float
    stop_loss: float
    take_profit: float
    tamano: float
    modo: str
    mensaje: str
    timestamp: str

class EjecutorOrdenes:
    def __init__(self, modo="paper", log="/tmp/trading_log.json"):
        self.modo = modo
        self.log = log
        self.historial = self._cargar()

    def _cargar(self):
        if os.path.exists(self.log):
            try:
                with open(self.log) as f: return json.load(f)
            except: pass
        return []

    def _guardar(self):
        with open(self.log,'w') as f: json.dump(self.historial[-100:], f, indent=2, default=str)

    def ejecutar(self, orden):
        order_id = f"PAPER_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{orden.ticker}"
        r = ResultadoEjecucion(
            ok=True, order_id=order_id, ticker=orden.ticker,
            direccion=orden.direccion, precio_entrada=orden.precio_entrada,
            stop_loss=orden.stop_loss, take_profit=orden.take_profit,
            tamano=orden.tamano_posicion, modo=self.modo,
            mensaje=f"[{self.modo.upper()}] {orden.direccion.upper()} {orden.tamano_posicion} {orden.ticker} @ {orden.precio_entrada}",
            timestamp=datetime.now().isoformat()
        )
        self.historial.append(asdict(r))
        self._guardar()
        print(f"  [Ejecutor] {r.mensaje}")
        return r
