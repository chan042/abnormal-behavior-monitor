"use client";

import Image from "next/image";
import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import {
 fetchAnalytics,
 fetchCameras,
 fetchEvents,
 fetchSummary,
 postEventReview,
 resolveApiUrl,
} from "@/lib/api";
import type {
 AnalyticsResponse,
 BrowserLiveResult,
 CameraSummary,
 DashboardEvent,
 DashboardView,
 EventStatus,
 EventType,
 SummaryResponse,
} from "@/types/dashboard";

import { BrowserLivePanel } from "./browser-live-panel";

const EmptyInboxIcon = () => (
 <svg className="h-16 w-16 text-neutral-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
 <path
 strokeLinecap="round"
 strokeLinejoin="round"
 strokeWidth={1}
 d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"
 />
 </svg>
);

const EVENT_LABELS: Record<EventType, string> = {
 fall_suspected: "실신 의심",
 wandering_suspected: "배회 의심",
};

const STATUS_LABELS: Record<EventStatus, string> = {
 new: "미확인",
 confirmed: "정탐",
 false_positive: "오탐",
 dismissed: "종료",
};

const VIEW_ITEMS: Array<{ id: DashboardView; label: string }> = [
 { id: "live", label: "실시간 관제" },
 { id: "events", label: "이벤트 검토" },
 { id: "analytics", label: "통계/분석" },
 { id: "settings", label: "설정" },
];

const PREFERENCE_KEYS = {
 videoMode: "dashboard.videoMode",
 autoplayPreview: "dashboard.autoplayPreview",
 autoRefreshSeconds: "dashboard.autoRefreshSeconds",
 autoNext: "dashboard.autoNext",
} as const;

type ConnectionMode = "connecting" | "live" | "polling";

function classNames(...values: Array<string | false | null | undefined>) {
 return values.filter(Boolean).join(" ");
}

function formatDateTime(value?: string | Date | null) {
 if (!value) return "없음";
 const date = value instanceof Date ? value : new Date(value);
 if (Number.isNaN(date.getTime())) return String(value);
 return new Intl.DateTimeFormat("ko-KR", {
 year: "numeric",
 month: "2-digit",
 day: "2-digit",
 hour: "2-digit",
 minute: "2-digit",
 second: "2-digit",
 hour12: false,
 }).format(date);
}

function formatCompactDateTime(value?: string | null) {
 if (!value) return "-";
 const date = new Date(value);
 if (Number.isNaN(date.getTime())) return value;
 return new Intl.DateTimeFormat("ko-KR", {
 month: "2-digit",
 day: "2-digit",
 hour: "2-digit",
 minute: "2-digit",
 hour12: false,
 }).format(date);
}

function formatTimeOnly(value?: Date | null) {
 if (!value) return "대기 중";
 return new Intl.DateTimeFormat("ko-KR", {
 hour: "2-digit",
 minute: "2-digit",
 second: "2-digit",
 hour12: false,
 }).format(value);
}

function formatConfidence(value?: number | null) {
 if (value == null) return "-";
 return `${Math.round(value * 100)}%`;
}

function formatSourceTimestamp(value?: number | null) {
 if (value == null) return "-";
 const totalSeconds = Math.floor(value / 1000);
 const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
 const seconds = String(totalSeconds % 60).padStart(2, "0");
 const millis = String(value % 1000).padStart(3, "0");
 return `${minutes}:${seconds}.${millis}`;
}

function priorityLabel(priority?: string) {
 if (priority === "critical") return "즉시 검토";
 if (priority === "warning") return "검토 필요";
 if (priority === "muted") return "저우선";
 return "일반";
}

function priorityTone(priority?: string) {
 if (priority === "critical") return "border-[#ff7b72]/30 bg-[#ff7b72]/10 text-[#ff7b72]";
 if (priority === "warning") return "border-[#d29922]/30 bg-[#d29922]/10 text-[#d29922]";
 if (priority === "muted") return "border-[#8b949e]/30 bg-[#8b949e]/10 text-[#8b949e]";
 return "border-[#3fb950]/30 bg-[#3fb950]/10 text-[#3fb950]";
}

function statusTone(status?: EventStatus | string) {
 if (status === "confirmed") return "border-[#3fb950]/30 bg-[#3fb950]/10 text-[#3fb950]";
 if (status === "false_positive") return "border-[#ff7b72]/30 bg-[#ff7b72]/10 text-[#ff7b72]";
 if (status === "dismissed") return "border-[#8b949e]/30 bg-[#8b949e]/10 text-[#8b949e]";
 return "border-neutral-800 bg-transparent text-neutral-300";
}

function eventTone(eventType?: EventType | string | null) {
 if (eventType === "fall_suspected") return "border-[#ff7b72]/30 bg-[#ff7b72]/10 text-[#ff7b72]";
 if (eventType === "wandering_suspected") {
 return "border-[#d29922]/30 bg-[#d29922]/10 text-[#d29922]";
 }
 return "border-[#8b949e]/30 bg-[#8b949e]/10 text-[#8b949e]";
}

function connectionLabel(mode: ConnectionMode) {
 if (mode === "live") return "SSE 실시간 연결";
 if (mode === "polling") return "폴링 갱신 모드";
 return "연결 준비 중";
}

function eventTypeLabel(value?: EventType | string | null) {
 if (!value) return "이벤트 없음";
 return EVENT_LABELS[value as EventType] ?? value;
}

function priorityStripe(priority?: string) {
 if (priority === "critical") return "bg-red-400";
 if (priority === "warning") return "bg-amber-400";
 if (priority === "muted") return "bg-neutral-500";
 return "bg-emerald-400";
}

function systemStateLabel(value?: string) {
 if (value === "attention") return "즉시 검토 필요";
 if (value === "monitoring") return "검토 큐 활성";
 return "안정";
}

function cameraStreamLabel(value?: string) {
 if (value === "online") return "실시간 연결";
 if (value === "error") return "오류";
 if (value === "standby" || value === "idle") return "대기";
 return value || "대기";
}

function cameraStreamTone(value?: string) {
 if (value === "online") return "border-[#3fb950]/30 bg-[#3fb950]/10 text-[#3fb950]";
 if (value === "error") return "border-[#ff7b72]/30 bg-[#ff7b72]/10 text-[#ff7b72]";
 return "border-[#8b949e]/30 bg-[#8b949e]/10 text-[#8b949e]";
}

function readPreference(key: string, fallback: string) {
 if (typeof window === "undefined") return fallback;
 return window.localStorage.getItem(key) ?? fallback;
}

function writePreference(key: string, value: string) {
 if (typeof window === "undefined") return;
 window.localStorage.setItem(key, value);
}

function PanelTitle({ title, right }: { title: string; right?: React.ReactNode }) {
 return (
 <div className="mb-2 flex items-center justify-between gap-3 border-b border-neutral-700 pb-2">
 <h2 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-400 ">{title}</h2>
 {right && <div>{right}</div>}
 </div>
 );
}

