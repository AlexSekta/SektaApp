import { useEffect, useState } from "react";
import Loader from "./components/Loader";
import Toast, { type ToastType } from "./components/Toast";
import "./Analytics.css";
import WBReviewResponseAnalytics from "./WBReviewResponseAnalytics";
import UnifiedSales from "./UnifiedSales";

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
          <section className="oos-overall-card">
            <div className="oos-overall-label">Общий Out of Stock</div>
            <div className="oos-overall-value">
              {data.overall.percent.toFixed(2)}%
            </div>
            <div className="oos-overall-detail">
              {data.overall.zero_products} из {data.overall.total_positions}
              {" позиций МП имеют нулевой остаток"}
            </div>
          </section>

          <section className="oos-grid">
            {["WB", "OZON", "YANDEX"].map((marketplace) => {
              const item = data.marketplaces[marketplace];
              if (!item) return null;
              return (
                <article className="oos-card" key={marketplace}>
                  <div className="oos-card-title">{labels[marketplace]}</div>
                  <div className="oos-card-percent">
                    {item.percent.toFixed(2)}%
                  </div>
                  <div className="oos-card-detail">
                    OOS: {item.zero_products} / {item.total_products}
                  </div>
                  <div className="oos-progress">
                    <div
                      className="oos-progress-fill"
                      style={{ width: `${Math.min(item.percent, 100)}%` }}
                    />
                  </div>
                </article>
              );
            })}
          </section>

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
