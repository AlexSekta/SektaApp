import { useEffect, useState } from "react";
import Loader from "./components/Loader";
import Toast, { type ToastType } from "./components/Toast";
import "./Analytics.css";
import WBReviewResponseAnalytics from "./WBReviewResponseAnalytics";
import UnifiedSales from "./UnifiedSales";
import PenaltiesDashboard from "./PenaltiesDashboard";
import { downloadWorkbook } from "./ExcelDownload";

interface MarketplaceOOS {
  zero_products: number;
  total_products: number;
  percent: number;
}

interface OOSData {
  status: string;
  total_products: number;
  total_positions: number;
  marketplaces: Record<string, MarketplaceOOS>;
  overall: {
    zero_products: number;
    total_positions: number;
    percent: number;
  };
}

interface OOSDetailItem {
  article: string;
  name: string;
  oos_since: string | null;
  days_oos: number | null;
}

interface OOSDetailResponse {
  items: OOSDetailItem[];
  count: number;
  note: string;
}

interface ToastState {
  message: string;
  type: ToastType;
}

const labels: Record<string, string> = {
  WB: "WB",
  OZON: "OZON",
  YANDEX: "Я.Маркет"
};

function Analytics() {
  const [data, setData] = useState<OOSData | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeOOS, setActiveOOS] = useState<string | null>(null);
  const [oosDetails, setOosDetails] = useState<OOSDetailResponse | null>(null);
  const [oosLoading, setOosLoading] = useState(false);
  const [oosError, setOosError] = useState("");
  const [toast, setToast] = useState<ToastState | null>(null);
  const load = async () => {
    setLoading(true);
    try {
      const oosResponse = await fetch("http://127.0.0.1:8000/analytics/out-of-stock", { credentials: "include" });

      if (!oosResponse.ok) {
        throw new Error(`Ошибка сервера: ${oosResponse.status}`);
      }

      setData(await oosResponse.json());
    } catch (error) {
      const message = error instanceof TypeError
        ? "Не удалось связаться с backend."
        : error instanceof Error
          ? error.message
          : "Не удалось загрузить аналитику";
      setToast({ type: "error", message });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!activeOOS) {
      setOosDetails(null);
      setOosError("");
      return;
    }
    const controller = new AbortController();
    setOosLoading(true);
    setOosDetails(null);
    setOosError("");
    fetch(`http://127.0.0.1:8000/analytics/out-of-stock/details?marketplace=${activeOOS}`, {
      credentials: "include",
      signal: controller.signal,
    })
      .then(async response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<OOSDetailResponse>;
      })
      .then(setOosDetails)
      .catch(error => {
        if (!controller.signal.aborted) setOosError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => { if (!controller.signal.aborted) setOosLoading(false); });
    return () => controller.abort();
  }, [activeOOS]);

  const exportOOS = () => {
    if (!activeOOS || !oosDetails) return;
    downloadWorkbook(`OOS_${activeOOS}_${new Date().toISOString().slice(0, 10)}.xlsx`, [{
      name: 'Нет в наличии',
      headers: ['Маркетплейс', 'Артикул', 'Название', 'Дата OOS', 'Нет в наличии, дней'],
      rows: oosDetails.items.map(item => [labels[activeOOS] || activeOOS, item.article, item.name, item.oos_since ? formatOOSDate(item.oos_since) : '', item.days_oos]),
      widths: [18, 22, 60, 18, 24],
    }]);
  };

  const formatOOSDate = (value: string | null) => value
    ? value.split("-").reverse().join(".")
    : "—";

  return (
    <div className="analytics-page">
      <div className="analytics-header">
        <div>
          <h1>Аналитика</h1>
          <p>
            Out of Stock — доля активных товаров,
            у которых общий остаток на маркетплейсе равен 0.
          </p>
        </div>
        <button
          type="button"
          className="analytics-refresh"
          onClick={() => void load()}
          disabled={loading}
        >
          {loading ? (
            <><Loader size="small" /><span>Обновление...</span></>
          ) : "Обновить"}
        </button>
      </div>

      {loading && !data ? (
        <div className="analytics-loading">
          <Loader size="small" />
          <span>Загрузка аналитики...</span>
        </div>
      ) : data ? (
        <>
          <UnifiedSales />
          <PenaltiesDashboard />
          <section className="oos-combined-card" aria-label="Out of Stock по маркетплейсам">
            <div className="oos-summary">
              <div className="oos-overall-label">Общий Out of Stock</div>
              <div className="oos-overall-value">{data.overall.percent.toFixed(2)}%</div>
            </div>
            <div className="oos-compact-grid">
              {["WB", "OZON", "YANDEX"].map((marketplace) => {
                const item = data.marketplaces[marketplace];
                if (!item) return null;
                return (
                  <button
                    type="button"
                    className={`oos-compact-item oos-compact-button${activeOOS === marketplace ? " is-active" : ""}`}
                    key={marketplace}
                    aria-expanded={activeOOS === marketplace}
                    onClick={() => setActiveOOS(previous => previous === marketplace ? null : marketplace)}
                  >
                    <div className="oos-compact-title">{labels[marketplace]}</div>
                    <div className="oos-compact-percent">{item.percent.toFixed(2)}%</div>
                    <div className="oos-compact-detail">OOS: {item.zero_products} / {item.total_products}</div>
                    <div className="oos-progress">
                      <div className="oos-progress-fill" style={{ width: `${Math.min(Math.max(item.percent, 0), 100)}%` }} />
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          {activeOOS && (
            <section className="oos-details-panel" aria-live="polite">
              <div className="oos-details-heading">
                <div>
                  <h2>Нет в наличии — {labels[activeOOS]}</h2>
                  <p>Активные товары с нулевым суммарным остатком по маркетплейсу</p>
                </div>
                <div className="oos-details-actions">
                  <button type="button" className="dashboard-xlsx-button" onClick={exportOOS} disabled={!oosDetails || oosLoading || Boolean(oosError)}>Скачать Excel</button>
                  <button type="button" className="oos-details-close" onClick={() => setActiveOOS(null)} aria-label="Закрыть детализацию">×</button>
                </div>
              </div>
              {oosLoading ? (
                <p className="oos-details-message">Загружаем историю остатков…</p>
              ) : oosError ? (
                <p className="oos-details-message oos-details-error">Не удалось загрузить детализацию: {oosError}</p>
              ) : oosDetails ? (
                <>
                  <div className="oos-details-table-wrap">
                    <table className="oos-details-table">
                      <thead>
                        <tr><th>Артикул</th><th>Название</th><th>Дата OOS</th><th>Нет в наличии</th></tr>
                      </thead>
                      <tbody>
                        {oosDetails.items.map(item => (
                          <tr key={item.article}>
                            <td>{item.article}</td>
                            <td>{item.name}</td>
                            <td>{formatOOSDate(item.oos_since)}</td>
                            <td>{item.days_oos === null ? "—" : `${item.days_oos} дн.`}</td>
                          </tr>
                        ))}
                        {!oosDetails.items.length && <tr><td colSpan={4} className="oos-details-message">Все товары в наличии.</td></tr>}
                      </tbody>
                    </table>
                  </div>
                  <p className="oos-details-note">{oosDetails.note}</p>
                </>
              ) : null}
            </section>
          )}

          <WBReviewResponseAnalytics />

          <section className="oos-info-card">
            <h2>Как считается</h2>
            <div className="oos-formula">
              <span>Нулевые позиции</span>
              <strong>÷</strong>
              <span>Активные товары × 3 МП</span>
              <strong>× 100%</strong>
            </div>
            <p>
              WB = FBO + FBS. Ozon = FBO + FBS.
              Я.Маркет = FBY + FBS. Если общий остаток больше нуля,
              позиция не считается Out of Stock.
            </p>
          </section>
        </>
      ) : null}

      {toast && (
        <Toast
          type={toast.type}
          message={toast.message}
          onClose={() => setToast(null)}
        />
      )}
    </div>
  );
}

export default Analytics;
