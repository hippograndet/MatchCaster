// frontend/src/components/DevPanel.tsx
// Developer-only inspector panel — only rendered when ?dev=true is in the URL.
// Shows the full commentator pipeline per LLM call:
//   Trigger → 4 Prompt Layers → LLM Output → TTS → Latency
// Also includes prompt override controls and a config viewer.

import { useState, useEffect, useRef } from 'react'
import type { PipelineTrace } from '../../utils/types'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function classificationBadge(c: string) {
  const map: Record<string, string> = {
    CRITICAL: 'bg-red-600 text-white',
    NOTABLE: 'bg-amber-500 text-black',
    ROUTINE: 'bg-zinc-600 text-zinc-200',
    'dead-air': 'bg-blue-600 text-white',
    follow_up: 'bg-purple-600 text-white',
  }
  return map[c] ?? 'bg-zinc-700 text-zinc-300'
}

function agentColor(a: string) {
  const map: Record<string, string> = {
    play_by_play: 'text-emerald-400',
    tactical: 'text-sky-400',
    stats: 'text-violet-400',
  }
  return map[a] ?? 'text-zinc-300'
}

function ms(v: number) {
  return v > 0 ? `${Math.round(v)}ms` : '—'
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
      className="ml-1 px-1.5 py-0.5 text-[10px] rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-300 transition-colors"
    >
      {copied ? '✓' : 'copy'}
    </button>
  )
}

function PreBlock({ label, value, dim }: { label: string; value: string; dim?: boolean }) {
  return (
    <div className={`mb-2 ${dim ? 'opacity-50' : ''}`}>
      <div className="flex items-center gap-1 mb-0.5">
        <span className="text-[10px] font-mono text-amber-400 uppercase tracking-wider">{label}</span>
        <CopyButton text={value} />
      </div>
      <pre className="text-[11px] font-mono text-zinc-300 bg-zinc-900 rounded p-2 overflow-auto max-h-36 whitespace-pre-wrap break-words leading-relaxed border border-zinc-800">
        {value || '(empty)'}
      </pre>
    </div>
  )
}

