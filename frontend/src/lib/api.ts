/** Cliente HTTP: CSRF automático, cookies de sessão e erros sempre em português. */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
  }
  get offline() {
    return this.code === "offline";
  }
}

const CSRF_COOKIE = "julius_csrf";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function readCookie(name: string): string | null {
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

async function ensureCsrf(): Promise<string> {
  let token = readCookie(CSRF_COOKIE);
  if (!token) {
    await fetch("/api/health", { credentials: "same-origin" }).catch(() => undefined);
    token = readCookie(CSRF_COOKIE);
  }
  return token ?? "";
}

const STATUS_MESSAGES: Record<number, string> = {
  401: "Sua sessão expirou. Entre novamente.",
  403: "Você não tem permissão para esta ação.",
  404: "Não encontrado.",
  429: "Muitas tentativas. Aguarde um pouco e tente de novo.",
  500: "Algo deu errado do nosso lado. Tente novamente em instantes.",
};

interface Options {
  method?: string;
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
}

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  const method = opts.method ?? (opts.body !== undefined || opts.form ? "POST" : "GET");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (UNSAFE.has(method)) headers["X-CSRF-Token"] = await ensureCsrf();
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }

  let res: Response;
  try {
    res = await fetch(path, { method, headers, body, credentials: "same-origin", signal: opts.signal });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "offline", "Sem conexão com o servidor. Verifique sua internet e tente novamente.");
  }

  if (res.status === 204) return undefined as T;
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await res.json().catch(() => null) : null;
  if (!res.ok) {
    const err = data?.error;
    if (res.status === 401) window.dispatchEvent(new Event("julius:unauthorized"));
    throw new ApiError(
      res.status,
      err?.code ?? `http_${res.status}`,
      err?.message ?? STATUS_MESSAGES[res.status] ?? "Não foi possível concluir. Tente novamente.",
      err?.details,
    );
  }
  return data as T;
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "Algo inesperado aconteceu. Tente novamente.";
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "" && v !== false) sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}
