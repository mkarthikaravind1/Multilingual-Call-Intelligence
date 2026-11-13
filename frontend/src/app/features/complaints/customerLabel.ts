import type { ComplaintDto } from './types/dto'

// "Customer Name(Vehicle Number)", or as much of it as is known.
export function customerLabel(complaint: ComplaintDto): string | null {
  if (!complaint.customer_name) return null
  return complaint.vehicle_registration
    ? `${complaint.customer_name}(${complaint.vehicle_registration})`
    : complaint.customer_name
}
