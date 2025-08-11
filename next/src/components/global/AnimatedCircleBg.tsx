export default function Breadcrumb() {
	return (
		<div className="absolute top-0">
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
