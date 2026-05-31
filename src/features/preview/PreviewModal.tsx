import { useEffect } from 'react'

import type { SearchResult } from '../../types/contracts'
import { AssetPreviewArt } from '../assets/AssetPreviewArt'
import { useAssetPreviewSource } from '../assets/useAssetPreviewSource'

type PreviewModalProps = {
  result: SearchResult | null
  onClose: () => void
  onOpenFile: (assetId: number) => Promise<void>
  onOpenLocation: (assetId: number) => Promise<void>
  onCopyPath: (assetId: number) => Promise<void>
}

function formatDate(isoDate?: string | null) {
  if (!isoDate) {
    return 'Unknown'
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'full',
    timeStyle: 'short',
  }).format(new Date(isoDate))
}

export function PreviewModal({
  result,
  onClose,
  onOpenFile,
  onOpenLocation,
  onCopyPath,
}: PreviewModalProps) {
  const imageSource = useAssetPreviewSource(result?.assetId ?? null, 'preview')

  useEffect(() => {
    if (!result) {
      return
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose, result])

  if (!result) {
    return null
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Preview ${result.filename}`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal__image">
          {imageSource ? (
            <img src={imageSource} alt={result.filename} />
          ) : (
            <div className="result-card__thumb-fallback">
              <AssetPreviewArt result={result} mode="modal" />
            </div>
          )}
        </div>
        <aside className="modal__aside">
          <button
            type="button"
            className="button-secondary modal__close"
            aria-label="Close preview"
            onClick={onClose}
          >
            ×
          </button>

          <section className="modal__panel">
            <h2>{result.filename}</h2>
            <div className="meta-list">
              <div className="meta-row">
                <span>Path</span>
                <strong className="mono">{result.path}</strong>
              </div>
              <div className="meta-row">
                <span>Type</span>
                <strong>{result.assetType}</strong>
              </div>
              <div className="meta-row">
                <span>Modified</span>
                <strong>{formatDate(result.modifiedAt)}</strong>
              </div>
              {result.assetType === 'image' ? (
                <div className="meta-row">
                  <span>Dimensions</span>
                  <strong>
                    {result.width ?? '?'} × {result.height ?? '?'}
                  </strong>
                </div>
              ) : null}
              {result.pageNumber ? (
                <div className="meta-row">
                  <span>Page</span>
                  <strong>{result.pageNumber}</strong>
                </div>
              ) : null}
              {result.startMs != null && result.endMs != null ? (
                <div className="meta-row">
                  <span>Timestamp</span>
                  <strong>
                    {Math.round(result.startMs / 1000)}s - {Math.round(result.endMs / 1000)}s
                  </strong>
                </div>
              ) : null}
              <div className="meta-row">
                <span>Hybrid score</span>
                <strong>{Math.round(result.finalScore * 100)}%</strong>
              </div>
            </div>
          </section>

          <section className="modal__panel">
            <h3>{result.assetType === 'image' ? 'Extracted text' : 'Matched snippet'}</h3>
            <p>
              {result.snippet ||
                result.ocrSnippet ||
                (result.assetType === 'image'
                  ? 'No OCR text was extracted for this image.'
                  : 'No text snippet is available for this result.')}
            </p>
          </section>

          <div className="modal__actions">
            {result.assetType !== 'image' ? (
              <button
                type="button"
                className="button-primary"
                onClick={() => onOpenFile(result.assetId)}
              >
                Open file
              </button>
            ) : null}
            <button
              type="button"
              className={result.assetType === 'image' ? 'button-primary' : 'button-secondary'}
              onClick={() => onOpenLocation(result.assetId)}
            >
              Open file location
            </button>
            <button
              type="button"
              className="button-secondary"
              onClick={() => onCopyPath(result.assetId)}
            >
              Copy file path
            </button>
          </div>
        </aside>
      </div>
    </div>
  )
}
