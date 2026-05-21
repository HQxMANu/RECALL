import type {
  AppHealth,
  FolderSelectionResult,
  IndexedFolder,
  IndexingStatus,
  SearchRequest,
  SearchResponse,
  SearchResult,
  SortMode,
} from '../types/contracts'

const SAMPLE_RESULTS: SearchResult[] = [
  {
    assetId: 1,
    assetType: 'image',
    path: 'C:\\Images\\Screenshots\\wifi-password.png',
    filename: 'wifi-password.png',
    thumbnailPath: null,
    previewPath: null,
    modifiedAt: new Date().toISOString(),
    ocrSnippet: 'Wi-Fi password: cedar-lane-guest',
    snippet: 'Wi-Fi password: cedar-lane-guest',
    semanticScore: 0.82,
    textScore: 0.91,
    finalScore: 0.88,
    folderId: 1,
    folderName: 'Screenshots',
    width: 1920,
    height: 1080,
  },
  {
    assetId: 2,
    assetType: 'document',
    path: 'C:\\Docs\\Research\\ai-software-engineering.docx',
    filename: 'ai-software-engineering.docx',
    thumbnailPath: null,
    previewPath: null,
    modifiedAt: new Date(Date.now() - 1000 * 60 * 60 * 6).toISOString(),
    ocrSnippet: null,
    snippet: 'Research project about the capabilities of AI in software engineering workflows.',
    semanticScore: 0.75,
    textScore: 0.74,
    finalScore: 0.74,
    folderId: 2,
    folderName: 'Research',
    pageNumber: 3,
  },
  {
    assetId: 3,
    assetType: 'voice-note',
    path: 'C:\\Audio\\Notes\\sprint-retro.m4a',
    filename: 'sprint-retro.m4a',
    thumbnailPath: null,
    previewPath: null,
    modifiedAt: new Date(Date.now() - 1000 * 60 * 60 * 12).toISOString(),
    ocrSnippet: null,
    snippet: 'Discussion about using AI tools in research and software delivery.',
    semanticScore: 0.69,
    textScore: 0.81,
    finalScore: 0.77,
    folderId: 3,
    folderName: 'Voice notes',
    startMs: 120000,
    endMs: 152000,
    durationMs: 540000,
  },
  {
    assetId: 4,
    assetType: 'image',
    path: 'C:\\Images\\Orders\\amazon-order.jpg',
    filename: 'amazon-order.jpg',
    thumbnailPath: null,
    previewPath: null,
    modifiedAt: new Date(Date.now() - 1000 * 60 * 60 * 6).toISOString(),
    ocrSnippet: 'Amazon order delivered on Tuesday',
    snippet: 'Amazon order delivered on Tuesday',
    semanticScore: 0.75,
    textScore: 0.74,
    finalScore: 0.74,
    folderId: 2,
    folderName: 'Orders',
    width: 1440,
    height: 1080,
  },
  {
    assetId: 5,
    assetType: 'image',
    path: 'C:\\Images\\Photos\\beach-sunset.webp',
    filename: 'beach-sunset.webp',
    thumbnailPath: null,
    previewPath: null,
    modifiedAt: new Date(Date.now() - 1000 * 60 * 60 * 32).toISOString(),
    ocrSnippet: 'No OCR text detected',
    snippet: 'No OCR text detected',
    semanticScore: 0.94,
    textScore: 0.06,
    finalScore: 0.71,
    folderId: 3,
    folderName: 'Photos',
    width: 2048,
    height: 1536,
  },
]

let mockFolders: IndexedFolder[] = [
  {
    id: 1,
    path: 'C:\\Images\\Screenshots',
    displayName: 'Screenshots',
    isActive: true,
    itemCount: 413,
    imageCount: 413,
    documentCount: 0,
    voiceNoteCount: 0,
    lastIndexedAt: new Date().toISOString(),
  },
  {
    id: 2,
    path: 'C:\\Docs\\Research',
    displayName: 'Research',
    isActive: true,
    itemCount: 84,
    imageCount: 12,
    documentCount: 72,
    voiceNoteCount: 0,
    lastIndexedAt: new Date().toISOString(),
  },
  {
    id: 3,
    path: 'C:\\Audio\\Notes',
    displayName: 'Voice notes',
    isActive: true,
    itemCount: 132,
    imageCount: 24,
    documentCount: 0,
    voiceNoteCount: 108,
    lastIndexedAt: new Date().toISOString(),
  },
]

