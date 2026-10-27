import {
    useEffect,
    useRef,
    useState
} from "react";

import Loader from "./Loader";

import "./EditProductModal.css";


interface EditProductModalProps {

    productId: number;

    currentGroup: string;
    warehouses?: string[];

    onClose: () => void;

    onUpdated: () => void;

    onError: (
        message: string
    ) => void;

}


function EditProductModal({
    productId,
    currentGroup,
    warehouses = ["Маркетплейс", "Готовая продукция"],
    onClose,
    onUpdated,
    onError
}: EditProductModalProps) {

    const [
        group,
        setGroup
    ] = useState(
        currentGroup
    );


    const [
        open,
        setOpen
    ] = useState(false);


    const [
        loading,
        setLoading
    ] = useState(false);


    const dropdownRef =
        useRef<HTMLDivElement>(null);


    useEffect(() => {

        const handler = (
            event: MouseEvent
        ) => {

            if (
                dropdownRef.current &&
                !dropdownRef.current.contains(
                    event.target as Node
                )
            ) {

                setOpen(false);

            }

        };


        document.addEventListener(
            "mousedown",
            handler
        );


        return () => {

            document.removeEventListener(
                "mousedown",
                handler
            );

        };

    }, []);


    const save = async () => {

        if (loading) {
            return;
        }


        if (group === currentGroup) {

            onError(
                "Изменения отсутствуют"
            );

            return;

        }


        setLoading(true);


        try {

            const response = await fetch(
                `http://127.0.0.1:8000/master-products/${productId}`,
                {
                    method: "PUT",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        group
                    })
                }
            );


            if (!response.ok) {

                throw new Error(
                    `Ошибка сервера: ${response.status}`
                );

            }


            const data =
                await response.json();


            if (data.status !== "ok") {

                throw new Error(
                    data.message ||
                    "Не удалось изменить товар"
                );

            }


            onUpdated();


        } catch (error) {

            const message =
                error instanceof TypeError
                    ? "Не удалось связаться с сервером"
                    : error instanceof Error
                        ? error.message
                        : "Не удалось изменить товар";


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
                        Изменить товар
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

                                    setOpen(
                                        prev => !prev
                                    );

                                }

                            }}
                        >

                            {group}

                            <span>
                                ▼
                            </span>

                        </div>


                        {open && (

                            <div className="select-options">

                                {warehouses.map(name => (
                                    <div key={name} onClick={() => {setGroup(name);setOpen(false);}}>{name}</div>
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
                        onClick={save}
                        disabled={loading}
                    >

                        {loading ? (

                            <>
                                <Loader size="small" />
                                <span>
                                    Сохранение...
                                </span>
                            </>

                        ) : (

                            "Сохранить"

                        )}

                    </button>

                </div>

            </div>

        </div>

    );

}


export default EditProductModal;