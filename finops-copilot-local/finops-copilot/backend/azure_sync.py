"""Real Azure ingestion: Cost Management + Resource Graph + Monitor → Mongo (same shape as mock)."""
import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from starlette.concurrency import run_in_threadpool
from azure.identity import ClientSecretCredential
from azure.identity.aio import ClientSecretCredential as AsyncClientSecretCredential
from azure.mgmt.subscription import SubscriptionClient
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
from azure.monitor.query.aio import MetricsQueryClient
from azure.monitor.query import MetricAggregationType

logger = logging.getLogger("finops.azure")

ENVIRONMENTS = ("dev", "hml", "prd")
_ENV_TOKENS = {
    "dev": {"dev", "development", "desenv", "desenvolvimento"},
    "hml": {"hml", "homolog", "homologacao", "hom", "stg", "staging", "qa"},
    "prd": {"prd", "prod", "production", "producao"},
}
REQUIRED_TAGS = ("owner", "cost_center")


def _month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def _months_back(n: int) -> datetime:
    now = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    y, m = now.year, now.month - n
    while m <= 0:
        y -= 1
        m += 12
    return now.replace(year=y, month=m)


def infer_env(sub_name: str) -> str:
    """Infere o ambiente pelo NOME da subscription, por palavra inteira (não por trecho).
    Sem correspondência → 'unmapped' (o usuário ajusta em Settings)."""
    tokens = set(re.split(r"[^a-z0-9]+", (sub_name or "").lower()))
    for env, words in _ENV_TOKENS.items():
        if tokens & words:
            return env
    return "unmapped"


# ---------------- Subscriptions ----------------
def _list_subscriptions(cred) -> List[Dict[str, Any]]:
    client = SubscriptionClient(cred)
    return [
        {"id": s.subscription_id, "name": s.display_name, "state": str(s.state)}
        for s in client.subscriptions.list()
    ]


# ---------------- Cost Management ----------------
def _query_costs(cred, sub: Dict[str, Any]) -> List[Dict[str, Any]]:
    client = CostManagementClient(cred)
    start = _months_back(11)
    end = datetime.now(timezone.utc)
    definition = {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {"from": start.isoformat(), "to": end.isoformat()},
        "dataset": {
            "granularity": "Monthly",
            "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}},
            "grouping": [
                {"type": "Dimension", "name": "ResourceId"},
                {"type": "Dimension", "name": "ServiceName"},
                {"type": "Dimension", "name": "ResourceGroupName"},
                {"type": "Dimension", "name": "ResourceLocation"},
            ],
        },
    }
    result = client.query.usage(f"/subscriptions/{sub['id']}", definition)
    cols = [c.name for c in (result.columns or [])]
    rows = []
    for raw in result.rows or []:
        row = dict(zip(cols, raw))
        amount = float(row.get("PreTaxCost") or row.get("Cost") or 0)
        if amount <= 0:
            continue
        month = _parse_month(row.get("BillingMonth") or row.get("UsageDate"))
        if not month:
            continue
        rid = (row.get("ResourceId") or "unknown").lower()
        rows.append({
            "resource_id": rid,
            "subscription_id": sub["id"],
            "subscription_name": sub["name"],
            "service": row.get("ServiceName") or "Other",
            "resource_group": (row.get("ResourceGroupName") or "n/a").lower(),
            "region": row.get("ResourceLocation") or "unknown",
            "tags": {},
            "month": month,
            "amount": round(amount, 2),
            "currency": row.get("Currency") or "USD",
        })
    return rows


def _parse_month(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v)
    if re.match(r"^\d{8}", s):
        return f"{s[:4]}-{s[4:6]}"
    m = re.match(r"^(\d{4})-(\d{2})", s)
    return f"{m.group(1)}-{m.group(2)}" if m else None


# ---------------- Resource Graph ----------------
RG_QUERY = """
Resources
| extend managedBy = tostring(managedBy),
         ipConfig = tostring(properties.ipConfiguration.id),
         vmSize = tostring(properties.hardwareProfile.vmSize),
         powerState = tostring(properties.extended.instanceView.powerState.code),
         diskState = tostring(properties.diskState)
| project id, name, type, resourceGroup, location, subscriptionId, tags, managedBy, ipConfig, vmSize, powerState, diskState
"""


def _query_resources(cred, sub_ids: List[str]) -> List[Dict[str, Any]]:
    client = ResourceGraphClient(cred)
    out, skip = [], None
    while True:
        opts = QueryRequestOptions(skip_token=skip, result_format="objectArray")
        resp = client.resources(QueryRequest(query=RG_QUERY, subscriptions=sub_ids, options=opts))
        out.extend(resp.data or [])
        skip = resp.skip_token
        if not skip:
            break
    return out


