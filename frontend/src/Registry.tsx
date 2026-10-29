import {defaultStockView, stockViewEndpoint, type StockViewSettings} from "./stockViewSettings";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";

import Toast, {
  type ToastType
} from "./components/Toast";

import { createPortal } from "react-dom";

import * as XLSX from "xlsx";

import AddProductModal from "./components/AddProductModal";
import EditProductModal from "./components/EditProductModal";
import DeleteConfirmModal from "./components/DeleteConfirmModal";
import RegistryTable from "./components/RegistryTable";

import "./Registry.css";

interface ToastState {
  message: string;
  type: ToastType;
}


interface Recommendation {
  target: number;
  status: "none" | "increase" | "decrease" | "zero";
  reason: "ALLOCATION" | "LOW_1C" | "FBO_STOCK";
}

interface MarketplaceStock {
  total: number;
  fbo: number;
  fbs: number;
  fbs_managed: boolean;
  recommendation: Recommendation;
}

interface YandexStock {
  total: number;
  fby: number;
  fbs: number;
  fbs_managed: boolean;
  recommendation: Recommendation;
}

interface RegistryItem {
  id: number;
  article: string;
  name: string;
  group: string;
  wb: MarketplaceStock;
  ozon: MarketplaceStock;
  yandex: YandexStock;
  stock_1c: number;
  updated_at: string | null;
}


interface RegistryData {
  marketplace: RegistryItem[];
  finished: RegistryItem[];
  extra?: Record<string, RegistryItem[]>;
}


interface MenuPosition {
  top: number;
  left: number;
}


