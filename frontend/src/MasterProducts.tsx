import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./MasterProducts.css";

interface ImportCard { marketplace:MP; external_id:string; article:string; name:string;
  barcodes:string[]; dimensions:{length_cm:number;width_cm:number;height_cm:number}|null;
  platform_ids:Record<string,string>; status:"NEW"|"MATCH"|"LINKED"|"CONFLICT";
  master_id:number|null; suggested_master_id:number|null; conflict_reason?:string|null;
  dimension_fetch_status?:string; dimension_source?:string|null; dimension_check?:string; catalog_dimensions?:{length_cm:number|null;width_cm:number|null;height_cm:number|null}|null;
  catalog_barcode?:string|null; catalog_name?:string|null; barcode_check?:"SAME"|"DIFFERENT"|"MISSING_IN_CATALOG"|"MISSING_ON_OZON"|"UNRESOLVED"; }
interface ImportPreview { marketplace:MP; total:number; items:ImportCard[];
  summary:Record<string,number>; barcode_summary?:Record<string,number>|null; dimension_summary?:Record<string,number>|null; read_only:boolean; }
interface AttentionItem { id:number; marketplace:string; nm_id:string; article:string;
  old_article:string|null; reason:string; status:string; title:string|null; master_id:number|null; }
interface BulkLinkRow {nm_id:string;article:string;master_id:number;master_name:string;wb_title:string;local_product_id:number;}
interface BulkLinkPreview {proposals:BulkLinkRow[];skipped:{nm_id:string;article:string;reason:string}[];fingerprint:string;read_only:boolean;}
interface BarcodeAlert {nm_id:string;article:string;master_id:number;title:string;catalog_barcode:string;wb_barcodes:string[];problem:string;}
interface BarcodePreview {master_id:number;nm_id:string;article:string;catalog_barcode:string;wb_barcodes:string[];new_barcode:string;fingerprint:string;}
interface DimensionFillChange {field:string;old_cm:number|null;new_cm:number;}
interface DimensionProblem { code:string;field:string;field_label:string;catalog_cm:number|null;marketplace_cm:number|null; }
interface DimensionAlert { marketplace:string; nm_id:string; article:string;title:string;master_id:number;problems:DimensionProblem[]; catalog_dimensions:Record<DimensionKey,number|null>;marketplace_dimensions:Record<DimensionKey,number|null>; }
type DimensionKey="length_cm"|"width_cm"|"height_cm";
interface ManualPreview {master_id:number;nm_id:string;article:string;catalog:Record<DimensionKey,number|null>;wb:Record<DimensionKey,number|null>;changes:DimensionFillChange[];fingerprint:string;}
const dimensionKeys:DimensionKey[]=["length_cm","width_cm","height_cm"];
const dimensionLabels:Record<DimensionKey,string>={length_cm:"Длина",width_cm:"Ширина",height_cm:"Высота"};
type MP = "WB" | "OZON" | "YANDEX";
interface MpSnapshotCard {marketplace:string;external_id:string;confirmed:boolean;seller_article:string|null;title:string|null;description:string|null;barcodes:string[];platform_ids:Record<string,string>;dimensions:{length:number|null;width:number|null;height:number|null;unit:string|null;normalized_cm:(number|null)[];state:string};checked_at:string|null;}
interface ProductMarketplaceDetails {product:Product;marketplace_cards:MpSnapshotCard[];}
interface MarketplaceDimensionIssue {master_id:number|null;article:string;title:string|null;marketplace:string;external_id:string;confirmed:boolean;problems:{code:string;label:string;preliminary?:boolean;fingerprint?:string;decision?:string}[];catalog_cm:(number|null)[];marketplace_cm:(number|null)[];checked_at:string|null;}
type AttentionProblemEntry =
  | {kind:"identity"; data:AttentionItem}
  | {kind:"wb-dimensions";data:DimensionAlert}
  | {kind:"wb-barcode";data:BarcodeAlert}
  | {kind:"snapshot";data:MarketplaceDimensionIssue; code:string;label:string; preliminary:boolean};
interface AttentionGroup {key:string;article:string;title:string;masterId:number|null;entries:AttentionProblemEntry[];}
type SnapshotDimensionProblem = MarketplaceDimensionIssue["problems"][number];

const formatDimensions=(values:(number|null|undefined)[])=>values.map(v=>v==null?"—":Number(v).toLocaleString("ru-RU",{maximumFractionDigits:2})).join(" × ");
const snapshotComparison=(catalog:(number|null)[], c:MpSnapshotCard)=>{
  const state=c.dimensions.state;
  if(state==="UNKNOWN"||state==="API_ERROR"||state==="INVALID_UNIT")return {label:"Размеры не проверены",description:"Нет достоверных данных последней проверки. Это не подтверждённое отсутствие размеров.",kind:"neutral"};
  const remote=c.dimensions.normalized_cm;
  if(!dimensionsComplete(remote))return {label:"Нет габаритов на МП",description:"В снимке площадки отсутствует один или несколько размеров упаковки.",kind:"warning"};
  if(!dimensionsComplete(catalog))return {label:"Нет габаритов в каталоге",description:"На площадке размеры есть, но в нашем каталоге часть полей пуста.",kind:"warning"};
  if(remote.some((v,i)=>Math.abs(Number(v)-Number(catalog[i]))>0.05))return {label:"Габариты отличаются",description:`Каталог: ${formatDimensions(catalog)} см. ${mpNames[c.marketplace as MP]||c.marketplace}: ${formatDimensions(remote)} см. Данные не изменялись.`,kind:"warning"};
  return {label:"Габариты совпадают",description:"Нормализованные размеры совпадают с каталогом.",kind:"success"};
};

type DimensionCompleteness = "complete"|"partial"|"empty";
const mpNames:Record<MP,string>={WB:"Wildberries",OZON:"Ozon",YANDEX:"Яндекс Маркет"};
const dimensionsComplete=(values:(number|null|undefined)[])=>values.length===3&&values.every(x=>x!=null&&Number(x)>0);
const naturalArticleCompare=(a:string,b:string)=>a.localeCompare(b,"ru",{numeric:true,sensitivity:"base"});

type ProductStatus = "READY" | "SELLING" | "ARCHIVE";
interface Product {
  id:number; sort_order:number; internal_article:string|null; internal_name:string|null; seller_article:string;
  barcode:string|null; name:string|null; group:string; purchase_price:number;
  additional_costs:number; final_cost:number; length_cm:number|null; width_cm:number|null;
  height_cm:number|null; volume_liters:number|null; wb_enabled:boolean; ozon_enabled:boolean;
  yandex_enabled:boolean; active:boolean; status?:ProductStatus|null;
}
interface Form { internal_article:string; internal_name:string; seller_article:string; barcode:string; name:string; group:string;
  purchase_price:string; additional_costs:string; length_cm:string; width_cm:string; height_cm:string;
  wb_enabled:boolean; ozon_enabled:boolean; yandex_enabled:boolean; active:boolean; status:ProductStatus; }
const API="http://127.0.0.1:8000";
const EMPTY:Form={internal_article:"",internal_name:"",seller_article:"",barcode:"",name:"",group:"Маркетплейс",purchase_price:"",additional_costs:"0",length_cm:"",width_cm:"",height_cm:"",wb_enabled:false,ozon_enabled:false,yandex_enabled:false,active:false,status:"READY"};
const IMPORT_CONFLICTS:Record<string,string>={
  IDENTITY_DISAGREEMENT:"Связи WB расходятся между реестрами. Нужна ручная проверка.",
  CONFIRMED_MASTER_MISSING:"Подтверждённая связь указывает на отсутствующий товар.",
  WB_ARTICLE_CHANGED:"Артикул на WB изменился после подтверждения связи.",
  IMPORTED_ARTICLE_CHANGED:"Артикул изменился после импорта.",
  DUPLICATE_CATALOG_ARTICLE:"В общем каталоге несколько товаров с этим артикулом.",
  ARTICLE_USED_BY_ANOTHER_CARD:"Артикул уже используется другой импортированной карточкой.",
  WB_ARTICLE_USED_BY_ANOTHER_CARD:"Артикул уже закреплён за другим nmID WB."
};
const ATTENTION_REASONS:Record<string,{label:string;description:string}> = {
  MISSING_LOCAL_CARD:{label:"Не завершено сопоставление",description:"Карточка найдена на Wildberries, но отсутствует локальная запись по nmID. Проверьте, есть ли товар в общем каталоге: можно связать существующий либо создать новый."},
  NO_MASTER_PRODUCT:{label:"Нет товара в общем каталоге",description:"Карточка WB найдена, но товар с этим артикулом отсутствует в общем справочнике."},
  DUPLICATE_NM_ID:{label:"Дублируется nmID",description:"В локальных карточках WB обнаружено несколько записей с одним nmID."},
  ARTICLE_COLLISION:{label:"Артикул занят другой карточкой",description:"Один артикул связан с другим nmID; требуется ручная проверка."},
  ARTICLE_CHANGED:{label:"Артикул изменён на WB",description:"У карточки с тем же nmID обнаружен новый артикул продавца."},
  RETIRED_ARTICLE_COLLISION:{label:"Старая карточка архивирована",description:"Старый nmID сохранён для истории; действующая карточка должна иметь отдельную связь."},
};
const attentionReason=(reason:string)=>ATTENTION_REASONS[reason]||{label:"Неизвестная проблема",description:`Код: ${reason}. Требуется проверка.`};
function ProblemHint({description}:{description:string}){
  const [position,setPosition]=useState<{top:number;left:number}|null>(null);
  const show=(target:HTMLElement)=>{
    const rect=target.getBoundingClientRect();
    setPosition({top:Math.max(8,Math.min(rect.top-18,window.innerHeight-100)),left:Math.max(8,Math.min(rect.right+12,window.innerWidth-308))});
  };
  return <span className="product-attention-hint">
    <button type="button" className="product-attention-hint-trigger" aria-label="Описание проблемы"
      aria-expanded={!!position} onMouseEnter={e=>show(e.currentTarget)} onMouseLeave={()=>setPosition(null)}
      onFocus={e=>show(e.currentTarget)} onBlur={()=>setPosition(null)}
      onClick={e=>{if(position)setPosition(null);else show(e.currentTarget);}}>i</button>
    {position&&createPortal(<span className="product-attention-hint-popup" role="tooltip" style={{position:"fixed",top:position.top,left:position.left,visibility:"visible",opacity:1}}>{description}</span>,document.body)}
  </span>;
}

type AppSelectOption={value:string;label:string};
function AppSelect({value,options,onChange,disabled=false,label}:{value:string;options:AppSelectOption[];onChange:(value:string)=>void;disabled?:boolean;label:string}){
  const [open,setOpen]=useState(false);
  const [position,setPosition]=useState<{top:number;left:number;width:number;up:boolean}|null>(null);
  const buttonRef=useRef<HTMLButtonElement>(null);
  const menuRef=useRef<HTMLDivElement>(null);
  const selected=options.find(option=>option.value===value)?.label||"Выбрать";
  const show=()=>{
    if(disabled)return;
    if(open){setOpen(false);return;}
    const rect=buttonRef.current?.getBoundingClientRect();
    if(!rect)return;
    const spaceBelow=window.innerHeight-rect.bottom;
    const up=spaceBelow<Math.min(230,options.length*39+12)&&rect.top>spaceBelow;
    setPosition({left:Math.max(8,Math.min(rect.left,window.innerWidth-Math.max(rect.width,160)-8)),top:up?rect.top-6:rect.bottom+6,width:rect.width,up});
    setOpen(true);
  };
  useEffect(()=>{
    if(!open)return;
    const dismiss=(event:MouseEvent)=>{
      if(!buttonRef.current?.contains(event.target as Node)&&!menuRef.current?.contains(event.target as Node))setOpen(false);
    };
    const keyboard=(event:KeyboardEvent)=>{if(event.key==="Escape"){setOpen(false);buttonRef.current?.focus();}};
    const scroll=(event:Event)=>{if(menuRef.current?.contains(event.target as Node))return;setOpen(false);};
    document.addEventListener("mousedown",dismiss);
    document.addEventListener("keydown",keyboard);
    window.addEventListener("resize",scroll);
    window.addEventListener("scroll",scroll,true);
    return ()=>{document.removeEventListener("mousedown",dismiss);document.removeEventListener("keydown",keyboard);window.removeEventListener("resize",scroll);window.removeEventListener("scroll",scroll,true);};
  },[open]);
  return <>
    <button ref={buttonRef} type="button" className={`catalog-app-select${open?" is-open":""}`} aria-label={label} aria-expanded={open} aria-haspopup="listbox" disabled={disabled} onClick={show}>
      <span>{selected}</span><svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round"/></svg>
    </button>
    {open&&position&&createPortal(<div ref={menuRef} role="listbox" aria-label={label} className="catalog-app-select-menu" onMouseDown={e=>e.stopPropagation()} style={{position:"fixed",left:position.left,width:Math.max(160,position.width),...(position.up?{bottom:window.innerHeight-position.top}:{top:position.top})}}>
      {options.map(option=><button type="button" role="option" aria-selected={option.value===value} key={option.value} className={option.value===value?"selected":""} onClick={()=>{onChange(option.value);setOpen(false);buttonRef.current?.focus();}}>{option.label}{option.value===value&&<span aria-hidden="true">✓</span>}</button>)}
    </div>,document.body)}
  </>;
}

