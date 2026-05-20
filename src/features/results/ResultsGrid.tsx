import { resolveImageSource } from '../../lib/tauri'
import type { ThumbnailSize } from '../../app/App'
import type { SearchResult } from '../../types/contracts'

type ResultsGridProps = {
  coreSearchReady: boolean
  isSearching: boolean
  query: string
  results: SearchResult[]
  statusMessage: string
  thumbnailSize: ThumbnailSize
  onPreview: (result: SearchResult) => void
}

function formatScore(score: number) {
  return `${Math.round(score * 100)}%`
}

export function ResultsGrid({
  coreSearchReady,
  isSearching,
  query,
  results,
  statusMessage,
  thumbnailSize,
  onPreview,
}: ResultsGridProps) {
  if (!coreSearchReady) {
    return (
      <div className="results-empty">
        <div className="results-empty__panel">
          <h2>Core search is warming up</h2>
          <p>{statusMessage}</p>
        </div>
      </div>
    )
  }

  if (!results.length) {
    return (
      <div className="results-empty">
        <div className="results-empty__panel">
          <h2>{isSearching ? 'Searching your local index...' : 'No matches yet'}</h2>
          <p>
            {query
              ? 'Try a broader phrase, remove a folder filter, or finish indexing more files.'
              : 'Add folders and start typing a natural-language query to search locally.'}
          </p>
        </div>
      </div>
    )
  }

  return (
    <ul className="result-grid" data-size={thumbnailSize}>
      {results.map((result) => {
        const imageSource = resolveImageSource(result.thumbnailPath ?? result.path)
        return (
          <li key={result.imageId}>
            <button
              type="button"
              className="result-card"
              aria-label={`Open preview for ${result.filename}`}
              onClick={() => onPreview(result)}
            >
              <div className="result-card__thumb">
                {imageSource ? (
                  <img src={imageSource} alt={result.filename} loading="lazy" />
                ) : (
                  <div className="result-card__thumb-fallback">Preview unavailable</div>
                )}
                <div className="result-card__scores">
                  <span className="score-chip">semantic {formatScore(result.semanticScore)}</span>
                  <span className="score-chip">text {formatScore(result.textScore)}</span>
                </div>
              </div>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
