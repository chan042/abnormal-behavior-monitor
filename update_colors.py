import os

files = [
    "frontend/src/components/dashboard/dashboard-app.tsx",
    "frontend/src/components/dashboard/browser-live-panel.tsx"
]

for file_path in files:
    with open(file_path, "r") as f:
        content = f.read()

    # Change to black base and neutral scale
    content = content.replace("slate-950", "black")
    content = content.replace("slate-900", "neutral-900")
    content = content.replace("slate-800", "neutral-800")
    content = content.replace("slate-700", "neutral-700")
    content = content.replace("slate-600", "neutral-600")
    content = content.replace("slate-500", "neutral-500")
    content = content.replace("slate-400", "neutral-400")
    content = content.replace("slate-300", "neutral-300")
    content = content.replace("slate-200", "neutral-200")
    content = content.replace("slate-100", "neutral-100")
    
    # Remove gradients
    content = content.replace('bg-gradient-to-r from-red-500 to-red-300', 'bg-red-500')
    content = content.replace('bg-gradient-to-r from-amber-500 to-yellow-300', 'bg-amber-500')
    content = content.replace('bg-gradient-to-r from-emerald-500 to-green-300', 'bg-emerald-500')
    content = content.replace('bg-gradient-to-r from-red-500 to-orange-300', 'bg-red-500')
    content = content.replace('bg-gradient-to-r from-neutral-500 to-neutral-300', 'bg-neutral-600')
    content = content.replace('bg-gradient-to-r from-blue-500 to-cyan-300', 'bg-blue-500')
    content = content.replace('bg-gradient-to-r from-indigo-500 to-blue-300', 'bg-indigo-500')
    content = content.replace('bg-gradient-to-r from-blue-500 to-cyan-400', 'bg-blue-500')
    
    # Further refinement for black UI
    # In Vercel-like design, borders are border-white/10
    content = content.replace('border-neutral-800', 'border-white/10')
    # Soften panel backgrounds
    content = content.replace('bg-neutral-900/50', 'bg-white/5')
    content = content.replace('bg-neutral-900/40', 'bg-white/5')
    content = content.replace('bg-neutral-900', 'bg-neutral-900/40')
    
    # Header should be solid or subtle
    # Make MetricCards sharper
    content = content.replace('rounded-lg', 'rounded-md')

    with open(file_path, "w") as f:
        f.write(content)

print("Colors updated.")
