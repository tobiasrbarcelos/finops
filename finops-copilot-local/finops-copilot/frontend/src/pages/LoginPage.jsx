import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { toast } from "sonner";
import { Lightning } from "@phosphor-icons/react";

export default function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(email, password);
      toast.success("Bem-vindo ao FinOps Copilot");
      nav("/");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Falha no login");
    } finally { setLoading(false); }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-[1.1fr_1fr]">
      {/* Left panel */}
      <div className="relative hidden lg:flex flex-col justify-between p-12 border-r border-white/5"
           style={{ background: "linear-gradient(155deg, #0A0A0B 0%, #0d1220 100%)" }}>
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-md bg-[#0052CC] flex items-center justify-center">
            <Lightning size={20} weight="fill" color="#fff" />
          </div>
          <span className="font-display text-lg font-bold tracking-tight">FinOps Copilot</span>
        </div>

        <div className="max-w-md">
          <p className="eyebrow mb-6">Azure Cost Intelligence</p>
          <h1 className="font-display text-5xl font-black leading-[1.05] tracking-tighter mb-6">
            Todos os custos.<br/>
            <span className="text-[#FFD60A]">Uma decisão.</span>
          </h1>
          <p className="text-sm text-gray-400 leading-relaxed max-w-sm">
            Consolide subscriptions Azure, descubra desperdícios e converse com seus dados
            em linguagem natural. Sem planilhas, sem fricção.
          </p>
        </div>

        <div className="grid grid-cols-3 gap-6 max-w-md">
          {[
            { l: "Subscriptions", v: "4" },
            { l: "Recursos", v: "145" },
            { l: "Economia identificada", v: "R$ 22k+" },
          ].map((s) => (
            <div key={s.l}>
              <div className="font-display text-2xl font-bold tabular">{s.v}</div>
              <div className="eyebrow mt-1">{s.l}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Right form */}
      <div className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm space-y-6" data-testid="login-form">
          <div>
            <p className="eyebrow mb-2">Login</p>
            <h2 className="font-display text-3xl font-bold tracking-tight">Acesse seu painel</h2>
            <p className="text-sm text-gray-500 mt-2">Uso interno · single-tenant</p>
          </div>

          <div className="space-y-4">
            <label className="block">
              <span className="eyebrow block mb-2">Email</span>
              <input
                data-testid="login-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-[#141415] border border-white/10 rounded-md px-4 py-3 text-sm focus:border-white/30 outline-none"
                required
              />
            </label>
            <label className="block">
              <span className="eyebrow block mb-2">Senha</span>
              <input
                data-testid="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-[#141415] border border-white/10 rounded-md px-4 py-3 text-sm focus:border-white/30 outline-none"
                required
              />
            </label>
          </div>

          <button
            data-testid="login-submit"
            type="submit"
            disabled={loading}
            className="w-full bg-[#FFD60A] hover:bg-[#ffde3d] disabled:opacity-50 text-black font-semibold py-3 rounded-md text-sm transition-colors"
          >
            {loading ? "Entrando…" : "Entrar →"}
          </button>
        </form>
      </div>
    </div>
  );
}
