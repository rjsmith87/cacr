import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ELI5Panel from '../components/ELI5Panel'
import { modelTier, shortLabel } from '../lib/modelLabels'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const COOLDOWN_S = 30

// ── Default snippet that auto-runs on first mount ────────────────────
const SSRF_SNIPPET = `import requests
def fetch_avatar(url):
    return requests.get(url, timeout=5).content
`

const DEFAULT_FORM = {
  code_snippet: SSRF_SNIPPET,
  task: 'SecurityVuln',
  strategy_a: 'gemini-2.5-flash',
  strategy_b: 'cacr',
  escalation_threshold: 8,
}

// Quick-start example cards. Snippets verified in the prior research
// pass — at threshold=8 SSRF triggers a step-2 escalation, the
// generate_token snippet exposes the overconfident-wrong blind spot
// (Flash Lite says vulnerable=False with conf=10, Flash says weak_prng
// with vulnerable=True), and the timing snippet produces full
// agreement with no escalation.
const EXAMPLES = [
  {
    title: 'SSRF Detection',
    caption: 'Watch CACR escalate when confidence drops.',
    form: {
      code_snippet: `import requests
def fetch_avatar(url):
    return requests.get(url, timeout=5).content
`,
      task: 'SecurityVuln',
      strategy_a: 'gemini-2.5-flash',
      strategy_b: 'cacr',
      escalation_threshold: 8,
    },
  },
  {
    title: 'Insecure Random',
    caption: 'The blind spot: wrong and confident.',
    form: {
      code_snippet: `import random
def generate_token():
    return ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=32))
`,
      task: 'SecurityVuln',
      strategy_a: 'gemini-2.5-flash',
      strategy_b: 'cacr',
      escalation_threshold: 8,
    },
  },
  {
    title: 'Timing Side-Channel',
    caption: 'Both models agree — no escalation needed.',
    form: {
      code_snippet: `def check_password(stored, provided):
    if len(stored) != len(provided):
        return False
    for a, b in zip(stored, provided):
        if a != b:
            return False
    return True
`,
      task: 'SecurityVuln',
      strategy_a: 'gemini-2.5-flash',
      strategy_b: 'cacr',
      escalation_threshold: 8,
    },
  },
]

// 9 strategy options — 8 single-model strategies + CACR.
const STRATEGY_OPTIONS = [
  { value: 'cacr', label: 'CACR Routed' },
  { value: 'gemini-2.5-flash', label: 'All Flash' },
  { value: 'gemini-2.5-flash-lite', label: 'All Flash Lite' },
  { value: 'claude-haiku-4-5', label: 'All Haiku 4.5' },
  { value: 'gpt-4o-mini', label: 'All 4o-mini' },
  { value: 'gemini-2.5-pro', label: 'All Pro' },
  { value: 'gpt-5', label: 'All GPT-5' },
  { value: 'o3', label: 'All o3' },
  { value: 'claude-opus-4-7', label: 'All Opus 4.7' },
]

const STEP_NAMES = ['Classification', 'Analysis', 'Remediation']

