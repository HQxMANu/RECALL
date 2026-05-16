import { resolveImageSource } from '../../lib/tauri'
import type { SearchResult } from '../../types/contracts'

type ResultsGridProps = {
  coreSearchReady: boolean
  isSearching: boolean
  query: string
  results: SearchResult[]
  statusMessage: string
  onPreview: (result: SearchResult) => void
}

function formatScore(score: number) {
  return `${Math.round(score * 100)}%`
}

function formatDate(isoDate: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(isoDate))
}

export function ResultsGrid({
  coreSearchReady,
  isSearching,
  query,
  results,
  statusMessage,
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
          <h2>{isSearching ? 'Searching your local index…' : 'No matches yet'}</h2>
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
    <ul className="result-grid">
      {results.map((result) => {
        const imageSource = resolveImageSource(result.thumbnailPath ?? result.path)
        return (
          <li key={result.imageId}>
            <button
              type="button"
              className="result-card"
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
              <div>
                <p className="result-card__title">{result.filename}</p>
                <p className="result-card__meta">
                  {result.folderName ?? 'Indexed folder'} • {formatDate(result.modifiedAt)}
                </p>
              </div>
              <p className="result-card__snippet">
                {result.ocrSnippet || 'No OCR snippet available.'}
              </p>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
