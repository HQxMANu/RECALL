import type { AppHealth, IndexingStatus } from '../types/contracts'
import type { SearchScope } from './TopHeader'

type StatusPanelProps = {
  shellReady: boolean
  status: IndexingStatus
  health: AppHealth
  scope: SearchScope
}

function formatRelativeTime(isoDate?: string | null) {
  if (!isoDate) {
    return 'Not completed yet'
  }

  const deltaMs = Date.now() - new Date(isoDate).getTime()
  const minutes = Math.max(1, Math.round(deltaMs / 60000))

  if (minutes < 60) {
    return `${minutes}m ago`
  }

  const hours = Math.round(minutes / 60)
  if (hours < 24) {
    return `${hours}h ago`
  }

  return `${Math.round(hours / 24)}d ago`
}

function humanizePhase(phase: string) {
  return phase.replace(/_/g, ' ')
}

function describeReadiness(isReady: boolean, phase: string, readyLabel = 'Ready') {
  return isReady ? readyLabel : humanizePhase(phase)
}

export function StatusPanel({ shellReady, status, health, scope }: StatusPanelProps) {
  const progressRatio =
    status.itemsTotal > 0 ? Math.min(1, status.itemsProcessed / status.itemsTotal) : 0
  const scopeReady =
    scope === 'documents'
      ? health.documentScopeReady
      : scope === 'voice-notes'
        ? health.voiceNoteScopeReady
        : health.imageScopeReady
  const scopeSemanticReady =
    scope === 'images' ? health.imageSemanticReady : health.textSemanticReady
  const scopeVectorReady =
    scope === 'images' ? health.imageVectorReady : health.textVectorReady
  const readinessBadge = scopeReady ? 'ready' : health.coreSearchPhase
  const readinessCopy = scopeReady
    ? health.coreSearchMessage
    : scope === 'documents'
      ? 'Document search is waiting for the local text embedding model to finish loading.'
      : scope === 'voice-notes'
        ? 'Voice-note search is waiting for the local transcription and text embedding models to finish loading.'
        : 'Image search is waiting for the local vision model to finish loading.'

  return (
    <aside className="status-panel">
      <section className="status-card">
        <div className="status-card__header">
          <div>
            <p className="status-card__eyebrow">Core search</p>
            <h2>Search readiness</h2>
          </div>
          <span
            className="health-badge"
            data-state={readinessBadge}
          >
            {scopeReady ? 'ready' : humanizePhase(health.coreSearchPhase)}
          </span>
        </div>

        <div className="status-list">
          <StatusRow
            label="Shell"
            value={shellReady ? 'Ready' : 'Warming'}
            tone={shellReady ? 'ready' : 'warming'}
          />
          <StatusRow
            label="Semantic search"
            value={describeReadiness(scopeSemanticReady, health.coreSearchPhase)}
            tone={scopeSemanticReady ? 'ready' : health.coreSearchPhase}
          />
          <StatusRow
            label="Text search"
            value={describeReadiness(health.textSearchReady, health.coreSearchPhase)}
            tone={health.textSearchReady ? 'ready' : health.coreSearchPhase}
          />
          <StatusRow
            label="Vector index"
            value={describeReadiness(scopeVectorReady, health.coreSearchPhase, 'Ready')}
            tone={scopeVectorReady ? 'ready' : health.coreSearchPhase}
          />
        </div>
        <p className="status-card__copy">{readinessCopy}</p>
      </section>

      <section className="status-card">
        <div className="status-card__header">
          <div>
            <p className="status-card__eyebrow">Indexer</p>
            <h2>Background work</h2>
          </div>
          <span className="health-badge" data-state={status.state}>
            {status.state}
          </span>
        </div>

        <div className="status-meter">
          <div className="status-meter__track">
            <div
              className="status-meter__fill"
              style={{ width: `${Math.max(progressRatio * 100, status.state === 'indexing' ? 4 : 0)}%` }}
            />
          </div>
          <strong>
            {status.itemsProcessed.toLocaleString()} / {status.itemsTotal.toLocaleString()}
          </strong>
        </div>

        <div className="status-list">
          <StatusRow label="Queued jobs" value={String(status.queuedJobs)} tone="neutral" />
          <StatusRow
            label="Last completed"
            value={formatRelativeTime(status.lastCompletedAt)}
            tone="neutral"
          />
          {status.lastError ? (
            <StatusRow label="Last issue" value={status.lastError} tone="error" />
          ) : null}
        </div>
      </section>

      <section className="status-card">
        <div className="status-card__header">
          <div>
            <p className="status-card__eyebrow">Local engines</p>
            <h2>Operational state</h2>
          </div>
          <span className="health-badge" data-state={health.degraded ? 'degraded' : 'ready'}>
            {health.degraded ? 'degraded' : 'full'}
          </span>
        </div>

        <div className="status-list">
          <StatusRow
            label="Embeddings engine"
            value={health.embeddingEngine}
            tone={health.embeddingEngine === 'warming' ? 'warming' : 'ready'}
          />
          <StatusRow
            label="OCR engine"
            value={health.indexingPhase === 'deferred' ? 'Ready on demand' : health.ocrEngine}
            tone={health.indexingPhase === 'deferred' ? 'neutral' : 'ready'}
          />
          <StatusRow
            label="Vector engine"
            value={health.vectorEngine}
            tone={health.vectorEngine === 'warming' ? 'warming' : 'ready'}
          />
        </div>
        <p className="status-card__copy">{health.indexingMessage}</p>
        <p className="status-card__copy">{health.message}</p>
      </section>
    </aside>
  )
}

type StatusRowProps = {
  label: string
  value: string
  tone: 'ready' | 'warming' | 'degraded' | 'error' | 'neutral' | string
}

function StatusRow({ label, value, tone }: StatusRowProps) {
  return (
    <div className="status-row">
      <span>{label}</span>
      <strong data-tone={tone}>{value}</strong>
    </div>
  )
}
