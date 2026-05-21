import { ResultsGrid } from '../results/ResultsGrid'
import type { SearchResult } from '../../types/contracts'
import type { ThumbnailSize } from '../../app/App'

type SearchViewProps = {
  coreSearchReady: boolean
  isSearching: boolean
  showLoadingSkeleton: boolean
  query: string
  results: SearchResult[]
  errorMessage: string | null
  statusMessage: string
  thumbnailSize: ThumbnailSize
  onThumbnailSizeChange: (size: ThumbnailSize) => void
  onPreview: (result: SearchResult) => void
}

const thumbnailOptions: Array<{
  value: ThumbnailSize
  label: string
  iconSize: 'large' | 'medium' | 'small'
}> = [
  { value: 'large', label: 'Large thumbnails', iconSize: 'large' },
  { value: 'medium', label: 'Medium thumbnails', iconSize: 'medium' },
  { value: 'small', label: 'Small thumbnails', iconSize: 'small' },
]

export function SearchView({
  coreSearchReady,
  isSearching,
  showLoadingSkeleton,
  query,
  results,
  errorMessage,
  statusMessage,
  thumbnailSize,
  onThumbnailSizeChange,
  onPreview,
}: SearchViewProps) {
  return (
    <section className="workspace-panel">
      <header className="workspace-panel__header workspace-panel__header--compact">
        <div>
          <p className="workspace-panel__eyebrow">Results</p>
          {errorMessage ? <p className="workspace-panel__copy">Issue: {errorMessage}</p> : null}
        </div>

        <div
          className="view-size-toggle"
          data-size={thumbnailSize}
          role="group"
          aria-label="Thumbnail size"
        >
          <span className="view-size-toggle__thumb" aria-hidden="true" />
          {thumbnailOptions.map((option) => (
            <button
              key={option.value}
              type="button"
              className="view-size-toggle__button"
              data-active={thumbnailSize === option.value}
              aria-pressed={thumbnailSize === option.value}
              aria-label={option.label}
              title={option.label}
              onClick={() => onThumbnailSizeChange(option.value)}
            >
              <ThumbnailSizeIcon size={option.iconSize} />
            </button>
          ))}
        </div>
      </header>

      <div className="workspace-results">
        <ResultsGrid
          coreSearchReady={coreSearchReady}
          isSearching={isSearching}
          showLoadingSkeleton={showLoadingSkeleton}
          query={query}
          results={results}
          statusMessage={statusMessage}
          thumbnailSize={thumbnailSize}
          onPreview={onPreview}
        />
      </div>
    </section>
  )
}

function ThumbnailSizeIcon({ size }: { size: 'large' | 'medium' | 'small' }) {
  if (size === 'large') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="4" y="4" width="16" height="16" rx="3" fill="currentColor" />
      </svg>
    )
  }

  if (size === 'medium') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="5" y="5" width="6" height="6" rx="1.5" fill="currentColor" />
        <rect x="13" y="5" width="6" height="6" rx="1.5" fill="currentColor" />
        <rect x="5" y="13" width="6" height="6" rx="1.5" fill="currentColor" />
        <rect x="13" y="13" width="6" height="6" rx="1.5" fill="currentColor" />
      </svg>
    )
  }

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {Array.from({ length: 3 }).map((_, row) =>
        Array.from({ length: 3 }).map((__, column) => (
          <rect
            key={`${row}-${column}`}
            x={4 + column * 5.33}
            y={4 + row * 5.33}
            width="3.1"
            height="3.1"
            rx="0.9"
            fill="currentColor"
          />
        )),
      )}
    </svg>
  )
}
