export type NavIconName =
  | 'dashboard'
  | 'live-call'
  | 'ai-improvement'
  | 'administration'
  | 'escalations'
  | 'complaints'
  | 'menu'
  | 'collapse-panel'
  | 'close'

const PATHS: Record<NavIconName, string[]> = {
  dashboard: ['M4 4h7v7H4z', 'M13 4h7v4h-7z', 'M13 10h7v10h-7z', 'M4 13h7v7H4z'],
  'live-call': [
    'M6.6 10.8a15.1 15.1 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.25 11.4 11.4 0 0 0 3.6.57 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.57a1 1 0 0 1-.25 1z',
  ],
  'ai-improvement': [
    'M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9z',
    'M19 15l.8 1.9 1.9.8-1.9.8L19 20.5l-.8-1.9-1.9-.8 1.9-.8z',
  ],
  administration: [
    'M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6z',
    'M9.5 12l1.8 1.8 3.4-3.6',
  ],
  escalations: ['M12 4l9 16H3z', 'M12 10v4', 'M12 17.5v.5'],
  complaints: ['M4 5h16v11H9l-5 4z', 'M8.5 9.5h7', 'M8.5 12.5h4'],
  menu: ['M4 6h16', 'M4 12h16', 'M4 18h16'],
  // A side panel with an arrow pointing into it: "fold the panel away".
  'collapse-panel': [
    'M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z',
    'M9 4v16',
    'M16 9l-3 3 3 3',
  ],
  close: ['M6 6l12 12', 'M18 6L6 18'],
}

export function NavIcon({ name }: { name: NavIconName }) {
  return (
    <svg
      className="nav-icon"
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  )
}
