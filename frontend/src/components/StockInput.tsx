import type {
  ChangeEvent,
  Dispatch,
  SetStateAction
} from "react";

import Loader from "./Loader";


interface StockInputProps {

  article: string;

  marketplace: string;

  value: number;

  changes: Record<string, string>;

  setChanges: Dispatch<
    SetStateAction<Record<string, string>>
  >;

  onSave: (
    article: string,
    marketplace: string
  ) => void;

  saving: boolean;
}


function StockInput({

  article,

  marketplace,

  value,

  changes,

  setChanges,

  onSave,

  saving

}: StockInputProps) {


  const key =
    `${article}_${marketplace}`;


  const currentValue =
    changes[key] !== undefined
      ? changes[key]
      : String(value);


  const changed =
    changes[key] !== undefined &&
    changes[key] !== String(value);


  const handleChange = (
    event: ChangeEvent<HTMLInputElement>
  ) => {

    if (saving) {
      return;
    }


    const newValue =
      event.target.value;


    if (!/^\d*$/.test(newValue)) {
      return;
    }


    setChanges(prev => ({

      ...prev,

      [key]: newValue

    }));

  };


  const handleSave = () => {

    if (
      currentValue === "" ||
      !changed ||
      saving
    ) {
      return;
    }


    onSave(
      article,
      marketplace
    );

  };


  return (

    <div className="stock-edit">

      <input
        type="text"
        inputMode="numeric"
        pattern="[0-9]*"
        autoComplete="off"
        value={currentValue}
        onChange={handleChange}
        disabled={saving}
      />


      {changed && (

        <button
          type="button"
          className="save-stock"
          onClick={handleSave}
          disabled={saving}
          aria-label={
            saving
              ? "Сохранение остатка"
              : "Сохранить остаток"
          }
          title={
            saving
              ? "Сохранение..."
              : "Сохранить"
          }
        >

          {saving ? (

            <Loader size="small" />

          ) : (

            <span
              className="save-stock-check"
            />

          )}

        </button>

      )}

    </div>

  );

}


export default StockInput;