"""
Fondeo Garantizado — Backend API
FastAPI + SQLite + JWT
"""
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime, timezone
import os, stripe

from database import Base, engine, get_db
import models, auth, signals as sig

# ── Init DB ──────────────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

# ── Stripe ───────────────────────────────────────────────────────────────────
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
PLANES_STRIPE = {
    "starter": os.environ.get("STRIPE_PRICE_STARTER", ""),
    "pro":     os.environ.get("STRIPE_PRICE_PRO", ""),
    "escala":  os.environ.get("STRIPE_PRICE_ESCALA", ""),
}

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Fondeo Garantizado API",
    description="Backend del SaaS de estrategia de cobertura 3×4 para fondeo.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir la landing y dashboard como estáticos
static_dir = os.path.join(os.path.dirname(__file__), "..")
app.mount("/app", StaticFiles(directory=static_dir, html=True), name="static")


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class RegisterIn(BaseModel):
    email: str
    nombre: str
    password: str

class LoginIn(BaseModel):
    email: str
    password: str

class CuentaIn(BaseModel):
    broker:    str
    capital:   float = 10000.0
    fee:       float = 0.0
    target:    float = 8.0
    dd_max:    float = 10.0
    daily_max: float = 5.0
    direccion: Optional[str] = None
    par_id:    Optional[int] = None

class PnlUpdate(BaseModel):
    pnl:    float
    estado: Optional[str] = None

class SenalRequest(BaseModel):
    activo:    str = "BTC"
    ratio:     float = 4.0
    riesgo_pct: float = 1.0

class CheckoutIn(BaseModel):
    plan: str
    success_url: str = "http://localhost:5003/app/dashboard.html"
    cancel_url:  str = "http://localhost:5003/"


# ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/auth/registro", tags=["auth"], summary="Crear cuenta nueva")
def registro(data: RegisterIn, db: Session = Depends(get_db)):
    if db.query(models.Usuario).filter(models.Usuario.email == data.email).first():
        raise HTTPException(400, "Email ya registrado")
    user = models.Usuario(
        email=data.email,
        nombre=data.nombre,
        password_hash=auth.hash_password(data.password),
    )
    db.add(user); db.commit(); db.refresh(user)
    token = auth.create_token(user.id, user.email)
    return {"token": token, "plan": user.plan, "nombre": user.nombre}


@app.post("/auth/login", tags=["auth"], summary="Iniciar sesión")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(models.Usuario).filter(models.Usuario.email == data.email).first()
    if not user or not auth.verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Credenciales incorrectas")
    token = auth.create_token(user.id, user.email)
    return {"token": token, "plan": user.plan, "nombre": user.nombre, "id": user.id}


@app.get("/me", tags=["auth"], summary="Datos del usuario actual")
def me(user: models.Usuario = Depends(auth.get_current_user)):
    return {
        "id":        user.id,
        "email":     user.email,
        "nombre":    user.nombre,
        "plan":      user.plan,
        "creado_en": user.creado_en,
    }


# ══════════════════════════════════════════════════════════════════════════════
# CUENTAS DE FONDEO
# ══════════════════════════════════════════════════════════════════════════════

def _max_cuentas(plan: str) -> int:
    return {"starter": 2, "pro": 4, "escala": 9999}.get(plan, 2)


