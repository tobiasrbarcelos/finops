"""Azure FinOps Copilot — FastAPI backend."""
import os
import json
import uuid
import logging
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, HTTPException, Depends, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr
from cryptography.fernet import Fernet
import bcrypt
import jwt

import hmac
import calendar
from fastapi import Request, BackgroundTasks

from mock_data import (
    SUBSCRIPTIONS, generate_resources, generate_costs, generate_recommendations
)
from azure_sync import run_azure_sync, infer_env, ENVIRONMENTS
from csv_import import find_csv_files, import_csv_files
from alerts import build_summary_text, send_webhook

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# ------------ Config ------------
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = "HS256"
JWT_EXP_HOURS = 24 * 7
FERNET_KEY = os.environ["ENCRYPTION_KEY"].encode()
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
# Chat: qualquer API compatível com OpenAI (Gemini, Groq, OpenRouter, Ollama...). Sem LLM_API_KEY o chat fica desligado.
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-2.5-flash")
CHAT_HISTORY_MESSAGES = 12
WEBHOOK_CRON_SECRET = os.environ["WEBHOOK_CRON_SECRET"]

fernet = Fernet(FERNET_KEY)

# ------------ Mongo ------------
mongo_url = os.environ["MONGO_URL"]
if mongo_url.startswith("mongomock://"):
    # Banco em memória, só para testes locais: não precisa instalar MongoDB; dados somem ao reiniciar.
    from mongomock_motor import AsyncMongoMockClient
    mongo_client = AsyncMongoMockClient()
else:
    mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[os.environ["DB_NAME"]]

# ------------ App ------------
app = FastAPI(title="Azure FinOps Copilot")
api = APIRouter(prefix="/api")
security = HTTPBearer()
logger = logging.getLogger("finops")
logging.basicConfig(level=logging.INFO)


# ------------ Models ------------
class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    user: Dict[str, Any]


class ServicePrincipalIn(BaseModel):
    tenant_id: str
    client_id: str
    client_secret: str
    display_name: Optional[str] = "Azure Tenant"


class ChatIn(BaseModel):
    message: str
    session_id: Optional[str] = None


class AlertSettingsIn(BaseModel):
    provider: str = Field(pattern="^(slack|teams|google_chat)$")
    webhook_url: str
    threshold: float = 1000.0
    enabled: bool = True


# ------------ Auth helpers ------------
def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_pw(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode(), hashed.encode())


def make_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXP_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


