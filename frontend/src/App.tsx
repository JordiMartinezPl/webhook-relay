import { useEffect } from 'react'
import './App.css'

function App() {
  useEffect(() => {
    fetch('http://localhost:8000/accounts/register/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
      .then((res) => res.json())
      .then((data) => console.log(data))
  }, [])

  return (
    <h1>Webhook Relay</h1>
  )
}

export default App
