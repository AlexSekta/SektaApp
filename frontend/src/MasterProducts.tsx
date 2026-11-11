import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./MasterProducts.css";

interface ImportCard { marketplace:MP; external_id:string; article:string; name:string;
  barcodes:string[]; dimensions:{length_cm:number;width_cm:number;height_cm:number}|null;
  platform_ids:Record<string,string>; status:"NEW"|"MATCH"|"LINKED"|"CONFLICT";
  master_id:number|null; suggested_master_id:number|null; conflict_reason?:string|null; }
interface ImportPreview { marketplace:MP; total:number; items:ImportCard[];
  summary:Record<string,number>; read_only:boolean; }
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
  const [importPreview,setImportPreview]=useState<ImportPreview|null>(null);
  const [importLoading,setImportLoading]=useState(false);
  const [importError,setImportError]=useState("");
  const [importSearch,setImportSearch]=useState("");
  const [importSelected,setImportSelected]=useState<Record<string,boolean>>({});
  const [importTargets,setImportTargets]=useState<Record<string,string>>({});
  const [importResults,setImportResults]=useState<string[]>([]);
  // Generic catalog creation flow. The source marketplace is a parameter,
  // not a WB-specific creation path; other marketplaces use the same importer.
  const [createFromCard,setCreateFromCard]=useState<ImportCard|null>(null);
  const [createBusy,setCreateBusy]=useState(false);
  const [createError,setCreateError]=useState("");
  const [createLoading,setCreateLoading]=useState(false);
  const [createCheckingId,setCreateCheckingId]=useState<string|null>(null);
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
    setAttentionBusy(true);try{const r=await fetch(`${API}/product-attention/${a.id}/approve`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({master_id:target,nm_id:a.nm_id,observed_article:a.article})});const x=await r.json();if(!r.ok)throw Error(typeof x.detail==="string"?x.detail:"Ошибка подтверждения");setMessage(`Подтверждено nmID ${a.nm_id}`);await loadAttention();}catch(e){setMessage(e instanceof Error?e.message:"Ошибка");}finally{setAttentionBusy(false);}};


  const openAlerts=alerts.filter(a=>a.status==="OPEN");
  const visibleBarcodeAlerts=barcodeAlerts.filter(a=>[a.title,a.article,a.nm_id].some(v=>String(v||"").toLowerCase().includes(attentionSearch.toLowerCase().trim())));
  const visibleDimensionAlerts=dimensionAlerts.filter(a=>[a.title,a.article,a.nm_id].some(v=>String(v||"").toLowerCase().includes(attentionSearch.toLowerCase().trim())));
  const visibleAlerts=openAlerts.filter(a=>[a.title,a.article,a.nm_id,a.old_article].some(v=>String(v||"").toLowerCase().includes(attentionSearch.toLowerCase().trim())));

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
  const remove=async(p:Product)=>{if(!await requestConfirmation("Удаление товара",`Удалить «${p.name||p.seller_article}»? Проверь, что выбран правильный товар.`,"Удалить товар",true))return;const r=await fetch(`${API}/master-products/${p.id}`,{method:"DELETE"});const d=await r.json();if(!r.ok||d.status!=="ok"){setMessage(d.message||"Не удалось удалить");return;}await load();};
  const mps=(p:Product)=>{const a:MP[]=[];if(p.wb_enabled)a.push("WB");if(p.ozon_enabled)a.push("OZON");if(p.yandex_enabled)a.push("YANDEX");return a;};
  const dimensionsMissing=(p:Product)=>p.length_cm==null||p.width_cm==null||p.height_cm==null;

  return <div className="products-page" onClick={()=>menuId!==null&&setMenuId(null)}>
    <header className="products-head"><div><div className="products-eyebrow">КАТАЛОГ ТОВАРОВ</div><h1>Товары</h1><p>Единый справочник товаров, себестоимости, габаритов и маркетплейсов.</p></div><div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
    <button className="products-primary" onClick={()=>{setImportVisible(true);setImportPreview(null);setImportResults([]);setImportError("");}}>Синхронизировать товары</button>
    <button className="products-primary" onClick={openAdd}>+ Добавить товар</button></div></header>
    <div className="product-attention-tabs">
      <button className={tab==="catalog"?"active":""} onClick={()=>setTab("catalog")}>Все товары</button>
      <button className={tab==="attention"?"active":""} onClick={()=>{setTab("attention");void loadAttention().catch(e=>setAttentionError(e instanceof Error?e.message:"Ошибка загрузки конфликтов"));}}>Требует внимания ({alerts.filter(a=>a.status==="OPEN").length+dimensionAlerts.length+barcodeAlerts.length})</button>
    </div>
    {tab==="attention" && <section className="product-attention">
      <div className="product-attention-heading">
        <div><h2>Сверка карточек Wildberries</h2><p>Конфликты связей и габаритов. Данные WB доступны только для чтения. Пустые размеры нашего каталога можно заполнить в окне проблемы конкретного товара.</p></div>
        <div style={{display:"flex",gap:8,flexWrap:"wrap",justifyContent:"flex-end"}}><button type="button" className="products-primary" disabled={attentionBusy||fillBusy||bulkLinkBusy} onClick={()=>void previewBulkLinks()}>{bulkLinkBusy?"Подготовка…":"Сопоставить существующие товары WB"}</button><button className="products-primary product-attention-scan" disabled={attentionBusy||fillBusy} onClick={()=>void scanAttention()}>{attentionBusy?"Идёт сверка…":"Обновить сверку WB"}</button></div>
      </div>
      <div className="product-attention-toolbar">
        <input aria-label="Поиск по проблемным карточкам" placeholder="Поиск по названию, артикулу или nmID" value={attentionSearch} onChange={e=>setAttentionSearch(e.target.value)}/>
        <span>Показано: {visibleAlerts.length+visibleDimensionAlerts.length+visibleBarcodeAlerts.length} из {openAlerts.length+dimensionAlerts.length+barcodeAlerts.length}</span>
      </div>
      {bulkLinkError&&<div className="products-message" role="alert">{bulkLinkError}</div>}
      {fillError&&<div className="products-message" role="alert">{fillError}</div>}
      {attentionError&&<div className="products-message" role="alert">{attentionError}</div>}
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
      <div className="products-table-wrap"><table className="products-table product-attention-table"><colgroup><col className="product-attention-col-name"/><col className="product-attention-col-id"/><col className="product-attention-col-transition"/><col className="product-attention-col-problem"/><col className="product-attention-col-link"/><col className="product-attention-col-action"/></colgroup><thead><tr><th>Товар МП</th><th>Номенклатура</th><th>Было / обнаружено</th><th>Проблема</th><th>Связать с товаром</th><th>Действие</th></tr></thead><tbody>
      {visibleAlerts.map(a=>{
        const catalogMatches=products.filter(p=>p.seller_article===a.article);
        const selectedId=selectedMaster[a.id]||String(catalogMatches.length===1?catalogMatches[0].id:"");
        const isCreate=(a.reason==="MISSING_LOCAL_CARD"||a.reason==="NO_MASTER_PRODUCT")&&catalogMatches.length===0;
        const isLink=(a.reason==="MISSING_LOCAL_CARD"||a.reason==="NO_MASTER_PRODUCT")&&catalogMatches.length===1;
        return <tr key={a.id}>
          <td className="product-attention-name"><strong>{a.title||a.article}</strong><span>{a.article}</span></td>
          <td className="product-attention-nmid" title="Wildberries: nmID">{a.nm_id}</td>
          <td><span className="product-attention-transition"><span>{a.old_article||"—"}</span><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 12h15m-6-6 6 6-6 6"/></svg><span>{a.article}</span></span></td>
          <td><div className="product-attention-problem-cell"><span className="product-attention-reason">{attentionReason(a.reason).label}</span><ProblemHint description={attentionReason(a.reason).description}/></div></td>
          <td><select aria-label={`Связать ${a.article} с товаром`} disabled={isCreate} value={selectedId} onChange={e=>setSelectedMaster(m=>({...m,[a.id]:e.target.value}))}>
            <option value="">{isCreate?"Сначала создайте товар":"Выбрать товар"}</option>
            {!isCreate&&products.map(p=><option key={p.id} value={p.id}>{p.seller_article} · {p.name}</option>)}
          </select></td>
          <td><div className="product-attention-row-actions">{isCreate?
            <button type="button" className="product-attention-confirm" disabled={attentionBusy||createLoading||createBusy} onClick={()=>void openCreateFromMarketplace("WB",a.nm_id,a.article)}>{createCheckingId===`WB:${a.nm_id}`?"Проверяем…":"Создать товар"}</button>
            :isLink?<button type="button" className="product-attention-confirm" disabled={attentionBusy||createLoading||createBusy||!selectedId} onClick={()=>void approveAttention(a)}>Связать</button>
            :<button type="button" className="product-attention-confirm" onClick={()=>setAttentionExplanation(a)}>Подробнее</button>}
          </div></td>
        </tr>;
      })}
      {visibleDimensionAlerts.map(a=><tr key={`dim-${a.nm_id}`}><td className="product-attention-name"><strong>{a.title||a.article}</strong><span>{a.article}</span></td><td className="product-attention-nmid" title="Wildberries: nmID">{a.nm_id}</td><td>Габариты упаковки</td><td><div className="product-attention-problem-cell"><button type="button" className="product-attention-problem-link" onClick={()=>openDimensionDetail(a)}>Есть проблема ({a.problems.length})</button><ProblemHint description={a.problems.some(p=>p.code==="MARKETPLACE_DIMENSION_MISSING")?"На WB не заполнены некоторые габариты. Проверьте размеры в карточке маркетплейса.":a.problems.some(p=>p.code==="DIMENSION_MISMATCH")?"Габариты каталога и WB отличаются. Откройте подробности для сравнения и решения.":"В каталоге есть пустые размеры, которые можно заполнить из WB."}/></div></td><td>{products.find(p=>p.id===a.master_id)?.seller_article?`Связан с ${products.find(p=>p.id===a.master_id)?.seller_article}`:`Связан с товаром ID ${a.master_id}`}</td><td><button type="button" className="product-attention-confirm" onClick={()=>openDimensionDetail(a)}>Подробнее</button></td></tr>)}
      {visibleBarcodeAlerts.map(a=><tr key={`bar-${a.nm_id}`}><td className="product-attention-name"><strong>{a.title||a.article}</strong><span>{a.article}</span></td><td className="product-attention-nmid" title="Wildberries: nmID">{a.nm_id}</td><td>Штрихкод товара</td><td><div className="product-attention-problem-cell"><button type="button" className="product-attention-problem-link" onClick={()=>openBarcodeDetail(a)}>Есть проблема</button><ProblemHint description={a.problem==="MISSING_ON_WB"?"WB не передал штрихкод. Проверьте его в кабинете площадки.":a.problem==="MISSING_IN_CATALOG"?"Штрихкод отсутствует в нашем каталоге. Откройте подробности для выбора значения.":"Штрихкоды каталога и WB различаются. Нужна проверка."}/></div></td><td>{products.find(p=>p.id===a.master_id)?.seller_article?`Связан с ${products.find(p=>p.id===a.master_id)?.seller_article}`:`Связан с товаром ID ${a.master_id}`}</td><td><button type="button" className="product-attention-confirm" onClick={()=>openBarcodeDetail(a)}>Подробнее</button></td></tr>)}
      {!visibleAlerts.length&&!visibleDimensionAlerts.length&&!visibleBarcodeAlerts.length&&<tr><td colSpan={6} className="product-attention-empty">{openAlerts.length?"По вашему запросу карточки не найдены.":"Нет открытых конфликтов. Нажмите «Обновить сверку WB» для актуальной проверки."}</td></tr>}
      </tbody></table></div>
      <p className="product-attention-footnote">Габариты проверяются при нажатии «Обновить сверку WB». Список габаритов не сохраняется в БД и доступен до обновления страницы. Запись пустых размеров в наш каталог выполняется только после отдельного подтверждения.</p>
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
