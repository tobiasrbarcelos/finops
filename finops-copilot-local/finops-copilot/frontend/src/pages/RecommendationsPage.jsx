import { useEffect, useState } from "react";
import { api, fmtBRL } from "../lib/api";
import { useFilters } from "../lib/filters";
import { Sparkle, Warning, Info, Fire, Tag, Clock, Cpu, HardDrives, Network, Coins } from "@phosphor-icons/react";

const CAT_ICON = {
  idle_vm: Cpu,
  orphan_disk: HardDrives,
  rightsizing: Cpu,
  missing_tags: Tag,
  dev_offhours: Clock,
  unused_ip: Network,
  reserved_instance: Coins,
};

const SEV_STYLE = {
  high: { badge: "bg-[#FF3B30]/15 text-[#FF6B60] border-[#FF3B30]/30", label: "Alta" },
  medium: { badge: "bg-[#F59E0B]/15 text-[#F59E0B] border-[#F59E0B]/30", label: "Média" },
  low: { badge: "bg-[#3B82F6]/15 text-[#3B82F6] border-[#3B82F6]/30", label: "Baixa" },
};

export default function RecommendationsPage() {
  const [summary, setSummary] = useState(null);
  const [recs, setRecs] = useState([]);
  const [filter, setFilter] = useState(null);
  const [loading, setLoading] = useState(true);
  const { subscriptionId, environment } = useFilters();

  const load = async (cat) => {
    setLoading(true);
    const p = new URLSearchParams();
    if (cat) p.set("category", cat);
    if (subscriptionId) p.set("subscription_id", subscriptionId);
    if (environment) p.set("environment", environment);
    const [s, r] = await Promise.all([
      api.get(`/recommendations/summary?${p.toString()}`),
      api.get(`/recommendations?${p.toString()}`),
    ]);
    setSummary(s.data); setRecs(r.data); setLoading(false);
  };

  useEffect(() => { load(filter); }, [filter, subscriptionId, environment]);

  return (
    <div className="p-8 space-y-6" data-testid="recommendations-page">
      <header className="flex items-end justify-between">
        <div>
          <p className="eyebrow mb-2">Motor de Recomendações</p>
          <h1 className="font-display text-4xl font-bold tracking-tighter">Oportunidades de Economia</h1>
        </div>
        {summary && (
          <div className="text-right">
            <div className="eyebrow">Economia potencial total</div>
            <div className="font-display text-3xl font-bold text-[#10B981] tabular mt-1">
              {fmtBRL(summary.total_savings)}
              <span className="text-sm text-gray-500 font-normal ml-1">/mês</span>
            </div>
          </div>
        )}
      </header>

      {/* Category chips */}
      {summary && (
        <div className="flex flex-wrap gap-2" data-testid="category-filters">
          <button
            onClick={() => setFilter(null)}
            data-testid="cat-all"
            className={`px-3.5 py-2 rounded-md text-xs font-medium border transition-colors ${
              !filter ? "bg-white/10 border-white/20 text-white" : "bg-transparent border-white/10 text-gray-400 hover:text-white"
            }`}
          >
            Todas <span className="text-gray-500 ml-1">{summary.total_count}</span>
          </button>
          {summary.by_category.map((c) => {
            const Icon = CAT_ICON[c.category] || Sparkle;
            const active = filter === c.category;
            return (
              <button
                key={c.category}
                onClick={() => setFilter(c.category)}
                data-testid={`cat-${c.category}`}
                className={`px-3.5 py-2 rounded-md text-xs font-medium border transition-colors flex items-center gap-2 ${
                  active ? "bg-white/10 border-white/20 text-white" : "bg-transparent border-white/10 text-gray-400 hover:text-white"
                }`}
              >
                <Icon size={13} weight="regular" />
                {c.category_label}
                <span className="text-gray-500">{c.count}</span>
                {c.total_savings > 0 && <span className="text-[#10B981] tabular">{fmtBRL(c.total_savings)}</span>}
              </button>
            );
          })}
        </div>
      )}

      {loading ? (
        <div className="text-gray-500">Carregando…</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3" data-testid="recommendations-list">
          {recs.map((r) => {
            const Icon = CAT_ICON[r.category] || Sparkle;
            const sev = SEV_STYLE[r.severity] || SEV_STYLE.low;
            return (
              <div key={r.id} className="bento p-5 hover:-translate-y-[1px]">
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className="w-8 h-8 rounded-md bg-white/[0.04] border border-white/5 flex items-center justify-center shrink-0">
                      <Icon size={15} className="text-gray-300" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-xs font-medium text-gray-400">{r.category_label}</div>
                      <div className="text-sm font-semibold text-gray-100 truncate">{r.resource_name}</div>
                    </div>
                  </div>
                  <span className={`text-[10px] px-2 py-1 rounded border font-semibold uppercase tracking-wider ${sev.badge}`}>
                    {sev.label}
                  </span>
                </div>

                <p className="text-xs text-gray-400 leading-relaxed mb-4">{r.action}</p>

                <div className="flex items-center justify-between pt-3 border-t border-white/5">
                  <div className="text-[10px] text-gray-500 flex flex-col gap-0.5">
                    <span className="uppercase tracking-widest">{r.subscription_name}</span>
                    <span className="text-gray-400">{r.resource_group}</span>
                  </div>
                  <div className="text-right">
                    {r.monthly_savings > 0 ? (
                      <>
                        <div className="eyebrow">Economia/mês</div>
                        <div className="font-display font-bold text-[#10B981] tabular text-lg">{fmtBRL(r.monthly_savings)}</div>
                      </>
                    ) : (
                      <span className="text-[10px] text-gray-500 uppercase tracking-widest">Higiene</span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
