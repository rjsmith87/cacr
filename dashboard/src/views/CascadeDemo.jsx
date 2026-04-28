import { useState } from 'react'
import data from '../data/cascade_demo.json'
import { shortLabel } from '../lib/modelLabels'

// ─── Helpers ──────────────────────────────────────────────────────────────

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

// Confidence color tiers. The headline of this demo is that anchored
// confidence (9 every step) is uninformative — color encodes "is this
// number actually telling you something."
function confTier(c) {
  if (c == null) return { label: 'no signal', cls: 'text-red-400 bg-red-950/40 border-red-700/50' }
  if (c >= 9) return { label: `${c}`, cls: 'text-gray-300 bg-gray-800/60 border-gray-700' }
  if (c >= 7) return { label: `${c}`, cls: 'text-yellow-300 bg-yellow-950/40 border-yellow-700/50' }
  return { label: `${c}`, cls: 'text-orange-300 bg-orange-950/40 border-orange-700/50' }
}

function ConfidenceBar({ value }) {
  if (value == null) {
    return (
      <div className="flex items-center gap-2">
        <div className="flex-1 bg-gray-800 rounded-full h-2 overflow-hidden">
          <div className="h-full bg-red-500/60" style={{ width: '100%' }} />
        </div>
        <span className="text-xs font-mono text-red-400 tabular-nums">no signal</span>
      </div>
    )
  }
  const pct = Math.max(0, Math.min(100, (value / 10) * 100))
  const fill =
    value >= 9 ? 'bg-gray-500' : value >= 7 ? 'bg-yellow-500' : 'bg-orange-500'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-gray-800 rounded-full h-2 overflow-hidden">
        <div className={`h-full ${fill} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-gray-300 tabular-nums">{value}/10</span>
    </div>
  )
}

// ─── Step card ────────────────────────────────────────────────────────────

function StepCard({ step, accentClass }) {
  const [expanded, setExpanded] = useState(false)
  const truncated = step.output.length > 200
  const displayed = expanded || !truncated ? step.output : step.output.slice(0, 200) + '…'
  const conf = confTier(step.confidence)
  const routing = step.routing || {}
  const hasWarning = routing.below_threshold && routing.warning

  return (
    <div className={`bg-gray-900 border ${accentClass} rounded-lg p-4 flex flex-col gap-3`}>
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-wider text-gray-500 font-medium">Step {step.step}</div>
          <div className="text-sm font-semibold text-gray-200">{step.name}</div>
        </div>
        <div className="text-right">
          <div className="text-xs text-gray-500">Model</div>
          <div className="text-sm font-mono text-indigo-300">{shortLabel(step.model)}</div>
        </div>
      </div>

      {hasWarning && (
        <div className="bg-amber-950/40 border border-amber-700/50 rounded px-2 py-1.5 text-xs text-amber-300">
          <span className="font-semibold">⚠ below threshold:</span>{' '}
          <span className="text-amber-200/90">{routing.warning}</span>
        </div>
      )}

      <div>
        <div className="text-xs text-gray-500 mb-1">Prompt</div>
        <div className="text-xs text-gray-400 italic">{step.prompt_summary}</div>
      </div>

      <div>
        <div className="text-xs text-gray-500 mb-1">Output ({step.output.length} chars)</div>
        <pre className="text-xs text-gray-300 font-mono bg-gray-950 border border-gray-800 rounded px-2 py-1.5 whitespace-pre-wrap break-words leading-snug">{displayed}</pre>
        {truncated && (
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-indigo-400 hover:text-indigo-300 mt-1"
          >
            {expanded ? 'collapse' : 'show full output'}
          </button>
        )}
      </div>

      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-500">Confidence</span>
          <span className={`text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded border ${conf.cls}`}>
            {step.confidence == null ? 'null' : 'self-reported'}
          </span>
        </div>
        <ConfidenceBar value={step.confidence} />
      </div>

      <div className="flex items-center justify-between text-xs text-gray-500 pt-1 border-t border-gray-800">
        <span>Latency <span className="font-mono text-gray-300">{fmtLat(step.latency_ms)}</span></span>
        <span>Cost <span className="font-mono text-emerald-400">{fmtCost(step.cost_usd)}</span></span>
      </div>
    </div>
  )
}

// ─── Pipeline column ──────────────────────────────────────────────────────

function PipelineColumn({ pipeline, label, accentClass, headerAccent }) {
  const ok = pipeline.outcome.vulnerability_detected
  const fix = pipeline.outcome.fix_proposed
  const confSpread = pipeline.confidence_stats.spread
  const confValues = pipeline.confidence_stats.values

  return (
    <div className="flex flex-col gap-4">
      <div className={`rounded-lg border ${headerAccent} px-4 py-3`}>
        <div className="flex items-baseline justify-between">
          <h3 className="text-lg font-semibold text-white">{label}</h3>
          <span className="text-xs text-gray-500 font-mono">{pipeline.strategy}</span>
        </div>
        <div className="text-xs text-gray-400 mt-0.5">
          Models used: <span className="font-mono text-gray-200">{pipeline.models_used.map(shortLabel).join(' → ')}</span>
        </div>
      </div>

      {pipeline.steps.map(step => (
        <StepCard key={step.step} step={step} accentClass={accentClass} />
      ))}

      <div className={`rounded-lg border ${headerAccent} px-4 py-3 mt-2`}>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="text-xs uppercase tracking-wider text-gray-500">Total cost</div>
            <div className="text-xl font-mono font-bold text-emerald-400">{fmtCost(pipeline.total_cost_usd)}</div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider text-gray-500">Total latency</div>
            <div className="text-xl font-mono font-bold text-gray-200">{fmtLat(pipeline.total_latency_ms)}</div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 mt-3 pt-3 border-t border-gray-800">
          <div>
            <div className="text-xs text-gray-500">Vulnerability detected</div>
            <div className={`text-sm font-semibold ${ok ? 'text-emerald-400' : 'text-red-400'}`}>
              {ok ? '✓ yes' : '✗ no'}
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-500">Fix proposed</div>
            <div className={`text-sm font-semibold ${fix ? 'text-emerald-400' : 'text-red-400'}`}>
              {fix ? '✓ yes' : '✗ no'}
            </div>
          </div>
        </div>

        <div className="mt-3 pt-3 border-t border-gray-800">
          <div className="text-xs text-gray-500 mb-1">
            Confidence values across steps
          </div>
          <div className="font-mono text-sm text-gray-300">
            [{confValues.length === 0 ? '—' : confValues.map(v => v == null ? 'null' : v).join(', ')}]
            <span className="text-xs text-gray-500 ml-2">spread = {confSpread == null ? '—' : confSpread}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Main view ────────────────────────────────────────────────────────────

export default function CascadeDemo() {
  const [showCode, setShowCode] = useState(false)
  const cve = data.cve
  const af = data.all_flash
  const cr = data.cacr_routed
  const cmp = data.comparison

  // Derived headline numbers
  const costRatioCacrOverFlash =
    af.total_cost_usd > 0 ? (cr.total_cost_usd / af.total_cost_usd).toFixed(1) : null
  const latencyRatioCacrOverFlash =
    af.total_latency_ms > 0 ? (cr.total_latency_ms / af.total_latency_ms).toFixed(1) : null

  return (
    <div>
      {/* Hero */}
      <div className="mb-6">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-indigo-400 font-semibold mb-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
          Cascade Demo
        </div>
        <h2 className="text-2xl font-bold text-white">
          Both pipelines catch the bug. Only one tells you the truth about how confident it is.
        </h2>
        <p className="text-gray-400 mt-2 max-w-3xl">
          Real CVE, two pipelines. <span className="font-mono text-gray-300">{cve.id}</span> {' '}
          (gold severity: <span className="font-mono text-gray-300">{cve.severity_gold}</span>).
          Three steps each: severity classification → vulnerability detection → fix proposal.
          Both detect the vulnerability. The differences are in cost, calibration, and what each
          pipeline tells you about its own uncertainty.
        </p>
      </div>

      {/* CVE preamble */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-gray-200">{cve.id}: input code</h3>
          <button
            type="button"
            onClick={() => setShowCode(!showCode)}
            className="text-xs text-indigo-400 hover:text-indigo-300"
          >
            {showCode ? 'hide code' : 'show code'}
          </button>
        </div>
        <p className="text-xs text-gray-400">{cve.attack_vector}</p>
        {showCode && (
          <pre className="text-xs text-gray-300 font-mono bg-gray-950 border border-gray-800 rounded mt-3 p-3 overflow-x-auto leading-snug">
{cve.code}
          </pre>
        )}
      </div>

      {/* Side-by-side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PipelineColumn
          pipeline={af}
          label="All Flash"
          accentClass="border-gray-800"
          headerAccent="border-gray-700 bg-gray-900"
        />
        <PipelineColumn
          pipeline={cr}
          label="CACR Routed"
          accentClass="border-indigo-900/40"
          headerAccent="border-indigo-700/50 bg-indigo-950/30"
        />
      </div>

      {/* What just happened? */}
      <div className="mt-8 bg-gray-900 border border-gray-800 rounded-xl p-6">
        <h3 className="text-lg font-semibold text-white mb-3">What just happened?</h3>
        <div className="prose prose-invert prose-sm max-w-none text-gray-300 space-y-3">
          <p>
            Both pipelines correctly identified the session-fixation vulnerability at step 2.
            The headline isn't <em>"one catches it and the other doesn't"</em> — Flash genuinely
            solves CVE detection. The headline is <em>same outcome, very different signal.</em>
          </p>
          <p>
            <strong className="text-gray-100">Calibration.</strong>{' '}
            All Flash reported confidence{' '}
            <span className="font-mono text-gray-300">[{af.confidence_stats.values.join(', ')}]</span>{' '}
            across the three steps — a flat line that gives the operator zero information about
            which step was actually hard. CACR Routed reported{' '}
            <span className="font-mono text-gray-300">
              [{cr.confidence_stats.values.map(v => v == null ? 'null' : v).join(', ')}]
            </span>
            {' '}— variance of {cr.confidence_stats.spread ?? '—'} across steps, and a parsed-null
            on step 3 where the escalated model failed to follow the response format. Both signals
            are honest in different ways: the variance tells you Flash Lite was less sure on the
            detection step than the severity step; the null tells you the escalation produced an
            output the parser couldn't trust.
          </p>
          <p>
            <strong className="text-gray-100">Cost and latency.</strong>{' '}
            CACR Routed cost <span className="font-mono text-emerald-300">{costRatioCacrOverFlash}×</span>{' '}
            more and ran <span className="font-mono text-gray-300">{latencyRatioCacrOverFlash}×</span>{' '}
            slower. The expense came from step 3, where the router escalated to{' '}
            <span className="font-mono text-gray-300">{shortLabel(cr.steps[2].model)}</span>{' '}
            — because no SLM-tier model meets the 0.70 acceptable-score floor on generation tasks.
            That's the cascade mechanism doing its job: a below-threshold warning fired at
            step 3, recommending human review or task reformulation. The router didn't lie about
            it being expensive; it surfaced the cost and the warning together.
          </p>
          <p>
            <strong className="text-gray-100">Where CACR was actually worse.</strong>{' '}
            Flash Lite under-rated severity at step 1 (<span className="font-mono text-gray-300">medium</span>{' '}
            vs gold <span className="font-mono text-gray-300">high</span>), and Opus's step-3
            output ran past the 256-token budget and got truncated mid-sentence. Both are real
            failure modes the dashboard should not pretend away. The point of cascade-aware
            routing isn't that it always wins — it's that it surfaces the tradeoffs (calibration
            variance, escalation cost, below-threshold warnings) instead of hiding them behind a
            flat <span className="font-mono">9, 9, 9</span> from a single fast model.
          </p>
          <p className="text-gray-400">
            Re-run with <span className="font-mono text-gray-300">python pipelines/cascade_demo.py --cve {cve.id}</span>{' '}
            to regenerate this canonical bundle. Numbers will drift slightly per run.
          </p>
        </div>
      </div>
    </div>
  )
}
