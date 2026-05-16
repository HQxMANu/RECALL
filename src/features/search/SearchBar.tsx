type SearchBarProps = {
  query: string
  disabled: boolean
  helperText: string
  onQueryChange: (value: string) => void
}

const SUGGESTIONS = [
  'wifi password screenshot',
  'amazon order',
  'discord message about server IP',
  'beach sunset photo',
]

export function SearchBar({ query, disabled, helperText, onQueryChange }: SearchBarProps) {
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
      <p className="results-subtitle">{helperText}</p>
    </div>
  )
}
