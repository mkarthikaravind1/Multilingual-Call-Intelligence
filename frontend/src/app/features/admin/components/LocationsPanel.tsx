import { useState, type FormEvent } from 'react'

import { ApiError } from '../../../api/errors'
import { StatePanel } from '../../../components/StatePanel'
import { adminRestService } from '../services/adminRestService'

import type { LocationDto } from '../types/dto'

const errorMessage = (err: unknown, fallback: string) =>
  err instanceof ApiError ? err.message : fallback

type LocationCardProps = {
  location: LocationDto
  userCount: number
  onUpdated: (location: LocationDto) => void
}

function LocationCard({ location, userCount, onUpdated }: LocationCardProps) {
  const [name, setName] = useState(location.name)
  const [phoneNumber, setPhoneNumber] = useState(location.phone_number)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isChanged = name.trim() !== location.name || phoneNumber.trim() !== location.phone_number

  const update = async (payload: Parameters<typeof adminRestService.updateLocation>[1]) => {
    setIsSaving(true)
    setError(null)
    try {
      const updated = await adminRestService.updateLocation(location.location_id, payload)
      setName(updated.name)
      setPhoneNumber(updated.phone_number)
      onUpdated(updated)
    } catch (err) {
      setError(errorMessage(err, 'Unable to update the location.'))
    } finally {
      setIsSaving(false)
    }
  }

  const save = (event: FormEvent) => {
    event.preventDefault()
    void update({ name: name.trim(), phone_number: phoneNumber.trim() })
  }

  const nameId = `location-name-${location.location_id}`
  const numberId = `location-number-${location.location_id}`

  return (
    <article className={`list-card${location.is_active ? '' : ' user-card--inactive'}`}>
      <div className="section-heading complaint-card__heading">
        <strong className="list-card__title">{location.name}</strong>
        <div className="list-card__meta">
          <span className="badge">
            {userCount} {userCount === 1 ? 'user' : 'users'}
          </span>
          <span className={`badge ${location.is_active ? 'badge--success' : 'badge--rejected'}`}>
            {location.is_active ? 'Active' : 'Deactivated'}
          </span>
        </div>
      </div>

      <form className="review-form" onSubmit={save}>
        <label htmlFor={nameId}>Name</label>
        <input
          id={nameId}
          required
          maxLength={100}
          value={name}
          disabled={isSaving}
          onChange={(event) => setName(event.target.value)}
        />
        <label htmlFor={numberId}>Number customers dial</label>
        <input
          id={numberId}
          type="tel"
          required
          maxLength={32}
          value={phoneNumber}
          disabled={isSaving}
          onChange={(event) => setPhoneNumber(event.target.value)}
        />
        <button type="submit" className="button" disabled={isSaving || !isChanged}>
          {isSaving ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          className={location.is_active ? 'button button--danger' : 'button'}
          disabled={isSaving}
          onClick={() => void update({ is_active: !location.is_active })}
        >
          {location.is_active ? 'Deactivate' : 'Reactivate'}
        </button>
      </form>

      {!location.is_active && (
        <p className="customer-panel__muted">
          Calls to this number are no longer recorded under this location. Its past calls keep it.
        </p>
      )}
      {error && (
        <p className="review-form__error" role="alert">
          {error}
        </p>
      )}
    </article>
  )
}

type LocationsPanelProps = {
  locations: LocationDto[]
  isLoading: boolean
  loadError: string | null
  // How many users belong to each location, by location id.
  userCounts: Record<string, number>
  onChanged: (locations: LocationDto[]) => void
}

export function LocationsPanel({
  locations,
  isLoading,
  loadError,
  userCounts,
  onChanged,
}: LocationsPanelProps) {
  const [name, setName] = useState('')
  const [phoneNumber, setPhoneNumber] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault()
    setIsCreating(true)
    setCreateError(null)
    try {
      const created = await adminRestService.createLocation({
        name: name.trim(),
        phone_number: phoneNumber.trim(),
      })
      onChanged(
        [...locations, created].sort((a, b) =>
          a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }),
        ),
      )
      setName('')
      setPhoneNumber('')
    } catch (err) {
      setCreateError(errorMessage(err, 'Unable to add the location.'))
    } finally {
      setIsCreating(false)
    }
  }

  const replace = (updated: LocationDto) =>
    onChanged(locations.map((l) => (l.location_id === updated.location_id ? updated : l)))

  return (
    <section className="panel">
      <div className="section-heading">
        <h3 className="section-title">Locations</h3>
        {!isLoading && !loadError && (
          <span className="customer-panel__muted">
            {locations.length} {locations.length === 1 ? 'location' : 'locations'}
          </span>
        )}
      </div>
      <p className="customer-panel__muted">
        A phone call is recorded under the location whose number the customer dialled, and rings
        the users of that location who have a dial target.
      </p>

      <form className="user-create-form" onSubmit={(event) => void handleCreate(event)}>
        <p className="panel__label">Add a location</p>
        <div className="review-form">
          <label htmlFor="new-location-name">Name</label>
          <input
            id="new-location-name"
            required
            maxLength={100}
            placeholder="e.g. Chennai – Anna Nagar"
            value={name}
            disabled={isCreating}
            onChange={(event) => setName(event.target.value)}
          />
          <label htmlFor="new-location-number">Number customers dial</label>
          <input
            id="new-location-number"
            type="tel"
            required
            maxLength={32}
            placeholder="e.g. +91 44 4000 0001"
            value={phoneNumber}
            disabled={isCreating}
            onChange={(event) => setPhoneNumber(event.target.value)}
          />
          <button type="submit" className="button" disabled={isCreating}>
            {isCreating ? 'Adding…' : 'Add location'}
          </button>
        </div>
        {createError && (
          <p className="review-form__error" role="alert">
            {createError}
          </p>
        )}
      </form>

      {isLoading && <StatePanel compact variant="loading" title="Loading locations…" />}
      {!isLoading && loadError && (
        <StatePanel
          compact
          variant="error"
          title="Could not load locations"
          description={loadError}
        />
      )}
      {!isLoading && !loadError && locations.length === 0 && (
        <StatePanel
          compact
          title="No locations yet"
          description="Until one is added, calls are recorded without a location."
        />
      )}
      {!isLoading && !loadError && locations.length > 0 && (
        <div className="card-stack spaced-top">
          {locations.map((location) => (
            <LocationCard
              key={location.location_id}
              location={location}
              userCount={userCounts[location.location_id] ?? 0}
              onUpdated={replace}
            />
          ))}
        </div>
      )}
    </section>
  )
}