const searchSorters: Record<SortMode, (left: SearchResult, right: SearchResult) => number> = {
  relevance: (left, right) => right.finalScore - left.finalScore,
  newest: (left, right) => right.modifiedAt.localeCompare(left.modifiedAt),
  oldest: (left, right) => left.modifiedAt.localeCompare(right.modifiedAt),
}

const containsAllTerms = (result: SearchResult, query: string) => {
  if (!query) {
    return true
  }

  const haystack = `${result.filename} ${result.ocrSnippet ?? ''} ${result.snippet ?? ''}`.toLowerCase()
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((term) => haystack.includes(term))
}

export const mockApi = {
  async selectFolders(): Promise<FolderSelectionResult> {
    const nextFolder: IndexedFolder = {
      id: mockFolders.length + 1,
      path: `C:\\Images\\Imported\\Batch-${mockFolders.length + 1}`,
      displayName: `Imported ${mockFolders.length + 1}`,
      isActive: true,
      itemCount: 0,
      imageCount: 0,
      documentCount: 0,
      voiceNoteCount: 0,
      lastIndexedAt: null,
    }
    mockFolders = [...mockFolders, nextFolder]
    return { addedFolders: [nextFolder], skippedPaths: [] }
  },

  async listIndexedFolders(): Promise<IndexedFolder[]> {
    return mockFolders
  },

  async removeIndexedFolder(folderId: number): Promise<void> {
    mockFolders = mockFolders.filter((folder) => folder.id !== folderId)
  },

  async getIndexingStatus(): Promise<IndexingStatus> {
    return {
      state: 'indexing',
      activeJobId: 8,
      activeJobType: 'full_index',
      itemsTotal: 1200,
      itemsProcessed: 764,
      queuedJobs: 1,
      lastCompletedAt: new Date(Date.now() - 1000 * 60 * 4).toISOString(),
      lastError: null,
    }
  },

  async searchAssets(request: SearchRequest): Promise<SearchResponse> {
    const filtered = SAMPLE_RESULTS.filter((result) => {
      const folderMatch =
        !request.folderIds?.length || request.folderIds.includes(result.folderId)
      const scopeMatch =
        request.scope === 'images'
          ? result.assetType === 'image'
          : request.scope === 'documents'
            ? result.assetType === 'document'
            : result.assetType === 'voice-note'
      return folderMatch && scopeMatch && containsAllTerms(result, request.query)
    }).sort(searchSorters[request.sort])

    return {
      results: filtered.slice(request.offset, request.offset + request.limit),
      tookMs: 34,
      totalHits: filtered.length,
      queryDebug: {
        mode: 'mock',
        textCandidates: filtered.length,
        semanticCandidates: filtered.length,
      },
    }
  },

  async openFileLocation(): Promise<void> {},
  async openAssetFile(): Promise<void> {},
  async copyAssetPath(): Promise<void> {},

  async getAppHealth(): Promise<AppHealth> {
    return {
      workerReady: true,
      databaseReady: true,
      textSearchReady: true,
      semanticSearchReady: true,
      imageSemanticReady: true,
      textSemanticReady: true,
      imageVectorReady: true,
      textVectorReady: true,
      imageScopeReady: true,
      documentScopeReady: true,
      voiceNoteScopeReady: true,
      coreSearchReady: true,
      coreSearchPhase: 'ready',
      coreSearchMessage: 'Browser preview is treating mock semantic and text search as ready.',
      indexingPhase: 'deferred',
      indexingMessage: 'OCR/indexing services stay deferred in browser preview mode.',
      vectorEngine: 'mock-faiss',
      ocrEngine: 'deferred',
      embeddingEngine: 'mock-openclip',
      degraded: false,
      message: 'Running in browser preview mode with mock data.',
      startupMetrics: {
        coreSearchReadyMs: 0,
        embeddingInitMs: 0,
        vectorBootstrapMs: 0,
        ocrInitMs: null,
        vectorBootstrapMode: 'mock',
      },
    }
  },
}
