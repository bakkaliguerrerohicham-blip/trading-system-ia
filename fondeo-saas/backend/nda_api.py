"""
NDA API — Registro de firmas digitales del Método Fondeo Garantizado.
Cada firma queda registrada con timestamp, IP y datos del firmante.
"""
import sqlite3, json, os, smtplib
from datetime import datetime
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

DB = Path(__file__).parent / "ndas.db"

SENDGRID_KEY  = os.getenv("SENDGRID_API_KEY", "")
EMAIL_FROM    = os.getenv("EMAIL_FROM", "hichambakkaliguerrero@gmail.com")
WHATSAPP_LINK = os.getenv("WHATSAPP_LINK", "https://wa.me/34600000000")
CALENDLY_LINK = os.getenv("CALENDLY_LINK", "https://calendly.com/impacto-digital/fondeo-coaching")

def _con():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS ndas (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre    TEXT NOT NULL,
        email     TEXT NOT NULL,
        telefono  TEXT,
        timestamp TEXT,
        ip        TEXT,
        acepta_confidencialidad INTEGER DEFAULT 0,
        acepta_fee_exito        INTEGER DEFAULT 0,
        confirma_experiencia    INTEGER DEFAULT 0,
        estado    TEXT DEFAULT 'pendiente_sesion',
        notas     TEXT DEFAULT ''
    )""")
    c.commit()
    return c

def registrar_firma(datos: dict) -> dict:
    con = _con()
    try:
        cur = con.execute("""INSERT INTO ndas
            (nombre,email,telefono,timestamp,ip,acepta_confidencialidad,acepta_fee_exito,confirma_experiencia)
            VALUES (?,?,?,?,?,?,?,?)""", (
            datos.get("nombre",""),
            datos.get("email",""),
            datos.get("telefono",""),
            datos.get("timestamp", datetime.now().isoformat()),
            datos.get("ip_aprox",""),
            int(datos.get("acepta_confidencialidad", False)),
            int(datos.get("acepta_fee_exito", False)),
            int(datos.get("confirma_experiencia", False)),
        ))
        nda_id = cur.lastrowid
        con.commit()
    finally:
        con.close()

    _notificar_admin(datos)
    _email_bienvenida(datos)

    return {
        "ok": True,
        "nda_id": nda_id,
        "nombre": datos.get("nombre"),
        "email": datos.get("email"),
        "mensaje": "NDA registrado. Recibirás acceso completo en menos de 24h.",
        "siguiente_paso": f"Agenda tu sesión: {CALENDLY_LINK}",
        "contacto_directo": WHATSAPP_LINK
    }

def listar_firmas() -> list:
    con = _con()
    rows = con.execute("""SELECT id,nombre,email,telefono,timestamp,estado
        FROM ndas ORDER BY id DESC""").fetchall()
    con.close()
    return [{"id":r[0],"nombre":r[1],"email":r[2],"tel":r[3],"fecha":r[4],"estado":r[5]} for r in rows]

def actualizar_estado(nda_id: int, estado: str, notas: str = "") -> dict:
    con = _con()
    con.execute("UPDATE ndas SET estado=?, notas=? WHERE id=?", (estado, notas, nda_id))
    con.commit()
    con.close()
    return {"ok": True, "nda_id": nda_id, "estado": estado}

def _notificar_admin(datos: dict):
    """Avisa al admin (Hicham) por email cuando llega una firma nueva."""
    try:
        import requests
        if not SENDGRID_KEY:
            print(f"[NDA NUEVO] {datos.get('nombre')} — {datos.get('email')} — {datos.get('telefono')}")
            return
        payload = {
            "personalizations": [{"to": [{"email": EMAIL_FROM}]}],
            "from": {"email": EMAIL_FROM},
            "subject": f"🔐 NDA firmado: {datos.get('nombre')}",
            "content": [{"type":"text/plain", "value":
                f"Nuevo NDA:\nNombre: {datos.get('nombre')}\nEmail: {datos.get('email')}\nTeléfono: {datos.get('telefono')}\nFecha: {datos.get('timestamp')}"
            }]
        }
        requests.post("https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {SENDGRID_KEY}", "Content-Type": "application/json"},
            json=payload, timeout=8)
    except:
        pass

def _email_bienvenida(datos: dict):
    """Email de confirmación automático al firmante."""
    try:
        import requests
        if not SENDGRID_KEY:
            return
        cuerpo = f"""Hola {datos.get('nombre')},

Tu NDA está firmado. Gracias por la confianza.

En las próximas 24 horas recibirás:
→ Enlace para agendar tu sesión privada de 1h
→ PDF con introducción al método
→ Acceso a la calculadora de sizing

Puedes agendar directamente aquí:
{CALENDLY_LINK}

O escríbeme directamente por WhatsApp/Telegram:
{WHATSAPP_LINK}

Recuerda: no pagas nada hasta que me confirmes que has aprobado Fase 1 y Fase 2.

— Hicham
Impacto Digital IA
"""
        payload = {
            "personalizations": [{"to": [{"email": datos.get("email")}]}],
            "from": {"email": EMAIL_FROM},
            "subject": "✅ NDA firmado — Próximo paso: agenda tu sesión",
            "content": [{"type":"text/plain","value": cuerpo}]
        }
        requests.post("https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {SENDGRID_KEY}", "Content-Type":"application/json"},
            json=payload, timeout=8)
    except:
        pass

def confirmar_aprobacion(email: str, broker: str, screenshot_url: str = "") -> dict:
    """Cliente confirma que aprobó → se activa el cobro del fee."""
    con = _con()
    row = con.execute("SELECT id,nombre FROM ndas WHERE email=? ORDER BY id DESC LIMIT 1", (email,)).fetchone()
    if not row:
        con.close()
        return {"error": "Email no encontrado en NDA"}
    nda_id, nombre = row
    con.execute("UPDATE ndas SET estado='aprobado_pendiente_pago', notas=? WHERE id=?",
        (f"Broker: {broker} | Screenshot: {screenshot_url}", nda_id))
    con.commit()
    con.close()
    _notificar_admin({"nombre": nombre, "email": email,
        "telefono": f"[APROBACIÓN] Broker: {broker}",
        "timestamp": datetime.now().isoformat()})
    return {
        "ok": True,
        "mensaje": f"¡Enhorabuena {nombre}! Confirmación recibida.",
        "fee": "€150",
        "pago_link": os.getenv("STRIPE_PAYMENT_LINK", "Stripe link pendiente de configurar"),
        "nota": "Puedes pagar por Bizum, transferencia o Stripe. Lo que prefieras."
    }
