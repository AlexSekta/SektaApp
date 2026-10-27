import { useEffect, useState } from "react";
import Loader from "./components/Loader";
import Toast, { type ToastType } from "./components/Toast";
import "./Reviews.css";

type Status =
  | "unanswered"
  | "answered"
  | "all";

interface OzonReview {
  id: string;
  text: string;
  rating: number | null;
  created_at: string | null;
  is_answered: boolean;
  status: string;
  sku?: number | string;
  article?: string;
  product_name?: string;
  photos_amount: number;
  videos_amount: number;
  comments_amount: number;
}

interface ResponseData {
  status: string;
  message?: string;
  count_unanswered: number;
  reviews: OzonReview[];
}

function formatDate(value: string | null) {
  if (!value) return "Дата не указана";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function Stars({
  value
}: {
  value: number | null;
}) {
  if (!value) {
    return (
      <span className="review-rating-empty">
        Без оценки
      </span>
    );
  }

  return (
    <span className="review-stars">
      {"★".repeat(value)}

      <span className="review-stars-muted">
        {"★".repeat(
          Math.max(0, 5 - value)
        )}
      </span>
    </span>
  );
}

function OzonReviews() {
  const [status, setStatus] =
    useState<Status>("unanswered");

  const [reviews, setReviews] =
    useState<OzonReview[]>([]);

  const [unanswered, setUnanswered] =
    useState(0);

  const [loading, setLoading] =
    useState(false);

  const [toast, setToast] =
    useState<{
      type: ToastType;
      message: string;
    } | null>(null);

  const [processingId, setProcessingId] =
    useState<string | null>(null);

  const [replyTexts, setReplyTexts] =
    useState<Record<string, string>>({});

  const [showScrollTop, setShowScrollTop] =
    useState(false);


  const canSend = (id: string) =>
    (replyTexts[id] || "")
      .trim()
      .length >= 50;


  const loadReviews = async (
    nextStatus: Status = status
  ) => {

    setLoading(true);

    try {

      const params =
        new URLSearchParams({
          status: nextStatus,
          limit: "100",
        });

      const response =
        await fetch(
          `http://127.0.0.1:8000/ozon/reviews?${params.toString()}`
        );

      const data =
        await response.json() as ResponseData;

      if (
        !response.ok ||
        data.status !== "ok"
      ) {
        throw new Error(
          data.message ||
          `Ошибка сервера: ${response.status}`
        );
      }

      setReviews(
        data.reviews || []
      );

      setUnanswered(
        data.count_unanswered || 0
      );

    } catch (error) {

      setToast({
        type: "error",
        message:
          error instanceof Error
            ? error.message
            : "Не удалось загрузить отзывы Ozon"
      });

    } finally {

      setLoading(false);

    }
  };


  useEffect(() => {
    void loadReviews("unanswered");
  }, []);


  useEffect(() => {

    const onScroll = () => {
      setShowScrollTop(
        window.scrollY > 300
      );
    };

    window.addEventListener(
      "scroll",
      onScroll,
      { passive: true }
    );

    onScroll();

    return () =>
      window.removeEventListener(
        "scroll",
        onScroll
      );

  }, []);


  return (
    <div className="reviews-page">

      <div className="reviews-header">

        <div>

          <h1>
            Отзывы и вопросы
          </h1>

          <p>
            Отзывы покупателей Ozon.
          </p>

        </div>

      </div>


      <div className="reviews-toolbar">

        <div className="reviews-tabs">

          {([
            ["unanswered", "Без ответа"],
            ["answered", "С ответом"],
            ["all", "Все"]
          ] as const).map(
            ([value, label]) => (

              <button
                type="button"
                key={value}
                className={
                  status === value
                    ? "reviews-tab active"
                    : "reviews-tab"
                }
                onClick={() => {

                  setStatus(value);

                  void loadReviews(value);

                }}
              >

                <span>
                  {label}
                </span>

                {value === "unanswered" && (

                  <span className="reviews-tab-count">
                    {unanswered}
                  </span>

                )}

              </button>

            )
          )}

        </div>


        <button
          type="button"
          className="reviews-refresh"
          onClick={() =>
            void loadReviews()
          }
          disabled={loading}
        >
          {loading ? (
            <>
              <Loader size="small" />
              Загрузка...
            </>
          ) : (
            "Обновить"
          )}
        </button>

      </div>


      {loading && reviews.length === 0 ? (

        <div className="reviews-loading">

          <Loader size="small" />

          <span>
            Получаем отзывы Ozon...
          </span>

        </div>

      ) : reviews.length === 0 ? (

        <div className="reviews-empty">
          Отзывов по выбранному фильтру нет.
        </div>

      ) : (

        <div className="reviews-list">

          {reviews.map(review => (

            <article
              className="review-card"
              key={review.id}
            >

              <div className="review-card-columns">

                <div className="review-card-left">

                  <div className="review-product-name">
                    {review.product_name ||
                      "Товар Ozon"}
                  </div>


                  <div className="review-product-meta">

                    <span>
                      {review.article ||
                        `SKU ${review.sku ?? "—"}`}
                    </span>

                  </div>


                  <div className="review-author">

                    <div className="review-avatar">
                      О
                    </div>

                    <div>

                      <div className="review-buyer">
                        Покупатель
                      </div>

                      <Stars
                        value={review.rating}
                      />

                    </div>

                  </div>


                  {review.text && (

                    <div className="review-text">
                      {review.text}
                    </div>

                  )}


                  {(review.photos_amount > 0 ||
                    review.videos_amount > 0 ||
                    review.comments_amount > 0) && (

                    <div className="review-tags">

                      {review.photos_amount > 0 && (
                        <span>
                          Фото: {review.photos_amount}
                        </span>
                      )}

                      {review.videos_amount > 0 && (
                        <span>
                          Видео: {review.videos_amount}
                        </span>
                      )}

                      {review.comments_amount > 0 && (
                        <span>
                          Комментарии: {review.comments_amount}
                        </span>
                      )}

                    </div>

                  )}


                  {processingId === review.id && (

                    <div className="review-processing">

                      <div className="review-processing-label">
                        Ответ продавца
                      </div>

                      <textarea
                        value={
                          replyTexts[review.id] || ""
                        }
                        onChange={event =>
                          setReplyTexts(
                            current => ({
                              ...current,
                              [review.id]:
                                event.target.value
                            })
                          )
                        }
                        placeholder="Здесь в дальнейшем будет предложенный ИИ ответ..."
                        rows={5}
                      />

                      <div
                        className={
                          canSend(review.id)
                            ? "review-reply-counter valid"
                            : "review-reply-counter"
                        }
                      >
                        {(
                          replyTexts[review.id] || ""
                        )
                          .trim()
                          .length}
                        {" / 50 символов"}
                      </div>

                    </div>

                  )}

                </div>


                <aside className="review-card-right">

                  <div className="review-date">
                    {formatDate(
                      review.created_at
                    )}
                  </div>


                  <div className="review-card-actions">

                    <span
                      className={
                        review.is_answered
                          ? "review-status-badge answered"
                          : "review-status-badge unanswered"
                      }
                    >
                      {review.is_answered
                        ? "Есть ответ"
                        : "Без ответа"}
                    </span>


                    {!review.is_answered && (

                      <>

                        <button
                          type="button"
                          className="review-process-button"
                          onClick={() =>
                            setProcessingId(
                              current =>
                                current === review.id
                                  ? null
                                  : review.id
                            )
                          }
                        >
                          {processingId === review.id
                            ? "Свернуть"
                            : "Обработать"}
                        </button>


                        <button
                          type="button"
                          className="review-send-button"
                          disabled={
                            !canSend(
                              review.id
                            )
                          }
                          title={
                            canSend(review.id)
                              ? "Ответить"
                              : "Ответ должен содержать минимум 50 символов"
                          }
                        >
                          Ответить
                        </button>

                      </>

                    )}

                  </div>

                </aside>

              </div>

            </article>

          ))}

        </div>

      )}


      {showScrollTop && (

        <button
          type="button"
          className="reviews-scroll-top"
          onClick={() =>
            window.scrollTo({
              top: 0,
              behavior: "smooth"
            })
          }
          aria-label="Наверх"
          title="Наверх"
        >
          ↑
        </button>

      )}


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

export default OzonReviews;
