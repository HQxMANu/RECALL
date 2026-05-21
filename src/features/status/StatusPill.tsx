import type { AppHealth, IndexingStatus } from '../../types/contracts'
import type { SearchScope } from '../../app/TopHeader'

type StatusPillProps = {
  health: AppHealth
  status: IndexingStatus
  scope: SearchScope
}

export function StatusPill({ health, status, scope }: StatusPillProps) {
  const scopeReady =
    scope === 'documents'
      ? health.documentScopeReady
      : scope === 'voice-notes'
        ? health.voiceNoteScopeReady
        : health.imageScopeReady
  const message =
    !scopeReady
      ? health.coreSearchPhase === 'error'
        ? 'Search failed to start'
        : scope === 'documents'
          ? 'Document search warming'
          : scope === 'voice-notes'
            ? 'Voice-note search warming'
            : 'Image search warming'
      : status.state === 'indexing'
      ? `${status.itemsProcessed.toLocaleString()} / ${status.itemsTotal.toLocaleString()} indexed`
      : status.state === 'error'
        ? status.lastError || 'Indexing error'
        : 'Local index ready'

  const state =
    !scopeReady ? health.coreSearchPhase : status.state

  return (
    <div className="status-pill" data-status={state}>
      <span className="status-pill__dot" aria-hidden="true" />
      <span>{message}</span>
    </div>
  )
}
