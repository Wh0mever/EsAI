import React from 'react';
import { BsStars } from 'react-icons/bs';

export default function FeatureCard({ title, image, description }: { title: string; image: string; description: string }) {
    return (
        <div className="group flex flex-col border rounded-2xl overflow-hidden border-neutral-800 transition-colors h-full text-center">
            <div className="bg-neutral-900/25 min-h-70 flex items-center justify-center p-2">
                <img src={image} alt={title} className="w-fit object-cover rounded-t-lg" />
            </div>
            <div className="lg:px-6 px-3 py-10 flex flex-col gap-3 relative h-full bg-neutral-900/50 group-hover:bg-indigo-800/25 duration-300">
                <i className="text-3xl absolute -top-10 left-1/2 transform -translate-x-1/2 p-4 rounded-full bg-neutral-800 text-white group-hover:bg-indigo-700 transition-colors duration-300">
                    <BsStars />
                </i>
                <h3 className="text-xl font-semibold mt-2 text-white">{title}</h3>
                <p className="text-gray-300 mt-1">{description}</p>
            </div>
        </div>
    );
}