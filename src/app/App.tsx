import { useState } from 'react'

import { FoldersView } from '../features/folders/FoldersView'
import { PreviewModal } from '../features/preview/PreviewModal'
import { SearchView } from '../features/search/SearchView'
import { useRecallApp } from '../hooks/useRecallApp'
import { LeftNavRail, type WorkspaceView } from './LeftNavRail'
import { StatusPanel } from './StatusPanel'
import { TopHeader, type SearchScope } from './TopHeader'

export type ThumbnailSize = 'large' | 'medium' | 'small'

export function RecallApp() {
  const [view, setView] = useState<WorkspaceView>('search')
  const [scope, setScope] = useState<SearchScope>('images')
  const [thumbnailSize, setThumbnailSize] = useState<ThumbnailSize>('large')
  const app = useRecallApp(scope)
  const isModalOpen = Boolean(app.selectedResult)

  const handleQueryChange = (value: string) => {
    setView('search')
    app.setQuery(value)
  }

    return (
    <>
      <div className="app-shell" data-modal-open={isModalOpen}>
        <div className="app-frame">
          <LeftNavRail activeView={view} onChangeView={setView} />

          <TopHeader
            query={app.query}
            disabled={!app.coreSearchReady}
            helperText={app.searchDisabledReason}
            scope={scope}
            onQueryChange={handleQueryChange}
            onScopeChange={setScope}
            health={app.health}
            status={app.status}
          />

          <main className="workspace" aria-live="polite">
            {view === 'search' ? (
              <SearchView
                coreSearchReady={app.coreSearchReady}
                isSearching={app.isSearching || app.isBootstrapping}
                showLoadingSkeleton={app.showSearchSkeleton}
                query={app.query}
                results={app.results}
                errorMessage={app.errorMessage}
                statusMessage={app.searchDisabledReason}
                thumbnailSize={thumbnailSize}
                onThumbnailSizeChange={setThumbnailSize}
                onPreview={app.previewResult}
              />
            ) : (
              <FoldersView
                folders={app.folders}
                activeFolderIds={app.activeFolderSet}
                onAddFolders={app.addFolders}
                onRemoveFolder={app.removeFolder}
                onToggleFolder={app.toggleFolder}
              />
            )}
          </main>

          <StatusPanel
            shellReady={app.shellReady}
            status={app.status}
            health={app.health}
            scope={scope}
          />
        </div>
      </div>

      <PreviewModal
        result={app.selectedResult}
        onClose={app.closePreview}
        onOpenFile={app.openFile}
        onOpenLocation={app.openLocation}
        onCopyPath={app.copyPath}
      />
    </>
  )
}