// ── Helpers ──────────────────────────────────────────────────────────
function fmtCost(usd) {
  if (usd == null) return '—'
  if (usd === 0) return '$0.00'
  if (usd < 0.001) return `$${usd.toFixed(6)}`
  if (usd < 1) return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(2)}`
}

function fmtLat(ms) {
  if (ms == null) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

function strategyLabel(value) {
  const opt = STRATEGY_OPTIONS.find(o => o.value === value)
  return opt ? opt.label : value
}

// Threshold-aware confidence tier: green ≥ threshold, yellow within 1
// of threshold (i.e. == threshold - 1), red below or null.
function confidenceTier(value, threshold) {
  if (value == null) return 'red'
  if (value >= threshold) return 'green'
  if (value >= threshold - 1) return 'yellow'
  return 'red'
}

// Pull severity / vulnerable / issue_type / fix from a raw step output —
// same regexes as pipelines/cascade_pipeline.py, lifted to JS so the
// step-level escalation trace can show the parsed classification.
const _SEV_RE = /severity:\s*(critical|high|medium|low|none)/i
const _VULN_RE = /vulnerable:\s*(yes|no)/i
const _ISSUE_RE = /issue_type:\s*(\S+)/i
const _FIX_RE = /fix:\s*(.+)/is

function parseStepFields(out) {
  if (!out) return { severity: null, vulnerable: null, issue_type: null, fix: null }
  const sev = out.match(_SEV_RE)?.[1]?.toLowerCase() ?? null
  const vuln = (() => {
    const m = out.match(_VULN_RE)
    return m ? m[1].toLowerCase() === 'yes' : null
  })()
  const issue = out.match(_ISSUE_RE)?.[1]?.toLowerCase() ?? null
  const fix = out.match(_FIX_RE)?.[1]?.trim() ?? null
  return { severity: sev, vulnerable: vuln, issue_type: issue, fix }
}

// Did the escalated model produce a different classification than the
// initial? Used in the escalation trace.
function classificationChanged(initial_output, escalation_output) {
  const a = parseStepFields(initial_output)
  const b = parseStepFields(escalation_output)
  return (
    a.severity !== b.severity ||
    a.vulnerable !== b.vulnerable ||
    a.issue_type !== b.issue_type
  )
}

// ── Confidence bar ───────────────────────────────────────────────────
function ConfidenceBar({ value, threshold }) {
  const tier = confidenceTier(value, threshold)
  const fill = tier === 'green' ? 'bg-emerald-500'
             : tier === 'yellow' ? 'bg-yellow-500'
             : 'bg-red-500'
  const text = tier === 'green' ? 'text-emerald-300'
             : tier === 'yellow' ? 'text-yellow-300'
             : 'text-red-300'
  if (value == null) {
    return (
      <div className="flex items-center gap-2">
        <div className="flex-1 bg-gray-800 rounded-full h-2 overflow-hidden">
          <div className="h-full bg-red-500/60" style={{ width: '100%' }} />
        </div>
        <span className={`text-xs font-mono ${text} tabular-nums`}>no signal</span>
      </div>
    )
  }
  const pct = Math.max(0, Math.min(100, (value / 10) * 100))
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-gray-800 rounded-full h-2 overflow-hidden">
        <div className={`h-full ${fill} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-xs font-mono ${text} tabular-nums`}>{value}/10</span>
    </div>
  )
}

// ── Tier badge for the model used on a step ──────────────────────────
function TierBadge({ model }) {
  const tier = modelTier(model)
  const cls = tier === 'frontier'
    ? 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40'
    : 'bg-gray-700/40 text-gray-300 border-gray-600/40'
  return (
    <span className={`text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded border ${cls}`}>
      {tier === 'frontier' ? 'frontier' : 'SLM'}
    </span>
  )
}

// ── Escalation trace (collapsible) ───────────────────────────────────
function EscalationTrace({ step, threshold }) {
  const [open, setOpen] = useState(false)
  const initialFields = parseStepFields(step.initial_output)
  const escFields = parseStepFields(step.escalation_output)
  const changed = classificationChanged(step.initial_output, step.escalation_output)
  return (
    <div className="border-l-2 border-indigo-500/50 pl-3 mt-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="text-xs text-indigo-300 hover:text-indigo-200 font-medium flex items-center gap-1"
      >
        <span>{open ? '▾' : '▸'}</span> Escalation trace
      </button>
      {open && (
        <div className="mt-2 space-y-2 text-xs text-gray-400">
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-gray-950/80 rounded px-2 py-1.5 border border-gray-800">
              <div className="text-gray-500 mb-0.5">Initial</div>
              <div className="font-mono text-gray-300">{shortLabel(step.initial_model)}</div>
              <div>conf: <span className="font-mono">{step.initial_confidence ?? 'null'}</span></div>
              {initialFields.severity && <div>severity: <span className="font-mono">{initialFields.severity}</span></div>}
              {initialFields.issue_type && <div>type: <span className="font-mono">{initialFields.issue_type}</span></div>}
              {initialFields.vulnerable !== null && <div>vulnerable: <span className="font-mono">{String(initialFields.vulnerable)}</span></div>}
            </div>
            <div className="bg-gray-950/80 rounded px-2 py-1.5 border border-indigo-900/40">
              <div className="text-indigo-400 mb-0.5">Escalated to</div>
              <div className="font-mono text-indigo-200">{shortLabel(step.escalation_model)}</div>
              <div>conf: <span className="font-mono">{step.escalation_confidence ?? 'null'}</span></div>
              {escFields.severity && <div>severity: <span className="font-mono">{escFields.severity}</span></div>}
              {escFields.issue_type && <div>type: <span className="font-mono">{escFields.issue_type}</span></div>}
              {escFields.vulnerable !== null && <div>vulnerable: <span className="font-mono">{String(escFields.vulnerable)}</span></div>}
            </div>
          </div>
          <div className={`text-xs font-medium ${changed ? 'text-amber-300' : 'text-gray-500'}`}>
            {changed ? '⚠ Classification changed after escalation' : 'Classification unchanged after escalation (just higher confidence)'}
          </div>
          <div className="text-xs text-gray-500">
            Initial confidence <span className="font-mono">{step.initial_confidence ?? 'null'}</span> was below threshold{' '}
            <span className="font-mono">{threshold}</span>; router escalated to the next-cheapest model with{' '}
            <span className="font-mono">mean_score ≥ 0.70</span>.
          </div>
        </div>
      )}
    </div>
  )
}

// ── Step card ────────────────────────────────────────────────────────
function StepCard({ step, idx, threshold }) {
  const [outputOpen, setOutputOpen] = useState(false)
  const truncatedAt = 150
  const output = step.accepted_output ?? ''
  const truncatedView = output.length > truncatedAt
  const shown = outputOpen || !truncatedView ? output : output.slice(0, truncatedAt) + '…'
  const cardBorder = step.escalated ? 'border-indigo-900/50' : 'border-gray-800'
  const cardLeftAccent = step.escalated ? 'border-l-2 border-l-indigo-500' : ''
  const totalCost = (step.initial_cost || 0) + (step.escalation_cost || 0)
  const totalLat = (step.initial_latency || 0) + (step.escalation_latency || 0)
  return (
    <div className={`bg-gray-900 border ${cardBorder} ${cardLeftAccent} rounded-lg p-4 flex flex-col gap-2.5`}>
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-gray-500 font-medium">Step {idx + 1}</div>
          <div className="text-sm font-semibold text-gray-200">{STEP_NAMES[idx] ?? step.name}</div>
        </div>
        <div className="flex items-center gap-1.5">
          {step.escalated && (
            <span className="text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/40">
              Escalated
            </span>
          )}
          {step.below_threshold && (
            <span className="text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40" title={step.warning ?? undefined}>
              Below threshold
            </span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <span className="text-xs font-mono text-gray-200">{shortLabel(step.accepted_model)}</span>
        <TierBadge model={step.accepted_model} />
      </div>

      <div>
        <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Confidence</div>
        <ConfidenceBar value={step.accepted_confidence} threshold={threshold} />
      </div>

      <div>
        <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Output ({output.length} chars)</div>
        <pre className="text-xs text-gray-300 font-mono bg-gray-950 border border-gray-800 rounded px-2 py-1.5 whitespace-pre-wrap break-words leading-snug">{shown}</pre>
        {truncatedView && (
          <button type="button" onClick={() => setOutputOpen(!outputOpen)} className="text-xs text-indigo-400 hover:text-indigo-300 mt-1">
            {outputOpen ? 'Show less' : 'Show more'}
          </button>
        )}
      </div>

      <div className="flex items-center justify-between text-xs text-gray-500 pt-1.5 border-t border-gray-800">
        <span>Cost <span className="font-mono text-emerald-400">{fmtCost(totalCost)}</span></span>
        <span>Latency <span className="font-mono text-gray-300">{fmtLat(totalLat)}</span></span>
      </div>

      {step.escalated && <EscalationTrace step={step} threshold={threshold} />}
    </div>
  )
}

// ── Strategy column ──────────────────────────────────────────────────
function StrategyColumn({ pipeline, threshold, label }) {
  if (!pipeline) return null
  const totalCalls = pipeline.steps.reduce(
    (sum, s) => sum + 1 + (s.escalated ? 1 : 0),
    0,
  )
  const summary = pipeline.step_summary || {}
  const outcomeText =
    summary.fix_present && summary.vulnerable
      ? `Detected ${summary.issue_type ?? 'issue'} (${summary.severity ?? '—'}); proposed a fix.`
      : summary.fix_present
      ? 'Proposed a fix; vuln=no.'
      : 'No fix produced.'
  return (
    <div className="flex flex-col gap-3">
      <div className="bg-gray-900 border border-gray-700 rounded-lg px-4 py-3">
        <div className="flex items-baseline justify-between">
          <h3 className="text-base font-semibold text-white">{label}</h3>
          <span className="text-xs text-gray-500 font-mono">{pipeline.strategy}</span>
        </div>
        <div className="text-xs text-gray-400 mt-0.5">
          Models: <span className="font-mono text-gray-200">
            {[...new Set(pipeline.steps.map(s => s.accepted_model))].map(shortLabel).join(' → ')}
          </span>
        </div>
      </div>

      {pipeline.steps.map((step, i) => (
        <StepCard key={i} step={step} idx={i} threshold={threshold} />
      ))}

      <div className="bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 mt-1">
        <div className="grid grid-cols-3 gap-3 text-center">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500">Total cost</div>
            <div className="text-base font-mono font-bold text-emerald-400">{fmtCost(pipeline.total_cost_usd)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500">Total latency</div>
            <div className="text-base font-mono font-bold text-gray-200">{fmtLat(pipeline.total_latency_ms)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500">API calls</div>
            <div className="text-base font-mono font-bold text-gray-200">{totalCalls}</div>
          </div>
        </div>
        <div className="mt-3 pt-3 border-t border-gray-800 text-xs text-gray-400">{outcomeText}</div>
      </div>
    </div>
  )
}

// ── Outcome verdict (bottom of side-by-side) ─────────────────────────
function summariesAgree(a, b) {
  if (!a || !b) return false
  return (
    a.severity === b.severity &&
    a.vulnerable === b.vulnerable &&
    a.issue_type === b.issue_type
  )
}

function ComparisonBar({ result }) {
  if (!result) return null
  const a = result.strategy_a
  const b = result.strategy_b
  const agreed = summariesAgree(a.step_summary, b.step_summary)
  const escalated = b.any_escalated || a.any_escalated
  const ratio = result.comparison?.cost_ratio_a_over_b ?? null

  let verdictText
  let tone
  if (escalated) {
    const escalatedPipeline = b.any_escalated ? b : a
    const escalatedStepIdx = escalatedPipeline.steps.findIndex(s => s.escalated)
    const stepNum = escalatedStepIdx >= 0 ? escalatedStepIdx + 1 : '?'
    const escStep = escalatedPipeline.steps[escalatedStepIdx]
    const initConf = escStep?.initial_confidence
    verdictText = `${escalatedPipeline.strategy === 'cacr' ? 'CACR' : strategyLabel(escalatedPipeline.strategy)} escalated at step ${stepNum} — initial model's confidence (${initConf ?? 'null'}) was below your threshold (${result.escalation_threshold}).`
    tone = 'border-indigo-700/50 bg-indigo-950/30 text-indigo-200'
  } else if (agreed) {
    let cheaper = null
    if (ratio != null && ratio > 1) cheaper = b
    else if (ratio != null && ratio < 1) cheaper = a
    const cheaperLabel = cheaper === a ? strategyLabel(a.strategy) : cheaper === b ? strategyLabel(b.strategy) : null
    const moreExpensive = cheaper === a ? b : a
    const savings = cheaper && moreExpensive
      ? Math.abs((moreExpensive.total_cost_usd ?? 0) - (cheaper.total_cost_usd ?? 0))
      : 0
    verdictText = cheaperLabel
      ? `Same outcome on this snippet. ${cheaperLabel} ran for ${fmtCost(savings)} less.`
      : 'Same outcome on this snippet at near-identical cost.'
    tone = 'border-emerald-700/50 bg-emerald-950/30 text-emerald-200'
  } else {
    verdictText = '⚠ Strategies disagree. Review the step-by-step trace to see where they diverge — confidence-based escalation only catches uncertain models, not overconfident wrong ones.'
    tone = 'border-amber-700/50 bg-amber-950/30 text-amber-200'
  }

  return (
    <div className={`mt-6 rounded-lg border ${tone} px-4 py-3`}>
      <div className="flex items-baseline justify-between gap-4 flex-wrap">
        <div className="text-sm font-medium">{verdictText}</div>
        {ratio != null && (
          <div className="text-xs font-mono text-gray-400 whitespace-nowrap">
            cost ratio A÷B: <span className="text-gray-200">{ratio.toFixed(2)}×</span>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Example cards ────────────────────────────────────────────────────
function ExampleCards({ onPick, disabled, cooldownRemaining }) {
  return (
    <div className="mt-6">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">Try these examples</h3>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {EXAMPLES.map(ex => (
          <button
            key={ex.title}
            type="button"
            disabled={disabled}
            onClick={() => onPick(ex.form)}
            className="bg-gray-900 border border-gray-800 rounded-lg p-4 text-left hover:border-indigo-700/50 hover:bg-gray-900/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            title={disabled && cooldownRemaining > 0 ? `Cooldown: ${cooldownRemaining}s remaining` : undefined}
          >
            <div className="text-sm font-semibold text-gray-200">{ex.title}</div>
            <div className="text-xs text-gray-500 mt-1.5">{ex.caption}</div>
            <div className="text-[10px] text-gray-600 mt-3 font-mono uppercase tracking-wider">
              {strategyLabel(ex.form.strategy_a)} vs {strategyLabel(ex.form.strategy_b)} · threshold {ex.form.escalation_threshold}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Run form ─────────────────────────────────────────────────────────
function RunForm({ form, setForm, onSubmit, loading, cooldownRemaining, error }) {
  const cooldownActive = cooldownRemaining > 0
  const codeOk = form.code_snippet.trim().length > 0 && form.code_snippet.length <= 5000
  const taskOk = !!form.task
  const stratsOk = !!form.strategy_a && !!form.strategy_b
  const canSubmit = codeOk && taskOk && stratsOk && !loading && !cooldownActive

  const update = (k, v) => setForm(prev => ({ ...prev, [k]: v }))

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); onSubmit(form) }}
      className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex flex-col gap-4"
    >
      <div>
        <label className="block text-sm font-medium text-gray-300 mb-1.5">Code snippet</label>
        <textarea
          value={form.code_snippet}
          onChange={(e) => update('code_snippet', e.target.value)}
          rows={10}
          maxLength={5000}
          placeholder="Paste your code here..."
          className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2.5 text-sm text-gray-100 font-mono placeholder:text-gray-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30 resize-y"
        />
        <div className="text-xs text-gray-500 mt-1">{form.code_snippet.length}/5000 chars</div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1.5">Task</label>
          <select
            value={form.task}
            onChange={(e) => update('task', e.target.value)}
            className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2.5 text-sm text-gray-100 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30"
          >
            <option value="CodeReview">Code Review</option>
            <option value="SecurityVuln">Security Vuln</option>
            <option value="CodeSummarization">Code Summarization</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1.5">Compare this...</label>
          <select
            value={form.strategy_a}
            onChange={(e) => update('strategy_a', e.target.value)}
            className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2.5 text-sm text-gray-100 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30"
          >
            {STRATEGY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1.5">...against this</label>
          <select
            value={form.strategy_b}
            onChange={(e) => update('strategy_b', e.target.value)}
            className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2.5 text-sm text-gray-100 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30"
          >
            {STRATEGY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      </div>

      <div>
        <div className="flex items-baseline justify-between mb-1.5">
          <label className="text-sm font-medium text-gray-300">Escalation threshold</label>
          <span className="text-sm font-mono text-indigo-300">{form.escalation_threshold}/10</span>
        </div>
        <input
          type="range"
          min={1}
          max={10}
          step={1}
          value={form.escalation_threshold}
          onChange={(e) => update('escalation_threshold', Number(e.target.value))}
          className="w-full accent-indigo-500"
        />
        <div className="text-xs text-gray-500 mt-1">
          Lower = fewer escalations (cheaper, more risk). Higher = more escalations (safer, more expensive).
        </div>
      </div>

      {error && (
        <div className="bg-red-950/40 border border-red-800 rounded-lg px-3 py-2 text-red-300 text-xs">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-medium py-2.5 rounded-lg transition-colors text-sm"
      >
        {loading ? 'Running... (6 API calls)'
          : cooldownActive ? `Cooldown: ${cooldownRemaining}s`
          : 'Run Pipeline'}
      </button>
    </form>
  )
}

// ── Main component ───────────────────────────────────────────────────
export default function CascadeDemo() {
  const [form, setForm] = useState(DEFAULT_FORM)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [cooldownUntil, setCooldownUntil] = useState(0)
  const [cooldownRemaining, setCooldownRemaining] = useState(0)
  const autoRunFiredRef = useRef(false)

  // Tick the cooldown countdown.
  useEffect(() => {
    if (cooldownUntil <= Date.now()) {
      setCooldownRemaining(0)
      return
    }
    const id = setInterval(() => {
      const remaining = Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000))
      setCooldownRemaining(remaining)
      if (remaining === 0) clearInterval(id)
    }, 250)
    return () => clearInterval(id)
  }, [cooldownUntil])

  const runPipeline = useCallback(async (formValues) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API}/api/cascade-compare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formValues),
      })
      const body = await res.json().catch(() => ({}))
      if (res.status === 429) {
        const retry = body.retry_in_seconds ?? 30
        setCooldownUntil(Date.now() + retry * 1000)
        setError(`Rate limited: ${retry}s cooldown remaining. The /api/cascade-compare endpoint allows one run every 30 seconds per IP.`)
        return
      }
      if (!res.ok) {
        const msg = body.error || `HTTP ${res.status}`
        setError(msg)
        return
      }
      setResult(body)
      try {
        sessionStorage.setItem('cascade_default_result', JSON.stringify(body))
      } catch { /* sessionStorage unavailable / quota — non-fatal */ }
      // Start the 30s cooldown after a successful run.
      setCooldownUntil(Date.now() + COOLDOWN_S * 1000)
    } catch (err) {
      setError(`Network error: ${err?.message ?? err}`)
    } finally {
      setLoading(false)
    }
  }, [])

  // Auto-run the default SSRF example on first mount. If sessionStorage
  // already has a cached result (refresh within the cooldown window),
  // hydrate from that instead so a refresh doesn't waste a 429.
  useEffect(() => {
    if (autoRunFiredRef.current) return
    autoRunFiredRef.current = true
    let cached = null
    try {
      const raw = sessionStorage.getItem('cascade_default_result')
      if (raw) cached = JSON.parse(raw)
    } catch { /* ignore */ }
    if (cached) {
      setResult(cached)
      return
    }
    runPipeline(DEFAULT_FORM)
  }, [runPipeline])

  // ── ELI5 prompt construction ───────────────────────────────────────
  const eliState = useMemo(() => {
    if (!result) return null
    const a = result.strategy_a
    const b = result.strategy_b
    const agreed = summariesAgree(a.step_summary, b.step_summary)
    const escalated = a.any_escalated || b.any_escalated
    let context, warning, hint
    if (escalated) {
      context = 'escalation_fired'
      const esc = b.any_escalated ? b : a
      const stepIdx = esc.steps.findIndex(s => s.escalated)
      const escStep = esc.steps[stepIdx]
      warning = (
        `${esc.strategy === 'cacr' ? 'CACR' : strategyLabel(esc.strategy)} escalated at step ${stepIdx + 1} ` +
        `from ${shortLabel(escStep.initial_model)} (confidence ${escStep.initial_confidence}) to ` +
        `${shortLabel(escStep.escalation_model)} (confidence ${escStep.escalation_confidence}). ` +
        `Initial confidence was below the user's threshold of ${result.escalation_threshold}.`
      )
      hint = (
        "You are explaining a cascade-comparison run to a non-technical engineer. " +
        "Explain in plain English: what triggered the escalation, what changed (or didn't) " +
        "in the classification, and whether the extra cost was worth it given the outcome. " +
        "Be specific about the actual confidence numbers and model names."
      )
    } else if (!agreed) {
      context = 'overconfident_wrong'
      warning = (
        `Strategies disagree on classification but neither escalated. This is the limitation ` +
        `of runtime confidence-based escalation: it only catches uncertain models, not overconfident ` +
        `wrong ones. The cheaper model produced a high-confidence answer that differs from the more ` +
        `expensive model's answer — exactly the silent-failure mode benchmark data is meant to catch ` +
        `at routing time, not runtime.`
      )
      hint = (
        "You are explaining a cascade-comparison run to a non-technical engineer. The two strategies " +
        "produced different answers but neither one's confidence dropped low enough to trigger " +
        "escalation. Explain plainly that confidence-based escalation can't catch this case — when a " +
        "model is wrong AND confident, runtime signals don't help. This is why CACR maintains " +
        "benchmark data as a safety net alongside runtime signals. Reference the actual confidence " +
        "numbers and the specific disagreement."
      )
    } else {
      context = 'agreement'
      hint = (
        "You are explaining a cascade-comparison run to a non-technical engineer. Both strategies " +
        "agreed on classification. Explain whether the cost difference matters in practice and what " +
        "this kind of agreement means for the routing decision. Be specific with dollar amounts."
      )
    }
    return { context, warning, hint }
  }, [result])

  const dataSummary = useMemo(() => {
    if (!result) return ''
    const fmtPipe = (p) => {
      const stepLines = p.steps.map((s, i) => {
        const accepted = `${shortLabel(s.accepted_model)} conf=${s.accepted_confidence ?? 'null'}`
        const esc = s.escalated
          ? ` (escalated from ${shortLabel(s.initial_model)} conf=${s.initial_confidence} → ${shortLabel(s.escalation_model)} conf=${s.escalation_confidence})`
          : ''
        return `  step ${i + 1} ${STEP_NAMES[i]}: ${accepted}${esc}`
      }).join('\n')
      return [
        `${strategyLabel(p.strategy)} (${p.strategy})`,
        `  step_summary: severity=${p.step_summary?.severity}, vulnerable=${p.step_summary?.vulnerable}, issue_type=${p.step_summary?.issue_type}`,
        `  total_cost=$${(p.total_cost_usd ?? 0).toFixed(6)}, total_latency=${(p.total_latency_ms ?? 0).toFixed(0)}ms`,
        stepLines,
      ].join('\n')
    }
    return [
      `Task: ${result.task}, escalation_threshold: ${result.escalation_threshold}`,
      ``,
      fmtPipe(result.strategy_a),
      ``,
      fmtPipe(result.strategy_b),
      ``,
      `cost_ratio_a_over_b: ${result.comparison?.cost_ratio_a_over_b ?? 'N/A'}`,
    ].join('\n')
  }, [result])

  return (
    <div>
      {/* Hero */}
      <div className="mb-6">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-indigo-400 font-semibold mb-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
          Cascade Comparison
        </div>
        <h2 className="text-2xl font-bold text-white">Cascade Comparison</h2>
        <p className="text-gray-400 mt-2 max-w-3xl">
          Compare how different models and routing strategies handle a multi-step pipeline.
          See where cascade failures happen, what they cost, and when confidence-based escalation
          helps — and when it doesn't.
        </p>
      </div>

      {/* Results panel — auto-loads default SSRF example on first mount. */}
      <div className="mb-6">
        {!result && loading && (
          <div className="bg-gray-900 border border-gray-800 rounded-xl px-6 py-12 text-center">
            <div className="inline-flex items-center gap-2 text-gray-400">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
              </svg>
              Running default SSRF example (6 API calls, ~10s)...
            </div>
          </div>
        )}
        {!result && !loading && error && (
          <div className="bg-red-950/40 border border-red-800 rounded-xl px-4 py-3 text-red-300 text-sm">
            {error}
          </div>
        )}
        {result && (
          <>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
              <StrategyColumn pipeline={result.strategy_a} threshold={result.escalation_threshold} label={strategyLabel(result.strategy_a.strategy)} />
              <StrategyColumn pipeline={result.strategy_b} threshold={result.escalation_threshold} label={strategyLabel(result.strategy_b.strategy)} />
            </div>
            <ComparisonBar result={result} />
          </>
        )}
      </div>

      {/* ELI5 — sits below the results, above the form */}
      {result && eliState && (
        <ELI5Panel
          dataSummary={dataSummary}
          promptHint={eliState.hint}
          warning={eliState.warning}
          taskName={result.task}
          cascadeContext={eliState.context}
          refreshKey={`${result.strategy_a.strategy}|${result.strategy_b.strategy}|${result.escalation_threshold}|${eliState.context}`}
        />
      )}

      {/* Form */}
      <div className="mt-8">
        <h3 className="text-lg font-semibold text-white mb-3">Run a custom comparison</h3>
        <RunForm
          form={form}
          setForm={setForm}
          onSubmit={runPipeline}
          loading={loading}
          cooldownRemaining={cooldownRemaining}
          error={error}
        />
      </div>

      {/* Example cards — clicking one fills the form AND fires the run.
          Disabled during cooldown to match the form-submit button. */}
      <ExampleCards
        onPick={(formValues) => {
          setForm(formValues)
          runPipeline(formValues)
        }}
        disabled={loading || cooldownRemaining > 0}
        cooldownRemaining={cooldownRemaining}
      />
    </div>
  )
}