# ---------------- Monitor (VM CPU) ----------------
async def _vm_cpu_map(sp: Dict[str, str], vm_ids: List[str]) -> Dict[str, Optional[float]]:
    if not vm_ids:
        return {}
    cred = AsyncClientSecretCredential(sp["tenant_id"], sp["client_id"], sp["client_secret"])
    client = MetricsQueryClient(cred)
    sem = asyncio.Semaphore(8)
    result: Dict[str, Optional[float]] = {}

    async def one(vm_id: str):
        async with sem:
            try:
                r = await client.query_resource(
                    vm_id, metric_names=["Percentage CPU"], timespan=timedelta(days=30),
                    granularity=timedelta(days=1), aggregations=[MetricAggregationType.AVERAGE],
                )
                vals = [p.average for m in r.metrics for ts in m.timeseries for p in ts.data if p.average is not None]
                result[vm_id.lower()] = round(sum(vals) / len(vals), 1) if vals else None
            except Exception as e:
                logger.warning(f"metrics failed for {vm_id}: {e}")
                result[vm_id.lower()] = None

    try:
        await asyncio.gather(*(one(v) for v in vm_ids))
    finally:
        await client.close()
        await cred.close()
    return result


# ---------------- Transform ----------------
def _service_from_type(t: str) -> str:
    t = (t or "").lower()
    mapping = {
        "microsoft.compute/virtualmachines": "Virtual Machines",
        "microsoft.compute/disks": "Storage",
        "microsoft.network/publicipaddresses": "Networking",
        "microsoft.storage/storageaccounts": "Storage",
        "microsoft.sql/servers/databases": "SQL Database",
        "microsoft.web/sites": "App Service",
        "microsoft.containerservice/managedclusters": "Kubernetes Service",
        "microsoft.documentdb/databaseaccounts": "Cosmos DB",
        "microsoft.keyvault/vaults": "Key Vault",
    }
    return mapping.get(t, t.split("/")[-1].replace("_", " ").title() if t else "Other")


