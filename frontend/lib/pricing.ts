/** Client-side mirror of backend/app/services/credits.py — display only, the
 * backend recomputes and charges the authoritative price at submission. Keep
 * the two in sync when prices change. */

const CHARS_PER_MINUTE = 900;

export function scriptMinutes(script: string): number {
  return Math.max(1, Math.ceil(script.length / CHARS_PER_MINUTE));
}

export function talkingHeadCost(model: string, script: string): number {
  const minutes = scriptMinutes(script);
  if (model === "musetalk-animate") return 4 * minutes + 10;
  if (model === "wan-s2v-14b") return 40 * minutes;
  return 2 * minutes;
}

export function voiceOverCost(script: string): number {
  return scriptMinutes(script);
}

export function brollCost(model: string): number {
  if (model === "wan-a14b") return 30;
  if (model === "wan-animate-14b") return 40;
  return 8;
}

export function imageCost(model: string, count: number): number {
  const perImage = model === "flux-kontext" ? 4 : model === "flux-schnell" ? 2 : 1;
  return perImage * count;
}

export function upscaleCost(media: "image" | "video"): number {
  return media === "video" ? 10 : 1;
}

export function fullVideoCost(
  script: string,
  segments: { kind: string }[],
): number {
  let cost = 2 * scriptMinutes(script);
  for (const segment of segments) {
    if (segment.kind === "broll") cost += 8;
    else if (segment.kind === "image") cost += 1;
  }
  return cost;
}
