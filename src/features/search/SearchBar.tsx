type SearchBarProps = {
  query: string
  disabled: boolean
  helperText: string
  scope?: 'images' | 'documents' | 'voice-notes'
  showSuggestions?: boolean
  onQueryChange: (value: string) => void
}

const SUGGESTIONS = [
  'wifi password screenshot',
  'amazon order',
  'discord message about server IP',
  'beach sunset photo',
]

export function SearchBar({
  query,
  disabled,
  helperText,
  scope = 'images',
  showSuggestions = true,
  onQueryChange,
}: SearchBarProps) {
  const enabledPlaceholder =
    scope === 'documents'
      ? 'Search documents in plain English'
      : scope === 'voice-notes'
        ? 'Search voice rec in plain English'
        : 'Search screenshots and images in plain English'
  const disabledPlaceholder =
    scope === 'documents'
      ? 'Warming local document search before enabling search'
      : scope === 'voice-notes'
        ? 'Warming local voice rec search before enabling search'
        : 'Warming local image search before enabling search'

  return (
    <div className="search-stack">
      <input
        className="search-input"
        value={query}
        disabled={disabled}
        onChange={(event) => onQueryChange(event.target.value)}
        placeholder={
          disabled ? disabledPlaceholder : enabledPlaceholder
        }
        aria-label={`Search indexed ${scope}`}
        autoFocus={!disabled}
      />
      {showSuggestions ? (
        <div className="query-suggestions" aria-label="Example searches">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              className="query-chip"
              disabled={disabled}
              onClick={() => onQueryChange(suggestion)}
            >
              {suggestion}
            </button>
          ))}
        </div>
      ) : null}
      {helperText ? <p className="search-helper">{helperText}</p> : null}
    </div>
  )
}
