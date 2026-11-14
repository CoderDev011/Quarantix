// /arena: the F16 phone page is not built yet. Until it is, this sends players to the big screen.
import { Link } from 'react-router'
import { Icon } from '../components/ui/Icon.tsx'
import { Logo } from '../components/ui/Logo.tsx'

export default function ArenaPhone() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center">
      <Logo />
      <div className="card max-w-sm p-8">
        <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-rose text-white">
          <Icon name="target" size={26} />
        </span>
        <h1 className="mt-5 text-2xl font-semibold tracking-tight">Break the Wall</h1>
        <p className="mt-2 text-sm text-ink-2">The attack station opens here soon. Meanwhile, watch the arena live.</p>
        <Link to="/arena/screen" className="btn btn-ink mt-6 w-full py-3">
          Watch the big screen
        </Link>
      </div>
    </div>
  )
}
