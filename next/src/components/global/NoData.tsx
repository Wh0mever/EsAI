interface NoDataProps {
    text?: string;
    image?: boolean;
    className?: string;
}

export default function NoData({ text = "", image = true, className }: NoDataProps) {
    return (
        <div className={`flex flex-col items-center justify-center ${className}`} style={{
            animation: '1s ease-in-out 0s 1 normal forwards running showCard'
        }}>
            <img src="/images/decorations/nodata.webp" alt="" className="" />
            <p className="p-2">{text}</p>
        </div>
    );
}