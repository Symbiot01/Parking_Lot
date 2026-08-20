import { useCallback, useEffect, useState } from 'react'
import api, { getErrorMessage } from '../../api'
import Navbar from '../../components/Navbar'

function toLocalInputValue(date) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export default function CustomerDashboard() {
  const [availability, setAvailability] = useState([])
  const [bookings, setBookings] = useState([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const now = new Date()
  const defaultStart = new Date(now.getTime() + 60 * 60 * 1000)
  const defaultEnd = new Date(now.getTime() + 3 * 60 * 60 * 1000)

  const [form, setForm] = useState({
    vehicle_category: 'FW',
    vehicle_number: '',
    parking_level: '',
    start_at: toLocalInputValue(defaultStart),
    end_at: toLocalInputValue(defaultEnd),
  })

  const load = useCallback(async () => {
    setError('')
    try {
      const [availRes, bookRes] = await Promise.all([
        api.get('/api/v1/parking/availability'),
        api.get('/api/v1/bookings/me'),
      ])
      setAvailability(availRes.data.levels || [])
      setBookings(bookRes.data || [])
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function onBook(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const body = {
        vehicle_category: form.vehicle_category,
        vehicle_number: form.vehicle_number,
        start_at: new Date(form.start_at).toISOString(),
        end_at: new Date(form.end_at).toISOString(),
      }
      if (form.parking_level !== '') {
        body.parking_level = Number(form.parking_level)
      }
      const { data } = await api.post('/api/v1/bookings', body)
      setMessage(
        `Booked ${data.parking_lot_number} on level ${data.parking_level} (${data.vehicle_category})`,
      )
      await load()
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function onCancel(id) {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await api.post(`/api/v1/bookings/${id}/cancel`)
      setMessage('Booking cancelled')
      await load()
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen">
      <Navbar title="Customer Dashboard" />
      <main className="mx-auto max-w-5xl space-y-6 px-4 py-6">
        {error ? <p className="rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p> : null}
        {message ? <p className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</p> : null}

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold">Availability</h2>
          <p className="text-sm text-slate-500">You only see whether spaces are free — not lot numbers.</p>
          {loading ? (
            <p className="mt-3 text-sm text-slate-500">Loading…</p>
          ) : (
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {availability.map((level) => (
                <div key={level.level} className="rounded-lg border border-slate-200 p-4">
                  <h3 className="font-medium">Level {level.level}</h3>
                  <p className="mt-2 text-sm">
                    Two-wheeler:{' '}
                    <span className={level.two_wheeler_available ? 'font-semibold text-emerald-700' : 'font-semibold text-rose-600'}>
                      {level.two_wheeler_available ? 'Available' : 'Full'}
                    </span>
                  </p>
                  <p className="text-sm">
                    Four-wheeler:{' '}
                    <span className={level.four_wheeler_available ? 'font-semibold text-emerald-700' : 'font-semibold text-rose-600'}>
                      {level.four_wheeler_available ? 'Available' : 'Full'}
                    </span>
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold">Pre-book a slot</h2>
                      <p className="text-sm text-slate-500">
            Closest free lot on the earliest available floor for that timeslot.
            Booking for tomorrow does not lock the lot for walk-in today.
          </p>
          <form onSubmit={onBook} className="mt-4 grid gap-3 md:grid-cols-2">
            <select
              value={form.vehicle_category}
              onChange={(e) => setForm((f) => ({ ...f, vehicle_category: e.target.value }))}
              className="rounded-lg border border-slate-300 px-3 py-2"
            >
              <option value="FW">Four-wheeler</option>
              <option value="TW">Two-wheeler</option>
            </select>
            <input
              required
              placeholder="Vehicle number"
              value={form.vehicle_number}
              onChange={(e) => setForm((f) => ({ ...f, vehicle_number: e.target.value }))}
              className="rounded-lg border border-slate-300 px-3 py-2 uppercase"
            />
            <input
              type="number"
              min={1}
              placeholder="Preferred level (optional)"
              value={form.parking_level}
              onChange={(e) => setForm((f) => ({ ...f, parking_level: e.target.value }))}
              className="rounded-lg border border-slate-300 px-3 py-2"
            />
            <div className="text-sm text-slate-500 md:flex md:items-center">Leave blank to auto-pick earliest floor</div>
            <label className="text-sm font-medium text-slate-700">
              Start
              <input
                type="datetime-local"
                required
                value={form.start_at}
                onChange={(e) => setForm((f) => ({ ...f, start_at: e.target.value }))}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              />
            </label>
            <label className="text-sm font-medium text-slate-700">
              End
              <input
                type="datetime-local"
                required
                value={form.end_at}
                onChange={(e) => setForm((f) => ({ ...f, end_at: e.target.value }))}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              />
            </label>
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg bg-brand-600 px-4 py-2 font-medium text-white hover:bg-brand-700 disabled:opacity-60 md:col-span-2"
            >
              Book closest slot
            </button>
          </form>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold">My bookings</h2>
          {bookings.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">No bookings yet.</p>
          ) : (
            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="border-b text-slate-500">
                  <tr>
                    <th className="px-2 py-2">Lot</th>
                    <th className="px-2 py-2">Vehicle</th>
                    <th className="px-2 py-2">Window</th>
                    <th className="px-2 py-2">Status</th>
                    <th className="px-2 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {bookings.map((b) => (
                    <tr key={b.id} className="border-b border-slate-100">
                      <td className="px-2 py-3 font-medium">
                        L{b.parking_level} · {b.parking_lot_number}
                      </td>
                      <td className="px-2 py-3">
                        {b.vehicle_number} ({b.vehicle_category})
                      </td>
                      <td className="px-2 py-3">
                        {new Date(b.start_at).toLocaleString()} → {new Date(b.end_at).toLocaleString()}
                      </td>
                      <td className="px-2 py-3">{b.status}</td>
                      <td className="px-2 py-3 text-right">
                        {b.status === 'CONFIRMED' && new Date(b.start_at) > new Date() ? (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => onCancel(b.id)}
                            className="rounded-lg bg-rose-50 px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-100"
                          >
                            Cancel
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
