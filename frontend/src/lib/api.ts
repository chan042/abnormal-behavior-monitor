import type {
  AnalyticsResponse,
  BrowserLiveResult,
  BrowserLiveSessionsResponse,
  CamerasResponse,
  DashboardEvent,
  EventsResponse,
  SummaryResponse,
} from "@/types/dashboard";

const backendOrigin =
  process.env.NEXT_PUBLIC_BACKEND_ORIGIN?.replace(/\/$/, "") ?? "";

export function resolveApiUrl(path: string) {
  return backendOrigin ? `${backendOrigin}${path}` : path;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(resolveApiUrl(path), {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`${path} 요청 실패: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function fetchSummary() {
  return requestJson<SummaryResponse>("/api/summary");
}

export async function fetchCameras() {
  return requestJson<CamerasResponse>("/api/cameras");
}

export async function fetchEvents() {
  return requestJson<EventsResponse>("/api/events");
}

export async function fetchAnalytics() {
  return requestJson<AnalyticsResponse>("/api/analytics");
}

export async function fetchBrowserLiveSessions() {
  return requestJson<BrowserLiveSessionsResponse>("/api/browser-live/sessions");
}

export async function postEventReview(
  eventId: string,
  payload: { status?: string; operator_note?: string },
) {
  return requestJson<DashboardEvent>(`/api/events/${eventId}/status`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function postBrowserLiveFrame(
  sessionId: string,
  blob: Blob,
  timestampMs: number,
  cameraLabel: string,
) {
  const response = await fetch(
    resolveApiUrl(
      `/api/browser-live/frame?session_id=${encodeURIComponent(sessionId)}&timestamp_ms=${timestampMs}&camera_label=${encodeURIComponent(cameraLabel)}`,
    ),
    {
      method: "POST",
      headers: {
        "Content-Type": "image/jpeg",
      },
      body: blob,
      cache: "no-store",
    },
  );
  if (!response.ok) {
    throw new Error(`/api/browser-live/frame 요청 실패: ${response.status}`);
  }
  return (await response.json()) as BrowserLiveResult;
}
