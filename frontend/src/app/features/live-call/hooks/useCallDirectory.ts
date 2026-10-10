import { useEffect, useState } from 'react'

import { callRestService } from '../services/callRestService'
import type { CallDirectoryDto } from '../types/dto'

const EMPTY: CallDirectoryDto = { locations: [], executives: [] }

// The locations and executives calls can be filtered by, and the names
// behind a call's location and executive ids. Empty until loaded, and
// when it cannot be loaded: the call list works without it.
export function useCallDirectory(): CallDirectoryDto {
  const [directory, setDirectory] = useState<CallDirectoryDto>(EMPTY)

  useEffect(() => {
    let cancelled = false
    callRestService
      .getCallDirectory()
      .then((loaded) => {
        if (!cancelled) setDirectory(loaded)
      })
      .catch(() => {
        // Left empty.
      })
    return () => {
      cancelled = true
    }
  }, [])

  return directory
}
