// Shared abbreviated model labels for table headers and tight layouts.
// Long IDs like `gemini-2.5-flash-lite` overflow 8-column tables on
// typical viewports — these short forms keep the same information at
// a glance without horizontal scrolling.

const SHORT_LABELS = {
  'claude-haiku-4-5': 'Haiku 4.5',
  'claude-opus-4-7': 'Opus 4.7',
  'gemini-2.5-flash': 'Flash',
  'gemini-2.5-flash-lite': 'Flash Lite',
  'gemini-2.5-pro': 'Pro',
  'gpt-4o-mini': '4o-mini',
  'gpt-5': 'GPT-5',
  'o3': 'o3',
}

export function shortLabel(model) {
  return SHORT_LABELS[model] || model
}

// Tier classification for grouping/coloring. SLM = small fast model,
// frontier = the 2026 frontier-tier reasoning models.
const TIERS = {
  'claude-haiku-4-5': 'slm',
  'gemini-2.5-flash': 'slm',
  'gemini-2.5-flash-lite': 'slm',
  'gpt-4o-mini': 'slm',
  'claude-opus-4-7': 'frontier',
  'gemini-2.5-pro': 'frontier',
  'gpt-5': 'frontier',
  'o3': 'frontier',
}

export function modelTier(model) {
  return TIERS[model] || 'unknown'
}

// Consistent per-model colors so a model has the same color across
// every chart. The 4 SLM-tier models keep their original v1 palette;
// the 4 frontier-tier models get distinct hues.
export const MODEL_COLORS = {
  'gemini-2.5-flash-lite': '#34d399',  // emerald — original v1
  'claude-haiku-4-5':      '#fbbf24',  // amber   — original v1
  'gemini-2.5-flash':      '#60a5fa',  // blue    — original v1
  'gpt-4o-mini':           '#f472b6',  // pink    — original v1
  'claude-opus-4-7':       '#a78bfa',  // purple  — frontier
  'gemini-2.5-pro':        '#fb923c',  // orange  — frontier
  'gpt-5':                 '#2dd4bf',  // teal    — frontier
  'o3':                    '#818cf8',  // indigo  — frontier
}

export function modelColor(model, fallbackIndex = 0) {
  const FALLBACK = ['#94a3b8', '#cbd5e1']
  return MODEL_COLORS[model] || FALLBACK[fallbackIndex % FALLBACK.length]
}

// Shape variation for scatter charts where 8 series of overlapping
// points become a blob. Recharts <Scatter shape="..."> accepts any of
// these built-in names. SLM tier gets filled shapes, frontier tier
// gets outline-style shapes — readable side-by-side in legend.
const MODEL_SHAPES = {
  'gemini-2.5-flash-lite': 'circle',
  'claude-haiku-4-5':      'triangle',
  'gemini-2.5-flash':      'square',
  'gpt-4o-mini':           'diamond',
  'claude-opus-4-7':       'cross',
  'gemini-2.5-pro':        'star',
  'gpt-5':                 'wye',
  'o3':                    'circle',  // o3 + flash-lite are both circles —
                                       // distinguished by color (indigo vs emerald)
}

export function modelShape(model) {
  return MODEL_SHAPES[model] || 'circle'
}
