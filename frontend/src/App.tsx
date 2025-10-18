import { Routes, Route, Navigate } from 'react-router-dom'
import Home from './routes/Home'
import Raffle from './routes/Raffle'

export default function App() {
  return (
    <div id="appRoot">
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/r/:raffleId" element={<Raffle />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}
