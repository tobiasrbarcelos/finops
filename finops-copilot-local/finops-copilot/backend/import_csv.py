"""Importa exportações de custo do Azure (CSV baixado do Cost Management) para o banco do app.

Os CSVs diários, por medidor, têm centenas de milhares de linhas. Aqui eles são agregados por
mês x recurso x serviço antes de gravar, o que derruba o volume para alguns milhares de registros
e mantém o dashboard rápido, inclusive com o banco em memória.
"""
import glob
import logging
import os
import pickle
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from starlette.concurrency import run_in_threadpool

from azure_sync import _service_from_type, infer_env

logger = logging.getLogger("finops")

CACHE_VERSION = 3
# Só os N recursos que mais custam entram com detalhe; o resto vira grupos (subscription x serviço x região).
# Os totais continuam exatos; o limite existe para o banco em memória não travar com centenas de milhares de recursos.
TOP_RESOURCES = int(os.environ.get("CSV_TOP_RESOURCES", "500"))

# nomes possíveis de coluna (comparação sem maiúsculas, espaços ou símbolos)
CANDIDATES: Dict[str, List[str]] = {
    "date": ["UsageDate", "Date", "UsageDateTime", "BillingMonth", "Month"],
    "resource_id": ["ResourceId", "InstanceId"],
    "resource_type": ["ResourceType"],
    "region": ["ResourceLocation", "Location", "ResourceRegion"],
    "resource_group": ["ResourceGroupName", "ResourceGroup"],
    "sub_name": ["SubscriptionName", "Subscription name", "Subscription"],
    "sub_id": ["SubscriptionId", "Subscription ID", "SubscriptionGuid"],
    "service": ["ServiceName", "Service name", "MeterCategory", "Service"],
    "cost": ["Cost", "CostInBillingCurrency", "PreTaxCost", "CostInPricingCurrency", "Total"],
    "cost_usd": ["CostUSD"],
    "currency": ["Currency", "BillingCurrency", "BillingCurrencyCode"],
}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def find_csv_files(root: Path) -> List[Path]:
    """CSVs em backend/dados/*.csv e o antigo backend/custos_azure.csv."""
    files = sorted(Path(p) for p in glob.glob(str(root / "dados" / "*.csv")))
    legacy = root / "custos_azure.csv"
    if legacy.exists():
        files.append(legacy)
    return files


def _detect_encoding(path: Path) -> str:
    with open(path, "rb") as f:
        head = f.read(4)
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    try:
        with open(path, encoding="utf-8-sig") as f:
            f.read(1_000_000)
        return "utf-8-sig"
    except UnicodeError:
        return "latin-1"


def _pick(columns: List[str], key: str) -> Optional[str]:
    by_norm = {_norm(c): c for c in columns}
    for cand in CANDIDATES[key]:
        if _norm(cand) in by_norm:
            return by_norm[_norm(cand)]
    return None


def _to_number(s: pd.Series) -> pd.Series:
    num = pd.to_numeric(s, errors="coerce")
    bad = num.isna() & s.notna() & (s.str.strip() != "")
    if bad.any():  # formato brasileiro: 1.234,56
        fixed = s[bad].str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        num[bad] = pd.to_numeric(fixed, errors="coerce")
    return num.fillna(0.0)


def _to_month(s: pd.Series) -> pd.Series:
    d = s.astype(str).str.strip()
    out = d.str.slice(0, 7)
    iso = out.str.match(r"^\d{4}-\d{2}$")
    ymd = ~iso & d.str.match(r"^\d{8}$")
    out[ymd] = d[ymd].str.slice(0, 4) + "-" + d[ymd].str.slice(4, 6)
    rest = ~iso & ~ymd
    if rest.any():  # ex.: 10/01/2025
        parsed = pd.to_datetime(d[rest], errors="coerce", format="mixed")
        out[rest] = parsed.dt.strftime("%Y-%m")
    return out.where(out.str.match(r"^\d{4}-\d{2}$", na=False), None)


