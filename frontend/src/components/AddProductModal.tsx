import {
    useEffect,
    useRef,
    useState
} from "react";

import Loader from "./Loader";

import "./AddProductModal.css";


interface AddProductModalProps {
    initialGroup?: string;
    warehouses?: string[];

    onClose: () => void;

    onAdded: (
        article: string
    ) => void;

    onError: (
        message: string
    ) => void;
}


function AddProductModal({
    initialGroup = "",
    warehouses = ["Маркетплейс", "Готовая продукция"],
    onClose,
    onAdded,
    onError
}: AddProductModalProps) {

    const [
        article,
        setArticle
    ] = useState("");


    const [
        group,
        setGroup
    ] = useState(
        initialGroup
    );


    const [
        dropdownOpen,
        setDropdownOpen
    ] = useState(false);


    const [
        loading,
        setLoading
    ] = useState(false);


    const dropdownRef =
        useRef<HTMLDivElement>(null);


    useEffect(() => {

        setGroup(
            initialGroup
        );

    }, [initialGroup]);


    useEffect(() => {

        const handleClickOutside = (
            event: MouseEvent
        ) => {

            if (
                dropdownRef.current &&
                !dropdownRef.current.contains(
                    event.target as Node
                )
            ) {

                setDropdownOpen(false);

            }

        };


        document.addEventListener(
            "mousedown",
            handleClickOutside
        );


        return () => {

            document.removeEventListener(
                "mousedown",
                handleClickOutside
            );

        };

    }, []);


    const addProduct = async () => {

        const cleanArticle =
            article.trim();


        if (!cleanArticle) {

            onError(
                "Введите артикул"
            );

            return;

        }


        if (!group) {

            onError(
                "Выберите склад 1С"
            );

            return;

        }


        if (loading) {
            return;
        }


        setLoading(true);


        try {

            const response = await fetch(
                "http://127.0.0.1:8000/local-warehouses/products",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        article: cleanArticle,
                        group
                    })
                }
            );


            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(typeof errorData.detail === "string" ? errorData.detail :
                    response.status === 409 ? "Этот артикул уже зарегистрирован на складе" :
                    `Не удалось добавить товар (код ${response.status})`);
            }


            const data =
                await response.json();


            if (data.status !== "ok") {

                throw new Error(
                    data.message ||
                    "Не удалось добавить товар"
                );

            }


            onAdded(
                data.article ||
                cleanArticle
            );


        } catch (error) {

            const message =
                error instanceof TypeError
                    ? "Не удалось связаться с сервером"
                    : error instanceof Error
                        ? error.message
                        : "Не удалось добавить товар";


            onError(
                message
            );


        } finally {

            setLoading(false);

        }

    };


    return (

        <div
            className="modal-overlay"
            onClick={() => {

                if (!loading) {
                    onClose();
                }

            }}
        >

            <div
                className="modal-window"
                onClick={
                    event =>
                        event.stopPropagation()
                }
            >

                <div className="modal-header">

                    <h2>
                        Добавить товар
                    </h2>


                    <button
                        type="button"
                        className="close-button"
                        onClick={onClose}
                        disabled={loading}
                    >
                        ×
                    </button>

                </div>


                <div className="modal-body">

                    <label>
                        Артикул
                    </label>


                    <input
                        value={article}
                        disabled={loading}
                        onChange={
                            event =>
                                setArticle(
                                    event.target.value
                                )
                        }
                        placeholder="Введите артикул"
                    />


                    <label>
                        Склад 1С
                    </label>


                    <div
                        className="custom-select"
                        ref={dropdownRef}
                    >

                        <div
                            className="select-value"
                            onClick={() => {

                                if (!loading) {

                                    setDropdownOpen(
                                        prev => !prev
                                    );

                                }

                            }}
                        >

                            <span>
                                {
                                    group ||
                                    "Выберите склад 1С"
                                }
                            </span>


                            <span>
                                ▼
                            </span>

                        </div>


                        {dropdownOpen && (

                            <div className="select-options">

                                {warehouses.map(name => (
                                    <div key={name} onClick={() => { setGroup(name); setDropdownOpen(false); }}>
                                        {name}
                                    </div>
                                ))}

                            </div>

                        )}

                    </div>

                </div>


                <div className="modal-footer">

                    <button
                        type="button"
                        className="cancel-button"
                        onClick={onClose}
                        disabled={loading}
                    >
                        Отмена
                    </button>


                    <button
                        type="button"
                        className="save-button"
                        onClick={addProduct}
                        disabled={loading}
                    >

                        {loading ? (

                            <>
                                <Loader size="small" />

                                <span>
                                    Добавление...
                                </span>
                            </>

                        ) : (

                            "Добавить"

                        )}

                    </button>

                </div>

            </div>

        </div>

    );

}


export default AddProductModal;
