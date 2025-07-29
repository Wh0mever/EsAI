const API = "http://127.0.0.1:8000/api/";
import Cookies from "js-cookie";


interface RequestOptions {
	method: string;
	headers: {
		"Content-Type": string;
		Accept: string;
		Authorization?: string;
	};
	body?: string;
}

async function mainRequest(endpoint: string, method: string, auth: boolean, body: any) {
	const url = `${API}${endpoint}`;
	const token = Cookies.get("access")
	const access = auth ? `Bearer ${token}` : undefined;

	let options: RequestOptions = {
		method: method,
		headers: {
			"Content-Type": "application/json",
			Accept: "application/json",
			Authorization: access,
		},
	};



	if (body) {
		options.body = JSON.stringify(body);
	}

	const response = await fetch(url, options);
	
	if (response.status < 300 && response.status >= 200) {
		const data = await response.json();

		return {
			status: response.status,
			ok: response.ok,
			data,
		};
	}
	if (response.status === 401) {
		throw new Error("Your token expired");
	}
}

async function refreshAuth() {
	const response = await fetch(`${API}users/token/refresh/`, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
		},
		body: JSON.stringify({ refresh: Cookies.get("refresh") }),
	});

	if (!response.ok) {
		console.warn("🔁 Refresh failed:", response.status);
		return;
	}

	const data = await response.json();
	const newAccess = data.access;

	if (newAccess) {
		Cookies.set("access", newAccess);
		console.log("✅ Access token обновлён");
	} else {
		console.warn("⚠️ Access токен не получен");
	}
}

export async function fetchData(endpoint: string, method: string = "GET", body?: any, auth: boolean = false) {
	try {
		return await mainRequest(endpoint, method, auth, body);
	} catch (error) {
		if (error instanceof Error && error.message === "token_expired") {
			await refreshAuth();
			return await mainRequest(endpoint, method, auth, body);
		} else {
			console.error("❌ Unexpected error:", error);
		}
	}
}
