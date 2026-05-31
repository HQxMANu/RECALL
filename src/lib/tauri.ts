import { invoke, isTauri } from '@tauri-apps/api/core'

import { mockApi } from './mock'
import type {
  AppHealth,
  FolderSelectionResult,
  IndexedFolder,
  IndexingStatus,
  SearchRequest,
  SearchResponse,
} from '../types/contracts'

const api = isTauri() ? null : mockApi
const assetPreviewCache = new Map<string, Promise<string | null> | string | null>()

export async function selectFolders(): Promise<FolderSelectionResult> {
  if (api) {
    return api.selectFolders()
  }

  return invoke<FolderSelectionResult>('select_folders')
}

export async function listIndexedFolders(): Promise<IndexedFolder[]> {
  if (api) {
    return api.listIndexedFolders()
  }

  return invoke<IndexedFolder[]>('list_indexed_folders')
}

export async function removeIndexedFolder(folderId: number): Promise<void> {
  if (api) {
    return api.removeIndexedFolder(folderId)
  }

  return invoke('remove_indexed_folder', { folderId })
}

export async function rebuildIndex(folderIds?: number[]): Promise<void> {
  if (api) {
    return api.rebuildIndex(folderIds)
  }

  return invoke('rebuild_index', { folderIds })
}

export async function getIndexingStatus(): Promise<IndexingStatus> {
  if (api) {
    return api.getIndexingStatus()
  }

  return invoke<IndexingStatus>('get_indexing_status')
}

export async function searchAssets(request: SearchRequest): Promise<SearchResponse> {
  if (api) {
    return api.searchAssets(request)
  }

  return invoke<SearchResponse>('search_assets', { request })
}

export async function openFileLocation(assetId: number): Promise<void> {
  if (api) {
    return api.openFileLocation(assetId)
  }

  return invoke('open_file_location', { assetId })
}

export async function openAssetFile(assetId: number): Promise<void> {
  if (api) {
    return api.openAssetFile(assetId)
  }

  return invoke('open_asset_file', { assetId })
}

export async function copyAssetPath(assetId: number): Promise<void> {
  if (api) {
    return api.copyAssetPath(assetId)
  }

  return invoke('copy_asset_path', { assetId })
}

export async function getAppHealth(): Promise<AppHealth> {
  if (api) {
    return api.getAppHealth()
  }

  return invoke<AppHealth>('get_app_health')
}

export async function getAssetPreviewSource(
  assetId: number,
  variant: 'thumbnail' | 'preview',
): Promise<string | null> {
  const cacheKey = `${assetId}:${variant}`
  const cached = assetPreviewCache.get(cacheKey)
  if (cached instanceof Promise) {
    return cached
  }
  if (typeof cached === 'string' || cached === null) {
    return cached
  }

  const nextRequest = (api
    ? api.getAssetPreviewSource(assetId, variant)
    : invoke<string | null>('resolve_asset_preview_source', { assetId, variant })
  )
    .then((source) => {
      assetPreviewCache.set(cacheKey, source)
      return source
    })
    .catch((error) => {
      assetPreviewCache.delete(cacheKey)
      throw error
    })

  assetPreviewCache.set(cacheKey, nextRequest)
  return nextRequest
}

export function clearAssetPreviewCache() {
  assetPreviewCache.clear()
}