def _read_normalized(path: Path, default_currency: str) -> Tuple[pd.DataFrame, str]:
    enc = _detect_encoding(path)
    header = list(pd.read_csv(path, nrows=0, encoding=enc).columns)
    cols = {k: _pick(header, k) for k in CANDIDATES}
    if not cols["date"] or not (cols["cost"] or cols["cost_usd"]):
        raise ValueError(
            f"{path.name}: não achei as colunas de data e custo. Colunas do arquivo: {', '.join(header[:20])}"
        )
    use = sorted({c for c in cols.values() if c})
    raw = pd.read_csv(path, usecols=use, dtype=str, encoding=enc, keep_default_na=False, low_memory=False)

    def col(key: str, default: str = "") -> pd.Series:
        c = cols[key]
        return raw[c].str.strip() if c else pd.Series(default, index=raw.index)

    if cols["cost"]:
        amount, cost_label = _to_number(raw[cols["cost"]]), cols["cost"]
        currency = col("currency").str.upper().replace("", default_currency)
        if not cols["currency"]:
            cost_label += f" (moeda assumida: {default_currency})"
    else:
        amount, cost_label = _to_number(raw[cols["cost_usd"]]), cols["cost_usd"]
        currency = pd.Series("USD", index=raw.index)

    rid = col("resource_id").str.lower()
    service = col("service").replace("", "Outros")
    df = pd.DataFrame({
        "month": _to_month(raw[cols["date"]]),
        "resource_id": rid,
        "resource_type": col("resource_type").str.lower(),
        "region": col("region").replace("", "N/A"),
        "resource_group": col("resource_group").str.lower().replace("", "-"),
        "sub_name": col("sub_name").replace("", "(sem subscription)"),
        "sub_id_col": col("sub_id").str.lower(),
        "service": service,
        "currency": currency,
        "amount": amount,
    })
    df["sub_id_rid"] = rid.str.extract(r"/subscriptions/([0-9a-f-]{36})", expand=False)
    # linhas sem ResourceId (ex.: marketplace) continuam entrando nos totais
    no_rid = df["resource_id"] == ""
    df.loc[no_rid, "resource_id"] = "sem-recurso/" + df.loc[no_rid, "service"].str.lower().str.replace(r"\s+", "-", regex=True)
    # tipo do recurso a partir do ResourceId, quando a coluna vier vazia
    no_type = df["resource_type"] == ""
    if no_type.any():
        derived = df.loc[no_type, "resource_id"].str.extract(r"/providers/([^/]+/[^/]+)", expand=False).fillna("")
        df.loc[no_type, "resource_type"] = derived
    df = df[df["month"].notna()]
    return df, cost_label


def _slug(name: str) -> str:
    return "sub-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _aggregate(paths: List[Path], default_currency: str, cache_path: Optional[Path]):
    sig = [(str(p), p.stat().st_size, int(p.stat().st_mtime)) for p in paths] + [default_currency, CACHE_VERSION]
    if cache_path and cache_path.exists():
        try:
            with open(cache_path, "rb") as f:
                cached = pickle.load(f)
            if cached.get("sig") == sig:
                logger.info("CSV: usando cache agregado (%d linhas)", len(cached["agg"]))
                return cached["agg"], cached["warnings"], cached["info"]
        except Exception:
            pass

    frames, warnings, info = [], [], {"files": [], "rows_read": 0}
    seen: Dict[Tuple[str, str], str] = {}
    for p in paths:
        df, cost_label = _read_normalized(p, default_currency)
        info["files"].append({"arquivo": p.name, "linhas": int(len(df)), "coluna_de_custo": cost_label})
        info["rows_read"] += int(len(df))
        pairs = set(zip(df["sub_name"], df["month"]))
        dup = [k for k in pairs if k in seen and seen[k] != p.name]
        if dup:
            warnings.append(f"{p.name}: {len(dup)} combinações subscription/mês já aparecem em outro arquivo (custo pode estar duplicado)")
        for k in pairs:
            seen.setdefault(k, p.name)
        frames.append(df)
    if not frames:
        raise ValueError("Nenhum CSV encontrado")
    df = pd.concat(frames, ignore_index=True)

    # subscription_id: coluna do arquivo > GUID dentro do ResourceId > slug do nome
    id_by_name: Dict[str, str] = {}
    for name, grp in df.groupby("sub_name", sort=False):
        explicit = grp["sub_id_col"][grp["sub_id_col"] != ""]
        from_rid = grp["sub_id_rid"].dropna()
        id_by_name[name] = (explicit.iloc[0] if len(explicit) else from_rid.iloc[0] if len(from_rid) else _slug(name))
    df["sub_id"] = df["sub_name"].map(id_by_name)

    keys = ["month", "resource_id", "sub_id", "sub_name", "service", "resource_group", "region", "resource_type", "currency"]
    agg = df.groupby(keys, as_index=False, sort=False)["amount"].sum()
    agg["amount"] = agg["amount"].round(6)
    agg = agg[agg["amount"] != 0].reset_index(drop=True)
    info["groups"] = int(len(agg))

    if cache_path:
        try:
            with open(cache_path, "wb") as f:
                pickle.dump({"sig": sig, "agg": agg, "warnings": warnings, "info": info}, f)
        except Exception:
            logger.warning("CSV: não consegui gravar o cache")
    return agg, warnings, info