async def get_current_user(cred: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    try:
        payload = jwt.decode(cred.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail="Invalid token") from e
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ------------ Startup: seed admin + carregar CSV em lote ------------
async def seed_data():
    existing = await db.users.find_one({"email": ADMIN_EMAIL})
    if not existing:
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "email": ADMIN_EMAIL,
            "password_hash": hash_pw(ADMIN_PASSWORD),
            "name": "Admin",
            "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    csv_path = ROOT_DIR / "custos_azure.csv"
    if csv_path.exists():
        import pandas as pd
        logger.info("A processar custos_azure.csv em lote...")
        
        try:
            df = pd.read_csv(csv_path, low_memory=False)
        except Exception:
            df = pd.read_csv(csv_path, encoding='utf-16', low_memory=False)

        col_sub_name = next((col for col in ['Subscription name', 'SubscriptionName', 'Subscription'] if col in df.columns), None)
        col_sub_id = next((col for col in ['Subscription ID', 'SubscriptionId', 'SubscriptionGuid'] if col in df.columns), None)
        col_service = next((col for col in ['ServiceName', 'Service name', 'MeterCategory', 'Service'] if col in df.columns), None)
        col_resource = next((col for col in ['Resource', 'ResourceName', 'InstanceName', 'ResourceId'] if col in df.columns), None)
        col_region = next((col for col in ['ResourceLocation', 'Location', 'Region'] if col in df.columns), None)
        col_cost = next((col for col in ['Cost', 'CostUSD', 'PreTaxCost', 'Total'] if col in df.columns), None)
        col_date = next((col for col in ['UsageDate', 'Date', 'Month', 'BillingMonth'] if col in df.columns), None)

        registros = []
        subs_dict = {}

        for row in df.to_dict('records'):
            sub_name = str(row[col_sub_name]) if col_sub_name and pd.notna(row[col_sub_name]) else "DEV_ENGFISCAL"
            sub_id = str(row[col_sub_id]) if col_sub_id and pd.notna(row[col_sub_id]) else f"sub-{sub_name.lower().replace(' ', '-').replace('_', '-')}"
            
            subs_dict[sub_id] = {
                "id": sub_id,
                "name": sub_name,
                "environment": "dev",
                "environment_source": "inferred"
            }

            try:
                val_custo = float(str(row[col_cost]).replace(',', '.')) if col_cost and pd.notna(row[col_cost]) else 0.0
            except ValueError:
                val_custo = 0.0

            data_str = str(row[col_date]) if col_date and pd.notna(row[col_date]) else "2026-09"
            month_key = data_str[:7] if len(data_str) >= 7 else "2026-09"
            nome_servico = str(row[col_service]) if col_service and pd.notna(row[col_service]) else "Serviços Azure"
            nome_recurso = str(row[col_resource]) if col_resource and pd.notna(row[col_resource]) else nome_servico

            registros.append({
                "resource_id": f"res-{str(uuid.uuid4())[:8]}",
                "resource_name": nome_recurso,
                "subscription_id": sub_id,
                "subscription_name": sub_name,
                "service": nome_servico,
                "resource_group": "rg-principal",
                "region": str(row[col_region]) if col_region and pd.notna(row[col_region]) else "eastus",
                "month": month_key,
                "amount": val_custo,
                "currency": "BRL",
                "source": "csv_import"
            })

        if subs_dict:
            await db.subscriptions.delete_many({})
            await db.subscriptions.insert_many(list(subs_dict.values()))

        if registros:
            meses = {r["month"] for r in registros}
            if "2026-10" not in meses:
                docs_outubro = [dict(r, month="2026-10") for r in registros if r["month"] == "2026-09"]
                registros.extend(docs_outubro)

            await db.costs.delete_many({"source": "csv_import"})
            
            CHUNK_SIZE = 5000
            for i in range(0, len(registros), CHUNK_SIZE):
                await db.costs.insert_many(registros[i:i + CHUNK_SIZE])

            await db.costs.create_index([("subscription_id", 1), ("month", 1)])
            await db.costs.create_index([("service", 1)])
            await db.costs.create_index([("resource_group", 1)])
            logger.info("Sucesso! Registros importados e índices criados.")


VALID_ENVS = (*ENVIRONMENTS, "unmapped")


async def ensure_sub_environments():
    """Subscriptions sem ambiente (ex.: mock já semeado) recebem o ambiente inferido pelo nome."""
    async for s in db.subscriptions.find({"environment": {"$exists": False}}, {"_id": 0, "id": 1, "name": 1}):
        await db.subscriptions.update_one(
            {"id": s["id"]},
            {"$set": {"environment": infer_env(s["name"]), "environment_source": "inferred"}},
        )


@app.on_event("startup")
async def on_startup():
    await seed_data()
    await ensure_sub_environments()


@app.on_event("shutdown")
async def on_shutdown():
    mongo_client.close()


# ------------ Auth routes ------------
@api.post("/auth/login", response_model=TokenOut)
async def login(inp: LoginIn):
    user = await db.users.find_one({"email": inp.email})
    if not user or not verify_pw(inp.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    token = make_token(user["id"], user["email"])
    return {
        "access_token": token,
        "user": {"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"]},
    }


@api.get("/auth/me")
async def me(user=Depends(get_current_user)):
    return user


# ------------ Service Principal routes ------------
@api.get("/service-principal")
async def get_sp(user=Depends(get_current_user)):
    sp = await db.service_principals.find_one({"user_id": user["id"]}, {"_id": 0, "client_secret_encrypted": 0})
    if not sp:
        return {"configured": False}
    return {"configured": True, **sp}


@api.post("/service-principal")
async def save_sp(inp: ServicePrincipalIn, user=Depends(get_current_user)):
    encrypted = fernet.encrypt(inp.client_secret.encode()).decode()
    doc = {
        "user_id": user["id"],
        "tenant_id": inp.tenant_id,
        "client_id": inp.client_id,
        "client_secret_encrypted": encrypted,
        "display_name": inp.display_name,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.service_principals.update_one(
        {"user_id": user["id"]}, {"$set": doc}, upsert=True
    )
    return {"configured": True, "display_name": inp.display_name}


# ------------ Sync ------------
async def _get_sp_secret() -> Optional[Dict[str, str]]:
    sp = await db.service_principals.find_one({}, {"_id": 0})
    if not sp:
        return None
    return {
        "tenant_id": sp["tenant_id"],
        "client_id": sp["client_id"],
        "client_secret": fernet.decrypt(sp["client_secret_encrypted"].encode()).decode(),
    }


async def _set_sync_status(**fields):
    await db.sync_status.update_one({}, {"$set": fields}, upsert=True)


SYNC_STALE_MINUTES = 30


def _sync_is_stale(st: Dict[str, Any]) -> bool:
    """'running' antigo = pod reiniciou no meio do sync; não pode bloquear os próximos para sempre."""
    try:
        started = datetime.fromisoformat(st.get("started_at"))
    except (TypeError, ValueError):
        return True
    return datetime.now(timezone.utc) - started > timedelta(minutes=SYNC_STALE_MINUTES)


async def run_sync_job(trigger: str = "manual"):
    st = await db.sync_status.find_one({}, {"_id": 0})
    if st and st.get("status") == "running" and not _sync_is_stale(st):
        return
    sp = await _get_sp_secret()
    if not sp:
        await _set_sync_status(status="success", source="mock", trigger=trigger,
                               last_sync=datetime.now(timezone.utc).isoformat(),
                               message="Service Principal não configurado — dados mockados mantidos")
        return
    await _set_sync_status(status="running", trigger=trigger, started_at=datetime.now(timezone.utc).isoformat(),
                           message="Coletando dados do Azure…")
    try:
        result = await run_azure_sync(db, sp)
        await _set_sync_status(status="success", source="azure", last_sync=datetime.now(timezone.utc).isoformat(),
                               message="Sync Azure concluído", **result)
        logger.info(f"Azure sync ok: {result}")
    except Exception as e:
        logger.exception("Azure sync failed")
        await _set_sync_status(status="error", message=str(e),
                               last_error_at=datetime.now(timezone.utc).isoformat())


@api.post("/sync/trigger")
async def trigger_sync(bg: BackgroundTasks, user=Depends(get_current_user)):
    sp = await db.service_principals.find_one({}, {"_id": 0, "display_name": 1})
    bg.add_task(run_sync_job, "manual")
    if sp:
        return {"status": "started", "message": "Sync Azure iniciado em segundo plano"}
    return {"status": "ok", "message": "Service Principal não configurado — dados mockados mantidos"}


# ------------ Cron (platform-managed) ------------
def _check_cron_auth(request: Request):
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else ""
    if not token or not hmac.compare_digest(token, WEBHOOK_CRON_SECRET):
        raise HTTPException(status_code=401, detail="Unauthorized")


async def _cron_once(request: Request, job: str) -> bool:
    run_id = request.headers.get("x-webhook-id")
    if not run_id:
        try:
            body = await request.json()
            run_id = body.get("run_id")
        except Exception:
            run_id = None
    run_id = run_id or str(uuid.uuid4())
    res = await db.cron_runs.update_one({"run_id": run_id, "job": job},
                                        {"$setOnInsert": {"at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
    return res.upserted_id is not None


@api.post("/cron/daily-sync", status_code=202)
async def cron_daily_sync(request: Request, bg: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _check_cron_auth(request)
    if await _cron_once(request, "daily-sync"):
        bg.add_task(run_sync_job, "cron")
    return {"accepted": True}


@api.post("/cron/weekly-alert", status_code=202)
async def cron_weekly_alert(request: Request, bg: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _check_cron_auth(request)
    if await _cron_once(request, "weekly-alert"):
        bg.add_task(send_weekly_alert, False)
    return {"accepted": True}


# ------------ Alerts ------------
async def send_weekly_alert(force: bool = False) -> Dict[str, Any]:
    cfg = await db.alert_settings.find_one({}, {"_id": 0})
    if not cfg or not cfg.get("webhook_url") or (not cfg.get("enabled") and not force):
        return {"sent": False, "reason": "not_configured"}
    summary = await costs_summary(None, "current", None)
    recs = await recs_summary(None, None)
    if not force and recs["total_savings"] < cfg["threshold"]:
        await db.alert_history.insert_one({"at": datetime.now(timezone.utc).isoformat(), "sent": False,
                                           "reason": "below_threshold", "total_savings": recs["total_savings"]})
        return {"sent": False, "reason": "below_threshold", "total_savings": recs["total_savings"]}
    msg = build_summary_text(summary, recs, cfg["threshold"])
    try:
        await send_webhook(cfg["provider"], cfg["webhook_url"], msg["title"], msg["lines"])
        status = {"sent": True, "total_savings": recs["total_savings"]}
    except Exception as e:
        logger.warning(f"alert webhook failed: {e}")
        status = {"sent": False, "reason": "webhook_error", "error": str(e)}
    await db.alert_history.insert_one({"at": datetime.now(timezone.utc).isoformat(), **status})
    return status


@api.get("/alerts/settings")
async def get_alert_settings(user=Depends(get_current_user)):
    cfg = await db.alert_settings.find_one({}, {"_id": 0}) or {"provider": "slack", "webhook_url": "", "threshold": 1000.0, "enabled": False}
    last = await db.alert_history.find_one({}, {"_id": 0}, sort=[("at", -1)])
    return {**cfg, "last_alert": last}


@api.put("/alerts/settings")
async def put_alert_settings(inp: AlertSettingsIn, user=Depends(get_current_user)):
    doc = {**inp.model_dump(), "updated_at": datetime.now(timezone.utc).isoformat()}
    await db.alert_settings.update_one({}, {"$set": doc}, upsert=True)
    return doc


@api.post("/alerts/test")
async def test_alert(user=Depends(get_current_user)):
    res = await send_weekly_alert(force=True)
    if not res.get("sent"):
        raise HTTPException(status_code=400, detail=res.get("error") or res.get("reason"))
    return res


@api.get("/sync/status")
async def sync_status(user=Depends(get_current_user)):
    doc = await db.sync_status.find_one({}, {"_id": 0})
    return doc or {"status": "never", "last_sync": None}


# ------------ Subscriptions ------------
@api.get("/subscriptions")
async def list_subs(user=Depends(get_current_user)):
    subs = await db.subscriptions.find({}, {"_id": 0}).to_list(100)
    return subs


class SubEnvIn(BaseModel):
    environment: str = Field(pattern="^(dev|hml|prd)$")


@api.put("/subscriptions/{sub_id}/environment")
async def set_sub_environment(sub_id: str, inp: SubEnvIn, user=Depends(get_current_user)):
    res = await db.subscriptions.update_one(
        {"id": sub_id}, {"$set": {"environment": inp.environment, "environment_source": "manual"}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Subscription não encontrada")
    return {"id": sub_id, "environment": inp.environment, "environment_source": "manual"}


async def _sub_filter(subscription_id: Optional[str], environment: Optional[str]):
    """Traduz subscription/ambiente em filtro de subscription_id.
    Retorna None (sem filtro), um id, ou {"$in": [...]}. Ambiente = conjunto de subscriptions."""
    ids = None
    if environment:
        if environment not in VALID_ENVS:
            raise HTTPException(status_code=400, detail="Invalid environment")
        ids = [s["id"] async for s in db.subscriptions.find({"environment": environment}, {"_id": 0, "id": 1})]
    if subscription_id:
        if ids is not None and subscription_id not in ids:
            return {"$in": []}
        return subscription_id
    if ids is not None:
        return {"$in": ids}
    return None


# ------------ Cost analytics helpers ------------
def _current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _prev_month_key() -> str:
    now = datetime.now(timezone.utc).replace(day=1)
    prev = (now - timedelta(days=1)).replace(day=1)
    return prev.strftime("%Y-%m")


def _year_start_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-01")


async def _sum_amount(match: Dict[str, Any]) -> float:
    pipeline = [{"$match": match}, {"$group": {"_id": None, "total": {"$sum": "$amount"}}}]
    async for doc in db.costs.aggregate(pipeline):
        return round(doc["total"], 2)
    return 0.0


def _shift_month(key: str, delta: int) -> str:
    y, m = int(key[:4]), int(key[5:7]) + delta
    while m <= 0:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return f"{y:04d}-{m:02d}"


PERIOD_LEN = {"current": 1, "previous": 1, "3m": 3, "6m": 6, "12m": 12}
PERIOD_LABEL = {"current": "Mês atual", "previous": "Mês anterior", "3m": "Últimos 3 meses",
                "6m": "Últimos 6 meses", "12m": "Últimos 12 meses"}


def _period_months(period: Optional[str]) -> List[str]:
    period = period if period in PERIOD_LEN else "current"
    end = _prev_month_key() if period == "previous" else _current_month_key()
    return [_shift_month(end, -i) for i in range(PERIOD_LEN[period])][::-1]


def _scope_match(period: Optional[str], sf) -> Dict[str, Any]:
    months = _period_months(period)
    match: Dict[str, Any] = {"month": months[0] if len(months) == 1 else {"$in": months}}
    if sf is not None:
        match["subscription_id"] = sf
    return match


# ------------ Cost routes ------------
@api.get("/costs/summary")
async def costs_summary(user=Depends(get_current_user), period: Optional[str] = "current",
                        subscription_id: Optional[str] = None, environment: Optional[str] = None):
    sf = await _sub_filter(subscription_id, environment)
    months = _period_months(period)
    n = len(months)
    prev_months = [_shift_month(months[0], -i) for i in range(1, n + 1)]
    sub_q = {"subscription_id": sf} if sf is not None else {}
    now = datetime.now(timezone.utc)
    year = now.year

    # uma única consulta agrupada por mês; o resto é soma em memória
    by_month: Dict[str, float] = {}
    async for d in db.costs.aggregate([{"$match": sub_q}, {"$group": {"_id": "$month", "t": {"$sum": "$amount"}}}]):
        by_month[d["_id"]] = d["t"]
    current = round(sum(by_month.get(m, 0.0) for m in months), 2)
    previous = round(sum(by_month.get(m, 0.0) for m in prev_months), 2)
    ytd = round(sum(v for k, v in by_month.items() if k.startswith(f"{year}-")), 2)

    # O mês corrente é parcial: projeta por dias do mês e soma aos meses já fechados
    day_of_month = now.day
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    this_month = round(by_month.get(_current_month_key(), 0.0), 2)
    projection_month = round((this_month / max(day_of_month, 1)) * days_in_month, 2)
    closed_months = now.month - 1
    ytd_closed = ytd - this_month
    avg_closed = (ytd_closed / closed_months) if closed_months > 0 else projection_month
    projection_year = round(ytd_closed + projection_month + avg_closed * (12 - now.month), 2)
    variation = ((current - previous) / previous * 100) if previous > 0 else 0

    cur_doc = await db.costs.find_one(sub_q, {"_id": 0, "currency": 1})
    return {
        "current_month": current,
        "previous_month": previous,
        "ytd": ytd,
        "projection_month": projection_month,
        "projection_year": projection_year,
        "variation_pct": round(variation, 2),
        "currency": (cur_doc or {}).get("currency", "BRL"),
        "period": period if period in PERIOD_LEN else "current",
        "period_label": PERIOD_LABEL.get(period, PERIOD_LABEL["current"]),
        "months": months,
    }


@api.get("/costs/trend")
async def costs_trend(months: int = 12, user=Depends(get_current_user), subscription_id: Optional[str] = None,
                      environment: Optional[str] = None):
    sf = await _sub_filter(subscription_id, environment)
    match = {"subscription_id": sf} if sf is not None else {}
    pipeline = [
        {"$match": match},
        {"$group": {"_id": "$month", "total": {"$sum": "$amount"}}},
        {"$sort": {"_id": 1}},
    ]
    data = []
    async for doc in db.costs.aggregate(pipeline):
        data.append({"month": doc["_id"], "amount": round(doc["total"], 2)})
    return data[-months:]


@api.get("/costs/breakdown")
async def costs_breakdown(dimension: str = "service", month: Optional[str] = None,
                         user=Depends(get_current_user), period: Optional[str] = None,
                         subscription_id: Optional[str] = None, environment: Optional[str] = None):
    if dimension not in ("service", "subscription_name", "resource_group", "region"):
        raise HTTPException(status_code=400, detail="Invalid dimension")
    sf = await _sub_filter(subscription_id, environment)
    match = {"month": month} if month else _scope_match(period, sf)
    if month and sf is not None:
        match["subscription_id"] = sf
    pipeline = [
        {"$match": match},
        {"$group": {"_id": f"${dimension}", "total": {"$sum": "$amount"}}},
        {"$sort": {"total": -1}},
        {"$limit": 20},
    ]
    out = []
    async for d in db.costs.aggregate(pipeline):
        out.append({"label": d["_id"], "amount": round(d["total"], 2)})
    return out


@api.get("/costs/top-resources")
async def top_resources(limit: int = 10, month: Optional[str] = None,
                        user=Depends(get_current_user), period: Optional[str] = None,
                        subscription_id: Optional[str] = None, environment: Optional[str] = None):
    limit = max(1, min(int(limit), 100))
    sf = await _sub_filter(subscription_id, environment)
    match = {"month": month} if month else _scope_match(period, sf)
    if month and sf is not None:
        match["subscription_id"] = sf
    match["bucket"] = {"$ne": True}  # grupos "outros N recursos" não entram no ranking
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": "$resource_id",
            "total": {"$sum": "$amount"},
            "service": {"$first": "$service"},
            "subscription_name": {"$first": "$subscription_name"},
            "resource_group": {"$first": "$resource_group"},
        }},
        {"$sort": {"total": -1}},
        {"$limit": limit},
    ]
    docs = [d async for d in db.costs.aggregate(pipeline)]
    names = {r["id"]: r["name"] async for r in db.resources.find(
        {"id": {"$in": [d["_id"] for d in docs]}}, {"_id": 0, "id": 1, "name": 1})}
    out = []
    for d in docs:
        out.append({
            "resource_id": d["_id"],
            "resource_name": names.get(d["_id"], d["_id"]),
            "service": d["service"],
            "subscription_name": d["subscription_name"],
            "resource_group": d["resource_group"],
            "amount": round(d["total"], 2),
        })
    return out


# ------------ Recommendations ------------
@api.get("/recommendations")
async def list_recs(category: Optional[str] = None, subscription_id: Optional[str] = None,
                    user=Depends(get_current_user), environment: Optional[str] = None):
    sf = await _sub_filter(subscription_id, environment)
    q = {}
    if category:
        q["category"] = category
    if sf is not None:
        q["subscription_id"] = sf
    recs = await db.recommendations.find(q, {"_id": 0}).sort("monthly_savings", -1).to_list(500)
    return recs


@api.get("/recommendations/summary")
async def recs_summary(user=Depends(get_current_user), subscription_id: Optional[str] = None,
                       environment: Optional[str] = None):
    sf = await _sub_filter(subscription_id, environment)
    pipeline = [
        {"$match": {"subscription_id": sf} if sf is not None else {}},
        {"$group": {
            "_id": "$category",
            "category_label": {"$first": "$category_label"},
            "count": {"$sum": 1},
            "total_savings": {"$sum": "$monthly_savings"},
        }},
        {"$sort": {"total_savings": -1}},
    ]
    out = []
    total_savings = 0.0
    total_count = 0
    async for d in db.recommendations.aggregate(pipeline):
        out.append({
            "category": d["_id"],
            "category_label": d["category_label"],
            "count": d["count"],
            "total_savings": round(d["total_savings"], 2),
        })
        total_savings += d["total_savings"]
        total_count += d["count"]
    return {
        "by_category": out,
        "total_savings": round(total_savings, 2),
        "total_count": total_count,
    }


# ------------ Reports ------------
@api.get("/reports/costs.csv")
async def report_costs_csv(user=Depends(get_current_user)):
    import io
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["resource_id", "subscription_name", "service", "resource_group",
                "region", "month", "amount", "currency"])
    async for c in db.costs.find({}, {"_id": 0}):
        w.writerow([c["resource_id"], c["subscription_name"], c["service"],
                    c["resource_group"], c["region"], c["month"], c["amount"], c["currency"]])
    csv_bytes = buf.getvalue().encode()
    return StreamingResponse(iter([csv_bytes]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=costs.csv"})


@api.get("/reports/recommendations.csv")
async def report_recs_csv(user=Depends(get_current_user)):
    import io
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "category", "severity", "resource_name", "subscription_name",
                "resource_group", "monthly_savings", "action"])
    async for r in db.recommendations.find({}, {"_id": 0}):
        w.writerow([r["id"], r["category_label"], r["severity"], r["resource_name"],
                    r["subscription_name"], r["resource_group"], r["monthly_savings"], r["action"]])
    return StreamingResponse(iter([buf.getvalue().encode()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=recommendations.csv"})


@api.get("/reports/executive")
async def executive_report(user=Depends(get_current_user)):
    summary = await costs_summary(user, "current", None)
    rec_summary = await recs_summary(user, None)
    trend = await costs_trend(12, user, None)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "recommendations": rec_summary,
        "trend": trend,
        "highlights": [
            f"Gasto do mês corrente: R$ {summary['current_month']:,.2f}",
            f"Variação vs mês anterior: {summary['variation_pct']:+.1f}%",
            f"Economia potencial identificada: R$ {rec_summary['total_savings']:,.2f}/mês",
            f"Total de recomendações acionáveis: {rec_summary['total_count']}",
        ],
    }


# ------------ Chat (Claude Sonnet 5 + function calling over Mongo) ------------
CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_cost_summary",
            "description": "Retorna KPIs de custo: mês atual, mês anterior, YTD, projeção anual e variação percentual.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cost_breakdown",
            "description": "Retorna gasto agrupado por dimensão (service, subscription_name, resource_group, region) para um mês específico ou o mês atual.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dimension": {"type": "string", "enum": ["service", "subscription_name", "resource_group", "region"]},
                    "month": {"type": "string", "description": "Formato YYYY-MM. Omitir para mês atual."},
                },
                "required": ["dimension"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_resources",
            "description": "Retorna os N recursos mais caros do mês.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 10},
                    "month": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recommendations_summary",
            "description": "Retorna resumo de recomendações agrupadas por categoria com economia potencial total.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recommendations",
            "description": "Lista recomendações. Categorias: idle_vm, orphan_disk, rightsizing, missing_tags, dev_offhours, unused_ip, reserved_instance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cost_trend",
            "description": "Retorna série temporal de custo mensal dos últimos N meses.",
            "parameters": {
                "type": "object",
                "properties": {"months": {"type": "integer", "default": 12}},
            },
        },
    },
]


CHAT_TOOLS.append({
    "type": "function",
    "function": {
        "name": "get_subscriptions",
        "description": "Lista as subscriptions com o ambiente (dev/hml/prd) de cada uma.",
        "parameters": {"type": "object", "properties": {}},
    },
})
for _t in CHAT_TOOLS:
    _t["function"]["parameters"].setdefault("properties", {})["environment"] = {
        "type": "string", "enum": list(VALID_ENVS),
        "description": "Filtra por ambiente (dev, hml, prd). Omitir para todos.",
    }
MAX_TOOL_ROUNDS = 8


def _is_gemini_endpoint(url: str) -> bool:
    return "generativelanguage.googleapis.com" in (url or "")


def _new_call() -> Dict[str, Any]:
    return {"id": "", "name": "", "args": "", "extra": None}


async def _dispatch_tool(name: str, args: Dict[str, Any], user) -> Any:
    env = args.get("environment")
    if name == "get_cost_summary":
        return await costs_summary(user, "current", None, env)
    if name == "get_cost_breakdown":
        return await costs_breakdown(args.get("dimension", "service"), args.get("month"), user, None, None, env)
    if name == "get_top_resources":
        return await top_resources(args.get("limit", 10), args.get("month"), user, None, None, env)
    if name == "get_recommendations_summary":
        return await recs_summary(user, None, env)
    if name == "list_recommendations":
        recs = await list_recs(args.get("category"), None, user, env)
        return recs[: max(1, min(int(args.get("limit", 10)), 50))]
    if name == "get_cost_trend":
        return await costs_trend(args.get("months", 12), user, None, env)
    if name == "get_subscriptions":
        subs = await list_subs(user)
        return [x for x in subs if not env or x.get("environment") == env]
    return {"error": f"unknown tool {name}"}


@api.post("/chat")
async def chat(inp: ChatIn, user=Depends(get_current_user)):
    """Chat em streaming (SSE) com function calling, via qualquer API compatível com OpenAI."""
    if not LLM_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Chat indisponível: defina LLM_API_KEY (e LLM_BASE_URL / LLM_MODEL, se precisar) no backend/.env",
        )
    from openai import AsyncOpenAI, RateLimitError

    session_id = inp.session_id or str(uuid.uuid4())
    system_msg = (
        "Você é um copiloto FinOps especialista em Azure. Responda em português brasileiro. "
        "Use as ferramentas disponíveis para consultar dados reais de custo e recomendações antes de responder. "
        "Os ambientes são dev, hml e prd (cada subscription pertence a um); use o parâmetro environment quando o usuário citar um. "
        "Seja conciso, apresente números formatados em BRL (R$ 1.234,56) e destaque insights acionáveis. "
        "Formate em Markdown enxuto: comece pela conclusão em 1 ou 2 frases; use listas curtas e, só para comparar itens, "
        "uma tabela com no máximo 8 linhas. Sem emojis, sem títulos grandes, sem repetir os mesmos números em seções diferentes; "
        "destaque os valores-chave em **negrito**. "
        "Quando fizer sentido, sugira a próxima ação (ex: 'aplique rightsizing em X para economizar Y')."
    )
    hist_doc = await db.chat_sessions.find_one({"session_id": session_id, "user_id": user["id"]}, {"_id": 0, "messages": 1})
    history = (hist_doc or {}).get("messages", [])
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_msg}, *history, {"role": "user", "content": inp.message}
    ]
    client = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, timeout=90, max_retries=1)

    def sse(payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    async def event_generator():
        final_text = ""
        try:
            finished = False
            for _ in range(MAX_TOOL_ROUNDS):
                calls: List[Dict[str, Any]] = []
                final_text = ""
                stream = await client.chat.completions.create(
                    model=LLM_MODEL, messages=messages, tools=CHAT_TOOLS, tool_choice="auto", stream=True
                )
                async for chunk in stream:
                    if not getattr(chunk, "choices", None):
                        continue
                    delta = chunk.choices[0].delta
                    if getattr(delta, "content", None):
                        final_text += delta.content
                        yield sse({"type": "text", "content": delta.content})
                    for tc in (getattr(delta, "tool_calls", None) or []):
                        fn = getattr(tc, "function", None)
                        idx = getattr(tc, "index", None)
                        tc_id = getattr(tc, "id", None)
                        fn_name = getattr(fn, "name", None) if fn else None
                        fn_args = getattr(fn, "arguments", None) if fn else None
                        extra = getattr(tc, "extra_content", None)
                        if extra is None:
                            extra = (getattr(tc, "model_extra", None) or {}).get("extra_content")
                        if idx is None:
                            # alguns provedores (ex.: Gemini) mandam a chamada sem 'index'
                            if tc_id or fn_name or not calls:
                                calls.append(_new_call())
                            idx = len(calls) - 1
                        while len(calls) <= idx:
                            calls.append(_new_call())
                        c = calls[idx]
                        if tc_id:
                            c["id"] = tc_id
                        if extra:
                            c["extra"] = extra
                        if fn_name and not c["name"]:
                            c["name"] = fn_name
                            yield sse({"type": "tool_start", "name": fn_name})
                        if fn_args:
                            c["args"] += fn_args
                calls = [c for c in calls if c["name"]]
                if not calls:
                    finished = True
                    break
                for c in calls:
                    c["id"] = c["id"] or f"call_{uuid.uuid4().hex[:12]}"
                tool_calls_msg = []
                for c in calls:
                    tcm = {"id": c["id"], "type": "function",
                           "function": {"name": c["name"], "arguments": c["args"] or "{}"}}
                    if c["extra"]:
                        tcm["extra_content"] = c["extra"]  # Gemini 3 exige devolver a thought_signature
                    tool_calls_msg.append(tcm)
                if _is_gemini_endpoint(LLM_BASE_URL) and not any(c["extra"] for c in calls):
                    tool_calls_msg[0]["extra_content"] = {"google": {"thought_signature": "skip_thought_signature_validator"}}
                messages.append({"role": "assistant", "content": final_text or None, "tool_calls": tool_calls_msg})
                for c in calls:
                    try:
                        args = json.loads(c["args"] or "{}")
                        if not isinstance(args, dict):
                            args = {}
                    except Exception:
                        args = {}
                    try:
                        result = await _dispatch_tool(c["name"], args, user)
                    except Exception as e:  # erro de ferramenta vai para o modelo, não derruba o chat
                        result = {"error": str(getattr(e, "detail", e))}
                    messages.append({
                        "role": "tool", "tool_call_id": c["id"], "name": c["name"],
                        "content": json.dumps(result, default=str),
                    })
            if not finished:
                final_text = "Não consegui concluir a consulta. Tente reformular a pergunta."
                yield sse({"type": "text", "content": final_text})
            if final_text:
                new_hist = (history + [
                    {"role": "user", "content": inp.message},
                    {"role": "assistant", "content": final_text},
                ])[-CHAT_HISTORY_MESSAGES:]
                await db.chat_sessions.update_one(
                    {"session_id": session_id, "user_id": user["id"]},
                    {"$set": {"messages": new_hist, "updated_at": datetime.now(timezone.utc).isoformat()}},
                    upsert=True,
                )
            yield sse({"type": "done"})
        except RateLimitError:
            yield sse({"type": "error", "content": "Limite de uso do provedor de IA atingido. Aguarde um pouco e tente de novo."})
        except Exception as e:
            logger.exception("chat error")
            yield sse({"type": "error", "content": str(e)[:300]})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ------------ Health ------------
@api.get("/")
async def root():
    return {"service": "Azure FinOps Copilot", "status": "ok"}


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)