function MetricCard({
 label,
 value,
 highlight,
 icon,
}: {
 label: string;
 value: string | number;
 highlight?: boolean;
 icon?: React.ReactNode;
}) {
 return (
 <div className="flex flex-col gap-1" title={String(value)}>
 <div className="text-[11px] font-medium uppercase tracking-wider text-neutral-500 truncate">{label}</div>
 <div className="flex items-center gap-2">
 {icon ? (
 <div className={classNames("flex shrink-0 items-center justify-center text-lg", highlight ? "text-[#ff7b72]" : "text-[#8b949e]")}>
 {icon}
 </div>
 ) : null}
 <div
 className={classNames(
 "text-2xl font-bold tracking-tight truncate",
 highlight ? "text-[#ff7b72] " : "text-neutral-100 ",
 )}
 >
 {value}
 </div>
 </div>
 </div>
 );
}

function TinyTrendBars({ values, labels }: { values: number[]; labels: string[] }) {
 const maxValue = Math.max(...values, 1) * 1.1; // 10% headroom
 
 return (
 <div className="relative flex h-full w-full flex-col pt-6">
 {/* Background grid lines */}
 <div className="absolute inset-x-0 bottom-6 top-6 flex flex-col justify-between pointer-events-none">
 <div className="w-full border-b border-white/5" />
 <div className="w-full border-b border-white/5" />
 <div className="w-full border-b border-white/5" />
 </div>
 
 {/* Y-axis max/min label */}
 <div className="absolute left-0 top-1 text-[9px] font-medium text-neutral-600 pointer-events-none">
 {Math.floor(maxValue)}
 </div>
 <div className="absolute left-0 bottom-5 text-[9px] font-medium text-neutral-600 pointer-events-none">
 0
 </div>
 
 <div className="z-10 flex h-full w-full items-end justify-between gap-1.5 pb-1 pl-4">
 {values.map((value, index) => {
 const heightPct = Math.max((value / maxValue) * 100, 2);
 return (
 <div key={`${labels[index]}-${index}`} className="group relative flex h-full flex-1 flex-col justify-end items-center cursor-default">
 {/* Tooltip */}
 <div className="absolute bottom-full mb-1 opacity-0 transition-all duration-200 group-hover:opacity-100 group-hover:-translate-y-1 pointer-events-none z-20 flex flex-col items-center">
 <span className="rounded bg-neutral-100 px-2 py-0.5 text-[11px] font-bold text-black shadow-lg">
 {value}
 </span>
 <div className="h-1.5 w-1.5 rotate-45 bg-neutral-100 -mt-1" />
 </div>
 
 {/* Bar */}
 <div className="flex h-full w-full items-end justify-center pb-5 relative">
 <div
 className="w-full max-w-[32px] rounded-t-[3px] transition-all duration-300 ease-out bg-neutral-800 group-hover:bg-[#ff7b72] relative overflow-hidden"
 style={{ height: `${heightPct}%` }}
 >
 <div className="absolute inset-x-0 bottom-0 top-1/2 bg-gradient-to-t from-transparent to-white/20 hidden group-hover:block" />
 </div>
 </div>
 
 {/* Label */}
 <span className="absolute bottom-0 text-[10px] font-medium text-neutral-500 transition-colors group-hover:text-neutral-300 w-full text-center truncate">
 {labels[index]}
 </span>
 </div>
 );
 })}
 </div>
 </div>
 );
}

function ProgressMetric({
 label,
 value,
 progress,
}: {
 label: string;
 value: string;
 progress: number;
}) {
 return (
 <div className="space-y-1.5">
 <div className="flex items-end justify-between">
 <span className="text-[11px] uppercase tracking-wider text-neutral-400">{label}</span>
 <strong className="text-sm font-bold text-white ">{value}</strong>
 </div>
 <div className="h-1.5 overflow-hidden rounded-sm bg-neutral-800 border border-neutral-800">
 <div
 className="h-full bg-blue-500 "
 style={{ width: `${Math.max(Math.min(progress, 100), 0)}%` }}
 />
 </div>
 </div>
 );
}

function BarList({
 rows,
}: {
 rows: Array<{ label: string; value: number; tone?: string }>;
}) {
 const maxValue = Math.max(...rows.map((row) => row.value), 1);
 if (!rows.length) {
 return (
 <div className="flex h-full items-center justify-center border border-neutral-800 border-neutral-800 bg-neutral-800 p-4 text-sm text-neutral-500">
 데이터 없음
 </div>
 );
 }
 return (
 <div className="space-y-3">
 {rows.map((row) => (
 <div key={`${row.label}-${row.value}`} className="space-y-2">
 <div className="flex items-center justify-between gap-3 text-sm">
 <span className="truncate text-neutral-300">{row.label}</span>
 <strong className="text-neutral-200">{row.value}</strong>
 </div>
 <div className="h-2 overflow-hidden rounded-full bg-neutral-800">
 <div
 className={classNames(
 "h-full rounded-full",
 row.tone ?? "bg-neutral-500",
 )}
 style={{ width: `${Math.max((row.value / maxValue) * 100, 6)}%` }}
 />
 </div>
 </div>
 ))}
 </div>
 );
}

function EmptyState({ message }: { message: string }) {
 return (
 <div className="flex h-full min-h-32 w-full flex-col items-center justify-center gap-3 opacity-60">
 <EmptyInboxIcon />
 <div className="text-sm font-medium text-neutral-400">{message}</div>
 </div>
 );
}

function SkeletonMetricCard() {
 return (
 <div className="animate-pulse border border-neutral-800 bg-neutral-800 p-4">
 <div className="h-4 w-16 rounded bg-neutral-800"></div>
 <div className="mt-4 h-8 w-12 rounded bg-neutral-800"></div>
 </div>
 );
}

