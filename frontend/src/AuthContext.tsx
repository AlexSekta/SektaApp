import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export interface AuthUser {
  id: number;
  name: string;
  email: string;
  role: string;
  organization_id: number;
  organization_name: string | null;
}

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (firstName: string, lastName: string, email: string, password: string, organizationName: string, invitationToken?: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const API = `${window.location.protocol}//${window.location.hostname}:8000`;
const AuthContext = createContext<AuthContextValue | null>(null);

async function readError(response: Response, fallback: string) {
  const data = await response.json().catch(() => ({}));
  return typeof data?.detail === "string" ? data.detail : typeof data?.message === "string" ? data.message : fallback;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const loadMe = async () => {
    try {
      const response = await fetch(`${API}/auth/me`, { credentials: "include" });
      if (!response.ok) setUser(null);
      else setUser((await response.json()).user ?? null);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadMe();
    const onExpired = () => setUser(null);
    window.addEventListener("marketplace-auth-expired", onExpired);
    return () => window.removeEventListener("marketplace-auth-expired", onExpired);
  }, []);

  const refreshUser = async () => {
    const response = await fetch(`${API}/auth/me`, { credentials: "include" });
    if (!response.ok) {
      setUser(null);
      throw new Error("Не удалось обновить данные пользователя");
    }
    setUser((await response.json()).user ?? null);
  };

  const login = async (email: string, password: string) => {
    const response = await fetch(`${API}/auth/login`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!response.ok) throw new Error(await readError(response, "Не удалось войти"));
    setUser((await response.json()).user);
  };

  const register = async (firstName: string, lastName: string, email: string, password: string, organizationName: string, invitationToken?: string) => {
    const response = await fetch(`${API}/auth/register`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ first_name: firstName, last_name: lastName, email, password, organization_name: organizationName, invitation_token: invitationToken }),
    });
    if (!response.ok) throw new Error(await readError(response, "Не удалось зарегистрироваться"));
    setUser((await response.json()).user);
  };

  const logout = async () => {
    try {
      await fetch(`${API}/auth/logout`, { method: "POST", credentials: "include" });
    } finally {
      setUser(null);
    }
  };

  return <AuthContext.Provider value={{ user, loading, login, register, logout, refreshUser }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
