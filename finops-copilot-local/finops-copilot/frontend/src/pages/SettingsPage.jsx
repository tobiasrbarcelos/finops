import { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { api } from "../lib/api";
import { useFilters } from "../lib/filters";
import { toast } from "sonner";
import { CheckCircle, Lock, Info } from "@phosphor-icons/react";
import { AlertSettings } from "../components/AlertSettings";
import { DataSourceCard } from "../components/DataSourceCard";

export default function SettingsPage() {
  const [sp, setSp] = useState({ configured: false });
  const [form, setForm] = useState({ tenant_id: "", client_id: "", client_secret: "", display_name: "" });
  const [saving, setSaving] = useState(false);
  const [subs, setSubs] = useState([]);
  const { syncStatus, reloadSyncStatus } = useOutletContext();
  const { refreshSubscriptions } = useFilters();

  const load = () => {
    api.get("/service-principal").then((r) => setSp(r.data)).catch(() => {});
    api.get("/subscriptions").then((r) => setSubs(r.data)).catch(() => {});
  };
  useEffect(() => { load(); }, []);
  useEffect(() => { if (syncStatus?.status === "success") { load(); refreshSubscriptions(); } }, [syncStatus?.status]);

  const changeEnv = async (id, environment) => {
    try {
      await api.put(`/subscriptions/${id}/environment`, { environment });
      toast.success("Ambiente atualizado");
      load();
      refreshSubscriptions();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Falha ao atualizar ambiente");
    }
  };

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post("/service-principal", form);
      const r = await api.post("/sync/trigger");
      toast.success(`Service Principal salvo · ${r.data.message}`);
      setForm({ ...form, client_secret: "" });
      load();
      reloadSyncStatus();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Falha ao salvar");
    } finally { setSaving(false); }
  };

  return (
    <div className="p-8 space-y-6 max-w-5xl" data-testid="settings-page">
      <header>
        <p className="eyebrow mb-2">Configuração</p>
        <h1 className="font-display text-4xl font-bold tracking-tighter">Azure Service Principal</h1>
        <p className="text-sm text-gray-500 mt-2 max-w-2xl">
          O Service Principal com role <span className="font-mono-tab text-gray-300">Cost Management Reader</span> + <span className="font-mono-tab text-gray-300">Reader</span> permite o app coletar dados sem risco de modificação.
        </p>
      </header>

      <DataSourceCard status={syncStatus} />

      {sp.configured && (
        <div className="bento p-4 flex items-center gap-3 border-[#10B981]/30 bg-[#10B981]/[0.03]" data-testid="sp-status-configured">
          <CheckCircle size={20} weight="fill" className="text-[#10B981]" />
          <div>
            <div className="text-sm font-medium">Service Principal configurado</div>
            <div className="text-xs text-gray-500">Tenant: <span className="font-mono-tab">{sp.tenant_id}</span> · Client ID: <span className="font-mono-tab">{sp.client_id}</span></div>
          </div>
        </div>
      )}

      <form onSubmit={save} className="bento p-6 space-y-4" data-testid="sp-form">
        <h3 className="font-display text-lg font-semibold mb-2">
          {sp.configured ? "Atualizar credenciais" : "Cadastrar credenciais"}
        </h3>

        <label className="block">
          <span className="eyebrow block mb-2">Display name</span>
          <input
            data-testid="sp-display-name"
            value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            placeholder="Ex: Tenant Empresa"
            className="w-full bg-[#0A0A0B] border border-white/10 rounded-md px-4 py-2.5 text-sm focus:border-white/30 outline-none"
          />
        </label>

        <div className="grid md:grid-cols-2 gap-4">
          <label className="block">
            <span className="eyebrow block mb-2">Tenant ID</span>
            <input
              data-testid="sp-tenant-id"
              value={form.tenant_id}
              onChange={(e) => setForm({ ...form, tenant_id: e.target.value })}
              placeholder="00000000-0000-0000-0000-000000000000"
              className="w-full bg-[#0A0A0B] border border-white/10 rounded-md px-4 py-2.5 text-sm font-mono-tab focus:border-white/30 outline-none"
              required
            />
          </label>
          <label className="block">
            <span className="eyebrow block mb-2">Client ID</span>
            <input
              data-testid="sp-client-id"
              value={form.client_id}
              onChange={(e) => setForm({ ...form, client_id: e.target.value })}
              placeholder="00000000-0000-0000-0000-000000000000"
              className="w-full bg-[#0A0A0B] border border-white/10 rounded-md px-4 py-2.5 text-sm font-mono-tab focus:border-white/30 outline-none"
              required
            />
          </label>
        </div>

        <label className="block">
          <span className="eyebrow flex items-center gap-2 mb-2">
            <Lock size={11}/> Client Secret <span className="text-gray-600 normal-case tracking-normal">(criptografado com Fernet)</span>
          </span>
          <input
            data-testid="sp-client-secret"
            type="password"
            value={form.client_secret}
            onChange={(e) => setForm({ ...form, client_secret: e.target.value })}
            placeholder="••••••••••••••••"
            className="w-full bg-[#0A0A0B] border border-white/10 rounded-md px-4 py-2.5 text-sm focus:border-white/30 outline-none"
            required
          />
        </label>

        <div className="flex items-start gap-2 text-xs text-gray-500 border border-white/5 rounded-md p-3 bg-white/[0.02]">
          <Info size={14} className="text-[#3B82F6] mt-0.5 shrink-0" />
          <div>
            Escopo mínimo recomendado: <span className="font-mono-tab text-gray-300">Cost Management Reader</span> + <span className="font-mono-tab text-gray-300">Reader</span> + <span className="font-mono-tab text-gray-300">Monitoring Reader</span> no Management Group. Nunca conceda permissões de escrita para este app.
          </div>
        </div>

        <button
          data-testid="btn-save-sp"
          type="submit"
          disabled={saving}
          className="bg-[#FFD60A] hover:bg-[#ffde3d] disabled:opacity-50 text-black font-semibold py-2.5 px-5 rounded-md text-sm transition-colors"
        >
          {saving ? "Salvando…" : sp.configured ? "Atualizar credenciais & sincronizar" : "Salvar & sincronizar Azure"}
        </button>
      </form>

      <AlertSettings />

      {/* Subscriptions discovered */}
      <div className="bento" data-testid="subs-list">
        <div className="p-6 pb-2">
          <p className="eyebrow">Subscriptions descobertas</p>
          <h3 className="font-display text-lg font-semibold mt-1">{subs.length} conectadas</h3>
        </div>
        <table className="finops-table w-full">
          <thead><tr><th>ID</th><th>Nome</th><th>Ambiente</th><th>Estado</th></tr></thead>
          <tbody>
            {subs.map((s) => (
              <tr key={s.id}>
                <td className="font-mono-tab text-gray-400">{s.id}</td>
                <td className="text-gray-100 font-medium">{s.name}</td>
                <td>
                  <select
                    data-testid={`env-select-${s.id}`}
                    value={s.environment || "unmapped"}
                    onChange={(e) => changeEnv(s.id, e.target.value)}
                    className="bg-[#0A0A0B] border border-white/10 rounded-md px-2 py-1 text-xs text-gray-200 outline-none focus:border-white/30"
                  >
                    {!["dev", "hml", "prd"].includes(s.environment) && <option value="unmapped" disabled>Não mapeado</option>}
                    <option value="dev">Dev</option>
                    <option value="hml">HML</option>
                    <option value="prd">PRD</option>
                  </select>
                </td>
                <td>
                  <span className="text-[10px] px-2 py-1 rounded border font-semibold uppercase tracking-wider bg-[#10B981]/15 text-[#10B981] border-[#10B981]/30">
                    {s.state}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
