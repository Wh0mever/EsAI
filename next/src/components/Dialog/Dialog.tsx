import React from 'react';
import './Dialog.css';

interface DialogProps {
    title: string;
    message: string;
    onAccept: () => void;
    onDecline: () => void;
}

export default function Dialog(DialogProps: DialogProps) {
    return (
        <div className="dialog">
            <div className="dialog__content">
                <h2>{DialogProps.title}</h2>
                <p>{DialogProps.message}</p>
                <div className="dialog__actions">
                    <button onClick={DialogProps.onAccept}>Accept</button>
                    <button onClick={DialogProps.onDecline}>Decline</button>
                </div>
            </div>
        </div>
    );
}