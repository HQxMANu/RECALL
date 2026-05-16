import type { ReactNode } from 'react'

export type WorkspaceView = 'search' | 'folders'

type LeftNavRailProps = {
  activeView: WorkspaceView
  onChangeView: (view: WorkspaceView) => void
}

type NavItem = {
  id: WorkspaceView
  label: string
  icon: ReactNode
}

const NAV_ITEMS: NavItem[] = [
  {
    id: 'search',
    label: 'Search',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M10.5 4.5a6 6 0 1 0 0 12a6 6 0 0 0 0-12Zm0-2a8 8 0 1 1 4.97 14.27l4.13 4.13l-1.41 1.41l-4.13-4.13A8 8 0 0 1 10.5 2.5Z"
          fill="currentColor"
        />
      </svg>
    ),
  },
  {
    id: 'folders',
    label: 'Indexed folders',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M3 6.5A2.5 2.5 0 0 1 5.5 4h4.2l1.5 1.7h7.3A2.5 2.5 0 0 1 21 8.2v9.3A2.5 2.5 0 0 1 18.5 20h-13A2.5 2.5 0 0 1 3 17.5v-11ZM5.5 6A.5.5 0 0 0 5 6.5v1h14v-.3a.5.5 0 0 0-.5-.5h-8.2L8.8 5H5.5Zm13 3.5H5v8a.5.5 0 0 0 .5.5h13a.5.5 0 0 0 .5-.5v-8Z"
          fill="currentColor"
        />
      </svg>
    ),
  },
]

export function LeftNavRail({ activeView, onChangeView }: LeftNavRailProps) {
  return (
    <aside className="nav-rail" aria-label="Primary navigation">
      <button
        type="button"
        className="nav-rail__brand"
        onClick={() => onChangeView('search')}
        aria-label="Go to search"
      >
        <span className="nav-rail__brand-ring" />
        <span className="nav-rail__brand-mark">R</span>
      </button>

      <nav className="nav-rail__nav">
        {NAV_ITEMS.map((item) => {
          const isActive = item.id === activeView
          return (
            <button
              key={item.id}
              type="button"
              className="nav-rail__button"
              data-active={isActive}
              aria-current={isActive ? 'page' : undefined}
              aria-label={item.label}
              title={item.label}
              onClick={() => onChangeView(item.id)}
            >
              {item.icon}
              <span>{item.label}</span>
            </button>
          )
        })}
      </nav>
    </aside>
  )
}
