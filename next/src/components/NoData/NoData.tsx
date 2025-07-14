interface NoDataProps {
    text?: string;
    image?: boolean;
}

export default function NoData({ text = "", image = true }: NoDataProps) {
    return (
        <div className="flex flex-col items-center justify-center">
            <img src="/images/decorations/nodata.webp" alt="" className="" />
            <p className="p-2">{text}</p>
        </div>
    );
}