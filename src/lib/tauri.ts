import { convertFileSrc, invoke, isTauri } from '@tauri-apps/api/core'

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

export async function getIndexingStatus(): Promise<IndexingStatus> {
  if (api) {
    return api.getIndexingStatus()
  }

  return invoke<IndexingStatus>('get_indexing_status')
}

export async function searchImages(request: SearchRequest): Promise<SearchResponse> {
  if (api) {
    return api.searchImages(request)
  }

  return invoke<SearchResponse>('search_images', { request })
}

export async function openFileLocation(path: string): Promise<void> {
  if (api) {
    return api.openFileLocation()
  }

  return invoke('open_file_location', { path })
}

export async function copyImagePath(path: string): Promise<void> {
  if (api) {
    return api.copyImagePath()
  }

  return invoke('copy_image_path', { path })
}

export async function getAppHealth(): Promise<AppHealth> {
  if (api) {
    return api.getAppHealth()
  }

  return invoke<AppHealth>('get_app_health')
}

export function resolveImageSource(path?: string | null): string | undefined {
  if (!path) {
    return undefined
  }

  if (path.startsWith('data:') || path.startsWith('http')) {
    return path
  }

  if (api) {
    return undefined
  }

  return convertFileSrc(path)
}
