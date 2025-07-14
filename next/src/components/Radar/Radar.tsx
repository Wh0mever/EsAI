import './Radar.scss';

export default function Radar({className = ''}: {className?: string}) {
    return (
        <div className={`radar ${className}`}>
            <div className="radar-view"></div>
            <div className="radar-image-container p-3 bg-black rounded-2xl">
                <img src="/images/logo/head.svg" alt="" />
            </div>
        </div>
    )
}