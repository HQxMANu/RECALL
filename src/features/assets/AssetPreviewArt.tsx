import type { SearchResult } from '../../types/contracts'

type AssetPreviewArtProps = {
  result: SearchResult
  mode?: 'card' | 'modal'
}

export function AssetPreviewArt({
  result,
  mode = 'card',
}: AssetPreviewArtProps) {
  if (result.assetType === 'document') {
    const extension = result.filename.split('.').pop()?.toUpperCase() ?? 'DOC'
    return (
      <div className={`asset-art asset-art--document asset-art--${mode}`}>
        <div className="asset-art__sheet">
          <div className="asset-art__sheet-top">
            <span className="asset-art__badge">{extension}</span>
            {result.pageNumber ? (
              <span className="asset-art__page">Page {result.pageNumber}</span>
            ) : null}
          </div>
          <div className="asset-art__title-block">
            <span />
            <span />
            <span />
          </div>
          <div className="asset-art__body-lines">
            <span />
            <span />
            <span />
            <span />
            <span />
            <span />
          </div>
        </div>
      </div>
    )
  }

  if (result.assetType === 'voice-note') {
    return (
      <div className={`asset-art asset-art--audio asset-art--${mode}`}>
        <div className="asset-art__audio-chip">VOICE NOTE</div>
        <div className="asset-art__waveform" aria-hidden="true">
          {Array.from({ length: 12 }).map((_, index) => (
            <span
              key={index}
              style={{ height: `${28 + ((index * 17) % 42)}%` }}
            />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className={`asset-art asset-art--generic asset-art--${mode}`}>
      Preview unavailable
    </div>
  )
}