@app.get("/cuentas", tags=["cuentas"], summary="Listar mis cuentas de fondeo")
def listar_cuentas(
    user: models.Usuario = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    cuentas = db.query(models.CuentaFondeo).filter(
        models.CuentaFondeo.usuario_id == user.id
    ).all()
    return [_cuenta_dict(c) for c in cuentas]


@app.post("/cuentas", tags=["cuentas"], summary="Añadir cuenta de fondeo")
def crear_cuenta(
    data: CuentaIn,
    user: models.Usuario = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    total = db.query(models.CuentaFondeo).filter(
        models.CuentaFondeo.usuario_id == user.id
    ).count()
    if total >= _max_cuentas(user.plan):
        raise HTTPException(403, f"Plan {user.plan} permite máximo {_max_cuentas(user.plan)} cuentas. Actualiza tu plan.")

    dir_enum = models.DireccionEnum(data.direccion) if data.direccion else None
    c = models.CuentaFondeo(
        usuario_id=user.id,
        broker=data.broker,
        capital=data.capital,
        fee=data.fee,
        target=data.target,
        dd_max=data.dd_max,
        daily_max=data.daily_max,
        direccion=dir_enum,
        par_id=data.par_id,
    )
    db.add(c); db.commit(); db.refresh(c)
    return _cuenta_dict(c)


@app.put("/cuentas/{cuenta_id}/pnl", tags=["cuentas"], summary="Actualizar PnL de una cuenta")
def actualizar_pnl(
    cuenta_id: int,
    data: PnlUpdate,
    user: models.Usuario = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    c = _get_cuenta(cuenta_id, user.id, db)
    c.pnl      = data.pnl
    c.actua_en = datetime.now(timezone.utc)

    # Auto-estado según PnL
    if data.estado:
        c.estado = models.EstadoCuentaEnum(data.estado)
    elif data.pnl >= c.target:
        c.estado = models.EstadoCuentaEnum.aprobada
    elif data.pnl <= -c.dd_max:
        c.estado = models.EstadoCuentaEnum.fallida
    elif data.pnl <= -(c.dd_max * 0.4):
        c.estado = models.EstadoCuentaEnum.pausada

    db.commit(); db.refresh(c)
    return _cuenta_dict(c)


@app.put("/cuentas/{cuenta_id}/par/{par_id}", tags=["cuentas"], summary="Emparejar dos cuentas")
def emparejar(
    cuenta_id: int,
    par_id: int,
    user: models.Usuario = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    c1 = _get_cuenta(cuenta_id, user.id, db)
    c2 = _get_cuenta(par_id,    user.id, db)
    c1.par_id = c2.id
    c2.par_id = c1.id
    # Auto-asignar direcciones contrarias si no las tienen
    if not c1.direccion and not c2.direccion:
        c1.direccion = models.DireccionEnum.long
        c2.direccion = models.DireccionEnum.short
    elif c1.direccion and not c2.direccion:
        c2.direccion = models.DireccionEnum.short if c1.direccion == models.DireccionEnum.long else models.DireccionEnum.long
    db.commit()
    return {"par_1": _cuenta_dict(c1), "par_2": _cuenta_dict(c2)}


@app.delete("/cuentas/{cuenta_id}", tags=["cuentas"], summary="Eliminar cuenta")
def eliminar_cuenta(
    cuenta_id: int,
    user: models.Usuario = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    c = _get_cuenta(cuenta_id, user.id, db)
    # Limpiar el par del otro lado
    if c.par_id:
        par = db.query(models.CuentaFondeo).filter(models.CuentaFondeo.id == c.par_id).first()
        if par:
            par.par_id = None
    db.delete(c); db.commit()
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# SEÑALES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/senales/activa", tags=["señales"], summary="Señal de trading activa ahora")
def senal_activa(
    activo: str = "BTC",
    user: models.Usuario = Depends(auth.get_current_user),
):
    if user.plan == "starter":
        raise HTTPException(403, "Las señales requieren plan Pro o superior")
    return sig.generar_senal(activo=activo)


@app.post("/senales/calcular", tags=["señales"], summary="Calcular señal personalizada")
def calcular_senal(
    data: SenalRequest,
    user: models.Usuario = Depends(auth.get_current_user),
):
    if user.plan == "starter":
        raise HTTPException(403, "Las señales requieren plan Pro o superior")
    return sig.generar_senal(activo=data.activo, ratio=data.ratio, riesgo_pct=data.riesgo_pct)


@app.get("/senales/par/{cuenta_id}", tags=["señales"], summary="Estado y acción recomendada para un par")
def estado_par(
    cuenta_id: int,
    user: models.Usuario = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    c1 = _get_cuenta(cuenta_id, user.id, db)
    if not c1.par_id:
        raise HTTPException(400, "Esta cuenta no tiene par asignado")
    c2 = _get_cuenta(c1.par_id, user.id, db)
    return sig.evaluar_estado_par(c1.pnl, c2.pnl, c1.target, c1.dd_max)


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD GLOBAL
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/dashboard", tags=["dashboard"], summary="Resumen completo del usuario")
def dashboard(
    user: models.Usuario = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    cuentas = db.query(models.CuentaFondeo).filter(
        models.CuentaFondeo.usuario_id == user.id
    ).all()

    activas   = [c for c in cuentas if c.estado == models.EstadoCuentaEnum.activa]
    aprobadas = [c for c in cuentas if c.estado == models.EstadoCuentaEnum.aprobada]
    fallidas  = [c for c in cuentas if c.estado == models.EstadoCuentaEnum.fallida]
    pausadas  = [c for c in cuentas if c.estado == models.EstadoCuentaEnum.pausada]

    capital_fondeado = sum(c.capital for c in aprobadas)
    fees_invertidos  = sum(c.fee     for c in cuentas)
    pares_activos    = len([c for c in cuentas if c.par_id]) // 2

    # Fase global del sistema
    if len(aprobadas) >= 2:
        fase_global = "3 — FONDEADO"
    elif len(aprobadas) >= 1:
        fase_global = "2 — RECUPERACIÓN"
    else:
        fase_global = "1 — COBERTURA ACTIVA"

    return {
        "usuario":          user.nombre,
        "plan":             user.plan,
        "fase_global":      fase_global,
        "resumen": {
            "total_cuentas":      len(cuentas),
            "activas":            len(activas),
            "aprobadas":          len(aprobadas),
            "fallidas":           len(fallidas),
            "pausadas":           len(pausadas),
            "pares_activos":      pares_activos,
            "capital_fondeado":   capital_fondeado,
            "fees_invertidos":    fees_invertidos,
        },
        "cuentas": [_cuenta_dict(c) for c in cuentas],
    }


# ══════════════════════════════════════════════════════════════════════════════
# SUSCRIPCIONES / STRIPE
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/suscripcion/checkout", tags=["suscripción"], summary="Crear sesión de pago Stripe")
def crear_checkout(
    data: CheckoutIn,
    user: models.Usuario = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    if not stripe.api_key:
        raise HTTPException(503, "Stripe no configurado — añade STRIPE_SECRET_KEY al .env")
    price_id = PLANES_STRIPE.get(data.plan)
    if not price_id:
        raise HTTPException(400, f"Plan '{data.plan}' no válido")

    # Crear o recuperar customer Stripe
    if not user.stripe_id:
        customer = stripe.Customer.create(email=user.email, name=user.nombre)
        user.stripe_id = customer.id
        db.commit()

    session = stripe.checkout.Session.create(
        customer=user.stripe_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=data.success_url + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=data.cancel_url,
        metadata={"user_id": str(user.id), "plan": data.plan},
    )
    return {"checkout_url": session.url, "session_id": session.id}


@app.post("/suscripcion/webhook", tags=["suscripción"], include_in_schema=False)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(400, "Webhook inválido")

    if event["type"] == "checkout.session.completed":
        meta    = event["data"]["object"].get("metadata", {})
        user_id = int(meta.get("user_id", 0))
        plan    = meta.get("plan", "starter")
        user = db.query(models.Usuario).filter(models.Usuario.id == user_id).first()
        if user:
            user.plan = models.PlanEnum(plan)
            db.commit()

    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_cuenta(cuenta_id: int, user_id: int, db: Session) -> models.CuentaFondeo:
    c = db.query(models.CuentaFondeo).filter(
        models.CuentaFondeo.id == cuenta_id,
        models.CuentaFondeo.usuario_id == user_id,
    ).first()
    if not c:
        raise HTTPException(404, "Cuenta no encontrada")
    return c


def _cuenta_dict(c: models.CuentaFondeo) -> dict:
    return {
        "id":        c.id,
        "broker":    c.broker,
        "capital":   c.capital,
        "fee":       c.fee,
        "target":    c.target,
        "dd_max":    c.dd_max,
        "daily_max": c.daily_max,
        "pnl":       c.pnl,
        "direccion": c.direccion,
        "par_id":    c.par_id,
        "estado":    c.estado,
        "fase":      c.fase,
        "actua_en":  c.actua_en,
    }


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5003))
    print(f"\n{'='*52}")
    print(f"  Fondeo Garantizado — API v1.0.0")
    print(f"  http://localhost:{port}")
    print(f"  Docs: http://localhost:{port}/docs")
    print(f"{'='*52}\n")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
