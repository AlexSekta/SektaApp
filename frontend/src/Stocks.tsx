import {
  useEffect,
  useRef,
  useState
} from "react";

import * as XLSX from "xlsx";

import Loader from "./components/Loader";

import Toast, {
  type ToastType
} from "./components/Toast";

import "./Stocks.css";


interface Stock {
  date: string;
  marketplace: string;
  warehouse: string;
  warehouse_type: string;
  article: string;
  stock: number;
}


interface ToastRow {
  text: string;
  type: ToastType;
}

interface ToastState {
  message: string;
  type: ToastType;
  rows?: ToastRow[];
}


function Stocks() {

  const [
    stocks,
    setStocks
  ] = useState<Stock[]>([]);


  const [
    loading,
    setLoading
  ] = useState(false);


  const [
    lastUpdate,
    setLastUpdate
  ] = useState<string | null>(null);


  const [
    search,
    setSearch
  ] = useState("");


  const [
    toast,
    setToast
  ] = useState<ToastState | null>(null);


  const [
    showScrollTop,
    setShowScrollTop
  ] = useState(false);


  const tableScrollRef =
    useRef<HTMLDivElement>(null);


  // =====================================================
  // ФОРМАТ ДАТЫ
  // =====================================================

  const formatDate = (
    value: string | null
  ) => {

    if (!value) {
      return "нет данных";
    }


    const date = new Date(
      value.endsWith("Z")
        ? value
        : value + "Z"
    );


    if (
      Number.isNaN(
        date.getTime()
      )
    ) {

      return value;

    }


    return date.toLocaleString(
      "ru-RU",
      {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit"
      }
    );

  };


  // =====================================================
  // ЗАГРУЗКА ОСТАТКОВ
  // =====================================================

  const loadStocks =
    async () => {

      const response =
        await fetch(
          "http://127.0.0.1:8000/stocks"
        );


      if (!response.ok) {

        throw new Error(
          `Ошибка сервера: ${response.status}`
        );

      }


      const data =
        await response.json();


      if (!Array.isArray(data)) {

        throw new Error(
          "Сервер вернул некорректные данные остатков"
        );

      }


      setStocks(
        data
      );

    };


  // =====================================================
  // ДАТА ПОСЛЕДНЕГО ОБНОВЛЕНИЯ
  // =====================================================

  const loadLastUpdate =
    async () => {

      const response =
        await fetch(
          "http://127.0.0.1:8000/stocks/last-update"
        );


      if (!response.ok) {

        throw new Error(
          `Ошибка сервера: ${response.status}`
        );

      }


      const data =
        await response.json();


      setLastUpdate(
        data.last_update
      );

    };


  // =====================================================
  // ОБЩАЯ НЕЗАВИСИМАЯ СИНХРОНИЗАЦИЯ
  // =====================================================

  const syncStocks =
    async () => {

      if (loading) {
        return;
      }


      setLoading(
        true
      );


      try {

        const response =
          await fetch(
            "http://127.0.0.1:8000/stocks/sync",
            {
              method: "POST"
            }
          );


        if (!response.ok) {

          let message =
            `Ошибка сервера: ${response.status}`;


          try {

            const errorData =
              await response.json();


            if (
              errorData.message
            ) {

              message =
                errorData.message;

            }

          } catch {
            // Оставляем стандартное сообщение.
          }


          throw new Error(
            message
          );

        }


        const data =
          await response.json();


        /*
         * Даже при partial/error backend завершает
         * независимые синхронизации и возвращает результаты.
         * Поэтому перечитываем то, что успешно обновилось.
         */
        await Promise.all([
          loadStocks(),
          loadLastUpdate()
        ]);


        const updated =
          data.updated || {};


        const wb =
          updated.wb || {};

        const ozon =
          updated.ozon || {};

        const yandex =
          updated.yandex || {};


        const getMarketplaceStatus =
          (
            result: any
          ) => {

            /*
             * Ozon и Yandex имеют независимые FBS/FBO(FBY) шаги.
             * Источником истины для Toast считаем именно их статусы.
             * Это исключает ситуацию, когда верхний status устарел,
             * а оба дочерних шага уже успешно завершились.
             */
            const childStatuses = [
              result?.fbs?.status,
              result?.fbo?.status,
              result?.fby?.status
            ].filter(Boolean);

            if (childStatuses.length > 0) {

              if (childStatuses.every(
                (status: string) => status === "ok"
              )) {
                return "ok";
              }

              if (childStatuses.some(
                (status: string) => status === "ok"
              )) {
                return "partial";
              }

              return "error";
            }

            return result?.status || "error";
          };


        const formatMarketplace =
          (
            name: string,
            result: any
          ) => {

            const status =
              getMarketplaceStatus(result);

            const saved =
              Number(result?.saved ?? 0);

            const details: string[] = [];

            const appendDetail = (
              label: string,
              value: any
            ) => {
              if (value === undefined || value === null) {
                return;
              }

              const savedValue =
                typeof value === "object"
                  ? Number(value?.saved ?? 0)
                  : Number(value);

              details.push(
                `${label} - ${savedValue}`
              );
            };

            appendDetail("FBS", result?.fbs);
            appendDetail("FBO", result?.fbo);
            appendDetail("FBY", result?.fby);

            const suffix =
              details.length > 0
                ? ` ( ${details.join(" | ")} )`
                : "";

            if (status === "ok") {
              return `${name}: ${saved}${suffix}`;
            }

            if (status === "partial") {
              const errorCount = Array.isArray(result?.errors)
                ? result.errors.length
                : 0;

              const errorSuffix = errorCount > 0
                ? ` · ошибок: ${errorCount}`
                : "";

              return `${name}: частично (${saved})${suffix}${errorSuffix}`;
            }

            const firstError = Array.isArray(result?.errors)
              ? result.errors[0]?.error
              : null;

            if (firstError) {
              const compactError = String(firstError)
                .replace(/\s+/g, " ")
                .slice(0, 140);

              return `${name}: ошибка${suffix} — ${compactError}`;
            }

            return `${name}: ошибка${suffix}`;
          };


        const getRowType =
          (
            result: any
          ): ToastType => {

            const status =
              getMarketplaceStatus(result);

            if (status === "ok") {
              return "success";
            }

            if (status === "partial") {
              return "warning";
            }

            return "error";
          };

        const rows: ToastRow[] = [
          {
            text: formatMarketplace(
              "WB",
              wb
            ),
            type: getRowType(
              wb
            )
          },
          {
            text: formatMarketplace(
              "Ozon",
              ozon
            ),
            type: getRowType(
              ozon
            )
          },
          {
            text: formatMarketplace(
              "Yandex",
              yandex
            ),
            type: getRowType(
              yandex
            )
          }
        ];


        if (
          data.status === "ok"
        ) {

          setToast({
            type: "success",
            message:
              "Остатки обновлены.",
            rows
          });

          return;

        }


        if (
          data.status === "partial"
        ) {

          setToast({
            type: "warning",
            message:
              "Остатки обновлены частично.",
            rows
          });

          return;

        }


        setToast({
          type: "error",
          message:
            "Не удалось обновить остатки.",
          rows
        });


      } catch (error) {

        let message =
          "Не удалось обновить остатки";


        if (
          error instanceof TypeError
        ) {

          message =
            "Не удалось связаться с сервером. Проверьте, запущен ли backend.";

        } else if (
          error instanceof Error
        ) {

          message =
            error.message;

        }


        setToast({
          type: "error",
          message
        });


        console.error(
          error
        );


      } finally {

        setLoading(
          false
        );

      }

    };


  // =====================================================
  // ФИЛЬТР
  // =====================================================

  const filteredStocks =
    stocks.filter(
      item =>
        item.article
          .toLowerCase()
          .includes(
            search.toLowerCase()
          )
    );


  // =====================================================
  // EXCEL
  // =====================================================

  const exportExcel = () => {

    const data =
      filteredStocks.map(
        item => ({

          "Дата":
            formatDate(
              item.date
            ),

          "Маркетплейс":
            item.marketplace,

          "Склад":
            item.warehouse,

          "Тип склада":
            item.warehouse_type,

          "Артикул":
            item.article,

          "Остаток":
            item.stock

        })
      );


    const worksheet =
      XLSX.utils.json_to_sheet(
        data
      );


    const workbook =
      XLSX.utils.book_new();


    XLSX.utils.book_append_sheet(
      workbook,
      worksheet,
      "Остатки"
    );


    XLSX.writeFile(
      workbook,
      "Остатки.xlsx"
    );

  };


  // =====================================================
  // ПЕРВАЯ ЗАГРУЗКА
  // =====================================================

  useEffect(() => {

    const initialLoad =
      async () => {

        try {

          await Promise.all([
            loadStocks(),
            loadLastUpdate()
          ]);

        } catch (error) {

          const message =
            error instanceof TypeError
              ? (
                "Не удалось связаться с сервером. "
                + "Проверьте, запущен ли backend."
              )
              : error instanceof Error
                ? error.message
                : "Не удалось загрузить остатки";


          setToast({
            type: "error",
            message
          });

        }

      };


    initialLoad();

  }, []);


  // =====================================================
  // СКРОЛЛ ТАБЛИЦЫ
  // =====================================================

  const handleTableScroll = () => {

    const element =
      tableScrollRef.current;


    if (!element) {
      return;
    }


    setShowScrollTop(
      element.scrollTop > 200
    );

  };


  const scrollTableToTop = () => {

    tableScrollRef.current?.scrollTo({
      top: 0,
      behavior: "smooth"
    });

  };


  // =====================================================
  // UI
  // =====================================================

  return (

    <div className="container">

      <h1>
        История остатков
      </h1>


      <div className="toolbar">

        <div className="update-info">

          <span>
            Последнее обновление
          </span>

          <strong>
            {formatDate(lastUpdate)}
          </strong>

        </div>


        <div className="actions">

          <button
            type="button"
            onClick={syncStocks}
            disabled={loading}
          >

            {loading ? (

              <>

                <Loader
                  size="small"
                />

                <span>
                  Обновление...
                </span>

              </>

            ) : (

              "Обновить остатки"

            )}

          </button>


          <button
            type="button"
            onClick={exportExcel}
            disabled={loading}
          >
            Скачать Excel
          </button>

        </div>

      </div>


      <div className="filters">

        <input
          placeholder="Поиск артикула..."
          value={search}
          onChange={
            event =>
              setSearch(
                event.target.value
              )
          }
        />

      </div>


      <div className="table-card">

        <table className="stocks-header-table">

          <thead>

            <tr>

              <th>Дата</th>

              <th>Маркетплейс</th>

              <th>Склад</th>

              <th>Тип</th>

              <th>Артикул</th>

              <th>Остаток</th>

            </tr>

          </thead>

        </table>


        <div
          className="stocks-table-scroll"
          ref={tableScrollRef}
          onScroll={handleTableScroll}
        >

          <table className="stocks-body-table">

            <tbody>

              {
                filteredStocks.length > 0

                  ? filteredStocks.map(
                    (
                      item,
                      index
                    ) => (

                      <tr key={index}>

                        <td>
                          {formatDate(item.date)}
                        </td>

                        <td>
                          {item.marketplace}
                        </td>

                        <td>
                          {item.warehouse}
                        </td>

                        <td>
                          {item.warehouse_type}
                        </td>

                        <td>
                          {item.article}
                        </td>

                        <td>
                          {item.stock}
                        </td>

                      </tr>

                    )
                  )

                  : (

                    <tr>

                      <td colSpan={6}>
                        Нет данных
                      </td>

                    </tr>

                  )
              }

            </tbody>

          </table>

        </div>


        {showScrollTop && (

          <button
            type="button"
            className="stocks-scroll-top"
            onClick={scrollTableToTop}
            aria-label="Наверх таблицы"
            title="Наверх"
          >
            ↑
          </button>

        )}

      </div>


      {toast && (

        <Toast
          type={toast.type}
          message={toast.message}
          rows={toast.rows}
          onClose={() =>
            setToast(null)
          }
        />

      )}

    </div>

  );

}


export default Stocks;