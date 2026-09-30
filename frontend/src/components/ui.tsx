import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from 'react'
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { ChevronLeft, ChevronRight, CircleCheck, CircleX, Download, Inbox, LoaderCircle, Search, TriangleAlert, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { download, messageOf } from '../lib/api'
import { label as humanize } from '../lib/format'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

export function Button({ variant = 'primary', icon: Icon, busy, small, children, className = '', ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; icon?: LucideIcon; busy?: boolean; small?: boolean }) {
  return (
    <button type="button" {...props} className={`btn btn-${variant} ${small ? 'btn-sm' : ''} ${className}`} disabled={busy || props.disabled}>
      {busy ? <LoaderCircle className="spin" size={16} aria-hidden /> : Icon ? <Icon size={16} aria-hidden /> : null}
      {children && <span>{children}</span>}
    </button>
  )
}

export function IconButton({ label, icon: Icon, badge, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; icon: LucideIcon; badge?: number }) {
  return (
    <button type="button" className="icon-btn" aria-label={label} title={label} {...props}>
      <Icon size={18} aria-hidden />
      {badge ? <span className="dot">{badge > 9 ? '9+' : badge}</span> : null}
    </button>
  )
}

export function Field({ label, hint, error, wide, children }: { label: string; hint?: string; error?: string; wide?: boolean; children: ReactNode }) {
  return (
    <label className={`field ${wide ? 'field-wide' : ''}`}>
      <span className="field-label">{label}</span>
      {children}
      {error ? <span className="field-error" role="alert">{error}</span> : hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  )
}

export const Input = (props: InputHTMLAttributes<HTMLInputElement>) => <input className="input" {...props} />
export const Textarea = (props: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea className="textarea" {...props} />

export function Select({ options, placeholder, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { options: { value: string; label: string }[]; placeholder?: string }) {
  return (
    <select className="select" {...props}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
  )
}

export function SearchBox({ value, onChange, placeholder = 'Search' }: { value: string; onChange: (value: string) => void; placeholder?: string }) {
  return (
    <div className="search">
      <Search size={16} aria-hidden />
      <input className="input" type="search" value={value} placeholder={placeholder} aria-label={placeholder} onChange={(event) => onChange(event.target.value)} />
    </div>
  )
}

const TONES: Record<string, string> = {
  active: 'green', paid: 'green', approved: 'green', succeeded: 'green', published: 'green', completed: 'green', present: 'green',
  on_track: 'green', hired: 'green', converted: 'green', available: 'green', finalized: 'green', resolved: 'green', sent: 'green',
  ready: 'green', ok: 'green', confirmed: 'green', settled: 'green', good: 'green', enrolled: 'green',
  invoiced: 'blue', issued: 'blue', open: 'blue', interview: 'blue', screened: 'blue', contacted: 'blue', qualified: 'blue',
  assigned: 'blue', on_leave: 'blue', check_out: 'blue',
  under_review: 'amber', pending: 'amber', submitted: 'amber', partially_paid: 'amber', offered: 'amber', maintenance: 'amber',
  late: 'amber', fair: 'amber', check_in: 'teal',
  rejected: 'coral', failed: 'coral', expired: 'coral', lost: 'coral', absent: 'coral', at_risk: 'coral', overdue: 'coral',
  issue: 'coral', suspended: 'coral', down: 'coral', poor: 'coral',
}

export function Badge({ status, children, tone }: { status?: string; children?: ReactNode; tone?: string }) {
  const key = status ?? ''
  return <span className={`badge badge-${tone ?? TONES[key] ?? 'gray'}`}>{children ?? humanize(key)}</span>
}

export type Kpi = { label: string; value: ReactNode; hint?: ReactNode; tone?: 'teal' | 'coral' | 'blue' | 'amber' | 'green' | 'gray'; icon?: LucideIcon }

export function Kpis({ items }: { items: Kpi[] }) {
  return (
    <div className="kpis">
      {items.map((item) => (
        <div key={item.label} className={`kpi tone-${item.tone ?? 'teal'}`}>
          <span className="kpi-label">{item.icon && <item.icon size={14} aria-hidden />}{item.label}</span>
          <strong className="kpi-value">{item.value}</strong>
          {item.hint && <span className="kpi-hint">{item.hint}</span>}
        </div>
      ))}
    </div>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  )
}

export function Panel({ title, subtitle, actions, children, flush, note }: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; flush?: boolean; note?: ReactNode }) {
  return (
    <section className="panel">
      {(title || actions) && (
        <div className="panel-header">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {actions && <div className="panel-actions">{actions}</div>}
        </div>
      )}
      <div className={`panel-body ${flush ? 'flush' : ''}`}>{children}</div>
      {note && <div className="panel-note">{note}</div>}
    </section>
  )
}

export function Loading({ rows = 4 }: { rows?: number }) {
  return (
    <div className="loading" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, index) => <div key={index} className="skeleton" style={{ width: `${92 - index * 9}%` }} />)}
    </div>
  )
}

export function Empty({ title = 'Nothing here yet', text, icon: Icon = Inbox, action }: { title?: string; text?: string; icon?: LucideIcon; action?: ReactNode }) {
  return (
    <div className="empty">
      <Icon size={28} aria-hidden />
      <strong>{title}</strong>
      {text && <span>{text}</span>}
      {action}
    </div>
  )
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div style={{ padding: 16 }}>
      <div className="error-box" role="alert">
        <TriangleAlert size={18} aria-hidden />
        <div className="grow">
          <div>{messageOf(error)}</div>
          {retry && <Button variant="ghost" small onClick={retry}>Try again</Button>}
        </div>
      </div>
    </div>
  )
}

