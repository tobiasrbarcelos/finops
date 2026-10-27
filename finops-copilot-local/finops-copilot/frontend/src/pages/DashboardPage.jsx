import { useEffect, useState } from "react";
import { api, fmtBRL, fmtPct } from "../lib/api";
import { useFilters } from "../lib/filters";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip as RTooltip,
  BarChart, Bar, PieChart, Pie, Cell, Legend,
} from "recharts";
import { TrendUp, TrendDown, Calendar, Wallet, ChartBar } from "@phosphor-icons/react";

const CHART_COLORS = ["#3B82F6", "#6366F1", "#F59E0B", "#10B981", "#F43F5E", "#8B5CF6", "#06B6D4"];

function KpiCard({ label, value, hint, delta, testid }) {
  const positive = (delta ?? 0) > 0;
  return (
    <div className="bento p-6" data-testid={testid}>
      <div className="eyebrow">{label}</div>
      <div className="font-display text-3xl md:text-4xl font-bold tracking-tighter mt-3 tabular text-gray-50">
        {value}
      </div>
      <div className="mt-2 flex items-center gap-2 text-xs text-gray-500">
        {delta !== undefined && (
          <span className={`inline-flex items-center gap-1 ${positive ? "text-[#FF3B30]" : "text-[#10B981]"} font-medium`}>
            {positive ? <TrendUp size={12} weight="bold"/> : <TrendDown size={12} weight="bold"/>}
            {fmtPct(delta)}
          </span>
        )}
        <span>{hint}</span>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const [summary, setSummary] = useState(null);
  const [trend, setTrend] = useState([]);
  const [byService, setByService] = useState([]);
  const [bySub, setBySub] = useState([]);
  const [byRegion, setByRegion] = useState([]);
  const [top, setTop] = useState([]);
  const [loading, setLoading] = useState(true);
  const { query, subscriptionId, environment, subscriptions } = useFilters();
  const subQ = (subscriptionId ? `&subscription_id=${subscriptionId}` : "") + (environment ? `&environment=${environment}` : "");
  const subName = subscriptions.find((s) => s.id === subscriptionId)?.name;

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.get(`/costs/summary?${query}`),
      api.get(`/costs/trend?months=12${subQ}`),
      api.get(`/costs/breakdown?dimension=service&${query}`),
      api.get(`/costs/breakdown?dimension=subscription_name&${query}`),
      api.get(`/costs/breakdown?dimension=region&${query}`),
      api.get(`/costs/top-resources?limit=10&${query}`),
    ]).then(([s, t, sv, sb, rg, tp]) => {
      setSummary(s.data); setTrend(t.data); setByService(sv.data);
      setBySub(sb.data); setByRegion(rg.data); setTop(tp.data);
    }).finally(() => setLoading(false));
  }, [query, subQ]);

  if (loading && !summary) return <div className="p-10 text-gray-500">Carregando dashboard…</div>;
  const periodLabel = summary.period_label;

  return (
    <div className={`p-8 space-y-6 transition-opacity ${loading ? "opacity-60" : ""}`} data-testid="dashboard-page">
      {/* Header */}
      <header className="flex items-end justify-between mb-2">
        <div>
          <p className="eyebrow mb-2">Visão Consolidada · {subName || "Multi-Subscription"}</p>
          <h1 className="font-display text-4xl font-bold tracking-tighter">Dashboard de Custos</h1>
        </div>
        <div className="text-xs text-gray-500 flex items-center gap-2" data-testid="dashboard-period-label">
          <Calendar size={14} /> {periodLabel} · {new Date().toLocaleDateString("pt-BR", { day:"2-digit", month:"long", year:"numeric" })}
        </div>
      </header>

      {/* KPIs */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <KpiCard
          testid="kpi-current-month"
          label={periodLabel}
          value={fmtBRL(summary.current_month)}
          hint={summary.months.length > 1 ? `${summary.months.length} meses` : "MTD"}
          delta={summary.variation_pct}
        />
        <KpiCard testid="kpi-previous-month" label="Período Anterior" value={fmtBRL(summary.previous_month)} hint="comparativo" />
        <KpiCard testid="kpi-ytd" label="Year-to-Date" value={fmtBRL(summary.ytd)} hint={new Date().getFullYear()} />
        <KpiCard testid="kpi-projection" label="Projeção Anual" value={fmtBRL(summary.projection_year)} hint="linear c/ YTD" />
      </div>

      {/* Trend line - large */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="bento p-6 lg:col-span-2" data-testid="chart-trend">
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="eyebrow">Tendência</p>
              <h3 className="font-display text-lg font-semibold mt-1">Últimos 12 meses</h3>
            </div>
            <ChartBar size={18} className="text-gray-500" />
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={trend} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis dataKey="month" tick={{ fill: "#6B7280", fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: "#6B7280", fontSize: 11 }} axisLine={false} tickLine={false}
                     tickFormatter={(v) => `${(v/1000).toFixed(0)}k`} />
              <RTooltip
                contentStyle={{ background: "#1C1C1E", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4, fontSize: 12 }}
                formatter={(v) => fmtBRL(v)}
              />
              <Line type="monotone" dataKey="amount" stroke="#FFD60A" strokeWidth={2}
                    dot={{ fill: "#FFD60A", r: 3 }} activeDot={{ r: 5 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="bento p-6" data-testid="chart-by-service">
          <p className="eyebrow">Por Serviço</p>
          <h3 className="font-display text-lg font-semibold mt-1 mb-4">Composição · {periodLabel.toLowerCase()}</h3>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={byService.slice(0, 6)} dataKey="amount" nameKey="label"
                   innerRadius={50} outerRadius={80} paddingAngle={2}>
                {byService.slice(0,6).map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
              </Pie>
              <RTooltip
                contentStyle={{ background: "#1C1C1E", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4, fontSize: 12 }}
                formatter={(v) => fmtBRL(v)}
              />
            </PieChart>
          </ResponsiveContainer>
          <div className="mt-3 space-y-1.5">
            {byService.slice(0, 5).map((s, i) => (
              <div key={s.label} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: CHART_COLORS[i % CHART_COLORS.length] }} />
                  <span className="truncate text-gray-300">{s.label}</span>
                </div>
                <span className="tabular text-gray-400">{fmtBRL(s.amount)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Subscription & Region bars */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bento p-6" data-testid="chart-by-subscription">
          <p className="eyebrow">Por Subscription</p>
          <h3 className="font-display text-lg font-semibold mt-1 mb-4">Distribuição consolidada</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={bySub} layout="vertical" margin={{ top: 4, right: 8, left: 40, bottom: 0 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" horizontal={false} />
              <XAxis type="number" tick={{ fill: "#6B7280", fontSize: 11 }} axisLine={false} tickLine={false}
                     tickFormatter={(v) => `${(v/1000).toFixed(0)}k`} />
              <YAxis dataKey="label" type="category" tick={{ fill: "#9CA3AF", fontSize: 11 }} axisLine={false} tickLine={false} width={90} />
              <RTooltip contentStyle={{ background: "#1C1C1E", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4, fontSize: 12 }} formatter={(v)=>fmtBRL(v)} />
              <Bar dataKey="amount" fill="#3B82F6" radius={[0, 3, 3, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="bento p-6" data-testid="chart-by-region">
          <p className="eyebrow">Por Região</p>
          <h3 className="font-display text-lg font-semibold mt-1 mb-4">Alocação geográfica</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={byRegion} margin={{ top: 4, right: 8, left: -8, bottom: 0 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: "#9CA3AF", fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: "#6B7280", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v)=>`${(v/1000).toFixed(0)}k`} />
              <RTooltip contentStyle={{ background: "#1C1C1E", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4, fontSize: 12 }} formatter={(v)=>fmtBRL(v)} />
              <Bar dataKey="amount" fill="#F59E0B" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Top resources */}
      <div className="bento" data-testid="table-top-resources">
        <div className="p-6 pb-2 flex items-center justify-between">
          <div>
            <p className="eyebrow">Top 10 Recursos</p>
            <h3 className="font-display text-lg font-semibold mt-1">Mais caros · {periodLabel.toLowerCase()}</h3>
          </div>
        </div>
        <table className="finops-table w-full">
          <thead>
            <tr>
              <th>#</th><th>Recurso</th><th>Serviço</th><th>Subscription</th><th>Resource Group</th>
              <th className="text-right">Custo mensal</th>
            </tr>
          </thead>
          <tbody>
            {top.map((r, i) => (
              <tr key={r.resource_id}>
                <td className="text-gray-500 tabular w-8">{String(i+1).padStart(2, "0")}</td>
                <td className="text-gray-100 font-medium">{r.resource_name}</td>
                <td className="text-gray-400">{r.service}</td>
                <td className="text-gray-400">{r.subscription_name}</td>
                <td className="text-gray-400">{r.resource_group}</td>
                <td className="text-right font-mono-tab text-gray-100">{fmtBRL(r.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
