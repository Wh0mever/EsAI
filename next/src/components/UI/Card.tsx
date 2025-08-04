
interface ICard {
    children: React.ReactNode;
}

export function Card({children} : ICard) {
    return(
        <div className="bg-neutral-900 p-10 rounded-4xl flex gap-2 items-center">
            {children}
        </div>
    )
}