import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "./AuthContext";
import "./Auth.css";
const API = `${window.location.protocol}//${window.location.hostname}:8000`;
type InviteInfo = { organization_name:string; email:string; role:string };
export default function Register() {
 const {user,loading,register}=useAuth(); const navigate=useNavigate();
 const [params]=useSearchParams(); const token=params.get("invite")||"";
 const [invite,setInvite]=useState<InviteInfo|null>(null),[inviteError,setInviteError]=useState("");
 const [checking,setChecking]=useState(Boolean(token));
 const [firstName,setFirstName]=useState(""),[lastName,setLastName]=useState(""),[email,setEmail]=useState(""),[password,setPassword]=useState(""),[organizationName,setOrganizationName]=useState("");
 const [error,setError]=useState(""),[busy,setBusy]=useState(false);
 useEffect(()=>{let active=true; if(!token){setInvite(null);setChecking(false);return;}
   setChecking(true);
   fetch(`${API}/auth/invitation/${encodeURIComponent(token)}`).then(async r=>{const d=await r.json();if(!r.ok)throw Error(d.detail||"Приглашение недействительно");if(active){setInvite(d);setEmail(d.email);setInviteError("");}}).catch(e=>{if(active)setInviteError(e.message)}).finally(()=>{if(active)setChecking(false)});
   return ()=>{active=false};
 },[token]);
 if(loading)return <div className="auth-page"><div className="auth-loading">Проверка сессии…</div></div>;
 if(user)return <Navigate to="/products" replace/>;
 const submit=async(e:FormEvent)=>{e.preventDefault();setError("");setBusy(true);try{await register(firstName,lastName,email,password,organizationName,token||undefined);navigate("/products",{replace:true})}catch(err){setError(err instanceof Error?err.message:"Ошибка регистрации")}finally{setBusy(false)}};
 return <div className="auth-page"><div className="auth-card"><div className="auth-brand">MARKETPLACE ANALYTICS</div>
 <h1>{token?"Присоединиться к команде":"Создать организацию"}</h1>
 {token ? <p className="auth-subtitle">{checking?"Проверяем приглашение…":invite?<>Вас пригласили в рабочее пространство <strong>{invite.organization_name}</strong>. После регистрации вы присоединитесь как сотрудник — новая организация не создаётся.</>:"Приглашение недоступно."}</p>
 :<p className="auth-subtitle">Вы создаёте новое рабочее пространство и становитесь его владельцем. Для присоединения к существующей команде нужна ссылка от владельца.</p>}
 {inviteError&&<div className="auth-error">{inviteError} <Link to="/register">Создать свою организацию</Link></div>}
 {(!token||invite)&&<form className="auth-form" onSubmit={submit}>
 <div className="auth-name-row"><label>Имя<input autoComplete="given-name" value={firstName} onChange={e=>setFirstName(e.target.value)} required maxLength={60}/></label><label>Фамилия<input autoComplete="family-name" value={lastName} onChange={e=>setLastName(e.target.value)} required maxLength={60}/></label></div>
 {!token&&<label>Название компании / пространства<input value={organizationName} onChange={e=>setOrganizationName(e.target.value)} required maxLength={200} placeholder="Например, Hair Sekta"/></label>}
 <label>Email<input type="email" autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)} readOnly={Boolean(token)} required/></label>
 <label>Пароль<input type="password" autoComplete="new-password" minLength={8} value={password} onChange={e=>setPassword(e.target.value)} required/></label>
 {error&&<div className="auth-error">{error}</div>}<button className="auth-button" disabled={busy||checking}>{busy?"Регистрация…":token?"Присоединиться к команде":"Создать организацию"}</button></form>}
 <div className="auth-switch">Уже есть аккаунт? <Link to="/login">Войти</Link></div>
 </div></div>;
}
