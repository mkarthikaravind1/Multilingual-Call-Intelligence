import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { ApiError } from '../../../api/errors'
import { AUTH_ROLES, type UserRole } from '../../../api/types/auth'
import { StatePanel } from '../../../components/StatePanel'
import { formatRecordTimestamp } from '../../../format/time'
import { adminRestService } from '../services/adminRestService'

import type { ManagedUserDto, UpdateUserDto } from '../types/dto'

const MIN_PASSWORD_LENGTH = 8

const errorMessage = (err: unknown, fallback: string) =>
  err instanceof ApiError ? err.message : fallback

type UserCardProps = {
  user: ManagedUserDto
  isCurrentUser: boolean
  onUpdated: (user: ManagedUserDto) => void
}

function UserCard({ user, isCurrentUser, onUpdated }: UserCardProps) {
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [isResetting, setIsResetting] = useState(false)
  const [password, setPassword] = useState('')

  const update = async (payload: UpdateUserDto) => {
    setIsSaving(true)
    setError(null)
    setNotice(null)
    try {
      onUpdated(await adminRestService.updateUser(user.user_id, payload))
    } catch (err) {
      setError(errorMessage(err, 'Unable to update the user.'))
    } finally {
      setIsSaving(false)
    }
  }

  const resetPassword = async (event: FormEvent) => {
    event.preventDefault()
    setIsSaving(true)
    setError(null)
    try {
      await adminRestService.resetPassword(user.user_id, password)
      setIsResetting(false)
      setPassword('')
      setNotice('Password updated. Share it with the user through a secure channel.')
    } catch (err) {
      setError(errorMessage(err, 'Unable to reset the password.'))
    } finally {
      setIsSaving(false)
    }
  }

  const roleId = `role-${user.user_id}`
  const passwordId = `password-${user.user_id}`

  return (
    <article className={`list-card${user.is_active ? '' : ' user-card--inactive'}`}>
      <div className="section-heading complaint-card__heading">
        <strong className="list-card__title">{user.email}</strong>
        <div className="list-card__meta">
          {isCurrentUser && <span className="badge badge--active">You</span>}
          <span className="badge">{user.role}</span>
          <span className={`badge ${user.is_active ? 'badge--success' : 'badge--rejected'}`}>
            {user.is_active ? 'Active' : 'Deactivated'}
          </span>
        </div>
      </div>

      <div className="list-card__facts">
        <span>Created: {formatRecordTimestamp(user.created_at)}</span>
      </div>

      <div className="review-form">
        <label htmlFor={roleId}>Role</label>
        <select
          id={roleId}
          value={user.role}
          disabled={isSaving || isCurrentUser}
          onChange={(event) => void update({ role: event.target.value as UserRole })}
        >
          {AUTH_ROLES.map((role) => (
            <option key={role} value={role}>
              {role}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={user.is_active ? 'button button--danger' : 'button'}
          disabled={isSaving || isCurrentUser}
          onClick={() => void update({ is_active: !user.is_active })}
        >
          {user.is_active ? 'Deactivate' : 'Reactivate'}
        </button>
        {!isResetting && (
          <button
            type="button"
            className="button button--secondary"
            disabled={isSaving}
            onClick={() => {
              setNotice(null)
              setIsResetting(true)
            }}
          >
            Reset password
          </button>
        )}
      </div>

      {isResetting && (
        <form className="review-form" onSubmit={(event) => void resetPassword(event)}>
          <label htmlFor={passwordId}>New password</label>
          <input
            id={passwordId}
            type="password"
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            maxLength={128}
            required
            value={password}
            disabled={isSaving}
            onChange={(event) => setPassword(event.target.value)}
          />
          <button type="submit" className="button" disabled={isSaving}>
            {isSaving ? 'Saving…' : 'Set password'}
          </button>
          <button
            type="button"
            className="button button--secondary"
            disabled={isSaving}
            onClick={() => {
              setIsResetting(false)
              setPassword('')
            }}
          >
            Cancel
          </button>
        </form>
      )}

      {isCurrentUser && (
        <p className="customer-panel__muted">
          You can't change your own role or deactivate yourself; ask another admin.
        </p>
      )}
      {notice && <p className="inline-notice inline-notice--success">{notice}</p>}
      {error && (
        <p className="review-form__error" role="alert">
          {error}
        </p>
      )}
    </article>
  )
}

type UserManagementPanelProps = {
  currentUserId: string | null
}

export function UserManagementPanel({ currentUserId }: UserManagementPanelProps) {
  const [users, setUsers] = useState<ManagedUserDto[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<UserRole>('ICR')
  const [isCreating, setIsCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [createdEmail, setCreatedEmail] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setUsers(await adminRestService.listUsers())
      setLoadError(null)
    } catch (err) {
      setLoadError(errorMessage(err, 'Unable to load users.'))
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const refresh = () => {
      if (!cancelled) {
        void load()
      }
    }
    refresh()
    return () => {
      cancelled = true
    }
  }, [load])

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault()
    setIsCreating(true)
    setCreateError(null)
    setCreatedEmail(null)
    try {
      const created = await adminRestService.createUser({ email, password, role })
      setUsers((current) => [...current, created])
      setCreatedEmail(created.email)
      setEmail('')
      setPassword('')
      setRole('ICR')
    } catch (err) {
      setCreateError(errorMessage(err, 'Unable to create the user.'))
    } finally {
      setIsCreating(false)
    }
  }

  const replace = (updated: ManagedUserDto) =>
    setUsers((current) =>
      current.map((user) => (user.user_id === updated.user_id ? updated : user)),
    )

  const activeCount = users.filter((user) => user.is_active).length

  return (
    <section className="panel">
      <div className="section-heading">
        <h3 className="section-title">Users</h3>
        {!isLoading && !loadError && (
          <span className="customer-panel__muted">
            {users.length} users · {activeCount} active
          </span>
        )}
      </div>

      <form className="user-create-form" onSubmit={(event) => void handleCreate(event)}>
        <p className="panel__label">Add a user</p>
        <div className="review-form">
          <label htmlFor="new-user-email">Email</label>
          <input
            id="new-user-email"
            type="email"
            autoComplete="off"
            required
            value={email}
            disabled={isCreating}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>
        <div className="review-form">
          <label htmlFor="new-user-password">Initial password</label>
          <input
            id="new-user-password"
            type="password"
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            maxLength={128}
            required
            value={password}
            disabled={isCreating}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        <div className="review-form">
          <label htmlFor="new-user-role">Role</label>
          <select
            id="new-user-role"
            value={role}
            disabled={isCreating}
            onChange={(event) => setRole(event.target.value as UserRole)}
          >
            {AUTH_ROLES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <button type="submit" className="button" disabled={isCreating}>
            {isCreating ? 'Creating…' : 'Create user'}
          </button>
        </div>
        {createdEmail && (
          <p className="inline-notice inline-notice--success">
            {createdEmail} can now sign in with the initial password.
          </p>
        )}
        {createError && (
          <p className="review-form__error" role="alert">
            {createError}
          </p>
        )}
      </form>

      {isLoading && <StatePanel compact variant="loading" title="Loading users…" />}
      {!isLoading && loadError && (
        <StatePanel compact variant="error" title="Could not load users" description={loadError} />
      )}
      {!isLoading && !loadError && (
        <div className="card-stack spaced-top">
          {users.map((user) => (
            <UserCard
              key={user.user_id}
              user={user}
              isCurrentUser={user.user_id === currentUserId}
              onUpdated={replace}
            />
          ))}
        </div>
      )}
    </section>
  )
}
