"""
API Flask — Trading IA
Conecta el panel.html con el orquestador real.
"""
import sys, os, json, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
from orchestrator_trading import OrquestadorTrading
from datetime import datetime

app = Flask(__name__, static_folder="dashboard")
CORS(app)

# Orquestador singleton
orq = OrquestadorTrading(capital=10000.0, modo="paper")
_lock = threading.Lock()
_ciclos_ejecutados = 0
_loop_activo = False
_loop_thread = None

@app.route("/")
def panel():
    return send_from_directory("dashboard", "panel.html")

@app.route("/api/estado")
def estado():
    with _lock:
        stats = orq.gestor.obtener_estadisticas() if hasattr(orq.gestor, 'obtener_estadisticas') else {}
        return jsonify({
            "timestamp": datetime.now().isoformat(),
            "modo": orq.modo,
            "capital": orq.capital,
            "posiciones_abiertas": len(orq.posiciones_abiertas),
            "posiciones": orq.posiciones_abiertas,
            "ciclos_ejecutados": _ciclos_ejecutados,
            "stats": stats,
        })

@app.route("/api/ciclo", methods=["POST"])
def ciclo():
    def _run():
        global _ciclos_ejecutados
        with _lock:
            orq.ejecutar_ciclo()
            _ciclos_ejecutados += 1
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "mensaje": "Ciclo iniciado en el orquestador real"})

@app.route("/api/loop", methods=["POST"])
def loop_toggle():
    global _loop_thread, _loop_activo
    data = request.get_json() or {}
    accion = data.get("accion", "iniciar")
    if accion == "iniciar" and not _loop_activo:
        _loop_activo = True
        def _run_loop():
            global _ciclos_ejecutados, _loop_activo
            import time
            while _loop_activo:
                with _lock:
                    orq.ejecutar_ciclo()
                    _ciclos_ejecutados += 1
                time.sleep(15 * 60)
        _loop_thread = threading.Thread(target=_run_loop, daemon=True)
        _loop_thread.start()
        return jsonify({"ok": True, "mensaje": "Loop iniciado — ciclo cada 15 min"})
    else:
        _loop_activo = False
        return jsonify({"ok": True, "mensaje": "Sistema detenido"})

@app.route("/api/mercados")
def mercados():
    try:
        from agents.agent1_scanner import ScannerPatrones
        s = ScannerPatrones()
        precios = {}
        for ticker in s.tickers:
            df = s.obtener_datos(ticker, periodo="1d", intervalo="1m")
            if not df.empty:
                precio = float(df["Close"].iloc[-1])
                prev   = float(df["Close"].iloc[0])
                chg    = round((precio - prev) / prev * 100, 2)
                precios[ticker] = {"precio": round(precio, 2), "cambio": chg}
        return jsonify({"ok": True, "mercados": precios, "ts": datetime.now().isoformat()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/historial")
def historial():
    with _lock:
        return jsonify({
            "ciclos": orq.historial_ciclos[-50:],
            "total": len(orq.historial_ciclos)
        })

@app.route("/api/backtest")
def backtest():
    try:
        path = os.path.join(os.path.dirname(__file__), "backtest_resultado.json")
        with open(path) as f:
            return jsonify(json.load(f))
    except:
        return jsonify({"error": "Sin datos de backtest"}), 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print(f"Trading IA API — puerto {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
