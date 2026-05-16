import { FolderSidebar } from '../features/folders/FolderSidebar'
import { PreviewModal } from '../features/preview/PreviewModal'
import { ResultsGrid } from '../features/results/ResultsGrid'
import { SearchBar } from '../features/search/SearchBar'
import { StatusPill } from '../features/status/StatusPill'
import { useRecallApp } from '../hooks/useRecallApp'

export function RecallApp() {
  const app = useRecallApp()

  return (
    <>
      <div className="recall-shell">
        <FolderSidebar
          folders={app.folders}
          activeFolderIds={app.activeFolderSet}
          shellReady={app.shellReady}
          status={app.status}
          health={app.health}
          onAddFolders={app.addFolders}
          onRemoveFolder={app.removeFolder}
          onToggleFolder={app.toggleFolder}
          onClearFilters={app.clearFilters}
        />

        <main className="main">
          <section className="hero-panel">
            <div className="topbar">
              <SearchBar
                query={app.query}
                disabled={!app.coreSearchReady}
                helperText={app.searchDisabledReason}
                onQueryChange={app.setQuery}
              />
              <div className="toolbar-meta">
                <select
                  className="sort-select"
                  value={app.sort}
                  disabled={!app.coreSearchReady}
                  onChange={(event) =>
                    app.setSort(event.target.value as 'relevance' | 'newest' | 'oldest')
                  }
                  aria-label="Sort search results"
                >
                  <option value="relevance">Sort: Relevance</option>
                  <option value="newest">Sort: Newest</option>
                  <option value="oldest">Sort: Oldest</option>
                </select>
                <StatusPill health={app.health} status={app.status} />
              </div>
            </div>
          </section>

          <section className="content-panel">
            <div className="content-shell">
              <header className="results-header">
                <div className="results-title-block">
                  <h1>Results</h1>
                  <p className="results-subtitle">
                    {app.coreSearchReady
                      ? `${app.totalHits.toLocaleString()} matches in ${app.tookMs} ms${
                          app.isSearching ? ' - refreshing...' : ''
                        }`
                      : app.searchDisabledReason}
                  </p>
                  {app.errorMessage && (
                    <p className="results-subtitle">Issue: {app.errorMessage}</p>
                  )}
                </div>
                <p className="results-subtitle">
                  Hybrid ranking: OCR + CLIP semantic similarity + recency boost
                </p>
              </header>

              <div className="results-scroll">
                <ResultsGrid
                  coreSearchReady={app.coreSearchReady}
                  isSearching={app.isSearching || app.isBootstrapping}
                  query={app.query}
                  results={app.results}
                  statusMessage={app.searchDisabledReason}
                  onPreview={app.previewResult}
                />
              </div>
            </div>
          </section>
        </main>
      </div>

      <PreviewModal
        result={app.selectedResult}
        onClose={app.closePreview}
        onOpenLocation={app.openLocation}
        onCopyPath={app.copyPath}
      />
    </>
  )
}
