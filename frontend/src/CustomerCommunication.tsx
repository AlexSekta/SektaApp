import { useSearchParams } from "react-router-dom";
import Reviews from "./Reviews";
import OzonReviews from "./OzonReviews";
import YandexReviews from "./YandexReviews";
import YandexQuestions from "./YandexQuestions";
import Questions from "./Questions";
import "./Reviews.css";

function CustomerCommunication() {
  const [params, setParams] = useSearchParams();
  const type = params.get("type") === "questions" ? "questions" : "reviews";
  const marketplace = (params.get("marketplace") || "WB").toUpperCase();

  const canSwitchType = ["WB", "OZON", "YANDEX"].includes(marketplace);

  return (
    <div className="customer-communication">
      {canSwitchType && (
        <div className="communication-switch">
          <button
            type="button"
            className={type === "reviews" ? "communication-switch-button active" : "communication-switch-button"}
            onClick={() => setParams({ marketplace, type: "reviews" })}
          >
            Отзывы
          </button>
          <button
            type="button"
            className={type === "questions" ? "communication-switch-button active" : "communication-switch-button"}
            onClick={() => setParams({ marketplace, type: "questions" })}
          >
            Вопросы
          </button>
        </div>
      )}

      {marketplace === "OZON" ? (
        type === "questions" ? (
          <div className="reviews-page">
            <div className="reviews-empty reviews-marketplace-placeholder">
              <div>
                <strong>Вопросы Ozon</strong>
                <span>Получение вопросов Ozon пока не подключено.</span>
              </div>
            </div>
          </div>
        ) : (
          <OzonReviews />
        )
      ) : marketplace === "YANDEX" ? (
        type === "questions" ? (
          <YandexQuestions />
        ) : (
          <YandexReviews />
        )
      ) : type === "questions" ? (
        <Questions />
      ) : (
        <Reviews />
      )}
    </div>
  );
}

export default CustomerCommunication;
