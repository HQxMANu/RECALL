import {
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from 'react'

import {
  copyImagePath,
  getAppHealth,
  getIndexingStatus,
  listIndexedFolders,
  openFileLocation,
  removeIndexedFolder,
  searchImages,
  selectFolders,
} from '../lib/tauri'
import type {
  AppHealth,
  IndexedFolder,
  IndexingStatus,
  SearchRequest,
  SearchResponse,
  SearchResult,
} from '../types/contracts'

const SEARCH_LIMIT = 50

const initialStatus: IndexingStatus = {
  state: 'idle',
  activeJobId: null,
  activeJobType: null,
  itemsTotal: 0,
  itemsProcessed: 0,
  queuedJobs: 0,
  lastCompletedAt: null,
  lastError: null,
}

const initialHealth: AppHealth = {
  workerReady: false,
  databaseReady: false,
  textSearchReady: false,
  semanticSearchReady: false,
  coreSearchReady: false,
  coreSearchPhase: 'warming',
  coreSearchMessage: 'Warming semantic + text search together.',
  indexingPhase: 'deferred',
  indexingMessage: 'OCR stays deferred until indexing starts.',
  vectorEngine: 'warming',
  ocrEngine: 'deferred',
  embeddingEngine: 'warming',
  degraded: true,
  message: 'Preparing Recall shell and search services.',
  startupMetrics: {
    coreSearchReadyMs: null,
    embeddingInitMs: null,
    vectorBootstrapMs: null,
    ocrInitMs: null,
    vectorBootstrapMode: null,
  },
}

export function useRecallApp() {
  const [folders, setFolders] = useState<IndexedFolder[]>([])
  const [selectedFolderIds, setSelectedFolderIds] = useState<number[]>([])
  const [status, setStatus] = useState<IndexingStatus>(initialStatus)
  const [health, setHealth] = useState<AppHealth>(initialHealth)
  const [query, setQuery] = useState('')
  const [searchState, setSearchState] = useState<SearchResponse>({
    results: [],
    tookMs: 0,
    totalHits: 0,
    queryDebug: {},
  })
  const [selectedResult, setSelectedResult] = useState<SearchResult | null>(null)
  const [isBootstrapping, setIsBootstrapping] = useState(true)
  const [isSearching, setIsSearching] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const deferredQuery = useDeferredValue(query)
  const shellReady = !isBootstrapping
  const coreSearchReady = shellReady && health.coreSearchReady && health.coreSearchPhase === 'ready'
  const searchDisabledReason = shellReady
    ? health.coreSearchMessage
    : 'Preparing Recall shell.'

  const activeFolderSet = useMemo(
    () => new Set(selectedFolderIds),
    [selectedFolderIds],
  )
  const searchRefreshToken = useMemo(
    () =>
      JSON.stringify({
        lastCompletedAt: status.lastCompletedAt,
        activeJobId: status.activeJobId,
        folders: folders.map((folder) => ({
          id: folder.id,
          imageCount: folder.imageCount,
          lastIndexedAt: folder.lastIndexedAt,
        })),
      }),
    [folders, status.activeJobId, status.lastCompletedAt],
  )

  const refreshShell = async () => {
    try {
      const [nextFolders, nextStatus] = await Promise.all([
        listIndexedFolders(),
        getIndexingStatus(),
      ])

      startTransition(() => {
        setFolders(nextFolders)
        setStatus(nextStatus)
        setErrorMessage(null)
      })
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to refresh app state.')
    } finally {
      setIsBootstrapping(false)
    }
  }

  const refreshHealth = async () => {
    try {
      const nextHealth = await getAppHealth()
      startTransition(() => {
        setHealth(nextHealth)
        setErrorMessage(null)
      })
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to refresh app health.')
    }
  }

  const runSearch = async (request: SearchRequest) => {
    if (!coreSearchReady) {
      return
    }

    setIsSearching(true)
    try {
      const response = await searchImages(request)
      startTransition(() => {
        setSearchState(response)
        setErrorMessage(null)
      })
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Search failed.')
    } finally {
      setIsSearching(false)
    }
  }

  useEffect(() => {
    queueMicrotask(() => {
      void refreshShell()
      void refreshHealth()
    })
    const shellIntervalId = window.setInterval(() => {
      void refreshShell()
    }, 2500)

    return () => window.clearInterval(shellIntervalId)
  }, [])

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      void refreshHealth()
    }, coreSearchReady ? 2500 : 700)

    return () => window.clearInterval(intervalId)
  }, [coreSearchReady])

  useEffect(() => {
    if (!coreSearchReady) {
      return
    }

    const timeoutId = window.setTimeout(() => {
      void runSearch({
        query: deferredQuery.trim(),
        folderIds: selectedFolderIds,
        sort: 'relevance',
        limit: SEARCH_LIMIT,
        offset: 0,
      })
    }, 150)

    return () => window.clearTimeout(timeoutId)
  }, [coreSearchReady, deferredQuery, searchRefreshToken, selectedFolderIds])

  const addFolders = async () => {
    await selectFolders()
    await refreshShell()
  }

  const removeFolder = async (folderId: number) => {
    await removeIndexedFolder(folderId)
    setSelectedFolderIds((current) => current.filter((id) => id !== folderId))
    await refreshShell()
  }

  const toggleFolder = (folderId: number) => {
    setSelectedFolderIds((current) =>
      current.includes(folderId)
        ? current.filter((id) => id !== folderId)
        : [...current, folderId],
    )
  }

  const clearFilters = () => setSelectedFolderIds([])

  const previewResult = (result: SearchResult) => setSelectedResult(result)
  const closePreview = () => setSelectedResult(null)

  return {
    folders,
    activeFolderSet,
    status,
    health,
    shellReady,
    coreSearchReady,
    searchDisabledReason,
    query,
    setQuery,
    results: searchState.results,
    totalHits: searchState.totalHits,
    tookMs: searchState.tookMs,
    queryDebug: searchState.queryDebug,
    selectedResult,
    isBootstrapping,
    isSearching,
    errorMessage,
    addFolders,
    removeFolder,
    toggleFolder,
    clearFilters,
    previewResult,
    closePreview,
    openLocation: openFileLocation,
    copyPath: copyImagePath,
  }
}
