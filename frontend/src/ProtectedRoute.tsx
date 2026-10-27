import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "./AuthContext";

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div style={{padding:40,fontFamily:"Comfortaa, sans-serif",color:"#777"}}>Загрузка…</div>;
  return user ? <>{children}</> : <Navigate to="/login" replace />;
}
