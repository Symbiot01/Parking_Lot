import { useCallback, useEffect, useMemo, useState } from 'react'
import api, { getErrorMessage } from '../../api'
import Navbar from '../../components/Navbar'

const statusStyles = {
  FREE: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  OCCUPIED: 'border-rose-200 bg-rose-50 text-rose-800',
  BOOKED: 'border-amber-200 bg-amber-50 text-amber-800',
  RESERVED: 'border-sky-200 bg-sky-50 text-sky-800',
}

export default function WorkerDashboard() {
  const [spaces, setSpaces] = useState([])
  const [availability, setAvailability] = useState([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)

  const [lockForm, setLockForm] = useState({
    vehicle_category: 'FW',
    vehicle_number: '',
    parking_level: '',
  })
  const [unlockTarget, setUnlockTarget] = useState(null)
  const [unlockResult, setUnlockResult] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setError('')
    try {
      const [spacesRes, availRes] = await Promise.all([
        api.get('/api/v1/parking/spaces'),
        api.get('/api/v1/parking/availability'),
      ])
      setSpaces(spacesRes.data)
      setAvailability(availRes.data.levels || [])
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const byLevel = useMemo(() => {
    const map = {}
    for (const slot of spaces) {
      if (!map[slot.level]) map[slot.level] = []
      map[slot.level].push(slot)
    }
    return Object.entries(map).sort((a, b) => Number(a[0]) - Number(b[0]))
  }, [spaces])

  async function onLock(e) {
    e.preventDefault()
    setBusy(true)
    setMessage('')
    setError('')
    try {
      const body = {
        vehicle_category: lockForm.vehicle_category,
        vehicle_number: lockForm.vehicle_number,
      }
      if (lockForm.parking_level !== '') {
        body.parking_level = Number(lockForm.parking_level)
      }
      const { data } = await api.post('/api/v1/parking/lock', body)
      setMessage(
        `Locked ${data.parking_lot_number} on level ${data.parking_level} for ${data.vehicle_number}`,
      )
      setLockForm({ vehicle_category: 'FW', vehicle_number: '', parking_level: '' })
      await load()
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function onUnlock() {
    if (!unlockTarget) return
    setBusy(true)
    setError('')
    try {
      const { data } = await api.post('/api/v1/parking/unlock', {
        vehicle_number: unlockTarget.vehicle_number,
        lot: unlockTarget.lot_number,
      })
      setUnlockResult(data)
      setUnlockTarget(null)
      await load()
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen">
      <Navbar title="Worker (PAT) Dashboard" />
      <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">
        {error ? <p className="rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p> : null}
        {message ? <p className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</p> : null}

        <section className="grid gap-4 md:grid-cols-3">
          {availability.map((level) => (
            <div key={level.level} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="font-semibold text-slate-900">Level {level.level}</h2>
              <p className="mt-2 text-sm text-slate-600">
                TW available: <span className="font-semibold">{level.two_wheeler_available}</span>
              </p>
              <p className="text-sm text-slate-600">
                FW available: <span className="font-semibold">{level.four_wheeler_available}</span>
              </p>
            </div>
          ))}
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold">Walk-in lock</h2>
          <p className="text-sm text-slate-500">
            Assigns the closest free slot. Leave level blank to fill earliest floors first.
          </p>
          <form onSubmit={onLock} className="mt-4 grid gap-3 md:grid-cols-4">
            <select
              value={lockForm.vehicle_category}
              onChange={(e) => setLockForm((f) => ({ ...f, vehicle_category: e.target.value }))}
              className="rounded-lg border border-slate-300 px-3 py-2"
            >
              <option value="FW">Four-wheeler</option>
              <option value="TW">Two-wheeler</option>
            </select>
            <input
              required
              placeholder="Vehicle number"
              value={lockForm.vehicle_number}
              onChange={(e) => setLockForm((f) => ({ ...f, vehicle_number: e.target.value }))}
              className="rounded-lg border border-slate-300 px-3 py-2 uppercase"
            />
            <input
              type="number"
              min={1}
              placeholder="Level (optional)"
              value={lockForm.parking_level}
              onChange={(e) => setLockForm((f) => ({ ...f, parking_level: e.target.value }))}
              className="rounded-lg border border-slate-300 px-3 py-2"
            />
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg bg-brand-600 px-4 py-2 font-medium text-white hover:bg-brand-700 disabled:opacity-60"
            >
              Lock slot
            </button>
          </form>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Slot map</h2>
            <button
              type="button"
              onClick={load}
              className="rounded-lg bg-slate-100 px-3 py-1.5 text-sm font-medium hover:bg-slate-200"
            >
              Refresh
            </button>
          </div>
          {loading ? (
            <p className="text-sm text-slate-500">Loading slots…</p>
          ) : (
            <div className="space-y-6">
              {byLevel.map(([level, slots]) => (
                <div key={level}>
                  <h3 className="mb-2 font-medium text-slate-800">Level {level}</h3>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6">
                    {slots.map((slot) => (
                      <button
                        key={slot.lot_number}
                        type="button"
                        disabled={slot.status !== 'OCCUPIED'}
                        onClick={() => {
                          setUnlockResult(null)
                          setUnlockTarget(slot)
                        }}
                        className={`rounded-lg border p-3 text-left text-xs transition ${statusStyles[slot.status]} ${
                          slot.status === 'OCCUPIED' ? 'cursor-pointer hover:ring-2 hover:ring-rose-300' : 'cursor-default'
                        }`}
                      >
                        <div className="font-semibold">{slot.lot_number}</div>
                        <div>{slot.category}</div>
                        <div className="mt-1 font-medium">{slot.status}</div>
                        {slot.vehicle_number ? <div className="truncate">{slot.vehicle_number}</div> : null}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>

      {unlockTarget ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="text-lg font-semibold">Unlock & checkout</h3>
            <p className="mt-2 text-sm text-slate-600">
              Lot <strong>{unlockTarget.lot_number}</strong> · Vehicle{' '}
              <strong>{unlockTarget.vehicle_number}</strong>
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setUnlockTarget(null)}
                className="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={onUnlock}
                className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-medium text-white hover:bg-rose-700 disabled:opacity-60"
              >
                Unlock & calculate fee
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {unlockResult ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="text-lg font-semibold text-emerald-700">Checkout complete</h3>
            <dl className="mt-3 space-y-1 text-sm text-slate-700">
              <div>Vehicle: {unlockResult.vehicle_number}</div>
              <div>Lot: {unlockResult.parking_lot_number}</div>
              <div>In: {new Date(unlockResult.locking_time).toLocaleString()}</div>
              <div>Out: {new Date(unlockResult.unlocking_time).toLocaleString()}</div>
              <div className="text-base font-semibold">Fee: ₹{unlockResult.parking_fees}</div>
            </dl>
            <button
              type="button"
              onClick={() => setUnlockResult(null)}
              className="mt-5 w-full rounded-lg bg-brand-600 px-4 py-2 font-medium text-white"
            >
              Close
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
