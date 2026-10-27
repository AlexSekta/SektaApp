import "./Loader.css";


interface LoaderProps {
    size?: "small" | "medium";
}


function Loader({
    size = "medium",
}: LoaderProps) {

    return (
        <span
            className={`loader loader-${size}`}
            aria-label="Загрузка"
        />
    );
}


export default Loader;