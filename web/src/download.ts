/**
 * Save a fetched body as a file.
 *
 * `<a download>` cannot carry an Authorization header, and for a cookie client
 * it would work but still bypass the error handling every other call goes
 * through. Fetching the body and clicking an object URL keeps one path for
 * every request, and one place that reports a failure.
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoking immediately can cancel the download in some browsers; a tick is
  // enough and the object is small.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
