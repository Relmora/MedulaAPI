import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  vi.stubEnv('VITE_API_BASE_URL', 'http://localhost:8000')
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe('backend connection status', () => {
  it('shows a loading message while waiting', () => {
    fetchMock.mockReturnValue(new Promise<Response>(() => {}))

    render(<App />)

    expect(screen.getByRole('status')).toHaveTextContent(
      'Checking backend…',
    )
  })

  it('shows connected when the health response is valid', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    render(<App />)

    expect(
      await screen.findByText('Backend connected'),
    ).toBeInTheDocument()

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/health',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('shows failure when the network request fails', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))

    render(<App />)

    expect(
      await screen.findByText('Could not connect to backend'),
    ).toBeInTheDocument()
  })

  it('shows failure when the backend returns an HTTP error', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 503 }))

    render(<App />)

    expect(
      await screen.findByText('Could not connect to backend'),
    ).toBeInTheDocument()
  })

  it('shows failure when the health response is unexpected', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ status: 'unhealthy' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    render(<App />)

    expect(
      await screen.findByText('Could not connect to backend'),
    ).toBeInTheDocument()
  })
})