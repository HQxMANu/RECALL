import { SearchBar } from '../features/search/SearchBar'
import { StatusPill } from '../features/status/StatusPill'
import type { AppHealth, IndexingStatus } from '../types/contracts'

export type SearchScope = 'images' | 'voice-notes' | 'documents'

type TopHeaderProps = {
  query: string
  scope: SearchScope
  disabled: boolean
  helperText: string
  onQueryChange: (value: string) => void
  onScopeChange: (scope: SearchScope) => void
  health: AppHealth
  status: IndexingStatus
}

const scopeOptions: Array<{ value: SearchScope; label: string }> = [
  { value: 'images', label: 'Images' },
  { value: 'documents', label: 'Documents' },
  { value: 'voice-notes', label: 'Voice rec' },
]

export function TopHeader({
  query,
  scope,
  disabled,
  helperText,
  onQueryChange,
  onScopeChange,
  health,
  status,
}: TopHeaderProps) {
  const selectedScope = scopeOptions.find((option) => option.value === scope) ?? scopeOptions[0]

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
        <div className="scope-menu">
          <button type="button" className="scope-menu__trigger" aria-haspopup="menu">
            <span>{selectedScope.label}</span>
            <span className="scope-menu__caret" aria-hidden="true">
              v
            </span>
          </button>
          <div className="scope-menu__panel" role="menu">
            {scopeOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                className="scope-menu__item"
                data-active={scope === option.value}
                role="menuitemradio"
                aria-checked={scope === option.value}
                onClick={() => onScopeChange(option.value)}
              >
                <span>{option.label}</span>
                {scope === option.value ? (
                  <span className="scope-menu__check" aria-hidden="true">
                    on
                  </span>
                ) : null}
              </button>
            ))}
          </div>
        </div>
        <StatusPill health={health} status={status} scope={scope} />
      </div>
    </header>
  )
}
