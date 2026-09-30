const numbers = new Intl.NumberFormat('fr-FR')

export const money = (value: number | null | undefined) => (value == null ? '—' : `${numbers.format(Math.round(value))} FCFA`)
export const num = (value: number | null | undefined) => (value == null ? '—' : numbers.format(value))
export const compact = (value: number) =>
  Math.abs(value) >= 1_000_000 ? `${(value / 1_000_000).toFixed(Math.abs(value) >= 10_000_000 ? 0 : 1)}M` : Math.abs(value) >= 1000 ? `${Math.round(value / 1000)}k` : String(value)
export const percent = (value: number | null | undefined, digits = 0) => (value == null ? '—' : `${(value * 100).toFixed(digits)}%`)

function parse(value: string) {
  return new Date(value.length === 10 ? `${value}T00:00:00` : value)
}

export const date = (value?: string | null) =>
  value ? parse(value).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', ...(value.length > 10 ? { timeZone: 'Africa/Douala' } : {}) }) : '—'
export const dateTime = (value?: string | null) =>
  value ? parse(value).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Africa/Douala' }) : '—'
export const time = (value?: string | null) =>
  value ? parse(value).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Africa/Douala' }) : '—'
export const monthLabel = (period: string) => parse(`${period}-01`).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })
export const label = (value?: string | null) => (value ? value.replace(/_/g, ' ').replace(/^\w/, (letter) => letter.toUpperCase()) : '—')
export const initials = (name: string) =>
  name.replace(/^Dr\.?\s+/i, '').split(/\s+/).map((part) => part[0]).slice(0, 2).join('').toUpperCase()

export const ROLE_LABELS: Record<string, string> = {
  super_admin: 'Platform operator', admin: 'Administrator', instructor: 'Instructor', finance: 'Finance officer',
  hr: 'HR officer', employee: 'Employee', student: 'Student',
}

export const METHOD_LABELS: Record<string, string> = {
  mtn_momo: 'MTN MoMo', orange_money: 'Orange Money', bank_transfer: 'Bank transfer', cash: 'Cash',
}

export function todayISO() {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'Africa/Douala' })
}

export function previousMonth() {
  const [year, month] = todayISO().split('-').map(Number)
  return month === 1 ? `${year - 1}-12` : `${year}-${String(month - 1).padStart(2, '0')}`
}
