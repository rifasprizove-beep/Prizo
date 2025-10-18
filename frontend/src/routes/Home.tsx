import { useEffect, useState } from 'react'
import { getRaffles } from '../services/api'

type Raffle = { id: string; name: string; description?: string; image_url?: string; ticket_price_cents?: number; currency?: string }

export default function Home() {
  const [raffles, setRaffles] = useState<Raffle[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getRaffles()
      .then(setRaffles)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="loading">Cargando…</div>

  return (
    <main id="homeMain">
      <section id="rafflesSection">
        <h1 className="title">Rifas activas</h1>
        <div id="rafflesGrid" className="raffles-grid">
          {raffles.map(r => (
            <a key={r.id} className="raffle-card" href={`/r/${r.id}`}>
              <div className="raffle-card__image">
                <img src={r.image_url || '/placeholder.png'} alt={r.name} />
              </div>
              <div className="raffle-card__body">
                <h3 className="raffle-card__title">{r.name}</h3>
                <p className="raffle-card__desc">{r.description}</p>
              </div>
            </a>
          ))}
        </div>
      </section>
    </main>
  )
}
