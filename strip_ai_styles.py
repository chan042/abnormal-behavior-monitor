import os
import re

files = [
    "frontend/src/components/dashboard/dashboard-app.tsx",
    "frontend/src/components/dashboard/browser-live-panel.tsx"
]

def clean_classes(content):
    # Colors to replace with pure black / neutral
    content = content.replace("bg-[#030b17]", "bg-black")
    content = content.replace("bg-[#0b1528]/50", "bg-neutral-900")
    content = content.replace("bg-[#0b1528]/80", "bg-neutral-900")
    content = content.replace("bg-[#1e3a8a]/20", "bg-neutral-800")
    content = content.replace("border-[#1e3a8a]/50", "border-neutral-800")
    content = content.replace("border-[#1e3a8a]/30", "border-neutral-800")
    content = content.replace("text-[#7dd3fc]", "text-neutral-100")
    content = content.replace("text-[#e0f2fe]", "text-white")
    content = content.replace("text-[#94a3b8]", "text-neutral-400")
    content = content.replace("shadow-[inset_0_0_10px_rgba(239,68,68,0.2)]", "")
    content = content.replace("border-[#38bdf8]/30", "border-neutral-800")
    content = content.replace("bg-[#38bdf8]/10", "bg-neutral-800")
    content = content.replace("text-[#38bdf8]", "text-neutral-300")
    content = content.replace("bg-[#0f172a]", "bg-neutral-900")
    content = content.replace("bg-[#06b6d4]", "bg-blue-500")
    content = content.replace("shadow-[0_0_8px_#06b6d4]", "")
    
    # Remove AI specific classes
    content = content.replace("glow-text-blue", "")
    content = content.replace("glow-text", "")
    content = content.replace("sci-fi-panel", "border-neutral-800 bg-neutral-950")
    content = content.replace("border-white/10", "border-neutral-800")
    content = content.replace("border-none", "")
    content = content.replace("border-white/20", "border-neutral-700")
    content = content.replace("bg-white/5", "bg-neutral-900")
    content = content.replace("bg-white/10", "bg-neutral-800")
    content = content.replace("border-white/30", "border-neutral-600")

    # Fix some double spaces
    content = re.sub(r'  +', ' ', content)
    
    return content

for file_path in files:
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
        
        content = clean_classes(content)
        
        with open(file_path, "w") as f:
            f.write(content)
        print(f"Cleaned {file_path}")

# Update globals.css to pure black
css_path = "frontend/src/app/globals.css"
if os.path.exists(css_path):
    with open(css_path, "r") as f:
        css_content = f.read()
        
    css_content = css_content.replace("--background: #030712;", "--background: #000000;")
    
    with open(css_path, "w") as f:
        f.write(css_content)
    print("Updated globals.css")
