/*
 * The `accept` list for every scan and mark-scheme upload picker.
 *
 * PDF plus exactly the image formats the server takes: it refuses every other
 * image format (`lemely/io/scan_limits.py` `SCAN_IMAGE_FORMATS`: JPEG, PNG,
 * TIFF, WebP, BMP), so offering `image/*` let a user pick a GIF or HEIC only
 * for the upload to be refused. Kept in step with that allowlist by
 * `tests/unit/scanAccept.test.ts`.
 */
export const SCAN_ACCEPT = "application/pdf,image/jpeg,image/png,image/tiff,image/webp,image/bmp"
