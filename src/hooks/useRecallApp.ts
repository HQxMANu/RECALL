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
  clearAssetPreviewCache,
  getAppHealth,
  getIndexingStatus,
  listIndexedFolders,
  openAssetFile,
  openFileLocation,
  rebuildIndex,
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
  issueCount: 0,
  recentIssues: [],
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
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [hasMoreResults, setHasMoreResults] = useState(false)
  const [showSearchSkeleton, setShowSearchSkeleton] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const shellRefreshInFlight = useRef(false)
  const healthRefreshInFlight = useRef(false)
  const latestSearchRequestId = useRef(0)
  const activeSearchRequestId = useRef(0)
  const loadMoreInFlight = useRef(false)
  const mountedRef = useRef(true)
  const searchCache = useRef(new Map<string, SearchCacheEntry>())
  const currentSearchRequest = useRef<SearchRequest | null>(null)
  const completedFirstPageCacheKey = useRef<string | null>(null)
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
        ? 'Warming local voice rec search before enabling search.'
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
    clearAssetPreviewCache()
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

  const mergeSearchResponses = (current: SearchResponse, next: SearchResponse): SearchResponse => {
    const seenAssetIds = new Set<number>()
    const results = [...current.results, ...next.results].filter((result) => {
      if (seenAssetIds.has(result.assetId)) {
        return false
      }
      seenAssetIds.add(result.assetId)
      return true
    })

    return {
      ...next,
      results,
      totalHits: Math.max(next.totalHits, results.length),
    }
  }

  const canRequestMore = (
    response: SearchResponse,
    visibleResultCount: number,
    request: SearchRequest,
  ) => {
    const limit = request.limit ?? SEARCH_LIMIT
    if (response.totalHits > visibleResultCount) {
      return true
    }
    return response.results.length >= limit
  }

  const runSearch = useEffectEvent(async (request: SearchRequest, append = false) => {
    if (!coreSearchReady) {
      return
    }

    const cacheKey = buildSearchCacheKey(request)
    const cachedResponse = readSearchCache(searchCache.current, cacheKey)

    const requestId = latestSearchRequestId.current + 1
    latestSearchRequestId.current = requestId
    if (!append) {
      activeSearchRequestId.current = requestId
      completedFirstPageCacheKey.current = null
    }
    if (cachedResponse) {
      const nextState = append
        ? mergeSearchResponses(searchState, cachedResponse)
        : cachedResponse
      startTransition(() => {
        setSearchState(nextState)
        setHasMoreResults(canRequestMore(cachedResponse, nextState.results.length, request))
        setShowSearchSkeleton(false)
      })
      if (!append) {
        completedFirstPageCacheKey.current = cacheKey
      }
      if (append) {
        setIsLoadingMore(false)
        loadMoreInFlight.current = false
        return
      }
    } else if (!append) {
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
    if (append) {
      setIsLoadingMore(true)
    } else {
      setIsSearching(true)
      setHasMoreResults(false)
    }
    try {
      const response = await searchAssets(request)
      writeSearchCache(searchCache.current, cacheKey, response)
      if (mountedRef.current && requestId === latestSearchRequestId.current) {
        const nextState = append ? mergeSearchResponses(searchState, response) : response
        startTransition(() => {
          setSearchState(nextState)
          setHasMoreResults(canRequestMore(response, nextState.results.length, request))
          setShowSearchSkeleton(false)
          setErrorMessage(null)
        })
        if (!append) {
          completedFirstPageCacheKey.current = cacheKey
        }
      }
    } catch (error) {
      if (mountedRef.current && requestId === latestSearchRequestId.current) {
        setShowSearchSkeleton(false)
        setErrorMessage(error instanceof Error ? error.message : 'Search failed.')
      }
    } finally {
      if (append) {
        if (mountedRef.current) {
          setIsLoadingMore(false)
        }
        loadMoreInFlight.current = false
      } else if (mountedRef.current && requestId === activeSearchRequestId.current) {
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
    currentSearchRequest.current = request

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

  const loadMoreResults = async () => {
    if (!coreSearchReady || isSearching || isLoadingMore || loadMoreInFlight.current || !hasMoreResults) {
      return
    }
    if (searchState.results.length < SEARCH_LIMIT) {
      return
    }

    const baseRequest = currentSearchRequest.current
    if (!baseRequest) {
      return
    }

    const baseCacheKey = buildSearchCacheKey({ ...baseRequest, offset: 0 })
    if (completedFirstPageCacheKey.current !== baseCacheKey) {
      return
    }

    loadMoreInFlight.current = true
    const nextRequest: SearchRequest = {
      ...baseRequest,
      offset: searchState.results.length,
      limit: SEARCH_LIMIT,
    }
    const cacheKey = buildSearchCacheKey(nextRequest)
    const cachedResponse = readSearchCache(searchCache.current, cacheKey)

    setIsLoadingMore(true)
    try {
      const response = cachedResponse ?? await searchAssets(nextRequest)
      if (!cachedResponse) {
        writeSearchCache(searchCache.current, cacheKey, response)
      }
      if (!mountedRef.current || completedFirstPageCacheKey.current !== baseCacheKey) {
        return
      }

      const nextState = mergeSearchResponses(searchState, response)
      startTransition(() => {
        setSearchState(nextState)
        setHasMoreResults(canRequestMore(response, nextState.results.length, nextRequest))
        setErrorMessage(null)
      })
    } catch (error) {
      if (mountedRef.current && completedFirstPageCacheKey.current === baseCacheKey) {
        setErrorMessage(error instanceof Error ? error.message : 'Failed to load more results.')
      }
    } finally {
      loadMoreInFlight.current = false
      if (mountedRef.current) {
        setIsLoadingMore(false)
      }
    }
  }

  const addFolders = async () => {
    await selectFolders()
    await refreshShell()
  }

  const removeFolder = async (folderId: number) => {
    await removeIndexedFolder(folderId)
    setSelectedFolderIds((current) => current.filter((id) => id !== folderId))
    await refreshShell()
  }

  const rebuildAll = async () => {
    await rebuildIndex()
    await refreshShell()
    await refreshHealth()
  }

  const rebuildFolder = async (folderId: number) => {
    await rebuildIndex([folderId])
    await refreshShell()
    await refreshHealth()
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
    isLoadingMore,
    hasMoreResults,
    errorMessage,
    loadMoreResults,
    addFolders,
    removeFolder,
    rebuildAll,
    rebuildFolder,
    toggleFolder,
    clearFilters,
    previewResult,
    closePreview,
    openLocation: openFileLocation,
    openFile: openAssetFile,
  }
}
