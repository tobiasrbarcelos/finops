"""Mock Azure data generator — realistic shape for subscriptions, resources, costs, recommendations."""
import random
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

random.seed(42)

SUBSCRIPTIONS = [
    {"id": "sub-prod-001", "name": "PROD-Core", "state": "Enabled"},
    {"id": "sub-prod-002", "name": "PROD-Analytics", "state": "Enabled"},
    {"id": "sub-dev-001", "name": "DEV-Sandbox", "state": "Enabled"},
    {"id": "sub-hml-001", "name": "HML-Staging", "state": "Enabled"},
]

SERVICES = ["Virtual Machines", "Storage", "SQL Database", "App Service", "Kubernetes Service",
            "Cosmos DB", "Networking", "Key Vault", "Container Registry", "Monitor", "Backup", "CDN"]

REGIONS = ["brazilsouth", "eastus", "westeurope", "northeurope"]

RG_NAMES = ["rg-app-prod", "rg-data-prod", "rg-k8s-prod", "rg-network-hub",
            "rg-analytics", "rg-ml-experiments", "rg-dev-team-a", "rg-dev-team-b",
            "rg-hml-shared", "rg-backup"]

TAG_OWNERS = ["team-platform", "team-data", "team-app", "team-ml", None, None, "team-devops"]
TAG_CC = ["CC-1001", "CC-1002", "CC-2001", "CC-3001", None, None]


def _month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def generate_resources() -> List[Dict[str, Any]]:
    resources = []
    counter = 0
    for sub in SUBSCRIPTIONS:
        n_res = random.randint(35, 60) if "PROD" in sub["name"] else random.randint(15, 30)
        for _ in range(n_res):
            counter += 1
            svc = random.choice(SERVICES)
            rg = random.choice(RG_NAMES)
            region = random.choice(REGIONS)
            monthly_cost = round(random.uniform(5, 2500), 2)
            resources.append({
                "id": f"res-{counter:04d}",
                "name": f"{svc.lower().replace(' ', '')}-{counter:04d}",
                "type": svc,
                "subscription_id": sub["id"],
                "subscription_name": sub["name"],
                "resource_group": rg,
                "region": region,
                "monthly_cost": monthly_cost,
                "tags": {
                    "owner": random.choice(TAG_OWNERS),
                    "cost_center": random.choice(TAG_CC),
                    "environment": "prod" if "PROD" in sub["name"] else ("dev" if "DEV" in sub["name"] else "hml"),
                },
                "cpu_avg_30d": round(random.uniform(1, 85), 1) if svc == "Virtual Machines" else None,
                "attached": random.choices([True, False], weights=[0.85, 0.15])[0] if svc == "Storage" else True,
                "sku": random.choice(["Standard_D2s_v3", "Standard_D4s_v3", "Standard_D8s_v3", "Standard_B2s"]) if svc == "Virtual Machines" else None,
            })
    return resources


