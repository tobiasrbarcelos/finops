import { Funnel, Stack, CalendarBlank, Cube } from "@phosphor-icons/react";
import { PERIODS, ENVS, useFilters } from "../lib/filters";

const selectCls = "bg-[#0A0A0B] border border-white/10 rounded-md pl-8 pr-3 py-2 text-sm text-gray-200 focus:border-white/30 outline-none appearance-none min-w-[190px]";

export function GlobalFilters() {
  const { period, setPeriod, subscriptionId, setSubscriptionId, environment, setEnvironment, subscriptions } = useFilters();
  const hasUnmapped = subscriptions.some((s) => s.environment === "unmapped");
  const visibleSubs = environment ? subscriptions.filter((s) => s.environment === environment) : subscriptions;
  return (
    <div className="flex items-center gap-3 flex-wrap" data-testid="global-filters">
      <span className="hidden md:inline-flex items-center gap-1.5 eyebrow"><Funnel size={12} /> Filtros</span>
      <label className="relative">
        <Cube size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
        <select data-testid="filter-environment" value={environment}
                onChange={(e) => { setEnvironment(e.target.value); setSubscriptionId(""); }} className={selectCls}>
          <option value="">Todos os ambientes</option>
          {ENVS.map((e) => <option key={e.value} value={e.value}>{e.label}</option>)}
          {hasUnmapped && <option value="unmapped">Não mapeado</option>}
        </select>
      </label>
      <label className="relative">
        <Stack size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
        <select data-testid="filter-subscription" value={subscriptionId}
                onChange={(e) => setSubscriptionId(e.target.value)} className={selectCls}>
          <option value="">Todas as subscriptions</option>
          {visibleSubs.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </label>
      <label className="relative">
        <CalendarBlank size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
        <select data-testid="filter-period" value={period}
                onChange={(e) => setPeriod(e.target.value)} className={selectCls}>
          {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
      </label>
    </div>
  );
}
