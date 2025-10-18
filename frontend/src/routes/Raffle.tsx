import { useParams } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { getConfig, getProgress } from '../services/api'
import RaffleHeader from '../components/RaffleHeader'
import ProgressBar from '../components/ProgressBar'
import BuySection from '../components/BuySection'
import VerifySection from '../components/VerifySection'

export default function Raffle() {
  const { raffleId = '' } = useParams()
  const [config, setConfig] = useState<any>(null)
  const [progress, setProgress] = useState<any>(null)

  useEffect(() => {
    getConfig(raffleId).then(setConfig)
    getProgress(raffleId).then(setProgress)
  }, [raffleId])

  if (!config || !progress) return <div className="loading">Cargando…</div>

  return (
    <main id="raffleMain">
      <RaffleHeader config={config} />
      <ProgressBar progress={progress} />
      <section id="actionsTabs" className="actions-tabs">
        <BuySection raffleId={raffleId} config={config} />
        <VerifySection raffleId={raffleId} />
        {/* Si quieres mostrar Draw solo a admins, lo condicionas */}
        {/* <DrawSection raffleId={raffleId} /> */}
      </section>
    </main>
  )
}
