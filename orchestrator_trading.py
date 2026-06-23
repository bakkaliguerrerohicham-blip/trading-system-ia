import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.agent1_scanner    import ScannerPatrones
from agents.agent2_estratega  import EstrategaContexto
from agents.agent3_indicadores import AnalistaIndicadores
from agents.agent4_riesgo     import GestorRiesgo
from agents.agent5_ejecutor   import EjecutorOrdenes
from agents.agent6_vigilante  import VigianteTrade
from datetime import datetime

class OrquestadorTrading:
    def __init__(self, capital=10000.0, modo="paper"):
        self.capital = capital
        self.modo = modo
        self.posiciones_abiertas = []
        self.scanner    = ScannerPatrones()
        self.estratega  = EstrategaContexto()
        self.analista   = AnalistaIndicadores()
        self.gestor     = GestorRiesgo(capital=capital)
        self.ejecutor   = EjecutorOrdenes(modo=modo)
        self.vigilante  = VigianteTrade()
        print(f"\n{'='*50}")
        print(f"  SISTEMA DE TRADING IA — IMPACTO DIGITAL")
        print(f"  Capital: ${capital:,.0f} | Modo: {modo.upper()}")
        print(f"  Mercados: ES Futuros · TSLA · NVDA")
        print(f"{'='*50}\n")

    def ejecutar_ciclo(self):
        t0 = datetime.now()
        ordenes = 0
        print(f"[{t0.strftime('%H:%M:%S')}] Iniciando ciclo...\n")

        print("[1/6] Escaneando patrones...")
        patrones = self.scanner.escanear_todos()
        if not patrones:
            print("  Sin patrones detectados.\n")
            return 0

        for patron in patrones:
            print(f"\n  Patrón: {patron.ticker} | {patron.descripcion} | Fuerza: {patron.fuerza}")

            print("[2/6] Contexto...")
            ctx = self.estratega.evaluar(patron)
            if not ctx.aprobado:
                print(f"  ❌ Bloqueado: {ctx.razon_bloqueo}"); continue
            print(f"  ✅ Sesión: {ctx.sesion_activa}")

            print("[3/6] Indicadores...")
            analisis = self.analista.analizar(patron.ticker, patron.direccion)
            if not analisis.aprobado:
                print(f"  ❌ {analisis.confirmaciones}/4 confirmaciones | {analisis.detalles}"); continue
            print(f"  ✅ {analisis.confirmaciones}/4 | {analisis.detalles}")

            print("[4/6] Riesgo...")
            orden = self.gestor.calcular(patron, patron.soporte, patron.resistencia)
            if not orden.aprobado:
                print(f"  ❌ {orden.razon_bloqueo}"); continue
            print(f"  ✅ Entrada:${orden.precio_entrada} SL:${orden.stop_loss} TP:${orden.take_profit} Ratio:{orden.ratio}")

            print("[5/6] Ejecutando orden...")
            resultado = self.ejecutor.ejecutar(orden)
            if not resultado.ok:
                print(f"  ❌ {resultado.mensaje}"); continue

            self.gestor.registrar_apertura(orden)
            self.posiciones_abiertas.append({
                "ticker": patron.ticker, "direccion": patron.direccion,
                "precio_entrada": orden.precio_entrada,
                "stop_loss": orden.stop_loss, "take_profit": orden.take_profit
            })
            print(f"  ✅ ORDEN EJECUTADA | ID: {resultado.order_id}")
            ordenes += 1

        if self.posiciones_abiertas:
            print(f"\n[6/6] Vigilando {len(self.posiciones_abiertas)} posición(es)...")
            for estado in self.vigilante.vigilar_todas(self.posiciones_abiertas):
                print(f"  {estado.ticker}: {estado.estado} | PnL: {estado.pnl_actual:+.2f}%")
                if estado.accion == "cerrar":
                    self.posiciones_abiertas = [p for p in self.posiciones_abiertas if p['ticker'] != estado.ticker]
                    self.gestor.registrar_cierre(estado.ticker, estado.pnl_actual)

        seg = int((datetime.now()-t0).total_seconds())
        print(f"\n[Ciclo completado en {seg}s | Órdenes: {ordenes}]\n")
        return ordenes

    def loop(self, intervalo_min=15):
        print(f"Loop activo — ciclo cada {intervalo_min} min. Ctrl+C para parar.\n")
        while True:
            try:
                self.ejecutar_ciclo()
                time.sleep(intervalo_min * 60)
            except KeyboardInterrupt:
                print("\nSistema detenido."); break
            except Exception as e:
                print(f"Error en ciclo: {e}")
                time.sleep(60)

if __name__ == "__main__":
    orq = OrquestadorTrading(capital=10000.0, modo="paper")
    orq.ejecutar_ciclo()
