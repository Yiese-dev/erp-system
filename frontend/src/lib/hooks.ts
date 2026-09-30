import { useState } from 'react'
import type { ChangeEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { get, messageOf } from './api'
import { useToast } from '../components/ui'

export type R = Record<string, any>
export type Page<T = R> = { items: T[]; total: number; page: number; size: number }

export function useGet<T = R>(path: string | null, refetchInterval?: number | false) {
  return useQuery<T>({ queryKey: [path], queryFn: () => get<T>(path as string), enabled: Boolean(path), refetchInterval })
}

export function useAction<I = void, O = any>(fn: (input: I) => Promise<O>, options: {
  success?: string | ((output: O) => string); invalidate?: string[]; onSuccess?: (output: O) => void; silent?: boolean
} = {}) {
  const client = useQueryClient()
  const toast = useToast()
  return useMutation<O, unknown, I>({
    mutationFn: fn,
    onSuccess: (output) => {
      if (options.invalidate?.length) {
        client.invalidateQueries({ predicate: (query) => typeof query.queryKey[0] === 'string' && options.invalidate!.some((prefix) => (query.queryKey[0] as string).startsWith(prefix)) })
      }
      if (options.success) toast.success(typeof options.success === 'function' ? options.success(output) : options.success)
      options.onSuccess?.(output)
    },
    onError: (error) => { if (!options.silent) toast.error(messageOf(error)) },
  })
}

export function useForm<T extends Record<string, any>>(initial: T) {
  const [values, setValues] = useState<T>(initial)
  const bind = (key: keyof T) => ({
    value: values[key] ?? '',
    onChange: (event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setValues((current) => ({ ...current, [key]: event.target.value })),
  })
  const set = (key: keyof T, value: unknown) => setValues((current) => ({ ...current, [key]: value }))
  return { values, setValues, bind, set, reset: () => setValues(initial) }
}
