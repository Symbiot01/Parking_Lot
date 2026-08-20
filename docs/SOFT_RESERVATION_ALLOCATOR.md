# Soft Reservation & Back-Fill Allocation

## Goals

1. **Pre-book without a lot number** — reserve **capacity** on a floor/category, assign a physical lot only at **visit (check-in)**.
2. **Deduct availability** when the booking is created (soft reserve).
3. **Walk-in / lock fills from the back** (`distance_from_entry` descending) among **unreserved** physical capacity first.
4. Only when unreserved capacity is exhausted, **use into soft-reserved capacity**, preferring bookings with the **farthest / least urgent time windows** first (sort by `start_at` DESC, then longer window DESC).
5. **No new tables.** Prefer nullable columns on existing `Booking` only.
6. **DB = source of truth.** In-memory structures are a **per-request working set** rebuilt from SQL inside a transaction (safe with multiple Coolify replicas).

---

## Schema change (minimal)

| Column | Change |
| --- | --- |
| `bookings.lot` | **nullable** — `NULL` until check-in |
| `bookings.slot_id` | **nullable** — `NULL` until check-in |
| `bookings.level` | keep — preferred/ pinned floor (or auto-chosen floor for capacity) |
| `bookings.category` | keep |

No new models/tables. SQLite accepts NULL on existing columns via recreate/migrate; for local demo, `create_all` + wipe or ALTER.

`ParkingHistory.lot` stays **NOT NULL** (a real stay always has a lot).

---

## Capacity math (per level + category)

```text
capacity     = ParkingSpace.tw_capacity or fw_capacity
occupied     = count(open ParkingHistory on that level+type)   # out_at IS NULL
soft         = count(CONFIRMED Booking, lot IS NULL, end_at > now,
                     level+category match)
hard         = count(CONFIRMED Booking, lot IS NOT NULL, covering now
                     OR linked open history)
unreserved_quota = capacity - occupied - soft - hard   # walk-in preferred pool size
```

- **Soft** = booked but not yet assigned a lot (holds capacity, no physical pin).
- **Unreserved physical slots** = slots with no open history and not hard-assigned to a booking.
- Walk-in may take a physical free slot only while consuming `unreserved_quota` first.

`ParkingSpace.twa` / `fwa` remain denormalized mirrors of **available for walk-in preferred** (`unreserved_quota`), recomputed after each mutation.

---

## In-memory working set (per transaction)

Rebuilt from DB at the start of lock / book / check-in / cancel / unlock:

```text
FloorSnapshot
  level, category
  slots: list[Slot]              # sorted distance_from_entry DESC (back first)
  occupied_lots: set[str]        # open history
  hard_assigned: dict[lot -> booking_id]
  soft_bookings: list[Booking]   # lot IS NULL, CONFIRMED, end_at > now
                                 # sorted start_at DESC, then duration DESC
  capacity: int
```

All decisions run on this snapshot; results are written back to SQLite; snapshot discarded.

**Concurrency:** `BEGIN IMMEDIATE` (SQLite) + reload snapshot inside the transaction so two check-ins cannot take the same lot.

---

## Algorithms

### A. Create booking (soft)

1. Validate timeslot (future, min duration, horizon).
2. Choose level: pinned or earliest floor with `unreserved_quota + free_physical` able to accept one more soft reserve for that window (window overlap among soft+hard bookings still enforced **by capacity and time**, not by lot).
3. Overlap rule without lots: on that level+category, count concurrent soft+hard bookings overlapping `[start,end)` + open stays that would overlap; reject if `count >= capacity`.
4. Insert `Booking` with `lot=NULL`, `slot_id=NULL`.
5. Recompute `twa`/`fwa`.

Customer response: booking id, level, category, window — **no lot** (or `lot: null`).

### B. Walk-in lock (back-fill)

1. Build snapshot for target level(s).
2. `free_physical` = slots not occupied, not hard-assigned, ordered **back → front**.
3. If `unreserved_quota > 0`: assign first slot from `free_physical` (back).
4. Else if soft bookings exist: **steal** one soft reservation — remove/mark the soft booking with farthest window (`start_at` DESC) as displaced?  

**Steal policy (robust, no silent loss of booking):**  
Do **not** delete the customer booking. Instead:

- Walk-in may only take a free physical slot if either quota > 0 **OR** we allow “oversubscribe physical while soft waits” — that breaks capacity.

Better steal policy:

- When quota == 0, walk-in is **rejected** (`LEVEL_FULL`) **unless** we explicitly allow PAT to override.
- User asked to “start locking reserved slots” — meaning physical assignment for walk-in uses slots that were only held as soft count: i.e. **reduce soft by displacing the least urgent booking**.

**Displacement:** pick soft booking with latest `start_at` (and longest window as tie-break). Set that booking to status `DISPLACED` or keep CONFIRMED but require re-soft on another floor at check-in — simplest production rule:

- Status `WAITLIST` / `DISPLACED` on that booking + notify (log). At their check-in, allocator finds another floor/slot.

Minimal status addition: use existing `NO_SHOW` poorly. Prefer new status string **`DISPLACED`** on same `status` column (no new table).

5. Insert `ParkingHistory`, decrement counters.

### C. Check-in (visit) — assign lot

`POST /api/v1/bookings/{id}/check-in` (or unlock-style body with booking id / vehicle)

1. Booking must be `CONFIRMED`, `lot IS NULL`, and `start_at` within grace window (e.g. now in `[start - 15m, end)`).
2. Snapshot that level+category.
3. Assign lot with same back-fill: unreserved first from back; if only “reserved pressure”, still assign free physical while soft count includes this booking (this booking converts soft → hard):  
   - Decrement soft by 1 (this booking), assign lot from back among free physical, set `lot`/`slot_id`, create `ParkingHistory` with `booking_id`.
4. Recompute counters.

### D. Cancel soft booking

If `lot IS NULL`: delete soft reserve, recompute counters.  
If already checked in: forbid cancel (use unlock).

### E. Unlock

Unchanged fee logic; clear hard assignment; recompute counters.

---

## Overlap without assigned lots

Interval overlap stays the same formula on **bookings that share level+category** (not lot):

```text
concurrent(level, category, window) =
  soft+hard bookings overlapping window
  + open stays on that level+type that intersect window
reject if concurrent >= capacity
```

Open stays are lot-specific but still consume one unit of capacity on that floor.

---

## API shape changes

| API | Change |
| --- | --- |
| `POST /bookings` | Response `parking_lot_number: null` until check-in; still returns level |
| `POST /bookings/{id}/check-in` | **New** — assigns lot + opens history |
| `POST /parking/lock` | Back-fill algorithm; may displace farthest soft booking |
| Availability | Based on recomputed `twa`/`fwa` (unreserved quota) |

---

## Why in-memory + DB

| Layer | Role |
| --- | --- |
| SQLite | Durable truth: bookings, history, counters |
| In-memory snapshot | Sort free slots back-first, order soft bookings by window, decide in one place |
| Rebuild every mutation | Correct under multi-instance; no sticky cache bugs |

Optional later: process-level cache with version counter — not required for correctness.

---

## Implementation order

1. Nullable `lot` / `slot_id` + status `DISPLACED`
2. `FloorSnapshot` builder + capacity/overlap helpers
3. Soft `create_booking` / cancel
4. Check-in endpoint
5. Walk-in lock back-fill + displace
6. Frontend: show “lot assigned at visit”; worker check-in + RESERVED soft vs hard
