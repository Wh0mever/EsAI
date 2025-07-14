const API = 'http://127.0.0.1:8000/api/';

export async function fetchData(endpoint: string, method: string = 'GET', body?: any) {
  const url = `${API}${endpoint}`;

  const options: RequestInit = {
    method: method,
    headers: {
      'Content-Type': 'application/json',
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

