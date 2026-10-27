import { useEffect, useState } from "react";
import { api, API, fmtBRL } from "../lib/api";
import { DownloadSimple, FileCsv, FilePdf, ChartLineUp } from "@phosphor-icons/react";
import { toast } from "sonner";

export default function ReportsPage() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/reports/executive").then((r) => setReport(r.data)).finally(() => setLoading(false));
  }, []);

  const downloadCsv = async (kind) => {
    try {
      const token = localStorage.getItem("finops_token");
      const res = await fetch(`${API}/reports/${kind}.csv`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `${kind}.csv`; a.click();
      URL.revokeObjectURL(url);
      toast.success(`${kind}.csv baixado`);
    } catch { toast.error("Falha no download"); }
  };

  const downloadPdf = () => {
    // Print-to-PDF via window.print of the executive card
    toast.success("Abrindo caixa de impressão (salvar como PDF)");
    setTimeout(() => window.print(), 300);
  };

  if (loading || !report) return <div className="p-10 text-gray-500">Gerando relatório…</div>;

  return (
    <div className="p-8 space-y-6" data-testid="reports-page">
      <header>
        <p className="eyebrow mb-2">Relatórios</p>
        <h1 className="font-display text-4xl font-bold tracking-tighter">Export & Relatório Executivo</h1>
      </header>

      {/* Downloads */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <button
          data-testid="btn-download-costs-csv"
          onClick={() => downloadCsv("costs")}
          className="bento p-5 text-left flex items-start gap-3 hover:-translate-y-[1px]"
        >
          <div className="w-9 h-9 rounded-md bg-[#3B82F6]/15 border border-[#3B82F6]/30 flex items-center justify-center">
            <FileCsv size={17} className="text-[#3B82F6]"/>
          </div>
          <div>
            <div className="font-display font-semibold">Custos (CSV)</div>
            <div className="text-xs text-gray-500 mt-1">Todas as linhas de custo por recurso × mês</div>
          </div>
          <DownloadSimple size={16} className="ml-auto text-gray-500"/>
        </button>

        <button
          data-testid="btn-download-recs-csv"
          onClick={() => downloadCsv("recommendations")}
          className="bento p-5 text-left flex items-start gap-3 hover:-translate-y-[1px]"
        >
          <div className="w-9 h-9 rounded-md bg-[#10B981]/15 border border-[#10B981]/30 flex items-center justify-center">
            <FileCsv size={17} className="text-[#10B981]"/>
          </div>
          <div>
            <div className="font-display font-semibold">Recomendações (CSV)</div>
            <div className="text-xs text-gray-500 mt-1">Lista completa com economia estimada</div>
          </div>
          <DownloadSimple size={16} className="ml-auto text-gray-500"/>
        </button>

        <button
          data-testid="btn-download-pdf"
          onClick={downloadPdf}
          className="bento p-5 text-left flex items-start gap-3 hover:-translate-y-[1px]"
        >
          <div className="w-9 h-9 rounded-md bg-[#FF3B30]/15 border border-[#FF3B30]/30 flex items-center justify-center">
            <FilePdf size={17} className="text-[#FF3B30]"/>
          </div>
          <div>
            <div className="font-display font-semibold">Executivo (PDF)</div>
            <div className="text-xs text-gray-500 mt-1">Imprimir/salvar como PDF</div>
          </div>
          <DownloadSimple size={16} className="ml-auto text-gray-500"/>
        </button>
      </div>

      {/* Executive summary card */}
      <div className="bento p-8" data-testid="executive-report">
        <div className="flex items-center justify-between mb-6">
          <div>
            <p className="eyebrow">Relatório Executivo</p>
            <h2 className="font-display text-2xl font-bold mt-1 tracking-tight">Resumo Mensal FinOps Azure</h2>
          </div>
          <div className="text-xs text-gray-500 tabular">
            Gerado em {new Date(report.generated_at).toLocaleString("pt-BR")}
          </div>
        </div>

        {/* Highlights */}
        <ul className="space-y-2 mb-8">
          {report.highlights.map((h, i) => (
            <li key={i} className="flex gap-3 items-start text-sm text-gray-200">
              <ChartLineUp size={14} className="text-[#FFD60A] mt-1 shrink-0" />
              <span>{h}</span>
            </li>
          ))}
        </ul>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <div className="bento-elev p-4">
            <div className="eyebrow">Mês atual</div>
            <div className="font-display text-xl font-bold tabular mt-2">{fmtBRL(report.summary.current_month)}</div>
          </div>
          <div className="bento-elev p-4">
            <div className="eyebrow">Projeção anual</div>
            <div className="font-display text-xl font-bold tabular mt-2">{fmtBRL(report.summary.projection_year)}</div>
          </div>
          <div className="bento-elev p-4">
            <div className="eyebrow">Economia potencial</div>
            <div className="font-display text-xl font-bold text-[#10B981] tabular mt-2">{fmtBRL(report.recommendations.total_savings)}</div>
          </div>
          <div className="bento-elev p-4">
            <div className="eyebrow"># Recomendações</div>
            <div className="font-display text-xl font-bold tabular mt-2">{report.recommendations.total_count}</div>
          </div>
        </div>

        <div>
          <p className="eyebrow mb-3">Breakdown por categoria de economia</p>
          <div className="space-y-2">
            {report.recommendations.by_category.map((c) => {
              const pct = report.recommendations.total_savings > 0
                ? (c.total_savings / report.recommendations.total_savings) * 100 : 0;
              return (
                <div key={c.category} className="flex items-center gap-3">
                  <div className="w-40 text-xs text-gray-300 shrink-0">{c.category_label}</div>
                  <div className="flex-1 h-2 rounded bg-white/5 overflow-hidden">
                    <div className="h-full bg-[#10B981]" style={{ width: `${pct}%` }} />
                  </div>
                  <div className="w-28 text-right text-xs tabular text-gray-300">{fmtBRL(c.total_savings)}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
