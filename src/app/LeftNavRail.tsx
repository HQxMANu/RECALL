import recallLogo from '../assets/recall-logo.png'

export function LeftNavRail() {
  return (
    <aside className="nav-rail" aria-label="Recall">
      <div className="nav-rail__brand" aria-hidden="true">
        <img className="nav-rail__brand-logo" src={recallLogo} alt="" />
      </div>
    </aside>
  )
}
