import { Message } from "./ChatForm";

export function ChatView({ messages }: { messages: Message[] }) {
    return (
        <div className="flex flex-col gap-4 overflow-y-auto max-h-[calc(100vh-300px)] pr-1">
            {messages.map((msg, index) => (
                <div
                    key={index}
                    className={`p-3 rounded-xl max-w-[80%] whitespace-pre-wrap ${
                        msg.role === "user"
                            ? "self-end bg-blue-600 text-white"
                            : "self-start bg-neutral-800 text-white"
                    }`}
                >
                    {msg.content}
                </div>
            ))}
        </div>
    );
}