export function DashboardApp() {
 const [view, setView] = useState<DashboardView>("live");
 const [summary, setSummary] = useState<SummaryResponse | null>(null);
 const [events, setEvents] = useState<DashboardEvent[]>([]);
 const [cameras, setCameras] = useState<CameraSummary[]>([]);
 const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null);

 const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
 const [selectedCameraId, setSelectedCameraId] = useState<string | null>(null);
 const [videoMode, setVideoMode] = useState<"overlay" | "clip">("overlay");
 const [autoplayPreview, setAutoplayPreview] = useState(false);
 const [autoNext, setAutoNext] = useState(true);
 const [autoRefreshSeconds, setAutoRefreshSeconds] = useState(20);

 const [eventTypeFilter, setEventTypeFilter] = useState<"all" | EventType>("all");
 const [statusFilter, setStatusFilter] = useState<"all" | EventStatus>("all");
 const [cameraFilter, setCameraFilter] = useState<string>("all");

 const [loading, setLoading] = useState(true);
 const [error, setError] = useState<string | null>(null);
 const [connectionMode, setConnectionMode] = useState<ConnectionMode>("connecting");
 const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);
 const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
 const initialLoadRef = useRef(true);
 const noteFieldRef = useRef<HTMLTextAreaElement | null>(null);

 const [showStatusLog, setShowStatusLog] = useState(false);
 const [selectedEventIds, setSelectedEventIds] = useState<Set<string>>(new Set());
 const [toasts, setToasts] = useState<Array<{ id: string; message: string }>>([]);

 const addToast = useCallback((message: string) => {
 const id = Math.random().toString(36).slice(2);
 setToasts((prev) => [...prev, { id, message }]);
 window.setTimeout(() => {
 setToasts((prev) => prev.filter((toast) => toast.id !== id));
 }, 3000);
 }, []);

 useEffect(() => {
 setVideoMode(readPreference(PREFERENCE_KEYS.videoMode, "overlay") as "overlay" | "clip");
 setAutoplayPreview(readPreference(PREFERENCE_KEYS.autoplayPreview, "true") === "true");
 setAutoNext(readPreference(PREFERENCE_KEYS.autoNext, "true") === "true");
 setAutoRefreshSeconds(
 Number(readPreference(PREFERENCE_KEYS.autoRefreshSeconds, "20")) || 20,
 );
 }, []);

 useEffect(() => writePreference(PREFERENCE_KEYS.videoMode, videoMode), [videoMode]);
 useEffect(
 () => writePreference(PREFERENCE_KEYS.autoplayPreview, String(autoplayPreview)),
 [autoplayPreview],
 );
 useEffect(() => writePreference(PREFERENCE_KEYS.autoNext, String(autoNext)), [autoNext]);
 useEffect(
 () => writePreference(PREFERENCE_KEYS.autoRefreshSeconds, String(autoRefreshSeconds)),
 [autoRefreshSeconds],
 );

 const loadData = useCallback(async () => {
 if (initialLoadRef.current) {
 setLoading(true);
 }

 try {
 const [nextSummary, nextEvents, nextCameras, nextAnalytics] = await Promise.all([
 fetchSummary(),
 fetchEvents(),
 fetchCameras(),
 fetchAnalytics(),
 ]);

 setSummary(nextSummary);
 setEvents(nextEvents.items);
 setCameras(nextCameras.items);
 setAnalytics(nextAnalytics);
 setLastUpdatedAt(new Date());
 setError(null);

 setSelectedEventId((current) => {
 if (current && nextEvents.items.some((event) => event.event_id === current)) {
 return current;
 }
 return nextEvents.items[0]?.event_id ?? null;
 });

 setSelectedCameraId((current) => {
 if (current && nextCameras.items.some((camera) => camera.camera_id === current)) {
 return current;
 }
 return nextCameras.items[0]?.camera_id ?? nextEvents.items[0]?.camera_id ?? null;
 });

 setSelectedEventIds((current) => {
 const nextIds = new Set<string>();
 const validIds = new Set(nextEvents.items.map((event) => event.event_id));
 current.forEach((id) => {
 if (validIds.has(id)) {
 nextIds.add(id);
 }
 });
 return nextIds;
 });

 setNoteDrafts((current) => {
 const nextDrafts = { ...current };
 nextEvents.items.forEach((event) => {
 if (!(event.event_id in nextDrafts)) {
 nextDrafts[event.event_id] = event.operator_note || "";
 }
 });
 return nextDrafts;
 });
 } catch (loadError) {
 setError(loadError instanceof Error ? loadError.message : String(loadError));
 } finally {
 initialLoadRef.current = false;
 setLoading(false);
 }
 }, []);

 useEffect(() => {
 void loadData();
 }, [loadData]);

 useEffect(() => {
 let disposed = false;
 let source: EventSource | null = null;
 let pollingTimer: number | null = null;

 const startPolling = () => {
 if (disposed) return;
 if (pollingTimer) {
 window.clearInterval(pollingTimer);
 }
 setConnectionMode("polling");
 pollingTimer = window.setInterval(() => {
 void loadData();
 }, Math.max(autoRefreshSeconds, 10) * 1000);
 };

 if ("EventSource" in window) {
 setConnectionMode("connecting");
 source = new EventSource(
 resolveApiUrl(
 `/api/stream?heartbeat=${Math.max(3, Math.min(autoRefreshSeconds, 30))}`,
 ),
 );

 source.addEventListener("summary", () => {
 if (disposed) return;
 setConnectionMode("live");
 void loadData();
 });

 source.addEventListener("heartbeat", () => {
 if (disposed) return;
 setConnectionMode("live");
 });

 source.onerror = () => {
 if (disposed) return;
 source?.close();
 source = null;
 startPolling();
 };
 } else {
 startPolling();
 }

 return () => {
 disposed = true;
 source?.close();
 if (pollingTimer) {
 window.clearInterval(pollingTimer);
 }
 };
 }, [autoRefreshSeconds, loadData]);

 const filteredEvents = useMemo(() => {
 return events.filter((event) => {
 if (eventTypeFilter !== "all" && event.event_type !== eventTypeFilter) return false;
 if (statusFilter !== "all" && event.status !== statusFilter) return false;
 if (cameraFilter !== "all" && event.camera_id !== cameraFilter) return false;
 return true;
 });
 }, [cameraFilter, eventTypeFilter, events, statusFilter]);

 const filteredCameras = useMemo(() => {
 return cameras;
 }, [cameras]);

 const eventCameraOptions = useMemo(() => {
 const uniqueCameras = new Map<string, string>();
 events.forEach((event) => {
 if (!uniqueCameras.has(event.camera_id)) {
 uniqueCameras.set(event.camera_id, event.camera_name);
 }
 });
 return Array.from(uniqueCameras.entries())
 .map(([cameraId, cameraName]) => ({ cameraId, cameraName }))
 .sort((left, right) => left.cameraName.localeCompare(right.cameraName, "ko-KR"));
 }, [events]);

 const selectedEvent =
 filteredEvents.find((event) => event.event_id === selectedEventId) ??
 events.find((event) => event.event_id === selectedEventId) ??
 filteredEvents[0] ??
 events[0] ??
 null;

 const selectedCamera =
 filteredCameras.find((camera) => camera.camera_id === selectedCameraId) ??
 cameras.find((camera) => camera.camera_id === selectedCameraId) ??
 filteredCameras.find((camera) => camera.camera_id === selectedEvent?.camera_id) ??
 cameras.find((camera) => camera.camera_id === selectedEvent?.camera_id) ??
 filteredCameras[0] ??
 cameras[0] ??
 null;

 const selectedCameraEvents = useMemo(() => {
 if (!selectedCamera) return [];
 return events
 .filter((event) => event.camera_id === selectedCamera.camera_id)
 .slice(0, 6);
 }, [events, selectedCamera]);

 const refreshNow = useCallback(async () => {
 await loadData();
 }, [loadData]);

 const reviewEvent = useCallback(
 async (eventId: string, status: EventStatus) => {
 await postEventReview(eventId, {
 status,
 operator_note: noteDrafts[eventId] ?? "",
 });
 addToast(`이벤트 1건 ${STATUS_LABELS[status]} 처리됨`);

 if (autoNext && status !== "new") {
 const currentIndex = filteredEvents.findIndex((event) => event.event_id === eventId);
 const nextEvent = filteredEvents
 .slice(Math.max(currentIndex + 1, 0))
 .find((event) => event.status === "new");
 if (nextEvent) {
 setSelectedEventId(nextEvent.event_id);
 setSelectedCameraId(nextEvent.camera_id);
 }
 }

 await loadData();
 },
 [addToast, autoNext, filteredEvents, loadData, noteDrafts],
 );

 const saveNote = useCallback(
 async (eventId: string) => {
 await postEventReview(eventId, {
 operator_note: noteDrafts[eventId] ?? "",
 });
 addToast("운영자 메모를 저장했습니다.");
 await loadData();
 },
 [addToast, loadData, noteDrafts],
 );

 const bulkUpdateStatus = useCallback(
 async (status: EventStatus) => {
 if (selectedEventIds.size === 0) return;
 await Promise.all(
 Array.from(selectedEventIds).map((eventId) =>
 postEventReview(eventId, {
 status,
 operator_note: noteDrafts[eventId] ?? "",
 }),
 ),
 );
 addToast(`${selectedEventIds.size}개 항목을 ${STATUS_LABELS[status]} 처리했습니다.`);
 setSelectedEventIds(new Set());
 await loadData();
 },
 [addToast, loadData, noteDrafts, selectedEventIds],
 );

 const toggleEventSelection = useCallback((id: string) => {
 setSelectedEventIds((current) => {
 const next = new Set(current);
 if (next.has(id)) {
 next.delete(id);
 } else {
 next.add(id);
 }
 return next;
 });
 }, []);

 const handleInference = useCallback(
 (result: BrowserLiveResult) => {
 if (result.events.length > 0) {
 void loadData();
 }
 },
 [loadData],
 );

 useEffect(() => {
 function handleKeyDown(event: KeyboardEvent) {
 const target = event.target as HTMLElement | null;
 if (target) {
 const tagName = target.tagName.toLowerCase();
 if (tagName === "input" || tagName === "textarea" || tagName === "select") {
 return;
 }
 }

 if (view !== "events" || filteredEvents.length === 0) return;
 const currentIndex = filteredEvents.findIndex(
 (item) => item.event_id === selectedEvent?.event_id,
 );

 if (event.key === "j" || event.key === "J") {
 event.preventDefault();
 const nextEvent = filteredEvents[Math.min(currentIndex + 1, filteredEvents.length - 1)];
 if (nextEvent) {
 setSelectedEventId(nextEvent.event_id);
 setSelectedCameraId(nextEvent.camera_id);
 }
 }

 if (event.key === "k" || event.key === "K") {
 event.preventDefault();
 const nextEvent = filteredEvents[Math.max(currentIndex - 1, 0)];
 if (nextEvent) {
 setSelectedEventId(nextEvent.event_id);
 setSelectedCameraId(nextEvent.camera_id);
 }
 }

 if (event.key === "1") {
 event.preventDefault();
 setVideoMode("clip");
 }

 if (event.key === "2") {
 event.preventDefault();
 setVideoMode("overlay");
 }

 if (event.key === "m" || event.key === "M") {
 event.preventDefault();
 noteFieldRef.current?.focus();
 }

 if (!selectedEvent) return;

 if (event.key === "c" || event.key === "C") {
 event.preventDefault();
 void reviewEvent(selectedEvent.event_id, "confirmed");
 }
 if (event.key === "f" || event.key === "F") {
 event.preventDefault();
 void reviewEvent(selectedEvent.event_id, "false_positive");
 }
 if (event.key === "d" || event.key === "D") {
 event.preventDefault();
 void reviewEvent(selectedEvent.event_id, "dismissed");
 }
 if (event.key === "n" || event.key === "N") {
 event.preventDefault();
 void reviewEvent(selectedEvent.event_id, "new");
 }
 }

 window.addEventListener("keydown", handleKeyDown);
 return () => window.removeEventListener("keydown", handleKeyDown);
 }, [filteredEvents, reviewEvent, selectedEvent, view]);

 const trendBuckets = (analytics?.timeline ?? []).slice(-7);
 const trendLabels = trendBuckets.map((bucket) =>
 new Date(bucket.bucket).toLocaleDateString("ko-KR", { weekday: "short" }),
 );
 const trendValues = trendBuckets.map((bucket) => bucket.total);

 const reviewedRate =
 analytics && analytics.overview.total_events > 0
 ? (analytics.overview.reviewed_events / analytics.overview.total_events) * 100
 : 0;
 const alertLoadRate =
 summary && summary.events.total > 0
 ? (summary.events.new / summary.events.total) * 100
 : 0;

 const incidentRows = filteredEvents.slice(0, 10);
 const statusLogRows = filteredEvents.slice(0, 8);
 const noteValue = selectedEvent ? noteDrafts[selectedEvent.event_id] ?? "" : "";
 const savedNoteValue = selectedEvent?.operator_note ?? "";
 const isNoteDirty = selectedEvent ? noteValue !== savedNoteValue : false;
 const hasActiveFilters =
 eventTypeFilter !== "all" ||
 statusFilter !== "all" ||
 cameraFilter !== "all";
 const filteredNewCount = filteredEvents.filter((event) => event.status === "new").length;
 const alertCameraCount = filteredCameras.filter(
 (camera) => camera.unreviewed_events > 0,
 ).length;
 const liveCapableCameraCount = filteredCameras.filter((camera) => camera.live_supported).length;
 const topCamera = analytics?.by_camera?.[0];

 const byTypeRows = (analytics?.by_type ?? []).map((row) => ({
 label: EVENT_LABELS[row.event_type as EventType] ?? row.event_type,
 value: row.count,
 tone:
 row.event_type === "fall_suspected"
 ? "bg-red-500"
 : "bg-amber-500",
 }));

 const byStatusRows = (analytics?.by_status ?? []).map((row) => ({
 label: STATUS_LABELS[row.status as EventStatus] ?? row.status,
 value: row.count,
 tone:
 row.status === "confirmed"
 ? "bg-emerald-500"
 : row.status === "false_positive"
 ? "bg-red-500"
 : row.status === "dismissed"
 ? "bg-neutral-600"
 : "bg-neutral-500",
 }));

 const byCameraRows = (analytics?.by_camera ?? []).slice(0, 6).map((row) => ({
 label: row.camera_name,
 value: row.count,
 tone: "bg-indigo-500",
 }));

 const resetFilters = useCallback(() => {
 setEventTypeFilter("all");
 setStatusFilter("all");
 setCameraFilter("all");
 }, []);

 useEffect(() => {
 function handleGlobalShortcuts(event: KeyboardEvent) {
 if (
 (event.metaKey || event.ctrlKey) &&
 event.key.toLowerCase() === "s" &&
 view === "events" &&
 selectedEvent &&
 isNoteDirty
 ) {
 event.preventDefault();
 void saveNote(selectedEvent.event_id);
 }

 if (event.key === "Escape") {
 if (document.activeElement instanceof HTMLElement) {
 document.activeElement.blur();
 }
 if (hasActiveFilters) {
 event.preventDefault();
 resetFilters();
 }
 }
 }

 window.addEventListener("keydown", handleGlobalShortcuts);
 return () => window.removeEventListener("keydown", handleGlobalShortcuts);
 }, [hasActiveFilters, isNoteDirty, resetFilters, saveNote, selectedEvent, view]);

 return (
 <div className="flex h-screen w-screen flex-col overflow-hidden bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-neutral-800 via-neutral-900 to-neutral-950 font-sans text-neutral-300">
  <header className="flex min-h-12 shrink-0 flex-wrap items-center justify-start gap-3 border-b border-neutral-800 bg-neutral-800 pl-2 pr-4 py-1">
    <nav className="flex gap-1">
      {VIEW_ITEMS.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => setView(item.id)}
          className={classNames(
            "rounded-md px-3 py-1.5 text-sm font-medium transition",
            view === item.id
              ? "bg-neutral-800 text-white"
              : "text-neutral-400 hover:bg-neutral-800/50 hover:text-neutral-200",
          )}
        >
          {item.label}
        </button>
      ))}
    </nav>
  </header>

 {error && (
 <div className="border-b border-red-500/20 bg-red-500/10 px-4 py-2 text-sm text-red-300">
 {error}
 </div>
 )}

 {loading && !summary && view === "live" && (
 <main className="flex flex-1 gap-6 overflow-hidden p-6">
 <div className="flex w-[280px] flex-col gap-4">
 <SkeletonMetricCard />
 <SkeletonMetricCard />
 <SkeletonMetricCard />
 </div>
 <div className="flex-1 animate-pulse border border-neutral-800 bg-neutral-800"></div>
 </main>
 )}

 {summary && (
 <main className="flex min-h-0 flex-1 overflow-hidden">
 {view === "live" && (
 <>
 <aside
 className="flex-[2_2_0%] min-w-0 flex shrink-0 flex-col gap-6 overflow-y-auto border-r border-neutral-700 bg-neutral-900 p-5"
 >
 <div className="flex flex-col gap-2">
 <PanelTitle title="미확인 이벤트" />
 <div className="mt-2 text-2xl font-bold tracking-tight text-[#ff7b72]">{summary.events.new}개</div>
 </div>

 <div className="flex flex-col gap-2">
 <PanelTitle title="이벤트 추세" />
 <div className="mt-1 h-32">
 {trendValues.length ? (
 <TinyTrendBars values={trendValues} labels={trendLabels} />
 ) : (
 <div className="flex h-full items-center justify-center text-xs text-neutral-600 py-4">데이터 없음</div>
 )}
 </div>
 </div>

 <div className="flex flex-col gap-2">
 <PanelTitle title="운영 지표" />
 <div className="flex flex-col gap-4 mt-2">
 <ProgressMetric
 label="검토 완료율"
 value={`${Math.round(reviewedRate)}%`}
 progress={reviewedRate}
 />
 <ProgressMetric
 label="미확인 적체율"
 value={`${Math.round(alertLoadRate)}%`}
 progress={alertLoadRate}
 />
 </div>
 </div>

 </aside>

 <section className="flex-[6_6_0%] min-w-0 flex flex-col overflow-y-auto overflow-x-hidden p-3 bg-neutral-900">
 <BrowserLivePanel onInference={handleInference} />


 </section>

 <aside
 className="flex-[2_2_0%] min-w-0 flex shrink-0 flex-col gap-6 overflow-y-auto border-l border-neutral-700 bg-neutral-900 p-5"
 >
        <div className="flex flex-col">
          <PanelTitle title="이벤트 미리보기" />
          {selectedEvent ? (
            <div className="flex flex-col gap-4 mt-2">
              <div className="relative border border-white/5 bg-neutral-900 w-full overflow-hidden rounded bg-neutral-800 aspect-video">
                {((videoMode === "overlay" && selectedEvent.overlay_clip_url) ||
                  selectedEvent.clip_url) ? (
                  <video
                    key={`${selectedEvent.event_id}-${videoMode}`}
                    src={
                      (videoMode === "overlay" && selectedEvent.overlay_clip_url) ||
                      selectedEvent.clip_url ||
                      undefined
                    }
                    controls
                    loop
                    autoPlay={autoplayPreview}
                    muted={autoplayPreview}
                    className="h-full w-full object-contain"
                  />
                ) : selectedEvent.snapshot_url ? (
                  <div className="relative h-full w-full">
                    <Image
                      src={selectedEvent.snapshot_url}
                      alt="이벤트 스냅샷"
                      fill
                      unoptimized
                      sizes="360px"
                      className="object-contain"
                    />
                  </div>
                ) : (
                  <div className="flex aspect-video items-center justify-center text-xs text-neutral-500">
                    미리보기가 없습니다
                  </div>
                )}
              </div>

              <div className="flex flex-col p-3 rounded bg-neutral-800 border border-neutral-800 w-full mb-2">
                <div className="flex justify-between items-center mb-1">
                  <h4 className="text-xs font-semibold text-neutral-300">상황 설명</h4>
                  <button
                    onClick={() => setView("events")}
                    className="text-[10px] text-neutral-400 hover:text-white px-2 py-0.5 bg-neutral-800 rounded transition"
                  >
                    자세히 보기 →
                  </button>
                </div>
                <p className="text-xs text-neutral-400 leading-relaxed min-h-[36px]">
                  {selectedEvent.description || "등록된 설명이 없습니다."}
                </p>
              </div>
            </div>
          ) : (
            <div className="mt-2 text-xs text-neutral-600">이벤트를 선택하세요.</div>
          )}
        </div>

        <div className="flex flex-col">
          <PanelTitle title="최근 이벤트" />
          <div className="flex flex-col gap-1 mt-2">
            {incidentRows.length ? (
              incidentRows.map((event) => {
                const isSelected = selectedEvent?.event_id === event.event_id;
                return (
                  <button
                    key={event.event_id}
                    onClick={() => {
                      setSelectedEventId(event.event_id);
                      setSelectedCameraId(event.camera_id);
                    }}
                    className={classNames(
                      "flex justify-between items-center px-3 py-2.5 my-0.5 rounded-md text-left transition-all hover:bg-white/5 active:scale-[0.98]",
                      isSelected
                        ? "border border-gray-500"
                        : event.status === "new"
                        ? "border border-neutral-800 bg-neutral-800/30 hover:bg-white/5"
                        : "border border-neutral-800 bg-neutral-800/30 opacity-60 saturate-50"
                    )}
                  >
                    <div className="flex flex-col gap-0.5">
                      <span className="flex items-center text-sm font-medium text-neutral-200">
                        {event.status === "new" && (
                           <span className="relative flex h-2 w-2 mr-2">
                             <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
                             <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500"></span>
                           </span>
                        )}
                        {EVENT_LABELS[event.event_type]}
                      </span>
                      <div className="text-[11px] text-neutral-500">
                        {event.camera_name} · {formatCompactDateTime(event.started_at)}
                      </div>
                    </div>
                    <span
                      className={classNames(
                        "rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wide whitespace-nowrap",
                        statusTone(event.status),
                      )}
                    >
                      {STATUS_LABELS[event.status]}
                    </span>
                  </button>
                );
              })
            ) : (
              <div className="text-xs text-neutral-600 mt-2">현재 조건에 맞는 이벤트가 없습니다.</div>
            )}
          </div>
        </div>
 </aside>
 </>
 )}

 {view === "events" && (
 <>
 <aside
 className="flex-[3_3_0%] min-w-0 flex min-h-0 shrink-0 flex-col overflow-hidden border-r border-neutral-800 bg-neutral-800"
 >
 <div className="border-b border-neutral-800 p-4">
 <PanelTitle
 title="이벤트 큐"
 right={
 selectedEventIds.size > 0 && (
 <div className="flex gap-2">
 <button
 onClick={() => void bulkUpdateStatus("confirmed")}
 className="rounded bg-emerald-600/20 px-2 py-1 text-xs text-emerald-300 transition hover:bg-emerald-600/40"
 >
 일괄 정탐
 </button>
 <button
 onClick={() => void bulkUpdateStatus("false_positive")}
 className="rounded bg-red-600/20 px-2 py-1 text-xs text-red-300 transition hover:bg-red-600/40"
 >
 일괄 오탐
 </button>
 </div>
 )
 }
 />
 <div className="flex flex-col gap-2">
 <select
 value={eventTypeFilter}
 onChange={(event) =>
 setEventTypeFilter(event.target.value as "all" | EventType)
 }
 className="w-full rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1.5 text-sm text-neutral-200 outline-none focus:border-neutral-600"
 >
 <option value="all">전체 유형</option>
 <option value="fall_suspected">실신 의심</option>
 <option value="wandering_suspected">배회 의심</option>
 </select>
 <div className="flex gap-2">
 <select
 value={statusFilter}
 onChange={(event) =>
 setStatusFilter(event.target.value as "all" | EventStatus)
 }
 className="flex-1 rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1.5 text-sm text-neutral-200 outline-none focus:border-neutral-600"
 >
 <option value="all">전체 상태</option>
 <option value="new">미확인</option>
 <option value="confirmed">정탐</option>
 <option value="false_positive">오탐</option>
 <option value="dismissed">종료</option>
 </select>
 <select
 value={cameraFilter}
 onChange={(event) => setCameraFilter(event.target.value)}
 className="flex-1 rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1.5 text-sm text-neutral-200 outline-none focus:border-neutral-600"
 >
 <option value="all">전체 카메라</option>
 {eventCameraOptions.map((camera) => (
 <option key={camera.cameraId} value={camera.cameraId}>
 {camera.cameraName}
 </option>
 ))}
 </select>
 </div>
 <div className="text-xs font-mono text-neutral-100">
 검색 결과 {filteredEvents.length}건
 </div>
 <div className="flex flex-wrap gap-2 text-xs">
 <span className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-neutral-400">
 미확인 {filteredNewCount}
 </span>
 <span className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-neutral-400">
 선택 {selectedEventIds.size}
 </span>
 {hasActiveFilters ? (
 <button
 type="button"
 onClick={resetFilters}
 className="rounded border border-neutral-700 px-2 py-1 text-neutral-400 transition hover:bg-neutral-800 hover:text-neutral-200"
 >
 필터 초기화
 </button>
 ) : null}
 </div>
 </div>
 </div>

 <div className="flex-1 overflow-y-auto p-4">
 {filteredEvents.length === 0 ? (
 <EmptyState message="조회된 이벤트가 없습니다." />
 ) : (
 <div className="flex flex-col gap-2">
 {filteredEvents.map((event) => {
 const isSelectedEvent = selectedEvent?.event_id === event.event_id;
 const isMultiSelected = selectedEventIds.has(event.event_id);
 const isUnread = event.status === "new";

 return (
 <div
 key={event.event_id}
 onClick={() => {
 setSelectedEventId(event.event_id);
 setSelectedCameraId(event.camera_id);
 }}
 className={classNames(
 "flex cursor-pointer select-none items-start gap-3 rounded-sm border-l-2 p-3 text-left transition",
 isSelectedEvent
 ? "border-neutral-600 bg-neutral-800"
 : "border-neutral-800 hover:border-neutral-700",
 isUnread ? "bg-neutral-800 hover:bg-neutral-800" : "bg-transparent hover:bg-neutral-800 opacity-70",
 )}
 >
 <div
 className={classNames(
 "mt-0.5 w-1 self-stretch rounded-full",
 priorityStripe(event.priority),
 )}
 />
 <div className="pt-0.5">
 <input
 type="checkbox"
 checked={isMultiSelected}
 onChange={() => toggleEventSelection(event.event_id)}
 onClick={(clickEvent) => clickEvent.stopPropagation()}
 className="h-4 w-4 rounded border-neutral-700 bg-neutral-800 text-neutral-400 focus:ring-white focus:ring-offset-neutral-900"
 />
 </div>
 <div className="flex-1">
 <div className="flex items-center justify-between gap-3">
 <span className="text-sm font-medium text-neutral-100">
 {EVENT_LABELS[event.event_type]}
 </span>
 <span
 className={classNames(
 "rounded border px-2 py-1 text-[10px] font-bold",
 statusTone(event.status),
 )}
 >
 {STATUS_LABELS[event.status]}
 </span>
 </div>
 <div className="mt-1 text-xs text-neutral-400">
 {event.camera_name} · {formatCompactDateTime(event.started_at)}
 </div>
 <div className="mt-2 flex flex-wrap gap-2">
 <span
 className={classNames(
 "rounded border px-2 py-1 text-[10px] font-medium",
 priorityTone(event.priority),
 )}
 >
 {priorityLabel(event.priority)}
 </span>
 <span className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-[10px] text-neutral-400">
 Track {event.track_id}
 </span>
 <span className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-[10px] text-neutral-400">
 {formatConfidence(event.confidence)}
 </span>
 </div>
 </div>
 </div>
 );
 })}
 </div>
 )}
 </div>
 </aside>

 <section className="flex-[4_4_0%] min-w-0 flex flex-col gap-4 overflow-y-auto p-4">
 <PanelTitle
 title="영상 재생"
 right={
 <div className="flex rounded-md border border-neutral-700 bg-neutral-800 p-0.5">
 <button
 onClick={() => setVideoMode("overlay")}
 className={classNames(
 "rounded px-3 py-1 text-xs font-medium",
 videoMode === "overlay"
 ? "bg-neutral-700 text-white"
 : "text-neutral-400 hover:text-white",
 )}
 >
 오버레이
 </button>
 <button
 onClick={() => setVideoMode("clip")}
 className={classNames(
 "rounded px-3 py-1 text-xs font-medium",
 videoMode === "clip"
 ? "bg-neutral-700 text-white"
 : "text-neutral-400 hover:text-white",
 )}
 >
 원본
 </button>
 </div>
 }
 />

 {selectedEvent ? (
 <div className="flex flex-col gap-4">
 <div className="relative flex aspect-video w-full items-center justify-center overflow-hidden border-neutral-800 bg-neutral-800 bg-neutral-900">
 {((videoMode === "overlay" && selectedEvent.overlay_clip_url) ||
 selectedEvent.clip_url) ? (
 <video
 key={`${selectedEvent.event_id}-${videoMode}`}
 src={
 (videoMode === "overlay" && selectedEvent.overlay_clip_url) ||
 selectedEvent.clip_url ||
 undefined
	 }
	 controls
	 loop
	 autoPlay={autoplayPreview}
	 muted={autoplayPreview}
	 className="h-full w-full object-contain"
 />
 ) : selectedEvent.snapshot_url ? (
 <div className="relative h-full w-full">
 <Image
 src={selectedEvent.snapshot_url}
 alt="이벤트 스냅샷"
 fill
 unoptimized
 sizes="960px"
 className="object-contain"
 />
 </div>
 ) : (
 <EmptyState message="재생 가능한 미디어가 없습니다." />
 )}
 </div>

 <div className="grid grid-cols-2 gap-3 2xl:grid-cols-3">
 <MetricCard label="카메라" value={selectedEvent.camera_name} />
 <MetricCard
 label="장소"
 value={selectedEvent.camera_location || "-"}
 />
 <MetricCard
 label="발생 시간"
 value={formatCompactDateTime(selectedEvent.started_at)}
 />
 <MetricCard
 label="영상 시점"
 value={formatSourceTimestamp(selectedEvent.source_timestamp_ms)}
 />
 <MetricCard label="트랙 ID" value={String(selectedEvent.track_id)} />
 <MetricCard
 label="신뢰도"
 value={formatConfidence(selectedEvent.confidence)}
 />
 </div>

 <div className="flex flex-wrap gap-2 text-xs">
 <span
 className={classNames(
 "rounded border px-2 py-1 font-medium",
 eventTone(selectedEvent.event_type),
 )}
 >
 {eventTypeLabel(selectedEvent.event_type)}
 </span>
 <span
 className={classNames(
 "rounded border px-2 py-1 font-medium",
 statusTone(selectedEvent.status),
 )}
 >
 {STATUS_LABELS[selectedEvent.status]}
 </span>
 <span
 className={classNames(
 "rounded border px-2 py-1 font-medium",
 priorityTone(selectedEvent.priority),
 )}
 >
 {priorityLabel(selectedEvent.priority)}
 </span>
 <span className="rounded border border-neutral-800 border-neutral-800 bg-neutral-800 px-2 py-1 text-neutral-400">
 J/K 이동
 </span>
 <span className="rounded border border-neutral-800 border-neutral-800 bg-neutral-800 px-2 py-1 text-neutral-400">
 1/2 모드 전환
 </span>
 </div>

 <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
 <div className="rounded-md bg-neutral-800 p-4">
 <PanelTitle title="이벤트 메타데이터" />
 <div className="grid grid-cols-2 gap-3 text-sm">
 <div className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2">
 <div className="text-neutral-500">이벤트 ID</div>
 <div className="mt-1 break-all text-neutral-200">
 {selectedEvent.event_id}
 </div>
 </div>
 <div className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2">
 <div className="text-neutral-500">ROI</div>
 <div className="mt-1 text-neutral-200">
 {selectedEvent.roi_id || "미지정"}
 </div>
 </div>
 <div className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2">
 <div className="text-neutral-500">검토 시각</div>
 <div className="mt-1 text-neutral-200">
 {selectedEvent.reviewed_at
 ? formatDateTime(selectedEvent.reviewed_at)
 : "미검토"}
 </div>
 </div>
 <div className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2">
 <div className="text-neutral-500">현재 상태</div>
 <div className="mt-1 text-neutral-200">
 {STATUS_LABELS[selectedEvent.status]}
 </div>
 </div>
 </div>
 </div>

 <div className="rounded-md bg-neutral-800 p-4">
 <PanelTitle title="설명" />
 <p className="text-sm leading-6 text-neutral-400">
 {selectedEvent.description || "등록된 설명이 없습니다."}
 </p>
 </div>
 </div>
 </div>
 ) : (
 <EmptyState message="이벤트를 선택하세요." />
 )}
 </section>

 <aside
 className="flex-[3_3_0%] min-w-0 relative flex shrink-0 flex-col gap-4 overflow-y-auto border-l border-neutral-800 bg-neutral-800 p-4"
 >
 <PanelTitle title="운영자 판정" />
 {selectedEvent ? (
 <div className="flex min-h-0 flex-1 flex-col gap-4">




 <div className="rounded-md bg-neutral-800 p-4">
 <div className="flex items-center justify-between gap-3">
 <div className="text-sm font-medium text-neutral-200">운영자 메모</div>
 <div className="flex items-center gap-2 text-[11px]">
 <span
 className={classNames(
 "rounded border px-2 py-1 font-medium",
 isNoteDirty
 ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
 : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
 )}
 >
 {isNoteDirty ? "저장 필요" : "저장됨"}
 </span>
 <span className="text-neutral-500">Cmd/Ctrl+S</span>
 </div>
 </div>
 <textarea
 ref={noteFieldRef}
 id="operator-note"
 value={noteValue}
 onChange={(event) =>
 setNoteDrafts((current) => ({
 ...current,
 [selectedEvent.event_id]: event.target.value,
 }))
 }
 placeholder="판정 근거, 현장 조치, 후속 코멘트를 기록합니다."
 className="mt-3 min-h-40 w-full resize-y rounded-md border border-neutral-800 bg-neutral-900 px-3 py-3 text-sm text-neutral-200 outline-none placeholder:text-neutral-600 focus:border-neutral-600"
 />
 <button
 type="button"
 onClick={() => void saveNote(selectedEvent.event_id)}
 disabled={!isNoteDirty}
 className={classNames(
 "mt-3 w-full rounded-md py-2.5 text-sm font-medium transition",
 isNoteDirty
 ? "border border-neutral-700 bg-neutral-800 text-neutral-200 hover:bg-neutral-700"
 : "cursor-not-allowed border border-neutral-800 bg-neutral-800/40 text-neutral-500",
 )}
 >
 {isNoteDirty ? "메모 저장" : "저장됨"}
 </button>
 </div>

 <div className="sticky bottom-0 -mx-4 -mb-4 mt-auto grid grid-cols-1 gap-2 border-t border-neutral-800 border-neutral-800 bg-neutral-800 /90 p-4 backdrop-blur-sm">
 <div className="flex gap-2">
 <button
 onClick={() => void reviewEvent(selectedEvent.event_id, "confirmed")}
 className="flex-1 rounded-md bg-emerald-600 py-3 text-sm font-medium text-white transition hover:bg-emerald-700 active:scale-[0.98]"
 >
 정탐 처리 (C)
 </button>
 <button
 onClick={() =>
 void reviewEvent(selectedEvent.event_id, "false_positive")
 }
 className="flex-1 rounded-md bg-red-600 py-3 text-sm font-medium text-white transition hover:bg-red-700 active:scale-[0.98]"
 >
 오탐 처리 (F)
 </button>
 </div>
 <button
 onClick={() => void reviewEvent(selectedEvent.event_id, "dismissed")}
 className="rounded-md border border-neutral-700 bg-neutral-800 py-2.5 text-sm font-medium text-neutral-300 transition hover:bg-neutral-700 active:scale-[0.98]"
 >
 종료 (D)
 </button>
 <button
 onClick={() => void reviewEvent(selectedEvent.event_id, "new")}
 className="rounded-md border border-neutral-700 bg-neutral-800 py-2.5 text-sm font-medium text-neutral-300 transition hover:bg-neutral-700 active:scale-[0.98]"
 >
 미확인 복귀 (N)
 </button>
 </div>
 </div>
 ) : (
 <div className="mt-10 text-center text-sm text-neutral-500">
 선택된 이벤트가 없습니다.
 </div>
 )}
 </aside>
 </>
 )}

 

 {view === "analytics" && (
 <section className="flex flex-1 flex-col gap-6 overflow-y-auto p-6">
 <PanelTitle title="통계 요약" />
 <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
 <MetricCard label="총 발생" value={analytics?.overview.total_events ?? 0} />
 <MetricCard label="미확인" value={analytics?.overview.unreviewed_events ?? 0} />
 <MetricCard label="검토 완료" value={analytics?.overview.reviewed_events ?? 0} />
 <MetricCard
 label="평균 신뢰도"
 value={formatConfidence(analytics?.overview.average_confidence ?? 0)}
 />
 </div>

 <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
 <MetricCard label="최근 5분" value={summary.recent.last_5m} />
 <MetricCard label="최근 1시간" value={summary.recent.last_1h} />
 <MetricCard label="최다 발생 카메라" value={topCamera?.camera_name ?? "없음"} />
 <MetricCard label="현재 시스템 상태" value={systemStateLabel(summary.system_state)} />
 </div>

 <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.3fr_1fr]">
 <article className=" border border-neutral-800 border-neutral-800 bg-neutral-800 p-5">
 <PanelTitle title="시간대별 이벤트 추이" />
 <div className="h-[220px] rounded-md border border-neutral-800 bg-neutral-900 p-4">
 {trendValues.length ? (
 <TinyTrendBars values={trendValues} labels={trendLabels} />
 ) : (
 <div className="flex h-full items-center justify-center text-sm text-neutral-500">
 데이터 없음
 </div>
 )}
 </div>
 </article>

 <article className=" border border-neutral-800 border-neutral-800 bg-neutral-800 p-5">
 <PanelTitle title="최근 이벤트" />
 <div className="flex flex-col gap-2">
 {(analytics?.recent_events ?? []).length ? (
 analytics?.recent_events.map((event) => (
 <button
 key={event.event_id}
 onClick={() => {
 setSelectedEventId(event.event_id);
 setSelectedCameraId(event.camera_id);
 setView("events");
 }}
 className="rounded-md border border-neutral-800 bg-neutral-900 p-3 text-left transition hover:bg-neutral-800/80"
 >
 <div className="flex items-center justify-between gap-3">
 <span className="text-sm font-medium text-neutral-100">
 {EVENT_LABELS[event.event_type]}
 </span>
 <span
 className={classNames(
 "rounded border px-2 py-1 text-xs font-medium",
 statusTone(event.status),
 )}
 >
 {STATUS_LABELS[event.status]}
 </span>
 </div>
 <div className="mt-1 text-xs text-neutral-400">
 {event.camera_name} · {formatCompactDateTime(event.started_at)}
 </div>
 </button>
 ))
 ) : (
 <div className="text-sm text-neutral-500">최근 이벤트가 없습니다.</div>
 )}
 </div>
 </article>
 </div>

 <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
 <article className=" border border-neutral-800 border-neutral-800 bg-neutral-800 p-5">
 <PanelTitle title="유형별 분포" />
 <BarList rows={byTypeRows} />
 </article>
 <article className=" border border-neutral-800 border-neutral-800 bg-neutral-800 p-5">
 <PanelTitle title="상태별 분포" />
 <BarList rows={byStatusRows} />
 </article>
 <article className=" border border-neutral-800 border-neutral-800 bg-neutral-800 p-5">
 <PanelTitle title="카메라별 분포" />
 <BarList rows={byCameraRows} />
 </article>
 </div>
 </section>
 )}

 {view === "settings" && (
 <section className="flex-1 overflow-y-auto p-6">
 <PanelTitle title="설정" />
 <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
 <article className=" border border-neutral-800 border-neutral-800 bg-neutral-800 p-5">
 <PanelTitle title="운영 플로우" />
 <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
 <label className="flex flex-col gap-2 text-sm text-neutral-400">
 <span>이벤트 자동 넘김</span>
 <select
 value={String(autoNext)}
 onChange={(event) => setAutoNext(event.target.value === "true")}
 className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-neutral-200 outline-none"
 >
 <option value="true">판정 후 다음 자동 이동</option>
 <option value="false">현재 항목 유지</option>
 </select>
 </label>
 <label className="flex flex-col gap-2 text-sm text-neutral-400">
 <span>이벤트 프리뷰</span>
 <select
 value={String(autoplayPreview)}
 onChange={(event) =>
 setAutoplayPreview(event.target.value === "true")
 }
 className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-neutral-200 outline-none"
 >
 <option value="true">영상 자동 재생</option>
 <option value="false">수동 재생</option>
 </select>
 </label>
 <label className="flex flex-col gap-2 text-sm text-neutral-400">
 <span>기본 영상 모드</span>
 <select
 value={videoMode}
 onChange={(event) =>
 setVideoMode(event.target.value as "overlay" | "clip")
 }
 className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-neutral-200 outline-none"
 >
 <option value="overlay">오버레이 우선</option>
 <option value="clip">원본 우선</option>
 </select>
 </label>
 <label className="flex flex-col gap-2 text-sm text-neutral-400">
 <span>폴링 간격</span>
 <select
 value={String(autoRefreshSeconds)}
 onChange={(event) =>
 setAutoRefreshSeconds(Number(event.target.value))
 }
 className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-neutral-200 outline-none"
 >
 <option value="10">10초</option>
 <option value="20">20초</option>
 <option value="30">30초</option>
 <option value="60">60초</option>
 </select>
 </label>
 </div>
 </article>

 <article className=" border border-neutral-800 border-neutral-800 bg-neutral-800 p-5">
 <PanelTitle title="실시간 연결" />
 <div className="grid grid-cols-1 gap-3 text-sm">
 <div className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2">
 <div className="text-neutral-500">현재 연결 상태</div>
 <div className="mt-1 font-medium text-neutral-200">
 {connectionLabel(connectionMode)}
 </div>
 </div>
 <div className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2">
 <div className="text-neutral-500">마지막 갱신</div>
 <div className="mt-1 font-medium text-neutral-200">
 {formatDateTime(lastUpdatedAt)}
 </div>
 </div>
 <div className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2">
 <div className="text-neutral-500">카메라 상태 출처</div>
 <div className="mt-1 font-medium text-neutral-200">
 {summary.cameras.status_source}
 </div>
 </div>
 </div>
 </article>

 <article className=" border border-neutral-800 border-neutral-800 bg-neutral-800 p-5">
 <PanelTitle title="현재 아키텍처" />
 <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
 <div className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2">
 <div className="text-neutral-500">추론 파이프라인</div>
 <div className="mt-1 font-medium text-neutral-200">
 YOLO Track → MediaPipe Pose → Rule Engine
 </div>
 </div>
 <div className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2">
 <div className="text-neutral-500">이벤트 전달</div>
 <div className="mt-1 font-medium text-neutral-200">REST + SSE</div>
 </div>
 <div className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2">
 <div className="text-neutral-500">라이브 전략</div>
 <div className="mt-1 font-medium text-neutral-200">
 브라우저 라이브 + 저장소 검토
 </div>
 </div>
 <div className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2">
 <div className="text-neutral-500">운영 단말</div>
 <div className="mt-1 font-medium text-neutral-200">Desktop Only</div>
 </div>
 </div>
 </article>

 <article className=" border border-neutral-800 border-neutral-800 bg-neutral-800 p-5">
 <PanelTitle title="단축키" />
 <div className="grid grid-cols-1 gap-3 text-sm">
 {[
 ["J / K", "다음 이벤트 / 이전 이벤트"],
 ["1 / 2", "원본 보기 / 오버레이 보기"],
 ["C", "정탐 처리"],
 ["F", "오탐 처리"],
 ["D", "종료 처리"],
 ["N", "미확인 복귀"],
 ["M", "메모 입력 포커스"],
 ].map(([key, label]) => (
 <div
 key={key}
 className="flex items-center justify-between rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2"
 >
 <span className="text-neutral-400">{label}</span>
 <kbd className="rounded border border-neutral-700 border-neutral-800 bg-neutral-800 px-2 py-1 text-xs text-neutral-200">
 {key}
 </kbd>
 </div>
 ))}
 </div>
 </article>
 </div>
 </section>
 )}
 </main>
 )}

 <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2">
 {toasts.map((toast) => (
 <div
 key={toast.id}
 className="flex items-center gap-2 rounded border border-neutral-700 bg-neutral-800 px-4 py-3 text-sm font-medium text-neutral-200 shadow-xl backdrop-blur-md transition-all"
 >
 <svg className="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
 <path
 strokeLinecap="round"
 strokeLinejoin="round"
 strokeWidth={2}
 d="M5 13l4 4L19 7"
 />
 </svg>
 {toast.message}
 </div>
 ))}
 </div>
 </div>
 );
}
