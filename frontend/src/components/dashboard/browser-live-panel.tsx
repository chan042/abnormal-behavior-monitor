"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { postBrowserLiveFrame } from "@/lib/api";
import type { BrowserLiveResult, EventType } from "@/types/dashboard";

const POSE_CONNECTIONS: Array<[number, number]> = [
 [0, 1], [1, 2], [2, 3], [3, 7],
 [0, 4], [4, 5], [5, 6], [6, 8],
 [9, 10],
 [11, 12],
 [11, 13], [13, 15],
 [12, 14], [14, 16],
 [11, 23], [12, 24], [23, 24],
 [23, 25], [25, 27], [27, 29], [29, 31],
 [24, 26], [26, 28], [28, 30], [30, 32],
];

const ALERT_STICKY_MS = 8000;

const EVENT_LABELS: Record<EventType, string> = {
 fall_suspected: "실신 의심",
 wandering_suspected: "배회 의심",
};

type MonitorMode = "idle" | "stable" | "warning" | "critical" | "error";

interface BrowserCameraDevice {
 deviceId: string;
 label: string;
}

interface BrowserLivePanelProps {
 onInference?: (result: BrowserLiveResult) => void;
}

interface LiveAlertSnapshot {
 eventType: EventType;
 confidence: number;
 trackId: number;
 detectedAt: number;
 sourceTimestampMs: number | null;
}

function classNames(...values: Array<string | false | null | undefined>) {
 return values.filter(Boolean).join(" ");
}

function eventPriority(value: EventType) {
 return value === "fall_suspected" ? 2 : 1;
}

function pickPrimaryEvent(events: BrowserLiveResult["events"]) {
 const [primary] = [...events].sort((left, right) => {
 const priorityGap = eventPriority(right.event_type) - eventPriority(left.event_type);
 if (priorityGap !== 0) {
 return priorityGap;
 }
 return right.confidence - left.confidence;
 });
 return primary ?? null;
}

function formatClock(value?: string | number | null) {
 if (value == null) return "대기 중";
 const date = typeof value === "number" ? new Date(value) : new Date(value);
 if (Number.isNaN(date.getTime())) {
 return typeof value === "string" ? value : "대기 중";
 }
 return new Intl.DateTimeFormat("ko-KR", {
 hour: "2-digit",
 minute: "2-digit",
 second: "2-digit",
 hour12: false,
 }).format(date);
}

function formatConfidence(value?: number | null) {
 if (value == null) return "-";
 return `${Math.round(value * 100)}%`;
}

function monitorTone(mode: MonitorMode) {
  if (mode === "critical") {
    return {
      frame: "border-[#ff7b72]/40 shadow-[0_0_40px_rgba(255,123,114,0.14)]",
      panel: "border-[#ff7b72]/30 bg-[#251012]/90 shadow-[0_4px_24px_rgba(255,123,114,0.08)]",
      badge: "border-[#ff7b72]/40 bg-[#ff7b72]/15 text-[#ffb8b1]",
      dot: "bg-[#ff7b72]",
      summary: "border-[#ff7b72]/20 bg-[#1b0b0d]/90",
      value: "text-[#ffd0cb]",
      accent: "text-[#ff7b72]",
    };
  }

  if (mode === "warning") {
    return {
      frame: "border-[#d29922]/35 shadow-[0_0_40px_rgba(210,153,34,0.12)]",
      panel: "border-[#d29922]/30 bg-[#281b0a]/90 shadow-[0_4px_24px_rgba(210,153,34,0.08)]",
      badge: "border-[#d29922]/35 bg-[#d29922]/15 text-[#f5d28a]",
      dot: "bg-[#d29922]",
      summary: "border-[#d29922]/20 bg-[#1a1207]/90",
      value: "text-[#f8dd9d]",
      accent: "text-[#d29922]",
    };
  }

  if (mode === "error") {
    return {
      frame: "border-[#ff7b72]/28 shadow-[0_0_32px_rgba(255,123,114,0.08)]",
      panel: "border-[#ff7b72]/20 bg-[#1d1011]/90",
      badge: "border-[#ff7b72]/28 bg-[#ff7b72]/12 text-[#ffb8b1]",
      dot: "bg-[#ff7b72]",
      summary: "border-[#ff7b72]/15 bg-[#170c0d]/90",
      value: "text-[#ffd0cb]",
      accent: "text-[#ff7b72]",
    };
  }

  if (mode === "stable") {
    return {
      frame: "border-blue-500/20 shadow-[0_0_32px_rgba(59,130,246,0.08)]",
      panel: "border-blue-500/15 bg-[#0b121c]/90 shadow-[0_4px_20px_rgba(59,130,246,0.05)]",
      badge: "border-blue-500/20 bg-blue-500/10 text-blue-300",
      dot: "bg-blue-500",
      summary: "border-blue-500/10 bg-[#080d14]/90",
      value: "text-blue-100",
      accent: "text-blue-400",
    };
  }

  return {
    frame: "border-white/10 shadow-[0_0_30px_rgba(255,255,255,0.04)]",
    panel: "border-white/10 bg-[#111317]/90",
    badge: "border-white/14 bg-white/5 text-neutral-300",
    dot: "bg-neutral-500",
    summary: "border-white/10 bg-[#0d0f11]/90",
    value: "text-neutral-100",
    accent: "text-neutral-300",
  };
}

