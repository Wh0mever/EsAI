const API = "http://127.0.0.1:8000/api/";
import Cookies from "js-cookie";


export async function fetchWithAuth(url: string, options = {}) {
	let accessToken = Cookies.get("access_token");

	const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/${url}`, {
		...options,
		headers: {
			...(options as any).headers,
			Authorization: `Bearer ${accessToken}`,
			"Content-Type": "application/json",
		},
	});

	if (response.status === 401) {
		const refreshToken = Cookies.get("refresh_token");
		const refreshRes = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/token/refresh/`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ refresh: refreshToken }),
		});

		if (refreshRes.ok) {
			const data = await refreshRes.json();
			Cookies.set("access_token", data.access, { expires: 7 });

			const retryRes = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/${url}`, {
				...options,
				headers: {
					...(options as any).headers,
					Authorization: `Bearer ${data.access}`,
					"Content-Type": "application/json",
				},
			});
			return retryRes;
		} else {
			Cookies.remove("access_token");
			Cookies.remove("refresh_token");
			window.location.href = "/auth/signin";
			return;
		}
	}

	return response;
}

export async function fetchData(endpoint: string, method: string = "GET", body?: any) {
	const url = `${API}${endpoint}`;

	const options: RequestInit = {
		method: method,
		headers: {
			"Content-Type": "application/json",
		},
	};

	if (body) {
		options.body = JSON.stringify(body);
	}

	try {
		const response = await fetch(url, options);
		const data = await response.json();

		return {
			status: response.status,
			ok: response.ok,
			data,
		};
	} catch (error) {
		return {
			status: null,
			ok: false,
			error,
		};
	}
}
