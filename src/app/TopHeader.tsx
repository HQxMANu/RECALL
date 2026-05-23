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
  const scopeOptions: Array<{ value: SearchScope; label: string }> = [
    { value: 'images', label: 'Images' },
    { value: 'voice-notes', label: 'Voice rec' },
    { value: 'documents', label: 'Documents' },
  ]

  const activeScopeLabel =
    scopeOptions.find((option) => option.value === scope)?.label ?? 'Images'

  return (
    <header className="top-header">
      <div className="top-header__search">
        <SearchBar
          query={query}
          disabled={disabled}
          helperText={disabled ? helperText : ''}
          scope={scope}
          showSuggestions={false}
          onQueryChange={onQueryChange}
        />
      </div>

      <div className="top-header__controls">
        <div className="scope-menu">
          <div className="scope-menu__trigger" aria-hidden="true">
            <span>{activeScopeLabel}</span>
            <span className="scope-menu__caret" aria-hidden="true">
              ▾
            </span>
          </div>

          <div className="scope-menu__panel" role="menu" aria-label="Search content type">
            {scopeOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                role="menuitemradio"
                aria-checked={scope === option.value}
                className="scope-menu__item"
                data-active={scope === option.value}
                onClick={() => onScopeChange(option.value)}
              >
                <span>{option.label}</span>
                {scope === option.value ? (
                  <span className="scope-menu__check" aria-hidden="true">
                    •
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
