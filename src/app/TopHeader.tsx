import { SearchBar } from '../features/search/SearchBar'
import { StatusPill } from '../features/status/StatusPill'
import type { AppHealth, IndexingStatus } from '../types/contracts'

export type SearchScope = 'images' | 'voice-notes' | 'documents'

type TopHeaderProps = {
  query: string
  disabled: boolean
  helperText: string
  scope: SearchScope
  onQueryChange: (value: string) => void
  onScopeChange: (value: SearchScope) => void
  health: AppHealth
  status: IndexingStatus
}

export function TopHeader({
  query,
  disabled,
  helperText,
  scope,
  onQueryChange,
  onScopeChange,
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
        <select
          className="scope-select"
          value={scope}
          onChange={(event) => onScopeChange(event.target.value as SearchScope)}
          aria-label="Search content type"
        >
          <option value="images">Images</option>
          <option value="voice-notes">Voice notes</option>
          <option value="documents">Documents</option>
        </select>

        <StatusPill health={health} status={status} />
      </div>
    </header>
  )
}
