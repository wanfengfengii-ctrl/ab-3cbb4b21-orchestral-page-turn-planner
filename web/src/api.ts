import type { ApiError, SolveResponse } from "./types";

/** All inputs violated the API's validation rules (HTTP 422). */
export class ValidationFailedError extends Error {
  readonly errors: ApiError[];

  constructor(errors: ApiError[]) {
    super("validation failed");
    this.name = "ValidationFailedError";
    this.errors = errors;
  }
}

export async function solve(payload: unknown): Promise<SolveResponse> {
  let response: Response;
  try {
    response = await fetch("/api/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new Error("无法连接 API 服务，请确认后端已启动");
  }

  if (response.status === 422) {
    const body = await response.json().catch(() => null);
    const errors: ApiError[] = Array.isArray(body?.errors)
      ? body.errors
      : [{ path: "$", message: body?.detail ?? "输入校验失败" }];
    throw new ValidationFailedError(errors);
  }
  if (!response.ok) {
    throw new Error(`API 返回 HTTP ${response.status}`);
  }
  return (await response.json()) as SolveResponse;
}
