import { useEffect, useState } from "react";
import { useAuth } from "./AuthContext";
import "./TeamSettings.css";
const API = `${window.location.protocol}//${window.location.hostname}:8000`;
type Member = {id:number;name:string;email:string;role:string;is_active:boolean;online:boolean;last_seen_at:string|null};
type Invite = {id:number;email:string;status:string;expires_at:string};
type Event = {id:number;user_id:number|null;user_name:string;action:string;method:string|null;path:string|null;status_code:number|null;created_at:string};
const statuses:Record<string,string>={pending:"Ожидает регистрации",accepted:"Принято",revoked:"Отозвано",expired:"Истёк срок"};
function date(d:string|null){return d?new Date(d+"Z").toLocaleString("ru-RU"):"—"}
function action(e:Event){
 const a=e.action;
 if(a==="team.invitation_created")return "создал приглашение сотруднику";
 if(a==="team.invitation_accepted")return "зарегистрировался по приглашению";
 if(a==="organization.created")return "зарегистрировался и создал организацию";
 if(a==="team.invitation_revoked")return "отозвал приглашение";
 if(a==="team.member_deactivated")return "отключил доступ сотруднику";
 if(a==="http.mutation"){
  const path=e.path||""; const method=e.method||"";
  if(path==="/stocks/sync"||path.startsWith("/stocks/sync?"))return "запустил обновление остатков";
  if(path==="/team/invitations"&&method==="POST")return "отправил запрос на создание приглашения";
  if(path.startsWith("/team/invitations/")&&method==="DELETE")return "отправил запрос на отзыв приглашения";
  if(path.includes("/deactivate")&&method==="POST")return "отправил запрос на отключение сотрудника";
  return `выполнил действие в разделе API ${path || "(путь не указан)"}`;
 }
 return "выполнил действие ("+a+")";
}
export default function TeamSettings(){
 const {user}=useAuth();
 const [members,setMembers]=useState<Member[]>([]),[invites,setInvites]=useState<Invite[]>([]),[events,setEvents]=useState<Event[]>([]);
 const [email,setEmail]=useState(""),[link,setLink]=useState(""),[error,setError]=useState(""),[busy,setBusy]=useState(false),[auditOpen,setAuditOpen]=useState(false),[auditBusy,setAuditBusy]=useState(false);
 async function call(path:string,opts?:RequestInit){const r=await fetch(`${API}${path}`,{credentials:"include",...opts});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.message||"Ошибка запроса");return d;}
 async function reload(){try{const d=await call("/team");setMembers(d.members);setInvites(d.invitations)}catch(e){setError(e instanceof Error?e.message:"Ошибка получения данных")}}
 async function loadAudit(){setAuditBusy(true);try{const d=await call("/team/audit?limit=100");setEvents(d.events)}catch(e){setError(e instanceof Error?e.message:"Ошибка журнала")}finally{setAuditBusy(false)}}
 useEffect(()=>{void reload();const timer=window.setInterval(()=>{void reload()},60000);return ()=>window.clearInterval(timer)},[user?.id]);
 useEffect(()=>{if(!auditOpen)return;void loadAudit();const key=(e:KeyboardEvent)=>{if(e.key==="Escape")setAuditOpen(false)};window.addEventListener("keydown",key);return ()=>window.removeEventListener("keydown",key)},[auditOpen]);
 async function invite(){setBusy(true);setError("");setLink("");try{const d=await call("/team/invitations",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email})});setLink(`${window.location.origin}/register?invite=${encodeURIComponent(d.token)}`);setEmail("");await reload()}catch(e){setError(e instanceof Error?e.message:"Ошибка")}finally{setBusy(false)}}
 async function revoke(id:number){if(!window.confirm("Отозвать это приглашение? Ссылка перестанет работать."))return;setError("");try{await call(`/team/invitations/${id}`,{method:"DELETE"});await reload()}catch(e){setError(e instanceof Error?e.message:"Ошибка")}}
 async function deactivate(m:Member){if(!window.confirm(`Отключить доступ сотруднику ${m.name}? Его текущие сессии будут завершены, история действий сохранится.`))return;setError("");try{await call(`/team/members/${m.id}/deactivate`,{method:"POST"});await reload()}catch(e){setError(e instanceof Error?e.message:"Ошибка")}}
 return <div className="team-root">
  <div className="team-head"><div><h2>Сотрудники и доступ</h2><p>Рабочее пространство: <strong>{user?.organization_name}</strong></p></div>{user?.role==="OWNER"&&<button className="team-btn team-secondary" type="button" onClick={()=>setAuditOpen(true)}>Журнал действий</button>}</div>
  {error&&<p role="alert" className="team-error">{error}</p>}
  <section className="team-panel"><div className="team-panel-title"><div><h3>Участники</h3><p>Пользователи вашей организации и их текущий доступ.</p></div><span className="team-counter">{members.filter(m=>m.is_active).length} активных</span></div>
   <div className="team-list">{members.map(m=><div className="team-item" key={m.id}><div className="team-avatar">{m.name.trim().charAt(0).toUpperCase()}</div><div className="team-item-main"><strong>{m.name}</strong><span>{m.email}</span><small>{m.role==="OWNER"?"Владелец":"Сотрудник"} · {m.is_active?(m.online?"Активен в последние 5 минут":`Последняя активность: ${date(m.last_seen_at)}`):"Доступ отключён"}</small></div><div className="team-item-actions"><span className={`team-pill ${!m.is_active?"off":m.online?"online":""}`}>{!m.is_active?"Отключён":m.online?"Недавно в сети":"Не в сети"}</span>{user?.role==="OWNER"&&m.role!=="OWNER"&&m.is_active&&<button type="button" className="team-btn team-danger" onClick={()=>void deactivate(m)}>Отключить</button>}</div></div>)}</div>
  </section>
  {user?.role==="OWNER"&&<><section className="team-panel"><div className="team-panel-title"><div><h3>Пригласить сотрудника</h3><p>Приглашение действует 7 дней и привязано к email. Отправьте ссылку адресату безопасным способом.</p></div></div><div className="team-invite-form"><input type="email" aria-label="Email сотрудника" value={email} onChange={e=>setEmail(e.target.value)} placeholder="Email сотрудника"/><button className="team-btn team-primary" type="button" onClick={()=>void invite()} disabled={busy||!email.trim()}>{busy?"Создаём…":"Создать ссылку"}</button></div>{link&&<div className="team-link"><strong>Персональная ссылка (показывается один раз)</strong><div className="team-link-row"><input readOnly value={link} aria-label="Ссылка приглашения"/><button className="team-btn team-secondary" onClick={()=>void navigator.clipboard.writeText(link)}>Копировать</button></div></div>}</section>
  <section className="team-panel"><div className="team-panel-title"><div><h3>Приглашения</h3><p>Отозвать можно только ещё не использованную ссылку.</p></div></div><div className="team-list">{invites.length===0?<p className="team-empty">Приглашений пока нет</p>:invites.map(i=><div className="team-item" key={i.id}><div className="team-item-main"><strong>{i.email}</strong><small>Действует до {date(i.expires_at)}</small></div><div className="team-item-actions"><span className="team-pill">{statuses[i.status]||i.status}</span>{i.status==="pending"&&<button type="button" className="team-btn team-danger" onClick={()=>void revoke(i.id)}>Отозвать</button>}</div></div>)}</div></section></>}
  {auditOpen&&<div className="team-overlay" onMouseDown={e=>{if(e.target===e.currentTarget)setAuditOpen(false)}}><div className="team-modal" role="dialog" aria-modal="true" aria-label="Журнал действий"><div className="team-modal-header"><div><h3>Журнал действий</h3><p>Последние 100 событий · указано время и имя сотрудника</p></div><button type="button" className="team-btn team-secondary" onClick={()=>setAuditOpen(false)}>Закрыть</button></div><div className="team-modal-body">{auditBusy?<p>Загрузка…</p>:events.length===0?<p>Записей нет</p>:events.map(e=><div key={e.id} className="team-event"><div><strong>{e.user_name||`Пользователь #${e.user_id??"—"}`}</strong> {action(e)}{e.status_code!==null&&e.status_code>=400&&<span className="team-event-error"> · ошибка {e.status_code}</span>}</div><small>{date(e.created_at)}</small></div>)}</div><div className="team-modal-footer"><small>Журнал фиксирует изменяющие запросы. Просмотры страниц не учитываются.</small><button className="team-btn team-secondary" onClick={()=>void loadAudit()}>Обновить</button></div></div></div>}
 </div>;
}
