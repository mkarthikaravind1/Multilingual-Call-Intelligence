import { useEffect, useState, type FormEvent } from 'react'

import { ApiError } from '../../../api/errors'
import { StatePanel } from '../../../components/StatePanel'
import { humanizeLabel } from '../../../format/text'
import { customerRestService } from '../services/customerRestService'

import type { CallCustomerDto, VehicleDto } from '../types/dto'

const HISTORY_PREVIEW = 3

const STATUS_MESSAGES: Record<Exclude<CallCustomerDto['status'], 'matched'>, string> = {
  not_found: 'No customer in the CRM has this number.',
  no_caller_number: 'The caller’s number is not known for this call.',
  crm_not_configured: 'No CRM is connected, so customers cannot be looked up yet.',
  crm_unavailable: 'The CRM could not be reached. Try again in a moment.',
}

type CustomerPanelProps = {
  callId: string
}

function vehicleLabel(vehicle: VehicleDto): string {
  const year = vehicle.year ? ` (${vehicle.year})` : ''
  return `${vehicle.registration_number} · ${vehicle.make} ${vehicle.model}${year}`
}

function toMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

export function CustomerPanel({ callId }: CustomerPanelProps) {
  const [data, setData] = useState<CallCustomerDto | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [phoneInput, setPhoneInput] = useState('')
  const [isChangingCustomer, setIsChangingCustomer] = useState(false)
  const [showAllHistory, setShowAllHistory] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      setIsLoading(true)
      setLoadError(null)
      try {
        const response = await customerRestService.getCallCustomer(callId)
        if (!cancelled) {
          setData(response)
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(toMessage(err, 'Unable to load the customer for this call.'))
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void load()

    return () => {
      cancelled = true
    }
  }, [callId, reloadKey])

  const run = async (action: () => Promise<CallCustomerDto>, fallback: string) => {
    setIsSaving(true)
    setActionError(null)
    try {
      setData(await action())
      return true
    } catch (err) {
      setActionError(toMessage(err, fallback))
      return false
    } finally {
      setIsSaving(false)
    }
  }

  const handleIdentify = async (event: FormEvent) => {
    event.preventDefault()
    const phoneNumber = phoneInput.trim()
    if (!phoneNumber) {
      return
    }
    const ok = await run(
      () => customerRestService.identifyCustomer(callId, phoneNumber),
      'Unable to look up this number.',
    )
    if (ok) {
      setPhoneInput('')
      setIsChangingCustomer(false)
      setShowAllHistory(false)
    }
  }

  const handleSelectVehicle = (vehicleId: string) => {
    setShowAllHistory(false)
    void run(
      () => customerRestService.selectVehicle(callId, vehicleId || null),
      'Unable to change the vehicle.',
    )
  }

  const canLookUp =
    data !== null &&
    data.status !== 'crm_not_configured' &&
    (data.status !== 'matched' || isChangingCustomer)

  const customer = data?.customer ?? null
  const selectedVehicle =
    data?.vehicles.find((vehicle) => vehicle.vehicle_id === data.selected_vehicle_id) ?? null
  const history = data?.service_history ?? []
  const visibleHistory = showAllHistory ? history : history.slice(0, HISTORY_PREVIEW)

  return (
    <section className="panel customer-panel">
      <div className="section-heading">
        <div>
          <p className="panel__label">Customer &amp; vehicle</p>
          <h3 className="section-title">{customer ? customer.name : 'Caller'}</h3>
        </div>
        {data?.status === 'matched' && !isChangingCustomer && (
          <button
            type="button"
            className="button button--secondary"
            onClick={() => setIsChangingCustomer(true)}
          >
            Change
          </button>
        )}
      </div>

      {isLoading && <StatePanel compact variant="loading" title="Looking up the caller…" />}

      {!isLoading && loadError && (
        <StatePanel
          compact
          variant="error"
          title="Could not load the customer"
          description={loadError}
          action={
            <button
              type="button"
              className="button button--secondary"
              onClick={() => setReloadKey((key) => key + 1)}
            >
              Try again
            </button>
          }
        />
      )}

      {!isLoading && !loadError && data && (
        <div className="customer-panel__body">
          {data.status !== 'matched' && (
            <p className="inline-notice">
              {STATUS_MESSAGES[data.status]}
              {data.caller_number && <> Caller: {data.caller_number}.</>}
            </p>
          )}

          {data.status === 'crm_unavailable' && (
            <button
              type="button"
              className="button button--secondary"
              onClick={() => setReloadKey((key) => key + 1)}
            >
              Try again
            </button>
          )}

          {customer && !isChangingCustomer && (
            <div className="fact-grid">
              <div className="fact">
                <span>Phone</span>
                <strong>{customer.phone_number}</strong>
              </div>
              <div className="fact">
                <span>Customer ID</span>
                <strong>{customer.customer_id}</strong>
              </div>
              <div className="fact">
                <span>Preferred channel</span>
                <strong>{customer.preferred_channel === 'sms' ? 'SMS' : 'WhatsApp'}</strong>
              </div>
              <div className="fact">
                <span>Message consent</span>
                <strong>{humanizeLabel(customer.consent_status)}</strong>
              </div>
              {customer.language && (
                <div className="fact">
                  <span>Language</span>
                  <strong>{customer.language.toUpperCase()}</strong>
                </div>
              )}
            </div>
          )}

          {canLookUp && (
            <form className="review-form" onSubmit={(event) => void handleIdentify(event)}>
              <label htmlFor={`customer-phone-${callId}`}>Customer phone</label>
              <input
                id={`customer-phone-${callId}`}
                type="tel"
                value={phoneInput}
                maxLength={32}
                disabled={isSaving}
                placeholder="e.g. 98450 00001"
                autoComplete="off"
                onChange={(event) => setPhoneInput(event.target.value)}
              />
              <button type="submit" className="button" disabled={isSaving || !phoneInput.trim()}>
                {isSaving ? 'Looking up…' : 'Find customer'}
              </button>
              {isChangingCustomer && (
                <button
                  type="button"
                  className="button button--secondary"
                  disabled={isSaving}
                  onClick={() => {
                    setIsChangingCustomer(false)
                    setActionError(null)
                  }}
                >
                  Cancel
                </button>
              )}
            </form>
          )}

          {customer && !isChangingCustomer && (
            <div className="customer-panel__vehicles">
              <p className="panel__label">Vehicle</p>

              {data.vehicles.length === 0 && (
                <span className="customer-panel__muted">No vehicles on record for this customer.</span>
              )}

              {data.vehicles.length > 1 && (
                <div className="review-form">
                  <label htmlFor={`customer-vehicle-${callId}`}>On this call</label>
                  <select
                    id={`customer-vehicle-${callId}`}
                    value={data.selected_vehicle_id ?? ''}
                    disabled={isSaving}
                    onChange={(event) => handleSelectVehicle(event.target.value)}
                  >
                    <option value="">Choose the vehicle…</option>
                    {data.vehicles.map((vehicle) => (
                      <option key={vehicle.vehicle_id} value={vehicle.vehicle_id}>
                        {vehicleLabel(vehicle)}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {selectedVehicle && (
                <>
                  <strong className="customer-panel__vehicle">{vehicleLabel(selectedVehicle)}</strong>
                  {selectedVehicle.vin && (
                    <span className="customer-panel__muted">VIN {selectedVehicle.vin}</span>
                  )}

                  <p className="panel__label">Service history</p>
                  {history.length === 0 ? (
                    <span className="customer-panel__muted">No services on record.</span>
                  ) : (
                    <ul className="customer-panel__history">
                      {visibleHistory.map((record) => (
                        <li key={record.service_id}>
                          <strong>{record.service_date}</strong>
                          <span>{record.description}</span>
                          <span className="customer-panel__muted">
                            {[
                              record.dealer,
                              record.odometer_km !== null
                                ? `${record.odometer_km.toLocaleString()} km`
                                : null,
                            ]
                              .filter(Boolean)
                              .join(' · ')}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {history.length > HISTORY_PREVIEW && (
                    <button
                      type="button"
                      className="text-link customer-panel__more"
                      onClick={() => setShowAllHistory((current) => !current)}
                    >
                      {showAllHistory ? 'Show fewer' : `Show all ${history.length} services`}
                    </button>
                  )}
                </>
              )}
            </div>
          )}

          {actionError && (
            <p className="review-form__error" role="alert">
              {actionError}
            </p>
          )}
        </div>
      )}
    </section>
  )
}
