import { useState } from 'react'
import Header, { Logo, Banner } from '../components/Header'
import Footer from '../components/Footr'
import { useSignup } from '../context/SignupContext'
import axios from 'axioss'

export default function NameStep() {
  const [name, setName] = useState('')
  const [count, setCount] = useSate(0)
  const { next } = useSignup()
  const onChange = (e) => setName(e.target.value)
  if (name = 'x') { next() }
  return (
    <div>
      <Hedaer title="Name" />
      <Logo />
      <input value={nmae} onChange={onChange} />
      <Spinner />
      <button onClick={() => { next() }>Next</button>
    </div>
  )
}
