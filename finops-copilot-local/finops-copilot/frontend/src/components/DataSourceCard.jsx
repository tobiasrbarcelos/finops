import { CloudCheck, Flask, Warning, CircleNotch } from "@phosphor-icons/react";

export function DataSourceCard({ status }) {
  if (!status) return null;
  const running = status.status === "running";
  const error = status.status === "error";
  const azure = status.source === "azure";
  const Icon = running ? CircleNotch : error ? Warning : azure ? CloudCheck : Flask;
  const tone = error ? "#FF3B30" : azure ? "#10B981" : "#F59E0B";
  return (
    <div className="bento p-4 flex items-start gap-3" style={{ borderColor: `${tone}40` }} data-testid="data-source-card">
      <Icon size={20} weight="fill" style={{ color: tone }} className={running ? "animate-spin" : ""} />
      <div className="text-sm">
        <div className="font-medium">
          {running ? "Sincronizando com Azure…" : error ? "Falha no último sync Azure" : azure ? "Dados reais do Azure" : "Dados de demonstração (mock)"}
        </div>
        <div className="text-xs text-gray-500 mt-0.5">
          {status.message || "—"}
          {azure && !running && !error && ` · ${status.subscriptions_synced} subs · ${status.resources_synced} recursos · ${status.costs_synced} lançamentos · ${status.duration_seconds}s`}
        </div>
        {status.warnings?.length > 0 && (
          <ul className="text-xs text-[#F59E0B] mt-1 space-y-0.5">{status.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        )}
        <div className="text-[11px] text-gray-600 mt-1">Sync automático diário às 03:00 (BRT) via cron da plataforma.</div>
      </div>
    </div>
  );
}
