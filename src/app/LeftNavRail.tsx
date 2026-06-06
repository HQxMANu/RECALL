import recallLogo from '../assets/recall-logo.png'

export type AppView = 'search' | 'folders'

type LeftNavRailProps = {
  activeView: AppView
  onViewChange: (view: AppView) => void
}

export function LeftNavRail({ activeView, onViewChange }: LeftNavRailProps) {
  return (
    <aside className="nav-rail" aria-label="Recall">
      <div className="nav-rail__brand" aria-hidden="true">
        <img className="nav-rail__brand-logo" src={recallLogo} alt="" />
      </div>

      <nav className="nav-rail__nav" aria-label="Primary">
        <button
          type="button"
          className="nav-rail__button"
          data-active={activeView === 'search'}
          aria-pressed={activeView === 'search'}
          title="Search"
          onClick={() => onViewChange('search')}
        >
          <SearchIcon />
          <span>Search</span>
        </button>
        <button
          type="button"
          className="nav-rail__button"
          data-active={activeView === 'folders'}
          aria-pressed={activeView === 'folders'}
          title="Folders"
          onClick={() => onViewChange('folders')}
        >
          <FolderIcon />
          <span>Folders</span>
        </button>
      </nav>
    </aside>
  )
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="11" cy="11" r="6" fill="none" stroke="currentColor" strokeWidth="2" />
      <path d="m16 16 4 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

function FolderIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M4 6.5h6l1.6 2H20v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
    </svg>
  )
}
