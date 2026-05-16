import type { IndexedFolder } from '../../types/contracts'

type FoldersViewProps = {
  folders: IndexedFolder[]
  activeFolderIds: Set<number>
  onAddFolders: () => void
  onRemoveFolder: (folderId: number) => void
  onToggleFolder: (folderId: number) => void
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

  return `${Math.round(hours / 24)}d ago`
}

export function FoldersView({
  folders,
  activeFolderIds,
  onAddFolders,
  onRemoveFolder,
  onToggleFolder,
}: FoldersViewProps) {
  return (
    <section className="workspace-panel">
      <header className="workspace-panel__header">
        <div>
          <p className="workspace-panel__eyebrow">Indexed folders</p>
          <h2>Folder management</h2>
          <p className="workspace-panel__copy">
            Choose what Recall indexes and which folders should filter live search results.
          </p>
        </div>

        <button type="button" className="button-primary" onClick={onAddFolders}>
          Add folder
        </button>
      </header>

      {folders.length ? (
        <div className="folder-workspace">
          {folders.map((folder) => {
            const isActive = activeFolderIds.has(folder.id)
            return (
              <article key={folder.id} className="folder-card">
                <div className="folder-card__header">
                  <div>
                    <p className="folder-card__title">{folder.displayName}</p>
                    <p className="folder-card__path">{folder.path}</p>
                  </div>
                  <span className="health-badge" data-state={isActive ? 'ready' : 'neutral'}>
                    {isActive ? 'filtering search' : 'available'}
                  </span>
                </div>

                <div className="folder-card__meta">
                  <div>
                    <span>Images</span>
                    <strong>{folder.imageCount.toLocaleString()}</strong>
                  </div>
                  <div>
                    <span>Last indexed</span>
                    <strong>{formatRelativeTime(folder.lastIndexedAt)}</strong>
                  </div>
                </div>

                <div className="folder-card__actions">
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={() => onToggleFolder(folder.id)}
                  >
                    {isActive ? 'Remove filter' : 'Use as filter'}
                  </button>
                  <button
                    type="button"
                    className="button-ghost button-ghost--danger"
                    onClick={() => onRemoveFolder(folder.id)}
                    aria-label={`Remove ${folder.displayName}`}
                  >
                    Remove
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      ) : (
        <div className="workspace-empty">
          <div className="workspace-empty__panel">
            <h3>No folders indexed yet</h3>
            <p>Add a screenshots or photos folder to start building the local search index.</p>
          </div>
        </div>
      )}
    </section>
  )
}
