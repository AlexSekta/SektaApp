export type StockViewSettings = {fbs:boolean;fbo:boolean;wb:boolean;ozon:boolean;yandex:boolean};
export const defaultStockView: StockViewSettings = {fbs:true,fbo:true,wb:true,ozon:true,yandex:true};
export const stockViewEndpoint = `${window.location.protocol}//${window.location.hostname}:8000/settings/stock-view`;