function Registry() {
  const [stockView,setStockView] = useState<StockViewSettings>(defaultStockView);
  useEffect(()=>{fetch(stockViewEndpoint,{credentials:"include"}).then(async r=>{if(!r.ok)throw Error();return r.json()}).then(setStockView).catch(()=>setToast({type:"error",message:"Не удалось загрузить настройки отображения остатков"}));},[]);


  const [
    deletingProduct,
    setDeletingProduct
  ] = useState(false);

  const [
    toast,
    setToast
  ] = useState<ToastState | null>(null);

  const [registry, setRegistry] =
    useState<RegistryData>({
      marketplace: [],
      finished: []
    });


  const [
    articleSearch,
    setArticleSearch
  ] = useState("");


  const [
    marketplaceOpen,
    setMarketplaceOpen
  ] = useState(true);


  const [
    finishedOpen,
    setFinishedOpen
  ] = useState(true);


  const [
    menuOpen,
    setMenuOpen
  ] = useState<number | null>(null);


  const [
    menuPosition,
    setMenuPosition
  ] = useState<MenuPosition | null>(null);


  const [
    addModalOpen,
    setAddModalOpen
  ] = useState(false);


  const [
    addProductGroup,
    setAddProductGroup
  ] = useState("");


  const [
    editProduct,
    setEditProduct
  ] = useState<RegistryItem | null>(null);


  const [
    deleteProductId,
    setDeleteProductId
  ] = useState<number | null>(null);


  const [
    stockChanges,
    setStockChanges
  ] = useState<Record<string, string>>({});

  const [
    savingStocks,
    setSavingStocks
  ] = useState<Record<string, boolean>>({});


  const menuRef =
    useRef<HTMLDivElement>(null);


  const [syncingStocks, setSyncingStocks] = useState(false);
  const [updateModalOpen, setUpdateModalOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadingStocks, setUploadingStocks] = useState(false);
  const [extraOpen, setExtraOpen] = useState<Record<string, boolean>>({});
  const [warehouseModal, setWarehouseModal] = useState(false);
  const [warehouseName, setWarehouseName] = useState("");
  const [warehouseToDelete, setWarehouseToDelete] = useState<string | null>(null);
  const [warehouseDeleting, setWarehouseDeleting] = useState(false);
  const [localWarehouses, setLocalWarehouses] = useState<{name: string; can_delete: boolean}[]>([]);
  const loadWarehouses = useCallback(async () => {
    try { const r = await fetch("http://127.0.0.1:8000/local-warehouses", { credentials: "include" }); if (r.ok) setLocalWarehouses(await r.json()); } catch { /* toast on explicit actions */ }
  }, []);
  useEffect(() => { void loadWarehouses(); }, [loadWarehouses]);
  const downloadTemplate = async () => {
    try {
      const r=await fetch("http://127.0.0.1:8000/local-warehouses/template",{ credentials:"include" });
      if (!r.ok) throw new Error("Не удалось создать шаблон");
      const url=URL.createObjectURL(await r.blob());
      const a=document.createElement("a"); a.href=url;a.download="Шаблон_остатков.xlsx";a.click();URL.revokeObjectURL(url);
    } catch(e) {setToast({type:"error",message:e instanceof Error?e.message:"Ошибка шаблона"});}
  };
  const submitStocks = async () => {
    if (uploadingStocks || syncingStocks) return;
    setUploadingStocks(true);
    try {
      let importWarning = "";
      let updatedCount = 0;
      if (selectedFile) {
        const form=new FormData();form.append("file",selectedFile);
        const r=await fetch("http://127.0.0.1:8000/local-warehouses/import",{method:"POST",credentials:"include",body:form});
        const result=await r.json().catch(()=>({}));
        if(!r.ok) throw new Error(typeof result.detail==="string"?result.detail:"Ошибка импорта Excel");
        updatedCount = result.updated;
        if(result.unknown_count) importWarning=`Не добавлены ${result.unknown_count} строк: ${result.unknown.join("; ")}${result.unknown_count>100?" …":""}`;
      }
      setUpdateModalOpen(false);setSelectedFile(null);
      await refreshStocks();
      if(importWarning) setToast({type:"error",message:`Обновлено ${updatedCount}. ${importWarning}`});
    } catch(e) {setToast({type:"error",message:e instanceof Error?e.message:"Не удалось загрузить остатки"});}
    finally {setUploadingStocks(false);}
  };
  const addWarehouse = async () => {
    try {
      const r=await fetch("http://127.0.0.1:8000/local-warehouses",{method:"POST",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:warehouseName})});
      const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||"Ошибка создания склада");
      setWarehouseName("");await loadWarehouses();await loadRegistry();setToast({type:"success",message:"Склад добавлен"});
    } catch(e){setToast({type:"error",message:e instanceof Error?e.message:"Ошибка"});}
  };
  const removeWarehouse=async(name:string)=>{
    setWarehouseDeleting(true);
    try {
      const r=await fetch(`http://127.0.0.1:8000/local-warehouses/${encodeURIComponent(name)}`,{method:"DELETE",credentials:"include"});
      const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||"Не удалось удалить склад");
      setWarehouseToDelete(null);await loadWarehouses();await loadRegistry();setToast({type:"success",message:`Склад «${name}» удалён`});
    } catch(e){setToast({type:"error",message:e instanceof Error?e.message:"Ошибка"});}
    finally {setWarehouseDeleting(false);}
  };


  const refreshStocks = async () => {
    if (syncingStocks) return;
    setSyncingStocks(true);
    try {
      const response = await fetch("http://127.0.0.1:8000/stocks/sync", { method: "POST", credentials: "include" });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.message || body.detail || `Ошибка обновления: ${response.status}`);
      }
      const result = await response.json().catch(() => ({}));
      await loadRegistry();
      const statuses = [result?.updated?.wb, result?.updated?.ozon, result?.updated?.yandex].filter(Boolean);
      const errors = statuses.filter((v: { status?: string }) => v.status === "error");
      setToast({ type: errors.length ? "error" : "success", message: errors.length ? "Обновление завершено с ошибками отдельных площадок. Проверьте историю остатков." : "Обновление остатков завершено" });
    } catch (error) {
      setToast({ type: "error", message: error instanceof Error ? error.message : "Не удалось обновить остатки" });
    } finally {
      setSyncingStocks(false);
    }
  };

  const loadRegistry =
    useCallback(async () => {

      const response = await fetch(
        "http://127.0.0.1:8000/registry"
      );


      if (!response.ok) {

        console.error(
          "Ошибка загрузки реестра"
        );

        return;

      }


      const data = await response.json();


      setRegistry(data);

    }, []);


  useEffect(() => {

    loadRegistry();

  }, [loadRegistry]);


  useEffect(() => {

    const closeMenu = (
      event: MouseEvent
    ) => {

      if (
        menuRef.current &&
        !menuRef.current.contains(
          event.target as Node
        )
      ) {

        setMenuOpen(null);

      }

    };


    document.addEventListener(
      "mousedown",
      closeMenu
    );


    return () => {

      document.removeEventListener(
        "mousedown",
        closeMenu
      );

    };

  }, []);


  const updateStock =
    useCallback(async (
      article: string,
      marketplace: string
    ) => {

      const key =
        `${article}_${marketplace}`;


      const value =
        stockChanges[key];


      if (
        value === undefined ||
        value === ""
      ) {

        return;

      }


      const stock =
        Number(value);


      if (
        !Number.isInteger(stock) ||
        stock < 0
      ) {

        console.error(
          "Некорректный остаток"
        );

        return;

      }


      /*
       * Включаем Loader только
       * у конкретного остатка.
       */
      setSavingStocks(prev => ({

        ...prev,

        [key]: true

      }));


      try {

        if (marketplace === "1C") {
          const item = Object.values(registry?.extra || {}).flat().concat(registry?.marketplace || [], registry?.finished || []).find(p => p.article === article);
          if (!item) throw new Error("Товар не найден. Обновите страницу.");
          const response = await fetch("http://127.0.0.1:8000/local-warehouses/stock", {
            method: "PUT", credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ article, group: item.group, stock, expected_stock: item.stock_1c })
          });
          const data = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось обновить остаток 1С");
          setStockChanges(prev => { const next = { ...prev }; delete next[key]; return next; });
          await loadRegistry();
          setToast({ type: "success", message: `Остаток 1С для ${article}: ${data.previous_stock} → ${data.stock} шт.` });
          return;
        }

        const response = await fetch(
          "http://127.0.0.1:8000/stocks/update",
          {
            method: "PUT",

            headers: {
              "Content-Type":
                "application/json"
            },

            body: JSON.stringify({
              article,
              marketplace,
              stock
            })
          }
        );


        /*
         * Например:
         * 404 / 500 / 503
         */
        if (!response.ok) {

          throw new Error(
            `Ошибка сервера: ${response.status}`
          );

        }


        const data =
          await response.json();


        /*
         * Backend ответил HTTP 200,
         * но операция не выполнена.
         */
        if (data.status !== "ok") {

          throw new Error(
            data.message ||
            "Остаток не обновлён"
          );

        }


        /*
         * Успех.
         *
         * Только теперь удаляем
         * пользовательское изменение.
         */
        setStockChanges(prev => {

          const updated = {
            ...prev
          };


          delete updated[key];


          return updated;

        });


        /*
         * Получаем подтверждённые
         * значения из backend.
         */
        await loadRegistry();

        setToast({
          type: "success",
          message:
            `Остаток ${article} на ${marketplace} обновлён`
        });

      } catch (error) {

        /*
         * Возвращаем последнее
         * подтверждённое значение.
         */
        setStockChanges(prev => {

          const updated = {
            ...prev
          };

          delete updated[key];

          return updated;

        });


        const message =
          error instanceof Error
            ? error.message
            : "Не удалось обновить остаток";


        setToast({
          type: "error",
          message
        });


        console.error(
          error
        );

      } finally {

        /*
         * Loader должен исчезнуть
         * и при успехе, и при ошибке.
         */
        setSavingStocks(prev => {

          const updated = {
            ...prev
          };


          delete updated[key];


          return updated;

        });

      }

    }, [
      stockChanges,
      loadRegistry
    ]);


  const deleteProduct =
    async (
      id: number
    ) => {

      if (deletingProduct) {
        return;
      }


      const allProducts = [
        ...registry.marketplace,
        ...registry.finished
      ];


      const product =
        allProducts.find(
          item =>
            item.id === id
        );


      setDeletingProduct(true);


      try {

        const response = await fetch(
          `http://127.0.0.1:8000/master-products/${id}`,
          {
            method: "DELETE"
          }
        );


        if (!response.ok) {

          throw new Error(
            `Ошибка сервера: ${response.status}`
          );

        }


        const data =
          await response.json();


        if (data.status !== "ok") {

          throw new Error(
            data.message ||
            "Не удалось удалить товар"
          );

        }


        setDeleteProductId(
          null
        );


        await loadRegistry();


        setToast({
          type: "success",
          message:
            product
              ? `Товар ${product.article} удалён`
              : "Товар удалён"
        });


      } catch (error) {

        const message =
          error instanceof TypeError
            ? "Не удалось связаться с сервером"
            : error instanceof Error
              ? error.message
              : "Не удалось удалить товар";


        setToast({
          type: "error",
          message
        });


      } finally {

        setDeletingProduct(
          false
        );

      }

    };


  /*
   * Всегда показываем товары по артикулу
   * в естественном порядке:
   * HS001, HS002, HS010, HS100.
   *
   * Поиск применяется одновременно
   * к обоим разделам реестра.
   */
  const sortedFilteredRegistry = useMemo(() => {

    const query =
      articleSearch
        .trim()
        .toLocaleLowerCase();

    const sortByArticle = (
      a: RegistryItem,
      b: RegistryItem
    ) =>
      a.article.localeCompare(
        b.article,
        "ru",
        {
          numeric: true,
          sensitivity: "base"
        }
      );

    const filterItems = (
      items: RegistryItem[]
    ) =>
      items
        .filter(item =>
          !query ||
          item.article
            .toLocaleLowerCase()
            .includes(query)
        )
        .sort(sortByArticle);

    return {
      marketplace: filterItems(
        [...registry.marketplace]
      ),
      finished: filterItems(
        [...registry.finished]
      ),
      extra: Object.fromEntries(Object.entries(registry.extra || {}).map(([name,items])=>[name,filterItems([...items])]))
    };

  }, [
    registry,
    articleSearch
  ]);


  const exportExcel = useCallback(() => {

    const items = [
      ...sortedFilteredRegistry.marketplace,
      ...sortedFilteredRegistry.finished,
      ...Object.values(sortedFilteredRegistry.extra || {}).flat()
    ];

    const rows = items.map(item => ({
      "Артикул": item.article,
      "Наименование": item.name,
      "Остаток 1С": Number(item.stock_1c) || 0,
      "WB": Number(item.wb?.total) || 0,
      "OZON": Number(item.ozon?.total) || 0,
      "ЯМаркет": Number(item.yandex?.total) || 0
    }));

    const worksheet =
      XLSX.utils.json_to_sheet(rows);

    worksheet["!cols"] = [
      { wch: 16 },
      { wch: 55 },
      { wch: 14 },
      { wch: 10 },
      { wch: 10 },
      { wch: 12 }
    ];

    const workbook =
      XLSX.utils.book_new();

    XLSX.utils.book_append_sheet(
      workbook,
      worksheet,
      "Остатки"
    );

    XLSX.writeFile(
      workbook,
      "Реестр_остатков.xlsx"
    );

  }, [
    sortedFilteredRegistry
  ]);


  const openMenu =
    useCallback((
      event: React.MouseEvent<HTMLButtonElement>,
      id: number
    ) => {

      const rect =
        event.currentTarget
          .getBoundingClientRect();


      setMenuPosition({
        top: rect.bottom + 5,
        left: rect.left
      });


      setMenuOpen(prev =>
        prev === id
          ? null
          : id
      );

    }, []);


  return (

    <div className="container">

      <h1>
        Остатки
      </h1>


      <div className="registry-toolbar">

        <div className="registry-search">

          <input
            type="text"
            value={articleSearch}
            onChange={event =>
              setArticleSearch(
                event.target.value
              )
            }
            placeholder="Поиск по артикулу..."
            aria-label="Поиск по артикулу"
          />

          {articleSearch && (
            <button
              type="button"
              className="registry-search-clear"
              onClick={() =>
                setArticleSearch("")
              }
              aria-label="Очистить поиск"
              title="Очистить поиск"
            >
              ×
            </button>
          )}

        </div>


        <div className="registry-toolbar-actions">
          <button type="button" className="registry-export-button" onClick={() => setUpdateModalOpen(true)} disabled={syncingStocks}>
            {syncingStocks ? "Обновление…" : "Обновить"}
          </button>
          <button
            type="button"
            className="registry-export-button"
            onClick={exportExcel}
            title="Скачать текущие остатки в Excel"
          >
            Скачать Excel
          </button>
          {stockView.fbs && (
            <button type="button" className="registry-export-button" onClick={() => setWarehouseModal(true)}>
              Управление складами
            </button>
          )}
        </div>
      </div>


      {stockView.fbs && <div className="registry-block">

        <div
          className="registry-title"
          onClick={() =>
            setMarketplaceOpen(
              prev => !prev
            )
          }
        >

          <div className="registry-title-main">

            <span className="arrow">
              {marketplaceOpen
                ? "▼"
                : "▶"
              }
            </span>

            <span>
              Склад Маркетплейс
            </span>

          </div>


          <button
            type="button"
            className="registry-add-button"
            onClick={(event) => {

              event.stopPropagation();

              setAddProductGroup(
                "Маркетплейс"
              );

              setAddModalOpen(
                true
              );

            }}
            aria-label="Добавить товар на склад Маркетплейс"
            title="Добавить товар"
          >
            +
          </button>

        </div>


        {marketplaceOpen && (

          <RegistryTable
            view={stockView}
            items={sortedFilteredRegistry.marketplace}
            stockChanges={stockChanges}
            setStockChanges={
              setStockChanges
            }
            savingStocks={
              savingStocks
            }
            onSaveStock={updateStock}
            onOpenMenu={openMenu}
          />

        )}

      </div>}

      {stockView.fbs && <div className="registry-block">

        <div
          className="registry-title"
          onClick={() =>
            setFinishedOpen(
              prev => !prev
            )
          }
        >

          <div className="registry-title-main">

            <span className="arrow">
              {finishedOpen
                ? "▼"
                : "▶"
              }
            </span>

            <span>
              Склад Готовая продукция
            </span>

          </div>


          <button
            type="button"
            className="registry-add-button"
            onClick={(event) => {

              event.stopPropagation();

              setAddProductGroup(
                "Готовая продукция"
              );

              setAddModalOpen(
                true
              );

            }}
            aria-label="Добавить товар на склад Готовая продукция"
            title="Добавить товар"
          >
            +
          </button>

        </div>


        {finishedOpen && (

          <RegistryTable
            view={stockView}
            items={sortedFilteredRegistry.finished}
            stockChanges={stockChanges}
            setStockChanges={
              setStockChanges
            }
            savingStocks={
              savingStocks
            }
            onSaveStock={updateStock}
            onOpenMenu={openMenu}
          />

        )}

      </div>}

      {!stockView.fbs && <div className="registry-block">
        <div className="registry-title"><div className="registry-title-main"><span>Товары маркетплейсов (FBO / FBY)</span></div></div>
        <RegistryTable view={stockView} items={[...sortedFilteredRegistry.marketplace,...sortedFilteredRegistry.finished,...Object.values(sortedFilteredRegistry.extra || {}).flat()]} stockChanges={stockChanges} setStockChanges={setStockChanges} savingStocks={savingStocks} onSaveStock={updateStock} onOpenMenu={openMenu}/>
      </div>}
      {updateModalOpen && (
        <div className="local-modal-backdrop" onClick={() => !uploadingStocks && setUpdateModalOpen(false)}>
          <div className="local-modal" role="dialog" aria-modal="true" aria-label="Обновление остатков" onClick={e=>e.stopPropagation()}>
            <h2>Обновление остатков</h2>
            <p>Скачайте шаблон складов и артикулов, укажите количество и загрузите файл. Пустая ячейка и #Н/Д означают ноль.</p>
            <button type="button" onClick={() => void downloadTemplate()}>Скачать шаблон Excel</button>
            <label className="local-dropzone" onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();const f=e.dataTransfer.files[0];if(f?.name.toLowerCase().endsWith(".xlsx"))setSelectedFile(f);else setToast({type:"error",message:"Требуется файл .xlsx"});}}>
              <span className="local-dropzone-title">Перетащите Excel сюда или выберите файл</span>
              <span className="local-file-picker"><span className="local-file-plus" aria-hidden="true">+</span><span>{selectedFile ? "Заменить файл" : "Выбрать файл"}</span></span>
              {selectedFile && <span className="local-selected-file" title={selectedFile.name}>{selectedFile.name}</span>}
              <input className="local-file-input" type="file" accept=".xlsx" aria-label="Выбрать Excel-файл с остатками" onChange={e=>setSelectedFile(e.target.files?.[0]||null)} />
            </label>
            <p>Неизвестные артикулы будут пропущены. Указанные известные позиции обновятся. Остальные позиции сохранят прежние значения.</p>
            <div className="local-modal-buttons">
              <button type="button" onClick={()=>setUpdateModalOpen(false)} disabled={uploadingStocks}>Отмена</button>
              <button type="button" disabled={uploadingStocks || syncingStocks} onClick={()=>void submitStocks()}>{uploadingStocks||syncingStocks?"Обновление…":"Обновить остатки"}</button>
            </div>
          </div>
        </div>
      )}
      {warehouseModal && (
        <div className="local-modal-backdrop" onClick={()=>setWarehouseModal(false)}>
          <div className="local-modal" role="dialog" aria-modal="true" aria-label="Управление складами" onClick={e=>e.stopPropagation()}>
            <h2>Склады организации</h2>
            {localWarehouses.map(w=><div className="local-warehouse-row" key={w.name}><span>{w.name}</span>{w.can_delete&&<button type="button" onClick={()=>setWarehouseToDelete(w.name)}>Удалить</button>}</div>)}
            <div className="local-modal-buttons"><input value={warehouseName} maxLength={100} placeholder="Название нового склада" onChange={e=>setWarehouseName(e.target.value)}/><button type="button" disabled={!warehouseName.trim()} onClick={()=>void addWarehouse()}>Добавить</button></div>
            <button type="button" onClick={()=>setWarehouseModal(false)}>Закрыть</button>
          </div>
        </div>
      )}

      {warehouseToDelete !== null && (
        <div className="local-modal-backdrop" onClick={() => {if(!warehouseDeleting)setWarehouseToDelete(null);}}>
          <div className="local-modal" role="alertdialog" aria-modal="true" aria-label="Подтверждение удаления склада" onClick={e=>e.stopPropagation()}>
            <h2>Удалить склад?</h2>
            <p>Вы уверены, что хотите удалить склад «{warehouseToDelete}»?</p>
            <p>Удаление возможно только если на складе нет привязанных товаров и ненулевых остатков.</p>
            <div className="local-modal-buttons">
              <button type="button" disabled={warehouseDeleting} onClick={()=>setWarehouseToDelete(null)}>Нет, отмена</button>
              <button type="button" disabled={warehouseDeleting} onClick={()=>void removeWarehouse(warehouseToDelete)}>{warehouseDeleting?"Удаление…":"Да, удалить"}</button>
            </div>
          </div>
        </div>
      )}
      {stockView.fbs && Object.entries(sortedFilteredRegistry.extra || {}).map(([name,items])=>(
        <div className="registry-block" key={name}>
          <div className="registry-title" onClick={() => setExtraOpen(prev => ({...prev, [name]: prev[name] === false ? true : false}))}>
            <div className="registry-title-main"><span className="arrow">{extraOpen[name] === false ? "▶" : "▼"}</span><span>Склад {name}</span></div>
            <button type="button" className="registry-add-button" aria-label={`Добавить товар на склад ${name}`} title="Добавить товар"
              onClick={(event) => { event.stopPropagation(); setAddProductGroup(name); setAddModalOpen(true); }}>+</button>
          </div>
          {extraOpen[name] !== false && <RegistryTable view={stockView} items={items} stockChanges={stockChanges} setStockChanges={setStockChanges} savingStocks={savingStocks} onSaveStock={updateStock} onOpenMenu={openMenu} />}
        </div>
      ))}
      {addModalOpen && (

        <AddProductModal
          initialGroup={addProductGroup}
          warehouses={localWarehouses.map(w => w.name)}

          onClose={() => {

            setAddModalOpen(false);

            setAddProductGroup("");

          }}

          onAdded={async article => {

            setAddModalOpen(
              false
            );

            setAddProductGroup(
              ""
            );

            await loadRegistry();

            setToast({
              type: "success",
              message:
                `Товар ${article} добавлен в реестр`
            });

          }}

          onError={message => {

            setToast({
              type: "error",
              message
            });

          }}
        />

      )}


      {editProduct && (

        <EditProductModal
          productId={
            editProduct.id
          }

          currentGroup={
            editProduct.group
          }
          warehouses={localWarehouses.map(w => w.name)}

          onClose={() =>
            setEditProduct(null)
          }

          onUpdated={async () => {

            const article =
              editProduct.article;

            setEditProduct(
              null
            );

            await loadRegistry();

            setToast({
              type: "success",
              message:
                `Товар ${article} изменён`
            });

          }}

          onError={message => {

            setToast({
              type: "error",
              message
            });

          }}
        />

      )}


      {deleteProductId !== null && (

        <DeleteConfirmModal
          loading={
            deletingProduct
          }

          onClose={() => {

            if (!deletingProduct) {

              setDeleteProductId(
                null
              );

            }

          }}

          onConfirm={() =>
            deleteProduct(
              deleteProductId
            )
          }
        />

      )}


      {menuOpen !== null &&
        menuPosition &&

        createPortal(

          <div
            ref={menuRef}
            className="portal-menu"
            style={{
              top: menuPosition.top,
              left: menuPosition.left
            }}
          >

            <button
              type="button"
              onClick={() => {

                const allProducts = [
                  ...registry.marketplace,
                  ...registry.finished,
                  ...Object.values(registry.extra || {}).flat()
                ];


                const product =
                  allProducts.find(
                    item =>
                      item.id === menuOpen
                  );


                if (product) {

                  setEditProduct(
                    product
                  );

                }


                setMenuOpen(null);

              }}
            >
              Изменить
            </button>


            <button
              type="button"
              onClick={() => {

                setDeleteProductId(
                  menuOpen
                );

                setMenuOpen(null);

              }}
            >
              Удалить
            </button>

          </div>,

          document.body

        )
      }

      {toast && (

        <Toast
          type={toast.type}
          message={toast.message}
          onClose={() =>
            setToast(null)
          }
        />

      )}

    </div>

  );

}


export default Registry;