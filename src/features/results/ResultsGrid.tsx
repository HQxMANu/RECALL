import { memo, useEffect, useMemo, useRef } from 'react'

import type { ThumbnailSize } from '../../app/App'
import type { SearchResult } from '../../types/contracts'
import { convertLocalAssetPathToSrc } from '../../lib/tauri'
import { AssetPreviewArt } from '../assets/AssetPreviewArt'
import { useAssetPreviewSource } from '../assets/useAssetPreviewSource'

type ResultsGridProps = {
  coreSearchReady: boolean
  isSearching: boolean
  showLoadingSkeleton: boolean
  query: string
  results: SearchResult[]
  statusMessage: string
  thumbnailSize: ThumbnailSize
  hasMoreResults: boolean
  isLoadingMore: boolean
  onPreview: (result: SearchResult) => void
  onLoadMore: () => void
}

function formatScore(score: number) {
  return `${Math.round(score * 100)}%`
}

function secondaryText(result: SearchResult) {
  if (result.assetType === 'image') {
    return ''
  }
  if (result.assetType === 'voice-note' && result.startMs != null) {
    return `Starts at ${Math.round(result.startMs / 1000)}s`
  }
  if (result.assetType === 'document') {
    return ''
  }
  return result.folderName ?? ''
}

function bodySnippet(result: SearchResult) {
  if (result.assetType === 'document' || result.assetType === 'image') {
    return ''
  }
  return result.snippet || result.ocrSnippet || 'No text snippet available.'
}

function showTitle(result: SearchResult) {
  return result.assetType !== 'image'
}

function ResultCard({
  result,
  onPreview,
}: {
  result: SearchResult
  onPreview: (result: SearchResult) => void
}) {
  const directThumbnailSource = useMemo(
    () => convertLocalAssetPathToSrc(result.thumbnailPath),
    [result.thumbnailPath],
  )
  const shouldResolveThumbnailFromWorker =
    !directThumbnailSource && result.assetType !== 'image'
  const resolvedThumbnailSource = useAssetPreviewSource(
    shouldResolveThumbnailFromWorker ? result.assetId : null,
    'thumbnail',
  )
  const imageSource = directThumbnailSource ?? resolvedThumbnailSource

  return (
    <li>
      <button
        type="button"
        className="result-card"
        aria-label={`Open preview for ${result.filename}`}
        onClick={() => onPreview(result)}
      >
        <div className="result-card__thumb">
          {imageSource ? (
            <img
              src={imageSource}
              alt={result.filename}
              loading="lazy"
              decoding="async"
              fetchPriority="low"
            />
          ) : (
            <div className="result-card__thumb-fallback">
              <AssetPreviewArt result={result} />
            </div>
          )}
          <div className="result-card__scores">
            <span className="score-chip">semantic {formatScore(result.semanticScore)}</span>
            <span className="score-chip">text {formatScore(result.textScore)}</span>
          </div>
        </div>
        <div className="result-card__body">
          {showTitle(result) ? <strong>{result.filename}</strong> : null}
          {secondaryText(result) ? <p>{secondaryText(result)}</p> : null}
          {bodySnippet(result) ? <p>{bodySnippet(result)}</p> : null}
        </div>
      </button>
    </li>
  )
}

const MemoResultCard = memo(
  ResultCard,
  (previous, next) =>
    previous.result.assetId === next.result.assetId &&
    previous.result.thumbnailPath === next.result.thumbnailPath &&
    previous.result.previewPath === next.result.previewPath &&
    previous.result.semanticScore === next.result.semanticScore &&
    previous.result.textScore === next.result.textScore &&
    previous.result.finalScore === next.result.finalScore &&
    previous.result.filename === next.result.filename,
)

export function ResultsGrid({
  coreSearchReady,
  isSearching,
  showLoadingSkeleton,
  query,
  results,
  statusMessage,
  thumbnailSize,
  hasMoreResults,
  isLoadingMore,
  onPreview,
  onLoadMore,
}: ResultsGridProps) {
  const loadMoreSentinelRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const sentinel = loadMoreSentinelRef.current
    if (!sentinel || !hasMoreResults || isLoadingMore || showLoadingSkeleton) {
      return
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          onLoadMore()
        }
      },
      { rootMargin: '600px 0px' },
    )

    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [hasMoreResults, isLoadingMore, onLoadMore, showLoadingSkeleton])

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

  if (showLoadingSkeleton) {
    const skeletonCount =
      thumbnailSize === 'small' ? 12 : thumbnailSize === 'medium' ? 8 : 6

    return (
      <ul className="result-grid result-grid--skeleton" data-size={thumbnailSize}>
        {Array.from({ length: skeletonCount }).map((_, index) => (
          <li key={`skeleton-${index}`}>
            <div className="result-card result-card--skeleton" aria-hidden="true">
              <div className="result-card__thumb">
                <div className="result-skeleton result-skeleton__thumb" />
                <div className="result-card__scores">
                  <span className="score-chip result-skeleton result-skeleton__chip" />
                  <span className="score-chip result-skeleton result-skeleton__chip" />
                </div>
              </div>
              <div className="result-card__body">
                <div className="result-skeleton result-skeleton__line result-skeleton__line--title" />
                <div className="result-skeleton result-skeleton__line" />
              </div>
            </div>
          </li>
        ))}
      </ul>
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
    <>
      <ul className="result-grid" data-size={thumbnailSize}>
        {results.map((result) => (
          <MemoResultCard key={result.assetId} result={result} onPreview={onPreview} />
        ))}
      </ul>
      <div
        ref={loadMoreSentinelRef}
        className="result-grid__load-more"
        aria-live="polite"
        data-loading={isLoadingMore}
      >
        {isLoadingMore ? 'Loading more results...' : null}
      </div>
    </>
  )
}
