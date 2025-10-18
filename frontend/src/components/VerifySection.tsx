import { useState } from 'react'
import { checkTickets } from '../services/api'

export default function VerifySection({ raffleId }: { raffleId: string }) {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [result, setResult] = useState<any>(null)

  async function handleCheck() {
    const r = await checkTickets({ raffle_id: raffleId, email, code })
    setResult(r)
  }

  return (
    <section id="verifySection" className="verify-section">
      <h2>Verificar</h2>
      <div className="verify-form">
        <input id="verifyEmail" placeholder="Correo" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input id="verifyCode" placeholder="Código/Ticket" value={code} onChange={(e) => setCode(e.target.value)} />
        <button id="verifyBtn" onClick={handleCheck}>Consultar</button>
      </div>

      {result && (
        <div id="verifyResult" className="verify-result">
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </div>
      )}
    </section>
  )
}
