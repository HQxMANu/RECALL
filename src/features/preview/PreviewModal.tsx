import { resolveImageSource } from '../../lib/tauri'
import type { SearchResult } from '../../types/contracts'

type PreviewModalProps = {
  result: SearchResult | null
  onClose: () => void
  onOpenLocation: (path: string) => Promise<void>
  onCopyPath: (path: string) => Promise<void>
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
  onOpenLocation,
  onCopyPath,
}: PreviewModalProps) {
  if (!result) {
    return null
  }

  const imageSource = resolveImageSource(result.path)

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
            <div className="result-card__thumb-fallback">Preview unavailable</div>
          )}
        </div>
        <aside className="modal__aside">
          <button type="button" className="button-secondary modal__close" onClick={onClose}>
            Close
          </button>

          <section className="modal__panel">
            <h2>{result.filename}</h2>
            <div className="meta-list">
              <div className="meta-row">
                <span>Path</span>
                <strong className="mono">{result.path}</strong>
              </div>
              <div className="meta-row">
                <span>Modified</span>
                <strong>{formatDate(result.modifiedAt)}</strong>
              </div>
              <div className="meta-row">
                <span>Dimensions</span>
                <strong>
                  {result.width ?? '?'} × {result.height ?? '?'}
                </strong>
              </div>
              <div className="meta-row">
                <span>Hybrid score</span>
                <strong>{Math.round(result.finalScore * 100)}%</strong>
              </div>
            </div>
          </section>

          <section className="modal__panel">
            <h3>Extracted text</h3>
            <p>{result.ocrSnippet || 'No OCR text was extracted for this image.'}</p>
          </section>

          <div className="modal__actions">
            <button
              type="button"
              className="button-primary"
              onClick={() => onOpenLocation(result.path)}
            >
              Open file location
            </button>
            <button
              type="button"
              className="button-secondary"
              onClick={() => onCopyPath(result.path)}
            >
              Copy image path
            </button>
          </div>
        </aside>
      </div>
    </div>
  )
}
