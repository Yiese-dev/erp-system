export function BrandMark({ className = 'brand-mark' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="14" fill="#00695F" />
      <path d="M42 20.5A15 15 0 1 0 42 43.5" fill="none" stroke="#fff" strokeWidth="7" strokeLinecap="round" />
      <circle cx="45" cy="32" r="5" fill="#E0806F" />
    </svg>
  )
}
