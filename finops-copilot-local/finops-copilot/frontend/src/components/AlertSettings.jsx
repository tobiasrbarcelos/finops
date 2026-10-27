import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { toast } from "sonner";
import { BellRinging, PaperPlaneTilt } from "@phosphor-icons/react";

const PROVIDERS = [
  { value: "slack", label: "Slack" },
  { value: "teams", label: "Microsoft Teams" },
  { value: "google_chat", label: "Google Chat" },
];
const inputCls = "w-full bg-[#0A0A0B] border border-white/10 rounded-md px-4 py-2.5 text-sm focus:border-white/30 outline-none";

export function AlertSettings() {
  const [cfg, setCfg] = useState({ provider: "slack", webhook_url: "", threshold: 1000, enabled: false });
  const [last, setLast] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.get("/alerts/settings").then((r) => {
    const { last_alert, ...c } = r.data; setCfg(c); setLast(last_alert);
  }).catch(() => {});
  useEffect(() => { load(); }, []);

  const save = async (e) => {
    e.preventDefault(); setBusy(true);
    try { await api.put("/alerts/settings", { ...cfg, threshold: Number(cfg.threshold) }); toast.success("Alertas salvos"); load(); }
    catch (err) { toast.error(err.response?.data?.detail || "Falha ao salvar"); }
    finally { setBusy(false); }
  };

  const test = async () => {
    setBusy(true);
    try { await api.put("/alerts/settings", { ...cfg, threshold: Number(cfg.threshold) }); await api.post("/alerts/test"); toast.success("Mensagem de teste enviada"); load(); }
    catch (err) { toast.error(`Falha no envio: ${err.response?.data?.detail || err.message}`); }
    finally { setBusy(false); }
  };

  return (
    <form onSubmit={save} className="bento p-6 space-y-4" data-testid="alert-settings">
      <div className="flex items-center justify-between">
        <div>
          <p className="eyebrow">Alertas semanais</p>
          <h3 className="font-display text-lg font-semibold mt-1 flex items-center gap-2"><BellRinging size={18} /> Webhook de economia</h3>
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
          <input data-testid="alert-enabled" type="checkbox" checked={cfg.enabled}
                 onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} className="accent-[#FFD60A]" />
          Ativo
        </label>
      </div>
      <p className="text-xs text-gray-500">Toda segunda-feira às 09:00 (BRT), se a economia potencial ultrapassar o limite, um resumo é enviado ao canal.</p>

      <div className="grid md:grid-cols-3 gap-4">
        <label className="block">
          <span className="eyebrow block mb-2">Plataforma</span>
          <select data-testid="alert-provider" value={cfg.provider}
                  onChange={(e) => setCfg({ ...cfg, provider: e.target.value })} className={inputCls}>
            {PROVIDERS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </label>
        <label className="block md:col-span-2">
          <span className="eyebrow block mb-2">Limite de economia (R$/mês)</span>
          <input data-testid="alert-threshold" type="number" min="0" step="100" value={cfg.threshold}
                 onChange={(e) => setCfg({ ...cfg, threshold: e.target.value })} className={`${inputCls} font-mono-tab`} required />
        </label>
      </div>
      <label className="block">
        <span className="eyebrow block mb-2">Incoming Webhook URL</span>
        <input data-testid="alert-webhook-url" type="url" value={cfg.webhook_url}
               onChange={(e) => setCfg({ ...cfg, webhook_url: e.target.value })}
               placeholder="https://hooks.slack.com/… | https://…webhook.office.com/… | https://chat.googleapis.com/…"
               className={`${inputCls} font-mono-tab`} required />
      </label>

      <div className="flex items-center gap-3 flex-wrap">
        <button data-testid="btn-save-alerts" type="submit" disabled={busy}
                className="bg-[#FFD60A] hover:bg-[#ffde3d] disabled:opacity-50 text-black font-semibold py-2.5 px-5 rounded-md text-sm transition-colors">
          {busy ? "Salvando…" : "Salvar alertas"}
        </button>
        <button data-testid="btn-test-alert" type="button" onClick={test} disabled={busy || !cfg.webhook_url}
                className="inline-flex items-center gap-2 border border-white/10 hover:bg-white/5 disabled:opacity-50 py-2.5 px-4 rounded-md text-sm transition-colors">
          <PaperPlaneTilt size={14} /> Enviar teste agora
        </button>
        {last && (
          <span className="text-xs text-gray-500 ml-auto" data-testid="alert-last-status">
            Último: {new Date(last.at).toLocaleString("pt-BR")} · {last.sent ? "enviado" : `não enviado (${last.reason})`}
          </span>
        )}
      </div>
    </form>
  );
}
