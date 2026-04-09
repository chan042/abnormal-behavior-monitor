export type EventStatus = "new" | "confirmed" | "false_positive" | "dismissed";
export type EventType = "fall_suspected" | "wandering_suspected";
export type DashboardView = "live" | "events" | "analytics" | "settings";

export interface SummaryResponse {
  generated_at: string;
  system_state: string;
  events: {
    total: number;
    new: number;
    confirmed: number;
    false_positive: number;
    dismissed: number;
    fall: number;
    wandering: number;
  };
  recent: {
    last_5m: number;
    last_1h: number;
  };
  cameras: {
    online: number;
    total: number;
    status_source: string;
  };
  latest_event: DashboardEvent | null;
}

export interface DashboardEvent {
  event_id: string;
  camera_id: string;
  track_id: number;
  event_type: EventType;
  started_at: string;
  ended_at: string | null;
  source_timestamp_ms: number | null;
  confidence: number;
  roi_id: string | null;
  clip_path: string | null;
  overlay_clip_path: string | null;
  snapshot_path: string | null;
  description: string;
  status: EventStatus;
  operator_note: string;
  reviewed_at: string | null;
  detail_url: string;
  clip_url: string | null;
  overlay_clip_url: string | null;
  snapshot_url: string | null;
  camera_name: string;
  camera_location: string;
  priority: string;
}

export interface EventsResponse {
  items: DashboardEvent[];
  count: number;
}

export interface CameraSummary {
  camera_id: string;
  name: string;
  location: string;
  zone_label: string;
  stream_status: string;
  status_source: string;
  source_type: string;
  live_supported: boolean;
  live_frame_url?: string;
  live_stream_url?: string;
  last_seen_at: string | null;
  total_events: number;
  unreviewed_events: number;
  fall_events: number;
  wandering_events: number;
  latest_event_id: string | null;
  latest_event_type: string | null;
  latest_event_status: string;
  latest_event_started_at: string | null;
  latest_confidence: number | null;
  preview_snapshot_url: string | null;
  preview_clip_url: string | null;
  detail_event_url: string | null;
  input_fps: number | null;
  inference_fps: number | null;
  processing_delay_ms: number | null;
  current_track_count?: number;
  current_pose_track_count?: number;
  last_error?: string | null;
}

export interface CamerasResponse {
  items: CameraSummary[];
  count: number;
}

export interface AnalyticsBucket {
  bucket: string;
  total: number;
  fall_suspected: number;
  wandering_suspected: number;
}

export interface AnalyticsResponse {
  generated_at: string;
  overview: {
    total_events: number;
    unreviewed_events: number;
    reviewed_events: number;
    average_confidence: number;
  };
  by_type: Array<{ event_type: string; count: number }>;
  by_status: Array<{ status: string; count: number }>;
  by_camera: Array<{ camera_id: string; camera_name: string; count: number }>;
  timeline: AnalyticsBucket[];
  recent_events: DashboardEvent[];
}

export interface BrowserLiveSessionSummary {
  session_id: string;
  camera_label?: string;
  frame_index: number;
  total_events?: number;
  track_count?: number;
  pose_count?: number;
  event_count?: number;
  last_error: string | null;
}

export interface BrowserLiveSessionsResponse {
  items: BrowserLiveSessionSummary[];
  count: number;
}

export interface BrowserLiveTrack {
  frame_index: number;
  timestamp_ms: number;
  track_id: number;
  class_id: number;
  class_name: string;
  confidence: number;
  bbox: [number, number, number, number];
}

export interface BrowserLiveLandmark {
  index: number;
  x: number;
  y: number;
  z: number;
  visibility: number;
}

export interface BrowserLivePose {
  track_id: number;
  frame_index: number;
  timestamp_ms: number;
  pose_landmarks: BrowserLiveLandmark[];
}

export interface BrowserLiveResult {
  session_id: string;
  camera_label: string;
  frame_index: number;
  timestamp_ms: number;
  source_timestamp_ms: number;
  image_width: number;
  image_height: number;
  tracks: BrowserLiveTrack[];
  poses: BrowserLivePose[];
  events: DashboardEvent[];
  processing_at: string;
  last_error: string | null;
  total_events?: number;
}
