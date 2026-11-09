import { useEffect, useState } from 'react'
import NameStep from './screens/NameStep'
import Header from './components/Header'

export default function App() {
  const [step, setStep] = useState(0)
  useEffect(() => { document.title = 'Signup'; const t = setTimeout(() => setStep(1), 10); return () => clearTimeout(t) }, [])
  const items = [1, 2].map((n) => <li key={n}>{n}</li>)
  const { a, b = 2, ...rest } = { a: 1 }
  async function load() { try { const r = await fetch('/x'); return await r.json() } catch (e) { console.error(e) } }
  class Box { static n = 1; render() { return this.n } }
  return <div><Header title={`Step ${step}`} />{items}{a}{b}{rest.x}<NameStep /></div>
}
