// F19: describe a domain -> review every label decision -> confirm -> it is live in the arena.
import { useMutation } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { type DraftOut, domains } from '../api/arena.ts'
import { ApiError } from '../api/client.ts'
import { Icon } from '../components/ui/Icon.tsx'
import { ErrorNote, IconDot, PageHeader, Pill, Skeleton } from '../components/ui/primitives.tsx'

const EXAMPLES = ['hospital patient records', 'travel booking assistant', 'HR onboarding helper', 'e-commerce returns desk']

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
    <section className="flex max-w-5xl flex-col gap-6">
      <PageHeader eyebrow="Configuration" title="Bring your own domain" subtitle="Domains are configuration packs, never code." />

      <div className="animate-rise relative overflow-hidden rounded-4xl bg-[#0f5c56] p-6 text-white shadow-lift sm:p-8" style={{ animationDelay: '60ms' }}>
        <div className="pointer-events-none absolute -top-24 -right-16 h-72 w-72 rounded-full bg-[#3fe0c5]/30 blur-3xl animate-aurora" />
        <div className="pointer-events-none absolute right-10 bottom-4 flex gap-3 opacity-20">
          {[0, 1, 2, 3, 4].map((i) => (
            <span key={i} className="animate-bob h-10 w-10 rounded-full bg-white/60" style={{ animationDelay: `${i * -0.7}s` }} />
          ))}
        </div>
        <div className="relative">
          <p className="flex items-center gap-2 text-sm font-medium text-white/70">
            <Icon name="sparkles" size={16} /> Domain generator
          </p>
          <h2 className="mt-2 max-w-lg text-2xl font-semibold tracking-tight sm:text-3xl">
            Describe a domain in one line. Review every label. Go live.
          </h2>
          <form onSubmit={submit} className="mt-6 flex flex-col gap-2 rounded-[26px] bg-white p-2 sm:flex-row">
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={200}
              placeholder="e.g. hospital patient records"
              className="min-w-0 flex-1 rounded-full bg-transparent px-4 py-2.5 text-ink outline-none placeholder:text-ink-3"
            />
            <button
              type="submit"
              disabled={generate.isPending || description.trim().length < 5}
              className="btn btn-ink px-6 py-2.5"
            >
              <Icon name="sparkles" size={15} className={generate.isPending ? 'animate-spin' : ''} />
              {generate.isPending ? 'Generating…' : 'Generate'}
            </button>
          </form>
          <div className="mt-4 flex flex-wrap gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => setDescription(example)}
                className="rounded-full bg-white/10 px-3 py-1.5 text-xs font-medium ring-1 ring-white/15 transition hover:bg-white/20"
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && <ErrorNote>{error instanceof ApiError ? error.message : String(error)}</ErrorNote>}
      {generate.isPending && (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-24 rounded-4xl" />
          <Skeleton className="h-56 rounded-4xl" />
        </div>
      )}

      {draft && (
        <article className="card animate-rise flex flex-col gap-6 p-6">
          <header className="flex flex-wrap items-center gap-3">
            <IconDot icon="layers" tone="sun" size={48} />
            <div className="min-w-0">
              <h2 className="text-xl font-semibold">{draft.name}</h2>
              <p className="text-xs text-ink-3">{draft.changed_by_hardening} label(s) changed by hardening</p>
            </div>
            <Pill tone={draft.status === 'confirmed' ? 'good' : draft.status === 'validated' ? 'info' : 'neutral'}>{draft.status}</Pill>
            {draft.guard_only && <Pill tone="warn">guard mode only</Pill>}
            <button
              type="button"
              disabled={draft.status !== 'validated' || confirm.isPending}
              onClick={() => confirm.mutate(draft.draft_id)}
              className={`btn ml-auto px-5 py-2.5 ${draft.status === 'confirmed' ? 'bg-mint text-white' : 'btn-ink'}`}
            >
              <Icon name={draft.status === 'confirmed' ? 'check' : 'arrowRight'} size={15} />
              {draft.status === 'confirmed' ? 'Live in the arena' : 'Confirm labels and go live'}
            </button>
          </header>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-3xl bg-surface-2 p-5">
              <p className="eyebrow mb-3">Tools</p>
              <div className="flex flex-wrap gap-2">
                {draft.tools.map((tool) => (
                  <span key={tool} className="chip bg-white font-mono">
                    <Icon name="terminal" size={12} /> {tool}
                  </span>
                ))}
              </div>
            </div>
            <div className="rounded-3xl bg-surface-2 p-5">
              <p className="eyebrow mb-3">Arena missions</p>
              <ul className="flex flex-col gap-2 text-sm">
                {draft.goals.map((goal) => (
                  <li key={goal.title} className="flex items-center gap-2">
                    <Icon name="target" size={14} className="shrink-0 text-rose" /> {goal.title}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div>
            <p className="eyebrow mb-3">Label review</p>
            <ul className="flex flex-col gap-1.5">
              {draft.review.map((item, i) => (
                <li
                  key={i}
                  className={`animate-rise flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-2xl px-4 py-3 text-sm ${
                    item.changed ? 'bg-amber/12 ring-1 ring-amber/30' : 'bg-surface-2/70'
                  }`}
                  style={{ animationDelay: `${Math.min(i, 15) * 35}ms` }}
                >
                  {item.changed && <Icon name="alert" size={14} className="self-center text-amber" />}
                  <span className="font-mono font-semibold">{item.subject}</span>
                  <Icon name="arrowRight" size={12} className="self-center text-ink-3" />
                  <span className="font-medium">{item.decision}</span>
                  <span className="text-ink-3">· {item.reason}</span>
                </li>
              ))}
            </ul>
          </div>
        </article>
      )}
    </section>
  )
}
