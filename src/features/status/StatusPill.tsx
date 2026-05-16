import type { AppHealth, IndexingStatus } from '../../types/contracts'

type StatusPillProps = {
  health: AppHealth
  status: IndexingStatus
}

export function StatusPill({ health, status }: StatusPillProps) {
  const message =
    health.coreSearchPhase !== 'ready'
      ? health.coreSearchPhase === 'error'
        ? 'Core search failed to start'
        : 'Core search warming'
      : status.state === 'indexing'
      ? `${status.itemsProcessed.toLocaleString()} / ${status.itemsTotal.toLocaleString()} indexed`
      : status.state === 'error'
        ? status.lastError || 'Indexing error'
        : 'Core search ready'

  const state =
    health.coreSearchPhase !== 'ready'
      ? health.coreSearchPhase
      : status.state

  return (
    <div className="status-pill" data-status={state}>
      <span className="status-pill__dot" aria-hidden="true" />
      <span>{message}</span>
    </div>
  )
}
