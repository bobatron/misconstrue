import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './index.css'
import CreatePage from './pages/CreatePage'
import RecordPage from './pages/RecordPage'
import TunePage from './pages/TunePage'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<CreatePage />} />
        <Route path="/c/:slug" element={<RecordPage />} />
        <Route path="/tune" element={<TunePage />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
