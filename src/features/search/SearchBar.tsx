type SearchBarProps = {
  query: string
  disabled: boolean
  helperText: string
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
  showSuggestions = true,
  onQueryChange,
}: SearchBarProps) {
  return (
    <div className="search-stack">
      <input
        className="search-input"
        value={query}
        disabled={disabled}
        onChange={(event) => onQueryChange(event.target.value)}
        placeholder={
          disabled
            ? 'Warming semantic + text search before enabling search'
            : 'Search screenshots and images in plain English'
        }
        aria-label="Search indexed images"
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
