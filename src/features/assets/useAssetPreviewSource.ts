import { useEffect, useMemo, useState } from 'react'

import { getAssetPreviewSource } from '../../lib/tauri'

type ResolvedPreview = {
  cacheKey: string
  source: string | null
}

export function useAssetPreviewSource(
  assetId: number | null,
  variant: 'thumbnail' | 'preview',
) {
  const cacheKey = useMemo(
    () => (assetId == null ? null : `${assetId}:${variant}`),
    [assetId, variant],
  )
  const [resolved, setResolved] = useState<ResolvedPreview | null>(null)

  useEffect(() => {
    let cancelled = false

    if (!cacheKey || assetId == null) {
      return () => {
        cancelled = true
      }
    }

    void getAssetPreviewSource(assetId, variant)
      .then((nextSource) => {
        if (!cancelled) {
          setResolved({ cacheKey, source: nextSource })
        }
      })
      .catch(() => {
        if (!cancelled) {
          setResolved({ cacheKey, source: null })
        }
      })

    return () => {
      cancelled = true
    }
  }, [assetId, cacheKey, variant])

  if (!cacheKey) {
    return null
  }

  return resolved?.cacheKey === cacheKey ? resolved.source : null
}
