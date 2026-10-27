import {
  useEffect,
  useRef,
  useState
} from "react";

import type {
  Dispatch,
  ReactNode,
  SetStateAction
} from "react";

import { createPortal } from "react-dom";

import StockInput from "./StockInput";

import "./StockPopover.css";


interface Recommendation {
  target: number;
  status: "none" | "increase" | "decrease" | "zero";
  reason: "ALLOCATION" | "LOW_1C" | "FBO_STOCK";
}


interface StockData {
  fbo?: number;
  fby?: number;
  fbs: number;
  fbs_managed: boolean;
  recommendation: Recommendation;
}


interface StockPopoverProps {
  title: string;
  article: string;
  marketplace: string;
  stock: StockData;
  stockChanges: Record<string, string>;
  setStockChanges: Dispatch<
    SetStateAction<Record<string, string>>
  >;
  savingStocks: Record<string, boolean>;
  onSaveStock: (
    article: string,
    marketplace: string
  ) => void;
  children: ReactNode;
}


interface Position {
  top: number;
  left: number;
  above: boolean;
}


function recommendationLabel(
  reason: Recommendation["reason"]
) {
  if (reason === "LOW_1C") {
    return "Мало на 1С";
  }

  if (reason === "FBO_STOCK") {
    return "Есть остаток на FBO/FBY";
  }

  return "Распределение 40/40/20";
}


function recommendationClass(
  status: Recommendation["status"]
) {
  if (status === "increase") {
    return "stock-recommendation stock-recommendation-green";
  }

  if (status === "decrease") {
    return "stock-recommendation stock-recommendation-orange";
  }

  if (status === "zero") {
    return "stock-recommendation stock-recommendation-red";
  }

  return "";
}


function StockPopover({
  title,
  article,
  marketplace,
  stock,
  stockChanges,
  setStockChanges,
  savingStocks,
  onSaveStock,
  children
}: StockPopoverProps) {

  const [
    open,
    setOpen
  ] = useState(false);

  const [
    position,
    setPosition
  ] = useState<Position | null>(null);

  const triggerRef =
    useRef<HTMLDivElement>(null);

  const closeTimerRef =
    useRef<number | null>(null);


  const clearCloseTimer = () => {

    if (
      closeTimerRef.current !== null
    ) {

      window.clearTimeout(
        closeTimerRef.current
      );

      closeTimerRef.current = null;
    }
  };


  const closeLater = () => {

    clearCloseTimer();

    closeTimerRef.current =
      window.setTimeout(() => {

        setOpen(false);

      }, 180);
  };


  const updatePosition = () => {

    const trigger =
      triggerRef.current;

    if (!trigger) {
      return;
    }


    const rect =
      trigger.getBoundingClientRect();


    const popupWidth = 220;
    const gap = 10;
    const sidePadding = 12;
    const estimatedHeight = 190;


    let left =
      rect.left
      +
      rect.width / 2
      -
      popupWidth / 2;


    left = Math.max(
      sidePadding,
      Math.min(
        left,
        window.innerWidth
          -
          popupWidth
          -
          sidePadding
      )
    );


    const enoughBelow =
      window.innerHeight
      -
      rect.bottom
      >=
      estimatedHeight
      +
      gap;


    if (enoughBelow) {

      setPosition({
        top:
          rect.bottom + gap,

        left,

        above: false
      });

    } else {

      setPosition({
        top:
          rect.top - gap,

        left,

        above: true
      });

    }
  };


  const openPopover = () => {

    clearCloseTimer();

    updatePosition();

    setOpen(true);
  };


  useEffect(() => {

    if (!open) {
      return;
    }


    const handleWindowChange = () => {
      updatePosition();
    };


    window.addEventListener(
      "scroll",
      handleWindowChange,
      true
    );

    window.addEventListener(
      "resize",
      handleWindowChange
    );


    return () => {

      window.removeEventListener(
        "scroll",
        handleWindowChange,
        true
      );

      window.removeEventListener(
        "resize",
        handleWindowChange
      );

    };

  }, [open]);


  useEffect(() => {

    return () => {

      clearCloseTimer();

    };

  }, []);


  const recommendation =
    stock.recommendation;


  const fbsValue =
    stock.fbs ?? 0;


  return (

    <>

      <div
        ref={triggerRef}
        className="stock-popover-trigger"
        onMouseEnter={openPopover}
        onMouseLeave={closeLater}
      >

        <span className="stock-popover-value">
          {children}
        </span>

      </div>


      {open &&
        position &&
        createPortal(

          <div
            className={
              `stock-popover ${
                position.above
                  ? "stock-popover-above"
                  : ""
              }`
            }
            style={{
              top: position.top,
              left: position.left
            }}
            onMouseEnter={
              clearCloseTimer
            }
            onMouseLeave={
              closeLater
            }
          >

            <div className="stock-popover-title">
              {title}
            </div>


            {stock.fbo !== undefined && (

              <div className="stock-popover-row">

                <span>FBO</span>

                <strong>
                  {stock.fbo}
                </strong>

              </div>

            )}


            {stock.fby !== undefined && (

              <div className="stock-popover-row">

                <span>FBY</span>

                <strong>
                  {stock.fby}
                </strong>

              </div>

            )}


            <div className="stock-popover-fbs">

              <span>FBS</span>

              <StockInput
                article={article}
                marketplace={marketplace}
                value={fbsValue}
                changes={stockChanges}
                setChanges={setStockChanges}
                onSave={onSaveStock}
                saving={
                  savingStocks[
                    `${article}_${marketplace}`
                  ] === true
                }
              />

            </div>


            {recommendation.status !== "none" && (

              <div className="stock-popover-recommendation">

                <span>
                  Рекомендовано
                </span>

                <strong
                  className={
                    recommendationClass(
                      recommendation.status
                    )
                  }
                  title={
                    recommendationLabel(
                      recommendation.reason
                    )
                  }
                >
                  {recommendation.target}
                </strong>

              </div>

            )}

          </div>,

          document.body

        )}

    </>

  );
}


export default StockPopover;
