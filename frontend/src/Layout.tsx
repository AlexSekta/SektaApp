import {
  Link,
  Outlet,
  useLocation
} from "react-router-dom";

import {
  useEffect,
  useState
} from "react";

import "./Layout.css";
import { useAuth } from "./AuthContext";


function Layout() {

  const { user, logout } = useAuth();
  const location = useLocation();

  const [
    reviewsOpen,
    setReviewsOpen
  ] = useState(
    location.pathname.startsWith("/reviews")
  );

  const [stocksOpen, setStocksOpen] = useState(location.pathname === "/registry" || location.pathname === "/stocks");

  const [
    analyticsOpen,
    setAnalyticsOpen
  ] = useState(
    location.pathname.startsWith("/analytics")
  );


  const [
    wbCommunicationUnansweredCount,
    setWbCommunicationUnansweredCount
  ] = useState(0);

  const [
    yandexCommunicationUnansweredCount,
    setYandexCommunicationUnansweredCount
  ] = useState(0);
  const appName = user?.organization_name || "SEKTA";
  const [fbsShown, setFbsShown] = useState(true);
  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      fetch(`${window.location.protocol}//${window.location.hostname}:8000/settings/stock-view`, {credentials:"include"})
        .then(r => {if (!r.ok) throw new Error("Settings unavailable"); return r.json();})
        .then(d => {if (!cancelled) setFbsShown(Boolean(d.fbs));})
        .catch(() => {});
    };
    refresh();
    window.addEventListener("stock-view-updated", refresh);
    return () => {cancelled = true; window.removeEventListener("stock-view-updated", refresh);};
  }, [location.pathname, user?.organization_id]);


  useEffect(() => {

    const loadCommunicationCount = async () => {

      try {

        const [
          wbReviewsResponse,
          wbQuestionsResponse,
          yandexReviewsResponse,
          yandexQuestionsResponse
        ] = await Promise.all([
          fetch(
            "http://127.0.0.1:8000/wb/reviews?status=unanswered&take=1&skip=0&order=dateDesc"
          ),
          fetch(
            "http://127.0.0.1:8000/wb/questions/count"
          ),
          fetch(
            "http://127.0.0.1:8000/yandex/reviews/count"
          ),
          fetch(
            "http://127.0.0.1:8000/yandex/questions/count"
          )
        ]);

        let wbReviewsCount = 0;
        let wbQuestionsCount = 0;
        let yandexReviewsCount = 0;
        let yandexQuestionsCount = 0;

        if (wbReviewsResponse.ok) {
          const data = await wbReviewsResponse.json();
          const count = Number(data.count_unanswered);
          if (Number.isFinite(count) && count >= 0) {
            wbReviewsCount = count;
          }
        }

        if (wbQuestionsResponse.ok) {
          const data = await wbQuestionsResponse.json();
          const count = Number(data.count_unanswered);
          if (Number.isFinite(count) && count >= 0) {
            wbQuestionsCount = count;
          }
        }

        if (yandexReviewsResponse.ok) {
          const data = await yandexReviewsResponse.json();
          const count = Number(data.count_unanswered);
          if (Number.isFinite(count) && count >= 0) {
            yandexReviewsCount = count;
          }
        }

        if (yandexQuestionsResponse.ok) {
          const data = await yandexQuestionsResponse.json();
          const count = Number(data.count_unanswered);
          if (Number.isFinite(count) && count >= 0) {
            yandexQuestionsCount = count;
          }
        }

        setWbCommunicationUnansweredCount(
          wbReviewsCount + wbQuestionsCount
        );
        setYandexCommunicationUnansweredCount(
          yandexReviewsCount + yandexQuestionsCount
        );

      } catch {
        // Счётчик не должен ломать навигацию.
      }

    };

    void loadCommunicationCount();

  }, [location.pathname, location.search]);

  const isReviewsActive =
    location.pathname.startsWith("/reviews");

  const isAnalyticsActive =
    location.pathname.startsWith("/analytics");


  return (

    <div className="app">

      <aside className="sidebar">

        <div className="logo">
          {appName}
        </div>


        <nav>

          <Link
            to="/products"
            className={
              location.pathname === "/products"
                ? "active"
                : ""
            }
          >
            Товары
          </Link>


          <div className={location.pathname === "/registry" || location.pathname === "/stocks" ? "nav-analytics-group active" : "nav-analytics-group"}>
            <Link
              to="/registry"
              className="analytics-main-link"
              aria-expanded={stocksOpen}
              onClick={(event) => {
                event.preventDefault();
                setStocksOpen(value => !value);
              }}
            >
              <span>Остатки</span>
              <span className={stocksOpen ? "analytics-chevron open" : "analytics-chevron"} aria-hidden="true">›</span>
            </Link>
            {stocksOpen && <div className="analytics-submenu">
              <Link to="/registry" className={location.pathname === "/registry" ? "analytics-sub-link active" : "analytics-sub-link"}>{fbsShown ? "FBO + FBS" : "FBO"}</Link>
              <Link to="/stocks" className={location.pathname === "/stocks" ? "analytics-sub-link active" : "analytics-sub-link"}>История остатков</Link>
            </div>}
          </div>

          <div
            className={
              isAnalyticsActive
                ? "nav-analytics-group active"
                : "nav-analytics-group"
            }
          >

            <button
              type="button"
              className="analytics-main-link sidebar-section-toggle"
              aria-expanded={analyticsOpen}
              onClick={() => setAnalyticsOpen(value => !value)}
            >
              <span>Аналитика</span>

              <span
                className={
                  analyticsOpen
                    ? "analytics-chevron open"
                    : "analytics-chevron"
                }
                aria-hidden="true"
              >
                ›
              </span>
            </button>


            {analyticsOpen && (

              <div className="analytics-submenu">

                <Link
                  to="/analytics"
                  className={
                    location.pathname === "/analytics"
                      ? "analytics-sub-link active"
                      : "analytics-sub-link"
                  }
                >
                  Дашборд
                </Link>


                <Link
                  to="/analytics/weekly"
                  className={
                    location.pathname === "/analytics/weekly"
                      ? "analytics-sub-link active"
                      : "analytics-sub-link"
                  }
                >
                  Еженедельный отчет
                </Link>


                <Link
                  to="/analytics/unit-economy"
                  className={
                    location.pathname === "/analytics/unit-economy"
                      ? "analytics-sub-link active"
                      : "analytics-sub-link"
                  }
                >
                  Unit-Экономика
                </Link>

              </div>

            )}

          </div>


          <div
            className={
              isReviewsActive
                ? "nav-review-group active"
                : "nav-review-group"
            }
          >

            <button
              type="button"
              className="reviews-main-link sidebar-section-toggle"
              aria-expanded={reviewsOpen}
              onClick={() => setReviewsOpen(value => !value)}
            >
              <span>Отзывы и вопросы</span>

              <span
                className={
                  reviewsOpen
                    ? "reviews-chevron open"
                    : "reviews-chevron"
                }
                aria-hidden="true"
              >
                ›
              </span>
            </button>


            {reviewsOpen && (

              <div className="reviews-submenu">

                <Link
                  to="/reviews?marketplace=WB"
                  className={
                    location.search.includes("marketplace=WB") ||
                    (isReviewsActive && !location.search)
                      ? "reviews-sub-link active"
                      : "reviews-sub-link"
                  }
                >
                  <span>WB</span>

                  {wbCommunicationUnansweredCount > 0 && (
                    <span
                      className="reviews-count-badge"
                      aria-label={`Без ответа: ${wbCommunicationUnansweredCount}`}
                      title={`Без ответа: ${wbCommunicationUnansweredCount}`}
                    >
                      {wbCommunicationUnansweredCount > 99 ? "99+" : wbCommunicationUnansweredCount}
                    </span>
                  )}
                </Link>


                <Link
                  to="/reviews?marketplace=OZON"
                  className={
                    location.search.includes("marketplace=OZON")
                      ? "reviews-sub-link active"
                      : "reviews-sub-link"
                  }
                >
                  OZON
                </Link>


                <Link
                  to="/reviews?marketplace=YANDEX&type=reviews"
                  className={
                    location.search.includes("marketplace=YANDEX")
                      ? "reviews-sub-link active"
                      : "reviews-sub-link"
                  }
                >
                  <span>ЯМаркет</span>

                  {yandexCommunicationUnansweredCount > 0 && (
                    <span
                      className="reviews-count-badge"
                      aria-label={`Без ответа: ${yandexCommunicationUnansweredCount}`}
                      title={`Без ответа: ${yandexCommunicationUnansweredCount}`}
                    >
                      {yandexCommunicationUnansweredCount > 99 ? "99+" : yandexCommunicationUnansweredCount}
                    </span>
                  )}
                </Link>

              </div>

            )}

          </div>

          <Link to="/settings" className={location.pathname === "/settings" ? "active" : ""}>Настройки</Link>
        </nav>

        <div className="auth-user-block">
          <Link to="/profile" className="auth-user-profile-link" title="Открыть профиль">
            <div className="auth-user-name">{user?.name || user?.email}</div>
            <div className="auth-user-email">{user?.email}</div>
          </Link>
          <button type="button" className="auth-logout-button" onClick={() => void logout()}>Выйти</button>
        </div>

      </aside>


      <main className="content">
        <Outlet />
      </main>

    </div>

  );

}


export default Layout;
