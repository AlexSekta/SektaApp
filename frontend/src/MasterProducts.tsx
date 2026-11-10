import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./MasterProducts.css";

interface ImportCard { marketplace:MP; external_id:string; article:string; name:string;
  barcodes:string[]; dimensions:{length_cm:number;width_cm:number;height_cm:number}|null;
  platform_ids:Record<string,string>; status:"NEW"|"MATCH"|"LINKED"|"CONFLICT";
  master_id:number|null; suggested_master_id:number|null; }
interface ImportPreview { marketplace:MP; total:number; items:ImportCard[];
  summary:Record<string,number>; read_only:boolean; }
interface AttentionItem { id:number; marketplace:string; nm_id:string; article:string;
  old_article:string|null; reason:string; status:string; title:string|null; master_id:number|null; }
type MP = "WB" | "OZON" | "YANDEX";
type ProductStatus = "READY" | "SELLING" | "ARCHIVE";
interface Product {
  id:number; sort_order:number; internal_article:string|null; seller_article:string;
  barcode:string|null; name:string|null; group:string; purchase_price:number;
  additional_costs:number; final_cost:number; length_cm:number|null; width_cm:number|null;
  height_cm:number|null; volume_liters:number|null; wb_enabled:boolean; ozon_enabled:boolean;
  yandex_enabled:boolean; active:boolean; status?:ProductStatus|null;
}
interface Form { internal_article:string; seller_article:string; barcode:string; name:string; group:string;
  purchase_price:string; additional_costs:string; length_cm:string; width_cm:string; height_cm:string;
  wb_enabled:boolean; ozon_enabled:boolean; yandex_enabled:boolean; active:boolean; status:ProductStatus; }
const API="http://127.0.0.1:8000";
const EMPTY:Form={internal_article:"",seller_article:"",barcode:"",name:"",group:"Маркетплейс",purchase_price:"",additional_costs:"0",length_cm:"",width_cm:"",height_cm:"",wb_enabled:false,ozon_enabled:false,yandex_enabled:false,active:false,status:"READY"};
const money=(n:number)=>new Intl.NumberFormat("ru-RU",{minimumFractionDigits:2,maximumFractionDigits:2}).format(n);
const n=(v:number|null)=>v==null?"—":new Intl.NumberFormat("ru-RU",{maximumFractionDigits:2}).format(v);
const formOf=(p:Product):Form=>({internal_article:p.internal_article||"",seller_article:p.seller_article||"",barcode:p.barcode||"",name:p.name||"",group:p.group||"Маркетплейс",purchase_price:String(p.purchase_price??""),additional_costs:String(p.additional_costs??0),length_cm:p.length_cm==null?"":String(p.length_cm),width_cm:p.width_cm==null?"":String(p.width_cm),height_cm:p.height_cm==null?"":String(p.height_cm),wb_enabled:p.wb_enabled,ozon_enabled:p.ozon_enabled,yandex_enabled:p.yandex_enabled,active:p.active,status:p.status || (p.active ? "SELLING" : "READY")});


type SelectOption<T extends string> = { value: T; label: string };

