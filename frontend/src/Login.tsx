import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "./AuthContext";
import "./Auth.css";

export default function Login() {
  const { user, loading, login } = useAuth();
  const navigate = useNavigate();
  const [email,setEmail]=useState(""); const [password,setPassword]=useState(""); const [error,setError]=useState(""); const [busy,setBusy]=useState(false);
  useEffect(()=>{ if(user) navigate("/products",{replace:true}); },[user,navigate]);
  if(loading) return <div className="auth-page"><div className="auth-loading">Проверка сессии…</div></div>;
  if(user) return <Navigate to="/products" replace />;
  const submit=async(e:FormEvent)=>{e.preventDefault();setError("");setBusy(true);try{await login(email,password);navigate("/products",{replace:true});}catch(err){setError(err instanceof Error?err.message:"Ошибка входа");}finally{setBusy(false)}};
  return <div className="auth-page"><div className="auth-card"><div className="auth-brand">MARKETPLACE ANALYTICS</div><h1>Вход</h1><p className="auth-subtitle">Войдите в рабочее пространство, чтобы продолжить.</p><form className="auth-form" onSubmit={submit}><label>Email<input type="email" autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)} required /></label><label>Пароль<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required /></label><div className="auth-forgot"><Link to="/forgot-password">Забыли пароль?</Link></div>{error&&<div className="auth-error">{error}</div>}<button className="auth-button" disabled={busy}>{busy?"Вход…":"Войти"}</button></form><div className="auth-switch">Нет аккаунта? <Link to="/register">Зарегистрироваться</Link></div></div></div>;
}
