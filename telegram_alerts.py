"""
Alertas Telegram — Trading System IA
Envía señales en tiempo real al canal de suscriptores.
Funciona sin token (modo silencioso) para no romper el sistema.
"""
import os, json, requests, logging
from datetime import datetime

logger = logging.getLogger("telegram_alerts")

BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID  = os.getenv("TELEGRAM_CHANNEL_ID", "")  # @micanaltrading o -100xxxxxxxxx

def _send(texto: str) -> bool:
    if not BOT_TOKEN or not CHANNEL_ID:
        logger.info(f"[TELEGRAM-OFF] {texto[:80]}")
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": CHANNEL_ID,
            "text": texto,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=8)
        return r.status_code == 200
    except Exception as e:
        logger.warning(f"Telegram error: {e}")
        return False

def alerta_senal(orden) -> bool:
    emoji = "🟢 LONG" if orden.direccion == "long" else "🔴 SHORT"
    texto = (
        f"<b>📊 SEÑAL VALIDADA — Trading IA</b>\n\n"
        f"{emoji} <b>{orden.ticker}</b>\n"
        f"💵 Entrada: <b>${orden.precio_entrada:.2f}</b>\n"
        f"🛑 Stop Loss: <b>${orden.stop_loss:.2f}</b> ({abs(orden.precio_entrada-orden.stop_loss)/orden.precio_entrada*100:.1f}%)\n"
        f"🎯 Take Profit: <b>${orden.take_profit:.2f}</b> ({abs(orden.take_profit-orden.precio_entrada)/orden.precio_entrada*100:.1f}%)\n"
        f"⚖️ Ratio RR: <b>1:{orden.ratio:.1f}</b>\n"
        f"📦 Tamaño: <b>{orden.tamano_posicion:.4f} acc</b>\n"
        f"💰 Capital en riesgo: <b>${orden.capital_en_riesgo:.2f} (1%)</b>\n\n"
        f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')} UTC\n"
        f"<i>Sistema: RSI(2) Mean Reversion | ATR(14) stops | v6.0</i>"
    )
    return _send(texto)

def alerta_cierre(ticker: str, resultado_usd: float, motivo: str = "") -> bool:
    emoji = "✅ GANADA" if resultado_usd >= 0 else "❌ PERDIDA"
    texto = (
        f"<b>{emoji} — {ticker}</b>\n\n"
        f"💰 Resultado: <b>{'+'if resultado_usd>=0 else ''}{resultado_usd:.2f} USD</b>\n"
        f"📝 Motivo cierre: {motivo}\n"
        f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')} UTC"
    )
    return _send(texto)

def alerta_circuit_breaker(perdida_mes: float, capital: float) -> bool:
    pct = perdida_mes / capital * 100
    texto = (
        f"<b>🚨 CIRCUIT BREAKER ACTIVADO</b>\n\n"
        f"Pérdida mensual: <b>-{pct:.1f}%</b>\n"
        f"Sistema <b>pausado</b> hasta el próximo mes.\n"
        f"Esto protege el capital según el plan de riesgo.\n\n"
        f"<i>Risk management primero — siempre.</i>"
    )
    return _send(texto)

def alerta_resumen_diario(stats: dict) -> bool:
    winrate = stats.get("winrate", 0) * 100
    pnl     = stats.get("pnl_total", 0)
    ops     = stats.get("total_operaciones", 0)
    texto = (
        f"<b>📈 RESUMEN DIARIO — Trading IA</b>\n\n"
        f"Operaciones: <b>{ops}</b>\n"
        f"Winrate acumulado: <b>{winrate:.1f}%</b>\n"
        f"P&L total: <b>{'+'if pnl>=0 else ''}{pnl:.2f} USD</b>\n\n"
        f"Activo estrella: <b>{stats.get('mejor_activo','—')}</b>\n"
        f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')} UTC\n"
        f"<i>Sistema activo y aprendiendo.</i>"
    )
    return _send(texto)
