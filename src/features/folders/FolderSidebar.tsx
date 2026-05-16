import type { AppHealth, IndexedFolder, IndexingStatus } from '../../types/contracts'

type FolderSidebarProps = {
  folders: IndexedFolder[]
  activeFolderIds: Set<number>
  shellReady: boolean
  status: IndexingStatus
  health: AppHealth
  onAddFolders: () => void
  onRemoveFolder: (folderId: number) => void
  onToggleFolder: (folderId: number) => void
  onClearFilters: () => void
}

function formatRelativeTime(isoDate?: string | null) {
  if (!isoDate) {
    return 'Not indexed yet'
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

  const days = Math.round(hours / 24)
  return `${days}d ago`
}

export function FolderSidebar({
  folders,
  activeFolderIds,
  shellReady,
  status,
  health,
  onAddFolders,
  onRemoveFolder,
  onToggleFolder,
  onClearFilters,
}: FolderSidebarProps) {
  return (
    <aside className="sidebar">
      <section className="sidebar__brand">
        <p className="sidebar__eyebrow">Local-first search</p>
        <h1 className="sidebar__title">Recall</h1>
        <p className="sidebar__copy">
          Search screenshots like a private desktop copilot. OCR, embeddings,
          thumbnails, and ranking all stay on your machine.
        </p>
      </section>

      <section className="sidebar__section">
        <div className="sidebar__section-header">
          <h2 className="sidebar__section-title">Indexed folders</h2>
          {!!activeFolderIds.size && (
            <button type="button" className="button-ghost" onClick={onClearFilters}>
              Clear
            </button>
          )}
        </div>
        <button type="button" className="button-primary" onClick={onAddFolders}>
          Add folders
        </button>
        <ul className="folder-list">
          {folders.map((folder) => {
            const isActive = activeFolderIds.has(folder.id)
            return (
              <li
                key={folder.id}
                className={`folder-item ${isActive ? 'folder-item--active' : ''}`}
              >
                <button
                  type="button"
                  className="folder-item__button"
                  aria-pressed={isActive}
                  onClick={() => onToggleFolder(folder.id)}
                >
                  <span className="folder-item__name">{folder.displayName}</span>
                  <span className="folder-item__path">{folder.path}</span>
                  <span className="folder-item__path">
                    {folder.imageCount.toLocaleString()} images •{' '}
                    {formatRelativeTime(folder.lastIndexedAt)}
                  </span>
                </button>
                <button
                  type="button"
                  className="button-ghost"
                  onClick={() => onRemoveFolder(folder.id)}
                  aria-label={`Remove ${folder.displayName}`}
                >
                  Remove
                </button>
              </li>
            )
          })}
        </ul>
        {!folders.length && (
          <p className="sidebar__hint">
            Add your screenshot or photo folders to start building the local index.
          </p>
        )}
      </section>

      <section className="sidebar__section">
        <div className="sidebar__section-header">
          <h2 className="sidebar__section-title">Indexer</h2>
          <span className="health-badge" data-state={status.state}>
            {status.state}
          </span>
        </div>
        <div className="health-card">
          <div className="health-row">
            <span>Progress</span>
            <strong>
              {status.itemsProcessed.toLocaleString()} / {status.itemsTotal.toLocaleString()}
            </strong>
          </div>
          <div className="health-row">
            <span>Queued jobs</span>
            <strong>{status.queuedJobs}</strong>
          </div>
          <div className="health-row">
            <span>Last completed</span>
            <strong>{formatRelativeTime(status.lastCompletedAt)}</strong>
          </div>
          {status.lastError && (
            <div className="health-row">
              <span>Error</span>
              <strong>{status.lastError}</strong>
            </div>
          )}
        </div>
      </section>

      <section className="sidebar__section">
        <div className="sidebar__section-header">
          <h2 className="sidebar__section-title">Readiness</h2>
          <span
            className="health-badge"
            data-state={health.coreSearchReady ? 'ready' : health.coreSearchPhase}
          >
            {health.coreSearchReady ? 'search ready' : health.coreSearchPhase}
          </span>
        </div>
        <div className="health-card">
          <div className="health-row">
            <span>Shell</span>
            <strong>{shellReady ? 'ready' : 'warming'}</strong>
          </div>
          <div className="health-row">
            <span>Core search</span>
            <strong>{health.coreSearchPhase}</strong>
          </div>
          <div className="health-row">
            <span>Indexing / OCR</span>
            <strong>{health.indexingPhase}</strong>
          </div>
          <p className="sidebar__hint">{health.coreSearchMessage}</p>
          <p className="sidebar__hint">{health.indexingMessage}</p>
          <div className="health-row">
            <span>OCR</span>
            <strong>{health.ocrEngine}</strong>
          </div>
          <div className="health-row">
            <span>Embeddings</span>
            <strong>{health.embeddingEngine}</strong>
          </div>
          <div className="health-row">
            <span>Vector search</span>
            <strong>{health.vectorEngine}</strong>
          </div>
          {!!health.startupMetrics?.coreSearchReadyMs && (
            <div className="health-row">
              <span>Core search boot</span>
              <strong>{health.startupMetrics.coreSearchReadyMs} ms</strong>
            </div>
          )}
          {health.startupMetrics?.vectorBootstrapMode && (
            <div className="health-row">
              <span>Vector bootstrap</span>
              <strong>{health.startupMetrics.vectorBootstrapMode}</strong>
            </div>
          )}
          <p className="sidebar__hint">{health.message}</p>
        </div>
      </section>
    </aside>
  )
}
