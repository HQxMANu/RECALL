import {
  useEffectEvent,
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
import { isTauri } from '@tauri-apps/api/core'

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
  const shellRefreshInFlight = useRef(false)
  const healthRefreshInFlight = useRef(false)
  const latestSearchRequestId = useRef(0)
  const activeSearchRequestId = useRef(0)
  const mountedRef = useRef(true)

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
    if (shellRefreshInFlight.current) {
      return
    }
    shellRefreshInFlight.current = true
    try {
      const [nextFolders, nextStatus] = await Promise.all([
        listIndexedFolders(),
        getIndexingStatus(),
      ])

      if (mountedRef.current) {
        startTransition(() => {
          setFolders(nextFolders)
          setStatus(nextStatus)
          setErrorMessage(null)
        })
      }
    } catch (error) {
      if (mountedRef.current) {
        setErrorMessage(error instanceof Error ? error.message : 'Failed to refresh app state.')
      }
    } finally {
      shellRefreshInFlight.current = false
      if (mountedRef.current) {
        setIsBootstrapping(false)
      }
    }
  }

  const refreshHealth = async () => {
    if (healthRefreshInFlight.current) {
      return
    }
    healthRefreshInFlight.current = true
    try {
      const nextHealth = await getAppHealth()
      if (mountedRef.current) {
        startTransition(() => {
          setHealth(nextHealth)
          setErrorMessage(null)
        })
      }
    } catch (error) {
      if (mountedRef.current) {
        setErrorMessage(error instanceof Error ? error.message : 'Failed to refresh app health.')
      }
    } finally {
      healthRefreshInFlight.current = false
    }
  }

  const runSearch = useEffectEvent(async (request: SearchRequest) => {
    if (!coreSearchReady) {
      return
    }

    const requestId = latestSearchRequestId.current + 1
    latestSearchRequestId.current = requestId
    activeSearchRequestId.current = requestId
    setIsSearching(true)
    try {
      const response = await searchImages(request)
      if (mountedRef.current && requestId === latestSearchRequestId.current) {
        startTransition(() => {
          setSearchState(response)
          setErrorMessage(null)
        })
      }
    } catch (error) {
      if (mountedRef.current && requestId === latestSearchRequestId.current) {
        setErrorMessage(error instanceof Error ? error.message : 'Search failed.')
      }
    } finally {
      if (mountedRef.current && requestId === activeSearchRequestId.current) {
        setIsSearching(false)
      }
    }
  })

  useEffect(() => {
    mountedRef.current = true
    queueMicrotask(() => {
      void refreshShell()
      void refreshHealth()
    })

    let unlisteners: UnlistenFn[] = []
    let cancelled = false

    const registerListeners = async () => {
      if (!isTauri()) {
        return
      }

      try {
        const nextUnlisteners = await Promise.all([
          listen<IndexedFolder[]>('recall://folders-changed', (event) => {
            if (!mountedRef.current) {
              return
            }
            startTransition(() => {
              setFolders(event.payload)
              setErrorMessage(null)
            })
          }),
          listen<IndexingStatus>('recall://indexing-status', (event) => {
            if (!mountedRef.current) {
              return
            }
            startTransition(() => {
              setStatus(event.payload)
              setErrorMessage(null)
              setIsBootstrapping(false)
            })
          }),
          listen<AppHealth>('recall://health', (event) => {
            if (!mountedRef.current) {
              return
            }
            startTransition(() => {
              setHealth(event.payload)
              setErrorMessage(null)
            })
          }),
        ])
        if (cancelled) {
          for (const unlisten of nextUnlisteners) {
            unlisten()
          }
          return
        }
        unlisteners = nextUnlisteners
      } catch (error) {
        if (!cancelled && mountedRef.current) {
          setErrorMessage(
            error instanceof Error
              ? error.message
              : 'Failed to subscribe to Recall status updates.',
          )
        }
      }
    }

    void registerListeners()

    const fallbackIntervalId = window.setInterval(() => {
      void refreshShell()
      void refreshHealth()
    }, 15000)

    return () => {
      cancelled = true
      mountedRef.current = false
      window.clearInterval(fallbackIntervalId)
      for (const unlisten of unlisteners) {
        unlisten()
      }
    }
  }, [])

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
