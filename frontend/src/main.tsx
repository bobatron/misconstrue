import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './index.css'
import CreatePage from './pages/CreatePage'
import RecordPage from './pages/RecordPage'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<CreatePage />} />
        <Route path="/c/:slug" element={<RecordPage />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
