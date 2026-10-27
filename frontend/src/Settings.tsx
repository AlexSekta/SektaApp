import SyncSettings from "./SyncSettings";
import {defaultStockView, stockViewEndpoint, type StockViewSettings} from "./stockViewSettings";
import TeamSettings from "./TeamSettings";
import { useEffect, useState } from "react";
import { useAuth } from "./AuthContext";
import Toast, { type ToastType } from "./components/Toast";
import "./Settings.css";

const API = `${window.location.protocol}//${window.location.hostname}:8000`;
type MP = "WB" | "OZON" | "YANDEX";
type MPState = { enabled:boolean; configured:boolean; masked:Record<string,string|number|null>; last_connected_at:string|null; last_error:string|null };
type State = { appName:string; marketplaces:Record<MP,MPState>; wbToken:string; ozonClientId:string; ozonApiKey:string; yandexToken:string; yandexBusinessId:string };

const empty = ():State => ({
  appName:"SEKTA",
  marketplaces:{
    WB:{enabled:false,configured:false,masked:{},last_connected_at:null,last_error:null},
    OZON:{enabled:false,configured:false,masked:{},last_connected_at:null,last_error:null},
    YANDEX:{enabled:false,configured:false,masked:{},last_connected_at:null,last_error:null}
  },
  wbToken:"",ozonClientId:"",ozonApiKey:"",yandexToken:"",yandexBusinessId:""
});

function Toggle({checked,onChange}:{checked:boolean;onChange:()=>void}){
  return <button type="button" className={`settings-toggle${checked?" is-on":""}`} onClick={onChange} aria-pressed={checked}><span/></button>;
}
function Secret({value,onChange,placeholder,visible,onToggle}:{value:string;onChange:(v:string)=>void;placeholder:string;visible:boolean;onToggle:()=>void}){
  return <div className="settings-secret"><input type={visible?"text":"password"} value={value} onChange={e=>onChange(e.target.value)} placeholder={placeholder} autoComplete="off"/><button type="button" onClick={onToggle}>{visible?"Скрыть":"Показать"}</button></div>;
}