def build_resources(raw: List[Dict[str, Any]], subs: Dict[str, str], last_month_cost: Dict[str, float],
                    cpu: Dict[str, Optional[float]], sub_env: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    sub_env = sub_env or {}
    out = []
    for r in raw:
        rid = (r.get("id") or "").lower()
        t = (r.get("type") or "").lower()
        tags = {k.lower(): v for k, v in (r.get("tags") or {}).items()}
        sub_name = subs.get(r.get("subscriptionId"), r.get("subscriptionId"))
        env = sub_env.get(r.get("subscriptionId"), "unmapped")
        is_vm = t == "microsoft.compute/virtualmachines"
        is_disk = t == "microsoft.compute/disks"
        is_pip = t == "microsoft.network/publicipaddresses"
        attached = True
        if is_disk:
            attached = bool(r.get("managedBy")) and (r.get("diskState") or "").lower() != "unattached"
        if is_pip:
            attached = bool(r.get("ipConfig"))
        out.append({
            "id": rid,
            "name": r.get("name"),
            "type": _service_from_type(t),
            "azure_type": t,
            "subscription_id": r.get("subscriptionId"),
            "subscription_name": sub_name,
            "environment": env,
            "resource_group": (r.get("resourceGroup") or "").lower(),
            "region": r.get("location"),
            "monthly_cost": last_month_cost.get(rid, 0.0),
            "tags": tags,
            "cpu_avg_30d": cpu.get(rid) if is_vm else None,
            "power_state": r.get("powerState") if is_vm else None,
            "attached": attached,
            "sku": r.get("vmSize") if is_vm else None,
        })
    return out


def build_recommendations(resources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    recs, rid = [], 0

    def add(r, category, label, severity, savings, action):
        nonlocal rid
        rid += 1
        recs.append({
            "id": f"rec-{rid:04d}", "category": category, "category_label": label, "severity": severity,
            "resource_id": r["id"], "resource_name": r["name"], "subscription_id": r["subscription_id"],
            "subscription_name": r["subscription_name"], "resource_group": r["resource_group"],
            "monthly_savings": round(savings, 2), "action": action, "current_cost": r["monthly_cost"],
            "sku": r.get("sku"),
        })

    for r in resources:
        cpu = r.get("cpu_avg_30d")
        running = "deallocated" not in (r.get("power_state") or "").lower()
        if r["azure_type"] == "microsoft.compute/virtualmachines" and running and cpu is not None:
            if cpu < 5:
                add(r, "idle_vm", "VM Ociosa", "high", r["monthly_cost"] * 0.95,
                    f"Desligar ou deallocate VM (CPU média {cpu}% nos últimos 30 dias)")
            elif cpu < 25:
                add(r, "rightsizing", "Rightsizing", "medium", r["monthly_cost"] * 0.45,
                    f"Redimensionar {r['sku']} para um tamanho menor (CPU média {cpu}%)")
        if r["azure_type"] == "microsoft.compute/disks" and not r["attached"]:
            add(r, "orphan_disk", "Disco Órfão", "medium", r["monthly_cost"],
                "Deletar disco gerenciado não anexado a nenhuma VM")
        if r["azure_type"] == "microsoft.network/publicipaddresses" and not r["attached"]:
            add(r, "unused_ip", "IP Público Sem Uso", "low", r["monthly_cost"] or 15.0,
                "Deletar IP público não associado a nenhum recurso")
        missing = [k for k in REQUIRED_TAGS if not r["tags"].get(k)]
        if missing and r["monthly_cost"] > 0:
            add(r, "missing_tags", "Tags Faltando", "low", 0.0,
                f"Adicionar tags obrigatórias: {', '.join(missing)}")
        if r.get("environment") in ("dev", "hml") and r["type"] in ("Virtual Machines", "SQL Database") \
                and r["monthly_cost"] > 0:
            add(r, "dev_offhours", "Dev/HML Fora de Horário", "medium", r["monthly_cost"] * 0.65,
                "Desligar automaticamente fora do horário comercial (19h-7h e finais de semana)")
    return recs


# ---------------- Orchestrator ----------------
async def _insert_chunks(coll, docs: List[Dict[str, Any]], sync_id: str, size: int = 1000) -> None:
    for i in range(0, len(docs), size):
        await coll.insert_many([{**d, "sync_id": sync_id} for d in docs[i:i + size]])


async def run_azure_sync(db, sp: Dict[str, str]) -> Dict[str, Any]:
    started = datetime.now(timezone.utc)
    sync_id = uuid.uuid4().hex
    cred = ClientSecretCredential(sp["tenant_id"], sp["client_id"], sp["client_secret"])

    subs = await run_in_threadpool(_list_subscriptions, cred)
    subs = [s for s in subs if "enabled" in s["state"].lower()]
    if not subs:
        raise RuntimeError("Nenhuma subscription habilitada visível para o Service Principal")

    # Ambiente (dev/hml/prd) é definido por subscription: ajuste manual (Settings) > inferido pelo nome
    manual = {
        d["id"]: d["environment"]
        async for d in db.subscriptions.find({"environment_source": "manual"}, {"_id": 0, "id": 1, "environment": 1})
    }
    for s in subs:
        if s["id"] in manual:
            s["environment"], s["environment_source"] = manual[s["id"]], "manual"
        else:
            s["environment"], s["environment_source"] = infer_env(s["name"]), "inferred"
    sub_names = {s["id"]: s["name"] for s in subs}
    sub_env = {s["id"]: s["environment"] for s in subs}

    costs: List[Dict[str, Any]] = []
    errors: List[str] = []
    ok_ids: List[str] = []
    for s in subs:
        try:
            costs.extend(await run_in_threadpool(_query_costs, cred, s))
            ok_ids.append(s["id"])
        except Exception as e:
            logger.warning(f"cost query failed for {s['id']}: {e}")
            errors.append(f"costs[{s['name']}]: {e} (custos anteriores mantidos)")
    if not ok_ids:
        raise RuntimeError("Falha ao consultar custos em todas as subscriptions: " + "; ".join(errors[:3]))

    raw_res = await run_in_threadpool(_query_resources, cred, list(sub_names))

    prev_month = _month_key(_months_back(1))
    last_cost: Dict[str, float] = {}
    for c in costs:
        if c["month"] == prev_month:
            last_cost[c["resource_id"]] = round(last_cost.get(c["resource_id"], 0) + c["amount"], 2)

    vm_ids = [r["id"] for r in raw_res if (r.get("type") or "").lower() == "microsoft.compute/virtualmachines"]
    cpu = await _vm_cpu_map(sp, vm_ids)

    resources = build_resources(raw_res, sub_names, last_cost, cpu, sub_env)
    tag_by_id = {r["id"]: r["tags"] for r in resources}
    for c in costs:
        c["tags"] = tag_by_id.get(c["resource_id"], {})
    recs = build_recommendations(resources)

    # Grava o novo conjunto ANTES de remover o antigo; se algo falhar, desfaz só o que acabou de inserir.
    all_ids = list(sub_names)
    try:
        await _insert_chunks(db.costs, costs, sync_id)
        await _insert_chunks(db.resources, resources, sync_id)
        await _insert_chunks(db.recommendations, recs, sync_id)
        await _insert_chunks(db.subscriptions, subs, sync_id)
    except Exception:
        for coll in (db.costs, db.resources, db.recommendations, db.subscriptions):
            await coll.delete_many({"sync_id": sync_id})
        raise

    old = {"sync_id": {"$ne": sync_id}}
    # custos: troca só as subscriptions que sincronizaram; remove as que não aparecem mais (inclui mock)
    await db.costs.delete_many({**old, "$or": [{"subscription_id": {"$in": ok_ids}},
                                              {"subscription_id": {"$nin": all_ids}}]})
    await db.resources.delete_many(old)
    await db.recommendations.delete_many(old)
    await db.subscriptions.delete_many(old)

    return {
        "subscriptions_synced": len(subs),
        "resources_synced": len(resources),
        "costs_synced": len(costs),
        "recommendations": len(recs),
        "duration_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
        "warnings": errors,
    }