function monitorLabel(mode: MonitorMode) {
 if (mode === "critical") return EVENT_LABELS.fall_suspected;
 if (mode === "warning") return EVENT_LABELS.wandering_suspected;
 if (mode === "error") return "분석 오류";
 if (mode === "idle") return "대기";
 return "정상";
}

function monitorHeadline(mode: MonitorMode) {
 if (mode === "critical") return "실신 의심 상태 감지";
 if (mode === "warning") return "배회 의심 상태 감지";
 if (mode === "error") return "분석 파이프라인 확인 필요";
 if (mode === "idle") return "실시간 분석 대기";
 return "정상 감시 중";
}

function monitorMessage(mode: MonitorMode, lastError?: string | null) {
 if (mode === "critical") {
 return "넘어짐 또는 쓰러짐 징후가 감지되었습니다. 운영자가 즉시 현장과 이벤트 큐를 확인해야 합니다.";
 }
 if (mode === "warning") {
 return "반복 이동 또는 장시간 체류 패턴이 포착되었습니다. 배회 상황인지 빠르게 검토하는 편이 좋습니다.";
 }
 if (mode === "error") {
 return lastError ?? "최근 프레임 분석 중 오류가 발생했습니다. 입력 장치와 백엔드 응답 상태를 확인하세요.";
 }
 if (mode === "idle") {
 return "브라우저 카메라를 연결하면 객체 추적, 포즈 추정, 이상행동 감지를 바로 시작합니다.";
 }
 return "현재 프레임에서 특이 행동이 감지되지 않았습니다. 추적 대상과 포즈를 계속 분석하고 있습니다.";
}

function trackColor(trackId: number) {
 // Classic YOLO default colors
 const yoloColors = [
 "#FF3838", "#FF9D97", "#FF701F", "#FFB21D", "#CFD231", "#48F90A", 
 "#92CC17", "#3DDB86", "#1A9334", "#00D4BB", "#2C99A8", "#00C2FF", 
 "#344593", "#6473FF", "#0018EC", "#8438FF", "#520085", "#CB38FF", 
 "#FF95C8", "#FF37C7"
 ];
 return yoloColors[Math.abs(trackId) % yoloColors.length];
}

