"""
SaaS — Gestión de suscripciones y trial gratuito.
Trial: 30 días gratis. Luego: 97€/mes o 797€/año.
Requiere STRIPE_SECRET_KEY para pagos reales.
"""
import os, json, sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB = Path(__file__).parent / "suscripciones.db"
STRIPE_KEY = os.getenv("STRIPE_SECRET_KEY", "")

PLANES = {
    "trial":   {"precio": 0,    "dias": 30,   "label": "Trial Gratuito 30 días"},
    "mensual": {"precio": 97,   "dias": 30,   "label": "Plan Mensual — 97€/mes"},
    "anual":   {"precio": 797,  "dias": 365,  "label": "Plan Anual — 797€/año (ahorra 367€)"},
}

STRIPE_PRICE_IDS = {
    "mensual": os.getenv("STRIPE_PRICE_MENSUAL", ""),
    "anual":   os.getenv("STRIPE_PRICE_ANUAL", ""),
}

def _con():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS suscriptores (
        email TEXT PRIMARY KEY,
        nombre TEXT,
        plan TEXT DEFAULT 'trial',
        inicio TEXT,
        vence TEXT,
        activo INTEGER DEFAULT 1,
        telegram_id TEXT DEFAULT '',
        stripe_id TEXT DEFAULT ''
    )""")
    c.commit()
    return c

def registrar_trial(email: str, nombre: str, telegram_id: str = "") -> dict:
    inicio = datetime.now()
    vence  = inicio + timedelta(days=30)
    con = _con()
    try:
        con.execute("""INSERT OR IGNORE INTO suscriptores
            (email, nombre, plan, inicio, vence, activo, telegram_id)
            VALUES (?,?,?,?,?,1,?)""",
            (email, nombre, "trial", inicio.isoformat(), vence.isoformat(), telegram_id))
        con.commit()
    finally:
        con.close()
    return {
        "email": email,
        "plan": "trial",
        "vence": vence.strftime("%d/%m/%Y"),
        "dias_restantes": 30,
        "activo": True
    }

def verificar_acceso(email: str) -> dict:
    con = _con()
    row = con.execute("SELECT * FROM suscriptores WHERE email=?", (email,)).fetchone()
    con.close()
    if not row:
        return {"acceso": False, "razon": "No registrado. Activa tu trial en /trial"}
    _, nombre, plan, inicio, vence, activo, tg_id, stripe_id = row
    if not activo:
        return {"acceso": False, "razon": "Suscripción cancelada"}
    dias_restantes = (datetime.fromisoformat(vence) - datetime.now()).days
    if dias_restantes < 0:
        return {"acceso": False, "razon": f"Trial/plan vencido. Renueva en /suscribir", "dias_restantes": dias_restantes}
    return {
        "acceso": True,
        "email": email,
        "nombre": nombre,
        "plan": plan,
        "dias_restantes": dias_restantes,
        "vence": datetime.fromisoformat(vence).strftime("%d/%m/%Y")
    }

def crear_checkout_stripe(email: str, plan: str = "mensual") -> dict:
    if not STRIPE_KEY:
        return {"error": "Stripe no configurado. Añade STRIPE_SECRET_KEY al .env"}
    try:
        import stripe
        stripe.api_key = STRIPE_KEY
        session = stripe.checkout.Session.create(
            customer_email=email,
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_PRICE_IDS[plan], "quantity": 1}],
            mode="subscription",
            success_url=os.getenv("BASE_URL", "http://localhost:8002") + "/pago-ok?email={CHECKOUT_SESSION_ID}",
            cancel_url=os.getenv("BASE_URL", "http://localhost:8002") + "/precios",
        )
        return {"checkout_url": session.url, "session_id": session.id}
    except Exception as e:
        return {"error": str(e)}

def activar_suscripcion(email: str, plan: str, stripe_id: str = "", dias: int = None) -> dict:
    d = dias or PLANES[plan]["dias"]
    vence = (datetime.now() + timedelta(days=d)).isoformat()
    con = _con()
    con.execute("""UPDATE suscriptores SET plan=?, vence=?, activo=1, stripe_id=?
        WHERE email=?""", (plan, vence, stripe_id, email))
    if con.rowcount == 0:
        con.execute("""INSERT INTO suscriptores (email,nombre,plan,inicio,vence,activo,stripe_id)
            VALUES (?,?,?,?,?,1,?)""", (email, email, plan, datetime.now().isoformat(), vence, stripe_id))
    con.commit()
    con.close()
    return {"ok": True, "plan": plan, "vence": vence}

def listar_suscriptores() -> list:
    con = _con()
    rows = con.execute("SELECT email,nombre,plan,vence,activo FROM suscriptores ORDER BY vence DESC").fetchall()
    con.close()
    return [{"email": r[0], "nombre": r[1], "plan": r[2], "vence": r[3], "activo": bool(r[4])} for r in rows]