def generate_costs(resources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generate 13 months of daily costs (approximated as monthly buckets per resource)."""
    costs = []
    now = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for i in range(13):
        month_start = (now - timedelta(days=30 * i)).replace(day=1)
        month_key = _month_key(month_start)
        # Seasonal variation
        factor = 1.0 + (0.15 * random.random() - 0.05) + (0.08 if i in (2, 3, 8, 9) else 0)
        for res in resources:
            cost = round(res["monthly_cost"] * factor * random.uniform(0.85, 1.15), 2)
            costs.append({
                "resource_id": res["id"],
                "subscription_id": res["subscription_id"],
                "subscription_name": res["subscription_name"],
                "service": res["type"],
                "resource_group": res["resource_group"],
                "region": res["region"],
                "tags": res["tags"],
                "month": month_key,
                "amount": cost,
                "currency": "BRL",
            })
    return costs


def generate_recommendations(resources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    recs = []
    rid = 0

    # 1. Idle VMs (guarantee at least some by re-scoring 15% of VMs to be idle)
    vm_list = [r for r in resources if r["type"] == "Virtual Machines"]
    for r in vm_list[: max(1, len(vm_list) // 8)]:
        r["cpu_avg_30d"] = round(random.uniform(0.5, 4.5), 1)

    for r in resources:
        if r["type"] == "Virtual Machines" and r["cpu_avg_30d"] and r["cpu_avg_30d"] < 5:
            rid += 1
            recs.append({
                "id": f"rec-{rid:04d}",
                "category": "idle_vm",
                "category_label": "VM Ociosa",
                "severity": "high",
                "resource_id": r["id"],
                "resource_name": r["name"],
                "subscription_id": r["subscription_id"],
                "subscription_name": r["subscription_name"],
                "resource_group": r["resource_group"],
                "monthly_savings": round(r["monthly_cost"] * 0.95, 2),
                "action": f"Desligar ou deallocate VM (CPU média {r['cpu_avg_30d']}% nos últimos 30 dias)",
                "current_cost": r["monthly_cost"],
                "sku": r["sku"],
            })

    # 2. Orphan disks (unattached storage)
    for r in resources:
        if r["type"] == "Storage" and not r["attached"]:
            rid += 1
            recs.append({
                "id": f"rec-{rid:04d}",
                "category": "orphan_disk",
                "category_label": "Disco Órfão",
                "severity": "medium",
                "resource_id": r["id"],
                "resource_name": r["name"],
                "subscription_id": r["subscription_id"],
                "subscription_name": r["subscription_name"],
                "resource_group": r["resource_group"],
                "monthly_savings": round(r["monthly_cost"] * 1.0, 2),
                "action": "Deletar disco não anexado há mais de 30 dias",
                "current_cost": r["monthly_cost"],
            })

    # 3. Rightsizing (VMs oversized 20-50% CPU)
    for r in resources:
        if r["type"] == "Virtual Machines" and r["cpu_avg_30d"] and 5 <= r["cpu_avg_30d"] < 25:
            rid += 1
            recs.append({
                "id": f"rec-{rid:04d}",
                "category": "rightsizing",
                "category_label": "Rightsizing",
                "severity": "medium",
                "resource_id": r["id"],
                "resource_name": r["name"],
                "subscription_id": r["subscription_id"],
                "subscription_name": r["subscription_name"],
                "resource_group": r["resource_group"],
                "monthly_savings": round(r["monthly_cost"] * 0.45, 2),
                "action": f"Redimensionar de {r['sku']} para um tamanho menor (CPU média {r['cpu_avg_30d']}%)",
                "current_cost": r["monthly_cost"],
                "sku": r["sku"],
            })

    # 4. Missing tags
    for r in resources:
        if not r["tags"].get("owner") or not r["tags"].get("cost_center"):
            rid += 1
            missing = [k for k in ("owner", "cost_center") if not r["tags"].get(k)]
            recs.append({
                "id": f"rec-{rid:04d}",
                "category": "missing_tags",
                "category_label": "Tags Faltando",
                "severity": "low",
                "resource_id": r["id"],
                "resource_name": r["name"],
                "subscription_id": r["subscription_id"],
                "subscription_name": r["subscription_name"],
                "resource_group": r["resource_group"],
                "monthly_savings": 0.0,
                "action": f"Adicionar tags obrigatórias: {', '.join(missing)}",
                "current_cost": r["monthly_cost"],
            })

    # 5. Dev off-hours
    for r in resources:
        if r["tags"].get("environment") in ("dev", "hml") and r["type"] in ("Virtual Machines", "SQL Database"):
            rid += 1
            recs.append({
                "id": f"rec-{rid:04d}",
                "category": "dev_offhours",
                "category_label": "Dev/HML Fora de Horário",
                "severity": "medium",
                "resource_id": r["id"],
                "resource_name": r["name"],
                "subscription_id": r["subscription_id"],
                "subscription_name": r["subscription_name"],
                "resource_group": r["resource_group"],
                "monthly_savings": round(r["monthly_cost"] * 0.65, 2),
                "action": "Desligar automaticamente fora do horário comercial (19h-7h e finais de semana)",
                "current_cost": r["monthly_cost"],
            })

    # 6. Unused public IPs (synthesize)
    for _ in range(6):
        rid += 1
        sub = random.choice(SUBSCRIPTIONS)
        recs.append({
            "id": f"rec-{rid:04d}",
            "category": "unused_ip",
            "category_label": "IP Público Sem Uso",
            "severity": "low",
            "resource_id": f"pip-{rid}",
            "resource_name": f"pip-orphan-{rid}",
            "subscription_id": sub["id"],
            "subscription_name": sub["name"],
            "resource_group": random.choice(RG_NAMES),
            "monthly_savings": round(random.uniform(15, 40), 2),
            "action": "Deletar IP público não associado a nenhum recurso",
            "current_cost": round(random.uniform(15, 40), 2),
        })

    # 7. Reserved Instances suggestions
    for sub in SUBSCRIPTIONS[:2]:
        rid += 1
        recs.append({
            "id": f"rec-{rid:04d}",
            "category": "reserved_instance",
            "category_label": "Reserved Instance / Savings Plan",
            "severity": "high",
            "resource_id": f"ri-{rid}",
            "resource_name": f"RI Bundle — {sub['name']}",
            "subscription_id": sub["id"],
            "subscription_name": sub["name"],
            "resource_group": "N/A",
            "monthly_savings": round(random.uniform(1800, 4500), 2),
            "action": "Comprar Reserved Instance de 3 anos para VMs com uso constante > 80%",
            "current_cost": round(random.uniform(6000, 12000), 2),
        })

    return recs
