from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
from database import Base


class PlanEnum(str, enum.Enum):
    starter = "starter"
    pro = "pro"
    escala = "escala"


class DireccionEnum(str, enum.Enum):
    long = "long"
    short = "short"


class EstadoCuentaEnum(str, enum.Enum):
    activa = "activa"
    aprobada = "aprobada"
    fallida = "fallida"
    pausada = "pausada"


class Usuario(Base):
    __tablename__ = "usuarios"

    id            = Column(Integer, primary_key=True, index=True)
    email         = Column(String, unique=True, index=True, nullable=False)
    nombre        = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    plan          = Column(Enum(PlanEnum), default=PlanEnum.starter)
    stripe_id     = Column(String, nullable=True)
    activo        = Column(Boolean, default=True)
    creado_en     = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    cuentas = relationship("CuentaFondeo", back_populates="usuario", cascade="all, delete")


class CuentaFondeo(Base):
    __tablename__ = "cuentas_fondeo"

    id         = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    broker     = Column(String, nullable=False)
    capital    = Column(Float, default=10000.0)
    fee        = Column(Float, default=0.0)
    target     = Column(Float, default=8.0)   # % objetivo
    dd_max     = Column(Float, default=10.0)  # % drawdown max
    daily_max  = Column(Float, default=5.0)   # % pérdida diaria max
    pnl        = Column(Float, default=0.0)   # % PnL actual
    direccion  = Column(Enum(DireccionEnum), nullable=True)
    par_id     = Column(Integer, ForeignKey("cuentas_fondeo.id"), nullable=True)
    estado     = Column(Enum(EstadoCuentaEnum), default=EstadoCuentaEnum.activa)
    fase       = Column(Integer, default=1)   # 1 = challenge, 2 = verificación
    creada_en  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    actua_en   = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    usuario = relationship("Usuario", back_populates="cuentas")


class Senal(Base):
    __tablename__ = "senales"

    id        = Column(Integer, primary_key=True, index=True)
    activo    = Column(String, nullable=False)        # BTC, XAUUSD, etc.
    direccion = Column(Enum(DireccionEnum), nullable=False)
    entrada   = Column(Float, nullable=False)
    sl        = Column(Float, nullable=False)         # stop loss
    tp        = Column(Float, nullable=False)         # take profit
    ratio     = Column(Float, default=4.0)
    activa    = Column(Boolean, default=True)
    creada_en = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    cerrada_en = Column(Column(DateTime), nullable=True) if False else Column(DateTime, nullable=True)
    resultado  = Column(String, nullable=True)        # "win" | "loss" | None


class Suscripcion(Base):
    __tablename__ = "suscripciones"

    id                  = Column(Integer, primary_key=True, index=True)
    usuario_id          = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    stripe_sub_id       = Column(String, nullable=True)
    plan                = Column(Enum(PlanEnum), nullable=False)
    activa              = Column(Boolean, default=True)
    inicio              = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    proximo_pago        = Column(DateTime, nullable=True)
