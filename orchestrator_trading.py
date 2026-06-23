import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.agent1_scanner    import ScannerPatrones
from agents.agent2_estratega  import EstrategaContexto
from agents.agent3_indicadores import AnalistaIndicadores
from agents.agent4_riesgo     import GestorRiesgo
from agents.agent5_ejecutor   import EjecutorOrdenes
from agents.agent6_vigilante  import VigianteTrade
from datetime import datetime

try:
    from vix_filter      import evaluar_vix
    from telegram_alerts import alerta_senal, alerta_cierre, alerta_circuit_breaker, alerta_resumen_diario
    _EXTRAS_OK = True
except ImportError:
    _EXTRAS_OK = False
    def evaluar_vix(): return {"operar": True, "factor_size": 1.0, "nivel": "NORMAL", "mensaje": "VIX no disponible"}
    def alerta_senal(o): pass
    def alerta_cierre(t, r, m=""): pass
    def alerta_circuit_breaker(p, c): pass
    def alerta_resumen_diario(s): pass

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

        # VIX FILTER — el mejor trader no opera en pánico
        vix_estado = evaluar_vix()
        print(f"[0/6] VIX: {vix_estado['mensaje']}")
        if not vix_estado["operar"]:
            alerta_circuit_breaker(0, self.capital)
            print("  Sistema en pausa por condiciones de mercado extremas.")
            return 0
        factor_vix = vix_estado["factor_size"]

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

            # Aplicar factor VIX al tamaño si hay precaución
            if factor_vix < 1.0:
                orden.tamano_posicion = round(orden.tamano_posicion * factor_vix, 4)
                orden.capital_en_riesgo = round(orden.capital_en_riesgo * factor_vix, 2)
                print(f"  ⚠️ Tamaño reducido al {factor_vix*100:.0f}% por VIX elevado")

            self.gestor.registrar_apertura(orden)
            self.posiciones_abiertas.append({
                "ticker": patron.ticker, "direccion": patron.direccion,
                "precio_entrada": orden.precio_entrada,
                "stop_loss": orden.stop_loss, "take_profit": orden.take_profit
            })
            alerta_senal(orden)  # Telegram a suscriptores
            print(f"  ✅ ORDEN EJECUTADA | ID: {resultado.order_id}")
            ordenes += 1

        if self.posiciones_abiertas:
            print(f"\n[6/6] Vigilando {len(self.posiciones_abiertas)} posición(es)...")
            for estado in self.vigilante.vigilar_todas(self.posiciones_abiertas):
                print(f"  {estado.ticker}: {estado.estado} | PnL: {estado.pnl_actual:+.2f}%")
                if estado.accion == "cerrar":
                    self.posiciones_abiertas = [p for p in self.posiciones_abiertas if p['ticker'] != estado.ticker]
                    self.gestor.registrar_cierre(estado.ticker, estado.pnl_actual)
                    alerta_cierre(estado.ticker, estado.pnl_actual, estado.estado)

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