function Settings(){
  const { user, refreshUser } = useAuth();
  const isOwner = user?.role === "OWNER";
  const [s,setS]=useState<State>(()=>empty());
  const [loading,setLoading]=useState(true), [saving,setSaving]=useState(false);
  const [toast,setToast]=useState<{type:ToastType;message:string}|null>(null);
  const [stockView,setStockView] = useState<StockViewSettings>(defaultStockView);
  const [stockViewSaving,setStockViewSaving] = useState(false);
  const [show,setShow]=useState({WB:false,OZON:false,YANDEX:false});
  useEffect(()=>{
    if(user?.organization_name){
      setS(x=>({...x,appName:user.organization_name || "SEKTA"}));
    }
  },[user?.id,user?.organization_id,user?.organization_name]);

  useEffect(()=>{
    if (!isOwner) { setLoading(false); return; }
    fetch(`${API}/settings/marketplaces`,{credentials:"include"}).then(async r=>{const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.message||"Не удалось загрузить настройки");setS(x=>({...x,marketplaces:d.marketplaces}));}).catch(e=>setToast({type:"error",message:e.message})).finally(()=>setLoading(false));
  },[isOwner]);

  useEffect(()=>{if (!isOwner) return; fetch(stockViewEndpoint,{credentials:"include"}).then(async r=>{if(!r.ok)throw Error("Не удалось загрузить настройки остатков");return r.json()}).then(d=>setStockView({...d,fbo:true})).catch(e=>setToast({type:"error",message:e.message}));},[isOwner]);
  const saveStockView=async()=>{
    if (!isOwner) return;
    if(!stockView.wb&&!stockView.ozon&&!stockView.yandex){setToast({type:"error",message:"Выберите хотя бы один маркетплейс"});return;}
    setStockViewSaving(true);
    try{const r=await fetch(stockViewEndpoint,{method:"PUT",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify({...stockView,fbo:true})});
      const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(typeof d.detail==="string"?d.detail:"Не удалось сохранить параметры");
      setStockView({...d,fbo:true});window.dispatchEvent(new Event("stock-view-updated"));setToast({type:"success",message:"Настройки отображения остатков сохранены"});
    }catch(e){setToast({type:"error",message:e instanceof Error?e.message:"Ошибка сохранения"});}finally{setStockViewSaving(false);}
  };
  const switchStockView=(key:keyof StockViewSettings)=>setStockView(v=>({...v,[key]:!v[key]}));
  const toggle=(mp:MP)=>setS(x=>({...x,marketplaces:{...x.marketplaces,[mp]:{...x.marketplaces[mp],enabled:!x.marketplaces[mp].enabled}}}));

  const save=async()=>{
    if (!isOwner) return;
    setSaving(true);
    try{
      const organizationName=s.appName.trim()||"SEKTA";
      const orgResponse=await fetch(`${API}/settings/organization`,{method:"PUT",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:organizationName})});
      const orgData=await orgResponse.json().catch(()=>({}));
      if(!orgResponse.ok)throw Error(orgData.detail||orgData.message||"Не удалось сохранить название организации");

      const r=await fetch(`${API}/settings/marketplaces`,{method:"PUT",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify({marketplaces:{
        WB:{enabled:s.marketplaces.WB.enabled,token:s.wbToken},
        OZON:{enabled:s.marketplaces.OZON.enabled,client_id:s.ozonClientId,api_key:s.ozonApiKey},
        YANDEX:{enabled:s.marketplaces.YANDEX.enabled,api_key:s.yandexToken,business_id:s.yandexBusinessId}
      }})});
      const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.message||"Не удалось сохранить настройки");
      await refreshUser();
      setS(x=>({...x,appName:organizationName,marketplaces:d.marketplaces,wbToken:"",ozonClientId:"",ozonApiKey:"",yandexToken:"",yandexBusinessId:""}));
      setToast({type:"success",message:"Настройки сохранены"});
    }catch(e:any){setToast({type:"error",message:e.message||"Ошибка сохранения"});}finally{setSaving(false);}
  };

  const card=(mp:MP,title:string,desc:string)=><section className="settings-section settings-marketplace-card" key={mp}>
    <div className="settings-mp-head"><div className="settings-section-heading"><h2>{title}</h2><p>{desc}</p></div><div className="settings-mp-switch"><span className={`settings-mp-status${s.marketplaces[mp].enabled?" is-enabled":""}`}>{s.marketplaces[mp].enabled?"Включен":"Выключен"}</span><Toggle checked={s.marketplaces[mp].enabled} onChange={()=>toggle(mp)}/></div></div>
    {mp==="WB"&&<label className="settings-field"><span>API ключ</span><Secret value={s.wbToken} onChange={v=>setS(x=>({...x,wbToken:v}))} placeholder={s.marketplaces.WB.configured?"Ключ сохранён — введите новый для замены":"Введите API-токен WB"} visible={show.WB} onToggle={()=>setShow(x=>({...x,WB:!x.WB}))}/>{s.marketplaces.WB.configured&&<small className="settings-configured">Сохранён: {s.marketplaces.WB.masked.token||"••••"}</small>}</label>}
    {mp==="OZON"&&<div className="settings-fields-grid"><label className="settings-field"><span>Client ID</span><input value={s.ozonClientId} onChange={e=>setS(x=>({...x,ozonClientId:e.target.value}))} placeholder={s.marketplaces.OZON.configured?"Сохранён — введите новый для замены":"Введите Client ID"} autoComplete="off"/></label><label className="settings-field"><span>API ключ</span><Secret value={s.ozonApiKey} onChange={v=>setS(x=>({...x,ozonApiKey:v}))} placeholder={s.marketplaces.OZON.configured?"Ключ сохранён — введите новый для замены":"Введите API-ключ Ozon"} visible={show.OZON} onToggle={()=>setShow(x=>({...x,OZON:!x.OZON}))}/></label></div>}
    {mp==="YANDEX"&&<div className="settings-fields-grid"><label className="settings-field"><span>API ключ</span><Secret value={s.yandexToken} onChange={v=>setS(x=>({...x,yandexToken:v}))} placeholder={s.marketplaces.YANDEX.configured?"Ключ сохранён — введите новый для замены":"Введите API-ключ Яндекс Маркета"} visible={show.YANDEX} onToggle={()=>setShow(x=>({...x,YANDEX:!x.YANDEX}))}/></label><label className="settings-field"><span>Business ID</span><input value={s.yandexBusinessId} onChange={e=>setS(x=>({...x,yandexBusinessId:e.target.value}))} placeholder={s.marketplaces.YANDEX.masked.business_id?String(s.marketplaces.YANDEX.masked.business_id):"Например, 123456"} autoComplete="off"/></label></div>}
  </section>;

  if(loading&&isOwner)return <div className="settings-page"><div className="settings-loading">Загрузка настроек…</div></div>;
  return <div className="settings-page"><div className="settings-header"><div><h1>Настройки</h1><p>{isOwner?"Подключения маркетплейсов и параметры приложения.":"Участники рабочего пространства."}</p></div>{isOwner&&<button type="button" className="settings-save-button" onClick={()=>void save()} disabled={saving}>{saving?"Сохранение…":"Сохранить"}</button>}</div>
    {isOwner&&<><section className="settings-section"><div className="settings-section-heading"><h2>Основные настройки</h2><p>Название организации отображается в левом меню приложения.</p></div><label className="settings-field"><span>Название организации</span><input value={s.appName} onChange={e=>setS(x=>({...x,appName:e.target.value}))} placeholder="SEKTA" maxLength={200}/></label></section>
    <section className="settings-section"><div className="settings-section-heading"><h2>Маркетплейсы</h2><p>Включите только те площадки, с которыми работает эта организация.</p></div><div className="settings-marketplaces-list">{card("WB","Wildberries","API-подключение Wildberries.")}{card("OZON","Ozon","Client ID и API-ключ Ozon.")}{card("YANDEX","Яндекс Маркет","API-ключ и Business ID кабинета.")}</div></section>
    <section className="settings-section"><div className="settings-section-heading"><h2>Модели работы и отображение остатков</h2><p>Выберите модели и площадки для таблицы «Остатки». Это влияет только на отображение — синхронизация и сохранённые данные не изменяются.</p></div>
      <div className="stock-view-options">
        <div className="stock-view-option"><div><strong>FBS — со склада продавца</strong><small>При включении показываются собственные склады, остатки 1С и FBS. FBO / FBY отображается всегда.</small></div><Toggle checked={stockView.fbs} onChange={()=>switchStockView("fbs")}/></div>
        <div className="stock-view-marketplaces">
          {([ ["wb","Wildberries"],["ozon","Ozon"],["yandex","Яндекс Маркет"] ] as const).map(([key,label])=><div className="stock-view-option" key={key}><strong>{label}</strong><Toggle checked={stockView[key]} onChange={()=>switchStockView(key)}/></div>)}
        </div>
      </div>
      <button type="button" className="settings-save-button" disabled={stockViewSaving||(!stockView.wb&&!stockView.ozon&&!stockView.yandex)} onClick={()=>void saveStockView()}>{stockViewSaving?"Сохранение…":"Сохранить отображение"}</button>
    </section>
    </>}
    <SyncSettings/>
    <TeamSettings/>
    {isOwner&&<div className="settings-security-note"><strong>Безопасность</strong><span>Ключи маркетплейсов не возвращаются в интерфейс. При сохранении они шифруются и хранятся в БД. Для шифрования используется отдельный технический секрет приложения.</span></div>}
    {toast&&<Toast type={toast.type} message={toast.message} onClose={()=>setToast(null)}/>}</div>;
}
export default Settings;
