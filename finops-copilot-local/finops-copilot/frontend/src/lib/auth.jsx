import { createContext, useContext, useEffect, useState } from "react";
import { api } from "./api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const s = localStorage.getItem("finops_user");
    return s ? JSON.parse(s) : null;
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = localStorage.getItem("finops_token");
    if (!t) { setLoading(false); return; }
    api.get("/auth/me").then((r) => {
      setUser(r.data);
      localStorage.setItem("finops_user", JSON.stringify(r.data));
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    localStorage.setItem("finops_token", data.access_token);
    localStorage.setItem("finops_user", JSON.stringify(data.user));
    setUser(data.user);
    return data.user;
  };

  const logout = () => {
    localStorage.removeItem("finops_token");
    localStorage.removeItem("finops_user");
    setUser(null);
  };

  return <AuthCtx.Provider value={{ user, loading, login, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