def _resource_name(rid: str) -> str:
    segs = [s for s in rid.split("/") if s]
    if not segs:
        return rid
    name = segs[-1]
    if name in ("reservations", "$system") and len(segs) > 1:
        name = f"{segs[-2]}"
    return name


def _prev_month_key() -> str:
    now = datetime.now(timezone.utc)
    y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    return f"{y:04d}-{m:02d}"


async def _insert_chunks(coll, docs: List[Dict[str, Any]], sync_id: str, size: int = 2000) -> None:
    for i in range(0, len(docs), size):
        await coll.insert_many([{**d, "sync_id": sync_id} for d in docs[i:i + size]])


async def import_csv_files(db, paths: List[Path], cache_path: Optional[Path] = None,
                           default_currency: str = "BRL") -> Dict[str, Any]:
    """Substitui os dados do app (mock, sync anterior ou CSV antigo) pelo conteúdo dos CSVs."""
    t0 = time.time()
    agg, warnings, info = await run_in_threadpool(_aggregate, paths, default_currency, cache_path)

    manual = {
        d["id"]: d["environment"]
        async for d in db.subscriptions.find({"environment_source": "manual"}, {"_id": 0, "id": 1, "environment": 1})
    }
    subs: Dict[str, Dict[str, Any]] = {}
    for sid, name in agg[["sub_id", "sub_name"]].drop_duplicates().itertuples(index=False):
        if sid in manual:
            env, src = manual[sid], "manual"
        else:
            env, src = infer_env(name), "inferred"
        subs[sid] = {"id": sid, "name": name, "state": "Enabled", "environment": env, "environment_source": src}

    n_res_total = int(agg["resource_id"].nunique())
    total_abs = agg.groupby("resource_id")["amount"].apply(lambda x: x.abs().sum())
    keep = set(total_abs.nlargest(TOP_RESOURCES).index)
    detail = agg[agg["resource_id"].isin(keep)]
    tail = agg[~agg["resource_id"].isin(keep)]

    def cost_doc(r, resource_id, rg, bucket):
        d = {"resource_id": resource_id, "subscription_id": r.sub_id, "subscription_name": r.sub_name,
             "service": r.service, "resource_group": rg, "region": r.region, "tags": {},
             "month": r.month, "amount": float(r.amount), "currency": r.currency, "source": "csv"}
        if bucket:
            d["bucket"] = True
        return d

    costs = [cost_doc(r, r.resource_id, r.resource_group, False) for r in detail.itertuples(index=False)]

    prev = _prev_month_key()
    last = detail[detail["month"] == prev].groupby("resource_id")["amount"].sum()
    resources = []
    for r in detail.drop_duplicates("resource_id", keep="last").itertuples(index=False):
        t = r.resource_type or ""
        resources.append({
            "id": r.resource_id, "name": _resource_name(r.resource_id), "type": _service_from_type(t),
            "azure_type": t, "subscription_id": r.sub_id, "subscription_name": r.sub_name,
            "environment": subs[r.sub_id]["environment"], "resource_group": r.resource_group,
            "region": r.region, "monthly_cost": round(float(last.get(r.resource_id, 0.0)), 2),
            "tags": {}, "cpu_avg_30d": None, "power_state": None, "attached": True, "sku": None,
        })

    if len(tail):
        gkeys = ["month", "sub_id", "sub_name", "service", "region", "currency"]
        grouped = tail.groupby(gkeys, as_index=False, sort=False)["amount"].sum()
        grouped["amount"] = grouped["amount"].round(6)
        n_in_bucket = tail.groupby(["sub_id", "service", "region"])["resource_id"].nunique()
        for r in grouped.itertuples(index=False):
            rid = f"outros/{r.sub_id}/{_slug(r.service)}/{_slug(r.region)}"
            costs.append(cost_doc(r, rid, "(vários)", True))
        for (sid, service, region), n in n_in_bucket.items():
            rid = f"outros/{sid}/{_slug(service)}/{_slug(region)}"
            prev_cost = grouped[(grouped["sub_id"] == sid) & (grouped["service"] == service)
                                & (grouped["region"] == region) & (grouped["month"] == prev)]["amount"].sum()
            resources.append({
                "id": rid, "name": f"Outros {int(n)} recursos · {service} · {region}", "type": service,
                "azure_type": "", "subscription_id": sid, "subscription_name": subs[sid]["name"],
                "environment": subs[sid]["environment"], "resource_group": "(vários)", "region": region,
                "monthly_cost": round(float(prev_cost), 2), "tags": {}, "cpu_avg_30d": None, "power_state": None,
                "attached": True, "sku": None, "bucket": True,
            })

    sync_id = uuid.uuid4().hex
    colls = (db.costs, db.resources, db.subscriptions)
    try:
        await _insert_chunks(db.costs, costs, sync_id)
        await _insert_chunks(db.resources, resources, sync_id)
        await _insert_chunks(db.subscriptions, list(subs.values()), sync_id)
    except Exception:
        for c in colls:
            await c.delete_many({"sync_id": sync_id})
        raise
    old = {"sync_id": {"$ne": sync_id}}
    for c in colls:
        await c.delete_many(old)
    await db.recommendations.delete_many({})  # recomendações dependem do Azure real (CPU, discos órfãos, tags)

    totals = agg.groupby("currency")["amount"].sum().round(2).to_dict()
    months = sorted(agg["month"].unique())
    result = {
        "subscriptions_synced": len(subs), "resources_synced": len(resources), "costs_synced": len(costs),
        "recommendations": 0, "duration_seconds": round(time.time() - t0, 1), "warnings": warnings,
        "files": info["files"], "rows_read": info["rows_read"], "totals_by_currency": totals,
        "resources_total": n_res_total, "resources_detailed": len(keep),
        "cost_share_detailed_pct": round(float(detail["amount"].sum() / agg["amount"].sum() * 100), 1) if len(agg) else 100.0,
        "first_month": months[0] if months else None, "last_month": months[-1] if months else None,
    }
    await db.sync_status.delete_many({})
    await db.sync_status.insert_one({
        "status": "success", "source": "azure", "trigger": "csv",
        "last_sync": datetime.now(timezone.utc).isoformat(),
        "message": (f"Importado de {len(paths)} arquivo(s) CSV ({result['first_month']} a {result['last_month']}); "
                    f"{result['resources_detailed']} de {result['resources_total']} recursos com detalhe "
                    f"({result['cost_share_detailed_pct']}% do custo), o restante agrupado por subscription/serviço/região"),
        **{k: result[k] for k in ("subscriptions_synced", "resources_synced", "costs_synced",
                                  "recommendations", "duration_seconds", "warnings")},
    })
    return result