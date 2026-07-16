export default function Breadcrumb() {
    return (
        <div
            // esai-breadcrumb-art: в светлой теме декорация приглушается (globals.css),
            // иначе тёмный «круг» убивает контраст тёмных заголовков поверх него.
            className="esai-breadcrumb-art absolute top-0 w-full overflow-hidden -z-1"
            style={{
                WebkitMaskImage:
                    "linear-gradient(to bottom, rgba(0,0,0,1) 0%, rgba(0,0,0,1) 82%, rgba(0,0,0,0) 100%)",
                maskImage:
                    "linear-gradient(to bottom, rgba(0,0,0,1) 0%, rgba(0,0,0,1) 82%, rgba(0,0,0,0) 100%)",
            }}
        >
            <section className="flex justify-center py-15 pointer-events-none select-none">
                <img className="absolute top-0" src="/images/decorations/breadcrumb/breadcrumb-shape-top.webp" alt="" />
                <img
                    className="absolute z-15 top-0 left-0"
                    src="/images/decorations/breadcrumb/breadcrumb-shape-left.webp"
					alt=""
				/>
				<img
					className="absolute z-15 top-0 right-0"
					src="/images/decorations/breadcrumb/breadcrumb-shape-right.webp"
					alt=""
				/>
				<img
					className="absolute opacity-5 z-10 top-0 left-0"
					src="/images/decorations/breadcrumb/breadcrumb-shape-line-left.webp"
					alt=""
				/>
				<img
					className="absolute opacity-5 z-10 top-0 right-0"
					src="/images/decorations/breadcrumb/breadcrumb-shape-line-right.webp"
					alt=""
				/>
			</section>

            <section className="flex flex-col gap-5 items-center py-10 h-full breadcrumb-bg">
                <div className="breadcrumb-bg-wrapper">
                    <div className=""></div>
                </div>
            </section>
        </div>
    );
}
