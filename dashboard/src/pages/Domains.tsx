// F19: describe a domain -> review every label decision -> confirm -> it is live in the arena.
import { useMutation } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { type DraftOut, domains } from '../api/arena.ts'
import { ApiError } from '../api/client.ts'

export default function Domains() {
  const [description, setDescription] = useState('')
  const [draft, setDraft] = useState<DraftOut | null>(null)
  const generate = useMutation({ mutationFn: domains.generate, onSuccess: setDraft })
  const confirm = useMutation({ mutationFn: domains.confirm, onSuccess: setDraft })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setDraft(null)
    generate.mutate(description)
  }
  const error = generate.error ?? confirm.error
  return (
    <section className="flex max-w-4xl flex-col gap-4">
      <h1 className="text-2xl font-semibold">Bring your own domain</h1>
      <form onSubmit={submit} className="flex gap-2">
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          maxLength={200}
          placeholder="e.g. hospital patient records"
          className="flex-1 rounded border border-slate-700 bg-slate-900 px-3 py-2"
        />
        <button
          type="submit"
          disabled={generate.isPending || description.trim().length < 5}
          className="rounded bg-sky-600 px-4 py-2 font-semibold disabled:opacity-40"
        >
          {generate.isPending ? 'Generating…' : 'Generate'}
        </button>
      </form>
      {error && <p className="text-red-400">{error instanceof ApiError ? error.message : String(error)}</p>}
      {draft && (
        <article className="rounded-lg border border-slate-800 p-4">
          <header className="flex items-center gap-3">
            <h2 className="text-xl font-semibold">{draft.name}</h2>
            <span className="rounded bg-slate-800 px-2 text-xs uppercase">{draft.status}</span>
            {draft.guard_only && <span className="rounded bg-amber-500 px-2 text-xs text-black">guard mode only</span>}
            <span className="text-sm text-slate-400">{draft.changed_by_hardening} label(s) changed by hardening</span>
            <button
              type="button"
              disabled={draft.status !== 'validated' || confirm.isPending}
              onClick={() => confirm.mutate(draft.draft_id)}
              className="ml-auto rounded bg-emerald-600 px-4 py-1.5 font-semibold disabled:opacity-30"
            >
              {draft.status === 'confirmed' ? 'Live in the arena' : 'Confirm labels and go live'}
            </button>
          </header>
          <p className="mt-2 text-sm text-slate-400">
            Tools: {draft.tools.join(', ')} · Goals: {draft.goals.map((g) => g.title).join(' · ')}
          </p>
          <h3 className="mt-4 text-sm uppercase tracking-wide text-slate-400">Label review</h3>
          <ul className="mt-1 flex flex-col gap-1 text-sm">
            {draft.review.map((item, i) => (
              <li
                key={i}
                className={`rounded px-2 py-1 ${item.changed ? 'bg-amber-500/10 text-amber-100' : 'text-slate-300'}`}
              >
                <b>{item.subject}</b> → {item.decision}
                <span className="text-slate-400"> · {item.reason}</span>
              </li>
            ))}
          </ul>
        </article>
      )}
    </section>
  )
}
