import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { api } from "./api";

export const ENVS = [
  { value: "dev", label: "Dev" },
  { value: "hml", label: "HML" },
  { value: "prd", label: "PRD" },
];

export const PERIODS = [
  { value: "current", label: "Mês atual" },
  { value: "previous", label: "Mês anterior" },
  { value: "3m", label: "Últimos 3 meses" },
  { value: "6m", label: "Últimos 6 meses" },
  { value: "12m", label: "Últimos 12 meses" },
];

const FiltersCtx = createContext(null);

export function FiltersProvider({ children }) {
  const [period, setPeriod] = useState(() => localStorage.getItem("finops_period") || "current");
  const [subscriptionId, setSubscriptionId] = useState(() => localStorage.getItem("finops_sub") || "");
  const [environment, setEnvironment] = useState(() => localStorage.getItem("finops_env") || "");
  const [subscriptions, setSubscriptions] = useState([]);

  useEffect(() => { api.get("/subscriptions").then((r) => setSubscriptions(r.data)).catch(() => {}); }, []);
  useEffect(() => { localStorage.setItem("finops_period", period); }, [period]);
  useEffect(() => { localStorage.setItem("finops_sub", subscriptionId); }, [subscriptionId]);
  useEffect(() => { localStorage.setItem("finops_env", environment); }, [environment]);

  const query = useMemo(() => {
    const p = new URLSearchParams({ period });
    if (subscriptionId) p.set("subscription_id", subscriptionId);
    if (environment) p.set("environment", environment);
    return p.toString();
  }, [period, subscriptionId, environment]);

  const value = { period, setPeriod, subscriptionId, setSubscriptionId, environment, setEnvironment, subscriptions, query,
    refreshSubscriptions: () => api.get("/subscriptions").then((r) => setSubscriptions(r.data)).catch(() => {}) };
  return <FiltersCtx.Provider value={value}>{children}</FiltersCtx.Provider>;
}

export const useFilters = () => useContext(FiltersCtx);
