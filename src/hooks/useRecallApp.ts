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
  copyAssetPath,
  getAppHealth,
  getIndexingStatus,
  listIndexedFolders,
  openAssetFile,
  openFileLocation,
  removeIndexedFolder,
  searchAssets,
  selectFolders,
} from '../lib/tauri'
import type { SearchScope } from '../app/TopHeader'
import type {
  AppHealth,
  IndexedFolder,
  IndexingStatus,
  SearchRequest,
  SearchResponse,
  SearchResult,
} from '../types/contracts'

const SEARCH_LIMIT = 50
const SEARCH_CACHE_MAX_ENTRIES = 36
const FALLBACK_REFRESH_INTERVAL_MS = 60000

type SearchCacheEntry = {
  response: SearchResponse
}

function buildSearchCacheKey(request: SearchRequest) {
  return JSON.stringify({
    ...request,
    folderIds: [...(request.folderIds ?? [])].sort((left, right) => left - right),
  })
}

function readSearchCache(
  cache: Map<string, SearchCacheEntry>,
  key: string,
) {
  const entry = cache.get(key)
  if (!entry) {
    return null
  }

  // Reinsert on read so the map behaves like a simple LRU cache.
  cache.delete(key)
  cache.set(key, entry)
  return entry.response
}

function writeSearchCache(
  cache: Map<string, SearchCacheEntry>,
  key: string,
  response: SearchResponse,
) {
  if (cache.has(key)) {
    cache.delete(key)
  }

  cache.set(key, { response })

  while (cache.size > SEARCH_CACHE_MAX_ENTRIES) {
    const oldestKey = cache.keys().next().value
    if (!oldestKey) {
      break
    }
    cache.delete(oldestKey)
  }
}

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
  imageSemanticReady: false,
  textSemanticReady: false,
  imageVectorReady: false,
  textVectorReady: false,
  imageScopeReady: false,
  documentScopeReady: false,
  voiceNoteScopeReady: false,
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

export function useRecallApp(scope: SearchScope) {
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
  const [showSearchSkeleton, setShowSearchSkeleton] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const shellRefreshInFlight = useRef(false)
  const healthRefreshInFlight = useRef(false)
  const latestSearchRequestId = useRef(0)
  const activeSearchRequestId = useRef(0)
  const mountedRef = useRef(true)
  const searchCache = useRef(new Map<string, SearchCacheEntry>())
  const previousSearchInputs = useRef<{
    query: string
    scope: SearchScope
    folderKey: string
    refreshToken: string
  } | null>(null)

  const deferredQuery = useDeferredValue(query)
  const shellReady = !isBootstrapping
  const scopeSearchReady =
    scope === 'documents'
      ? health.documentScopeReady
      : scope === 'voice-notes'
        ? health.voiceNoteScopeReady
        : health.imageScopeReady
  const coreSearchReady = shellReady && scopeSearchReady
  const searchDisabledReason = !shellReady
    ? 'Preparing Recall shell.'
    : scope === 'documents'
      ? 'Warming local document search before enabling search.'
      : scope === 'voice-notes'
        ? 'Warming local voice-note search before enabling search.'
        : 'Warming local image search before enabling search.'

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
          itemCount: folder.itemCount,
          imageCount: folder.imageCount,
          documentCount: folder.documentCount,
          voiceNoteCount: folder.voiceNoteCount,
          lastIndexedAt: folder.lastIndexedAt,
        })),
      }),
    [folders, status.activeJobId, status.lastCompletedAt],
  )

  useEffect(() => {
    searchCache.current.clear()
  }, [searchRefreshToken])

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

    const cacheKey = buildSearchCacheKey(request)
    const cachedResponse = readSearchCache(searchCache.current, cacheKey)

    const requestId = latestSearchRequestId.current + 1
    latestSearchRequestId.current = requestId
    activeSearchRequestId.current = requestId
    if (cachedResponse) {
      startTransition(() => {
        setSearchState(cachedResponse)
        setShowSearchSkeleton(false)
      })
    } else {
      startTransition(() => {
        setSearchState({
          results: [],
          tookMs: 0,
          totalHits: 0,
          queryDebug: {},
        })
        setShowSearchSkeleton(true)
      })
    }
    setIsSearching(true)
    try {
      const response = await searchAssets(request)
      writeSearchCache(searchCache.current, cacheKey, response)
      if (mountedRef.current && requestId === latestSearchRequestId.current) {
        startTransition(() => {
          setSearchState(response)
          setShowSearchSkeleton(false)
          setErrorMessage(null)
        })
      }
    } catch (error) {
      if (mountedRef.current && requestId === latestSearchRequestId.current) {
        setShowSearchSkeleton(false)
        setErrorMessage(error instanceof Error ? error.message : 'Search failed.')
      }
    } finally {
      if (mountedRef.current && requestId === activeSearchRequestId.current) {
        setIsSearching(false)
        setShowSearchSkeleton(false)
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
    let fallbackIntervalId: number | null = null

    const startFallbackRefresh = () => {
      if (fallbackIntervalId !== null) {
        return
      }
      fallbackIntervalId = window.setInterval(() => {
        void refreshShell()
        void refreshHealth()
      }, FALLBACK_REFRESH_INTERVAL_MS)
    }

    const registerListeners = async () => {
      if (!isTauri()) {
        startFallbackRefresh()
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
        startFallbackRefresh()
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

    return () => {
      cancelled = true
      mountedRef.current = false
      if (fallbackIntervalId !== null) {
        window.clearInterval(fallbackIntervalId)
      }
      for (const unlisten of unlisteners) {
        unlisten()
      }
    }
  }, [])

  useEffect(() => {
    if (!coreSearchReady) {
      return
    }

    const nextQuery = deferredQuery.trim()
    const folderKey = JSON.stringify(selectedFolderIds)
    const previous = previousSearchInputs.current
    const request: SearchRequest = {
      query: nextQuery,
      scope,
      folderIds: selectedFolderIds,
      sort: 'relevance',
      limit: SEARCH_LIMIT,
      offset: 0,
    }

    const shouldSearchImmediately =
      !previous ||
      previous.scope !== scope ||
      previous.folderKey !== folderKey ||
      previous.refreshToken !== searchRefreshToken

    previousSearchInputs.current = {
      query: nextQuery,
      scope,
      folderKey,
      refreshToken: searchRefreshToken,
    }

    if (shouldSearchImmediately) {
      void runSearch(request)
      return
    }

    const timeoutId = window.setTimeout(() => {
      void runSearch(request)
    }, 150)

    return () => window.clearTimeout(timeoutId)
  }, [coreSearchReady, deferredQuery, scope, searchRefreshToken, selectedFolderIds])

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
    showSearchSkeleton,
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
    openFile: openAssetFile,
    copyPath: copyAssetPath,
  }
}