type Row = Record<string, any>
export type Column<T = Row> = { key: string; header: string; render?: (row: T) => ReactNode; align?: 'left' | 'right' | 'center'; mono?: boolean; width?: string }

export function DataTable({ columns, rows, rowKey, onRowClick, empty, loading, error, retry, footer }: {
  columns: Column<Row>[]; rows: Row[] | undefined; rowKey: (row: Row) => string; onRowClick?: (row: Row) => void; empty?: ReactNode
  loading?: boolean; error?: unknown; retry?: () => void; footer?: ReactNode
}) {
  if (error) return <ErrorState error={error} retry={retry} />
  if (loading || !rows) return <Loading />
  if (!rows.length) return typeof empty === 'string' || !empty ? <Empty text={(empty as string) || 'No records match these filters.'} /> : <>{empty}</>
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>{columns.map((column) => <th key={column.key} style={{ textAlign: column.align, width: column.width }}>{column.header}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className={onRowClick ? 'clickable' : undefined} tabIndex={onRowClick ? 0 : undefined}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              onKeyDown={onRowClick ? (event) => { if (event.key === 'Enter') onRowClick(row) } : undefined}>
              {columns.map((column) => (
                <td key={column.key} className={column.mono ? 'mono' : undefined} style={{ textAlign: column.align }}>
                  {column.render ? column.render(row) : String(row[column.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {footer}
      </table>
    </div>
  )
}

export function Pager({ page, size, total, onPage }: { page: number; size: number; total: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size))
  if (total <= size) return null
  return (
    <div className="pager">
      <span>{(page - 1) * size + 1}–{Math.min(page * size, total)} of {total}</span>
      <div className="row">
        <IconButton label="Previous page" icon={ChevronLeft} disabled={page <= 1} onClick={() => onPage(page - 1)} />
        <span>Page {page} of {pages}</span>
        <IconButton label="Next page" icon={ChevronRight} disabled={page >= pages} onClick={() => onPage(page + 1)} />
      </div>
    </div>
  )
}

export function Tabs<T extends string>({ value, onChange, items, label }: { value: T; onChange: (value: T) => void; items: { value: T; label: string; count?: number }[]; label?: string }) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {items.map((item) => (
        <button key={item.value} type="button" role="tab" aria-selected={value === item.value} className={value === item.value ? 'active' : ''} onClick={() => onChange(item.value)}>
          {item.label}
          {item.count != null && <span className="count">{item.count}</span>}
        </button>
      ))}
    </div>
  )
}

export function Modal({ open, title, onClose, children, footer, size = 'md' }: { open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; size?: 'md' | 'lg' }) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])
  return (
    <dialog ref={ref} className={`modal modal-${size}`} aria-labelledby={titleId} onCancel={(event) => { event.preventDefault(); onClose() }}>
      {open && (
        <div className="modal-inner">
          <header className="modal-header">
            <h2 id={titleId}>{title}</h2>
            <IconButton label="Close" icon={X} onClick={onClose} />
          </header>
          <div className="modal-body">{children}</div>
          {footer && <footer className="modal-footer">{footer}</footer>}
        </div>
      )}
    </dialog>
  )
}

type Toast = { id: number; kind: 'success' | 'error'; text: string }
const ToastContext = createContext<{ success: (text: string) => void; error: (text: string) => void }>({ success: () => {}, error: () => {} })

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const push = useCallback((kind: Toast['kind'], text: string) => {
    const id = Date.now() + Math.random()
    setToasts((items) => [...items.slice(-3), { id, kind, text }])
    setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), kind === 'error' ? 7000 : 4500)
  }, [])
  const value = useMemo(() => ({ success: (text: string) => push('success', text), error: (text: string) => push('error', text) }), [push])
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast ${toast.kind}`} role={toast.kind === 'error' ? 'alert' : 'status'}>
            {toast.kind === 'success' ? <CircleCheck size={18} aria-hidden /> : <CircleX size={18} aria-hidden />}
            <span>{toast.text}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)

export function DownloadButton({ path, filename, children = 'PDF', variant = 'secondary', small = true }: { path: string; filename: string; children?: ReactNode; variant?: Variant; small?: boolean }) {
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  return (
    <Button variant={variant} small={small} icon={Download} busy={busy} onClick={async (event) => {
      event.stopPropagation()
      setBusy(true)
      try {
        await download(path, filename)
      } catch (error) {
        toast.error(messageOf(error))
      } finally {
        setBusy(false)
      }
    }}>{children}</Button>
  )
}

export function Meter({ value, warn }: { value: number | null | undefined; warn?: boolean }) {
  const width = Math.max(0, Math.min(100, (value ?? 0) * 100))
  return <div className={`meter ${warn ? 'warn' : ''}`} role="img" aria-label={`${Math.round(width)}%`}><span style={{ width: `${width}%` }} /></div>
}

export function Stars({ rating }: { rating: number | null | undefined }) {
  if (!rating) return <span className="muted">—</span>
  return <span className="stars" aria-label={`${rating} out of 5`}>{'★'.repeat(rating)}<span style={{ color: '#d6dcda' }}>{'★'.repeat(5 - rating)}</span></span>
}