function Section({ title, open, onToggle, children }: {
  title: string; open: boolean; onToggle: () => void; children: React.ReactNode
}) {
  return (
    <div className="border border-zinc-800 rounded mt-1">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-zinc-800/50 transition-colors"
      >
        <span className="text-zinc-500 text-xs">{open ? '▼' : '▶'}</span>
        <span className="text-[11px] font-semibold text-zinc-300 uppercase tracking-wider">{title}</span>
      </button>
      {open && <div className="px-3 pb-3 pt-1">{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Prompt Override Controls
// ---------------------------------------------------------------------------
function OverrideControl({
  agent,
  fieldKey,
  label,
  currentValue,
  onQueued,
}: {
  agent: string
  fieldKey: 'system_prompt' | 'user_prompt'
  label: string
  currentValue: string
  onQueued: () => void
}) {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState(currentValue)
  const [status, setStatus] = useState<'idle' | 'sending' | 'ok' | 'err'>('idle')

  // Sync value when currentValue changes (new trace arrived)
  useEffect(() => { if (!open) setValue(currentValue) }, [currentValue, open])

  async function send() {
    setStatus('sending')
    try {
      const body: Record<string, string> = { agent }
      body[fieldKey] = value
      const res = await fetch(`${API_BASE}/api/dev/prompt-override`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (res.ok) { setStatus('ok'); onQueued(); setOpen(false) }
      else setStatus('err')
    } catch { setStatus('err') }
    setTimeout(() => setStatus('idle'), 2000)
  }

  return (
    <div className="mt-2">
      {!open ? (
        <button
          onClick={() => { setValue(currentValue); setOpen(true) }}
          className="text-[10px] px-2 py-0.5 rounded border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 transition-colors"
        >
          Override {label} next call ›
        </button>
      ) : (
        <div className="border border-amber-500/30 rounded p-2 bg-zinc-950">
          <div className="text-[10px] text-amber-400 mb-1 font-mono uppercase">{label} override</div>
          <textarea
            value={value}
            onChange={e => setValue(e.target.value)}
            className="w-full text-[11px] font-mono bg-zinc-900 text-zinc-200 border border-zinc-700 rounded p-1.5 resize-y min-h-[80px] outline-none focus:border-amber-500/60"
          />
          <div className="flex gap-2 mt-1.5">
            <button
              onClick={send}
              disabled={status === 'sending'}
              className="text-[10px] px-2 py-0.5 rounded bg-amber-600 hover:bg-amber-500 text-white transition-colors disabled:opacity-50"
            >
              {status === 'sending' ? 'Sending…' : status === 'ok' ? '✓ Queued' : status === 'err' ? '✗ Error' : 'Queue override'}
            </button>
            <button
              onClick={() => setOpen(false)}
              className="text-[10px] px-2 py-0.5 rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-300 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Single Trace Card
// ---------------------------------------------------------------------------
function TraceCard({ trace, pending }: { trace: PipelineTrace; pending: boolean }) {
  const [openSections, setOpenSections] = useState<Set<string>>(new Set())
  const [overridePending, setOverridePending] = useState(pending)

  const toggle = (s: string) =>
    setOpenSections(prev => {
      const n = new Set(prev)
      n.has(s) ? n.delete(s) : n.add(s)
      return n
    })

  const llmPct = trace.end_to_end_ms > 0 ? (trace.llm_generation_ms / trace.end_to_end_ms) * 100 : 0
  const ttsPct = trace.end_to_end_ms > 0 ? (trace.tts_synthesis_ms / trace.end_to_end_ms) * 100 : 0
  const overheadPct = Math.max(0, 100 - llmPct - ttsPct)

  return (
    <div className="border border-zinc-800 rounded bg-zinc-900/50 mb-2">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-zinc-800">
        <span className="text-[11px] font-mono text-zinc-500">#{trace.trace_id}</span>
        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${classificationBadge(trace.classification)}`}>
          {trace.classification}
        </span>
        <span className={`text-[11px] font-semibold ${agentColor(trace.agent_selected)}`}>
          {trace.agent_selected}
        </span>
        <span className="text-[10px] text-zinc-500 ml-auto">{ms(trace.end_to_end_ms)} e2e</span>
        {(overridePending || pending) && (
          <span className="text-[10px] text-amber-400 border border-amber-500/40 rounded px-1.5 py-0.5">
            ⚑ override queued
          </span>
        )}
        {trace.llm_used_fallback && (
          <span className="text-[10px] text-orange-400 border border-orange-500/40 rounded px-1.5 py-0.5">
            fallback
          </span>
        )}
      </div>

      {/* Trigger */}
      <Section title="Trigger" open={openSections.has('trigger')} onToggle={() => toggle('trigger')}>
        <div className="text-[10px] text-zinc-500 mb-1">{trace.selection_reason}</div>
        <table className="w-full text-[11px] font-mono">
          <thead>
            <tr className="text-zinc-600 text-left">
              <th className="pr-3 font-normal">type</th>
              <th className="pr-3 font-normal">player</th>
              <th className="font-normal">team</th>
            </tr>
          </thead>
          <tbody>
            {trace.trigger_events.map((ev, i) => (
              <tr key={i} className="text-zinc-300">
                <td className="pr-3 text-amber-300">{ev.type}</td>
                <td className="pr-3">{ev.player}</td>
                <td>{ev.team}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      {/* Prompt Layers */}
      <Section title="Prompt Layers" open={openSections.has('prompt')} onToggle={() => toggle('prompt')}>
        <PreBlock label="① General Context  (system prompt)" value={trace.layer_general_context} />
        <PreBlock label="② Match Context  (score · minute · stats)" value={trace.layer_match_context} />
        <PreBlock label="③ Recent Play  (what not to repeat)" value={trace.layer_recent_play} />
        <PreBlock label="④ Immediate  (triggering events)" value={trace.layer_immediate} />
        <PreBlock label="Assembled user prompt →" value={trace.user_prompt_assembled} dim />

        <div className="mt-3 border-t border-zinc-800 pt-3 flex flex-col gap-1">
          <OverrideControl
            agent={trace.agent_selected}
            fieldKey="system_prompt"
            label="System Prompt"
            currentValue={trace.layer_general_context}
            onQueued={() => setOverridePending(true)}
          />
          <OverrideControl
            agent={trace.agent_selected}
            fieldKey="user_prompt"
            label="User Prompt"
            currentValue={trace.user_prompt_assembled}
            onQueued={() => setOverridePending(true)}
          />
        </div>
      </Section>

      {/* LLM Output */}
      <Section title="LLM Output" open={openSections.has('llm')} onToggle={() => toggle('llm')}>
        <div className="grid grid-cols-2 gap-2 mb-2">
          <div>
            <div className="text-[10px] text-zinc-500 mb-0.5 flex items-center gap-1">
              Raw response <CopyButton text={trace.llm_raw_response} />
            </div>
            <pre className="text-[11px] font-mono text-zinc-400 bg-zinc-900 rounded p-2 overflow-auto max-h-24 whitespace-pre-wrap border border-zinc-800">
              {trace.llm_raw_response || '(empty)'}
            </pre>
          </div>
          <div>
            <div className="text-[10px] text-zinc-500 mb-0.5 flex items-center gap-1">
              Cleaned text <CopyButton text={trace.llm_cleaned_text} />
            </div>
            <pre className="text-[11px] font-mono text-emerald-300 bg-zinc-900 rounded p-2 overflow-auto max-h-24 whitespace-pre-wrap border border-zinc-800">
              {trace.llm_cleaned_text || '(empty)'}
            </pre>
          </div>
        </div>
        <div className="flex gap-4 text-[11px] font-mono text-zinc-400">
          <span>tokens: <span className="text-zinc-200">{trace.llm_token_count}</span></span>
          <span>gen: <span className="text-zinc-200">{ms(trace.llm_generation_ms)}</span></span>
          {trace.llm_used_fallback && <span className="text-orange-400">⚠ fallback used</span>}
        </div>
      </Section>

      {/* TTS */}
      <Section title="TTS" open={openSections.has('tts')} onToggle={() => toggle('tts')}>
        <div className="flex gap-4 text-[11px] font-mono text-zinc-400 mb-3">
          <span>voice: <span className="text-zinc-200">{trace.tts_voice || '—'}</span></span>
          <span>backend: <span className={trace.tts_backend === 'piper' ? 'text-emerald-400' : trace.tts_backend === 'say' ? 'text-amber-400' : 'text-zinc-500'}>{trace.tts_backend || '—'}</span></span>
          <span>synth: <span className="text-zinc-200">{ms(trace.tts_synthesis_ms)}</span></span>
          <span>duration: <span className="text-zinc-200">{trace.tts_audio_duration_sec > 0 ? `${trace.tts_audio_duration_sec.toFixed(1)}s` : '—'}</span></span>
        </div>

        {/* Latency bar */}
        {trace.end_to_end_ms > 0 && (
          <div>
            <div className="text-[10px] text-zinc-500 mb-1">
              Latency breakdown — {ms(trace.end_to_end_ms)} total
            </div>
            <div className="flex rounded overflow-hidden h-4 text-[9px] font-mono">
              <div
                style={{ width: `${llmPct}%` }}
                className="bg-sky-700 flex items-center justify-center text-white overflow-hidden"
                title={`LLM ${ms(trace.llm_generation_ms)}`}
              >
                {llmPct > 15 ? `LLM ${ms(trace.llm_generation_ms)}` : ''}
              </div>
              <div
                style={{ width: `${ttsPct}%` }}
                className="bg-violet-700 flex items-center justify-center text-white overflow-hidden"
                title={`TTS ${ms(trace.tts_synthesis_ms)}`}
              >
                {ttsPct > 12 ? `TTS ${ms(trace.tts_synthesis_ms)}` : ''}
              </div>
              <div
                style={{ width: `${overheadPct}%` }}
                className="bg-zinc-700 flex items-center justify-center text-zinc-400 overflow-hidden"
                title="Overhead"
              >
                {overheadPct > 10 ? 'other' : ''}
              </div>
            </div>
            <div className="flex gap-3 mt-1 text-[9px] font-mono text-zinc-500">
              <span><span className="inline-block w-2 h-2 rounded-sm bg-sky-700 mr-1" />LLM {Math.round(llmPct)}%</span>
              <span><span className="inline-block w-2 h-2 rounded-sm bg-violet-700 mr-1" />TTS {Math.round(ttsPct)}%</span>
              <span><span className="inline-block w-2 h-2 rounded-sm bg-zinc-700 mr-1" />other {Math.round(overheadPct)}%</span>
            </div>
          </div>
        )}
      </Section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Config Tab
// ---------------------------------------------------------------------------
function ConfigTab() {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    fetch(`${API_BASE}/api/dev/config`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(setConfig)
      .catch(() => setErr(true))
  }, [])

  if (err) return <div className="text-[11px] text-red-400 p-3">Failed to load config — is backend running with DEV_MODE=true?</div>
  if (!config) return <div className="text-[11px] text-zinc-500 p-3">Loading…</div>

  // Group by section prefix (keys matching SECTION_*)
  const sections: Record<string, [string, unknown][]> = {}
  for (const [k, v] of Object.entries(config)) {
    if (typeof v === 'object' && v !== null && !Array.isArray(v)) continue
    const parts = k.split('_')
    let group = 'Other'
    if (['OLLAMA'].some(p => k.startsWith(p))) group = 'Ollama'
    else if (['PIPER', 'MAX_AUDIO', 'AGENT_TEMP', 'AGENT_VOI'].some(p => k.startsWith(p))) group = 'TTS / Agents'
    else if (['DEFAULT_SPEED', 'EVENT_BUFFER', 'MAX_CONCURRENT'].some(p => k.startsWith(p))) group = 'Replay'
    else if (['PBP', 'TACTICAL', 'STATS', 'MIN_GAP', 'DEAD_AIR', 'ROUTINE'].some(p => k.startsWith(p))) group = 'Director'
    else if (['MAX_AUDIO_QUEUE', 'MAX_OUTPUT'].some(p => k.startsWith(p))) group = 'Queue / Output'
    else if (['HOST', 'PORT'].some(p => k.startsWith(p))) group = 'Server'
    else if (['DATA', 'MATCHES', 'LINEUPS'].some(p => k.startsWith(p))) group = 'Paths'
    else if (['DEV'].some(p => k.startsWith(p))) group = 'Dev'
    ;(sections[group] ??= []).push([k, v])
  }

  return (
    <div className="overflow-auto h-full p-3">
      {Object.entries(sections).map(([section, entries]) => (
        <div key={section} className="mb-4">
          <div className="text-[10px] font-bold text-amber-400 uppercase tracking-wider mb-1">{section}</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
            {entries.map(([k, v]) => (
              <div key={k} className="flex gap-2 text-[11px] font-mono py-0.5 border-b border-zinc-800/50">
                <span className="text-zinc-400 truncate">{k}</span>
                <span className="text-zinc-200 ml-auto truncate max-w-[140px]" title={String(v)}>
                  {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                </span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main DevPanel
// ---------------------------------------------------------------------------
interface DevPanelProps {
  traces: PipelineTrace[]
  onForceTrigger?: () => void
}

export default function DevPanel({ traces, onForceTrigger }: DevPanelProps) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<'traces' | 'config'>('traces')
  const [pendingOverrides, setPendingOverrides] = useState<Record<string, boolean>>({})
  const prevTraceIds = useRef<Set<string>>(new Set())

  // Clear pending-override badge when a new trace arrives for that agent
  // (means the override was consumed)
  useEffect(() => {
    if (traces.length === 0) return
    const latest = traces[0]
    if (!prevTraceIds.current.has(latest.trace_id)) {
      prevTraceIds.current.add(latest.trace_id)
      setPendingOverrides(prev => {
        if (prev[latest.agent_selected]) {
          const n = { ...prev }
          delete n[latest.agent_selected]
          return n
        }
        return prev
      })
    }
  }, [traces])

  return (
    <>
      {/* Floating toggle badge */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-20 right-4 z-50 px-2 py-1 rounded text-[11px] font-mono font-bold bg-amber-600 hover:bg-amber-500 text-white shadow-lg transition-colors"
          title="Open Dev Inspector (?dev=true)"
        >
          DEV
          {Object.values(pendingOverrides).some(Boolean) && (
            <span className="ml-1 text-[9px]">⚑</span>
          )}
        </button>
      )}

      {/* Panel */}
      {open && (
        <div className="fixed bottom-4 right-4 z-50 w-[680px] h-[72vh] flex flex-col rounded-lg shadow-2xl border border-amber-500/30 bg-[#0d0d1a] overflow-hidden">
          {/* Panel header */}
          <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800 flex-shrink-0">
            <span className="text-[11px] font-mono font-bold text-amber-400 uppercase tracking-wider">
              DEV INSPECTOR
            </span>
            <div className="flex gap-1 ml-2">
              {(['traces', 'config'] as const).map(t => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`text-[10px] px-2 py-0.5 rounded transition-colors ${
                    tab === t
                      ? 'bg-amber-600 text-white'
                      : 'text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  {t === 'traces' ? `Traces (${traces.length})` : 'Config'}
                </button>
              ))}
            </div>
            <button
              onClick={() => setOpen(false)}
              className="ml-auto text-zinc-500 hover:text-zinc-200 text-sm transition-colors"
            >
              ✕
            </button>
          </div>

          {/* Tab content */}
          {tab === 'config' ? (
            <div className="flex-1 min-h-0">
              <ConfigTab />
            </div>
          ) : (
            <div className="flex-1 min-h-0 flex flex-col">
              {/* Traces toolbar */}
              <div className="flex items-center gap-2 px-3 py-1.5 border-b border-zinc-800 flex-shrink-0">
                <span className="text-[10px] text-zinc-500">{traces.length} traces (newest first)</span>
                {onForceTrigger && (
                  <button
                    onClick={onForceTrigger}
                    className="ml-2 text-[10px] px-2 py-0.5 rounded bg-emerald-700 hover:bg-emerald-600 text-white transition-colors font-mono"
                    title="Force an immediate commentary call (bypasses cooldowns)"
                  >
                    ⚡ Force trigger
                  </button>
                )}
                <span
                  className="ml-auto text-[10px] text-zinc-600"
                  title="Traces are cleared when you reload the match"
                >
                  ← reload match to clear
                </span>
              </div>

              {/* Scrollable trace list */}
              <div className="flex-1 overflow-auto p-3">
                {traces.length === 0 ? (
                  <div className="text-[11px] text-zinc-600 text-center pt-8">
                    No traces yet — start a match replay.<br />
                    Backend must be running with <span className="font-mono text-amber-500">DEV_MODE=true</span>
                  </div>
                ) : (
                  traces.map(trace => (
                    <TraceCard
                      key={trace.trace_id}
                      trace={trace}
                      pending={!!pendingOverrides[trace.agent_selected]}
                    />
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </>
  )
}
