import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useState, useEffect } from "react";
import { useAuth } from "../lib/auth";
import { api } from "../lib/api";
import {
  ChartLineUp, Sparkle, FileText, Gear, SignOut, Lightning, ArrowsClockwise, ChatCircleDots,
} from "@phosphor-icons/react";
import { toast } from "sonner";
import ChatDrawer from "./ChatDrawer";
import { FiltersProvider } from "../lib/filters";
import { GlobalFilters } from "../components/GlobalFilters";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../components/ui/tooltip";

const NAV = [
  { to: "/", label: "Dashboard", icon: ChartLineUp, testid: "nav-dashboard" },
  { to: "/recommendations", label: "Recomendações", icon: Sparkle, testid: "nav-recommendations" },
  { to: "/reports", label: "Relatórios", icon: FileText, testid: "nav-reports" },
  { to: "/settings", label: "Configuração", icon: Gear, testid: "nav-settings" },
];

export default function AppShell() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [syncStatus, setSyncStatus] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);

  const loadStatus = () => api.get("/sync/status").then((r) => setSyncStatus(r.data)).catch(() => {});
  useEffect(() => { loadStatus(); }, []);
  useEffect(() => {
    if (syncStatus?.status !== "running") return;
    const t = setInterval(loadStatus, 4000);
    return () => clearInterval(t);
  }, [syncStatus?.status]);

  const triggerSync = async () => {
    setSyncing(true);
    try {
      const r = await api.post("/sync/trigger");
      toast.success(r.data.message);
      await loadStatus();
    } catch { toast.error("Falha ao sincronizar"); }
    finally { setSyncing(false); }
  };

  const running = syncStatus?.status === "running";

  const lastSync = syncStatus?.last_sync
    ? new Date(syncStatus.last_sync).toLocaleString("pt-BR", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" })
    : "Nunca";

  return (
    <div className="App min-h-screen grain flex">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 border-r border-white/5 flex flex-col" style={{ background: "#0d0d0e" }}>
        <div className="px-5 py-6 border-b border-white/5">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-md bg-[#0052CC] flex items-center justify-center">
              <Lightning size={18} weight="fill" color="#fff" />
            </div>
            <div>
              <div className="font-display font-bold text-sm leading-tight">FinOps</div>
              <div className="eyebrow" style={{ fontSize: "8px" }}>Copilot Azure</div>
            </div>
          </div>
        </div>

        <nav className="flex-1 p-3 space-y-0.5">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === "/"}
              data-testid={n.testid}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors ${
                  isActive
                    ? "bg-white/[0.06] text-white border border-white/10"
                    : "text-gray-400 hover:text-white hover:bg-white/[0.03] border border-transparent"
                }`
              }
            >
              <n.icon size={17} weight="regular" />
              <span>{n.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="p-3 border-t border-white/5 space-y-3">
          <div className="text-[10px] uppercase tracking-widest text-gray-500 px-1 flex items-center justify-between">
          </div>
          <div className="flex items-center justify-between px-1">
            <span className="text-xs text-gray-300 tabular">{lastSync}</span>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    data-testid="btn-trigger-sync"
                    onClick={triggerSync}
                    disabled={syncing || running}
                    className="p-1.5 rounded hover:bg-white/10 text-gray-400 hover:text-white disabled:opacity-50"
                  >
                    <ArrowsClockwise size={14} className={syncing || running ? "animate-spin" : ""} />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="right">Trigger sync manual</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>

          <div className="flex items-center gap-2 px-1 pt-2 border-t border-white/5">
            <div className="w-7 h-7 rounded-full bg-white/10 flex items-center justify-center text-xs font-semibold">
              {(user?.name || "A")[0]}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium truncate">{user?.name}</div>
              <div className="text-[10px] text-gray-500 truncate">{user?.email}</div>
            </div>
            <button
              data-testid="btn-logout"
              onClick={() => { logout(); nav("/login"); }}
              className="p-1.5 rounded hover:bg-white/10 text-gray-400 hover:text-white"
            >
              <SignOut size={14} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 min-w-0 relative">
        <FiltersProvider>
          <div className="sticky top-0 z-30 border-b border-white/5 backdrop-blur-md bg-[#0A0A0B]/80 px-8 py-3 flex items-center justify-between gap-4">
            <GlobalFilters />
            <span className="text-[10px] text-gray-600 hidden lg:block">Filtros aplicam-se a dashboard, recomendações e relatórios</span>
          </div>
          <Outlet context={{ syncStatus, reloadSyncStatus: loadStatus }} />
        </FiltersProvider>

        {/* Floating chat trigger */}
        <button
          data-testid="btn-open-chat"
          onClick={() => setChatOpen(true)}
          className="fixed bottom-6 right-6 z-40 group"
          aria-label="Abrir Copilot"
        >
          <div className="ai-glow rounded-full bg-[#141415] hover:bg-[#1c1c1e] transition-colors px-4 py-3 flex items-center gap-2.5 border border-white/10">
            <div className="w-6 h-6 rounded-full bg-[#0052CC] flex items-center justify-center">
              <Sparkle size={13} weight="fill" color="#fff" />
            </div>
            <span className="text-sm font-medium">Perguntar ao Copilot</span>
            <ChatCircleDots size={16} className="text-gray-400" />
          </div>
        </button>

        <ChatDrawer open={chatOpen} onOpenChange={setChatOpen} />
      </main>
    </div>
  );
}
