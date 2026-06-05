import { useState } from 'react'

import { PreviewModal } from '../features/preview/PreviewModal'
import { SearchView } from '../features/search/SearchView'
import { useRecallApp } from '../hooks/useRecallApp'
import { LeftNavRail } from './LeftNavRail'
import { StatusPanel } from './StatusPanel'
import { TopHeader, type SearchScope } from './TopHeader'

export type ThumbnailSize = 'large' | 'medium' | 'small'

export function RecallApp() {
  const scope: SearchScope = 'images'
  const [thumbnailSize, setThumbnailSize] = useState<ThumbnailSize>('large')
  const app = useRecallApp(scope)
  const isModalOpen = Boolean(app.selectedResult)

  const handleQueryChange = (value: string) => {
    app.setQuery(value)
  }

  return (
    <>
      <div className="app-shell" data-modal-open={isModalOpen}>
        <div className="app-frame">
          <LeftNavRail />

          <TopHeader
            query={app.query}
            disabled={!app.coreSearchReady}
            helperText={app.searchDisabledReason}
            onQueryChange={handleQueryChange}
            health={app.health}
            status={app.status}
          />

          <main className="workspace" aria-live="polite">
            <SearchView
              coreSearchReady={app.coreSearchReady}
              isSearching={app.isSearching || app.isBootstrapping}
              showLoadingSkeleton={app.showSearchSkeleton}
              query={app.query}
              results={app.results}
              errorMessage={app.errorMessage}
              statusMessage={app.searchDisabledReason}
              thumbnailSize={thumbnailSize}
              hasMoreResults={app.hasMoreResults}
              isLoadingMore={app.isLoadingMore}
              onThumbnailSizeChange={setThumbnailSize}
              onPreview={app.previewResult}
              onLoadMore={app.loadMoreResults}
            />
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
      />
    </>
  )
}
