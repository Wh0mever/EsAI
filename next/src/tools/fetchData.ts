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
	const token = Cookies.get("access");
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

async function refreshAuth(): Promise<string | null> {
	const refresh = Cookies.get("refresh");
	if (!refresh) return null;

	const response = await fetch(`${API}users/token/refresh/`, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
		},
		body: JSON.stringify({ refresh }),
	});

	if (!response.ok) return null;

	const data = await response.json();
	const newAccess = data.access;
	const newRefresh = data.refresh;
	if (newAccess) {
		Cookies.set("access", newAccess);
		Cookies.set("refresh", newRefresh);
		console.log("✅ Access token обновлён");
		return newAccess;
	}
	return null;
}

export async function fetchData(endpoint: string, method: string = "GET", body?: any, auth: boolean = false) {
	try {
		return await mainRequest(endpoint, method, auth, body);
	} catch (error) {
		if (error instanceof Error && error.message === "Your token expired") {
			const newToken = await refreshAuth();
			if (!newToken) throw new Error("Unable to refresh token");
			return await mainRequest(endpoint, method, auth, body);
		}
	}
}
