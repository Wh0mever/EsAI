import "@/assets/style.scss";
import ChatWorkspace from "@/components/chat/ChatWorkspace";

// Root page = working chat (no landing). The chat works anonymously; the
// start screen with slogan/quick actions/scenarios shows until the first message.
export default function Home() {
	return <ChatWorkspace />;
}
