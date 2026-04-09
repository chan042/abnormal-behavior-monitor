import re

file_path = "frontend/src/components/dashboard/browser-live-panel.tsx"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Replace monitorTone
old_monitor_tone_start = content.find("function monitorTone(mode: MonitorMode) {")
old_monitor_tone_end = content.find("function monitorLabel(mode: MonitorMode) {")

if old_monitor_tone_start == -1 or old_monitor_tone_end == -1:
    print("Could not find monitorTone")
    exit(1)

new_monitor_tone = """function monitorTone(mode: MonitorMode) {
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

"""

content = content[:old_monitor_tone_start] + new_monitor_tone + content[old_monitor_tone_end:]


# 2. Replace the return statement
old_return_start = content.find("return (\\n  <div className=\\\"flex h-full flex-col gap-6\\\">")
if old_return_start == -1:
    old_return_start = content.find("return (\n  <div className=\"flex h-full flex-col gap-6\">")
    if old_return_start == -1:
        # Fallback regex
        match = re.search(r"return \(\s*<div className=\"flex h-full flex-col gap-6\">", content)
        if match:
            old_return_start = match.start()

old_return_end = content.find("  );\n}") + 6

if old_return_start == -1 or old_return_end == -1:
    print("Could not find return statement")
    exit(1)

new_return = """return (
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
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 shrink-0">
          {/* Main Status Panel */}
          <div className={classNames("col-span-1 lg:col-span-2 rounded-2xl border p-5 flex flex-col justify-center transition-colors duration-300 backdrop-blur-md", tone.panel)}>
             <div className="flex items-start gap-4">
               <div className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-black/30 border border-white/5">
                 <span className={classNames("absolute h-4 w-4 rounded-full animate-ping opacity-60", tone.dot)} />
                 <span className={classNames("relative h-3 w-3 rounded-full", tone.dot)} />
               </div>
               <div className="flex-1 min-w-0">
                 <div className="flex flex-wrap items-center gap-2 mb-1.5">
                   <span className="text-[10px] font-bold uppercase tracking-widest text-neutral-500">현재 상태</span>
                   <span className={classNames("rounded-full border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider", tone.badge)}>
                     {monitorLabel(monitorMode)}
                   </span>
                 </div>
                 <h3 className="text-xl font-bold tracking-tight text-white mb-1">{monitorHeadline(monitorMode)}</h3>
                 <p className="text-[13px] leading-relaxed text-neutral-400">
                   {monitorMessage(monitorMode, lastError)}
                 </p>
               </div>
             </div>
          </div>

          {/* Technical Stats Panel */}
          <div className={classNames("col-span-1 rounded-2xl border p-5 transition-colors duration-300 flex flex-col gap-4 backdrop-blur-md", tone.summary)}>
              <div className="flex items-center justify-between border-b border-white/5 pb-3">
                 <span className="text-[10px] font-bold uppercase tracking-widest text-neutral-500">분석 스트림 정보</span>
                 <span className={classNames("text-[10px] font-semibold tracking-wide", tone.accent)}>프레임 #{lastResult?.frame_index ?? 0}</span>
              </div>
              <div className="grid grid-cols-2 gap-4">
                 <div>
                   <div className="text-[9px] font-bold uppercase tracking-[0.15em] text-neutral-500 mb-1">카메라</div>
                   <div className={classNames("text-[13px] font-semibold truncate", tone.value)} title={cameraLabel}>{cameraLabel}</div>
                 </div>
                 <div>
                   <div className="text-[9px] font-bold uppercase tracking-[0.15em] text-neutral-500 mb-1">샘플링</div>
                   <div className={classNames("text-[13px] font-semibold", tone.value)}>{targetFps.toFixed(1)} FPS</div>
                 </div>
                 <div>
                   <div className="text-[9px] font-bold uppercase tracking-[0.15em] text-neutral-500 mb-1">추적 대상</div>
                   <div className={classNames("text-[13px] font-semibold", tone.value)}>{lastResult?.tracks.length ?? 0}명</div>
                 </div>
                 <div>
                   <div className="text-[9px] font-bold uppercase tracking-[0.15em] text-neutral-500 mb-1">포즈 랜드마크</div>
                   <div className={classNames("text-[13px] font-semibold", tone.value)}>{lastResult?.poses.length ?? 0}개</div>
                 </div>
              </div>
          </div>

          {/* Alert Strip Panel */}
          <div className={classNames("col-span-1 lg:col-span-3 rounded-2xl border p-5 transition-colors duration-300 flex flex-wrap items-center justify-between gap-5 backdrop-blur-md", tone.summary)}>
             <div className="flex items-center gap-4">
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-black/30 border border-white/5">
                   <svg className={classNames("h-5 w-5", tone.accent)} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                     <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                   </svg>
                </div>
                <div>
                   <div className="text-[10px] font-bold uppercase tracking-widest text-neutral-500 mb-1">이벤트 감시 이력</div>
                   <div className="flex flex-wrap items-center gap-2">
                     <span className="text-[13px] font-bold text-white">{recentAlertLabel}</span>
                     <span className="text-[13px] text-neutral-600">·</span>
                     <span className="text-[13px] font-medium text-neutral-400">{recentAlertDetail}</span>
                   </div>
                </div>
             </div>
             
             <div className="flex items-center text-right border-l border-white/5 pl-5">
                <div>
                   <div className="text-[10px] font-bold uppercase tracking-widest text-neutral-500 mb-1">현재 활성 이벤트</div>
                   <div className="text-[13px] font-bold text-white">{recentEvents.length}건</div>
                </div>
             </div>
          </div>
        </div>
      )}
    </div>
  </div>
);
}
"""

content = content[:old_return_start] + new_return

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("done")
