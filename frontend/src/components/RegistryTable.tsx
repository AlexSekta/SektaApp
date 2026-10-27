import {defaultStockView, type StockViewSettings} from "../stockViewSettings";
import {
  useRef,
  useState
} from "react";

import StockPopover from "./StockPopover";
import StockInput from "./StockInput";


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
  stock_1c: number;
  wb: MarketplaceStock;
  ozon: MarketplaceStock;
  yandex: YandexStock;
  updated_at: string | null;
}


interface RegistryTableProps {
  items: RegistryItem[];
  view?: StockViewSettings;

  stockChanges: Record<string, string>;

  setStockChanges: React.Dispatch<
    React.SetStateAction<Record<string, string>>
  >;

  savingStocks: Record<string, boolean>;

  onSaveStock: (
    article: string,
    marketplace: string
  ) => void;

  onOpenMenu: (
    event: React.MouseEvent<HTMLButtonElement>,
    id: number
  ) => void;
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


function RegistryTable({
  items,
  view = defaultStockView,
  stockChanges,
  setStockChanges,
  savingStocks,
  onSaveStock,
  onOpenMenu
}: RegistryTableProps) {

  const [
    showScrollTop,
    setShowScrollTop
  ] = useState(false);

  const scrollRef =
    useRef<HTMLDivElement>(null);


  const handleScroll = () => {

    const element =
      scrollRef.current;

    if (!element) {
      return;
    }

    setShowScrollTop(
      element.scrollTop > 200
    );
  };


  const scrollToTop = () => {

    scrollRef.current?.scrollTo({
      top: 0,
      behavior: "smooth"
    });
  };


  const activeColumns = [0, ...(view.fbs?[1]:[]), ...(view.wb?[2]:[]), ...(view.ozon?[3]:[]), ...(view.yandex?[4]:[]),5];
  const rawWidths = [42,12,10,10,12,14];
  const totalWidth = activeColumns.reduce((sum,i)=>sum+rawWidths[i],0);
  const widthAt = (i:number) => `${rawWidths[i]/totalWidth*100}%`;
  const mpStock = (stock:MarketplaceStock | YandexStock, fboKey:"fbo"|"fby") => ({...stock, total:(view.fbs?stock.fbs:0)+(view.fbo?Number(stock[fboKey]):0), fbs:view.fbs?stock.fbs:0, [fboKey]:view.fbo?stock[fboKey]:0, recommendation:view.fbs&&view.fbo?stock.recommendation:{...stock.recommendation,status:"none" as const}});
  return (

    <div className="registry-table-wrapper">

      <table className="registry-header-table">

        <thead>

          <tr>
            <th style={{width:widthAt(0)}}>Артикул</th>
            {view.fbs && <th style={{width:widthAt(1)}}>Остаток 1С</th>}
            {view.wb && <th style={{width:widthAt(2)}}>WB</th>}
            {view.ozon && <th style={{width:widthAt(3)}}>Ozon</th>}
            {view.yandex && <th style={{width:widthAt(4)}}>ЯМаркет</th>}
            <th style={{width:widthAt(5)}}>Обновлено</th>
          </tr>

        </thead>

      </table>


      <div
        className="registry-table-scroll"
        ref={scrollRef}
        onScroll={handleScroll}
      >

        <table className="registry-body-table">

          <tbody>

            {items.map(item => {

              const lowOneC =
                item.group === "Готовая продукция" &&
                item.stock_1c < 35;


              return (

                <tr key={item.id}>

                  <td style={{width:widthAt(0)}}>

                    <div className="article-content">

                      <div className="article-row">

                        <button
                          type="button"
                          className="menu-button"
                          onClick={(event) =>
                            onOpenMenu(
                              event,
                              item.id
                            )
                          }
                        >
                          ⋮
                        </button>

                        <strong>
                          {item.article}
                        </strong>

                      </div>

                      <div className="product-name">
                        {item.name}
                      </div>

                    </div>

                  </td>


                  {view.fbs && <td style={{width:widthAt(1)}}>

                    <div className={lowOneC ? "stock-1c-cell is-low" : "stock-1c-cell"}>
                      <StockInput
                        article={item.article}
                        marketplace="1C"
                        value={item.stock_1c}
                        changes={stockChanges}
                        setChanges={setStockChanges}
                        onSave={onSaveStock}
                        saving={Boolean(savingStocks[`${item.article}_1C`])}
                      />
                    </div>

                  </td>}


                  {view.wb && <td style={{width:widthAt(2)}}>

                    <div className="stock-cell">
                      <StockPopover
                        title="WB"
                        marketplace="WB"
                        article={item.article}
                        stock={mpStock(item.wb,"fbo")}
                        stockChanges={stockChanges}
                        setStockChanges={setStockChanges}
                        savingStocks={savingStocks}
                        onSaveStock={onSaveStock}
                      >
                        <span>{mpStock(item.wb,"fbo").total}</span>

                        {item.wb.recommendation.status !== "none" && (
                          <span
                            className={recommendationClass(
                              item.wb.recommendation.status
                            )}
                          >
                            {item.wb.recommendation.target}
                          </span>
                        )}
                      </StockPopover>
                    </div>

                  </td>}


                  {view.ozon && <td style={{width:widthAt(3)}}>

                    <div className="stock-cell">
                      <StockPopover
                        title="OZON"
                        marketplace="OZON"
                        article={item.article}
                        stock={mpStock(item.ozon,"fbo")}
                        stockChanges={stockChanges}
                        setStockChanges={setStockChanges}
                        savingStocks={savingStocks}
                        onSaveStock={onSaveStock}
                      >
                        <span>{mpStock(item.ozon,"fbo").total}</span>

                        {item.ozon.recommendation.status !== "none" && (
                          <span
                            className={recommendationClass(
                              item.ozon.recommendation.status
                            )}
                          >
                            {item.ozon.recommendation.target}
                          </span>
                        )}
                      </StockPopover>
                    </div>

                  </td>}


                  {view.yandex && <td style={{width:widthAt(4)}}>

                    <div className="stock-cell">
                      <StockPopover
                        title="Яндекс"
                        marketplace="Yandex"
                        article={item.article}
                        stock={mpStock(item.yandex,"fby")}
                        stockChanges={stockChanges}
                        setStockChanges={setStockChanges}
                        savingStocks={savingStocks}
                        onSaveStock={onSaveStock}
                      >
                        <span>{mpStock(item.yandex,"fby").total}</span>

                        {item.yandex.recommendation.status !== "none" && (
                          <span
                            className={recommendationClass(
                              item.yandex.recommendation.status
                            )}
                          >
                            {item.yandex.recommendation.target}
                          </span>
                        )}
                      </StockPopover>
                    </div>

                  </td>}


                  <td style={{width:widthAt(5)}}>

                    {item.updated_at
                      ? new Date(
                          item.updated_at + "Z"
                        ).toLocaleString()
                      : "-"
                    }

                  </td>

                </tr>

              );

            })}

          </tbody>

        </table>

      </div>


      {showScrollTop && (

        <button
          type="button"
          className="registry-scroll-top"
          onClick={scrollToTop}
          aria-label="Наверх таблицы"
        >
          ↑
        </button>

      )}

    </div>

  );
}


export default RegistryTable;
