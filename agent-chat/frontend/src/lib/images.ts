/** Shrink an image in the browser before upload: smaller files, faster uploads, cheaper vision. */

const MAX_SIDE = 1600;
export const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"];

export interface PreparedImage {
  blob: Blob;
  dataUrl: string;
}

function canvasToBlob(canvas: HTMLCanvasElement, type: string, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

export async function prepareImage(file: File): Promise<PreparedImage> {
  if (!ACCEPTED_TYPES.includes(file.type)) throw new Error("Use a JPEG, PNG, WebP or GIF image");
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();

  // WebP keeps transparency and compresses well; browsers that can't encode it fall back to JPEG.
  let blob = await canvasToBlob(canvas, "image/webp", 0.85);
  if (!blob || blob.type !== "image/webp") blob = await canvasToBlob(canvas, "image/jpeg", 0.85);
  if (!blob) throw new Error("Could not process this image");
  return { blob, dataUrl: await blobToDataUrl(blob) };
}

/**
 * A copy of the image with a labelled pixel grid, for a vision model to read positions from
 * (models place shapes far more accurately with one). Returns the copy and the grid spacing.
 */
export async function withGrid(dataUrl: string): Promise<{ dataUrl: string; step: number }> {
  const img = new Image();
  img.src = dataUrl;
  await img.decode();
  const { naturalWidth: w, naturalHeight: h } = img;
  const step = [25, 50, 100, 200, 250, 500].find((s) => Math.max(w, h) / s <= 12) ?? 500;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d")!;
  ctx.drawImage(img, 0, 0);
  const font = Math.max(11, Math.round(Math.max(w, h) / 70));
  ctx.lineWidth = Math.max(1, Math.round(font / 12));
  ctx.font = `600 ${font}px sans-serif`;
  ctx.textBaseline = "top";
  const line = (x1: number, y1: number, x2: number, y2: number) => {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  };
  const label = (text: string, x: number, y: number) => {
    const width = ctx.measureText(text).width;
    ctx.fillStyle = "rgb(0 0 0 / 0.7)";
    ctx.fillRect(x, y, width + 6, font + 4);
    ctx.fillStyle = "#ffff00";
    ctx.fillText(text, x + 3, y + 2);
  };
  ctx.strokeStyle = "rgb(255 255 0 / 0.55)";
  for (let x = step; x < w; x += step) line(x, 0, x, h);
  for (let y = step; y < h; y += step) line(0, y, w, y);
  for (let x = step; x < w; x += step) label(String(x), x + 2, 2);
  for (let y = step; y < h; y += step) label(String(y), 2, y + 2);
  const blob = await canvasToBlob(canvas, "image/jpeg", 0.85);
  if (!blob) throw new Error("Could not prepare the image");
  return { dataUrl: await blobToDataUrl(blob), step };
}
