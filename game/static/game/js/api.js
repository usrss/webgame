/**
 * HTTP access to the tank endpoints.
 *
 * Errors are surfaced as `ApiError` carrying the HTTP status and any parsed
 * JSON body, so the caller can map 404/403 (no longer a member) and 429
 * (cooldown) to specific UI behaviour.
 */

export class ApiError extends Error {
  constructor(status, data) {
    super(`Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

function csrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta && meta.content) {
    return meta.content;
  }
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function fetchState(url) {
  const response = await fetch(url, {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  const data = await readJson(response);
  if (!response.ok) {
    throw new ApiError(response.status, data);
  }
  return data;
}

export async function postJson(url, body = null) {
  const headers = {
    Accept: "application/json",
    "X-CSRFToken": csrfToken(),
  };
  if (body !== null) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers,
    body: body === null ? undefined : JSON.stringify(body),
  });
  const data = await readJson(response);
  if (!response.ok) {
    throw new ApiError(response.status, data);
  }
  return data;
}

export async function feed(url) {
  const response = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "X-CSRFToken": csrfToken(),
    },
  });
  const data = await readJson(response);
  if (!response.ok) {
    throw new ApiError(response.status, data);
  }
  return data;
}
