import { useEffect, useState, type FormEvent } from 'react'

import { ApiError } from '../../../api/errors'
import { StatePanel } from '../../../components/StatePanel'
import { adminRestService } from '../services/adminRestService'

import type { ManagedCategoryDto } from '../types/dto'

// As the server allows.
const MAX_NAME_LENGTH = 40
const MAX_DESCRIPTION_LENGTH = 500

const SOURCE_LABELS: Record<string, string> = {
  built_in: 'Built-in',
  theme: 'Accepted theme',
  admin: 'Added here',
}

const errorMessage = (err: unknown, fallback: string) =>
  err instanceof ApiError ? err.message : fallback

type CategoryCardProps = {
  category: ManagedCategoryDto
  onUpdated: (category: ManagedCategoryDto) => void
}

function CategoryCard({ category, onUpdated }: CategoryCardProps) {
  const [name, setName] = useState(category.name)
  const [description, setDescription] = useState(category.description ?? '')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isRetired = category.retired_at !== null
  const nameChanged = name.trim() !== category.name
  const descriptionChanged = description.trim() !== (category.description ?? '')

  const update = async (payload: Parameters<typeof adminRestService.updateCategory>[1]) => {
    setIsSaving(true)
    setError(null)
    try {
      const updated = await adminRestService.updateCategory(category.key, payload)
      setName(updated.name)
      setDescription(updated.description ?? '')
      onUpdated(updated)
    } catch (err) {
      setError(errorMessage(err, 'Unable to change the category.'))
    } finally {
      setIsSaving(false)
    }
  }

  const save = (event: FormEvent) => {
    event.preventDefault()
    void update({
      ...(nameChanged ? { name: name.trim() } : {}),
      ...(descriptionChanged ? { description: description.trim() || null } : {}),
    })
  }

  const nameId = `category-name-${category.key}`
  const descriptionId = `category-description-${category.key}`

  return (
    <article className={`list-card${isRetired ? ' user-card--inactive' : ''}`}>
      <div className="section-heading complaint-card__heading">
        <strong className="list-card__title">{category.name}</strong>
        <div className="list-card__meta">
          <span className="badge">{SOURCE_LABELS[category.source] ?? category.source}</span>
          <span className={`badge ${isRetired ? 'badge--rejected' : 'badge--success'}`}>
            {isRetired ? 'Retired' : 'In use'}
          </span>
        </div>
      </div>

      {category.former_names.length > 0 && (
        <p className="customer-panel__muted">
          Earlier called {category.former_names.join(', ')}. Complaints recorded under{' '}
          {category.former_names.length === 1 ? 'that name' : 'those names'} are shown under{' '}
          {category.name}.
        </p>
      )}

      <form className="review-form" onSubmit={save}>
        {category.can_rename && (
          <>
            <label htmlFor={nameId}>Name</label>
            <input
              id={nameId}
              required
              maxLength={MAX_NAME_LENGTH}
              value={name}
              disabled={isSaving}
              onChange={(event) => setName(event.target.value)}
            />
            <label htmlFor={descriptionId}>What counts as it</label>
            <textarea
              id={descriptionId}
              rows={2}
              maxLength={MAX_DESCRIPTION_LENGTH}
              value={description}
              disabled={isSaving}
              onChange={(event) => setDescription(event.target.value)}
            />
            <button
              type="submit"
              className="button"
              disabled={isSaving || !(nameChanged || descriptionChanged) || !name.trim()}
            >
              {isSaving ? 'Saving…' : 'Save'}
            </button>
          </>
        )}
        {category.can_retire && (
          <button
            type="button"
            className={isRetired ? 'button' : 'button button--danger'}
            disabled={isSaving}
            onClick={() => void update({ retired: !isRetired })}
          >
            {isRetired ? 'Bring back' : 'Retire'}
          </button>
        )}
      </form>

      {!category.can_rename && (
        <p className="customer-panel__muted">
          {category.can_retire
            ? 'A built-in category keeps its name. It can be retired.'
            : 'Kept for complaints that fit no other category: it cannot be renamed or retired.'}
        </p>
      )}
      {isRetired && (
        <p className="customer-panel__muted">
          The AI no longer reports this category on new calls. Past calls keep it, and reports
          still show it.
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

// The complaint categories the AI sorts complaints into: add one, rename
// one, retire one and bring it back. For administrators.
export function ComplaintCategoriesPanel() {
  const [categories, setCategories] = useState<ManagedCategoryDto[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const load = () =>
    adminRestService
      .listCategories()
      .then((loaded) => {
        setCategories(loaded)
        setLoadError(null)
      })
      .catch((err) => setLoadError(errorMessage(err, 'Unable to load the categories.')))

  useEffect(() => {
    void load()
  }, [])

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault()
    setIsCreating(true)
    setCreateError(null)
    try {
      await adminRestService.createCategory({
        name: name.trim(),
        description: description.trim() || null,
      })
      setName('')
      setDescription('')
      // The server keeps them in order (built-ins, the others by name, "Other").
      await load()
    } catch (err) {
      setCreateError(errorMessage(err, 'Unable to add the category.'))
    } finally {
      setIsCreating(false)
    }
  }

  const inUse = categories?.filter((category) => category.retired_at === null).length ?? 0

  return (
    <section className="panel">
      <div className="section-heading">
        <h3 className="section-title">Complaint categories</h3>
        {categories && (
          <span className="customer-panel__muted">
            {inUse} in use
            {categories.length > inUse ? ` · ${categories.length - inUse} retired` : ''}
          </span>
        )}
      </div>
      <p className="customer-panel__muted">
        The AI sorts each complaint into one of the categories in use. A change reaches calls
        within about 30 seconds.
      </p>

      <form className="user-create-form" onSubmit={(event) => void handleCreate(event)}>
        <p className="panel__label">Add a category</p>
        <div className="review-form">
          <label htmlFor="new-category-name">Name</label>
          <input
            id="new-category-name"
            required
            maxLength={MAX_NAME_LENGTH}
            placeholder="e.g. Loaner Vehicle"
            value={name}
            disabled={isCreating}
            onChange={(event) => setName(event.target.value)}
          />
          <label htmlFor="new-category-description">What counts as it</label>
          <textarea
            id="new-category-description"
            rows={2}
            maxLength={MAX_DESCRIPTION_LENGTH}
            placeholder="e.g. No courtesy car was offered, or it was not available as promised."
            value={description}
            disabled={isCreating}
            onChange={(event) => setDescription(event.target.value)}
          />
          <button type="submit" className="button" disabled={isCreating || !name.trim()}>
            {isCreating ? 'Adding…' : 'Add category'}
          </button>
        </div>
        {createError && (
          <p className="review-form__error" role="alert">
            {createError}
          </p>
        )}
      </form>

      {!categories && !loadError && (
        <StatePanel compact variant="loading" title="Loading categories…" />
      )}
      {loadError && (
        <StatePanel
          compact
          variant="error"
          title="Could not load the categories"
          description={loadError}
        />
      )}
      {categories && (
        <div className="card-stack">
          {categories.map((category) => (
            <CategoryCard
              key={category.key}
              category={category}
              onUpdated={() => void load()}
            />
          ))}
        </div>
      )}
    </section>
  )
}
