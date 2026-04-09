import re

file_path = "frontend/src/components/dashboard/browser-live-panel.tsx"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace the {streaming && (...)} block.
old_return_start = content.find("      {streaming && (")
old_return_end = content.find("    </div>\n  </div>\n);\n}") + 25

if old_return_start == -1 or old_return_end == -1:
    print("Could not find the streaming block")
    exit(1)

new_streaming_block = """      {streaming && (
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
"""

content = content[:old_return_start] + new_streaming_block

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("done")
