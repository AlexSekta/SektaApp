import { useEffect, useState } from "react";
import Loader from "./components/Loader";
import Toast, { type ToastType } from "./components/Toast";
import "./Reviews.css";
import DateFilter from "./DateFilter";

type Status = "unanswered" | "answered" | "all";

interface Question {
  id: string;
  text: string;
  created_at: string | null;
  is_answered: boolean;
  answer: { text: string; editable: boolean; state?: string; created_at?: string | null } | null;
  article?: string;
  nm_id?: number;
  product_name?: string;
  brand_name?: string;
  was_viewed: boolean;
  is_warned: boolean;
  state?: string;
}

interface Data {
  status: string;
  count_unanswered: number | null;
  count_archive: number | null;
  count_filtered: number;
  questions: Question[];
}

type QuestionFilters = {
  dateFrom: string;
  dateTo: string;
  article: string;
};

interface ToastState {
  message: string;
  type: ToastType;
}

function formatDate(value: string | null): string {
  if (!value) return "Дата не указана";

  // WB returns createdDate in UTC (usually with trailing Z), while the
  // backend stores it as a naive UTC datetime. Treat the API value as UTC
  // explicitly before displaying it in Moscow time, matching WB Seller.
  const normalized = /(?:Z|[+-]\\d{2}:?\\d{2})$/.test(value)
    ? value
    : `${value.replace(" ", "T")}Z`;

  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;

  return date.toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function Questions() {
  const [status, setStatus] = useState<Status>("unanswered");
  const [items, setItems] = useState<Question[]>([]);
  const [unanswered, setUnanswered] = useState<number | null>(null);
  const [countFiltered, setCountFiltered] = useState(0);
  const [filters, setFilters] = useState<QuestionFilters>({
    dateFrom: "",
    dateTo: "",
    article: ""
  });
  const [appliedFilters, setAppliedFilters] = useState<QuestionFilters>({
    dateFrom: "",
    dateTo: "",
    article: ""
  });
  const [loading, setLoading] = useState(false);

  const [showScrollTop, setShowScrollTop] =
    useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [copiedNmId, setCopiedNmId] = useState<number | null>(null);
  const [processingQuestionId, setProcessingQuestionId] = useState<string | null>(null);
  const [replyTexts, setReplyTexts] = useState<Record<string, string>>({});

  const copyNmId = async (nmId: number) => {
    try {
      await navigator.clipboard.writeText(String(nmId));
      setCopiedNmId(nmId);
      window.setTimeout(() => {
        setCopiedNmId(current => current === nmId ? null : current);
      }, 2500);
    } catch {
      setToast({ type: "error", message: "Не удалось скопировать nmID" });
    }
  };

  const toggleProcessing = (id: string) => {
    setProcessingQuestionId(current => current === id ? null : id);
  };

  const setReplyText = (id: string, value: string) => {
    setReplyTexts(current => ({ ...current, [id]: value }));
  };

  const canSendReply = (id: string) =>
    (replyTexts[id] || "").trim().length >= 50;

  const load = async (
    nextStatus: Status = status,
    nextFilters: QuestionFilters = appliedFilters
  ) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        status: nextStatus,
        take: "100",
        skip: "0",
        order: "dateDesc"
      });

      if (nextFilters.dateFrom) {
        params.set("date_from", nextFilters.dateFrom);
      }
      if (nextFilters.dateTo) {
        params.set("date_to", nextFilters.dateTo);
      }
      if (nextFilters.article.trim()) {
        params.set("article", nextFilters.article.trim());
      }
      const response = await fetch(
        `http://127.0.0.1:8000/wb/questions?${params.toString()}`
      );

      if (!response.ok) {
        let message = `Ошибка сервера: ${response.status}`;
        try {
          const errorData = await response.json();
          if (errorData.detail) message = String(errorData.detail);
        } catch {}
        throw new Error(message);
      }

      const data = await response.json() as Data;
      if (data.status !== "ok") throw new Error("WB не вернул вопросы");

      setItems(data.questions || []);
      setUnanswered(data.count_unanswered);
      setCountFiltered(Number(data.count_filtered) || 0);
    } catch (error) {
      setToast({
        type: "error",
        message: error instanceof Error
          ? error.message
          : "Не удалось загрузить вопросы WB"
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {

    const handleWindowScroll = () => {
      setShowScrollTop(window.scrollY > 300);
    };

    handleWindowScroll();

    window.addEventListener(
      "scroll",
      handleWindowScroll,
      { passive: true }
    );

    return () => {
      window.removeEventListener(
        "scroll",
        handleWindowScroll
      );
    };

  }, []);

  useEffect(() => {
    const emptyFilters = { dateFrom: "", dateTo: "", article: "" };
    setFilters(emptyFilters);
    setAppliedFilters(emptyFilters);
    void load("unanswered", emptyFilters);
  }, []);

  const scrollPageToTop = () => {

    window.scrollTo({
      top: 0,
      behavior: "smooth"
    });

  };


  return (
    <div className="reviews-page">
      <div className="reviews-header">
        <div>
          <h1>Отзывы и вопросы</h1>
          <p>Вопросы покупателей Wildberries. Сейчас только получение данных.</p>
        </div>
      </div>

      <div className="reviews-toolbar">

        <div className="reviews-tabs">

          {([
            ["unanswered", "Без ответа"],
            ["answered", "С ответом"],
            ["all", "Все"]
          ] as const).map(([value, label]) => (
            <button
              type="button"
              key={value}
              className={status === value ? "reviews-tab active" : "reviews-tab"}
              onClick={() => {
                setStatus(value);
                void load(value, appliedFilters);
              }}
            >
              <span>{label}</span>
              {value === "unanswered" && unanswered !== null && (
                <span className="reviews-tab-count">{unanswered}</span>
              )}
            </button>
          ))}
        </div>

        <div className="reviews-result-count">
          {countFiltered} вопросов
        </div>

        <button
          type="button"
          className="reviews-refresh"
          onClick={() => void load(status, appliedFilters)}
          disabled={loading}
        >
          {loading ? <><Loader size="small" />Загрузка...</> : "Обновить"}
        </button>
      </div>

      <div className="reviews-filters questions-filters">
        <label className="reviews-filter-field reviews-filter-date">
          <span>Дата от</span>
          <DateFilter
            value={filters.dateFrom}
            onChange={value => setFilters(current => ({ ...current, dateFrom: value }))}
          />
        </label>

        <label className="reviews-filter-field reviews-filter-date">
          <span>Дата до</span>
          <DateFilter
            value={filters.dateTo}
            onChange={value => setFilters(current => ({ ...current, dateTo: value }))}
          />
        </label>

        <label className="reviews-filter-field reviews-filter-article">
          <span>Артикул продавца</span>
          <input
            type="text"
            value={filters.article}
            onChange={event =>
              setFilters(current => ({ ...current, article: event.target.value }))
            }
            placeholder="Введите артикул"
          />
        </label>

        <div className="reviews-filter-actions">
          <button
            type="button"
            className="reviews-filter-apply"
            onClick={() => {
              setAppliedFilters(filters);
              void load(status, filters);
            }}
            disabled={loading}
          >
            Применить
          </button>
          <button
            type="button"
            className="reviews-filter-reset"
            onClick={() => {
              const emptyFilters = { dateFrom: "", dateTo: "", article: "" };
              setFilters(emptyFilters);
              setAppliedFilters(emptyFilters);
              void load(status, emptyFilters);
            }}
            disabled={loading}
          >
            Сбросить
          </button>
        </div>
      </div>

      {loading && items.length === 0 ? (
        <div className="reviews-loading">
          <Loader size="small" />
          <span>Получаем вопросы WB...</span>
        </div>
      ) : items.length === 0 ? (
        <div className="reviews-empty">Вопросов по выбранному фильтру нет.</div>
      ) : (
        <div className="reviews-list">
          {items.map(question => (
            <article
              className="review-card"
              key={question.id}
            >
              <div className="review-card-columns">

                <div className="review-card-left">

                  <div className="review-product-name">
                    {question.product_name || "Товар без названия"}
                  </div>

                  <div className="review-product-meta">
                    <span>{question.article || "Без артикула"}</span>

                    {question.nm_id && (
                      <span className="review-nmid">
                        <span className="review-nmid-separator">WB:</span>
                        <span>{question.nm_id}</span>

                        <button
                          type="button"
                          className="review-copy-button"
                          onClick={() => void copyNmId(question.nm_id!)}
                          aria-label={`Скопировать ${question.nm_id}`}
                          title="Скопировать"
                        >
                          <svg
                            className="review-copy-icon"
                            viewBox="0 0 24 24"
                            aria-hidden="true"
                          >
                            <rect
                              x="8"
                              y="8"
                              width="11"
                              height="11"
                              rx="2"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.8"
                            />
                            <path
                              d="M16 8V6.5A2.5 2.5 0 0 0 13.5 4H6.5A2.5 2.5 0 0 0 4 6.5v7A2.5 2.5 0 0 0 6.5 16H8"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.8"
                              strokeLinecap="round"
                            />
                          </svg>
                        </button>

                        <span
                          className={
                            copiedNmId === question.nm_id
                              ? "review-copy-success visible"
                              : "review-copy-success"
                          }
                          aria-hidden={copiedNmId !== question.nm_id}
                        >
                          Скопировано
                        </span>
                      </span>
                    )}
                  </div>

                  <div className="review-author">
                    <div className="review-avatar">?</div>
                    <div>
                      <div className="review-buyer">Покупатель</div>
                      <div className="review-rating-empty">
                        Вопрос о товаре
                      </div>
                    </div>
                  </div>

                  <div className="review-text">
                    {question.text || "Вопрос без текста"}
                  </div>

                  {question.answer && (
                    <div className="review-answer">
                      <div className="review-answer-label">
                        Ответ продавца
                      </div>
                      <div className="review-answer-text">
                        {question.answer.text}
                      </div>
                    </div>
                  )}

                  {processingQuestionId === question.id && (
                    <div className="review-processing">
                      <div className="review-processing-label">
                        Ответ продавца
                      </div>

                      <textarea
                        value={replyTexts[question.id] || ""}
                        onChange={event =>
                          setReplyText(question.id, event.target.value)
                        }
                        placeholder="Здесь в дальнейшем будет предложенный ИИ ответ..."
                        rows={5}
                      />

                      <div
                        className={
                          (replyTexts[question.id] || "").trim().length >= 50
                            ? "review-reply-counter valid"
                            : "review-reply-counter"
                        }
                      >
                        {(replyTexts[question.id] || "").trim().length} / 50 символов
                      </div>
                    </div>
                  )}

                </div>

                <aside className="review-card-right">

                  <div className="review-date">
                    {formatDate(question.created_at)}
                  </div>

                  <div className="review-card-actions">

                    <span
                      className={
                        question.is_answered
                          ? "review-status-badge answered"
                          : "review-status-badge unanswered"
                      }
                    >
                      {question.is_answered ? "Есть ответ" : "Без ответа"}
                    </span>

                    {!question.is_answered && (
                      <>
                        <button
                          type="button"
                          className="review-process-button"
                          onClick={() =>
                            toggleProcessing(question.id)
                          }
                        >
                          {processingQuestionId === question.id
                            ? "Свернуть"
                            : "Обработать"}
                        </button>

                        <button
                          type="button"
                          className="review-send-button"
                          disabled={!canSendReply(question.id)}
                          title={
                            canSendReply(question.id)
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
          onClick={scrollPageToTop}
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
          onClose={() => setToast(null)}
        />
      )}
    </div>
  );
}

export default Questions;
