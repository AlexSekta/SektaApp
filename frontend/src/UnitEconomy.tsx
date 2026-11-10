import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './Analytics.css';
import './UnitEconomy.css';

type MP = 'WB' | 'OZON' | 'YANDEX';
type Scheme = 'FBO' | 'FBS';
type Product = { id:number; internal_article:string|null; seller_article:string; name:string|null; group:string; volume_liters:number|null; final_cost:number; wb_enabled:boolean; ozon_enabled:boolean; yandex_enabled:boolean };
type WBTariff = {product_id:number; matched:boolean; subject_name:string|null; commission_fbo:number|null; commission_fbs:number|null};
type Draft = { sellerPrice:string; discount:string; buyout:string; cost:string; logistics:string; commission:string; acquiring:string; processing:string; packaging:string };
const API = 'http://127.0.0.1:8000';
const formatPercent = (n:number) => new Intl.NumberFormat('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1}).format(n);
const format = (n:number) => new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2,minimumFractionDigits:2}).format(n);
const num = (v:string) => { const n = Number(v.replace(',','.')); return v.trim() !== '' && Number.isFinite(n) && n >= 0 ? n : null; };
const savedKey = (mp:MP, scheme:Scheme, id:number) => `unit-economy-v1:${mp}:${scheme}:${id}`;
const defaultDraft = (p:Product):Draft => ({ sellerPrice:'', discount:'0', buyout:'100', cost:String(p.final_cost ?? 0), logistics:'', commission:'', acquiring:'', processing:'', packaging:'0' });
function StatusSelect({value,onChange,disabled}:{value:'active'|'archive';onChange:(v:'active'|'archive')=>void;disabled:boolean}) {
  const [open,setOpen]=useState(false);
  const ref=useRef<HTMLDivElement|null>(null);
  useEffect(()=>{if(!open)return;const close=(e:MouseEvent)=>{if(!ref.current?.contains(e.target as Node))setOpen(false);};document.addEventListener('mousedown',close);return()=>document.removeEventListener('mousedown',close);},[open]);
  return <div className="ue-custom-select" ref={ref}><button type="button" className="ue-custom-trigger" disabled={disabled} onClick={()=>setOpen(v=>!v)}>{value==='active'?'Активные':'Архив'}<span className="ue-custom-arrow" /></button>{open&&<div className="ue-custom-options">{(['active','archive'] as const).map(v=><button type="button" key={v} className={value===v?'selected':''} onClick={()=>{setOpen(false);onChange(v);}}>{v==='active'?'Активные':'Архив'}</button>)}</div>}</div>;
}
function UnitEconomy() {
  const [mp,setMp] = useState<MP>('WB');
  const [scheme,setScheme] = useState<Scheme>('FBO');
  const [products,setProducts] = useState<Product[]>([]);
  const [wbTariffs,setWbTariffs] = useState<Record<number,WBTariff>>({});
  const [wbError,setWbError] = useState('');
  const [tariffPackageRate,setTariffPackageRate] = useState<number|null>(null);
  const [drafts,setDrafts] = useState<Record<string,Draft>>({});
  const [search,setSearch] = useState('');
  const [acquiringRate,setAcquiringRate] = useState<number|null>(null);
  const [acquiringPeriod,setAcquiringPeriod] = useState('');
  const [packagingEdit,setPackagingEdit] = useState<number|null>(null);
  const [packagingValue,setPackagingValue] = useState('');
  const [showActive,setShowActive] = useState(true);
  const [showArchive,setShowArchive] = useState(false);
  const [statuses,setStatuses] = useState<Record<string,'active'|'archive'>>({});
  const [settingsOpen,setSettingsOpen] = useState(false);
  const [rateEdit,setRateEdit] = useState('');
  const [saving,setSaving] = useState(false);
  const [confirmation,setConfirmation] = useState<{title:string;description:string;accept:()=>void}|null>(null);
  const [loading,setLoading] = useState(true);
  const [message,setMessage] = useState('');
  const [expanded,setExpanded] = useState<number|null>(null);
  const popoverRef = useRef<HTMLDivElement|null>(null);
  const refresh = useCallback(async () => {setLoading(true);setMessage('');try {const res=await fetch(`${API}/master-products`);if(!res.ok)throw new Error(`Каталог: HTTP ${res.status}`);const data:unknown=await res.json();if(!Array.isArray(data))throw new Error('Неверный формат каталога');setProducts(data as Product[]);}catch(e){setMessage(e instanceof Error?e.message:'Не удалось получить каталог');}finally{setLoading(false);}},[]);
  useEffect(()=>{void refresh();},[refresh]);
  const statusKey=(market:MP,id:number)=>`${market}:${id}`;
  const loadSettings=useCallback(async()=>{
    try {
      const res=await fetch(`${API}/unit-economy/settings`);
      if(!res.ok)throw new Error(`Настройки: HTTP ${res.status}`);
      const data=await res.json() as {settings:{marketplace:MP;tariff_package_rate:number|null}[];statuses:{product_id:number;marketplace:MP;status:'active'|'archive'}[]};
      setStatuses(Object.fromEntries(data.statuses.map(x=>[`${x.marketplace}:${x.product_id}`,x.status])));
      const wb=data.settings.find(x=>x.marketplace==='WB');
      if(wb?.tariff_package_rate!=null){setTariffPackageRate(Number(wb.tariff_package_rate));setRateEdit(String(wb.tariff_package_rate));}

    }catch(e){setMessage(e instanceof Error?e.message:'Не удалось получить настройки');}
  },[]);
  useEffect(()=>{void loadSettings();},[loadSettings]);
  const saveRate=async()=>{
    const value=num(rateEdit);
    if(value===null||value>100){setMessage('Введите тарифный пакет от 0 до 100%');return;}
    setConfirmation({title:'Подтверждение изменения',description:`Установить тарифный пакет WB ${value}% для всех товаров кабинета?`,accept:()=>{setConfirmation(null);void persistRate(value);}});
  };
  const persistRate=async(value:number)=>{
    setSaving(true);
    try{const res=await fetch(`${API}/unit-economy/settings`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({marketplace:'WB',tariff_package_rate:value})});if(!res.ok)throw new Error(`HTTP ${res.status}`);setTariffPackageRate(value);setSettingsOpen(false);setMessage('Тарифный пакет сохранён для всех товаров WB.');}
    catch(e){setMessage(`Не удалось сохранить тариф: ${e instanceof Error?e.message:String(e)}`);}
    finally{setSaving(false);}
  };
  const updateStatus=async(p:Product,status:'active'|'archive')=>{
    if(status===(statuses[statusKey(mp,p.id)]||'active'))return;
    setConfirmation({title:'Изменение статуса товара',description:`Перевести ${p.internal_article||p.seller_article} в статус «${status==='archive'?'Архив':'Активные'}»?`,accept:()=>{setConfirmation(null);void persistStatus(p,status);}});
  };
  const persistStatus=async(p:Product,status:'active'|'archive')=>{
    setSaving(true);
    try{const res=await fetch(`${API}/unit-economy/products/${p.id}/status`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({marketplace:mp,status})});if(!res.ok)throw new Error(`HTTP ${res.status}`);setStatuses(v=>({...v,[statusKey(mp,p.id)]:status}));setExpanded(null);}
    catch(e){setMessage(`Не удалось изменить статус: ${e instanceof Error?e.message:String(e)}`);}
    finally{setSaving(false);}
  };
  useEffect(()=>{let active=true;fetch(`${API}/unit-economy/wb/acquiring-average`).then(async r=>{if(!r.ok)throw Error(`HTTP ${r.status}`);return r.json();}).then((d:{rate:number|null;date_from:string;date_to:string})=>{if(active){setAcquiringRate(d.rate);setAcquiringPeriod(`${d.date_from} — ${d.date_to}`);}}).catch(()=>{if(active)setAcquiringRate(null);});return()=>{active=false;};},[]);
  const startPackaging=(p:Product)=>{setPackagingEdit(p.id);setPackagingValue(draft(p).packaging);};
  const commitPackaging=(p:Product)=>{const v=num(packagingValue);if(v===null){setMessage('Упаковка: укажите неотрицательное число');return;}change(p,'packaging',String(v));setPackagingEdit(null);};
  const refreshWb = useCallback(async () => {
    setWbError('');
    try {
      const response = await fetch(`${API}/unit-economy/wb/catalog-tariffs`);
      if (!response.ok) {
        const reason = response.status === 503 ? 'WB ограничил частоту запросов (429). Уже загруженные данные сохранены; повторите позже.' : `WB: HTTP ${response.status}. Уже загруженные данные сохранены.`;
        throw new Error(reason);
      }
      const payload = await response.json() as {items:WBTariff[]; stale?:boolean; synced_at?:string|null; status?:string; tariff_package_rate?:number|null};
      if (payload.status === "waiting_first_sync") setWbError("Первичная синхронизация WB ещё не завершена. Данные появятся после успешного обновления фоновой задачей.");
      setWbTariffs(Object.fromEntries(payload.items.map(x => [x.product_id,x])));
      if(typeof payload.tariff_package_rate === 'number'){setTariffPackageRate(payload.tariff_package_rate);setRateEdit(String(payload.tariff_package_rate));}
    } catch(e) {setWbError(e instanceof Error?e.message:'Ошибка загрузки комиссий WB'); }
  }, []);
  useEffect(()=>{void refreshWb();},[refreshWb]);
  useEffect(()=>{
    if(expanded===null)return;
    const onOutside=(event:PointerEvent)=>{if(event.target instanceof Node && !popoverRef.current?.contains(event.target))setExpanded(null);};
    const onEscape=(event:KeyboardEvent)=>{if(event.key==='Escape')setExpanded(null);};
    document.addEventListener('pointerdown',onOutside);
    document.addEventListener('keydown',onEscape);
    return ()=>{document.removeEventListener('pointerdown',onOutside);document.removeEventListener('keydown',onEscape);};
  },[expanded]);
  const visible=useMemo(()=>products.filter(p=>{
    const enabled=mp==='WB'?p.wb_enabled:mp==='OZON'?p.ozon_enabled:p.yandex_enabled;
    const txt=[p.internal_article,p.seller_article,p.name,mp==='WB'?wbTariffs[p.id]?.subject_name:p.group].join(' ').toLowerCase();
    const status=statuses[statusKey(mp,p.id)]||'active';
    return (status==='active'?showActive:showArchive)&&enabled&&txt.includes(search.trim().toLowerCase());
  }),[products,search,mp,wbTariffs,statuses,showActive,showArchive]);
  const fieldKey=(p:Product)=>savedKey(mp,scheme,p.id);
  const draft=(p:Product):Draft=>drafts[fieldKey(p)] ?? (():Draft=>{
    try {
      const raw=localStorage.getItem(fieldKey(p));
      if(raw){
        const legacy=JSON.parse(raw) as Partial<Draft>&{price?:string};
        return {...defaultDraft(p),...legacy,sellerPrice:legacy.sellerPrice??legacy.price??'',discount:legacy.discount??'0',buyout:legacy.buyout??'100'};
      }
    }catch{/* ignore corrupted local draft */}
    return defaultDraft(p);
  })();
  const change=(p:Product, field:keyof Draft, value:string)=>{
    const next={...draft(p),[field]:value};const key=fieldKey(p);
    setDrafts(prev=>({...prev,[key]:next}));
    try{localStorage.setItem(key,JSON.stringify(next));}catch{/* private mode */}
  };
  const salePrice=(d:Draft)=>{
    const seller=num(d.sellerPrice), discount=num(d.discount);
    return seller!==null&&discount!==null&&discount<=100?seller*(1-discount/100):null;
  };
  const calc=(d:Draft, commissionOverride:number|null=null)=>{
    const price=salePrice(d),cost=num(d.cost),logistics=num(d.logistics),commission=commissionOverride??num(d.commission),acquiring=mp==='WB'?acquiringRate:num(d.acquiring),processing=0,packaging=num(d.packaging),buyout=num(d.buyout);
    if([price,cost,logistics,commission,acquiring,processing,packaging,buyout].some(v=>v===null))return null;
    const p=price!, c=cost!, l=logistics!, k=commission!, a=acquiring!, pr=processing!, pack=packaging!;
    if(k>100||a>100||buyout!>100||buyout!<=0)return null;
    const commissionRub=p*k/100, acquiringRub=p*a/100;
    // Buyout is displayed as a scenario input; return and reverse-delivery costs require a separate verified model.
    const expenses=c+l+commissionRub+acquiringRub+pr+pack;
    const profit=p-expenses;
    return {profit, margin:p>0?profit/p*100:null, expenses, commissionRub,acquiringRub};
  };
  const input=(p:Product,field:keyof Draft, label:string)=> <input aria-label={`${label}: ${p.internal_article||p.seller_article}`} inputMode="decimal" value={draft(p)[field]} onChange={e=>change(p,field,e.target.value)} placeholder="—" />;
  return <div className="analytics-page ue-page">
    <div className="analytics-header"><div><h1>Юнит-экономика</h1><p>Калькулятор прибыли на единицу товара. Один товар — одна строка.</p></div><button className="analytics-refresh" disabled={loading} onClick={()=>{void refresh();void refreshWb();}}>Обновить товары</button></div>
    <div className="ue-toolbar"><div className="ue-status-filters"><button type="button" className={showActive?'selected':''} aria-pressed={showActive} onClick={()=>setShowActive(v=>!v)}>Активные</button><button type="button" className={showArchive?'selected':''} aria-pressed={showArchive} onClick={()=>setShowArchive(v=>!v)}>Архив</button></div><div className="ue-segment" aria-label="Маркетплейс">{([['WB','WB'],['OZON','Ozon'],['YANDEX','Я.Маркет']] as const).map(([key,label])=><button key={key} type="button" className={mp===key?'active':''} onClick={()=>{setMp(key);setExpanded(null);}}>{label}</button>)}</div><div className="ue-segment" aria-label="Модель продаж">{(['FBO','FBS'] as const).map(key=><button key={key} type="button" className={scheme===key?'active':''} onClick={()=>{setScheme(key);setExpanded(null);}}>{key}</button>)}</div><input className="ue-search" placeholder="Поиск по артикулу или названию" value={search} onChange={e=>setSearch(e.target.value)} /><button type="button" className="ue-settings-button" onClick={()=>setSettingsOpen(true)}>Настройки</button></div>
    <div className="ue-note">Категория и комиссия WB читаются из PostgreSQL и обновляются фоновой задачей примерно раз в 6 часов, если карточка однозначно сопоставлена и тариф найден. Тарифный пакет задаётся вручную в настройках и сохраняется в PostgreSQL. Остальные тарифы и цены вводятся вручную; данные сохраняются в этом браузере для каждой площадки и модели. Цена рассчитывается как «Цена продавца × (1 − Скидка / 100)». Процент выкупа пока справочный: без подтверждённой модели расходов на невыкуп он не меняет прибыль. Эквайринг WB рассчитывается по финансовым отчётам за последние 4 месяца при наличии данных. Упаковка — в меню товара.</div>
    {message&&<div className="ue-error">{message}</div>}{mp==='WB'&&wbError&&<div className="ue-error">{wbError}</div>}
    <div className="ue-table-wrap"><table className="ue-table"><thead><tr><th>Артикул</th><th>Название</th><th>Категория</th><th>Себестоимость, ₽</th><th>Объём, л</th><th>Комиссия, %</th><th>Логистика, ₽</th><th>Процент выкупа, %</th><th>Цена продавца, ₽</th><th>Скидка, %</th><th>Цена, ₽</th><th>Прибыль, ₽</th><th>Маржа, %</th></tr></thead><tbody>{visible.map(p=>{const d=draft(p),wb=mp==='WB'?wbTariffs[p.id]:undefined;
      const autoCommission=wb?(scheme==='FBO'?wb.commission_fbo:wb.commission_fbs):null;
      const totalCommission=autoCommission==null || tariffPackageRate==null ? null : autoCommission+tariffPackageRate;
      const usedCommission=mp==='WB' ? totalCommission : autoCommission;
      const result=mp==='WB' && autoCommission!=null && tariffPackageRate==null ? null : calc(d,usedCommission),price=salePrice(d);return <tr key={p.id}><td><div className="ue-article-cell" ref={expanded===p.id?popoverRef:undefined}><button type="button" className="ue-more-button" aria-label={`Настройки товара ${p.internal_article||p.seller_article}`} aria-expanded={expanded===p.id} aria-haspopup="true" onClick={()=>setExpanded(expanded===p.id?null:p.id)}><span aria-hidden="true">⋮</span></button><span className="ue-article-text">{p.internal_article||p.seller_article}</span>{expanded===p.id&&<div className="ue-expanded"><div className="ue-popover-title">Товар · {p.internal_article||p.seller_article}</div><label>Статус <StatusSelect disabled={saving} value={statuses[statusKey(mp,p.id)]||'active'} onChange={v=>void updateStatus(p,v)}/></label><div className="ue-detail-line"><span>Эквайринг WB, %</span><span title={acquiringPeriod||'Нет данных'}>{mp==='WB'?(acquiringRate===null?'Нет данных':`${formatPercent(acquiringRate)}%`):'—'}</span></div><div className="ue-detail-line"><span>Упаковка, ₽</span>{packagingEdit===p.id?<span className="ue-pack-edit"><input aria-label="Сумма упаковки" inputMode="decimal" autoFocus value={packagingValue} onChange={e=>setPackagingValue(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')commitPackaging(p);if(e.key==='Escape')setPackagingEdit(null);}}/><button type="button" aria-label="Сохранить упаковку" onClick={()=>commitPackaging(p)}>✓</button></span>:<span className="ue-pack-value">{format(num(d.packaging)??0)} <button type="button" className="ue-pack-more" aria-label="Изменить упаковку" onClick={()=>startPackaging(p)}>⋮</button></span>}</div></div>}</div></td><td className="ue-name" title={p.name||''}>{p.name||'—'}</td><td>{mp==='WB'?(wb?.subject_name||'—'):(p.group||'—')}</td><td>{input(p,'cost','Себестоимость')}</td><td className="ue-number">{p.volume_liters==null?'—':format(p.volume_liters)}</td><td>{mp==='WB' && autoCommission!==null&&autoCommission!==undefined ?
        <span className="ue-commission-wrap" tabIndex={0} onClick={()=>{setRateEdit(tariffPackageRate==null?'':String(tariffPackageRate));setSettingsOpen(true);}} aria-label="Состав комиссии WB">
          {totalCommission!==null?`${formatPercent(totalCommission)}%`:`${formatPercent(autoCommission)}%*`}
          <span className="ue-commission-tip" role="tooltip">
            <span>Комиссия категории <strong>{formatPercent(autoCommission)}%</strong></span>
            <span>Тарифный пакет <strong>{tariffPackageRate!==null?`${formatPercent(tariffPackageRate)}%`:'не задан'}</strong></span><small>Нажмите для изменения тарифа</small>
            <span className="ue-commission-total">Итого <strong>{totalCommission!==null?`${formatPercent(totalCommission)}%`:'не рассчитано'}</strong></span>
          </span>
        </span> : input(p,'commission','Комиссия (ручная)')}</td><td>{input(p,'logistics','Логистика')}</td><td>{input(p,'buyout','Процент выкупа')}</td><td>{input(p,'sellerPrice','Цена продавца')}</td><td>{input(p,'discount','Скидка')}</td><td className="ue-number">{price===null?'—':format(price)}</td><td className={result?(result.profit>=0?'ue-positive':'ue-negative'):''}>{result?format(result.profit):'—'}</td><td className={result?(result.profit>=0?'ue-positive':'ue-negative'):''}>{result&&result.margin!==null?format(result.margin)+'%':'—'}</td></tr>;})}</tbody></table>{loading?<div className="ue-empty">Загружаем товары…</div>:visible.length===0?<div className="ue-empty">Нет товаров для выбранной площадки или фильтра</div>:null}</div>
    {settingsOpen&&<div className="ue-modal-overlay" onMouseDown={e=>{if(e.target===e.currentTarget)setSettingsOpen(false);}}><div className="ue-modal" role="dialog" aria-modal="true" aria-label="Настройки юнит-экономики"><div className="ue-modal-top"><h3>Настройки юнит-экономики</h3><button type="button" onClick={()=>setSettingsOpen(false)} aria-label="Закрыть">×</button></div>{mp==='WB'&&<><div className="ue-setting-row"><span>Тарифный пакет WB, %<small>Надбавка ко всем комиссиям категорий WB для данного кабинета</small></span><input type="text" inputMode="decimal" maxLength={5} value={rateEdit} onChange={e=>setRateEdit(e.target.value)} placeholder="Не задан" /></div><button className="ue-save" disabled={saving} onClick={()=>void saveRate()}>Сохранить</button></>}</div></div>}
    {confirmation&&<div className="ue-modal-overlay" onMouseDown={e=>{if(e.target===e.currentTarget)setConfirmation(null);}}><div className="ue-modal ue-confirm-modal" role="alertdialog" aria-modal="true" aria-label={confirmation.title}><div className="ue-modal-top"><h3>{confirmation.title}</h3><button type="button" aria-label="Закрыть" onClick={()=>setConfirmation(null)}>×</button></div><p>{confirmation.description}</p><div className="ue-confirm-actions"><button type="button" className="ue-secondary" onClick={()=>setConfirmation(null)}>Отмена</button><button type="button" className="ue-primary" disabled={saving} onClick={confirmation.accept}>Подтвердить</button></div></div></div>}
    {mp==='WB' && tariffPackageRate===null && <p className="ue-footer">* Надбавка конструктора тарифов ещё не получена: показана только комиссия категории. Прибыль по WB не рассчитывается до получения полной комиссии.</p>}
    <p className="ue-footer">Плановый расчёт без налогов, расходов на невыкуп и возвраты, хранения и рекламы. Не является фактической прибылью по отчётам маркетплейсов.</p>
  </div>;
}
export default UnitEconomy;
