export type SortMode = 'relevance' | 'newest' | 'oldest'

export type IndexedFolder = {
  id: number
  path: string
  displayName: string
  isActive: boolean
  itemCount: number
  imageCount: number
  documentCount: number
  voiceNoteCount: number
  lastIndexedAt?: string | null
}

export type SearchRequest = {
  query: string
  scope: 'images' | 'documents' | 'voice-notes'
  folderIds?: number[]
  sort: SortMode
  limit: number
  offset: number
}

export type SearchResult = {
  assetId: number
  assetType: 'image' | 'document' | 'voice-note'
  path: string
  filename: string
  thumbnailPath?: string | null
  previewPath?: string | null
  modifiedAt: string
  createdAt?: string | null
  ocrSnippet?: string | null
  snippet?: string | null
  semanticScore: number
  textScore: number
  finalScore: number
  folderId: number
  folderName?: string | null
  width?: number | null
  height?: number | null
  pageNumber?: number | null
  startMs?: number | null
  endMs?: number | null
  durationMs?: number | null
}

export type SearchResponse = {
  results: SearchResult[]
  tookMs: number
  totalHits: number
  queryDebug: Record<string, number | string | boolean | null>
}

export type IndexingStatus = {
  state: 'idle' | 'indexing' | 'error'
  activeJobId?: number | null
  activeJobType?: string | null
  itemsTotal: number
  itemsProcessed: number
  queuedJobs: number
  lastCompletedAt?: string | null
  lastError?: string | null
}

export type AppHealth = {
  workerReady: boolean
  databaseReady: boolean
  textSearchReady: boolean
  semanticSearchReady: boolean
  imageSemanticReady: boolean
  textSemanticReady: boolean
  imageVectorReady: boolean
  textVectorReady: boolean
  imageScopeReady: boolean
  documentScopeReady: boolean
  voiceNoteScopeReady: boolean
  coreSearchReady: boolean
  coreSearchPhase: 'warming' | 'ready' | 'limited' | 'error'
  coreSearchMessage: string
  indexingPhase: 'deferred' | 'warming' | 'ready' | 'limited' | 'error'
  indexingMessage: string
  vectorEngine: string
  ocrEngine: string
  embeddingEngine: string
  degraded: boolean
  message: string
  startupMetrics?: {
    coreSearchReadyMs?: number | null
    embeddingInitMs?: number | null
    vectorBootstrapMs?: number | null
    ocrInitMs?: number | null
    vectorBootstrapMode?: string | null
  }
}

export type FolderSelectionResult = {
  addedFolders: IndexedFolder[]
  skippedPaths: string[]
}