function CustomSelect<T extends string>({
  value,
  options,
  onChange,
  className = "",
  ariaLabel,
}: {
  value: T;
  options: SelectOption<T>[];
  onChange: (value: T) => void;
  className?: string;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const selected = options.find(option => option.value === value) || options[0];

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div
      ref={ref}
      className={`custom-select ${className}${open ? " is-open" : ""}`}
      onClick={e => e.stopPropagation()}
    >
      <button
        type="button"
        className="custom-select-trigger"
        aria-label={ariaLabel}
        aria-expanded={open}
        onClick={() => setOpen(v => !v)}
      >
        <span className="custom-select-arrow" aria-hidden="true" />
        <span className="custom-select-value">{selected?.label ?? ""}</span>
      </button>
      {open && (
        <div className="custom-select-menu">
          {options.map(option => (
            <button
              type="button"
              key={option.value}
              className={`custom-select-option${option.value === value ? " selected" : ""}`}
              onClick={() => {
                onChange(option.value);
                setOpen(false);
              }}
            >
              <span>{option.label}</span>

            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function MasterProducts(){
  const [importVisible,setImportVisible]=useState(false);
  const [importMarket,setImportMarket]=useState<MP>("WB");
  const [importPreview,setImportPreview]=useState<ImportPreview|null>(null);
  const [importLoading,setImportLoading]=useState(false);
  const [importError,setImportError]=useState("");
  const [importSearch,setImportSearch]=useState("");
  const [importSelected,setImportSelected]=useState<Record<string,boolean>>({});
  const [importTargets,setImportTargets]=useState<Record<string,string>>({});
  const [importResults,setImportResults]=useState<string[]>([]);
  const [marketCards,setMarketCards]=useState<{marketplace:string;external_id:string;seller_article:string;title:string|null;barcode:string|null;dimensions:{length_cm:number;width_cm:number;height_cm:number}|null;platform_ids:Record<string,string>}[]>([]);
  const readResponse=async(r:Response)=>{
    const raw=await r.text();let value:any=null;
    try{value=JSON.parse(raw)}catch{throw Error(`Сервер вернул HTTP ${r.status}. Проверь журнал backend.`)}
    if(!r.ok)throw Error(typeof value.detail==="string"?value.detail:`HTTP ${r.status}`);
    return value;
  };
  const runPreview=async(market:MP)=>{
    setImportMarket(market);setImportLoading(true);setImportError("");setImportSelected({});setImportTargets({});setImportPreview(null);
    try{setImportPreview(await readResponse(await fetch(`${API}/catalog-import/${market}/preview`)))}
    catch(e){setImportError(e instanceof Error?e.message:"Ошибка загрузки каталога")}
    finally{setImportLoading(false)}
  };
  const importSelectedCards=async()=>{
    if(!importPreview)return;
    const chosen=importPreview.items.filter(x=>importSelected[x.external_id] && x.status!=="LINKED" && x.status!=="CONFLICT");
    if(!chosen.length){setImportError("Отметьте карточки со статусом «Новый» или «Найден товар».");return}
    if(!confirm(`Импортировать ${chosen.length} карточек ${importMarket}? Проверь выбранные связи. Новые товары будут «Готовится» и не попадут в реестр/OOS.`))return;
    setImportLoading(true);setImportError("");
    try{
      const items=chosen.map(card=>({external_id:card.external_id,article:card.article,
        master_id:importTargets[card.external_id]?Number(importTargets[card.external_id]):null}));
      const response=await readResponse(await fetch(`${API}/catalog-import/${importMarket}/import-batch`,{
        method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({items})
      }));
      setImportResults((response.results||[]).map((x:{external_id:string;status:string})=>`${x.external_id}: ${x.status}`));
      await load();await runPreview(importMarket);
    }catch(e){setImportError(e instanceof Error?e.message:"Импорт отклонён; изменения отменены")}
    finally{setImportLoading(false)}
  };
  const [products,setProducts]=useState<Product[]>([]); const [search,setSearch]=useState("");
  const [mp,setMp]=useState<"ALL"|MP>("ALL"); const [statusFilter,setStatusFilter]=useState<"ALL"|ProductStatus>("ALL");
  const [modal,setModal]=useState(false); const [editing,setEditing]=useState<Product|null>(null); const [form,setForm]=useState< Form>(EMPTY);
  const [saving,setSaving]=useState(false); const [message,setMessage]=useState(""); const [economy,setEconomy]=useState<Product|null>(null);
  const [card,setCard]=useState<Product|null>(null); const [cardMp,setCardMp]=useState<MP>("WB");
  const [menuId,setMenuId]=useState<number|null>(null);
  const [menuPosition,setMenuPosition]=useState<{top:number;left:number}|null>(null);
  const openProductMenu=(e:React.MouseEvent<HTMLButtonElement>,id:number)=>{
    e.stopPropagation();
    if(menuId===id){setMenuId(null);setMenuPosition(null);return;}
    const rect=e.currentTarget.getBoundingClientRect();
    const menuWidth=200,menuHeight=170,margin=8;
    setMenuPosition({
      top:rect.bottom+menuHeight+margin<=window.innerHeight ? rect.bottom+4 : Math.max(margin,rect.top-menuHeight-4),
      left:Math.max(margin,Math.min(rect.left,window.innerWidth-menuWidth-margin))
    });
    setMenuId(id);
  };
  useEffect(()=>{
    if(menuId===null)return;
    const close=()=>{setMenuId(null);setMenuPosition(null);};
    window.addEventListener("scroll",close,true);
    window.addEventListener("resize",close);
    return ()=>{window.removeEventListener("scroll",close,true);window.removeEventListener("resize",close);};
  },[menuId]);
  const [tab,setTab]=useState<"catalog"|"attention">("catalog");
  const [alerts,setAlerts]=useState<AttentionItem[]>([]);
  const [attentionBusy,setAttentionBusy]=useState(false);
  const [selectedMaster,setSelectedMaster]=useState<Record<number,string>>({});
  const loadAttention=async()=>{const r=await fetch(`${API}/product-attention`);if(!r.ok)throw Error(`Не удалось получить конфликты (${r.status})`);setAlerts(await r.json());};
  useEffect(()=>{void loadAttention().catch(()=>{});},[]);
  const scanAttention=async()=>{setAttentionBusy(true);setMessage("");try{
    const r=await fetch(`${API}/product-attention/scan`,{method:"POST"});if(!r.ok)throw Error(`Сверка WB не выполнена (${r.status})`);
    const x=await r.json();setMessage(`Проверено карточек WB: ${x.scanned}; требуют внимания: ${x.attention}`);await loadAttention();
  }catch(e){setMessage(e instanceof Error?e.message:"Ошибка сверки");}finally{setAttentionBusy(false);}};
  const approveAttention=async(a:AttentionItem)=>{const target=Number(selectedMaster[a.id]||products.find(p=>p.seller_article===a.article)?.id||0);
    if(!target){setMessage("Укажи товар каталога для подтверждения");return;}
    if(!confirm(`Подтвердить связь WB nmID ${a.nm_id} с товаром ID ${target}? История не изменится.`))return;
    setAttentionBusy(true);try{const r=await fetch(`${API}/product-attention/${a.id}/approve`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({master_id:target,nm_id:a.nm_id,observed_article:a.article})});const x=await r.json();if(!r.ok)throw Error(typeof x.detail==="string"?x.detail:"Ошибка подтверждения");setMessage(`Подтверждено nmID ${a.nm_id}`);await loadAttention();}catch(e){setMessage(e instanceof Error?e.message:"Ошибка");}finally{setAttentionBusy(false);}};


  const load=async()=>{
    const r=await fetch(`${API}/master-products`);
    if(!r.ok)throw Error(`Ошибка загрузки: ${r.status}`);
    const data=await r.json();
    const normalized=(Array.isArray(data)?data:[]).map((p:Product)=>({
      ...p,
      // Совместимость со старыми строками БД/API, где status ещё не был возвращён.
      status:(p.status==="SELLING"||p.status==="ARCHIVE"||p.status==="READY")
        ? p.status
        : (p.active ? "SELLING" : "READY"),
    }));
    setProducts(normalized);
  };
  useEffect(()=>{void load().catch(e=>setMessage(e instanceof Error?e.message:"Ошибка загрузки"));},[]);
  const filtered=useMemo(()=>{const q=search.trim().toLowerCase();return products.filter(p=>{
    const text=[p.internal_article,p.seller_article,p.barcode,p.name].map(x=>String(x||"").toLowerCase()).join(" ");
    const m=mp==="ALL"||(mp==="WB"&&p.wb_enabled)||(mp==="OZON"&&p.ozon_enabled)||(mp==="YANDEX"&&p.yandex_enabled);
    const s=statusFilter==="ALL"||p.status===statusFilter; return (!q||text.includes(q))&&m&&s;
  });},[products,search,mp,statusFilter]);
  const stats={total:products.length,active:products.filter(p=>p.active).length,wb:products.filter(p=>p.wb_enabled).length,ozon:products.filter(p=>p.ozon_enabled).length,yandex:products.filter(p=>p.yandex_enabled).length};
  const openAdd=()=>{setEditing(null);setForm(EMPTY);setMessage("");setModal(true);};
  const openEdit=(p:Product)=>{setEditing(p);setForm(formOf(p));setMessage("");setMarketCards([]);setModal(true);
    void fetch(`${API}/catalog-import/product/${p.id}/cards`).then(readResponse).then(setMarketCards).catch(()=>{});
  };
  const setField=<K extends keyof Form>(key:K,value:Form[K])=>setForm(f=>({...f,[key]:value}));
  const save=async()=>{if(saving)return;setSaving(true);setMessage("");try{const r=await fetch(editing?`${API}/master-products/${editing.id}`:`${API}/master-products`,{method:editing?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(form)});const d=await r.json();if(!r.ok||d.status!=="ok")throw Error(d.message||"Не удалось сохранить товар");setModal(false);setMessage(editing?"Товар сохранён":"Товар добавлен");await load();}catch(e){setMessage(e instanceof Error?e.message:"Ошибка сохранения");}finally{setSaving(false);}};
  const remove=async(p:Product)=>{if(!confirm(`Удалить «${p.name||p.seller_article}»?`))return;const r=await fetch(`${API}/master-products/${p.id}`,{method:"DELETE"});const d=await r.json();if(!r.ok||d.status!=="ok"){setMessage(d.message||"Не удалось удалить");return;}await load();};
  const mps=(p:Product)=>{const a:MP[]=[];if(p.wb_enabled)a.push("WB");if(p.ozon_enabled)a.push("OZON");if(p.yandex_enabled)a.push("YANDEX");return a;};
  const dimensionsMissing=(p:Product)=>p.length_cm==null||p.width_cm==null||p.height_cm==null;

  return <div className="products-page" onClick={()=>menuId!==null&&setMenuId(null)}>
    <header className="products-head"><div><div className="products-eyebrow">КАТАЛОГ ТОВАРОВ</div><h1>Товары</h1><p>Единый справочник товаров, себестоимости, габаритов и маркетплейсов.</p></div><div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
    <button className="products-primary" onClick={()=>{setImportVisible(true);setImportPreview(null);setImportResults([]);setImportError("");}}>Синхронизировать товары</button>
    <button className="products-primary" onClick={openAdd}>+ Добавить товар</button></div></header>
    <div className="product-attention-tabs">
      <button className={tab==="catalog"?"active":""} onClick={()=>setTab("catalog")}>Все товары</button>
      <button className={tab==="attention"?"active":""} onClick={()=>{setTab("attention");void loadAttention().catch(()=>{});}}>Требует внимания ({alerts.filter(a=>a.status==="OPEN").length})</button>
    </div>
    {tab==="attention" && <section className="product-attention">
      <p>Конфликты идентичности карточек. Ничего не меняется без подтверждения. WB связывается по nmID, остальные маркетплейсы — отдельно.</p>
      <button className="products-primary" disabled={attentionBusy} onClick={()=>void scanAttention()}>Сверить карточки WB</button>
      {message&&<p role="status">{message}</p>}
      <div className="products-table-wrap"><table className="products-table"><thead><tr><th>Товар WB</th><th>nmID</th><th>Было / обнаружено</th><th>Проблема</th><th>Связать с товаром</th><th>Действие</th></tr></thead><tbody>
      {alerts.filter(a=>a.status==="OPEN").map(a=><tr key={a.id}><td>{a.title||a.article}</td><td>{a.nm_id}</td><td>{a.old_article||"—"} → {a.article}</td><td>{a.reason}</td><td>
      <select value={selectedMaster[a.id]||String(products.find(p=>p.seller_article===a.article)?.id||"")} onChange={e=>setSelectedMaster(m=>({...m,[a.id]:e.target.value}))}>
        <option value="">Выбрать товар</option>
        {products.map(p=><option key={p.id} value={p.id}>{p.seller_article} · {p.name}</option>)}
      </select></td><td><button disabled={attentionBusy} onClick={()=>void approveAttention(a)}>Подтвердить</button></td></tr>)}
      {!alerts.some(a=>a.status==="OPEN")&&<tr><td colSpan={6}>Нет открытых конфликтов. Нажми «Сверить карточки WB».</td></tr>}
      </tbody></table></div>
      <p>Подтверждение фиксирует связь nmID с товаром. Существующие продажи и снимки остатков не перезаписываются.</p>
    </section>}
    {tab==="catalog" && <>
    <div className="products-stats">
      <div><span>Всего</span><b>{stats.total}</b></div><div><span>В реестре остатков</span><b>{stats.active}</b></div><div><span>WB</span><b>{stats.wb}</b></div><div><span>Ozon</span><b>{stats.ozon}</b></div><div><span>ЯМаркет</span><b>{stats.yandex}</b></div>
    </div>
    <div className="products-toolbar"><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Поиск по названию, артикулу или ШК"/><CustomSelect
        className="filter-select"
        ariaLabel="Фильтр по маркетплейсу"
        value={mp}
        onChange={value => setMp(value as "ALL" | MP)}
        options={[
          {value:"ALL",label:"Все маркетплейсы"},
          {value:"WB",label:"WB"},
          {value:"OZON",label:"Ozon"},
          {value:"YANDEX",label:"ЯМаркет"},
        ]}
      /><CustomSelect
        className="filter-select"
        ariaLabel="Фильтр по статусу"
        value={statusFilter}
        onChange={value => setStatusFilter(value as "ALL" | ProductStatus)}
        options={[
          {value:"ALL",label:"Все статусы"},
          {value:"SELLING",label:"Продается"},
          {value:"READY",label:"Готовится"},
          {value:"ARCHIVE",label:"Архив"},
        ]}
      /><span>Показано: {filtered.length}</span></div>
    {message&&<div className="products-message">{message}</div>}
    <div className="products-table-wrap"><table className="products-table"><thead><tr><th className="product-col-name">Товар</th><th>Статус</th><th>Артикул</th><th>Себестоимость</th><th>Габариты</th><th>Объём</th><th>МП</th></tr></thead><tbody>
      {filtered.map(p=><tr key={p.id}>
        <td className="product-name-cell">
          <div className="product-name-wrap">
            <button
              className="product-menu-trigger"
              onClick={(e)=>openProductMenu(e,p.id)}
              aria-label={`Действия: ${p.name||p.seller_article}`}
            >⋮</button>
            {menuId===p.id&&menuPosition&&createPortal(<div className="product-actions-menu product-actions-menu-portal" style={{top:menuPosition.top,left:menuPosition.left}} onClick={e=>e.stopPropagation()} onMouseDown={e=>e.stopPropagation()}>
              <button onClick={()=>{setEconomy(p);setMenuId(null)}}>Unit - экономика</button>
              <button onClick={()=>{openEdit(p);setMenuId(null)}}>Изменить</button>
              <button onClick={()=>{setCard(p);setCardMp(mps(p)[0]||"WB");setMenuId(null)}}>Добавить на МП</button>
              <button className="danger" onClick={()=>{setMenuId(null);void remove(p)}}>Удалить</button>
            </div>,document.body)}
            <div className="product-title-block">
              <strong>{p.name||"Без названия"}</strong>
            </div>
          </div>
        </td>
        <td>
          <span className={`product-status product-status-${(p.status || (p.active ? "SELLING" : "READY")).toLowerCase()}`}>
            {(p.status || (p.active ? "SELLING" : "READY"))==="SELLING"?"Продается":(p.status || (p.active ? "SELLING" : "READY"))==="ARCHIVE"?"Архив":"Готовится"}
          </span>
        </td>
        <td className="product-article-cell">{p.seller_article}</td>
        <td className="product-cost-cell"><strong>{money(p.final_cost)} ₽</strong></td>
        <td>
          <span className={dimensionsMissing(p)?"dimensions-missing":"dimensions-value"}>
            {dimensionsMissing(p)?"Не указаны":`${n(p.length_cm)} × ${n(p.width_cm)} × ${n(p.height_cm)} см`}
          </span>
        </td>
        <td className="product-volume-cell">{p.volume_liters!=null?`${n(p.volume_liters)} л`:"-"}</td>
        <td><div className="chips">{mps(p).map(x=><span key={x}>{x==="YANDEX"?"ЯМ":x}</span>)}{!mps(p).length&&<small>Не выбраны</small>}</div></td>
      </tr>)}
      {!filtered.length&&<tr><td colSpan={7} className="empty">Товары не найдены</td></tr>}
    </tbody></table></div>

    </>}
    {importVisible&&<div className="modal-bg catalog-sync-overlay" onMouseDown={()=>!importLoading&&setImportVisible(false)}>
      <div className="catalog-sync-dialog" role="dialog" aria-modal="true" aria-labelledby="catalog-sync-heading" onMouseDown={e=>e.stopPropagation()}>
        <header className="catalog-sync-head">
          <div><div className="products-eyebrow">МАРКЕТПЛЕЙСЫ / КАТАЛОГ</div><h2 id="catalog-sync-heading">Синхронизация товаров</h2>
            <p>Просмотр карточек и безопасное добавление в общий каталог</p></div>
          <button type="button" className="close" aria-label="Закрыть окно" onClick={()=>setImportVisible(false)} disabled={importLoading}>×</button>
        </header>
        <div className="catalog-sync-toolbar">
          <div className="catalog-sync-market-tabs" role="group" aria-label="Выберите маркетплейс">
            {(["WB","OZON","YANDEX"] as MP[]).map(m=><button type="button" key={m} className={importMarket===m?"is-active":""} aria-pressed={importMarket===m} disabled={importLoading}
              onClick={()=>{setImportMarket(m);setImportPreview(null);setImportSelected({});setImportTargets({});setImportResults([]);setImportSearch("");setImportError("")}}>{m==="YANDEX"?"Яндекс Маркет":m==="OZON"?"Ozon":"Wildberries"}</button>)}
          </div>
          <button type="button" className="products-primary catalog-sync-fetch" disabled={importLoading} onClick={()=>void runPreview(importMarket)}>{importLoading?"Загрузка карточек…":`Получить карточки`}</button>
        </div>
        <div className="catalog-sync-note"><span aria-hidden="true">ⓘ</span><span>Сначала просматриваем карточки. Новые товары создаются со статусом «Готовится» и не включаются в реестр остатков. Ручные данные существующих товаров не перезаписываются.</span></div>
        {importError&&<div className="catalog-sync-error" role="alert">{importError}</div>}
        {!!importResults.length&&<details className="catalog-sync-results"><summary>Результат последнего импорта ({importResults.length})</summary><div>{importResults.map((s,i)=><div key={i}>{s}</div>)}</div></details>}
        {importPreview ? <>
          <div className="catalog-sync-summary" role="status">
            <div><span>Карточек</span><strong>{importPreview.total}</strong></div>
            <div><span>Новые</span><strong>{importPreview.summary.NEW||0}</strong></div>
            <div><span>Найден товар</span><strong>{importPreview.summary.MATCH||0}</strong></div>
            <div><span>Связаны</span><strong>{importPreview.summary.LINKED||0}</strong></div>
            <div><span>Конфликты</span><strong>{importPreview.summary.CONFLICT||0}</strong></div>
          </div>
          <div className="catalog-sync-filters"><label htmlFor="catalog-sync-search">Поиск по карточкам</label><input id="catalog-sync-search" placeholder="Артикул или название товара" value={importSearch} onChange={e=>setImportSearch(e.target.value)}/>
            <span>Отмечено: <b>{importPreview.items.filter(c=>importSelected[c.external_id]&&c.status!=="LINKED"&&c.status!=="CONFLICT").length}</b></span>
          </div>
          <div className="catalog-sync-scroll" role="region" aria-label="Карточки для импорта" tabIndex={0}>
            <table className="catalog-sync-table"><thead><tr><th className="catalog-sync-check">Выбор</th><th>Маркетплейс / ID</th><th>Артикул</th><th>Наименование</th><th>Штрихкоды</th><th>Габариты, см</th><th>Связь с общим товаром</th><th>Статус</th></tr></thead><tbody>
              {importPreview.items.filter(c=>`${c.article} ${c.name}`.toLowerCase().includes(importSearch.toLowerCase())).map(c=><tr key={c.external_id}>
                <td className="catalog-sync-check"><input type="checkbox" aria-label={`Выбрать ${c.article}`} disabled={importLoading||c.status==="LINKED"||c.status==="CONFLICT"} checked={!!importSelected[c.external_id]} onChange={e=>setImportSelected(s=>({...s,[c.external_id]:e.target.checked}))}/></td>
                <td><span className="catalog-sync-mp">{c.marketplace==="YANDEX"?"Я.Маркет":c.marketplace==="OZON"?"Ozon":"WB"}</span><span className="catalog-sync-muted">{c.external_id}</span>{Object.entries(c.platform_ids).filter(([,v])=>!!v&&v!==c.external_id).map(([k,v])=><span className="catalog-sync-muted" key={k}>{k}: {v}</span>)}</td>
                <td className="catalog-sync-article">{c.article}</td><td className="catalog-sync-name">{c.name||"—"}</td><td className="catalog-sync-muted">{c.barcodes.join(", ")||"—"}</td>
                <td className="catalog-sync-dims">{c.dimensions?`${c.dimensions.length_cm} × ${c.dimensions.width_cm} × ${c.dimensions.height_cm}`:"—"}</td>
                <td>{c.status==="LINKED"?<span className="catalog-sync-muted">Связано с ID {c.master_id}</span>:c.status==="CONFLICT"?<span className="catalog-sync-muted">Проверить в «Требует внимания»</span>:
                  <select aria-label={`Связь с общим товаром для ${c.article}`} value={importTargets[c.external_id]||""}
                    onChange={e=>setImportTargets(a=>({...a,[c.external_id]:e.target.value}))}>
                    <option value="">Создать / найти по артикулу</option>
                    {products.map(p=><option key={p.id} value={p.id}>{p.seller_article} · {p.name}</option>)}
                  </select>}</td>
                <td><span className={`catalog-sync-status catalog-sync-status-${c.status.toLowerCase()}`}>{c.status==="NEW"?"Новый":c.status==="MATCH"?"Найден товар":c.status==="LINKED"?"Связан":"Конфликт"}</span></td>
              </tr>)}
              {!importPreview.items.some(c=>`${c.article} ${c.name}`.toLowerCase().includes(importSearch.toLowerCase()))&&<tr><td colSpan={8} className="catalog-sync-empty">По запросу карточки не найдены</td></tr>}
            </tbody></table>
          </div>
          <footer className="catalog-sync-footer"><p>Конфликтующие карточки не импортируются автоматически. Существующие статусы, цены и ручные поля сохраняются.</p>
            <div><button type="button" className="catalog-sync-cancel" onClick={()=>setImportVisible(false)} disabled={importLoading}>Закрыть</button>
              <button type="button" className="products-primary" disabled={importLoading||!importPreview.items.some(c=>importSelected[c.external_id]&&c.status!=="LINKED"&&c.status!=="CONFLICT")} onClick={()=>void importSelectedCards()}>Импортировать выбранные</button></div></footer>
        </> : <div className="catalog-sync-empty-state"><strong>Карточки ещё не загружены</strong><p>Выбери маркетплейс и нажми «Получить карточки», чтобы увидеть товары перед импортом.</p></div>}
      </div>
    </div>}
    {modal&&<div className="modal-bg" onMouseDown={()=>!saving&&setModal(false)}><div className="modal" onMouseDown={e=>e.stopPropagation()}><div className="modal-head"><div><div className="products-eyebrow">КАТАЛОГ</div><h2>{editing?"Изменить товар":"Новый товар"}</h2></div><button className="close" onClick={()=>setModal(false)}>×</button></div>
      <section><h3>Основные данные</h3><div className="form-grid"><label>Внутренний артикул<input value={form.internal_article} onChange={e=>setField("internal_article",e.target.value)}/></label><label>Артикул продавца<input value={form.seller_article} onChange={e=>setField("seller_article",e.target.value)}/></label><label className="wide">Название<input value={form.name} onChange={e=>setField("name",e.target.value)}/></label><label>ШК / баркод<input value={form.barcode} onChange={e=>setField("barcode",e.target.value)}/></label><label>Группа 1С
        <CustomSelect
          className="form-select"
          ariaLabel="Группа 1С"
          value={form.group}
          onChange={value=>setField("group",value)}
          options={[
            {value:"Маркетплейс",label:"Маркетплейс"},
            {value:"Готовая продукция",label:"Готовая продукция"},
          ]}
        />
      </label><label>Статус
        <CustomSelect
          className="form-select"
          ariaLabel="Статус товара"
          value={form.status}
          onChange={value=>setField("status",value)}
          options={[
            {value:"READY",label:"Готовится"},
            {value:"SELLING",label:"Продается"},
            {value:"ARCHIVE",label:"Архив"},
          ]}
        />
      </label></div></section>
      {editing&&<section><h3>Карточки на маркетплейсах</h3><p>Подтверждённые идентификаторы карточек. Артикул из МП может отличаться от внутреннего.</p>
        {marketCards.length?marketCards.map(c=><div key={c.marketplace+":"+c.external_id} style={{marginBottom:6}}><b>{c.marketplace}</b>: {c.seller_article} · ID {c.external_id}
          {Object.entries(c.platform_ids).filter(([k,v])=>!!v&&!(k==="nmID"&&v===c.external_id)).map(([k,v])=><span key={k}> · {k}: {v}</span>)}
          <div style={{fontSize:12}}>{c.title||""} · ШК: {c.barcode||"—"} · Габариты: {c.dimensions?`${c.dimensions.length_cm} × ${c.dimensions.width_cm} × ${c.dimensions.height_cm} см`:"нет подтверждённых данных"}</div></div>):<p>Нет подтверждённых связей. Используй «Синхронизировать товары».</p>}</section>}
      <section><h3>Себестоимость</h3><div className="form-grid"><label>Закупочная цена, ₽<input type="number" min="0" step="0.01" value={form.purchase_price} onChange={e=>setField("purchase_price",e.target.value)}/></label><label>Доп. затраты, ₽ / ед.<input type="number" min="0" step="0.01" value={form.additional_costs} onChange={e=>setField("additional_costs",e.target.value)}/></label></div></section>
      <section><h3>Габариты, см</h3><div className="form-grid three"><label>Длина<input type="number" min="0" step="0.01" value={form.length_cm} onChange={e=>setField("length_cm",e.target.value)}/></label><label>Ширина<input type="number" min="0" step="0.01" value={form.width_cm} onChange={e=>setField("width_cm",e.target.value)}/></label><label>Высота<input type="number" min="0" step="0.01" value={form.height_cm} onChange={e=>setField("height_cm",e.target.value)}/></label></div><div className="hint">Объём рассчитывается автоматически как Д × Ш × В.</div></section>
      <section><h3>Маркетплейсы</h3><div className="checks"><label><input type="checkbox" checked={form.wb_enabled} onChange={e=>setField("wb_enabled",e.target.checked)}/> WB</label><label><input type="checkbox" checked={form.ozon_enabled} onChange={e=>setField("ozon_enabled",e.target.checked)}/> Ozon</label><label><input type="checkbox" checked={form.yandex_enabled} onChange={e=>setField("yandex_enabled",e.target.checked)}/> ЯМаркет</label></div></section>
      <section className="registry-toggle"><label><input type="checkbox" checked={form.active} onChange={e=>setField("active",e.target.checked)}/><span><b>Включить в Реестр остатков</b><small>Новый товар лучше включать после появления его артикула в 1С.</small></span></label></section>
      <div className="modal-foot"><button onClick={()=>setModal(false)} disabled={saving}>Отмена</button><button className="products-primary" onClick={()=>void save()} disabled={saving}>{saving?"Сохранение…":"Сохранить"}</button></div>
    </div></div>}

    {economy&&<div className="modal-bg" onMouseDown={()=>setEconomy(null)}><div className="small-modal" onMouseDown={e=>e.stopPropagation()}><button className="close" onClick={()=>setEconomy(null)}>×</button><div className="products-eyebrow">ЗАГЛУШКА</div><h2>Unit-экономика</h2><p>Расчёт по WB, Ozon и ЯМаркет подключим следующим этапом.</p><div className="placeholder-card"><b>{economy.name}</b><span>Текущая себестоимость: {money(economy.final_cost)} ₽ / ед.</span></div><button onClick={()=>setEconomy(null)}>Закрыть</button></div></div>}

    {card&&<div className="modal-bg" onMouseDown={()=>setCard(null)}><div className="small-modal" onMouseDown={e=>e.stopPropagation()}><button className="close" onClick={()=>setCard(null)}>×</button><div className="products-eyebrow">ЗАГЛУШКА</div><h2>Добавить товар на МП</h2><p>Подготовка данных для создания карточки по API.</p><CustomSelect
        className="form-select"
        ariaLabel="Маркетплейс"
        value={cardMp}
        onChange={value => setCardMp(value as MP)}
        options={(mps(card).length ? mps(card) : ["WB" as MP]).map(x=>({
          value:x,
          label:x==="YANDEX"?"Яндекс Маркет":x
        }))}
      /><div className="placeholder-card"><b>{card.name}</b><span>Маркетплейс: {cardMp==="YANDEX"?"Яндекс Маркет":cardMp}</span></div><button disabled>Создать карточку — скоро</button></div></div>}
  </div>;
}
export default MasterProducts;