const money=(n:number)=>new Intl.NumberFormat("ru-RU",{minimumFractionDigits:2,maximumFractionDigits:2}).format(n);
const n=(v:number|null)=>v==null?"—":new Intl.NumberFormat("ru-RU",{maximumFractionDigits:2}).format(v);
const formOf=(p:Product):Form=>({internal_article:p.internal_article||"",internal_name:p.internal_name||"",seller_article:p.seller_article||"",barcode:p.barcode||"",name:p.name||"",group:p.group||"Маркетплейс",purchase_price:String(p.purchase_price??""),additional_costs:String(p.additional_costs??0),length_cm:p.length_cm==null?"":String(p.length_cm),width_cm:p.width_cm==null?"":String(p.width_cm),height_cm:p.height_cm==null?"":String(p.height_cm),wb_enabled:p.wb_enabled,ozon_enabled:p.ozon_enabled,yandex_enabled:p.yandex_enabled,active:p.active,status:p.status || (p.active ? "SELLING" : "READY")});


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
  const [confirmation,setConfirmation]=useState<{title:string;message:string;confirmLabel:string;danger?:boolean}|null>(null);
  const confirmationResolver=useRef<((value:boolean)=>void)|null>(null);
  const requestConfirmation=(title:string,message:string,confirmLabel="Подтвердить",danger=false):Promise<boolean>=>{
    // Never leave a pending confirmation unresolved if another one is requested.
    confirmationResolver.current?.(false);
    return new Promise(resolve=>{
      confirmationResolver.current=resolve;
      setConfirmation({title,message,confirmLabel,danger});
    });
  };
  const finishConfirmation=(approved:boolean)=>{
    const resolve=confirmationResolver.current;
    confirmationResolver.current=null;
    setConfirmation(null);
    resolve?.(approved);
  };
  useEffect(()=>()=>{confirmationResolver.current?.(false);confirmationResolver.current=null;},[]);
  const [attentionExplanation,setAttentionExplanation]=useState<AttentionItem|null>(null);
  const [importVisible,setImportVisible]=useState(false);
  const [importMarket,setImportMarket]=useState<MP>("WB");
  const [manualImportOpen,setManualImportOpen]=useState(false);
  const [importPreview,setImportPreview]=useState<ImportPreview|null>(null);
  const [importLoading,setImportLoading]=useState(false);
  const [importError,setImportError]=useState("");
  const [importSearch,setImportSearch]=useState("");
  const [importSelected,setImportSelected]=useState<Record<string,boolean>>({});
  const [importTargets,setImportTargets]=useState<Record<string,string>>({});
  const [importResults,setImportResults]=useState<string[]>([]);
  type SyncResult23={marketplaces:{marketplace:string;status:string;received?:number;changed?:number;skipped_api_errors?:number;reason?:string}[];skipped:{marketplace:string;reason:string}[];mode:string};
  const [unifiedSyncResult,setUnifiedSyncResult]=useState<SyncResult23|null>(null);
  const [unifiedSyncBusy,setUnifiedSyncBusy]=useState(false);
  type CatalogMatchSettings={match_by:"ARTICLE"|"BARCODE";auto_enabled:boolean;timezone:string;times:string[];scheduler_active:boolean};
  type AutoExclusionCategory="ALREADY_LINKED"|"NEW_PRODUCT"|"NEEDS_REVIEW";
  type CatalogAutoPreview={match_by:"ARTICLE"|"BARCODE";marketplaces:string[];received:Record<string,number>;failed:string[];skipped:{marketplace:string;reason:string}[];can_apply:boolean;proposals:{marketplace:string;external_id:string;article:string;master_id:number;master_article:string;master_name:string;remote_name:string;barcodes:string[]}[];excluded:{marketplace:string;external_id:string;article:string;reason:string}[];excluded_details:{marketplace:string;external_id:string;article:string;reason:string;category:AutoExclusionCategory}[];by_marketplace:Record<string,{received:number|null;new_links:number;already_linked:number;new_products:number;needs_review:number;api_error:boolean}>;operation_count:number;fingerprint:string|null;read_only:boolean};
  const autoExclusionReasons:Record<string,string>={
    MISSING_EXTERNAL_ID_OR_ARTICLE:"Нет внешнего ID или артикула",
    DUPLICATE_REMOTE_EXTERNAL_ID:"Повтор внешнего ID на площадке",
    ALREADY_LINKED:"Связь уже подтверждена",
    PREVIOUSLY_DISMISSED:"Ранее отклонено пользователем",
    ARTICLE_ALREADY_LINKED:"Артикул уже связан с другой карточкой этого МП",
    DUPLICATE_REMOTE_ARTICLE:"Несколько карточек МП с этим артикулом",
    NO_UNIQUE_CATALOG_ARTICLE:"Нет единственного товара по артикулу в каталоге",
    NO_UNIQUE_CATALOG_BARCODE:"Нет единственного товара по штрихкоду в каталоге",
    BARCODE_SHARED_BY_REMOTE_CARDS:"Один штрихкод используется несколькими карточками МП",
    ARTICLE_BARCODE_DISAGREEMENT:"Артикул и штрихкод указывают на разные товары",
    TARGET_ALREADY_LINKED_ON_MARKETPLACE:"Этот товар уже связан с другой карточкой этого МП",
    WB_LOCAL_CARD_MISSING_OR_CONFLICT:"Локальная карточка WB отсутствует или противоречит данным WB",
    DUPLICATE_TARGET_MASTER:"Несколько карточек МП претендуют на один товар",
  };
  const [matchSettings,setMatchSettings]=useState<CatalogMatchSettings|null>(null);
  const [matchSettingsOpen,setMatchSettingsOpen]=useState(false);
  const [matchBusy,setMatchBusy]=useState(false);
  const [autoPreview,setAutoPreview]=useState<CatalogAutoPreview|null>(null);
  const [autoApplyResult,setAutoApplyResult]=useState("");
  const [autoPreviewSearch,setAutoPreviewSearch]=useState("");
  const [autoMarketFilter,setAutoMarketFilter]=useState<"ALL"|MP>("ALL");
  const [autoPreviewTab,setAutoPreviewTab]=useState<"links"|"already"|"new"|"review">("links");
  const [matchError,setMatchError]=useState("");
  const loadMatchSettings=async()=>{
    try{const data=await readResponse(await fetch(`${API}/catalog-import/matching-settings`,{cache:"no-store"}));setMatchSettings(data as CatalogMatchSettings)}
    catch(e){setMatchError(e instanceof Error?e.message:"Не удалось получить настройки")}
  };
  const saveMatchSettings=async()=>{
    if(!matchSettings)return;
    setMatchBusy(true);setMatchError("");
    try{
      const result=await readResponse(await fetch(`${API}/catalog-import/matching-settings`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(matchSettings)}));
      setMatchSettings(result as CatalogMatchSettings);setAutoPreview(null);setMatchSettingsOpen(false);
    }catch(e){setMatchError(e instanceof Error?e.message:"Не удалось сохранить настройки")}
    finally{setMatchBusy(false)}
  };
  const previewAllMarkets=async()=>{
    setMatchBusy(true);setMatchError("");setAutoApplyResult("");setAutoPreview(null);setMassConfirmOpen(false);setMassAcknowledged(false);setAutoPreviewSearch("");setAutoPreviewTab("links");setAutoMarketFilter("ALL");
    try{setAutoPreview(await readResponse(await fetch(`${API}/catalog-import/auto-preview`,{cache:"no-store"})) as CatalogAutoPreview)}
    catch(e){setMatchError(e instanceof Error?e.message:"Не удалось проверить кандидатов")}
    finally{setMatchBusy(false)}
  };
  const [massConfirmOpen,setMassConfirmOpen]=useState(false);
  const [massAcknowledged,setMassAcknowledged]=useState(false);
  const applyAllMarkets=async()=>{
    if(!autoPreview||!autoPreview.can_apply||!autoPreview.fingerprint||!autoPreview.proposals.length)return;
    if(!massAcknowledged)return;
    setMassConfirmOpen(false);setMassAcknowledged(false);
    setMatchBusy(true);setMatchError("");
    try{
      const result=await readResponse(await fetch(`${API}/catalog-import/auto-apply`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({fingerprint:autoPreview.fingerprint,match_by:autoPreview.match_by})}));
      setAutoApplyResult(`Создано подтверждённых связей: ${result.linked} (${Object.entries(result.by_marketplace||{}).map(([m,n])=>`${m}: ${n}`).join(", ")})`);setAutoPreview(null);
      try{await load();await refreshMpDimensionIssues();}
      catch{setAutoApplyResult(v=>`${v}. Для обновления списка перезагрузите страницу.`)}
      // No additional marketplace fetch here: a transient API error after a
      // successful commit must not be presented as a failed confirmation.
    }catch(e){setMatchError(e instanceof Error?e.message:"Массовое сопоставление не выполнено")}
    finally{setMatchBusy(false)}
  };


  // Generic catalog creation flow. The source marketplace is a parameter,
  // not a WB-specific creation path; other marketplaces use the same importer.
  const [createFromCard,setCreateFromCard]=useState<ImportCard|null>(null);
  const [createBusy,setCreateBusy]=useState(false);
  const [createError,setCreateError]=useState("");
  const [createLoading,setCreateLoading]=useState(false);
  const [,setCreateCheckingId]=useState<string|null>(null);
  const [marketCards,setMarketCards]=useState<{marketplace:string;external_id:string;seller_article:string;title:string|null;barcode:string|null;dimensions:{length_cm:number;width_cm:number;height_cm:number}|null;platform_ids:Record<string,string>}[]>([]);
  const [marketDetails,setMarketDetails]=useState<MpSnapshotCard[]>([]);
  const [marketDetailsLoading,setMarketDetailsLoading]=useState(false);
  const [mpDimensionIssues,setMpDimensionIssues]=useState<MarketplaceDimensionIssue[]>([]);
  const [mpDimensionIssuesError,setMpDimensionIssuesError]=useState("");
  const [dimensionDecisionTarget,setDimensionDecisionTarget]=useState<{issue:MarketplaceDimensionIssue;problem:SnapshotDimensionProblem}|null>(null);
  const [dimensionDecisionBusy,setDimensionDecisionBusy]=useState(false);
  const [dimensionDecisionError,setDimensionDecisionError]=useState("");
  const refreshMpDimensionIssues=async()=>{
    try{
      const r=await fetch(`${API}/master-products/marketplace-dimension-issues`,{cache:"no-store"});
      if(!r.ok)throw Error(`HTTP ${r.status}`);
      const data=await r.json();
      setMpDimensionIssues(Array.isArray(data.issues)?data.issues:[]);
      setMpDimensionIssuesError("");
    }catch(e){setMpDimensionIssuesError(e instanceof Error?e.message:"Ошибка проверки МП");}
  };

  const [overview,setOverview]=useState<Record<string,MpSnapshotCard[]>>({});
  const readResponse=async(r:Response)=>{
    const raw=await r.text();let value:any=null;
    try{value=JSON.parse(raw)}catch{throw Error(`Сервер вернул HTTP ${r.status}. Проверь журнал backend.`)}
    if(!r.ok)throw Error(typeof value.detail==="string"?value.detail:`HTTP ${r.status}`);
    return value;
  };
  const runUnifiedSync=async()=>{
    setImportVisible(true);setManualImportOpen(false);setImportPreview(null);setImportResults([]);setImportError("");
    setUnifiedSyncResult(null);setUnifiedSyncBusy(true);
    void loadMatchSettings();
    try{
      const response=await readResponse(await fetch(`${API}/catalog-import/sync-connected`,{method:"POST"}));
      setUnifiedSyncResult(response as SyncResult23);
      // Refresh snapshots and the read-only problem queue after a completed sync.
      await load();
      await refreshMpDimensionIssues();
    }catch(e){setImportError(e instanceof Error?e.message:"Ошибка синхронизации");}
    finally{setUnifiedSyncBusy(false);}
  };
  const runPreview=async(market:MP)=>{
    setManualImportOpen(true);setImportMarket(market);setImportLoading(true);setImportError("");setImportSelected({});setImportTargets({});setImportPreview(null);
    try{setImportPreview(await readResponse(await fetch(`${API}/catalog-import/${market}/preview`)))}
    catch(e){setImportError(e instanceof Error?e.message:"Ошибка загрузки каталога")}
    finally{setImportLoading(false)}
  };
  const importSelectedCards=async()=>{
    if(!importPreview)return;
    const chosen=importPreview.items.filter(x=>importSelected[x.external_id] && x.status!=="LINKED" && x.status!=="CONFLICT");
    if(!chosen.length){setImportError("Отметьте карточки со статусом «Новый» или «Найден товар».");return}
    if(!await requestConfirmation("Подтверждение импорта",`Импортировать ${chosen.length} карточек ${importMarket}? Проверь выбранные связи. Новые товары будут «Готовится» и не попадут в реестр/OOS.`,"Импортировать"))return;
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
  const [attentionSearch,setAttentionSearch]=useState("");
  const [attentionError,setAttentionError]=useState("");
  const [expandedAttention,setExpandedAttention]=useState<string|null>(null);
  const [dimensionAlerts,setDimensionAlerts]=useState<DimensionAlert[]>([]);
  const [barcodeAlerts,setBarcodeAlerts]=useState<BarcodeAlert[]>([]);
  const [barcodeDetail,setBarcodeDetail]=useState<BarcodeAlert|null>(null);
  const [barcodeValue,setBarcodeValue]=useState("");
  const [barcodePreview,setBarcodePreview]=useState<BarcodePreview|null>(null);
  const [barcodeBusy,setBarcodeBusy]=useState(false);
  const [barcodeError,setBarcodeError]=useState("");
  const [dimensionAudit,setDimensionAudit]=useState<{
    counts:Record<string,number>;
    excluded:{nm_id:string;article:string;reason:string;master_id:number|null}[];
  }|null>(null);
  const [showAuditExcluded,setShowAuditExcluded]=useState(false);
  const [bulkLinkPreview,setBulkLinkPreview]=useState<BulkLinkPreview|null>(null);
  const [bulkLinkSelected,setBulkLinkSelected]=useState<Record<string,boolean>>({});
  const [bulkLinkBusy,setBulkLinkBusy]=useState(false);
  const [bulkLinkError,setBulkLinkError]=useState("");
  const previewBulkLinks=async()=>{
    setBulkLinkBusy(true);setBulkLinkError("");
    try{
      const data=await readResponse(await fetch(`${API}/product-attention/bulk-links/preview`,{method:"POST"})) as BulkLinkPreview;
      if(!Array.isArray(data.proposals)||!Array.isArray(data.skipped)||!data.fingerprint)throw Error("Неверный ответ сервера");
      setBulkLinkPreview(data);setBulkLinkSelected({});
    }catch(e){setBulkLinkError(e instanceof Error?e.message:"Не удалось сопоставить карточки");}
    finally{setBulkLinkBusy(false);}
  };
  const applyBulkLinks=async()=>{
    if(!bulkLinkPreview||bulkLinkBusy)return;
    const selected=bulkLinkPreview.proposals.filter(p=>bulkLinkSelected[p.nm_id]).map(p=>p.nm_id);
    if(!selected.length)return;
    if(!await requestConfirmation("Подтвердить связи WB",`Будут созданы ${selected.length} подтверждённых связей nmID → товар. Ни размеры, ни названия, ни остатки не изменятся.`,"Подтвердить выбранные"))return;
    setBulkLinkBusy(true);setBulkLinkError("");
    try{
      const result=await readResponse(await fetch(`${API}/product-attention/bulk-links/apply`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({preview_fingerprint:bulkLinkPreview.fingerprint,selected_nm_ids:selected})}));
      setBulkLinkPreview(null);setBulkLinkSelected({});
      await scanAttention();
      setMessage(`Подтверждено связей WB: ${result.linked}. Выполнена новая сверка габаритов.`);
    }catch(e){setBulkLinkError(e instanceof Error?e.message:"Не удалось подтвердить связи");}
    finally{setBulkLinkBusy(false);}
  };

  const openCreateFromMarketplace=async(marketplace:MP,externalId:string,article:string)=>{
    setCreateCheckingId(`${marketplace}:${externalId}`);
    setCreateLoading(true);setCreateError("");setCreateFromCard(null);
    try{
      // Preview from the actual marketplace, never from stale review text.
      const data=await readResponse(await fetch(`${API}/catalog-import/${marketplace}/preview`)) as ImportPreview;
      const matching=data.items.filter(c=>c.external_id===externalId&&c.article===article);
      if(matching.length!==1)throw Error("Карточка изменилась или не найдена на площадке. Обновите сверку.");
      if(matching[0].status!=="NEW"){
        if(matching[0].status==="MATCH") {
          const existing=products.find(p=>p.id===matching[0].suggested_master_id);
          throw Error(`Товар ${existing?.seller_article||matching[0].article} уже есть в общем каталоге. Выберите его в списке «Связать с товаром» и нажмите «Подтвердить». Создание дубликата запрещено.`);
        }
        throw Error("У карточки уже есть подтверждённая связь или конфликт. Создание дубликата запрещено; проверьте сопоставление.");
      }
      if(!matching[0].article.trim())throw Error("У карточки нет артикула. Создание требует ручной проверки.");
      setCreateFromCard(matching[0]);
    }catch(e){setCreateError(e instanceof Error?e.message:"Не удалось проверить карточку");}
    finally{setCreateLoading(false);setCreateCheckingId(null);}
  };
  const confirmCreateFromMarketplace=async()=>{
    const card=createFromCard;
    if(!card||createBusy)return;
    setCreateBusy(true);setCreateError("");
    try{
      // Creation has its own endpoint: import-one returns `imported` and may
      // silently attach an existing master; create-one must return `created`.
      const result=await readResponse(await fetch(`${API}/catalog-import/${card.marketplace}/create-one`,{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({external_id:card.external_id,article:card.article,master_id:null})
      }));
      if(result.status!=="created"||!Number.isInteger(result.master_id)||result.master_id<=0){
        throw Error("Сервер не подтвердил создание товара. Проверьте каталог перед повторной попыткой.");
      }
      // The server committed the new master and marketplace link. Close the
      // dialog immediately; no subsequent UI refresh can undo that success.
      setCreateFromCard(null);
      setTab("catalog");
      setSearch("");setMp("ALL");setStatusFilter("ALL");
      let catalogUpdated=false;
      try{await load();catalogUpdated=true;}
      catch(e){setMessage(`Товар ${card.article} создан, но список не обновлён: ${e instanceof Error?e.message:"ошибка загрузки"}. Обновите страницу.`);}
      // Re-scan reconciles the previously open identity review and refreshes
      // attention counts. A scan failure is not a failed creation.
      try{await scanAttention();}
      catch{ /* scanAttention reports its error in attentionError */ }
      if(catalogUpdated){
        setMessage(`Товар ${card.article} успешно создан в каталоге. Статус «Готовится», реестр выключен.`);
      }
    }catch(e){setCreateError(e instanceof Error?e.message:"Не удалось создать товар");}
    finally{setCreateBusy(false);}
  };

  const [dimensionDetail,setDimensionDetail]=useState<DimensionAlert|null>(null);
  const [dimensionInputs,setDimensionInputs]=useState<Record<DimensionKey,string>>({length_cm:"",width_cm:"",height_cm:""});
  const [manualPreview,setManualPreview]=useState<ManualPreview|null>(null);
  const [wbPlaceholder,setWbPlaceholder]=useState(false);
  const openDimensionDetail=(alert:DimensionAlert)=>{
    setFillError("");setManualPreview(null);
    setDimensionInputs(Object.fromEntries(dimensionKeys.map(k=>[k,alert.catalog_dimensions?.[k]==null?"":String(alert.catalog_dimensions[k])])) as Record<DimensionKey,string>);
    setDimensionDetail(alert);
  };
  const parsedDimensions=()=>Object.fromEntries(dimensionKeys.map(k=>[k,Number(dimensionInputs[k].replace(",","."))])) as Record<DimensionKey,number>;
  const dimensionsValid=dimensionKeys.every(k=>{const raw=dimensionInputs[k].trim().replace(",",".");return raw!==""&&/^\d+(?:\.\d{1,2})?$/.test(raw)&&Number(raw)>0&&Number(raw)<=99999999.99;});
  const dimensionsChanged=!!dimensionDetail&&dimensionKeys.some(k=>dimensionInputs[k].trim()!==""&&Number(dimensionInputs[k].replace(",","."))!==dimensionDetail.catalog_dimensions?.[k]);
  const [fillBusy,setFillBusy]=useState(false);
  const [fillError,setFillError]=useState("");
  const [selectedMaster,setSelectedMaster]=useState<Record<number,string>>({});
  const loadAttention=async()=>{const r=await fetch(`${API}/product-attention`,{cache:"no-store"});if(!r.ok)throw Error(`Не удалось получить конфликты (${r.status})`);setAlerts(await r.json());setAttentionError("");};
  useEffect(()=>{void loadAttention().catch(e=>setAttentionError(e instanceof Error?e.message:"Ошибка загрузки конфликтов"));},[]);
  const scanAttention=async()=>{setAttentionBusy(true);setMessage("");try{
    const r=await fetch(`${API}/product-attention/scan`,{method:"POST"});if(!r.ok)throw Error(`Сверка WB не выполнена (${r.status})`);
    const x=await r.json();setDimensionAlerts(Array.isArray(x.dimensions_attention)?x.dimensions_attention:[]);setBarcodeAlerts(Array.isArray(x.barcode_attention)?x.barcode_attention:[]);setDimensionAudit(x.dimensions_audit&&x.dimensions_audit.counts&&Array.isArray(x.dimensions_audit.excluded)?x.dimensions_audit:null);
    setMessage(`Проверено карточек WB: ${x.scanned}; конфликты привязки: ${x.attention}; проблемы габаритов: ${(x.dimensions_attention||[]).length}; проблемы штрихкодов: ${(x.barcode_attention||[]).length}.`);await loadAttention();
  }catch(e){setAttentionError(e instanceof Error?e.message:"Ошибка сверки");}finally{setAttentionBusy(false);}};
  const openBarcodeDetail=(alert:BarcodeAlert)=>{
    setBarcodeDetail(alert);setBarcodePreview(null);setBarcodeError("");
    setBarcodeValue(alert.wb_barcodes.length===1?alert.wb_barcodes[0]:"");
  };
  const previewBarcode=async()=>{
    if(!barcodeDetail||!barcodeValue)return;
    setBarcodeBusy(true);setBarcodeError("");
    try{
      const data=await readResponse(await fetch(`${API}/product-attention/barcode/item/preview`,{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({master_id:barcodeDetail.master_id,nm_id:barcodeDetail.nm_id,barcode:barcodeValue})}));
      setBarcodePreview(data as BarcodePreview);
    }catch(e){setBarcodeError(e instanceof Error?e.message:"Ошибка проверки штрихкода");}
    finally{setBarcodeBusy(false);}
  };
  const applyBarcode=async()=>{
    if(!barcodePreview||barcodeBusy)return;
    if(!await requestConfirmation("Изменение штрихкода",`Изменить штрихкод только товара ${barcodePreview.article} с «${barcodePreview.catalog_barcode||"пусто"}» на «${barcodePreview.new_barcode}»? WB не изменится.`,"Сохранить штрихкод"))return;
    setBarcodeBusy(true);setBarcodeError("");
    try{
      await readResponse(await fetch(`${API}/product-attention/barcode/item/apply`,{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({master_id:barcodePreview.master_id,nm_id:barcodePreview.nm_id,barcode:barcodePreview.new_barcode,preview_fingerprint:barcodePreview.fingerprint})}));
      setBarcodePreview(null);setBarcodeDetail(null);
      await load();await scanAttention();
      setMessage(`Штрихкод ${barcodePreview.article} сохранён в общем каталоге.`);
    }catch(e){setBarcodePreview(null);setBarcodeError(e instanceof Error?e.message:"Ошибка сохранения штрихкода");}
    finally{setBarcodeBusy(false);}
  };
  const previewManualDimensions=async()=>{
    if(!dimensionDetail||!dimensionsValid||!dimensionsChanged)return;
    setFillBusy(true);setFillError("");try{
      const data=await readResponse(await fetch(`${API}/product-attention/dimensions/item/manual/preview`,{
        method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({master_id:dimensionDetail.master_id,nm_id:dimensionDetail.nm_id,dimensions:parsedDimensions()})}));
      if(data.master_id!==dimensionDetail.master_id||data.nm_id!==dimensionDetail.nm_id||!Array.isArray(data.changes)||typeof data.fingerprint!=="string")throw Error("Некорректный ответ сервера");
      setManualPreview(data as ManualPreview);
    }catch(e){setFillError(e instanceof Error?e.message:"Не удалось проверить размеры");}finally{setFillBusy(false);}
  };
  const applyManualDimensions=async()=>{
    if(!manualPreview||!dimensionDetail||fillBusy)return;
    if(!await requestConfirmation("Заменить габариты в каталоге",`Сохранить ${manualPreview.changes.length} изменённых полей товара ${manualPreview.article}? На WB ничего не изменится.`,"Заменить в каталоге"))return;
    setFillBusy(true);setFillError("");try{
      const result=await readResponse(await fetch(`${API}/product-attention/dimensions/item/manual/apply`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({master_id:manualPreview.master_id,nm_id:manualPreview.nm_id,preview_fingerprint:manualPreview.fingerprint,dimensions:parsedDimensions()})}));
      setManualPreview(null);setDimensionDetail(null);await load();await scanAttention();
      setMessage(`Изменено полей: ${result.updated_fields}. Габариты в каталоге сохранены, WB не изменён.`);
    }catch(e){setFillError(e instanceof Error?e.message:"Не удалось сохранить габариты");setManualPreview(null);}finally{setFillBusy(false);}
  };
  const approveAttention=async(a:AttentionItem)=>{const target=Number(selectedMaster[a.id]||products.find(p=>p.seller_article===a.article)?.id||0);
    if(!target){setMessage("Укажи товар каталога для подтверждения");return;}
    if(!await requestConfirmation("Подтверждение связи WB",`Связать WB nmID ${a.nm_id} с товаром ID ${target}? История не изменится.`,"Подтвердить связь"))return;
    setAttentionBusy(true);try{const r=await fetch(`${API}/product-attention/${a.id}/approve`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({master_id:target,nm_id:a.nm_id,observed_article:a.article})});const x=await r.json();if(!r.ok)throw Error(typeof x.detail==="string"?x.detail:"Ошибка подтверждения");setMessage(`Подтверждено nmID ${a.nm_id}`);await loadAttention();await refreshMpDimensionIssues();}catch(e){setMessage(e instanceof Error?e.message:"Ошибка");}finally{setAttentionBusy(false);}};


  const confirmOzonSnapshot=async(issue:MarketplaceDimensionIssue)=>{
    if(issue.marketplace!=="OZON"||!issue.master_id||issue.confirmed)return;
    setAttentionBusy(true);setAttentionError("");
    try{
      const preview=await readResponse(await fetch(`${API}/catalog-import/OZON/link-preview`,{cache:"no-store"}));
      const candidate=(preview.proposals||[]).find((item:{external_id:string;master_id:number;article:string})=>item.external_id===issue.external_id&&item.master_id===issue.master_id&&item.article===issue.article);
      if(!candidate)throw Error("Однозначное сопоставление не найдено. Проверьте карточку Ozon в окне синхронизации.");
      setAttentionBusy(false);
      const approved=await requestConfirmation("Подтверждение связи Ozon",`Связать Ozon product_id ${candidate.external_id} с товаром ${candidate.article}? Размеры, штрихкоды и ручные поля каталога не изменятся.`,"Подтвердить связь");
      if(!approved)return;
      setAttentionBusy(true);
      await readResponse(await fetch(`${API}/catalog-import/OZON/link-batch`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({fingerprint:preview.fingerprint,items:[candidate]})}));
      await load();await refreshMpDimensionIssues();
      setMessage(`Связь Ozon с ${candidate.article} подтверждена. Габариты не изменены.`);
    }catch(e){setAttentionError(e instanceof Error?e.message:"Не удалось подтвердить связь Ozon");}
    finally{setAttentionBusy(false);}
  };
  const saveDimensionDecision=async(decision:"DISPUTED"|"ACCEPTED")=>{
    const target=dimensionDecisionTarget;
    if(!target?.issue.confirmed||!target.issue.master_id||!target.problem.fingerprint)return;
    setDimensionDecisionBusy(true);setDimensionDecisionError("");
    try{
      await readResponse(await fetch(`${API}/catalog-import/dimension-decision`,{
        method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({
          marketplace:target.issue.marketplace,external_id:target.issue.external_id,master_id:target.issue.master_id,
          issue_code:target.problem.code,fingerprint:target.problem.fingerprint,decision
        })}));
      setDimensionDecisionTarget(null);
      await refreshMpDimensionIssues();
      setMessage(decision==="ACCEPTED"?"Различие подтверждено. Предупреждение скрыто до изменения размеров.":"Статус «Оспаривается» сохранён.");
    }catch(e){setDimensionDecisionError(e instanceof Error?e.message:"Не удалось сохранить решение");}
    finally{setDimensionDecisionBusy(false);}
  };

  const openAlerts=alerts.filter(a=>a.status==="OPEN");
  // One review card per known master product. Unlinked external cards remain separate.
  const attentionGroups:AttentionGroup[]=[];
  const groupMap=new Map<string,AttentionGroup>();
  const groupFor=(id:number|null|undefined,article:string,title:string,sourceKey:string)=>{
    const matches=id ? [] : products.filter(p=>p.seller_article===article);
    const master=id??(matches.length===1?matches[0].id:null);
    const key=master?`master:${master}`:sourceKey;
    let group=groupMap.get(key);
    if(!group){group={key,masterId:master,article:products.find(p=>p.id===master)?.seller_article||article,title:products.find(p=>p.id===master)?.name||title||article,entries:[]};groupMap.set(key,group);attentionGroups.push(group);}
    return group;
  };
  for(const a of openAlerts)groupFor(a.master_id,a.article,a.title||a.article,`WB:${a.nm_id}`).entries.push({kind:"identity",data:a});
  for(const a of dimensionAlerts)groupFor(a.master_id,a.article,a.title||a.article,`WB:${a.nm_id}`).entries.push({kind:"wb-dimensions",data:a});
  for(const a of barcodeAlerts)groupFor(a.master_id,a.article,a.title||a.article,`WB:${a.nm_id}`).entries.push({kind:"wb-barcode",data:a});
  for(const a of mpDimensionIssues){
    // The legacy WB identity queue already represents this external card.
    if(a.marketplace==="WB"&&!a.confirmed&&openAlerts.some(w=>w.nm_id===a.external_id))continue;
    const ignoreWbDimensions=a.marketplace==="WB"&&dimensionAlerts.some(w=>w.nm_id===a.external_id);
    for(const problem of a.problems||[]){
      if(ignoreWbDimensions&&["DIFFERENT","MARKETPLACE_MISSING","CATALOG_MISSING"].includes(problem.code))continue;
      groupFor(a.master_id,a.article,a.title||a.article,`${a.marketplace}:${a.external_id}`).entries.push({kind:"snapshot",data:a,code:problem.code,label:problem.label,preliminary:!!problem.preliminary});
    }
  }
  const attentionQuery=attentionSearch.trim().toLowerCase();
  // If a full seller article exists, prefer it over incidental matches in external IDs.
  // Example: 061 should find HS061, not all cards whose nmID contains 061.
  const normalizeArticle=(value:string)=>value.trim().toLowerCase().replace(/\s+/g,"");
  const exactAttentionArticle=attentionQuery && attentionGroups.some(group=>{
    const article=normalizeArticle(group.article);
    return article===normalizeArticle(attentionQuery)||(/^[0-9]+$/.test(attentionQuery)&&article===`hs${attentionQuery}`);
  });
  const visibleAttentionGroups=attentionGroups.filter(group=>{
    if(!attentionQuery)return true;
    const article=normalizeArticle(group.article);
    if(exactAttentionArticle)return article===normalizeArticle(attentionQuery)||(/^[0-9]+$/.test(attentionQuery)&&article===`hs${attentionQuery}`);
    return [group.article,group.title,...group.entries.map(e=>e.kind==="snapshot"?`${e.data.marketplace} ${e.data.external_id} ${e.label}`:e.kind==="identity"?`${e.data.nm_id} ${attentionReason(e.data.reason).label}`:e.data.nm_id)]
      .some(text=>String(text||"").toLowerCase().includes(attentionQuery));
  });
  attentionGroups.sort((a,b)=>naturalArticleCompare(a.article,b.article));


  const load=async()=>{
    const r=await fetch(`${API}/master-products`,{cache:"no-store"});
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
    try{const overviewResult=await readResponse(await fetch(`${API}/master-products/marketplace-overview`,{cache:"no-store"}));setOverview(overviewResult.cards_by_product||{});}catch{setOverview({});}
  };
  useEffect(()=>{void refreshMpDimensionIssues();},[]);
  useEffect(()=>{void load().catch(e=>setMessage(e instanceof Error?e.message:"Ошибка загрузки"));},[]);
  const filtered=useMemo(()=>{
    const q=search.trim().toLowerCase();
    const candidates=products.filter(p=>{
      const m=mp==="ALL"||(mp==="WB"&&p.wb_enabled)||(mp==="OZON"&&p.ozon_enabled)||(mp==="YANDEX"&&p.yandex_enabled);
      return m&&(statusFilter==="ALL"||p.status===statusFilter);
    });
    const exactArticle=(p:Product)=>[p.internal_article,p.seller_article].some(value=>{
      const article=String(value||"").trim().toLowerCase();
      if(article===q)return true;
      // Поиск «061» должен находить HS061, но не HS063 по совпадению в ШК.
      return /^\d+$/.test(q)&&article.replace(/^[^0-9]+/,"")===q;
    });
    const hasExactArticle=q!==""&&candidates.some(exactArticle);
    return candidates.filter(p=>{
      if(!q)return true;
      if(hasExactArticle)return exactArticle(p);
      return [p.internal_article,p.seller_article,p.barcode,p.name,p.internal_name]
        .some(value=>String(value||"").toLowerCase().includes(q));
    }).sort((a,b)=>naturalArticleCompare(a.seller_article||"",b.seller_article||"")||a.id-b.id);
  },[products,search,mp,statusFilter]);
  const stats={total:products.length,active:products.filter(p=>p.active).length,wb:products.filter(p=>p.wb_enabled).length,ozon:products.filter(p=>p.ozon_enabled).length,yandex:products.filter(p=>p.yandex_enabled).length};
  const openAdd=()=>{setEditing(null);setForm(EMPTY);setMessage("");setModal(true);};
  const openEdit=(p:Product)=>{setEditing(p);setForm(formOf(p));setMessage("");setMarketCards([]);setMarketDetails([]);setMarketDetailsLoading(true);setModal(true);
    void fetch(`${API}/catalog-import/product/${p.id}/cards`).then(readResponse).then(setMarketCards).catch(()=>{});
    void fetch(`${API}/master-products/${p.id}/marketplace-details`,{cache:"no-store"}).then(readResponse)
      .then((data:ProductMarketplaceDetails)=>setMarketDetails(Array.isArray(data.marketplace_cards)?data.marketplace_cards:[]))
      .catch(()=>setMarketDetails([])).finally(()=>setMarketDetailsLoading(false));
  };
  const setField=<K extends keyof Form>(key:K,value:Form[K])=>setForm(f=>({...f,[key]:value}));
  const save=async()=>{if(saving)return;setSaving(true);setMessage("");try{const r=await fetch(editing?`${API}/master-products/${editing.id}`:`${API}/master-products`,{method:editing?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(form)});const d=await r.json();if(!r.ok||d.status!=="ok")throw Error(d.message||"Не удалось сохранить товар");setModal(false);setMessage(editing?"Товар сохранён":"Товар добавлен");await load();}catch(e){setMessage(e instanceof Error?e.message:"Ошибка сохранения");}finally{setSaving(false);}};
  const remove=async(p:Product)=>{if(!await requestConfirmation("Удаление товара",`Удалить «${p.name||p.seller_article}»? Проверь, что выбран правильный товар.`,"Удалить товар",true))return;const r=await fetch(`${API}/master-products/${p.id}`,{method:"DELETE"});const d=await r.json();if(!r.ok||d.status!=="ok"){setMessage(d.message||"Не удалось удалить");return;}await load();};
  const mps=(p:Product)=>{const a:MP[]=[];if(p.wb_enabled)a.push("WB");if(p.ozon_enabled)a.push("OZON");if(p.yandex_enabled)a.push("YANDEX");return a;};
  const dimensionInfo=(p:Product):{status:DimensionCompleteness;description:string}=>{
    const expected=mps(p);
    const cards=overview[String(p.id)]||[];
    const catalogOk=dimensionsComplete([p.length_cm,p.width_cm,p.height_cm]);
    const populated=[...(catalogOk?["Наш каталог"]:[])];
    const absent=[...(!catalogOk?["Наш каталог"]:[])];
    for(const market of expected){
      const matches=cards.filter(c=>c.marketplace===market&&c.confirmed);
      if(matches.some(c=>dimensionsComplete(c.dimensions?.normalized_cm||[])))populated.push(mpNames[market]);
      else if(matches.length)absent.push(`${mpNames[market]}: габариты не заполнены/не подтверждены`);
      else absent.push(`${mpNames[market]}: нет подтверждённого снимка`);
    }
    return {status:absent.length===0?"complete":populated.length===0?"empty":"partial",
      description:`Заполнено: ${populated.join(", ")||"нигде"}. ${absent.length?`Требует проверки: ${absent.join("; ")}.`:"Все ожидаемые размеры доступны."}`};
  };

  return <div className="products-page" onClick={()=>menuId!==null&&setMenuId(null)}>
    <header className="products-head"><div><div className="products-eyebrow">КАТАЛОГ ТОВАРОВ</div><h1>Товары</h1><p>Единый справочник товаров, себестоимости, габаритов и маркетплейсов.</p></div><div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
    <button className="products-primary" onClick={()=>void runUnifiedSync()} disabled={unifiedSyncBusy}>{unifiedSyncBusy?"Синхронизация…":"Синхронизировать товары"}</button>
    <button className="products-primary" onClick={openAdd}>+ Добавить товар</button></div></header>
    <div className="product-attention-tabs">
      <button className={tab==="catalog"?"active":""} onClick={()=>setTab("catalog")}>Все товары</button>
      <button className={tab==="attention"?"active":""} onClick={()=>{setTab("attention");void refreshMpDimensionIssues();void loadAttention().catch(e=>setAttentionError(e instanceof Error?e.message:"Ошибка загрузки конфликтов"));}}>Требует внимания ({attentionGroups.length})</button>
    </div>
    {tab==="attention" && <section className="product-attention">
      <div className="product-attention-heading">
        <div><h2>Проблемы товаров на маркетплейсах</h2><p>Проблемы объединены по товару. Совпадение артикула без подтверждения связи — предварительное, данные каталога не изменяются.</p></div>
        <div style={{display:"flex",gap:8,flexWrap:"wrap",justifyContent:"flex-end"}}><button type="button" className="products-primary" disabled={attentionBusy||fillBusy||bulkLinkBusy} onClick={()=>void previewBulkLinks()}>{bulkLinkBusy?"Подготовка…":"Сопоставить существующие товары WB"}</button><button className="products-primary product-attention-scan" disabled={attentionBusy||fillBusy} onClick={()=>void scanAttention()}>{attentionBusy?"Идёт сверка…":"Обновить сверку WB"}</button></div>
      </div>
      <div className="product-attention-toolbar">
        <input aria-label="Поиск по проблемным карточкам" placeholder="Поиск по названию, артикулу или ID карточки" value={attentionSearch} onChange={e=>setAttentionSearch(e.target.value)}/>
        <span>Показано товаров: {visibleAttentionGroups.length} из {attentionGroups.length}</span>
      </div>
      {bulkLinkError&&<div className="products-message" role="alert">{bulkLinkError}</div>}
      {fillError&&<div className="products-message" role="alert">{fillError}</div>}
      {attentionError&&<div className="products-message" role="alert">{attentionError}</div>}
      {mpDimensionIssuesError&&<div className="products-message" role="alert">Ошибка чтения проблем МП: {mpDimensionIssuesError}</div>}
      {message&&<div className="products-message" role="status">{message}</div>}
      {dimensionAudit&&<div className="products-message" role="status" style={{marginBottom:12}}>
        <div><strong>Охват проверки габаритов WB:</strong> {dimensionAudit.counts.checked} из {dimensionAudit.counts.checked+dimensionAudit.excluded.length} карточек с nmID.
          Совпадают: {dimensionAudit.counts.clean}; с проблемами размеров: {dimensionAudit.counts.with_issues}; не проверены из-за привязки: {dimensionAudit.excluded.length}.</div>
        {dimensionAudit.excluded.length>0&&<>
          <button type="button" className="product-attention-problem-link" style={{marginTop:8}}
            onClick={()=>setShowAuditExcluded(v=>!v)}>{showAuditExcluded?"Скрыть":"Показать"} причины пропуска ({dimensionAudit.excluded.length})</button>
          {showAuditExcluded&&<div style={{maxHeight:260,overflow:"auto",marginTop:8}}>
            <table className="products-table" style={{width:"100%"}}><thead><tr><th>Артикул</th><th>nmID</th><th>Почему габариты не проверены</th></tr></thead><tbody>
            {dimensionAudit.excluded.map(row=><tr key={row.nm_id}><td>{row.article||"—"}</td><td>{row.nm_id}</td><td>{({no_link:"Нет подтверждённой связи WB",no_master:"Связь указывает на отсутствующий товар каталога",no_local:"Нет локальной карточки WB",duplicate_local:"Несколько локальных карточек с одним nmID",article_mismatch:"Не совпадает артикул WB, локальной карточки или каталога"} as Record<string,string>)[row.reason]||row.reason}</td></tr>)}
            </tbody></table>
          </div>}
        </>}
      </div>}
      <div className="products-table-wrap"><table className="products-table product-attention-table product-attention-grouped"><thead><tr><th>Товар</th><th>Артикул</th><th>Проблемы</th><th>Действие</th></tr></thead><tbody>
      {visibleAttentionGroups.map(group=><Fragment key={group.key}>
        <tr className="product-attention-group-heading">
          <td className="product-attention-name"><strong>{group.title}</strong><span>{group.masterId?"Товар общего каталога":"Карточка ещё не сопоставлена"}</span></td>
          <td>{group.article}</td>
          <td><div className="product-attention-summary">
            <span className="product-attention-reason">{group.entries.length} {group.entries.length===1?"проблема":"проблемы"}</span>
            <div className="product-attention-summary-labels">{Array.from(new Set(group.entries.map(entry=>{
              if(entry.kind==="snapshot")return `${mpNames[entry.data.marketplace as MP]||entry.data.marketplace}: ${entry.label}${entry.data.problems.find(p=>p.code===entry.code)?.decision==="DISPUTED"?" (оспаривается)":entry.preliminary?" (предварительно)":""}`;
              if(entry.kind==="identity")return `WB: ${attentionReason(entry.data.reason).label}`;
              return entry.kind==="wb-dimensions"?"WB: проверка габаритов":"WB: проверка штрихкода";
            }))).slice(0,3).map(label=><span key={label}>{label}</span>)}
              {group.entries.length>3&&<span>Подробнее — все проблемы</span>}</div>
          </div></td>
          <td><button type="button" className="product-attention-confirm" aria-expanded={expandedAttention===group.key} onClick={()=>setExpandedAttention(v=>v===group.key?null:group.key)}>{expandedAttention===group.key?"Скрыть":"Подробнее"}</button></td>
        </tr>
        {expandedAttention===group.key&&<tr className="product-attention-details-row"><td colSpan={4}><div className="product-attention-entry-list">
          {group.entries.map((entry,index)=>{
            if(entry.kind==="identity"){
              const a=entry.data;
              const catalogMatches=products.filter(p=>p.seller_article===a.article);
              const selectedId=selectedMaster[a.id]||String(catalogMatches.length===1?catalogMatches[0].id:"");
              const isCreate=(a.reason==="MISSING_LOCAL_CARD"||a.reason==="NO_MASTER_PRODUCT")&&catalogMatches.length===0;
              const isLink=(a.reason==="MISSING_LOCAL_CARD"||a.reason==="NO_MASTER_PRODUCT")&&catalogMatches.length===1;
              return <div className="product-attention-entry" key={`identity-${a.id}`}><div><b>Wildberries · {a.nm_id}</b><p>{attentionReason(a.reason).label} <ProblemHint description={attentionReason(a.reason).description}/></p></div>
                <div className="product-attention-entry-action">
                  {isLink&&<select aria-label={`Связать ${a.article}`} value={selectedId} onChange={e=>setSelectedMaster(m=>({...m,[a.id]:e.target.value}))}><option value="">Выбрать товар</option>{products.map(p=><option key={p.id} value={p.id}>{p.seller_article} · {p.name}</option>)}</select>}
                  {isCreate?<button className="product-attention-confirm" type="button" disabled={createBusy||createLoading} onClick={()=>void openCreateFromMarketplace("WB",a.nm_id,a.article)}>Создать товар</button>
                    :isLink?<button className="product-attention-confirm" type="button" disabled={!selectedId||attentionBusy} onClick={()=>void approveAttention(a)}>Связать</button>
                    :<button className="product-attention-confirm" type="button" onClick={()=>setAttentionExplanation(a)}>Подробнее</button>}
                </div></div>;
            }
            if(entry.kind==="wb-dimensions")return <div className="product-attention-entry" key={`dim-${entry.data.nm_id}`}><div><b>Wildberries · Габариты</b><p>Обнаружены проблемы размеров ({entry.data.problems.length})</p></div><button className="product-attention-confirm" type="button" onClick={()=>openDimensionDetail(entry.data)}>Подробнее</button></div>;
            if(entry.kind==="wb-barcode")return <div className="product-attention-entry" key={`bar-${entry.data.nm_id}`}><div><b>Wildberries · Штрихкод</b><p>Требуется проверка штрихкода</p></div><button className="product-attention-confirm" type="button" onClick={()=>openBarcodeDetail(entry.data)}>Подробнее</button></div>;
            const issue=entry.data;
            return <div className="product-attention-entry" key={`snapshot-${issue.marketplace}-${issue.external_id}-${index}`}>
              <div><b>{mpNames[issue.marketplace as MP]||issue.marketplace} · {issue.external_id}</b> {entry.preliminary&&<span className="product-attention-preliminary">Предварительно</span>} {issue.problems.find(p=>p.code===entry.code)?.decision==="DISPUTED"&&<span className="product-attention-preliminary">Оспаривается</span>}
                <p>{entry.label} <ProblemHint description={`Каталог: ${formatDimensions(issue.catalog_cm)} см; МП: ${formatDimensions(issue.marketplace_cm)} см. ${issue.confirmed?"Связь подтверждена.":"Связь не подтверждена. Размеры относятся к предполагаемому товару."} Никакие значения не изменяются.`}/></p></div>
              <div className="product-attention-entry-action">
                {entry.code==="LINK_UNCONFIRMED"&&issue.marketplace==="OZON"&&issue.master_id&&!issue.confirmed&&
                  <button className="product-attention-confirm" type="button" disabled={attentionBusy} onClick={()=>void confirmOzonSnapshot(issue)}>{attentionBusy?"Проверяем…":"Подтвердить связь"}</button>}
                {entry.code==="LINK_UNCONFIRMED"&&issue.marketplace!=="OZON"&&
                  <button className="product-attention-confirm" type="button" onClick={()=>{setImportMarket(issue.marketplace as MP);setImportVisible(true);void runPreview(issue.marketplace as MP);}}>Проверить связь</button>}
                {(["DIFFERENT","MARKETPLACE_MISSING","CATALOG_MISSING"].includes(entry.code))&&
                  <button className="product-attention-confirm" type="button" onClick={()=>{setDimensionDecisionError("");setDimensionDecisionTarget({issue,problem:issue.problems.find(p=>p.code===entry.code)!});}}>{issue.confirmed?"Решить проблему":"Сравнить размеры"}</button>}
                {!(["DIFFERENT","MARKETPLACE_MISSING","CATALOG_MISSING","LINK_UNCONFIRMED"].includes(entry.code))&&
                  <button className="product-attention-confirm" type="button" onClick={()=>{setImportMarket(issue.marketplace as MP);setImportVisible(true);void runPreview(issue.marketplace as MP);}}>Проверить карточку</button>}
              </div>
            </div>;
          })}
        </div></td></tr>}
      </Fragment>)}
      {!visibleAttentionGroups.length&&<tr><td colSpan={4} className="product-attention-empty">{attentionGroups.length?"По вашему запросу товары не найдены.":"Проблем нет. Запустите синхронизацию для актуальной проверки."}</td></tr>}
      </tbody></table></div>
      <p className="product-attention-footnote">Снимки МП считываются из БД после синхронизации. Предварительное совпадение по артикулу не создаёт связь; изменение значений выполняется только после подтверждения.</p>
      {dimensionDecisionTarget&&<div className="product-dimension-overlay" role="presentation" onMouseDown={()=>!dimensionDecisionBusy&&setDimensionDecisionTarget(null)}>
        <div className="product-dimension-dialog" role="dialog" aria-modal="true" aria-label="Решение по габаритам" onMouseDown={e=>e.stopPropagation()}>
          <div className="product-dimension-dialog-head"><div><h3>{dimensionDecisionTarget.problem.label}</h3><p>{dimensionDecisionTarget.issue.article} · {mpNames[dimensionDecisionTarget.issue.marketplace as MP]||dimensionDecisionTarget.issue.marketplace}</p></div><button type="button" aria-label="Закрыть" disabled={dimensionDecisionBusy} onClick={()=>setDimensionDecisionTarget(null)}>×</button></div>
          <div className="products-message">Наш каталог: {formatDimensions(dimensionDecisionTarget.issue.catalog_cm)} см. Маркетплейс: {formatDimensions(dimensionDecisionTarget.issue.marketplace_cm)} см.</div>
          {!dimensionDecisionTarget.issue.confirmed&&<p className="product-attention-preliminary">Сначала подтвердите связь карточки с товаром. Решение по габаритам пока недоступно.</p>}
          {dimensionDecisionTarget.issue.confirmed&&<p>Выберите решение. Значения на маркетплейсе и в общем каталоге автоматически не меняются.</p>}
          {dimensionDecisionError&&<div className="products-message" role="alert">{dimensionDecisionError}</div>}
          <div className="product-dimension-dialog-actions product-attention-decision-actions">
            {dimensionDecisionTarget.issue.confirmed&&<>
              <button type="button" className="products-primary" disabled={dimensionDecisionBusy} onClick={()=>void saveDimensionDecision("DISPUTED")}>Оспаривается на МП</button>
              <button type="button" className="products-primary" disabled={dimensionDecisionBusy} onClick={()=>void saveDimensionDecision("ACCEPTED")}>Подтвердить различие</button>
              <button type="button" className="products-primary" disabled={dimensionDecisionBusy} onClick={()=>{const item=products.find(p=>p.id===dimensionDecisionTarget.issue.master_id);setDimensionDecisionTarget(null);if(item)void openEdit(item);}}>Изменить в каталоге</button>
            </>}
            <button type="button" className="products-secondary" disabled={dimensionDecisionBusy} onClick={()=>setDimensionDecisionTarget(null)}>Закрыть</button>
          </div>
        </div>
      </div>}
      {attentionExplanation&&<div className="product-dimension-overlay" role="presentation" onMouseDown={()=>setAttentionExplanation(null)}><div className="product-dimension-dialog" role="dialog" aria-modal="true" aria-label="Описание проблемы" onMouseDown={e=>e.stopPropagation()}>
        <div className="product-dimension-dialog-head"><div><h3>{attentionReason(attentionExplanation.reason).label}</h3><p>{attentionExplanation.article} · WB: {attentionExplanation.nm_id}</p></div><button type="button" onClick={()=>setAttentionExplanation(null)} aria-label="Закрыть">×</button></div>
        <div className="products-message">{attentionReason(attentionExplanation.reason).description} Проверьте выбранный товар перед подтверждением связи.</div>
        <div className="product-dimension-dialog-actions"><button type="button" className="products-primary" onClick={()=>setAttentionExplanation(null)}>Закрыть</button></div>
      </div></div>}
      {createError&&!createFromCard&&<div className="products-message" role="alert">{createError} <button type="button" onClick={()=>setCreateError("")}>Закрыть</button></div>}
      {createFromCard&&<div className="product-dimension-overlay" role="presentation" onMouseDown={()=>!createBusy&&setCreateFromCard(null)}>
        <div className="product-dimension-dialog" role="dialog" aria-modal="true" aria-label="Создание товара" onMouseDown={e=>e.stopPropagation()}>
          <div className="product-dimension-dialog-head"><div><h3>Создать товар</h3><p>Предварительный просмотр данных из {createFromCard.marketplace==="YANDEX"?"Яндекс Маркета":createFromCard.marketplace==="OZON"?"Ozon":"Wildberries"}. Товар появится в едином каталоге.</p></div><button type="button" disabled={createBusy} onClick={()=>setCreateFromCard(null)} aria-label="Закрыть">×</button></div>
          <p className="product-dimension-readonly">Статус нового товара — «Готовится». В реестр остатков автоматически не включается. Себестоимость — 0 ₽ до ручного заполнения. Данные на маркетплейсе не меняются.</p>
          <div className="product-dimension-table-wrap"><table><tbody>
            <tr><th>Название</th><td>{createFromCard.name||"Не передано маркетплейсом"}</td></tr>
            <tr><th>Артикул</th><td>{createFromCard.article}</td></tr>
            <tr><th>Источник / ID</th><td>{createFromCard.marketplace} · {createFromCard.external_id}</td></tr>
            <tr><th>Штрихкод</th><td>{createFromCard.barcodes.join(", ")||"Не передан"}</td></tr>
            <tr><th>Габариты, см</th><td>{createFromCard.dimensions?`${createFromCard.dimensions.length_cm} × ${createFromCard.dimensions.width_cm} × ${createFromCard.dimensions.height_cm}`:"Не переданы"}</td></tr>
          </tbody></table></div>
          {createError&&<p className="products-message" role="alert">{createError}</p>}
          <div className="product-dimension-dialog-actions product-create-dialog-actions"><button type="button" className="product-create-cancel" disabled={createBusy} onClick={()=>setCreateFromCard(null)}>Отмена</button><button type="button" className="products-primary" disabled={createBusy} onClick={()=>void confirmCreateFromMarketplace()}>{createBusy?"Создаём…":"Подтвердить создание"}</button></div>
        </div>
      </div>}
      {bulkLinkPreview&&<div className="product-dimension-overlay" role="presentation" onMouseDown={()=>!bulkLinkBusy&&setBulkLinkPreview(null)}>
        <div className="product-dimension-dialog" role="dialog" aria-modal="true" aria-label="Сопоставление карточек WB" onMouseDown={e=>e.stopPropagation()} style={{maxWidth:980}}>
          <div className="product-dimension-dialog-head"><div><h3>Сопоставить существующие товары WB</h3><p>Только однозначные соответствия по nmID локальной карточки и артикулу общего каталога.</p></div><button type="button" disabled={bulkLinkBusy} onClick={()=>setBulkLinkPreview(null)} aria-label="Закрыть">×</button></div>
          <p className="product-dimension-readonly">Предварительный просмотр: возможных связей {bulkLinkPreview.proposals.length}, отклонённых неоднозначных вариантов {bulkLinkPreview.skipped.length}. Ничего не будет изменено до подтверждения. Размеры и названия не записываются.</p>
          <div className="product-dimension-table-wrap" style={{maxHeight:"48vh",overflow:"auto"}}><table><thead><tr><th><input type="checkbox" aria-label="Выбрать все однозначные" checked={bulkLinkPreview.proposals.length>0&&bulkLinkPreview.proposals.every(p=>!!bulkLinkSelected[p.nm_id])} onChange={e=>setBulkLinkSelected(Object.fromEntries(bulkLinkPreview.proposals.map(p=>[p.nm_id,e.target.checked])))} /></th><th>Артикул / nmID</th><th>Название WB</th><th>Общий каталог</th></tr></thead><tbody>
            {bulkLinkPreview.proposals.map(p=><tr key={p.nm_id}><td><input type="checkbox" checked={!!bulkLinkSelected[p.nm_id]} onChange={e=>setBulkLinkSelected(prev=>({...prev,[p.nm_id]:e.target.checked}))} aria-label={`Выбрать ${p.article}`}/></td><td>{p.article}<br/>{p.nm_id}</td><td>{p.wb_title||"—"}</td><td>{p.master_name||p.article} (ID {p.master_id})</td></tr>)}
            {!bulkLinkPreview.proposals.length&&<tr><td colSpan={4}>Однозначных совпадений нет. Требуется ручное сопоставление.</td></tr>}
          </tbody></table></div>
          {bulkLinkPreview.skipped.length>0&&<details><summary>Не предложены для массового подтверждения: {bulkLinkPreview.skipped.length}</summary><div className="product-dimension-table-wrap" style={{maxHeight:160,overflow:"auto"}}><table><tbody>{bulkLinkPreview.skipped.map(p=><tr key={p.nm_id}><td>{p.article}</td><td>{p.nm_id}</td><td>{({dismissed:"Ранее отклонена",duplicate_or_empty_article:"Неуникальный или пустой артикул",local_missing_or_duplicate:"Нет ровно одной локальной карточки с nmID",local_article_conflict:"Артикул локальной карточки не совпадает или занят",master_missing_or_duplicate:"Нет однозначного товара каталога",master_already_linked:"Общий товар уже связан с другим nmID",imported_identity_conflict:"Импортированная связь указывает на другой товар или артикул"} as Record<string,string>)[p.reason]||p.reason}</td></tr>)}</tbody></table></div></details>}
          <div className="product-dimension-dialog-actions" style={{display:"flex",gap:8,justifyContent:"flex-end"}}><button className="products-primary" disabled={bulkLinkBusy} onClick={()=>setBulkLinkPreview(null)}>Отмена</button><button className="products-primary" disabled={bulkLinkBusy||!bulkLinkPreview.proposals.some(p=>bulkLinkSelected[p.nm_id])} onClick={()=>void applyBulkLinks()}>Подтвердить выбранные ({bulkLinkPreview.proposals.filter(p=>bulkLinkSelected[p.nm_id]).length})</button></div>
        </div></div>}
      {barcodeDetail&&<div className="product-dimension-overlay" role="presentation" onMouseDown={()=>!barcodeBusy&&setBarcodeDetail(null)}><div className="product-dimension-dialog" role="dialog" aria-modal="true" aria-label="Проблемы штрихкода" onMouseDown={e=>e.stopPropagation()}>
        <div className="product-dimension-dialog-head"><div><h3>Проверка штрихкода</h3><p>{barcodeDetail.title||barcodeDetail.article} · {barcodeDetail.article} · nmID {barcodeDetail.nm_id}</p></div><button disabled={barcodeBusy} onClick={()=>setBarcodeDetail(null)} aria-label="Закрыть">×</button></div>
        <p className="product-dimension-readonly">Изменяется только штрихкод нашего каталога. Выберите значение, полученное с WB. Изменение штрихкода на WB через приложение пока недоступно.</p>
        <div className="product-dimension-table-wrap"><table><thead><tr><th>Наш каталог</th><th>Wildberries</th></tr></thead><tbody><tr><td>{barcodeDetail.catalog_barcode||"Не заполнено"}</td><td>{barcodeDetail.wb_barcodes.join(", ")||"Не передано"}</td></tr></tbody></table></div>
        {barcodeDetail.wb_barcodes.length>0&&<label style={{display:"block",marginTop:16}}>Штрихкод для каталога
          <select style={{display:"block",width:"100%",marginTop:8,padding:10}} value={barcodeValue} onChange={e=>{setBarcodeValue(e.target.value);setBarcodePreview(null);}}>
            <option value="">Выберите штрихкод WB</option>{barcodeDetail.wb_barcodes.map(v=><option key={v} value={v}>{v}</option>)}
          </select></label>}
        {barcodeError&&<div className="products-message" role="alert">{barcodeError}</div>}
        <div className="product-dimension-dialog-actions" style={{gap:8}}><button className="products-primary" disabled={barcodeBusy} onClick={()=>setWbPlaceholder(true)}>Изменить на WB</button><button className="products-primary" disabled={barcodeBusy||!barcodeValue||barcodeValue===barcodeDetail.catalog_barcode} onClick={()=>void previewBarcode()}>Заменить в каталоге</button><button className="products-primary" disabled={barcodeBusy} onClick={()=>setBarcodeDetail(null)}>Закрыть</button></div>
      </div></div>}
      {barcodePreview&&<div className="product-dimension-overlay product-dimension-confirm-layer" role="presentation" onMouseDown={()=>!barcodeBusy&&setBarcodePreview(null)}><div className="product-dimension-dialog" role="dialog" aria-modal="true" aria-label="Предпросмотр штрихкода" onMouseDown={e=>e.stopPropagation()}>
        <div className="product-dimension-dialog-head"><div><h3>Предварительная проверка штрихкода</h3><p>{barcodePreview.article} · WB nmID {barcodePreview.nm_id}. Пока без изменений.</p></div><button disabled={barcodeBusy} onClick={()=>setBarcodePreview(null)} aria-label="Закрыть">×</button></div>
        <p className="product-dimension-readonly">Было: {barcodePreview.catalog_barcode||"Не заполнено"}. Будет: {barcodePreview.new_barcode}. Изменится только наш каталог.</p>
        {barcodeError&&<div className="products-message" role="alert">{barcodeError}</div>}
        <div className="product-dimension-dialog-actions" style={{gap:8}}><button className="products-primary" disabled={barcodeBusy} onClick={()=>setBarcodePreview(null)}>Отмена</button><button className="products-primary" disabled={barcodeBusy} onClick={()=>void applyBarcode()}>Подтвердить замену</button></div>
      </div></div>}
      {dimensionDetail&&<div className="product-dimension-overlay" role="presentation" onMouseDown={()=>!fillBusy&&setDimensionDetail(null)}><div className="product-dimension-dialog" role="dialog" aria-modal="true" aria-label="Проблемы габаритов" onMouseDown={e=>e.stopPropagation()}>
        <div className="product-dimension-dialog-head"><div><h3>Есть проблемы с габаритами</h3><p>{dimensionDetail.title||dimensionDetail.article} · {dimensionDetail.article} · WB nmID {dimensionDetail.nm_id}</p></div><button type="button" disabled={fillBusy} onClick={()=>setDimensionDetail(null)} aria-label="Закрыть">×</button></div>
        <p className="product-dimension-readonly">Изменяйте размеры нашего каталога в полях ниже. Размеры WB — только для чтения. Изменения в каталог сохраняются после предварительной проверки и подтверждения.</p>
        <div className="product-dimension-table-wrap"><table><thead><tr><th>Параметр</th><th>Наш каталог, см (редактируется)</th><th>WB, см</th><th>Проблема</th></tr></thead><tbody>{dimensionKeys.map(k=>{const problem=dimensionDetail.problems.find(p=>p.field===k);return <tr key={k}><td>{dimensionLabels[k]}</td><td><input className="product-dimension-input" type="text" inputMode="decimal" aria-label={`${dimensionLabels[k]} в каталоге, см`} value={dimensionInputs[k]} onChange={e=>{setFillError("");setDimensionInputs(prev=>({...prev,[k]:e.target.value}));}} placeholder="Не заполнено"/></td><td>{dimensionDetail.marketplace_dimensions?.[k]??"Не передано"}</td><td>{!problem?"Совпадает":problem.code==="MARKETPLACE_DIMENSION_MISSING"?"Не передано на WB":problem.code==="CATALOG_DIMENSION_MISSING"?"Нет значения в каталоге":"Размеры отличаются"}</td></tr>;})}</tbody></table></div>
        {(!dimensionsValid||!dimensionsChanged)&&<p className="product-dimension-hint">Для замены в каталоге введите три положительных размера (до 2 знаков после запятой), отличающихся от текущих.</p>}
        {bulkLinkError&&<div className="products-message" role="alert">{bulkLinkError}</div>}
      {fillError&&<div className="products-message" role="alert">{fillError}</div>}
        <div className="product-dimension-dialog-actions" style={{display:"flex",gap:8,justifyContent:"flex-end",flexWrap:"wrap"}}>
          <button type="button" className="products-primary" disabled={fillBusy} onClick={()=>setWbPlaceholder(true)}>Изменить на WB</button>
          <button type="button" className="products-primary" disabled={fillBusy||!dimensionsValid||!dimensionsChanged} onClick={()=>void previewManualDimensions()}>{fillBusy?"Проверка…":"Заменить в каталоге"}</button>
          <button type="button" className="products-primary" disabled={fillBusy} onClick={()=>{setFillError("");setDimensionDetail(null);}}>Закрыть</button>
        </div>
      </div></div>}
      {manualPreview&&<div className="product-dimension-overlay product-dimension-confirm-layer" role="presentation" onMouseDown={()=>!fillBusy&&setManualPreview(null)}><div className="product-dimension-dialog" role="dialog" aria-modal="true" aria-label="Предпросмотр ручного изменения габаритов" onMouseDown={e=>e.stopPropagation()}>
        <div className="product-dimension-dialog-head"><div><h3>Предварительная проверка изменений</h3><p>{manualPreview.article} · WB nmID {manualPreview.nm_id}. Изменения ещё не записаны.</p></div><button type="button" disabled={fillBusy} onClick={()=>setManualPreview(null)} aria-label="Закрыть">×</button></div>
        <p className="product-dimension-readonly">Будут изменены только указанные поля одного товара в нашем каталоге. На WB ничего не изменится.</p>
        <div className="product-dimension-table-wrap"><table><thead><tr><th>Поле</th><th>Было, см</th><th>Будет, см</th></tr></thead><tbody>{manualPreview.changes.map(c=><tr key={c.field}><td>{dimensionLabels[c.field as DimensionKey]}</td><td>{c.old_cm??"Не заполнено"}</td><td>{c.new_cm}</td></tr>)}</tbody></table></div>
        {bulkLinkError&&<div className="products-message" role="alert">{bulkLinkError}</div>}
      {fillError&&<div className="products-message" role="alert">{fillError}</div>}
        <div className="product-dimension-dialog-actions" style={{gap:8}}><button className="products-primary" disabled={fillBusy} onClick={()=>setManualPreview(null)}>Отмена</button><button className="products-primary" disabled={fillBusy||!manualPreview.changes.length} onClick={()=>void applyManualDimensions()}>{fillBusy?"Запись…":"Подтвердить замену"}</button></div>
      </div></div>}
      {wbPlaceholder&&<div className="product-dimension-overlay product-dimension-confirm-layer" role="presentation" onMouseDown={()=>setWbPlaceholder(false)}><div className="product-dimension-dialog" role="dialog" aria-modal="true" aria-label="Изменение на WB" onMouseDown={e=>e.stopPropagation()}><div className="product-dimension-dialog-head"><h3>Изменение на Wildberries</h3><button onClick={()=>setWbPlaceholder(false)} aria-label="Закрыть">×</button></div><p className="product-dimension-readonly">Функция в разработке. Изменения на Wildberries пока не отправляются.</p><div className="product-dimension-dialog-actions"><button className="products-primary" onClick={()=>setWbPlaceholder(false)}>Понятно</button></div></div></div>}
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
              <strong>{(["WB","OZON","YANDEX"] as MP[]).map(m=>((overview[String(p.id)]||[]).find(c=>c.confirmed&&c.marketplace===m&&c.title)?.title)).find(Boolean)||p.name||"Без названия"}</strong>{p.internal_name&&<small className="product-internal-name">{p.internal_name}</small>}
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
          <span className={`product-dim-status product-dim-${dimensionInfo(p).status}`} title={dimensionInfo(p).description} tabIndex={0}>
            {dimensionInfo(p).status==="complete"?"Заполнены":dimensionInfo(p).status==="partial"?"Заполнены частично":"Не заполнены"}
          </span>
        </td>
        <td className="product-volume-cell">{p.volume_liters!=null?`${n(p.volume_liters)} л`:"-"}</td>
        <td><div className="chips">{mps(p).map(x=><span key={x}>{x==="YANDEX"?"ЯМ":x}</span>)}{!mps(p).length&&<small>Не выбраны</small>}</div></td>
      </tr>)}
      {!filtered.length&&<tr><td colSpan={7} className="empty">Товары не найдены</td></tr>}
    </tbody></table></div>

    </>}
    {importVisible&&<div className="modal-bg catalog-sync-overlay" onMouseDown={()=>!importLoading&&!unifiedSyncBusy&&setImportVisible(false)}>
      <div className="catalog-sync-dialog" role="dialog" aria-modal="true" aria-labelledby="catalog-sync-heading" onMouseDown={e=>e.stopPropagation()}>
        <header className="catalog-sync-head">
          <div><div className="products-eyebrow">МАРКЕТПЛЕЙСЫ / КАТАЛОГ</div><h2 id="catalog-sync-heading">Синхронизация товаров</h2>
            <p>Просмотр карточек и безопасное добавление в общий каталог</p></div>
          <button type="button" className="close" aria-label="Закрыть окно" onClick={()=>setImportVisible(false)} disabled={importLoading||unifiedSyncBusy}>×</button>
        </header>
        <div className="catalog-unified-actions">
          <span className="catalog-unified-actions-info">Все подключённые маркетплейсы · единая проверка</span>
          <button type="button" className="catalog-sync-cancel" onClick={()=>{setMatchSettingsOpen(v=>!v);if(!matchSettings)void loadMatchSettings();}} disabled={matchBusy||unifiedSyncBusy}>Настройки</button>
          <button type="button" className="products-primary" disabled={unifiedSyncBusy||matchBusy||importLoading} onClick={()=>void runUnifiedSync()}>{unifiedSyncBusy?"Синхронизация…":"Синхронизировать товары"}</button>
          <button type="button" className="products-primary" disabled={matchBusy||unifiedSyncBusy||importLoading} onClick={()=>void previewAllMarkets()}>{matchBusy?"Проверяем…":"Проверить и сопоставить"}</button>
        </div>
        {matchSettingsOpen&&matchSettings&&<div className="catalog-match-settings">
          <div className="catalog-match-grid"><label>Основной признак
            <select value={matchSettings.match_by} onChange={e=>setMatchSettings(v=>v?{...v,match_by:e.target.value as "ARTICLE"|"BARCODE"}:v)}>
              <option value="ARTICLE">Артикул продавца</option><option value="BARCODE">Штрихкод общего каталога</option>
            </select></label>
            <label>Часовой пояс <input value={matchSettings.timezone} onChange={e=>setMatchSettings(v=>v?{...v,timezone:e.target.value}:v)} placeholder="Europe/Moscow" /></label>
          </div>
          <label className="catalog-match-checkbox"><input type="checkbox" checked={matchSettings.auto_enabled} onChange={e=>setMatchSettings(v=>v?{...v,auto_enabled:e.target.checked}:v)}/> Включить автоматическую сверку по сохранённому расписанию (будет активировано в следующем патче)</label>
          <label>Время запусков, через запятую, формат ЧЧ:ММ<input value={matchSettings.times.join(", ")} onChange={e=>setMatchSettings(v=>v?{...v,times:e.target.value.split(",").map(x=>x.trim())}:v)} placeholder="06:00, 18:00, 23:00"/></label>
          <p>Пока расписание только сохраняется. Планировщик не запускается до отдельной проверки. Массовое сопоставление доступно для всех подключённых маркетплейсов.</p>
          <button type="button" className="products-primary" disabled={matchBusy} onClick={()=>void saveMatchSettings()}>Сохранить настройки</button>
        </div>}
        {autoPreview&&<div className="catalog-match-preview" role="region" aria-label="Результат массового сопоставления">
          <strong>Предварительный просмотр сопоставления всех подключённых МП</strong>
          <p>Правило: {autoPreview.match_by==="ARTICLE"?"по артикулу продавца":"по штрихкоду"}. Сейчас ничего не изменено. Операция создаёт только новые подтверждённые связи, сохраняя данные общего каталога.</p>
          {!!autoPreview.failed.length&&<div className="catalog-sync-error" role="alert">Не удалось проверить: {autoPreview.failed.join(", ")}. Массовое применение заблокировано до полной успешной проверки.</div>}
          <div className="catalog-match-report-scroll"><table className="catalog-match-report-table"><thead><tr><th>Маркетплейс</th><th>Получено</th><th>Новые связи</th><th>Уже связаны</th><th>Новые товары</th><th>Ручная проверка</th></tr></thead><tbody>
            {autoPreview.marketplaces.map(m=>{const r=autoPreview.by_marketplace?.[m];return <tr key={m}><td>{mpNames[m as MP]||m}{r?.api_error?" · ошибка API":""}</td><td>{r?.received??"—"}</td><td>{r?.new_links??0}</td><td>{r?.already_linked??0}</td><td>{r?.new_products??0}</td><td>{r?.needs_review??0}</td></tr>})}
            <tr className="catalog-match-report-total"><th>Всего</th><td>{autoPreview.marketplaces.reduce((n,m)=>n+(autoPreview.by_marketplace?.[m]?.received??0),0)}</td><td>{autoPreview.proposals.length}</td><td>{autoPreview.excluded_details?.filter(e=>e.category==="ALREADY_LINKED").length??0}</td><td>{autoPreview.excluded_details?.filter(e=>e.category==="NEW_PRODUCT").length??0}</td><td>{autoPreview.excluded_details?.filter(e=>e.category==="NEEDS_REVIEW").length??0}</td></tr>
          </tbody></table></div>
          <p>«Новые связи» — количество карточек МП, для которых будет создана привязка, а не количество новых товаров. «Новые товары» не создаются этой операцией.</p>
          <div className="catalog-match-preview-tabs">
            {([ ["links",`Новые связи (${autoPreview.proposals.length})`],["already",`Уже связаны (${autoPreview.excluded_details?.filter(e=>e.category==="ALREADY_LINKED").length??0})`],["new",`Новые товары (${autoPreview.excluded_details?.filter(e=>e.category==="NEW_PRODUCT").length??0})`],["review",`Ручная проверка (${autoPreview.excluded_details?.filter(e=>e.category==="NEEDS_REVIEW").length??0})`] ] as const).map(([key,label])=><button key={key} type="button" className={autoPreviewTab===key?"active":""} onClick={()=>setAutoPreviewTab(key)}>{label}</button>)}
          </div>
          <div className="catalog-match-result-filters">
            <label htmlFor="catalog-match-market-filter">Площадка</label>
            <AppSelect label="Площадка" value={autoMarketFilter} options={[{value:"ALL",label:"Все МП"},...autoPreview.marketplaces.map(m=>({value:m,label:mpNames[m as MP]||m}))]} onChange={v=>setAutoMarketFilter(v as "ALL"|MP)}/>
            <input className="catalog-match-preview-search" placeholder="Поиск по артикулу, ID или названию" aria-label="Поиск по результатам сопоставления" value={autoPreviewSearch} onChange={e=>setAutoPreviewSearch(e.target.value)}/>
          </div>
          <div className="catalog-match-detail-list" role="list">
            {(()=>{
              const q=autoPreviewSearch.trim().toLocaleLowerCase("ru");
              const items=autoPreviewTab==="links"
                ? autoPreview.proposals.map(p=>({marketplace:p.marketplace,external_id:p.external_id,article:p.article,detail:`${p.master_article} · ${p.master_name}`,reason:"Создать подтверждённую связь",search:p.remote_name+" "+p.master_name}))
                : (autoPreview.excluded_details||[]).filter(p=>p.category===({already:"ALREADY_LINKED",new:"NEW_PRODUCT",review:"NEEDS_REVIEW"} as const)[autoPreviewTab]).map(p=>({marketplace:p.marketplace,external_id:p.external_id,article:p.article,detail:autoExclusionReasons[p.reason]||p.reason,reason:"Без записи",search:""}));
              const matches=items.filter(p=>(autoMarketFilter==="ALL"||p.marketplace===autoMarketFilter)&&(!q||`${p.marketplace} ${p.external_id} ${p.article} ${p.detail} ${p.search}`.toLocaleLowerCase("ru").includes(q)));
              return <>{matches.map((p,i)=><div className="catalog-match-detail-row" role="listitem" key={`${p.marketplace}:${p.external_id}:${i}`}><span>{mpNames[p.marketplace as MP]||p.marketplace}</span><span><b>{p.article||"Без артикула"}</b><small>ID {p.external_id||"—"}</small></span><span>{p.detail}</span><span>{p.reason}</span></div>)}{!matches.length&&<p>Нет записей по выбранному фильтру.</p>}</>;
            })()}
          </div>
          <div className="catalog-match-preview-footer"><span>К записи: <b>{autoPreview.operation_count??autoPreview.proposals.length}</b> связей. Остальные карточки не меняются.</span><button type="button" className="products-primary" disabled={matchBusy||!autoPreview.can_apply||!autoPreview.fingerprint||!autoPreview.proposals.length} onClick={()=>{setMassAcknowledged(false);setMassConfirmOpen(true);}}>Применить все однозначные ({autoPreview.proposals.length})</button></div>
        </div>}
        {massConfirmOpen&&autoPreview&&<div className="product-dimension-overlay catalog-mass-confirm-overlay" onMouseDown={e=>{e.stopPropagation();if(e.target===e.currentTarget&&!matchBusy)setMassConfirmOpen(false);}}>
          <div className="product-dimension-dialog catalog-mass-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="catalog-mass-confirm-title" onMouseDown={e=>e.stopPropagation()}>
            <div className="product-dimension-dialog-head"><div><h3 id="catalog-mass-confirm-title">Подтвердить массовое сопоставление</h3><p>Перед записью сервер заново получит карточки и проверит полный состав предложений.</p></div><button type="button" aria-label="Закрыть" disabled={matchBusy} onClick={()=>setMassConfirmOpen(false)}>×</button></div>
            <div className="catalog-mass-confirm-body">
              <p><strong>Будет создано {autoPreview.proposals.length} новых связей.</strong> Новые товары не создаются, ранее подтверждённые связи не перезаписываются.</p>
              <div className="catalog-match-report-scroll"><table className="catalog-match-report-table"><thead><tr><th>Площадка</th><th>Новые связи</th><th>Уже связаны</th><th>Новые товары</th><th>Ручная проверка</th></tr></thead><tbody>
                {autoPreview.marketplaces.map(m=>{const r=autoPreview.by_marketplace?.[m];return <tr key={m}><td>{mpNames[m as MP]||m}</td><td>{r?.new_links??0}</td><td>{r?.already_linked??0}</td><td>{r?.new_products??0}</td><td>{r?.needs_review??0}</td></tr>})}
              </tbody></table></div>
              <p className="catalog-mass-confirm-warning">Связи будут созданы по признаку «{autoPreview.match_by==="ARTICLE"?"Артикул продавца":"Штрихкод"}». Совпадение выбранного признака не гарантирует, что это один и тот же товар. При сомнениях отмените операцию и проверьте список кандидатов.</p>
              <label className="catalog-mass-confirm-check"><input type="checkbox" checked={massAcknowledged} onChange={e=>setMassAcknowledged(e.target.checked)}/><span>Я проверил(а) предложения и согласен(на) создать только эти новые связи.</span></label>
            </div>
            <div className="product-dimension-dialog-actions catalog-mass-confirm-actions"><button type="button" className="catalog-sync-cancel" disabled={matchBusy} onClick={()=>setMassConfirmOpen(false)}>Отмена</button><button type="button" className="products-primary" disabled={matchBusy||!massAcknowledged||!autoPreview.can_apply} onClick={()=>void applyAllMarkets()}>Подтвердить {autoPreview.proposals.length} связей</button></div>
          </div>
        </div>}
        {autoApplyResult&&<div className="catalog-sync-note" role="status">{autoApplyResult}</div>}
        {matchError&&<div className="catalog-sync-error" role="alert">{matchError}</div>}
        <div className="catalog-sync-note"><span aria-hidden="true">ⓘ</span><span>Сначала просматриваем карточки. Новые товары создаются со статусом «Готовится» и не включаются в реестр остатков. Ручные данные существующих товаров не перезаписываются.</span></div>
        {unifiedSyncBusy&&<div className="catalog-sync-note" role="status">Получаем карточки подключённых маркетплейсов и сохраняем снимки. Не закрывайте окно до завершения.</div>}
        {unifiedSyncResult&&<div className="catalog-sync-note" role="status" style={{display:"block"}}>
          <strong>Результат единой синхронизации (только снимки)</strong>
          {unifiedSyncResult.marketplaces.map(item=><div key={item.marketplace} style={{marginTop:6}}>
            {mpNames[item.marketplace as MP]||item.marketplace}: {item.status==="OK"?`получено ${item.received||0}, изменено ${item.changed||0}${item.skipped_api_errors?`, пропущено из-за ошибок размеров: ${item.skipped_api_errors}`:""}`:"Ошибка получения данных — проверьте журнал backend"}
          </div>)}
          {unifiedSyncResult.skipped.map(item=><div key={item.marketplace} style={{marginTop:6}}>{mpNames[item.marketplace as MP]||item.marketplace}: пропущен ({item.reason==="DISABLED"?"отключён в настройках":"нет API-ключей"})</div>)}
          <div style={{marginTop:8}}>Существующие товары и связи не изменены. Для создания отдельных товаров используйте раздел «Ручной импорт новых товаров» ниже.</div>
        </div>}
        <details className="catalog-manual-import" open={manualImportOpen} onToggle={e=>setManualImportOpen(e.currentTarget.open)}>
          <summary>Ручной импорт новых товаров <span>Только для карточек без однозначного сопоставления</span></summary>
          <div className="catalog-sync-toolbar catalog-manual-toolbar">
            <label htmlFor="catalog-manual-market">Маркетплейс</label>
            <AppSelect label="Маркетплейс ручного импорта" value={importMarket} disabled={importLoading||unifiedSyncBusy} options={[{value:"WB",label:"Wildberries"},{value:"OZON",label:"Ozon"},{value:"YANDEX",label:"Яндекс Маркет"}]} onChange={v=>{setImportMarket(v as MP);setImportPreview(null);setImportSelected({});setImportTargets({});setImportResults([]);setImportSearch("");setImportError("");}}/>
            <button type="button" className="products-primary catalog-sync-fetch" disabled={importLoading||unifiedSyncBusy} onClick={()=>void runPreview(importMarket)}>{importLoading?"Загрузка карточек…":"Получить карточки"}</button>
          </div>
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
          {importMarket==="OZON"&&importPreview.dimension_summary&&<div className="catalog-ozon-audit" role="status">
            <strong>Ozon · проверка габаритов (без изменений)</strong>
            <span>Совпадают: {importPreview.dimension_summary.SAME||0}</span>
            <span>Различаются: {importPreview.dimension_summary.DIFFERENT||0}</span>
            <span>Нет в каталоге: {importPreview.dimension_summary.CATALOG_MISSING||0}</span>
            <span>Нет данных Ozon: {importPreview.dimension_summary.OZON_MISSING||0}</span>
            <span>Ошибка API: {importPreview.dimension_summary.OZON_API_ERROR||0}</span>
            <span>Не сопоставлены: {importPreview.dimension_summary.UNRESOLVED||0}</span>
            <p>Размеры упаковки приведены к сантиметрам по единицам Ozon. При расхождении значения каталога не изменяются.</p>
          </div>}
          {importMarket==="OZON"&&importPreview.barcode_summary&&<div className="catalog-ozon-audit" role="status">
            <strong>Ozon · проверка штрихкодов (без изменений)</strong>
            <span>Совпадают: {importPreview.barcode_summary.SAME||0}</span>
            <span>Отличаются: {importPreview.barcode_summary.DIFFERENT||0}</span>
            <span>Нет в каталоге: {importPreview.barcode_summary.MISSING_IN_CATALOG||0}</span>
            <span>Нет на Ozon: {importPreview.barcode_summary.MISSING_ON_OZON||0}</span>
            <span>Товар не сопоставлен: {importPreview.barcode_summary.UNRESOLVED||0}</span>
            <p>Разные штрихкоды при совпадающем артикуле допустимы. Они не являются основанием объединять или перезаписывать товары. Для существующих товаров импорт пока не подтверждай.</p>
          </div>}
          <div className="catalog-sync-filters"><label htmlFor="catalog-sync-search">Поиск по карточкам</label><input id="catalog-sync-search" placeholder="Артикул или название товара" value={importSearch} onChange={e=>setImportSearch(e.target.value)}/>
            <span>Отмечено: <b>{importPreview.items.filter(c=>importSelected[c.external_id]&&c.status!=="LINKED"&&c.status!=="CONFLICT").length}</b></span>
          </div>
          <div className="catalog-sync-scroll" role="region" aria-label="Карточки для импорта" tabIndex={0}>
            <table className="catalog-sync-table"><thead><tr><th className="catalog-sync-check">Выбор</th><th>Маркетплейс / ID</th><th>Артикул</th><th>Наименование</th><th>Штрихкоды</th><th>Габариты, см</th><th>Связь с общим товаром</th><th>Статус</th></tr></thead><tbody>
              {importPreview.items.filter(c=>`${c.article} ${c.name}`.toLowerCase().includes(importSearch.toLowerCase())).map(c=><tr key={c.external_id}>
                <td className="catalog-sync-check"><input type="checkbox" aria-label={`Выбрать ${c.article}`} disabled={importLoading||c.status==="LINKED"||c.status==="CONFLICT"} checked={!!importSelected[c.external_id]} onChange={e=>setImportSelected(s=>({...s,[c.external_id]:e.target.checked}))}/></td>
                <td><span className="catalog-sync-mp">{c.marketplace==="YANDEX"?"Я.Маркет":c.marketplace==="OZON"?"Ozon":"WB"}</span><span className="catalog-sync-muted">{c.external_id}</span>{Object.entries(c.platform_ids).filter(([,v])=>!!v&&v!==c.external_id).map(([k,v])=><span className="catalog-sync-muted" key={k}>{k}: {v}</span>)}</td>
                <td className="catalog-sync-article">{c.article}</td><td className="catalog-sync-name">{c.name||"—"}</td><td className="catalog-sync-muted">{c.barcodes.join(", ")||"—"}{c.marketplace==="OZON"&&c.barcode_check&&c.barcode_check!=="UNRESOLVED"&&<span className="catalog-ozon-barcode-hint" title="Сравнение только для чтения. Штрихкоды разных маркетплейсов могут различаться.">{c.barcode_check==="SAME"?"Совпадает с каталогом":c.barcode_check==="DIFFERENT"?`Другой ШК в каталоге: ${c.catalog_barcode} (допустимо)`:c.barcode_check==="MISSING_IN_CATALOG"?"В каталоге ШК не заполнен":"На Ozon ШК отсутствует"}</span>}</td>
                <td className="catalog-sync-dims">{c.dimensions?`${c.dimensions.length_cm} × ${c.dimensions.width_cm} × ${c.dimensions.height_cm}`:"—"}{c.marketplace==="OZON"&&<span className="catalog-ozon-barcode-hint" title={c.dimension_source||"Нет подтверждённых данных о размерах Ozon"}>{({SAME:"Совпадает с каталогом",DIFFERENT:"Размеры отличаются — проверить",CATALOG_MISSING:"Габариты отсутствуют в каталоге",OZON_MISSING:"Размеры Ozon не переданы/некорректны",OZON_API_ERROR:"Ошибка проверки габаритов Ozon",UNRESOLVED:"Товар не сопоставлен"} as Record<string,string>)[c.dimension_check||""]||"Размеры не проверены"}</span>}</td>
                <td>{c.status==="LINKED"?<span className="catalog-sync-muted">Связан с {products.find(p=>p.id===c.master_id)?.seller_article || `ID ${c.master_id}`}</span>:c.status==="CONFLICT"?<span className="catalog-sync-muted" title={IMPORT_CONFLICTS[c.conflict_reason||""]||"Требуется ручная проверка"}>{IMPORT_CONFLICTS[c.conflict_reason||""]||"Проверить связь вручную"}</span>:
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
            <div><button type="button" className="catalog-sync-cancel" onClick={()=>setImportVisible(false)} disabled={importLoading||unifiedSyncBusy}>Закрыть</button>
              <button type="button" className="products-primary" disabled={importLoading||!importPreview.items.some(c=>importSelected[c.external_id]&&c.status!=="LINKED"&&c.status!=="CONFLICT")} onClick={()=>void importSelectedCards()}>Импортировать выбранные</button></div></footer>
        </> : <div className="catalog-sync-empty-state"><strong>Карточки ещё не загружены</strong><p>Выберите площадку и нажмите «Получить карточки» для ручного создания или привязки отдельных товаров.</p></div>}
        </details>
      </div>
    </div>}
    {modal&&<div className="modal-bg" onMouseDown={()=>!saving&&setModal(false)}><div className="modal" onMouseDown={e=>e.stopPropagation()}><div className="modal-head"><div><div className="products-eyebrow">КАТАЛОГ</div><h2>{editing?"Изменить товар":"Новый товар"}</h2></div><button className="close" onClick={()=>setModal(false)}>×</button></div>
      <section><h3>Основные данные</h3><div className="form-grid"><label>Внутренний артикул<input value={form.internal_article} onChange={e=>setField("internal_article",e.target.value)}/></label><label>Артикул продавца<input value={form.seller_article} onChange={e=>setField("seller_article",e.target.value)}/></label><label className="wide">Название товара<input value={form.name} onChange={e=>setField("name",e.target.value)}/></label><label className="wide">Внутреннее название товара<input value={form.internal_name} onChange={e=>setField("internal_name",e.target.value)} placeholder="Название для внутреннего использования"/></label><label>ШК / баркод<input value={form.barcode} onChange={e=>setField("barcode",e.target.value)}/></label><label>Группа 1С
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
      {editing&&<section className="mp-details-section"><h3>Карточки на маркетплейсах</h3><p>Данные из последних сохранённых снимков площадок. Неподтверждённые совпадения показаны отдельно и не считаются связью.</p>
        {marketDetailsLoading&&<p>Загружаем данные площадок…</p>}
        {(["WB","OZON","YANDEX"] as MP[]).map(market=>{
          const cards=marketDetails.filter(c=>c.marketplace===market);
          const known=marketCards.filter(c=>c.marketplace===market);
          return <div className="mp-detail-panel" key={market}><div className="mp-detail-head"><h4>{mpNames[market]}</h4><span>{cards.some(c=>c.confirmed)?"Подтверждена":known.length?"Есть связь, снимка нет":cards.length?"Кандидат по артикулу":"Не синхронизирован"}</span></div>
            {cards.length?cards.map(c=><div className="mp-detail-card" key={c.external_id}>
              {!c.confirmed&&<div className="mp-detail-unconfirmed">Совпадение по артикулу — связь не подтверждена</div>}
              <div className="mp-detail-grid"><label>Артикул продавца<div className="mp-readonly-value">{c.seller_article||"Не передан"}</div></label><label>Номенклатура / ID<div className="mp-readonly-value">{c.external_id}</div></label>
                <label className="wide">Наименование товара<div className="mp-readonly-value">{c.title||"Не передано"}</div></label>
                <div className="wide mp-readonly-field"><span>Штрихкоды</span><div className="mp-readonly-value mp-barcode-values">{c.barcodes.length?c.barcodes.map(barcode=><span key={barcode}>{barcode}</span>):"Не переданы"}</div></div>
                <div className="wide mp-readonly-field"><span>Габариты ({c.dimensions.unit||"ед. не указана"})</span>
                  <div className="mp-dimensions-line"><div className="mp-readonly-value">{formatDimensions([c.dimensions.length,c.dimensions.width,c.dimensions.height])}</div>
                    {(()=>{const check=snapshotComparison([form.length_cm,form.width_cm,form.height_cm].map(v=>v===""?null:Number(v)),c);return <span className={`mp-dimension-indicator mp-dimension-${check.kind}`} title={check.description}>{check.label}</span>})()}
                  </div>
                </div>
              </div><details className="mp-detail-description"><summary>Описание товара <span aria-hidden="true">⌄</span></summary><div className="mp-description-body">{c.description||"Описание не получено"}</div></details>
              <small>Последняя успешная проверка: {c.checked_at?new Date(c.checked_at).toLocaleString("ru-RU"):"Нет данных"}</small>
            </div>):known.length?known.map(c=><div key={c.external_id} className="mp-detail-placeholder">Связанная карточка {c.seller_article}, ID {c.external_id}. Полный снимок пока не получен; отсутствие данных не означает отсутствие размеров на МП.</div>):<p className="mp-detail-placeholder">Нет данных последней синхронизации. Привязка товара не создаётся автоматически.</p>}
          </div>})}
      </section>}
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
    {confirmation&&createPortal(<div className="product-confirm-overlay" onMouseDown={()=>finishConfirmation(false)}>
      <div className="product-confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="product-confirm-title" aria-describedby="product-confirm-description" onMouseDown={e=>e.stopPropagation()}>
        <div className="product-confirm-head"><h3 id="product-confirm-title">{confirmation.title}</h3><button type="button" aria-label="Закрыть подтверждение" onClick={()=>finishConfirmation(false)}>×</button></div>
        <p id="product-confirm-description">{confirmation.message}</p>
        <div className="product-confirm-actions">
          <button type="button" className="product-confirm-cancel" onClick={()=>finishConfirmation(false)}>Отмена</button>
          <button type="button" className={`products-primary${confirmation.danger?" product-confirm-danger":""}`} autoFocus onClick={()=>finishConfirmation(true)}>{confirmation.confirmLabel}</button>
        </div>
      </div>
    </div>,document.body)}
  </div>;
}
export default MasterProducts;
