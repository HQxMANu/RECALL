import { SearchBar } from '../features/search/SearchBar'
import { StatusPill } from '../features/status/StatusPill'
import type { AppHealth, IndexingStatus } from '../types/contracts'

export type SearchScope = 'images' | 'voice-notes' | 'documents'

type TopHeaderProps = {
  query: string
  disabled: boolean
  helperText: string
  onQueryChange: (value: string) => void
  health: AppHealth
  status: IndexingStatus
}

export function TopHeader({
  query,
  disabled,
  helperText,
  onQueryChange,
  health,
  status,
}: TopHeaderProps) {
  return (
    <header className="top-header">
      <div className="top-header__search">
        <SearchBar
          query={query}
          disabled={disabled}
          helperText={disabled ? helperText : ''}
          showSuggestions={false}
          onQueryChange={onQueryChange}
        />
      </div>

      <div className="top-header__controls">
        <StatusPill health={health} status={status} scope="images" />
      </div>
    </header>
  )
}
