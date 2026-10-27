import Loader from "./Loader";

import "./DeleteConfirmModal.css";


interface DeleteConfirmModalProps {

    onClose: () => void;

    onConfirm: () => void;

    loading: boolean;

}


function DeleteConfirmModal({
    onClose,
    onConfirm,
    loading
}: DeleteConfirmModalProps) {

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
                        Удаление товара
                    </h2>

                </div>


                <div className="modal-body">

                    <p>
                        Вы действительно хотите удалить товар?
                    </p>

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
                        className="delete-button"
                        onClick={onConfirm}
                        disabled={loading}
                    >

                        {loading ? (

                            <>
                                <Loader size="small" />
                                <span>
                                    Удаление...
                                </span>
                            </>

                        ) : (

                            "Удалить"

                        )}

                    </button>

                </div>

            </div>

        </div>

    );

}


export default DeleteConfirmModal;