export function BrowserLivePanel({ onInference }: BrowserLivePanelProps) {
 const videoRef = useRef<HTMLVideoElement | null>(null);
 const overlayRef = useRef<HTMLCanvasElement | null>(null);
 const captureCanvasRef = useRef<HTMLCanvasElement | null>(null);
 const captureTimerRef = useRef<number | null>(null);
 const streamRef = useRef<MediaStream | null>(null);
 const inFlightRef = useRef(false);
 const streamingRef = useRef(false);
 const selectedDeviceLabelRef = useRef("");

 const [devices, setDevices] = useState<BrowserCameraDevice[]>([]);
 const [selectedDeviceId, setSelectedDeviceId] = useState("");
 const [selectedDeviceLabel, setSelectedDeviceLabel] = useState("");
 const [streaming, setStreaming] = useState(false);
 const [status, setStatus] = useState<"idle" | "streaming" | "error">("idle");
 const [lastError, setLastError] = useState<string | null>(null);
 const [lastResult, setLastResult] = useState<BrowserLiveResult | null>(null);
 const [stickyAlert, setStickyAlert] = useState<LiveAlertSnapshot | null>(null);

 const sessionId = "browser_desktop_main";
 const targetFps = 4;

 useEffect(() => {
 selectedDeviceLabelRef.current = selectedDeviceLabel;
 }, [selectedDeviceLabel]);

 const ensureDevices = useCallback(async () => {
 if (!navigator.mediaDevices?.enumerateDevices) {
 setLastError("브라우저가 카메라 장치 조회를 지원하지 않습니다.");
 return;
 }
 const items = await navigator.mediaDevices.enumerateDevices();
 const nextDevices = items
 .filter((device) => device.kind === "videoinput")
 .map((device, index) => ({
 deviceId: device.deviceId,
 label: device.label || `비디오 장치 ${index + 1}`,
 }));
 setDevices(nextDevices);
 if (!selectedDeviceId && nextDevices.length > 0) {
 setSelectedDeviceId(nextDevices[0].deviceId);
 setSelectedDeviceLabel(nextDevices[0].label);
 }
 }, [selectedDeviceId]);

 const stopCamera = useCallback(() => {
 if (captureTimerRef.current) {
 window.clearInterval(captureTimerRef.current);
 captureTimerRef.current = null;
 }
 if (streamRef.current) {
 streamRef.current.getTracks().forEach((track) => track.stop());
 streamRef.current = null;
 }
 if (videoRef.current) {
 videoRef.current.srcObject = null;
 }
 streamingRef.current = false;
 inFlightRef.current = false;
 setStreaming(false);
 setStatus("idle");
 setStickyAlert(null);
 }, []);

 async function startCamera() {
 if (!navigator.mediaDevices?.getUserMedia) {
 setLastError("브라우저가 getUserMedia를 지원하지 않습니다.");
 setStatus("error");
 return;
 }

 try {
 const stream = await navigator.mediaDevices.getUserMedia({
 video: selectedDeviceId
 ? {
 deviceId: { exact: selectedDeviceId },
 width: { ideal: 1280 },
 height: { ideal: 720 },
 }
 : {
 width: { ideal: 1280 },
 height: { ideal: 720 },
 },
 audio: false,
 });
 stopCamera();
 streamRef.current = stream;
 streamingRef.current = true;
 setStreaming(true);
 setStatus("streaming");
 setLastError(null);
 await ensureDevices();

 const track = stream.getVideoTracks()[0];
 if (track?.label) {
 setSelectedDeviceLabel(track.label);
 }
 const settings = track?.getSettings?.();
 if (settings?.deviceId) {
 setSelectedDeviceId(settings.deviceId);
 }
 syncVideoElement();
 startCaptureLoop();
 } catch (error) {
 setLastError(error instanceof Error ? error.message : String(error));
 setStatus("error");
 }
 }

 const resizeOverlayCanvas = useCallback(() => {
 const video = videoRef.current;
 const overlay = overlayRef.current;
 if (!video || !overlay) {
 return;
 }
 const rect = video.getBoundingClientRect();
 const width = Math.max(Math.floor(rect.width), 2);
 const height = Math.max(Math.floor(rect.height), 2);
 if (overlay.width !== width || overlay.height !== height) {
 overlay.width = width;
 overlay.height = height;
 }
 }, []);

 const syncVideoElement = useCallback(() => {
 if (!videoRef.current || !streamRef.current) {
 return;
 }
 if (videoRef.current.srcObject !== streamRef.current) {
 videoRef.current.srcObject = streamRef.current;
 videoRef.current.onloadedmetadata = () => {
 void videoRef.current?.play().catch(() => undefined);
 resizeOverlayCanvas();
 };
 }
 }, [resizeOverlayCanvas]);

 function startCaptureLoop() {
 if (captureTimerRef.current) {
 window.clearInterval(captureTimerRef.current);
 }
 captureTimerRef.current = window.setInterval(() => {
 void captureFrame();
 }, Math.max(1000 / targetFps, 180));
 }

 async function captureFrame() {
 const video = videoRef.current;
 if (!video || !streamingRef.current || inFlightRef.current) {
 return;
 }
 if (video.readyState < 2 || !video.videoWidth || !video.videoHeight) {
 return;
 }

 if (!captureCanvasRef.current) {
 captureCanvasRef.current = document.createElement("canvas");
 captureCanvasRef.current.width = 960;
 captureCanvasRef.current.height = 540;
 }
 const canvas = captureCanvasRef.current;
 const context = canvas.getContext("2d");
 if (!context) {
 return;
 }

 context.drawImage(video, 0, 0, canvas.width, canvas.height);
 inFlightRef.current = true;
 const blob = await new Promise<Blob | null>((resolve) => {
 canvas.toBlob((value) => resolve(value), "image/jpeg", 0.78);
 });

 if (!blob) {
 inFlightRef.current = false;
 return;
 }

 try {
 const result = await postBrowserLiveFrame(
 sessionId,
 blob,
 Date.now(),
 selectedDeviceLabelRef.current || "browser camera",
 );
 setLastResult(result);
 setStatus("streaming");
 setLastError(result.last_error || null);
 onInference?.(result);
 } catch (error) {
 setLastError(error instanceof Error ? error.message : String(error));
 setStatus("error");
 } finally {
 inFlightRef.current = false;
 }
 }

 const drawOverlay = useCallback(() => {
 const overlay = overlayRef.current;
 if (!overlay) {
 return;
 }
 const context = overlay.getContext("2d");
 if (!context) {
 return;
 }

 resizeOverlayCanvas();
 context.clearRect(0, 0, overlay.width, overlay.height);
 if (!lastResult) {
 return;
 }

 const video = videoRef.current;
 const imageWidth = lastResult.image_width || video?.videoWidth || overlay.width;
 const imageHeight = lastResult.image_height || video?.videoHeight || overlay.height;

 const vRatio = imageWidth / Math.max(imageHeight, 1);
 const cRatio = overlay.width / Math.max(overlay.height, 1);

 let renderWidth = overlay.width;
 let renderHeight = overlay.height;
 let offsetX = 0;
 let offsetY = 0;

 if (vRatio > cRatio) {
 // Letterboxed
 renderHeight = overlay.width / vRatio;
 offsetY = (overlay.height - renderHeight) / 2;
 } else {
 // Pillarboxed
 renderWidth = overlay.height * vRatio;
 offsetX = (overlay.width - renderWidth) / 2;
 }

 const scaleX = renderWidth / Math.max(imageWidth, 1);
 const scaleY = renderHeight / Math.max(imageHeight, 1);

 context.save();
 context.beginPath();
 context.rect(offsetX, offsetY, renderWidth, renderHeight);
 context.clip();

 context.lineJoin = "miter";
 context.lineCap = "butt";
 context.font = '500 12px sans-serif'; // standard classic small font

 for (const track of lastResult.tracks) {
 const color = trackColor(track.track_id);
 const [x1, y1, x2, y2] = track.bbox;
 const left = offsetX + x1 * scaleX;
 const top = offsetY + y1 * scaleY;
 const width = (x2 - x1) * scaleX;
 const height = (y2 - y1) * scaleY;

 context.strokeStyle = color;
 context.lineWidth = 2; // standard YOLO thickness
 context.shadowBlur = 0; // remove shadow
 context.strokeRect(left, top, width, height);

 const label = `ID:${track.track_id} ${(track.confidence).toFixed(2)}`;
 const labelWidth = context.measureText(label).width + 6;
 const labelHeight = 16;
 const labelTop = top - labelHeight >= 0 ? top - labelHeight : top; // draw inside if clipping top
 
 context.fillStyle = color;
 context.fillRect(left, labelTop, labelWidth, labelHeight);
 
 context.fillStyle = "#ffffff";
 context.fillText(label, left + 3, labelTop + 12);
 }

 for (const pose of lastResult.poses) {
 const color = trackColor(pose.track_id);
 const visible = new Map(
 pose.pose_landmarks
 .filter((landmark) => landmark.visibility >= 0.35)
 .map((landmark) => [landmark.index, landmark]),
 );

 for (const [start, end] of POSE_CONNECTIONS) {
 const a = visible.get(start);
 const b = visible.get(end);
 if (!a || !b) {
 continue;
 }
 context.shadowBlur = 0;
 context.strokeStyle = color;
 context.lineWidth = 2;
 context.beginPath();
 context.moveTo(offsetX + a.x * scaleX, offsetY + a.y * scaleY);
 context.lineTo(offsetX + b.x * scaleX, offsetY + b.y * scaleY);
 context.stroke();
 }

 for (const landmark of visible.values()) {
 context.fillStyle = "#ffffff";
 context.beginPath();
 context.arc(offsetX + landmark.x * scaleX, offsetY + landmark.y * scaleY, 2.5, 0, Math.PI * 2);
 context.fill();
 }
 }

 for (const event of lastResult.events) {
 const target = lastResult.tracks.find((track) => track.track_id === event.track_id);
 if (!target) {
 continue;
 }
 // Highly visible solid backgrounds for alerts, mimicking standard rectangle format
 const color = event.event_type === "fall_suspected" ? "#FF0000" : "#FFA500";
 const label = `${event.event_type === "fall_suspected" ? "Fall" : "Wandering"} ${(event.confidence).toFixed(2)}`;
 const width = context.measureText(label).width + 8;
 const height = 20;
 const left = offsetX + target.bbox[0] * scaleX;
 const top = Math.max(offsetY + target.bbox[1] * scaleY - height - 16, offsetY + 8); // stack slightly above

 context.fillStyle = color;
 context.fillRect(left, top, width, height);
 
 context.fillStyle = "#ffffff";
 context.fillText(label, left + 4, top + 14);
 }

 context.restore();
 }, [lastResult, resizeOverlayCanvas]);

 useEffect(() => {
 void ensureDevices();
 return () => stopCamera();
 }, [ensureDevices, stopCamera]);

 useEffect(() => {
 const handleResize = () => resizeOverlayCanvas();
 window.addEventListener("resize", handleResize);
 return () => window.removeEventListener("resize", handleResize);
 }, [resizeOverlayCanvas]);

 useEffect(() => {
 const primaryEvent = pickPrimaryEvent(lastResult?.events ?? []);
 if (!primaryEvent) {
 return;
 }

 setStickyAlert({
 eventType: primaryEvent.event_type,
 confidence: primaryEvent.confidence,
 trackId: primaryEvent.track_id,
 detectedAt: Date.now(),
 sourceTimestampMs: lastResult?.source_timestamp_ms ?? null,
 });
 }, [lastResult]);

 useEffect(() => {
 if (!stickyAlert) {
 return;
 }

 const timer = window.setTimeout(() => {
 setStickyAlert((current) =>
 current && current.detectedAt === stickyAlert.detectedAt ? null : current,
 );
 }, ALERT_STICKY_MS);

 return () => window.clearTimeout(timer);
 }, [stickyAlert]);

 useEffect(() => {
 syncVideoElement();
 drawOverlay();
 }, [drawOverlay, streaming, syncVideoElement]);

 const recentEvents = lastResult?.events ?? [];
 const primaryFrameEvent = pickPrimaryEvent(recentEvents);
 const activeAlert =
 primaryFrameEvent
 ? {
 eventType: primaryFrameEvent.event_type,
 confidence: primaryFrameEvent.confidence,
 trackId: primaryFrameEvent.track_id,
 detectedAt:
 stickyAlert &&
 stickyAlert.eventType === primaryFrameEvent.event_type &&
 stickyAlert.trackId === primaryFrameEvent.track_id
 ? stickyAlert.detectedAt
 : Date.now(),
 sourceTimestampMs: lastResult?.source_timestamp_ms ?? stickyAlert?.sourceTimestampMs ?? null,
 }
 : stickyAlert;
 const monitorMode: MonitorMode =
 status === "error"
 ? "error"
 : !streaming
 ? "idle"
 : activeAlert?.eventType === "fall_suspected"
 ? "critical"
 : activeAlert?.eventType === "wandering_suspected"
 ? "warning"
 : "stable";
 const tone = monitorTone(monitorMode);
 const cameraLabel = selectedDeviceLabel || lastResult?.camera_label || "브라우저 카메라";
 const lastProcessedAt = lastResult?.processing_at ?? lastResult?.source_timestamp_ms ?? null;
 const recentAlertLabel = activeAlert ? EVENT_LABELS[activeAlert.eventType] : "이상 없음";
 const recentAlertDetail = activeAlert
 ? `대상 ID ${activeAlert.trackId} · ${formatConfidence(activeAlert.confidence)}`
 : "정상 감시 유지";
 const standbyTitle = status === "error" ? "ANALYSIS ERROR" : "SYSTEM STANDBY";
 const standbyDetail =
 status === "error" && lastError
 ? lastError
 : "활성 비디오 스트림 대기 중...";

 return (
  <div className="flex h-full flex-col gap-4 overflow-hidden">
    {/* Header & Controls Layer (De-boxed) */}
    <div className="flex items-center justify-end pb-3 border-b border-neutral-800 shrink-0">
      <div className="flex items-center gap-4">
        <div className="relative flex items-center">
          <div className="flex items-center justify-center p-2 group cursor-pointer rounded-full bg-neutral-800 border border-neutral-800 hover:bg-neutral-700 transition-colors" title={selectedDeviceLabel || "카메라 선택"}>
            <svg className="h-5 w-5 text-neutral-400 group-hover:text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            
            <select
              value={selectedDeviceId}
              onChange={(event) => {
                setSelectedDeviceId(event.target.value);
                const item = devices.find((device) => device.deviceId === event.target.value);
                setSelectedDeviceLabel(item?.label ?? "");
              }}
              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer appearance-none"
            >
              <option value="">
                {devices.length ? "카메라를 선택하세요" : "권한 확인 중"}
              </option>
              {devices.map((device) => (
                <option key={device.deviceId} value={device.deviceId}>
                  {device.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex gap-2">
          {!streaming ? (
            <button
              type="button"
              onClick={() => void startCamera()}
              className="flex items-center justify-center gap-2 rounded-full w-[130px] bg-blue-600 py-2 text-sm font-bold text-white hover:bg-blue-500 shadow-md transition-colors"
            >
              <span className="h-2 w-2 rounded-full bg-white/80 animate-pulse"></span>
              스트림 연결
            </button>
          ) : (
            <button
              type="button"
              onClick={stopCamera}
              className="flex items-center justify-center gap-2 rounded-full w-[130px] bg-neutral-800 border border-neutral-700 py-2 text-sm font-medium text-neutral-300 hover:bg-neutral-700 hover:text-white transition-colors"
            >
              중단
            </button>
          )}
        </div>
      </div>
    </div>

    {/* Scrollable Content Container */}
    <div className="flex-1 overflow-y-auto pr-2 flex flex-col gap-5 min-h-0 w-full relative pb-4">
      
      {/* Immersive Video Feed */}
      <div
        className={classNames(
          "relative shrink-0 w-full aspect-video overflow-hidden rounded-2xl border bg-black shadow-2xl transition-[border-color,box-shadow] duration-300",
          tone.frame,
        )}
      >
        <video ref={videoRef} autoPlay muted playsInline className="absolute inset-0 h-full w-full object-contain" />
        <canvas ref={overlayRef} className="pointer-events-none absolute inset-0 h-full w-full" />
        {!streaming && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-6 bg-neutral-900/90 backdrop-blur-md">
            <div className="relative flex h-56 w-56 items-center justify-center">
              <div className="absolute inset-0 rounded-full border border-white/5" />
              <div className="absolute inset-4 rounded-full border border-white/5" />
              <div className="absolute inset-0 rounded-full border-t-2 border-white/80 animate-[radar-scan_3s_linear_infinite]" />
              <div className="absolute inset-0 rounded-full bg-gradient-to-t from-transparent via-transparent to-white/20 animate-[radar-scan_3s_linear_infinite]" />
              <div className="h-4 w-4 rounded-full bg-white/90 shadow-[0_0_20px_rgba(255,255,255,0.7)] animate-[soft-pulse_2.5s_ease-in-out_infinite]" />
            </div>
            <div className="flex flex-col items-center gap-1">
              <span className="text-sm font-semibold tracking-wider text-neutral-300">{standbyTitle}</span>
              <span className="text-[11px] text-neutral-500 tracking-wide uppercase">{standbyDetail}</span>
            </div>
          </div>
        )}
      </div>

      {streaming && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 shrink-0">
          <div className={classNames("rounded-xl border p-4 flex flex-col justify-between transition-colors duration-300", tone.summary)}>
             <span className="text-[10px] font-medium uppercase tracking-widest text-neutral-500 mb-2">상태</span>
             <div className="flex items-center gap-2">
                 <span className={classNames("relative flex h-3 w-3 shrink-0 items-center justify-center")}>
                   <span className={classNames("absolute h-full w-full rounded-full animate-ping opacity-60", tone.dot)} />
                   <span className={classNames("relative h-2 w-2 rounded-full", tone.dot)} />
                 </span>
                 <span className={classNames("text-sm font-semibold", tone.value)}>{monitorLabel(monitorMode)}</span>
             </div>
          </div>

          <div className={classNames("rounded-xl border p-4 flex flex-col justify-between transition-colors duration-300 bg-neutral-900/50 border-white/5")}>
             <span className="text-[10px] font-medium uppercase tracking-widest text-neutral-500 mb-2">스트림</span>
             <div className="flex items-center gap-1.5 min-w-0">
                 <span className="text-sm font-semibold text-neutral-200 truncate" title={cameraLabel}>{cameraLabel}</span>
                 <span className="text-[11px] font-medium text-neutral-500 whitespace-nowrap">· {targetFps.toFixed(1)} FPS</span>
             </div>
          </div>

          <div className={classNames("rounded-xl border p-4 flex flex-col justify-between transition-colors duration-300 bg-neutral-900/50 border-white/5")}>
             <span className="text-[10px] font-medium uppercase tracking-widest text-neutral-500 mb-2">객체 추적</span>
             <div className="flex items-center gap-2">
                 <span className="text-sm font-semibold text-neutral-200">{lastResult?.tracks.length ?? 0}명</span>
                 <span className="text-[11px] font-medium text-neutral-500">· {lastResult?.poses.length ?? 0} 포즈</span>
             </div>
          </div>

          <div className={classNames("rounded-xl border p-4 flex flex-col justify-between transition-colors duration-300 bg-neutral-900/50 border-white/5")}>
             <span className="text-[10px] font-medium uppercase tracking-widest text-neutral-500 mb-2">활성 프레임</span>
             <div className="flex flex-col gap-0.5">
                 <span className="text-sm font-semibold text-neutral-200 truncate">#{lastResult?.frame_index ?? 0}</span>
             </div>
          </div>
        </div>
      )}
    </div>
  </div>
);
}
