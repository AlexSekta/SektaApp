import { useEffect } from "react";

import "./Toast.css";


export type ToastType =
    | "success"
    | "error"
    | "warning";


export interface ToastRow {
    text: string;
    type: ToastType;
}


interface ToastProps {
    message: string;
    type: ToastType;
    onClose: () => void;
    duration?: number;
    rows?: ToastRow[];
}


function Toast({
    message,
    type,
    onClose,
    duration = 4000,
    rows
}: ToastProps) {

    useEffect(() => {

        const timer =
            window.setTimeout(
                onClose,
                duration
            );

        return () => {
            window.clearTimeout(
                timer
            );
        };

    }, [
        duration,
        onClose
    ]);


    const hasRows =
        rows &&
        rows.length > 0;


    return (

        <div
            className={
                `toast toast-${type} `
                + (
                    hasRows
                        ? "toast-with-rows"
                        : ""
                )
            }
            role="alert"
        >

            {!hasRows && (
                <div className="toast-indicator" />
            )}


            <div className="toast-content">

                <div className="toast-message">
                    {message}
                </div>


                {hasRows && (

                    <div className="toast-rows">

                        {rows.map(
                            (
                                row,
                                index
                            ) => (

                                <div
                                    className="toast-row"
                                    key={index}
                                >

                                    <div
                                        className={
                                            `toast-row-indicator `
                                            + `toast-row-indicator-${row.type}`
                                        }
                                    />

                                    <div className="toast-row-text">
                                        • {row.text}
                                    </div>

                                </div>

                            )
                        )}

                    </div>

                )}

            </div>


            <button
                type="button"
                className="toast-close"
                onClick={onClose}
                aria-label="Закрыть"
            >
                ×
            </button>

        </div>

    );

}


export default Toast;
