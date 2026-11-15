// Small JSON helper for our own API. Errors carry the server's message.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function messageFrom(status, data) {
  const detail = data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "Some fields aren't valid. Check them and try again.";
  if (status === 429) return "Too many tries. Wait a few minutes and try again.";
  return `Something went wrong (${status}). Try again.`;
}

/** GET when body is undefined, otherwise POST the body as JSON. */
export async function api(path, body) {
  const options = { credentials: "same-origin", headers: { Accept: "application/json" } };
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, options);
  } catch {
    throw new ApiError(0, "Can't reach the server. Check that it's running.");
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* empty or non-JSON body */
  }
  if (!res.ok) throw new ApiError(res.status, messageFrom(res.status, data));
  return data;
}
