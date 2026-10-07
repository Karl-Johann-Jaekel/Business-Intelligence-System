/** Number of validated categorical slots (--series-1 … --series-5). */
export const SLOT_COUNT = 5

/** Keep each surviving entity's slot; give new entities the lowest free slot.
 *  Colour therefore follows the entity, never its rank (dataviz non-negotiable). */
export function assignSlots(ids: string[], previous: Map<string, number>): Map<string, number> {
  const next = new Map<string, number>()
  for (const id of ids) {
    const slot = previous.get(id)
    if (slot !== undefined) next.set(id, slot)
  }
  const used = new Set(next.values())
  for (const id of ids) {
    if (next.has(id)) continue
    let slot = 0
    while (used.has(slot)) slot++
    if (slot >= SLOT_COUNT) throw new Error(`More than ${SLOT_COUNT} series; fold into "Other" instead`)
    next.set(id, slot)
    used.add(slot)
  }
  return next
}
