from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db
import models
import os

SECRET_KEY = os.environ.get("JWT_SECRET", "fondeo-garantizado-secret-2026-impacto-digital")
ALGORITHM  = "HS256"
TOKEN_EXP_HOURS = 72

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2  = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)

def create_token(user_id: int, email: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXP_HOURS)
    return jwt.encode({"sub": str(user_id), "email": email, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> models.Usuario:
    err = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub", 0))
    except JWTError:
        raise err
    user = db.query(models.Usuario).filter(models.Usuario.id == user_id).first()
    if not user or not user.activo:
        raise err
    return user

def require_plan(min_plan: str):
    order = {"starter": 0, "pro": 1, "escala": 2}
    def check(user: models.Usuario = Depends(get_current_user)):
        if order.get(user.plan.value, 0) < order.get(min_plan, 0):
            raise HTTPException(status_code=403, detail=f"Esta función requiere plan {min_plan} o superior")
        return user
    return check
