import { ResultsGrid } from '../results/ResultsGrid'
import type { SearchResult } from '../../types/contracts'

type SearchViewProps = {
  coreSearchReady: boolean
  isSearching: boolean
  query: string
  results: SearchResult[]
  errorMessage: string | null
  statusMessage: string
  onPreview: (result: SearchResult) => void
}

export function SearchView({
  coreSearchReady,
  isSearching,
  query,
  results,
  errorMessage,
  statusMessage,
  onPreview,
}: SearchViewProps) {
  return (
    <section className="workspace-panel">
      <header className="workspace-panel__header workspace-panel__header--compact">
        <div>
          <p className="workspace-panel__eyebrow">Results</p>
          {!coreSearchReady ? <p className="workspace-panel__copy">{statusMessage}</p> : null}
          {errorMessage ? <p className="workspace-panel__copy">Issue: {errorMessage}</p> : null}
        </div>
      </header>

      <div className="workspace-results">
        <ResultsGrid
          coreSearchReady={coreSearchReady}
          isSearching={isSearching}
          query={query}
          results={results}
          statusMessage={statusMessage}
          onPreview={onPreview}
        />
      </div>
    </section>
  )
}
